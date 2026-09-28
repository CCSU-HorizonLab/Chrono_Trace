"""G7 端到端验收报告生成器:聚合样例预期、三链回放与 NLI 判定。

用法(仓库根目录)::

    python backend/scripts/g1_e2e_report.py

产出 ``docs/goals/g1-e2e-report.md``:任务识别对照、联系人隔离/任务契约/
隐私红线/发送清单一致性四项门禁检查、延迟与降级统计、忠实度汇总。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORT_VERSION = "g1-e2e-report-v1"
CHAINS = ("no_rag", "legacy", "g1")
_KNOWLEDGE_BLOCKS = {"relationship_policy", "contact_preferences", "contact_profile", "retrieval_memory", "relationship_signal"}


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def latest_results_by_chain(results_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """(sample_id, chain) → 最后一次 live 结果;无 live 时回落最后一次 dry。"""
    payload = _json(results_path.read_text(encoding="utf-8"), {})
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for run in payload.get("runs") or []:
        live = bool(run.get("live"))
        for result in run.get("results") or []:
            key = (result.get("sample_id") or "", result.get("chain") or "")
            if key not in latest or live:
                latest[key] = result
    return latest


def check_contact_isolation(samples: list[dict], results: dict[tuple[str, str], dict]) -> dict[str, Any]:
    """联系人隔离门禁:范围缺失/歧义/无效的样例,任何链路都不得注入知识。"""
    violations = []
    checked = 0
    for sample in samples:
        expected_scope = (sample.get("expected") or {}).get("scope") or "ok"
        if expected_scope == "ok":
            continue
        checked += 1
        for chain in CHAINS:
            result = results.get((sample["sample_id"], chain))
            if not result:
                continue
            manifest = result.get("manifest") or {}
            injected_facts = len(manifest.get("fact_ids") or [])
            knowledge_blocks = [b for b in manifest.get("blocks") or [] if b in _KNOWLEDGE_BLOCKS]
            if injected_facts or knowledge_blocks:
                violations.append({
                    "sample_id": sample["sample_id"],
                    "chain": chain,
                    "fact_ids": manifest.get("fact_ids"),
                    "knowledge_blocks": knowledge_blocks,
                })
    return {"checked": checked, "violations": violations, "pass": not violations}


def check_task_contract(samples: list[dict], results: dict[tuple[str, str], dict]) -> dict[str, Any]:
    """任务契约门禁:g1 链路的 task/output 必须与(AI 初判)预期一致。"""
    matches, mismatches = 0, []
    for sample in samples:
        expected = sample.get("expected") or {}
        if not expected.get("task"):
            continue
        result = results.get((sample["sample_id"], "g1"))
        if not result:
            continue
        routing = result.get("routing") or {}
        if routing.get("task") == expected["task"] and routing.get("output") == expected["output"]:
            matches += 1
        else:
            mismatches.append({
                "sample_id": sample["sample_id"],
                "expected": f"{expected['task']}/{expected['output']}",
                "actual": f"{routing.get('task')}/{routing.get('output')}",
            })
    return {"matches": matches, "mismatches": mismatches, "pass": not mismatches}


def check_manifest_badge_consistency(results: dict[tuple[str, str], dict]) -> dict[str, Any]:
    """发送清单一致性门禁:badge 的 referenced_count 必须等于实际发送的 document 数。"""
    violations = []
    checked = 0
    for (sample_id, chain), result in results.items():
        if chain != "g1":
            continue
        manifest = result.get("manifest") or {}
        badge = result.get("badge") or {}
        if not manifest or not badge:
            continue
        checked += 1
        if int(badge.get("referenced_count") or 0) != len(manifest.get("document_ids") or []):
            violations.append({
                "sample_id": sample_id,
                "badge_referenced": badge.get("referenced_count"),
                "manifest_documents": len(manifest.get("document_ids") or []),
            })
    return {"checked": checked, "violations": violations, "pass": not violations}


def check_privacy_redline(samples: list[dict], results: dict[tuple[str, str], dict], judgments_path: Path) -> dict[str, Any]:
    """隐私红线门禁:回放结果与判定文件中不得出现明文手机号/身份证;
    evidence_redacted_unusable 的排除原因必须留痕。"""
    import re

    phone_re = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    id_re = re.compile(r"\b\d{17}[\dXx]\b")
    leaks = []
    blobs = [json.dumps({f"{k[0]}|{k[1]}": v for k, v in results.items()}, ensure_ascii=False, default=str)]
    if judgments_path.exists():
        blobs.append(judgments_path.read_text(encoding="utf-8"))
    for blob in blobs:
        for match in phone_re.findall(blob):
            leaks.append({"type": "phone", "value_prefix": match[:3] + "****"})
            break
        for match in id_re.findall(blob):
            leaks.append({"type": "id_card", "value_prefix": match[:4] + "****"})
            break
    unusable_total = sum(
        1
        for result in results.values()
        for entry in (result.get("manifest") or {}).get("excluded") or []
        if entry.get("reason") == "evidence_redacted_unusable"
    )
    return {"leaks": leaks, "evidence_redacted_unusable": unusable_total, "pass": not leaks}


def latency_stats(results: dict[tuple[str, str], dict]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for chain in CHAINS:
        elapsed = [
            int(result.get("elapsed_ms") or 0)
            for (sample_id, c), result in results.items()
            if c == chain and result.get("output")
        ]
        if not elapsed:
            continue
        ordered = sorted(elapsed)
        stats[chain] = {
            "n": len(elapsed),
            "avg_ms": round(sum(elapsed) / len(elapsed)),
            "p50_ms": ordered[len(ordered) // 2],
            "max_ms": ordered[-1],
        }
    return stats


def build_report(samples_path: Path, results_path: Path, judgments_path: Path) -> str:
    samples_payload = _json(samples_path.read_text(encoding="utf-8"), {})
    samples = samples_payload.get("samples") or []
    results = latest_results_by_chain(results_path)
    nli = _json(judgments_path.read_text(encoding="utf-8"), {}) if judgments_path.exists() else {}
    meta = samples_payload.get("meta") or {}

    isolation = check_contact_isolation(samples, results)
    contract = check_task_contract(samples, results)
    consistency = check_manifest_badge_consistency(results)
    privacy = check_privacy_redline(samples, results, judgments_path)
    stats = latency_stats(results)

    lines: list[str] = []
    lines.append("# G1 端到端验收报告")
    lines.append("")
    lines.append(f"- 报告版本:`{REPORT_VERSION}`")
    lines.append(f"- 样例:`{samples_path.name}`({len(samples)} 条,装载器 {meta.get('loader_version')})")
    lines.append(f"- 预期标注:{(meta.get('expected_annotation') or {}).get('version')}(**AI 初判,人工终审前不作门禁**)")
    lines.append(f"- 模型:{(meta.get('active_model') or {}).get('name')} / {(meta.get('active_model') or {}).get('model_id')}")
    lines.append(f"- 基线代码:`{str(meta.get('code_commit'))[:12]}`")
    lines.append("")

    lines.append("## 门禁检查")
    lines.append("")
    lines.append("| 门禁 | 结果 | 明细 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| 联系人隔离 | {'✅ 通过' if isolation['pass'] else '❌ 失败'} | "
        f"检查 {isolation['checked']} 条范围受限样例 × 3 链路,违规 {len(isolation['violations'])} |"
    )
    lines.append(
        f"| 任务契约 | {'✅ 通过' if contract['pass'] else '❌ 失败'} | "
        f"g1 路由与预期一致 {contract['matches']}/{contract['matches'] + len(contract['mismatches'])} |"
    )
    lines.append(
        f"| 发送清单一致性 | {'✅ 通过' if consistency['pass'] else '❌ 失败'} | "
        f"badge=实际发送 {consistency['checked']}/{consistency['checked'] + len(consistency['violations'])} |"
    )
    lines.append(
        f"| 隐私红线 | {'✅ 通过' if privacy['pass'] else '❌ 失败'} | "
        f"明文泄漏 {len(privacy['leaks'])};evidence_redacted_unusable 留痕 {privacy['evidence_redacted_unusable']} |"
    )
    lines.append("")

    lines.append("## 任务识别三链对照(g1 live)")
    lines.append("")
    lines.append("| 样例 | 维度 | 预期 | no_rag | legacy | g1 | g1 输出摘要 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")

    def _task(result):
        routing = (result or {}).get("routing") or {}
        return f"{routing.get('task', '-')}/{routing.get('output', '-')}"

    for sample in samples:
        expected = sample.get("expected") or {}
        g1_result = results.get((sample["sample_id"], "g1")) or {}
        output = (g1_result.get("output") or {})
        summary = str(output.get("summary") or "-")[:30].replace("|", "\\|")
        speeches = output.get("speeches") or []
        output_brief = summary if not speeches else f"{summary} +{len(speeches)}话术"
        lines.append(
            f"| {sample['sample_id']} | {sample['dimension']} | "
            f"{expected.get('task', '-')}/{expected.get('output', '-')} | "
            f"{_task(results.get((sample['sample_id'], 'no_rag')))} | "
            f"{_task(results.get((sample['sample_id'], 'legacy')))} | "
            f"{_task(g1_result)} | {output_brief} |"
        )
    lines.append("")

    lines.append("## 延迟与稳定性(live)")
    lines.append("")
    lines.append("| 链路 | n | 平均 | p50 | 最大 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for chain, stat in stats.items():
        lines.append(f"| {chain} | {stat['n']} | {stat['avg_ms']}ms | {stat['p50_ms']}ms | {stat['max_ms']}ms |")
    errors = [
        {"sample_id": sid, "chain": chain, "error": result.get("error")}
        for (sid, chain), result in results.items()
        if result.get("error")
    ]
    lines.append("")
    lines.append(f"- 失败数:{len(errors)}")
    for error in errors[:10]:
        lines.append(f"  - {error['sample_id']}/{error['chain']}: {str(error['error'])[:120]}")
    lines.append("")

    label_counts = nli.get("label_counts") or {}
    lines.append("## 忠实度(NLI 初判,脱敏证据)")
    lines.append("")
    lines.append(f"- judge:{nli.get('judge_version')} / prompt `{nli.get('judge_prompt_version')}` / 模型 {(nli.get('model') or {}).get('model_id')}")
    lines.append(f"- 汇总:**entailed={label_counts.get('entailed', 0)}, contradicted={label_counts.get('contradicted', 0)}, unknown={label_counts.get('unknown', 0)}**")
    lines.append("- 说明:建议话术多为新措辞,unknown 占多数是预期分布;关键红线是 contradicted=0(输出不得与已发送事实冲突)。")
    lines.append("- 状态:`model_judged_pending_human`")
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    gates = {
        "联系人隔离": isolation["pass"],
        "任务契约": contract["pass"],
        "发送清单一致性": consistency["pass"],
        "隐私红线": privacy["pass"],
    }
    for gate, passed in gates.items():
        lines.append(f"- {'✅' if passed else '❌'} {gate}")
    lines.append("")
    lines.append("以上基于 AI 初判预期与模型判定;**人工终审通过前,本报告不作为 G1 完成依据**(上游文档第七节)。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--samples", default=str(root / "docs" / "goals" / "g1-baseline-samples.json"))
    parser.add_argument("--results", default=str(root / "docs" / "goals" / "g1-replay-results.json"))
    parser.add_argument("--judgments", default=str(root / "docs" / "goals" / "g1-nli-judgments.json"))
    parser.add_argument("--out", default=str(root / "docs" / "goals" / "g1-e2e-report.md"))
    args = parser.parse_args()

    report = build_report(Path(args.samples), Path(args.results), Path(args.judgments))
    out = Path(args.out)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n[G7 Report] 已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
