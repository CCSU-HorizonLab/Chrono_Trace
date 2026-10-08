"""确保 ONNX 导出所需源模型存在（缺失自动从 ModelScope 下载）。

构建机通常没运行过应用、没有本地模型——build 脚本调本脚本按需拉取源
模型再导出 fp16。产物已存在则全部跳过（常规增量构建秒过）。

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
        SENTIMENT_MODEL_DIRNAME,
        SENTIMENT_MODEL_REPO_ID,
        get_embedding_variant_info,
        get_model_root_dir,
    )

    root = get_model_root_dir()
    # 嵌入源模型跟随激活变体（spec 双平台均内置 bge；text2vec 仅按需）
    _emb = get_embedding_variant_info()
    jobs = [
        (_emb["repo_id"], root / _emb["dirname"]),
        (SENTIMENT_MODEL_REPO_ID, root / SENTIMENT_MODEL_DIRNAME),
    ]

    if all((d / "onnx" / "model.fp16.onnx").exists() for _, d in jobs):
        print("[模型] fp16 产物已存在，跳过下载与导出")
        return

    for repo_id, model_dir in jobs:
        if not ensure_source_model(repo_id, model_dir):
            raise SystemExit(f"模型获取失败: {repo_id}")

    if args.with_export:
        import subprocess

        subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "export_models_onnx.py")],
            check=True,
        )


if __name__ == "__main__":
    main()
