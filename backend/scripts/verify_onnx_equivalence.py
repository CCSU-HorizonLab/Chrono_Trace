"""ONNX int8 等价性验收——阶段 A 的门槛（不达标则回退 fp16 方案）。

门槛（对 ≥2000 条真实消息）：
  1. 嵌入余弦相似度（torch vs onnx-int8）mean ≥ 0.995 且 p5 ≥ 0.98
  2. 相邻文本对相似度的「< 0.5」边界判定一致率 ≥ 99%（会话切分阈值的代理）
  3. 情感三分类 argmax 一致率 ≥ 98%

用法：
  python verify_onnx_equivalence.py [--sample 2000] [--fp32]（跑 fp32 对照）
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def sample_texts(sample: int) -> list[str]:
    """真实消息采样：短消息与长文本（近似发言单元）混合。"""
    from app.db.connection import get_db

    conn = get_db()
    rows = conn.execute(
        """
        SELECT content FROM messages
        WHERE message_type = 1 AND LENGTH(content) BETWEEN 2 AND 200
        ORDER BY RANDOM() LIMIT ?
        """,
        (sample,),
    ).fetchall()
    texts = [r[0] if isinstance(r[0], str) else r[0].decode("utf-8", "ignore") for r in rows]
    # 拼接相邻消息模拟发言单元长文本（嵌入的主要消费形态）
    units = ["。".join(texts[i:i + 4]) for i in range(0, max(0, len(texts) - 4), 4)]
    return [t for t in (texts + units) if t and t.strip()]


class OnnxEmbedder:
    """ONNX int8 + HF tokenizers：mask 加权 mean pooling + L2 归一（与
    sentence-transformers 的 text2vec 前向等价）。"""

    def __init__(self, model_path: Path, tokenizer_dir: Path):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        if (tokenizer_dir / "tokenizer.json").exists():
            from tokenizers import Tokenizer

            self.tokenizer = Tokenizer.from_file(str(tokenizer_dir / "tokenizer.json"))
        else:
            # 慢速 tokenizer（vocab.txt）→ transformers 自动转 fast，取底层句柄
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(tokenizer_dir), local_files_only=True
            ).backend_tokenizer
        self.tokenizer.enable_truncation(max_length=128)
        self.input_names = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        vectors = []
        for start in range(0, len(texts), batch_size):
            chunk = [t if t.strip() else "。" for t in texts[start:start + batch_size]]
            enc = self.tokenizer.encode_batch(chunk)
            maxlen = max(len(e.ids) for e in enc)
            ids = np.zeros((len(enc), maxlen), dtype=np.int64)
            mask = np.zeros((len(enc), maxlen), dtype=np.int64)
            token_type = np.zeros((len(enc), maxlen), dtype=np.int64)
            for i, e in enumerate(enc):
                ids[i, :len(e.ids)] = e.ids
                mask[i, :len(e.attention_mask)] = e.attention_mask
                if "token_type_ids" in self.input_names and e.type_ids:
                    token_type[i, :len(e.type_ids)] = e.type_ids
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = token_type
            hidden = self.session.run(None, feeds)[0]  # [b, seq, 768]
            m = mask[:, :, None].astype(hidden.dtype)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            vectors.append(pooled / np.clip(norms, 1e-9, None))
        return np.concatenate(vectors)


class OnnxClassifier:
    def __init__(self, model_path: Path):
        import onnxruntime as ort

        self.session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )

    def argmax(self, texts: list[str], tokenizer) -> np.ndarray:
        preds = []
        input_names = {i.name for i in self.session.get_inputs()}
        for start in range(0, len(texts), 32):
            chunk = [t if t.strip() else "。" for t in texts[start:start + 32]]
            enc = tokenizer.encode_batch(chunk)
            maxlen = max(len(e.ids) for e in enc)
            ids = np.zeros((len(enc), maxlen), dtype=np.int64)
            mask = np.zeros((len(enc), maxlen), dtype=np.int64)
            ttype = np.zeros((len(enc), maxlen), dtype=np.int64)
            for i, e in enumerate(enc):
                ids[i, :len(e.ids)] = e.ids
                mask[i, :len(e.attention_mask)] = e.attention_mask
                if e.type_ids:
                    ttype[i, :len(e.type_ids)] = e.type_ids
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in input_names:
                feeds["token_type_ids"] = ttype
            logits = self.session.run(None, feeds)[0]
            preds.append(np.argmax(logits, axis=1))
        return np.concatenate(preds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=2000)
    parser.add_argument("--fp32", action="store_true", help="跑 fp32 onnx 对照")
    args = parser.parse_args()

    from app.db.connection import DatabaseConnection

    DatabaseConnection.initialize(str(Path(__file__).parent.parent / "data/chrono_trace.db"))

    from app.services.model_paths import (
        EMBEDDING_MODEL_DIRNAME, SENTIMENT_MODEL_DIRNAME, get_model_root_dir,
    )

    root = get_model_root_dir()
    emb_dir = root / EMBEDDING_MODEL_DIRNAME / "onnx"
    sent_dir = root / SENTIMENT_MODEL_DIRNAME / "onnx"
    suffix = "model.onnx" if args.fp32 else "model.fp16.onnx"

    texts = sample_texts(args.sample)
    print(f"[采样] {len(texts)} 条文本（消息+拼接单元）")

    # ---- torch 侧（sentence-transformers，与生产同路径）
    from app.services.analysis.sentiment_service import SentimentService

    svc = SentimentService()
    svc._load_embedding_model()
    t0 = time.time()
    torch_vecs = np.array(svc._get_embeddings_batch(texts, batch_size=32))
    t_torch = time.time() - t0

    # ---- onnx 侧
    onnx_emb = OnnxEmbedder(emb_dir / suffix, emb_dir / "tokenizer")
    t0 = time.time()
    onnx_vecs = onnx_emb.encode(texts)
    t_onnx = time.time() - t0

    cos = (torch_vecs * onnx_vecs).sum(1)
    print(f"\n== 嵌入等价（{suffix}）==")
    print(f"  cosine mean={cos.mean():.5f}  p5={np.percentile(cos, 5):.5f}  min={cos.min():.5f}")
    print(f"  耗时 torch={t_torch:.1f}s  onnx={t_onnx:.1f}s  ({len(texts)} 条)")

    # ---- 相邻对边界一致率（会话切分阈值的代理）
    sim_t = (torch_vecs[:-1] * torch_vecs[1:]).sum(1)
    sim_o = (onnx_vecs[:-1] * onnx_vecs[1:]).sum(1)
    agree = ((sim_t < 0.5) == (sim_o < 0.5)).mean()
    max_gap = float(np.abs(np.sort(sim_t) - np.sort(sim_o)).max())
    print(f"== 边界判定（<0.5）==")
    print(f"  一致率={agree:.4f}  相似度最大漂移={max_gap:.4f}")

    # ---- 情感分类一致率
    from transformers import AutoModelForSequenceClassification, AutoTokenizer as AT
    import torch

    sent_texts = [t for t in texts if len(t) <= 120][: min(1000, len(texts))]
    tok_pt = AT.from_pretrained(str(root / SENTIMENT_MODEL_DIRNAME), local_files_only=True)
    clf_pt = AutoModelForSequenceClassification.from_pretrained(
        str(root / SENTIMENT_MODEL_DIRNAME), local_files_only=True).eval()
    preds_pt = []
    for start in range(0, len(sent_texts), 32):
        batch = tok_pt(sent_texts[start:start + 32], padding=True, truncation=True,
                       max_length=128, return_tensors="pt")
        with torch.no_grad():
            preds_pt.append(clf_pt(**batch).logits.argmax(-1).numpy())
    preds_pt = np.concatenate(preds_pt)

    onnx_clf = OnnxClassifier(sent_dir / suffix)
    preds_onnx = onnx_clf.argmax(sent_texts, onnx_emb.tokenizer)
    clf_agree = (preds_pt == preds_onnx).mean()
    print(f"== 情感三分类 ==")
    print(f"  argmax 一致率={clf_agree:.4f}  ({len(sent_texts)} 条)")

    # ---- 门槛判定
    gates = {
        "嵌入余弦 mean≥0.995": cos.mean() >= 0.995,
        "嵌入余弦 p5≥0.98": np.percentile(cos, 5) >= 0.98,
        "边界一致率≥0.99": agree >= 0.99,
        "分类一致率≥0.98": clf_agree >= 0.98,
    }
    print("\n== 门槛 ==")
    all_pass = True
    for name, ok in gates.items():
        print(f"  {'✅' if ok else '❌'} {name}")
        all_pass &= ok
    print(f"\n{'[+] 全部通过' if all_pass else '[!] 未达标（考虑 fp16 或全精度 onnx）'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
