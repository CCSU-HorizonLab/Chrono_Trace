"""情感分类器蒸馏 v2——LLM 教师（Qwen3.5-9B 本地服务）+ 大学生 rbt3（开发机脚本）。

v1（BERT 教师→MiniRBT-H256，脚本已删，结论存档于 git 历史）纯 KL 天花板
97.3%、KL+CE 97.34%，98% 门槛未达；教师 77% 样本标中性（影评语料微调的
中性化偏差），微信口语/表情/语气词大面积误标中性。

v2 换口径（用户已授权：自有数据、内网 LLM，试验不限隐私）：
  教师 = Qwen3.5-9B（qwen3.8-flash-next，llama-server /v1，enable_thinking
  必须关，否则 reasoning 吃满输出）；快测随机 40 条对旧教师一致率 72.5%，
  分歧抽样 LLM 判定全面更准（旧教师误标中性的语境依赖短句被正确改标
  neg/pos，分歧样例留档本地不引原文）。
  学生 = hfl/rbt3（3 层×768，38M，词表与教师同 21128 标准 BERT 词表）。
  上下文 = 打标/学生输入/生产推理三口径统一为「前 3 条会话上下文拼接」
  （ablation：6.2% 标签变化且大半变得更准；单条判断在语境依赖消息上
  原理性受限——按准确优先，接受输入变长的吞吐代价）。留出集同为 ctx
  实例，门槛 = 学生对 ctx 口径 LLM 标签的端到端复现。吞吐双基准：
  同输入对旧教师（纯模型加速比，门槛 ≥3×）+ 对现生产单条形态（实际
  冷启动变化，报告不设门槛——准确度的成本）。

三段式：
  python distill_sentiment_v2.py prepare   # 会话序采样 + LLM 打标（JSONL 断点续传，~8.5h）
  python distill_sentiment_v2.py train     # 软标签 KL + CE 混合训练 rbt3
  python distill_sentiment_v2.py evaluate  # 留出集 argmax 一致率≥98% + 吞吐≥3×（对旧教师 torch）

端点默认 http://192.168.103.112:8004/v1，env 覆盖：
  CHRONO_V2_LLM_BASE / CHRONO_V2_LLM_KEY / CHRONO_V2_LLM_MODEL
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

DISTILL_DIR = backend_dir / "data" / "distill"
BASE_DIR = DISTILL_DIR / "base_rbt3"      # hfl/rbt3 基座（hf-mirror 拉取存档）
JSONL_PATH = DISTILL_DIR / "v2_labels.jsonl"        # prepare 增量产物（断点续传）
DATASET_PATH = DISTILL_DIR / "v2_dataset.pt"
STUDENT_PATH = DISTILL_DIR / "v2_student.pt"
V1_STUDENT_PATH = DISTILL_DIR / "student.pt"
OLD_TEACHER_DIR = backend_dir / "data" / "models" / "sentiment_3class"

# 内网端点不入库：默认空，label 子命令须显式提供 CHRONO_V2_LLM_BASE/KEY
LLM_BASE = os.environ.get("CHRONO_V2_LLM_BASE", "")
LLM_KEY = os.environ.get("CHRONO_V2_LLM_KEY", "")
LLM_MODEL = os.environ.get("CHRONO_V2_LLM_MODEL", "Qwen3.5-9B")

MAX_LENGTH = 160          # ctx（3×60 字符≈90-120 token）+ 消息本体
TRAIN_N = 60_000
HOLDOUT_N = 8_000
SEED = 20261106
CTX_N = 3                 # 目标消息前文条数（同联系人）
CTX_CHARS = 60            # 每条前文截断
MAX_PER_TEXT = 2          # 同一文本最多采的实例数（控重复文本的 LLM 调用浪费）
CONCURRENCY = 16
MIN_CONF = 50             # LLM 自报置信低于此丢弃（噪声门）
LABELS = ("neg", "pos", "neu")     # 旧教师 id2label 真实顺序（realtime_sentiment_service.py:210）

PROMPT_CTX = """你是聊天消息情感标注员。结合对话上下文，判断「目标消息」发送者的情感极性。

