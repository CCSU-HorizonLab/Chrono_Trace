"""Evaluate the fixed memory-intent regression set without requiring an LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.realtime.memory_intent import detect_memory_intent  # noqa: E402


def _legacy_rule_intent(text: str) -> tuple[str, bool]:
    """Compatibility proxy for the pre-prototype detector used for A/B diagnostics."""
    compact = "".join(str(text or "").split())
    has_temporal = any(token in compact for token in ("上次", "上回", "之前", "以前", "那次", "刚刚", "上轮"))
    asks_detail = any(token in compact for token in ("啥", "什么", "哪", "谁", "记得", "不记得", "说过", "聊过", "提过"))
    has_actor = any(token in compact for token in ("她", "他", "对方", "我们", "ta", "TA"))
    reported = any(token in compact for token in ("说过", "聊过", "提过", "说的", "聊的", "提的"))
    referential = any(token in compact for token in ("那个", "那家", "那次", "这个", "这家"))
    direct_lookup = any(token in compact for token in ("找一下", "找下", "查一下", "查下", "翻一下", "翻下"))
    history = ((has_temporal and asks_detail and has_actor) or (has_actor and reported and asks_detail) or (has_actor and referential and reported) or (direct_lookup and (has_temporal or reported)))
    asks_strategy = any(token in compact for token in ("适合", "能不能", "可不可以", "该不该", "怎么", "如何"))
    relation_axis = any(token in compact for token in ("开玩笑", "玩笑", "调侃", "关系", "边界", "分寸", "相处", "沟通", "习惯", "风格"))
    relationship = asks_strategy and relation_axis and has_actor
    if relationship:
        return "relationship_context", True
    if history:
        return "memory_request", True
    return "none", False


def evaluate(samples: list[dict], detector=detect_memory_intent) -> dict:
    mode_correct = 0
    retrieve_correct = 0
    false_positive = 0
    false_negative = 0
    mismatches: list[dict] = []
    for sample in samples:
        intent = detector({"user_context": sample.get("user_context", "")})
        expected_mode = sample.get("expected_mode", "none")
        expected_retrieve = bool(sample.get("expected_retrieve", False))
        actual_retrieve = bool(intent.should_retrieve)
        if intent.mode == expected_mode:
            mode_correct += 1
        if actual_retrieve == expected_retrieve:
            retrieve_correct += 1
        if actual_retrieve and not expected_retrieve:
            false_positive += 1
        if expected_retrieve and not actual_retrieve:
            false_negative += 1
        if intent.mode != expected_mode or actual_retrieve != expected_retrieve:
            mismatches.append({"id": sample.get("id"), "expected_mode": expected_mode, "actual_mode": intent.mode, "expected_retrieve": expected_retrieve, "actual_retrieve": actual_retrieve, "reason": intent.reason})
    total = len(samples)
    positive = sum(bool(item.get("expected_retrieve")) for item in samples)
    negative = total - positive
    return {
        "samples": total,
        "mode_accuracy": round(mode_correct / total, 4) if total else 0.0,
        "retrieve_accuracy": round(retrieve_correct / total, 4) if total else 0.0,
        "recall": round((positive - false_negative) / positive, 4) if positive else 0.0,
        "false_positive_rate": round(false_positive / negative, 4) if negative else 0.0,
        "false_negative_rate": round(false_negative / positive, 4) if positive else 0.0,
        "no_hit_honesty_cases": sum(bool(item.get("no_hit_honest")) for item in samples),
        "mismatches": mismatches,
    }


def evaluate_ab(sample: list[dict]) -> dict:
    optimized = evaluate(sample)
    baseline = evaluate(sample, lambda context: type("LegacyIntent", (), {"mode": _legacy_rule_intent(context.get("user_context"))[0], "should_retrieve": _legacy_rule_intent(context.get("user_context"))[1], "reason": "legacy_rule_proxy"})())
    return {"baseline_legacy_rule_proxy": baseline, "optimized": optimized}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, default=ROOT / "docs/goals/rag-memory-intent-eval-samples.json")
    parser.add_argument("--check", action="store_true", help="return non-zero when a fixed expectation mismatches")
    args = parser.parse_args()
    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    report = evaluate_ab(samples)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.check and report["optimized"]["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
