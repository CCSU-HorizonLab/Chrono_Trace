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
        SENTIMENT_MODEL_DIRNAME,
        SENTIMENT_MODEL_REPO_ID,
        get_embedding_variant_info,
        get_model_root_dir,
    )

    root = get_model_root_dir()
    # 嵌入源模型跟随激活变体（spec 双平台均内置 bge；text2vec 仅按需）
    _emb = get_embedding_variant_info()
    # 跳过判据按各模型发行产物文件名（嵌入定死 fp32=model.onnx，分类器
    # fp16=model.fp16.onnx），与 build_release*/spec 收集口径一致——此前
    # 一律查 fp16 文件名，text2vec 时代旧产物会让脚本误判「已存在跳过」，
    # bge 永远不被导出
    jobs = [
        (_emb["repo_id"], root / _emb["dirname"], "model.onnx"),
        (SENTIMENT_MODEL_REPO_ID, root / SENTIMENT_MODEL_DIRNAME, "model.fp16.onnx"),
    ]

    # 情感模型代际门：发行产物存在≠代际正确——旧模型产物齐全时文件名
    # 判据会放行，v2 代码配 v1 权重静默劣化。model_version.json 的
    # version 与代码期望（model_paths.SENTIMENT_MODEL_TAG）不符或档案
    # 缺失，均视为来源不明/过期，强制重新获取
    from app.services.model_paths import SENTIMENT_MODEL_TAG

    sentiment_dir = root / SENTIMENT_MODEL_DIRNAME
    sentiment_stale = _sentiment_generation_stale(sentiment_dir, SENTIMENT_MODEL_TAG)

    if (
        all((d / "onnx" / product).exists() for _, d, product in jobs)
        and not sentiment_stale
    ):
        print("[模型] 发行产物已存在且代际一致，跳过下载与导出")
        return
    if sentiment_stale:
        print(f"[模型] 本地情感模型代际落后于代码期望（{SENTIMENT_MODEL_TAG}），强制重新获取")

    for repo_id, model_dir, _product in jobs:
        if model_dir == sentiment_dir and sentiment_stale:
            print(f"[模型] 删除代际落后的本地目录: {model_dir}")
            shutil.rmtree(model_dir, ignore_errors=True)
        if not ensure_source_model(repo_id, model_dir):
            raise SystemExit(f"模型获取失败: {repo_id}")

    # 远端代际复核：ModelScope 还是旧代时到此为止——继续导出只会给旧
    # 权重盖上新代际章（export 的补档逻辑只在档案缺失时动笔），必须
    # 先上传新版再跑本脚本
    if _sentiment_generation_stale(sentiment_dir, SENTIMENT_MODEL_TAG):
        raise SystemExit(
            f"ModelScope 仓库 {SENTIMENT_MODEL_REPO_ID} 仍是旧代情感模型"
            f"（期望 {SENTIMENT_MODEL_TAG}）：请先将新版模型连同其 "
            "model_version.json 上传后重试"
        )

    if args.with_export:
        import subprocess

        subprocess.run(
            [sys.executable, str(backend_dir / "scripts" / "export_models_onnx.py")],
            check=True,
        )


if __name__ == "__main__":
    main()
