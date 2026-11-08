"""上传情感模型到 ModelScope 仓库（发布为默认版本）。

只上传 HF 源模型文件 + model_version.json 代际档案（+README）——ONNX
产物由各机器 ensure_models_for_export.py 拉源模型后本地导出，不进远端。

用法（token 从 modelscope.cn 用户中心「访问令牌」获取，需仓库写权限）：
  python push_sentiment_model.py --token ms-xxxx
  MODELSCOPE_API_TOKEN=ms-xxxx python push_sentiment_model.py

依赖 modelscope 包（.venv-model-export 内置）。
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.model_paths import (  # noqa: E402
    SENTIMENT_MODEL_DIRNAME,
    get_model_root_dir,
)

#: 发布目标：自建 ModelScope 仓库（历史渠道，token 失效暂不可用）
SENTIMENT_MODEL_REPO_ID = "tingting0514/chrono-trace-sentiment"

#: 进远端的文件（HF 源格式 + 代际档案）；onnx/ 为各机器本地导出产物
PUSH_FILES = (
    "config.json",
    "pytorch_model.bin",
    "model.safetensors",
    "vocab.txt",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "model_version.json",
)


def stage(model_dir: Path) -> Path:
    staging = model_dir.parent / f"{SENTIMENT_MODEL_DIRNAME}_push_stage"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    copied = []
    for name in PUSH_FILES:
        src = model_dir / name
        if src.exists():
            shutil.copy2(src, staging / name)
            copied.append(name)
    if "config.json" not in copied or not (
        "pytorch_model.bin" in copied or "model.safetensors" in copied
    ):
        sys.exit(f"[上传] {model_dir} 缺源模型文件（config.json + 权重），中止")
    if "model_version.json" not in copied:
        sys.exit(
            "[上传] 缺 model_version.json 代际档案——先跑 regen_sentiment_model.py "
            "或 export_models_onnx.py 补档，否则 ensure 代际门无法识别远端版本"
        )

    version = json.loads((staging / "model_version.json").read_text(encoding="utf-8"))
    (staging / "README.md").write_text(
        "---\n"
        f"license: apache-2.0\n---\n"
        "# Chrono Trace 情感分类模型\n\n"
        f"- 代际：`{version.get('version')}`（model_version.json 为准）\n"
        f"- 更新：{version.get('updated_at')}\n"
        f"- 溯源：{version.get('lineage', '—')}\n\n"
        "3 类情感（neg/pos/neu，位置序），输入口径：前 3 条同会话文本上文与"
        "目标消息以 ` [SEP] ` 拼接（详见 Chrono Trace 仓库 sentiment_context）。\n\n"
        "```python\n"
        "from modelscope.hub.snapshot_download import snapshot_download\n"
        f"model_dir = snapshot_download('{SENTIMENT_MODEL_REPO_ID}')\n"
        "```\n",
        encoding="utf-8",
    )
    print(f"[上传] 暂存 {len(copied) + 1} 个文件 → {staging}")
    return staging


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--token", default=os.environ.get("MODELSCOPE_API_TOKEN"),
                        help="ModelScope 访问令牌（或环境变量 MODELSCOPE_API_TOKEN）")
    args = parser.parse_args()
    if not args.token:
        sys.exit("[上传] 缺 token：--token ms-xxxx 或 MODELSCOPE_API_TOKEN 环境变量")

    staging = stage(get_model_root_dir() / SENTIMENT_MODEL_DIRNAME)

    from modelscope.hub.api import HubApi

    api = HubApi()
    api.login(args.token)
    print(f"[上传] 推送 {staging} → {SENTIMENT_MODEL_REPO_ID}（约 150MB，耐心等待）")
    t0 = time.time()
    api.push_model(model_id=SENTIMENT_MODEL_REPO_ID, model_dir=str(staging))
    print(
        f"[上传] 完成（{time.time() - t0:.0f}s）→ "
        f"https://modelscope.cn/models/{SENTIMENT_MODEL_REPO_ID}\n"
        "其他机器 now: ensure_models_for_export.py 会拉到本版本并通过代际门"
    )


if __name__ == "__main__":
    main()
