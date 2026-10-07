"""模型 ONNX 导出 + int8 动态量化（开发机一次性脚本，不进发行包）。

产出（models/<name>/onnx/）：
  model.onnx        fp32 基准
  model.fp16.onnx   半精度（发行产物——int8 动态量化对该模型精度崩坏，实测 cosine 0.37-0.70，弃用）
  tokenizer/        原样复制 HF tokenizer 文件

用法：
  python export_models_onnx.py                # 全部模型
  python export_models_onnx.py --only embedding
"""
import argparse
import shutil
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.txt", "special_tokens_map.json")


def export_one(model_dir: Path, out_dir: Path, model_type: str) -> None:
    import torch
    from transformers import AutoModel, AutoTokenizer

    out_dir.mkdir(parents=True, exist_ok=True)
    device = "cpu"

    class Wrapper(torch.nn.Module):
        """固定 forward 签名（新版 transformers 的 BertModel 位置参数与
        传统导出器不兼容）；嵌入输出 token 级隐状态，池化在推理侧做。"""

        def __init__(self, core, is_embedding: bool):
            super().__init__()
            self.core = core
            self.is_embedding = is_embedding

        def forward(self, input_ids, attention_mask, token_type_ids=None):
            out = self.core(
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
                return_dict=True,
            )
            if self.is_embedding:
                return out.last_hidden_state
            return out.logits

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    if model_type == "embedding":
        core = AutoModel.from_pretrained(str(model_dir)).to(device).eval()
    else:
        from transformers import AutoModelForSequenceClassification

        core = AutoModelForSequenceClassification.from_pretrained(str(model_dir)).to(device).eval()
    model = Wrapper(core, model_type == "embedding").eval()

    # 代表输入（动态 batch/seq 轴）
    dummy = tokenizer(
        ["测试中文句子导出", "第二句"],
        padding=True, truncation=True, max_length=128, return_tensors="pt",
    )
    input_names = ["input_ids", "attention_mask"] + (
        ["token_type_ids"] if "token_type_ids" in dummy else []
    )
    args = tuple(dummy[name] for name in input_names)

    onnx_path = out_dir / "model.onnx"
    dynamic_axes = {
        "input_ids": {0: "batch", 1: "seq"},
        "attention_mask": {0: "batch", 1: "seq"},
    }
    if "token_type_ids" in dummy:
        dynamic_axes["token_type_ids"] = {0: "batch", 1: "seq"}
    with torch.no_grad():
        torch.onnx.export(
            model, args, str(onnx_path),
            input_names=list(dynamic_axes.keys()),
            output_names=["last_hidden_state"] if model_type == "embedding" else ["logits"],
            dynamic_axes=dynamic_axes,
            opset_version=17,
            do_constant_folding=True,
            dynamo=False,  # 传统导出器：dynamo 导出的分类头形状信息与量化 shape inference 冲突
        )
    print(f"[导出] {model_dir.name} fp32 → {onnx_path} ({onnx_path.stat().st_size / 1e6:.0f}MB)")

    # fp16 半精度：对该 BERT 权重分布精度无损（实测 cosine=1.0）；
    # int8（含 per-channel）实测崩坏（cosine 0.37-0.70）不可用
    import onnx
    from onnxconverter_common import float16

    fp16_path = out_dir / "model.fp16.onnx"
    fp16_model = float16.convert_float_to_float16(
        onnx.load(str(onnx_path)), keep_io_types=True
    )
    onnx.save(fp16_model, str(fp16_path))
    print(f"[量化] fp16 → {fp16_path} ({fp16_path.stat().st_size / 1e6:.0f}MB)")

    # tokenizer 原样复制 + 生成 fast tokenizer.json（运行时 tokenizers 直读，
    # 无 vocab.txt-only 模型也免 transformers 依赖）
    tok_dir = out_dir / "tokenizer"
    tok_dir.mkdir(exist_ok=True)
    for name in TOKENIZER_FILES:
        src = model_dir / name
        if src.exists():
            shutil.copy2(src, tok_dir / name)
    if not (tok_dir / "tokenizer.json").exists():
        tokenizer.backend_tokenizer.save(str(tok_dir / "tokenizer.json"))
    print(f"[tokenizer] {len(list(tok_dir.iterdir()))} 个文件 → {tok_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["embedding", "sentiment"], default=None)
    args = parser.parse_args()

    from app.services.model_paths import (
        SENTIMENT_MODEL_DIRNAME, get_embedding_variant_info, get_model_root_dir,
    )

    # 嵌入导出跟随激活变体（默认 bge；text2vec 需产物时先在 settings 配置变体）
    _emb = get_embedding_variant_info()
    jobs = [
        ("embedding", get_model_root_dir() / _emb["dirname"], "embedding"),
        ("sentiment", get_model_root_dir() / SENTIMENT_MODEL_DIRNAME, "classification"),
    ]
    for name, model_dir, mtype in jobs:
        if args.only and name != args.only:
            continue
        if not model_dir.exists():
            print(f"[跳过] {name}: 模型目录不存在 {model_dir}")
            continue
        export_one(model_dir, model_dir / "onnx", mtype)


if __name__ == "__main__":
    main()
