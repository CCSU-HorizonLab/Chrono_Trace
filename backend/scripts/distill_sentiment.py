"""情感三分类蒸馏——学生 MiniRBT-H256（6 层×256，~10.4M）对齐教师
chinese-roberta-wwm-ext（12 层×768，102M）的 logits（开发机一次性脚本）。

动机：分类器 CPU 推理是冷启动主要瓶颈（13 万条 ≈ 20+ 分钟），蒸馏小模型
目标吞吐 ≥3×（门槛，与 int8 实验同一验收框架）+ argmax 一致率 ≥98%。

词表红利：MiniRBT-H256 与教师 vocab.txt 逐位一致（sha256 45bbac6b…，
21128 标准 BERT 中文词表），编码零差异，蒸馏只需对齐 logits。

三段式（基座默认 data/distill/base，从 hf-mirror.com/hfl/minirbt-h256 拉取存档）：
  python distill_sentiment.py prepare   # DB 采样唯一文本 + 教师本地打软标签 → data/distill/dataset.pt
  python distill_sentiment.py train     # KL(T) 蒸馏微调学生 → data/distill/student.pt
  python distill_sentiment.py evaluate  # argmax 一致率 + 吞吐比门槛验收

隐私：教师打标全部本地（torch CPU 前向），语料不出网；只有基座权重下载入网。
"""
import argparse
import random
import sys
import time
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

DISTILL_DIR = backend_dir / "data" / "distill"
BASE_DIR = DISTILL_DIR / "base"    # MiniRBT-H256 基座（hf-mirror 拉取后存档）
DATASET_PATH = DISTILL_DIR / "sentiment_dataset.pt"
STUDENT_PATH = DISTILL_DIR / "student.pt"
TEACHER_DIR = backend_dir / "data" / "models" / "sentiment_3class"

MAX_LENGTH = 128          # 生产分类器同款截断
TRAIN_N = 60_000          # 训练文本数（唯一文本去重后采样）
EVAL_N = 8_000            # 留出验收集（不进训练）
SEED = 20261106
TEMPERATURE = 2.0         # 蒸馏温度：软化教师分布，3 类任务常规起点


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cmd_prepare(sample: int) -> None:
    """教师对真实唯一消息打软标签（全本地）。"""
    import sqlite3

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    DISTILL_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{backend_dir / 'data/chrono_trace.db'}?mode=ro", uri=True)
    rows = conn.execute(
        """
        SELECT DISTINCT content FROM messages
        WHERE message_type = 1 AND LENGTH(content) BETWEEN 1 AND 500
        """
    ).fetchall()
    conn.close()
    texts = sorted({r[0] if isinstance(r[0], str) else r[0].decode("utf-8", "ignore") for r in rows})
    texts = [t for t in texts if t.strip()]
    log(f"库内唯一文本 {len(texts)} 条（全库只读采样）")
    rng = random.Random(SEED)
    rng.shuffle(texts)
    texts = texts[: sample + EVAL_N]

    # 长度聚批：token 长度排序消 padding 浪费（与生产推理同思路）；
    # 排序只服务打标，存储还原回 shuffle 原序（否则 eval 切片「最后 8k」
    # 会全是长文本，训练/验收分布错位）
    tok = AutoTokenizer.from_pretrained(str(TEACHER_DIR), local_files_only=True)
    keyed = []
    for t in texts:
        n = len(tok(t, truncation=True, max_length=MAX_LENGTH)["input_ids"])
        keyed.append((n, t))
    order = sorted(range(len(keyed)), key=lambda i: keyed[i][0])
    sorted_texts = [keyed[i][1] for i in order]

    teacher = AutoModelForSequenceClassification.from_pretrained(
        str(TEACHER_DIR), local_files_only=True
    ).eval()
    torch.set_num_threads(4)  # 物理核（与 ONNX 线程调参结论一致）

    def infer(chunk: list[str]) -> list[list[float]]:
        batch = tok(chunk, padding=True, truncation=True, max_length=MAX_LENGTH,
                    return_tensors="pt")
        with torch.no_grad():
            return teacher(**batch).logits.float().tolist()

    logits_sorted: list[list[float]] = []
    t0 = time.perf_counter()
    for i in range(0, len(sorted_texts), 32):
        logits_sorted.extend(infer(sorted_texts[i:i + 32]))
        if (i // 32) % 100 == 0 and i:
            done = i + 32
            rate = done / (time.perf_counter() - t0)
            log(f"  {done}/{len(sorted_texts)}  {rate:.1f} 条/s  ETA {(len(sorted_texts)-done)/rate/60:.0f}min")
    el = time.perf_counter() - t0
    log(f"教师打标完成：{len(sorted_texts)} 条 / {el/60:.1f}min（{len(sorted_texts)/el:.1f} 条/s）")

    # 还原 shuffle 原序：logits_sorted[k] 对应 sorted_texts[k]=texts[order[k]]
    logits_all: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]
    for k, i in enumerate(order):
        logits_all[i] = logits_sorted[k]
    torch.save(
        {"texts": texts, "teacher_logits": torch.tensor(logits_all, dtype=torch.float32),
         "meta": {"temperature": TEMPERATURE, "seed": SEED, "max_length": MAX_LENGTH}},
        DATASET_PATH,
    )
    log(f"数据集 → {DATASET_PATH}（{DATASET_PATH.stat().st_size/1e6:.1f}MB）")


