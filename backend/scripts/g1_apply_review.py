"""G0 审核回灌:把审核 agent 的作答应用回样例文件并重新生成 e2e 报告。

用法(仓库根目录)::

    python backend/scripts/g1_apply_review.py --answers docs/goals/g1-review-answers.json

行为:

- ``verdict=agree``  → ``expected_annotation=agent_reviewed_confirmed``;
- ``verdict=override`` → 用作答给出的 task/output/needs 覆写 expected,
  ``expected_annotation=agent_reviewed_overridden``,保留原判定于
  ``expected_superseded`` 供追溯;
- 缺答/无效作答的样例保持 ``ai_first_pass_pending_human``,报告里单列。

回灌后自动重跑 ``g1_e2e_report.build_report`` 刷新门禁结论。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

APPLY_VERSION = "g1-apply-review-v1"
VALID_VERDICTS = {"agree", "override"}
VALID_OUTPUTS = {"direct_answer", "suggestion_card", "answer_with_speeches"}


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def apply_answers(samples_payload: dict[str, Any], answers_payload: dict[str, Any], reviewer: str) -> dict[str, int]:
    answers = {a.get("sample_id"): a for a in answers_payload.get("answers") or [] if isinstance(a, dict)}
    stats = {"confirmed": 0, "overridden": 0, "skipped": 0, "missing": 0}
    for sample in samples_payload.get("samples") or []:
        sid = sample.get("sample_id") or ""
        answer = answers.get(sid)
        if not answer:
            stats["missing"] += 1
            continue
        verdict = str(answer.get("verdict") or "").strip().lower()
        if verdict not in VALID_VERDICTS:
            stats["skipped"] += 1
            continue
        issues = [str(i) for i in (answer.get("issues") or []) if str(i).strip()]
        if verdict == "agree":
            sample["expected_annotation"] = "agent_reviewed_confirmed"
            sample["review"] = {
                "reviewer": reviewer,
                "verdict": "agree",
                "issues": issues,
                "severity": answer.get("severity"),
                "applied_at": int(time.time()),
            }
            stats["confirmed"] += 1
            continue
        # override:必须给出合法 task/output
        task = str(answer.get("expected_task") or "").strip()
        output = str(answer.get("expected_output") or "").strip()
        if not task or output not in VALID_OUTPUTS:
            stats["skipped"] += 1
            continue
        sample["expected_superseded"] = sample.get("expected")
        expected = dict(sample.get("expected") or {})
        expected["task"] = task
        expected["output"] = output
        if isinstance(answer.get("knowledge_needs"), list):
            expected["knowledge_needs"] = [str(n) for n in answer["knowledge_needs"]]
        expected["annotation_basis"] = f"agent override: {('; '.join(issues)) or '未给理由'}"
        sample["expected"] = expected
        sample["expected_annotation"] = "agent_reviewed_overridden"
        sample["review"] = {
            "reviewer": reviewer,
            "verdict": "override",
            "issues": issues,
            "severity": answer.get("severity"),
            "applied_at": int(time.time()),
        }
        stats["overridden"] += 1
    meta = samples_payload.setdefault("meta", {})
    meta["expected_annotation"] = {
        "version": APPLY_VERSION,
        "annotated_at": int(time.time()),
        "reviewer": reviewer,
        "confirmed": stats["confirmed"],
        "overridden": stats["overridden"],
        "pending": stats["missing"] + stats["skipped"],
        "note": "更强审核 agent 终审;override 保留原判定于 expected_superseded",
    }
    return stats


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", default=str(root / "docs" / "goals" / "g1-review-answers.json"))
    parser.add_argument("--samples", default=str(root / "docs" / "goals" / "g1-baseline-samples.json"))
    parser.add_argument("--results", default=str(root / "docs" / "goals" / "g1-replay-results.json"))
    parser.add_argument("--judgments", default=str(root / "docs" / "goals" / "g1-nli-judgments.json"))
    parser.add_argument("--report-out", default=str(root / "docs" / "goals" / "g1-e2e-report.md"))
    parser.add_argument("--reviewer", default="stronger-agent")
    args = parser.parse_args()

    answers_path = Path(args.answers)
    if not answers_path.exists():
        print(f"[G0 Apply] 作答文件不存在: {answers_path}(先用 template 让审核 agent 填写)")
        return 1
    samples_payload = _json(Path(args.samples).read_text(encoding="utf-8"), None)
    answers_payload = _json(answers_path.read_text(encoding="utf-8"), None)
    if not samples_payload or not answers_payload:
        print("[G0 Apply] 样例或作答文件解析失败")
        return 1

    stats = apply_answers(samples_payload, answers_payload, args.reviewer)
    Path(args.samples).write_text(json.dumps(samples_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[G0 Apply] 确认 {stats['confirmed']} / 改判 {stats['overridden']} / "
        f"跳过 {stats['skipped']} / 未答 {stats['missing']} → {args.samples}"
    )

    from g1_e2e_report import build_report

    report = build_report(Path(args.samples), Path(args.results), Path(args.judgments))
    Path(args.report_out).write_text(report, encoding="utf-8")
    print(f"[G0 Apply] e2e 报告已刷新 → {args.report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
