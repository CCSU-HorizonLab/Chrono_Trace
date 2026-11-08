"""模型 ONNX 导出 + int8 动态量化（开发机一次性脚本，不进发行包）。

产出（models/<name>/onnx/）：
  model.onnx        fp32 基准
  model.fp16.onnx   半精度（发行产物——int8 动态量化对该模型精度崩坏，实测 cosine 0.37-0.70，弃用）
  model.int8.onnx   分类器 int8 实验产物（--int8 显式开启，不发行——见下方结论）
  tokenizer/        原样复制 HF tokenizer 文件

分类器 int8 动态量化门槛验收（2026-11，i7-8665U，会话 1599 真实语料 3000 条，
对 fp16 生产基线）：吞吐 1.56× 达标，但 argmax 一致率 per-tensor 95.3% /
per-channel 94.1% / 排除末层 MatMul 仍 95.3%——精度损失分布于各层非尾部
集中，98% 门槛无路可达，弃用。复评时跑 export --int8 + verify --int8。

用法：
  python export_models_onnx.py                # 全部模型
  python export_models_onnx.py --only embedding
  python export_models_onnx.py --int8         # 分类器额外产 int8 实验件
"""
import argparse
import shutil
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.txt", "special_tokens_map.json")


def quantize_classifier_int8(fp32_path: Path, out_path: Path) -> None:
    """分类器 int8 动态量化（只量化 MatMul 权重，per-tensor——门槛验收
    变体实测里精度最好的一个，结论见模块 docstring，未达 98% 不发行）。"""
    from onnxruntime.quantization import quantize_dynamic, QuantType

    quantize_dynamic(
        str(fp32_path), str(out_path),
        weight_type=QuantType.QInt8,
        per_channel=False,
        op_types_to_quantize=["MatMul"],
    )
    print(f"[量化] int8 → {out_path} ({out_path.stat().st_size / 1e6:.0f}MB)")


def export_one(model_dir: Path, out_dir: Path, model_type: str, int8: bool = False) -> None:
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
    # 嵌入 int8（含 per-channel）实测崩坏（cosine 0.37-0.70）不可用，
    # 分类器 int8 也未达门槛（见模块 docstring）。
    # 精度择优（CPU 实测）：嵌入 fp32 快 32%——发行产物即上面导出的
    # fp32，跳过 fp16 转换；分类器 fp16 反快 14%——仍转换。
    # 2026-11 复测修正（i7-8665U / ORT 1.30 / CPU EP，生产同款推理形态）：
    # ① 分类器 fp32 反超 fp16（短文本 89.6 vs 74.0、长拼接 24.4 vs 16.7
    #    条/s，+21%/+46%）——旧「fp16 反快 14%」已环境反转；fp16 仍保留：
    #    包体积 205 vs 409MB，且 DML 设备模式下 fp16 原生对齐，切 fp32 待议
    # ② ORT transformers 离线优化器（onnxruntime.transformers.optimizer，
    #    opt_level 1/2/99）对本模型全档位负优化（短 -9~-15%、长 -17~-21%，
    #    argmax 全档 100% 无损）——运行时 load 已自动做基础/扩展融合，离线
    #    融合产物反而干扰 MLAS kernel 选择，弃用勿再试
    if model_type == "embedding":
        print("[量化] 嵌入产物为 fp32（CPU 实测更快），跳过 fp16 转换")
    else:
        import onnx
        from onnxconverter_common import float16

        fp16_path = out_dir / "model.fp16.onnx"
        fp16_model = float16.convert_float_to_float16(
            onnx.load(str(onnx_path)), keep_io_types=True
        )
        onnx.save(fp16_model, str(fp16_path))
        print(f"[量化] fp16 → {fp16_path} ({fp16_path.stat().st_size / 1e6:.0f}MB)")
        if int8:
            quantize_classifier_int8(onnx_path, out_dir / "model.int8.onnx")

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


def write_version_file_if_absent(model_dir: Path) -> None:
    """代际档案随权重走：model_version.json 已存在则不动（版本号属于权重
    本身——下载来的保留远端代际，本地蒸馏的保留训练时代际，导出动作
    无权改写）；缺失才按代码期望代际补档（本地蒸馏产物放置后首导出的
    常规路径）。ensure 脚本据此文件比对代际，防旧模型被误当新版导出"""
    import datetime
    import json

    from app.services.model_paths import SENTIMENT_MODEL_TAG

    version_file = model_dir / "model_version.json"
    if version_file.exists():
        print(f"[版本] 沿用既有代际档案: {version_file}")
        return
    version_file.write_text(
        json.dumps(
            {
                "version": SENTIMENT_MODEL_TAG,
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[版本] 补写代际档案 {version_file}（version={SENTIMENT_MODEL_TAG}）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["embedding", "sentiment"], default=None)
    parser.add_argument("--int8", action="store_true", help="分类器额外产 int8 实验件（门槛验收用）")
    args = parser.parse_args()

    from app.services.model_paths import (
        EMBEDDING_MODEL_DIRNAME, SENTIMENT_MODEL_DIRNAME, get_model_root_dir,
    )

    root = get_model_root_dir()
    jobs = [
        ("embedding", root / EMBEDDING_MODEL_DIRNAME, "embedding"),
        ("sentiment", root / SENTIMENT_MODEL_DIRNAME, "classification"),
    ]
    for name, model_dir, mtype in jobs:
        if args.only and name != args.only:
            continue
        if not (model_dir / "config.json").exists():
            print(
                f"[跳过] {name}: 无 HF 源模型（{model_dir}）——git 布局下 "
                "onnx 发行产物随仓库分发无需源；重生成走 regen_sentiment_model.py"
            )
            continue
        export_one(model_dir, model_dir / "onnx", mtype, int8=args.int8)
        if name == "sentiment":
            write_version_file_if_absent(model_dir)


if __name__ == "__main__":
    main()
