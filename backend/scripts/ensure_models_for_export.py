"""确保 ONNX 发行产物就绪（构建机前置检查）。

- 情感模型：发行产物（onnx/model.fp16.onnx + model_version.json）随 git
  仓库分发，本脚本只做存在性 + 代际校验，缺/落后即报错指路（git pull /
  regen_sentiment_model.py），不从 ModelScope 拉自建历史仓库。
- 嵌入模型：源模型缺失时从 ModelScope（官方仓库）按需下载。

用法：
  python ensure_models_for_export.py                # 只补源模型
  python ensure_models_for_export.py --with-export  # 补源模型 + 执行导出
"""
import argparse
import shutil
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


def _sentiment_generation_stale(model_dir: Path, expected_tag: str) -> bool:
    """本地情感模型代际是否落后：model_version.json 缺失 / 无 version 键 /
    与代码期望不符，均视为来源不明或过期（真值只有权重自己知道）。"""
    version_file = model_dir / "model_version.json"
    if not version_file.exists():
        return True
    try:
        import json

        version = json.loads(version_file.read_text(encoding="utf-8")).get("version")
    except Exception:
        return True
    return version != expected_tag


def ensure_source_model(repo_id: str, model_dir: Path) -> bool:
    """源 torch 模型存在即真；缺失则从 ModelScope 下载（temp 目录落盘后原子换入）。"""
    if (model_dir / "config.json").exists():
        print(f"[模型] 源模型已存在: {model_dir.name}")
        return True

    print(f"[模型] 从 ModelScope 下载 {repo_id} → {model_dir} ...")
    from modelscope.hub.snapshot_download import snapshot_download

    temp_dir = model_dir.parent / f"{model_dir.name}_dl_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.parent.mkdir(parents=True, exist_ok=True)
    # 参数口径与应用内 ModelManager 一致（cache_dir 放元数据、local_dir 落内容）
    snapshot_download(repo_id, cache_dir=str(temp_dir.parent), local_dir=str(temp_dir))

    if not (temp_dir / "config.json").exists():
        print(f"[模型] 下载内容校验失败（缺 config.json）: {repo_id}")
        return False
    if model_dir.exists():
        shutil.rmtree(model_dir, ignore_errors=True)
    shutil.move(str(temp_dir), str(model_dir))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-export", action="store_true", help="补齐后执行 ONNX 导出")
    args = parser.parse_args()

    from app.services.model_paths import (
        EMBEDDING_MODEL_DIRNAME,
        EMBEDDING_MODEL_REPO_ID,
        SENTIMENT_MODEL_DIRNAME,
        SENTIMENT_MODEL_TAG,
        get_model_root_dir,
    )

    root = get_model_root_dir()

    # 情感模型随 git 仓库分发（onnx 发行产物 + model_version.json 入库）：
    # 产物缺失或代际落后（version ≠ model_paths.SENTIMENT_MODEL_TAG）时
    # 指路 git pull / regen，不从 ModelScope 拉——远端历史仓库是旧代，
    # 拉了也是错模型（v2 代码配 v1 权重静默劣化）
    sentiment_dir = root / SENTIMENT_MODEL_DIRNAME
    sentiment_product = sentiment_dir / "onnx" / "model.fp16.onnx"
    if not sentiment_product.exists():
        raise SystemExit(
            f"情感模型发行产物缺失 {sentiment_product}：git pull 拉最新仓库，"
            "或本机跑 regen_sentiment_model.py 重生成"
        )
    if _sentiment_generation_stale(sentiment_dir, SENTIMENT_MODEL_TAG):
        raise SystemExit(
            f"本地情感模型代际落后于代码期望（{SENTIMENT_MODEL_TAG}）："
            "git pull 拉最新仓库（模型随仓库分发），"
            "或 regen_sentiment_model.py 本机重生成"
        )

    # 嵌入源模型从 ModelScope 官方仓库按需补；产物判据按发行文件名
    # （嵌入定死 fp32=model.onnx），与 build_release*/spec 收集口径一致
    emb_dir = root / EMBEDDING_MODEL_DIRNAME
    if not (emb_dir / "onnx" / "model.onnx").exists():
        if not (emb_dir / "config.json").exists():
            print(f"[模型] 嵌入源模型缺失，从 ModelScope 下载 {EMBEDDING_MODEL_REPO_ID} ...")
        if not ensure_source_model(EMBEDDING_MODEL_REPO_ID, emb_dir):
            raise SystemExit(f"模型获取失败: {EMBEDDING_MODEL_REPO_ID}")
    else:
        print("[模型] 发行产物就绪（情感=git 分发 + 嵌入产物在位），无需下载导出")

    if args.with_export:
        import subprocess

        subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "export_models_onnx.py")],
            check=True,
        )


if __name__ == "__main__":
    main()