三类定义：
- neg：负面（抱怨、生气、伤心、焦虑、讽刺贬损等）
- neu：中性（陈述事实、问答、安排事务、无明确情绪等）
- pos：正面（开心、感谢、关心、赞美、亲昵、期待等）

之前的对话（供参考，不是判断对象）：
{ctx}

目标消息：{msg}

只输出一行 JSON，不要任何其他内容：{{"label": "neg或neu或pos", "conf": 整数0到100}}"""

PROMPT_SOLO = """你是聊天消息情感标注员。判断下面这条微信消息的情感极性。

三类定义：
- neg：负面（抱怨、生气、伤心、焦虑、讽刺贬损等）
- neu：中性（陈述事实、问答、安排事务、无明确情绪等）
- pos：正面（开心、感谢、关心、赞美、亲昵、期待等）

消息：{msg}

只输出一行 JSON，不要任何其他内容：{{"label": "neg或neu或pos", "conf": 整数0到100}}"""


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def llm_label(prompt: str, retries: int = 3) -> dict | None:
    """单次打标：{label, conf}；解析失败/网络异常返回 None（由调用方重试）。"""
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0, "max_tokens": 64,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                LLM_BASE + "/chat/completions", data=body,
                headers={"Authorization": f"Bearer {LLM_KEY}",
                         "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                content = json.loads(r.read())["choices"][0]["message"]["content"]
            c = content.strip().removeprefix("```json").removesuffix("```").strip()
            obj = json.loads(c)
            lbl, conf = obj["label"], int(obj["conf"])
            if lbl in LABELS and 0 <= conf <= 100:
                return {"label": lbl, "conf": conf}
            return None      # 格式合法但内容越界：不重试（temperature=0 重试同样结果）
        except Exception:
            time.sleep(2)
    return None


def load_messages() -> list[tuple]:
    """DB 只读：全部文本消息按（联系人, 时间）序。"""
    import sqlite3

    conn = sqlite3.connect(f"file:{backend_dir / 'data/chrono_trace.db'}?mode=ro", uri=True)
    rows = conn.execute(
        """
        SELECT talker, timestamp, id, content FROM messages
        WHERE message_type = 1 AND LENGTH(content) BETWEEN 1 AND 500
        ORDER BY talker, timestamp, id
        """
    ).fetchall()
    conn.close()
    return rows


def build_samples(rows: list[tuple], rng: random.Random) -> tuple[list[dict], list[dict]]:
    """训练实例（带上下文，同文本≤MAX_PER_TEXT 个）+ 留出文本（单条，与训练文本不重叠）。"""
    keyed = []
    for k in range(CTX_N, len(rows)):
        talker, _, _, content = rows[k]
        if not isinstance(content, str) or not content.strip():
            continue
        ctx = [rows[j][3].replace("\n", " ")[:CTX_CHARS]
               for j in range(k - CTX_N, k)
               if rows[j][0] == talker and isinstance(rows[j][3], str) and rows[j][3].strip()]
        if len(ctx) < CTX_N:
            continue
        keyed.append({"key": f"{talker}|{rows[k][2]}", "text": content,
                      "ctx": " / ".join(ctx)})
    rng.shuffle(keyed)

    train, seen = [], Counter()
    for s in keyed:
        if len(train) >= TRAIN_N:
            break
        if seen[s["text"]] >= MAX_PER_TEXT:
            continue
        seen[s["text"]] += 1
        train.append(s)

    # 留出：ctx 实例（与训练/生产同口径），文本与训练不重叠；反向遍历——
    # 训练已消费 shuffle 序前段的大部分文本配额
    holdout, h_texts = [], set(seen)
    for s in reversed(keyed):
        if len(holdout) >= HOLDOUT_N:
            break
        if s["text"] in h_texts:
            continue
        h_texts.add(s["text"])
        holdout.append({"key": f"holdctx|{s['key']}", "text": s["text"], "ctx": s["ctx"]})
    return train, holdout


def cmd_prepare() -> None:
    """LLM 打标：训练与留出均带上下文（三口径统一）；JSONL 断点续传，最后合并 .pt。"""
    rng = random.Random(SEED)
    rows = load_messages()
    log(f"消息总数 {len(rows)}")
    train, holdout = build_samples(rows, rng)
    log(f"采样：训练 {len(train)}（前{CTX_N}条上文，同文本≤{MAX_PER_TEXT}） / "
        f"留出 {len(holdout)}（同 ctx 口径，文本与训练不重叠）")

    done: set[str] = set()
    if JSONL_PATH.exists():
        with open(JSONL_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass
        log(f"断点续传：已有 {len(done)} 条标签")

    pending = [s for s in train + holdout if s["key"] not in done]
    log(f"待打标 {len(pending)} 条（并发 {CONCURRENCY}，预估 "
        f"{len(pending) / 2.3 / 3600:.1f}h）")

    t0 = time.perf_counter()
    n_ok = n_bad = 0
    with open(JSONL_PATH, "a", encoding="utf-8") as out:
        def one(s: dict):
            if s["ctx"]:
                prompt = PROMPT_CTX.format(ctx=s["ctx"], msg=s["text"])
            else:
                prompt = PROMPT_SOLO.format(msg=s["text"])
            return s, llm_label(prompt)

        # ThreadPoolExecutor.map 保序；逐个落盘，中断最多丢当前批
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            for idx, (s, res) in enumerate(pool.map(one, pending), 1):
                if res is None or res["conf"] < MIN_CONF:
                    n_bad += 1
                    continue
                out.write(json.dumps({"key": s["key"], "text": s["text"],
                                      "ctx": s["ctx"], **res}, ensure_ascii=False) + "\n")
                n_ok += 1
                if idx % 500 == 0:
                    out.flush()
                    rate = idx / (time.perf_counter() - t0)
                    log(f"  {idx}/{len(pending)}  ok={n_ok} 丢={n_bad}  "
                        f"{rate:.1f}条/s  ETA {(len(pending)-idx)/rate/3600:.1f}h")

    log(f"打标完成：ok={n_ok} 丢弃={n_bad}（含 conf<{MIN_CONF}）→ {JSONL_PATH}")

    # 合并 .pt（训练软标签矩阵 + 留出硬标签）
    samples: dict[str, dict] = {}
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                samples[rec["key"]] = rec
            except Exception:
                pass
    train_recs = [samples[s["key"]] for s in train if s["key"] in samples]
    hold_recs = [samples[s["key"]] for s in holdout if s["key"] in samples]
    log(f"有效样本：训练 {len(train_recs)} / 留出 {len(hold_recs)}")

    import torch

    torch.save({
        "train": [{"text": r["text"], "ctx": r["ctx"],
                   "label": LABELS.index(r["label"]), "conf": r["conf"]}
                  for r in train_recs],
        "holdout": [{"text": r["text"], "ctx": r["ctx"],
                     "label": LABELS.index(r["label"]), "conf": r["conf"]}
                    for r in hold_recs],
        "meta": {"model": LLM_MODEL, "seed": SEED, "ctx_n": CTX_N,
                 "min_conf": MIN_CONF, "labels": LABELS},
    }, DATASET_PATH)
    dist = Counter(r["label"] for r in train_recs)
    log(f"训练标签分布 {dict(dist)} → {DATASET_PATH} "
        f"({DATASET_PATH.stat().st_size/1e6:.1f}MB)")


def student_input(rec: dict) -> str:
    """学生/生产同口径输入：前文 [SEP] 目标消息（打标 prompt 同源拼接）。"""
    if rec.get("ctx"):
        return f"{rec['ctx']} [SEP] {rec['text']}"
    return rec["text"]


def soft_target(label: int, conf: int):
    """(label, conf) → 软分布：主类 conf/100（下限 0.60），余量均分两类。

    LLM 自报 conf 是粗校准（快测 neg 85-95 / neu 85-95 常见），构造只求
    保序与可解释；KL 蒸馏的温度机制在此之上再软化。"""
    import torch

    p_true = max(0.60, conf / 100.0)
    p = torch.full((3,), (1.0 - p_true) / 2)
    p[label] = p_true
    return p


def cmd_train(epochs: int, lr: float, batch_size: int, ce_weight: float) -> None:
    """软标签 KL + CE 混合（v1 结论：CE 0.5 对症互换型分歧，97.34 vs 纯 KL 97.28）。"""
    import torch
    import torch.nn.functional as F
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    data = torch.load(DATASET_PATH, weights_only=False)
    train, holdout = data["train"], data["holdout"]
    log(f"训练 {len(train)} / 留出 {len(holdout)}")

    tok = AutoTokenizer.from_pretrained(str(BASE_DIR), local_files_only=True)
    student = AutoModelForSequenceClassification.from_pretrained(
        str(BASE_DIR), num_labels=3)
    torch.set_num_threads(4)

    T = 2.0
    opt = torch.optim.AdamW(student.parameters(), lr=lr, weight_decay=0.01)
    total = (len(train) + batch_size - 1) // batch_size
    steps = total * epochs
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: max(0.05, 1 - s / max(1, steps)))

    rng = random.Random(SEED)
    # 长度聚批：随机批填充均长≈160（几乎批批顶格），聚批后≈70（实测输入 p50=56），
    # CPU 提速 ~2.3×；批序乱序保留随机性，批内样本固定不影响蒸馏（软标签无组内结构）
    texts = [student_input(r) for r in train]
    by_len = sorted(range(len(train)), key=lambda i: len(texts[i]))
    batches = [by_len[i:i + batch_size] for i in range(0, len(by_len), batch_size)]
    best_agree = -1.0
    for epoch in range(epochs):
        rng.shuffle(batches)
        running, step = 0.0, 0
        t0 = time.perf_counter()
        for idx in batches:
            batch = tok([texts[i] for i in idx], padding=True,
                        truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
            s_logits = student(**batch).logits
            targets = torch.stack([soft_target(train[i]["label"], train[i]["conf"])
                                   for i in idx])
            hard = torch.tensor([train[i]["label"] for i in idx])
            # 教师只有概率无 logit：温度软化 = p^(1/T) 归一（v1 有 logit 用 softmax(tl/T)）。
            # 首版误写 targets/T——未归一化 loss 为负且教师侧未软化，实测已修
            t_soft = targets.pow(1.0 / T)
            t_soft = t_soft / t_soft.sum(dim=-1, keepdim=True)
            loss = F.kl_div(F.log_softmax(s_logits / T, dim=-1), t_soft,
                            reduction="batchmean") * (T * T)
            if ce_weight > 0:
                loss = loss + ce_weight * F.cross_entropy(s_logits, hard)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            running += loss.item()
            if step % 500 == 0:
                rate = step * batch_size / (time.perf_counter() - t0)
                log(f"  epoch{epoch} step{step}/{steps} loss={running/500:.4f} "
                    f"{rate:.0f} 条/s")
                running = 0.0
        agree = quick_eval(student, tok, holdout)
        log(f"epoch{epoch} 留出集（单条口径）argmax 一致率 {agree:.4f}")
        torch.save({"state_dict": student.state_dict(),
                    "config": student.config.to_dict(),
                    "meta": {"epoch": epoch, "agree": agree}},
                   DISTILL_DIR / f"v2_student_epoch{epoch}.pt")
        if agree > best_agree:
            best_agree = agree
            torch.save({"state_dict": student.state_dict(),
                        "config": student.config.to_dict(),
                        "meta": {"epoch": epoch, "agree": agree}}, STUDENT_PATH)
    log(f"最佳学生（{best_agree:.4f}）→ {STUDENT_PATH}")


def quick_eval(student, tok, holdout: list[dict], batch_size: int = 64) -> float:
    """留出集（ctx 输入，与生产同口径）学生对 LLM 标签 argmax 一致率（长度聚批）。"""
    import numpy as np
    import torch

    inputs = [student_input(h) for h in holdout]
    keyed = sorted(range(len(inputs)), key=lambda i: len(inputs[i]))
    preds = [0] * len(holdout)
    with torch.no_grad():
        for bi in range(0, len(keyed), batch_size):
            idx = keyed[bi:bi + batch_size]
            batch = tok([inputs[i] for i in idx], padding=True,
                        truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
            out = student(**batch).logits.argmax(-1).tolist()
            for j, i in enumerate(idx):
                preds[i] = out[j]
    gold = [h["label"] for h in holdout]
    return float((np.array(preds) == np.array(gold)).mean())


def cmd_evaluate(batch_size: int) -> int:
    """门槛：留出集（ctx 口径）argmax≥98% 且学生 torch 吞吐≥3×（对旧教师同输入）。

    吞吐双基准：r_model=学生(ctx)/旧教师(ctx) 同输入比纯模型加速（门槛）；
    r_prod=学生(ctx)/旧教师(单条)=对现生产形态的实际变化（输入变长的成本，
    报告不设门槛——按准确优先的决策记录在案）。"""
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    data = torch.load(DATASET_PATH, weights_only=False)
    holdout = data["holdout"]
    inputs = [student_input(h) for h in holdout]      # ctx 拼接（生产形态）
    texts = [h["text"] for h in holdout]              # 单条（旧教师生产形态）
    gold = np.array([h["label"] for h in holdout])
    tok = AutoTokenizer.from_pretrained(str(BASE_DIR), local_files_only=True)
    torch.set_num_threads(4)

    ckpt = torch.load(STUDENT_PATH, weights_only=False)
    student = AutoModelForSequenceClassification.from_pretrained(
        str(BASE_DIR), num_labels=3).eval()
    student.load_state_dict(ckpt["state_dict"])
    old_teacher = AutoModelForSequenceClassification.from_pretrained(
        str(OLD_TEACHER_DIR), local_files_only=True).eval()

    def timed(model, tag: str, seq: list[str]):
        keyed = sorted(range(len(seq)), key=lambda i: len(seq[i]))
        best, preds = None, None
        for _ in range(2):
            preds = [0] * len(seq)
            t0 = time.perf_counter()
            with torch.no_grad():
                for bi in range(0, len(keyed), batch_size):
                    idx = keyed[bi:bi + batch_size]
                    batch = tok([seq[i] for i in idx], padding=True,
                                truncation=True, max_length=MAX_LENGTH,
                                return_tensors="pt")
                    out = model(**batch).logits.argmax(-1).tolist()
                    for j, i in enumerate(idx):
                        preds[i] = out[j]
            el = time.perf_counter() - t0
            best = el if best is None else min(best, el)
        rate = len(seq) / best
        log(f"  {tag}: {best:.2f}s  {rate:.1f} 条/s")
        return np.array(preds), rate

    log(f"== v2 门槛（留出 {len(inputs)} 条，ctx 口径，对 LLM 标签）==")
    p_student, r_student = timed(student, "学生 rbt3（ctx 输入）", inputs)
    p_old_ctx, r_old_ctx = timed(old_teacher, "旧教师（ctx 输入）", inputs)
    _, r_old_prod = timed(old_teacher, "旧教师（单条=现生产）", texts)
    agree = float((p_student == gold).mean())
    r_model = r_student / r_old_ctx
    r_prod = r_student / r_old_prod
    log(f"  对 LLM 标签一致率={agree:.4f}  模型加速比={r_model:.2f}x  "
        f"对现生产={r_prod:.2f}x  学生对旧教师一致率={float((p_student == p_old_ctx).mean()):.4f}")
    gates = {"对LLM标签一致率≥0.98": agree >= 0.98,
             "模型加速比(同输入)≥3.0": r_model >= 3.0}
    for name, ok in gates.items():
        log(f"  {'✅' if ok else '❌'} {name}")
    all_pass = all(gates.values())
    log("[+] 达标（export ONNX + 生产形态复验 + 与用户确认切换）" if all_pass
        else "[!] 未达标（样本量/温度/epoch 可调，或保守采纳记录在案）")
    return 0 if all_pass else 1


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    p2 = sub.add_parser("train")
    p2.add_argument("--epochs", type=int, default=4)
    p2.add_argument("--lr", type=float, default=4e-5)
    p2.add_argument("--batch-size", type=int, default=32)
    p2.add_argument("--ce-weight", type=float, default=0.5)
    p3 = sub.add_parser("evaluate")
    p3.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    if args.cmd == "prepare":
        cmd_prepare()
    elif args.cmd == "train":
        cmd_train(args.epochs, args.lr, args.batch_size, args.ce_weight)
    else:
        sys.exit(cmd_evaluate(args.batch_size))


if __name__ == "__main__":
    main()
