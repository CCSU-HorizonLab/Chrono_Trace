"""情感模型再生成全链（模型生成与打包解耦的唯一入口）。

任何机器一条命令：本地聊天数据 + 指定 LLM 教师 → 打标 → 蒸馏训练 →
验收 → 安装为本地情感模型（HF 源 + ONNX 产物 + 代际档案）。打包
（build_release*）只消费 backend/data/models/ 目录，不再关心模型怎么来；
其他机器获取默认版走 ensure_models_for_export.py（ModelScope 拉取后本地
导出），本脚本只负责「重新做蒸馏」这条个性化路径。

依赖：torch/transformers/onnx 全栈（本仓库 .venv-model-export 即该环境）；
runtime venv（onnxruntime-only）跑不了训练，脚本启动即自检。

用法（打标三参必填；复用既有标签则只要 --skip-label）：
  python regen_sentiment_model.py \\
      --llm-base http://192.168.103.112:8004/v1 --llm-key token-abc123 \\
      --llm-model Qwen3.5-9B
  python regen_sentiment_model.py --skip-label          # 复用 v2_labels.jsonl
  可选：--train-n 60000 --epochs 4 --tag v3-ctx-20261108 --no-code-tag

流程：ensure_base（hf-mirror 拉 hfl/rbt3 基座）→ prepare（LLM 打标，
断点续传）→ train → evaluate（报告口径，旧模型缺席自动跳过）→ install
（换入 models/sentiment_3class）→ export（ONNX）→ 代际档案 + 同步
model_paths.SENTIMENT_MODEL_TAG（缓存重置与 ensure 代际门的锚点）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir / "scripts"))

REGEN_DEFAULT_TAG = "regen-ctx"


def check_env() -> None:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as exc:
        sys.exit(
            f"[环境] 缺 {exc.name}——本脚本需要 torch/transformers 全栈，\n"
            "       请在 .venv-model-export（或同等导出环境）中运行"
        )


def ensure_base(base_dir: Path) -> None:
    """hfl/rbt3 基座本地缺席则拉取（默认 hf-mirror，可 HF_ENDPOINT 覆盖）。"""
    if (base_dir / "config.json").exists():
        return
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from transformers import AutoModel, AutoTokenizer

    print(f"[基座] 拉取 hfl/rbt3 → {base_dir}")
    AutoTokenizer.from_pretrained("hfl/rbt3").save_pretrained(str(base_dir))
    AutoModel.from_pretrained("hfl/rbt3").save_pretrained(str(base_dir))


def install_student(model_dir: Path, base_dir: Path, student_path: Path, tag: str,
                    teacher: str) -> dict:
    """学生权重 → HF 格式换入模型目录（旧目录整删重建，ONNX 随后重导出）。"""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    ckpt = torch.load(student_path, weights_only=False)
    meta = ckpt.get("meta", {})
    student = AutoModelForSequenceClassification.from_pretrained(
        str(base_dir), num_labels=3)
    student.load_state_dict(ckpt["state_dict"])
    student.config._name_or_path = "hfl/rbt3"

    if model_dir.exists():
        print(f"[安装] 删除旧模型目录: {model_dir}")
        shutil.rmtree(model_dir)
    model_dir.mkdir(parents=True)
    student.save_pretrained(str(model_dir))
    AutoTokenizer.from_pretrained(str(base_dir)).save_pretrained(str(model_dir))

    version = {
        "version": tag,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "lineage": (
            f"regen 蒸馏：{teacher} 教师打标（本地数据）→ rbt3 学生"
            f"（留出一致率 {meta.get('agree', '?')}，epoch {meta.get('epoch', '?')}）；"
            f"{Path(__file__).name}，训练脚本 distill_sentiment_v2.py"
        ),
    }
    (model_dir / "model_version.json").write_text(
        json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")
    return version


def patch_code_tag(tag: str) -> None:
    """model_paths.SENTIMENT_MODEL_TAG 是缓存重置与 ensure 代际门的锚点——
    不改的话新模型会被本机 ensure 判为「代际落后」强制重拉覆盖。"""
    paths_py = backend_dir / "app" / "services" / "model_paths.py"
    src = paths_py.read_text(encoding="utf-8")
    new, n = re.subn(
        r'SENTIMENT_MODEL_TAG = "[^"]*"',
        f'SENTIMENT_MODEL_TAG = "{tag}"',
        src,
    )
    if n != 1:
        sys.exit(f"[代际] model_paths.py 中未找到唯一的 SENTIMENT_MODEL_TAG 赋值（匹配 {n} 处）")
    paths_py.write_text(new, encoding="utf-8")
    print(f"[代际] 已更新 model_paths.SENTIMENT_MODEL_TAG → {tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm-base", help="教师 LLM OpenAI 兼容端点（打标必填）")
    parser.add_argument("--llm-key", help="教师 LLM API key（打标必填）")
    parser.add_argument("--llm-model", help="教师 LLM 模型名（打标必填）")
    parser.add_argument("--skip-label", action="store_true",
                        help="复用 data/distill/v2_labels.jsonl（需已存在）")
    parser.add_argument("--train-n", type=int, default=60_000)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--lr", type=float, default=4e-5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--ce-weight", type=float, default=0.5)
    parser.add_argument("--tag", default=None,
                        help="代际标识（默认 regen-ctx-YYYYMMDD-HHMM）")
    parser.add_argument("--no-code-tag", action="store_true",
                        help="不改 model_paths.SENTIMENT_MODEL_TAG（默认自动改）")
    args = parser.parse_args()

    check_env()
    tag = args.tag or f"{REGEN_DEFAULT_TAG}-{time.strftime('%Y%m%d-%H%M')}"

    # LLM 配置经环境变量注入（distill_sentiment_v2 模块导入时读取）
    if not args.skip_label:
        missing = [k for k in ("--llm-base", "--llm-key", "--llm-model")
                   if not getattr(args, k.lstrip("-").replace("-", "_"))]
        if missing:
            sys.exit(f"[参数] 打标需要 {missing}（或 --skip-label 复用既有标签）")
        os.environ["CHRONO_V2_LLM_BASE"] = args.llm_base
        os.environ["CHRONO_V2_LLM_KEY"] = args.llm_key
        os.environ["CHRONO_V2_LLM_MODEL"] = args.llm_model

    import distill_sentiment_v2 as v2

    ensure_base(v2.BASE_DIR)

    if args.skip_label:
        if not v2.JSONL_PATH.exists():
            sys.exit(f"[数据] {v2.JSONL_PATH} 不存在——--skip-label 需要先打过标")
        print(f"[数据] 复用既有标签 {v2.JSONL_PATH}")
    else:
        v2.cmd_prepare()          # 增量断点续传：已标注 key 自动跳过

    if not v2.DATASET_PATH.exists():
        sys.exit(f"[数据] 缺 {v2.DATASET_PATH}——先完成打标（去掉 --skip-label）")
    v2.cmd_train(args.epochs, args.lr, args.batch_size, args.ce_weight)

    # 验收为报告口径（换代是否采纳由人拍板）；旧模型缺席/加载失败不阻断
    try:
        v2.cmd_evaluate(args.batch_size)
    except Exception as exc:
        print(f"[验收] 对比评估跳过（{exc}）——一致率见上方训练日志")

    version = install_student(v2.OLD_TEACHER_DIR, v2.BASE_DIR, v2.STUDENT_PATH,
                              tag, os.environ.get("CHRONO_V2_LLM_MODEL", "?"))
    print(f"[安装] {v2.OLD_TEACHER_DIR}（version={version['version']}）")

    subprocess.run(
        [sys.executable, str(backend_dir / "scripts" / "export_models_onnx.py"),
         "--only", "sentiment"],
        check=True,
    )

    if not args.no_code_tag:
        patch_code_tag(tag)
    print(
        "[完成] 模型已生成并安装。发布为默认版本：\n"
        "       python backend/scripts/push_sentiment_model.py --token <ModelScope令牌>\n"
        "       （未上传前，其他机器 ensure_models_for_export.py 会因远端旧代报错——设计行为）"
    )


if __name__ == "__main__":
    main()