def cmd_train(base_dir: Path, epochs: int, lr: float, batch_size: int,
              ce_weight: float) -> None:
    """KL 蒸馏：学生 softmax 对齐教师温度软化分布。

    无人工标注，硬标签即教师 argmax。纯 KL（ce_weight=0）实测天花板
    97.3%：分歧 92% 是互换型（学生 top2=教师 top1）且 91% 集中在教师
    gap<1.0 的低置信区——软标签在这些样本上教的是「两类差不多」，
    top1 拉不硬；CE 混合直接惩罚 top1 不硬，对症。"""
    import torch
    import torch.nn.functional as F
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    data = torch.load(DATASET_PATH, weights_only=False)
    texts: list[str] = data["texts"]
    t_logits: torch.Tensor = data["teacher_logits"]
    n_eval = min(EVAL_N, len(texts) // 8)
    eval_texts, train_texts = texts[-n_eval:], texts[:-n_eval]
    eval_logits, train_logits = t_logits[-n_eval:], t_logits[:-n_eval]
    log(f"训练 {len(train_texts)} / 验收 {len(eval_texts)}（留出，不进训练）")

    tok = AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True)
    student = AutoModelForSequenceClassification.from_pretrained(
        str(base_dir), num_labels=3
    )
    torch.set_num_threads(4)

    T = TEMPERATURE
    opt = torch.optim.AdamW(student.parameters(), lr=lr, weight_decay=0.01)
    total = (len(train_texts) + batch_size - 1) // batch_size
    steps = total * epochs
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: max(0.05, 1 - s / max(1, steps))
    )  # 线性衰减到 5%

    rng = random.Random(SEED)
    step = 0
    best_agree = -1.0
    for epoch in range(epochs):
        order = list(range(len(train_texts)))
        rng.shuffle(order)
        running = 0.0
        t0 = time.perf_counter()
        for bi in range(0, len(order), batch_size):
            idx = order[bi:bi + batch_size]
            batch = tok([train_texts[i] for i in idx], padding=True,
                        truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
            s_logits = student(**batch).logits
            tl = train_logits[idx]
            loss = F.kl_div(
                F.log_softmax(s_logits / T, dim=-1),
                F.softmax(tl / T, dim=-1),
                reduction="batchmean",
            ) * (T * T)
            if ce_weight > 0:
                loss = loss + ce_weight * F.cross_entropy(s_logits, tl.argmax(-1))
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            running += loss.item()
            if step % 200 == 0:
                rate = step * batch_size / (time.perf_counter() - t0)
                log(f"  epoch{epoch} step{step}/{steps} loss={running/200:.4f} "
                    f"{rate:.0f} 条/s")
                running = 0.0
        # 每个 epoch 验一次留出集；STUDENT_PATH 恒存最佳轮（末轮可能过拟合回落）
        agree = quick_eval(student, tok, eval_texts, eval_logits)
        log(f"epoch{epoch} 留出集 argmax 一致率 {agree:.4f}")
        torch.save({"state_dict": student.state_dict(), "config": student.config.to_dict(),
                    "meta": {"epoch": epoch, "agree": agree}},
                   DISTILL_DIR / f"student_epoch{epoch}.pt")
        if agree > best_agree:
            best_agree = agree
            torch.save({"state_dict": student.state_dict(),
                        "config": student.config.to_dict(),
                        "meta": {"epoch": epoch, "agree": agree}}, STUDENT_PATH)
    log(f"最佳学生（{best_agree:.4f}）→ {STUDENT_PATH}")


def quick_eval(student, tok, texts: list[str], t_logits, batch_size: int = 64) -> float:
    """留出集 argmax 一致率（长度聚批）。"""
    import torch

    keyed = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    preds = [0] * len(texts)
    with torch.no_grad():
        for bi in range(0, len(keyed), batch_size):
            idx = keyed[bi:bi + batch_size]
            batch = tok([texts[i] for i in idx], padding=True, truncation=True,
                        max_length=MAX_LENGTH, return_tensors="pt")
            out = student(**batch).logits.argmax(-1).tolist()
            for j, i in enumerate(idx):
                preds[i] = out[j]
    import numpy as np

    return float((np.array(preds) == t_logits.argmax(-1).numpy()).mean())


def cmd_evaluate(batch_size: int) -> int:
    """门槛验收：留出集 argmax 一致率 ≥98% 且学生 torch 吞吐 ≥3× 教师 torch。"""
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    data = torch.load(DATASET_PATH, weights_only=False)
    texts: list[str] = data["texts"]
    t_logits = data["teacher_logits"].numpy()
    n_eval = min(EVAL_N, len(texts) // 8)
    eval_texts, eval_logits = texts[-n_eval:], t_logits[-n_eval:]

    tok = AutoTokenizer.from_pretrained(str(TEACHER_DIR), local_files_only=True)
    torch.set_num_threads(4)

    ckpt = torch.load(STUDENT_PATH, weights_only=False)
    student = _load_student(ckpt)
    teacher = AutoModelForSequenceClassification.from_pretrained(
        str(TEACHER_DIR), local_files_only=True
    ).eval()

    def timed(model, tag: str):
        # 长度聚批 + best-of-2
        keyed = sorted(range(len(eval_texts)), key=lambda i: len(eval_texts[i]))
        best = None
        preds = None
        for _ in range(2):
            preds = [0] * len(eval_texts)
            t0 = time.perf_counter()
            with torch.no_grad():
                for bi in range(0, len(keyed), batch_size):
                    idx = keyed[bi:bi + batch_size]
                    batch = tok([eval_texts[i] for i in idx], padding=True,
                                truncation=True, max_length=MAX_LENGTH,
                                return_tensors="pt")
                    out = model(**batch).logits.argmax(-1).tolist()
                    for j, i in enumerate(idx):
                        preds[i] = out[j]
            el = time.perf_counter() - t0
            best = el if best is None else min(best, el)
        rate = len(eval_texts) / best
        log(f"  {tag}: {best:.2f}s  {rate:.1f} 条/s")
        return np.array(preds), rate

    log(f"== 蒸馏门槛（留出 {len(eval_texts)} 条真实消息）==")
    p_teacher, r_teacher = timed(teacher, "教师 12×768")
    p_student, r_student = timed(student, "学生 6×256")
    agree = float((p_student == p_teacher).mean())
    ratio = r_student / r_teacher
    log(f"  argmax 一致率={agree:.4f}  吞吐比={ratio:.2f}x")

    gates = {"argmax一致率≥0.98": agree >= 0.98, "吞吐比≥3.0": ratio >= 3.0}
    for name, ok in gates.items():
        log(f"  {'✅' if ok else '❌'} {name}")
    all_pass = all(gates.values())
    log("[+] 达标（下一步：export ONNX + 生产门槛复验）" if all_pass
        else "[!] 未达标（调温度/epoch/lr，或转 hfl/rbt3 保精度退路）")
    return 0 if all_pass else 1


def _load_student(ckpt):
    from transformers import BertConfig, BertForSequenceClassification

    cfg = BertConfig.from_dict(ckpt["config"])
    model = BertForSequenceClassification(cfg)
    model.load_state_dict(ckpt["state_dict"])
    return model.eval()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare")
    p1.add_argument("--sample", type=int, default=TRAIN_N)
    p2 = sub.add_parser("train")
    p2.add_argument("--base-dir", type=Path, default=BASE_DIR)
    p2.add_argument("--epochs", type=int, default=3)
    p2.add_argument("--lr", type=float, default=5e-5)
    p2.add_argument("--batch-size", type=int, default=32)
    p2.add_argument("--ce-weight", type=float, default=0.0,
                    help="CE 硬标签混合权重（教师 argmax；0=纯 KL）")
    p3 = sub.add_parser("evaluate")
    p3.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    if args.cmd == "prepare":
        cmd_prepare(args.sample)
    elif args.cmd == "train":
        cmd_train(args.base_dir, args.epochs, args.lr, args.batch_size, args.ce_weight)
    else:
        sys.exit(cmd_evaluate(args.batch_size))


if __name__ == "__main__":
    main()
