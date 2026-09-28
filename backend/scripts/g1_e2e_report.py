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
    """联系人隔离门禁:范围缺失/歧义/无效的样例,任何链路都不得注入知识。

    审核返工 4:应查未查(样例×链路缺结果)记为 incomplete,不得默认通过。
    """
    violations = []
    missing = []
    checked = 0
    for sample in samples:
        expected_scope = (sample.get("expected") or {}).get("scope") or "ok"
        if expected_scope == "ok":
            continue
        checked += 1
        for chain in CHAINS:
            result = results.get((sample["sample_id"], chain))
            if not result:
                missing.append({"sample_id": sample["sample_id"], "chain": chain})
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
    status = "incomplete" if missing else ("fail" if violations else "ok")
    return {
        "checked": checked,
        "violations": violations,
        "missing": missing,
        "status": status,
        "pass": status == "ok",
    }


def check_task_contract(samples: list[dict], results: dict[tuple[str, str], dict]) -> dict[str, Any]:
    """任务契约门禁:g1 链路的 task/output 必须与(AI 初判)预期一致。

    审核返工 4:路由标签一致只是必要条件——输出契约也要成立:
    要话术的必须有非空 speeches;直答的必须有非空 reply。
    """
    matches, mismatches, missing, output_violations = 0, [], [], []
    for sample in samples:
        expected = sample.get("expected") or {}
        if not expected.get("task"):
            continue
        result = results.get((sample["sample_id"], "g1"))
        if not result:
            missing.append({"sample_id": sample["sample_id"], "chain": "g1"})
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
        output = result.get("output") or {}
        wants_speeches = str(routing.get("output")) != "direct_answer"
        if wants_speeches and not [s for s in output.get("speeches") or [] if str(s).strip()]:
            output_violations.append({"sample_id": sample["sample_id"], "issue": "要话术但 speeches 为空"})
        if not wants_speeches and not str(output.get("reply") or "").strip():
            output_violations.append({"sample_id": sample["sample_id"], "issue": "直答但 reply 为空"})
    status = (
        "incomplete" if missing
        else ("fail" if mismatches or output_violations else "ok")
    )
    return {
        "matches": matches,
        "mismatches": mismatches,
        "output_violations": output_violations,
        "missing": missing,
        "status": status,
        "pass": status == "ok",
    }


def check_manifest_badge_consistency(samples: list[dict], results: dict[tuple[str, str], dict]) -> dict[str, Any]:
    """发送清单一致性门禁:badge 的 referenced_count 必须等于实际发送的 document 数。"""
    violations = []
    missing = []
    checked = 0
    for sample in samples:
        result = results.get((sample["sample_id"], "g1"))
        manifest = (result or {}).get("manifest") or {}
        badge = (result or {}).get("badge") or {}
        if not result or not manifest or not badge:
            missing.append({"sample_id": sample["sample_id"], "chain": "g1"})
            continue
        checked += 1
        if int(badge.get("referenced_count") or 0) != len(manifest.get("document_ids") or []):
            violations.append({
                "sample_id": sample["sample_id"],
                "badge_referenced": badge.get("referenced_count"),
                "manifest_documents": len(manifest.get("document_ids") or []),
            })
    status = "incomplete" if missing or checked == 0 else ("fail" if violations else "ok")
    return {
        "checked": checked,
        "violations": violations,
        "missing": missing,
        "status": status,
        "pass": status == "ok",
    }


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
    has_results = bool(results)
    status = "incomplete" if (not has_results or leaks) else "ok"
    if leaks:
        status = "fail"
    return {
        "leaks": leaks,
        "evidence_redacted_unusable": unusable_total,
        "status": status,
        "pass": status == "ok",
    }


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


def _outputs_fingerprint(results: dict[Any, dict]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for key in sorted(results, key=str):
        result = results[key]
        if isinstance(key, tuple):
            sid, chain = str(key[0]), str(key[1])
        else:
            sid, chain = str(key), "g1"
        digest.update(f"{sid}|{chain}|".encode("utf-8"))
        digest.update(json.dumps(result.get("output") or {}, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _gate_mark(check: dict[str, Any]) -> str:
    status = check.get("status") or ("ok" if check.get("pass") else "fail")
    return {"ok": "✅ 通过", "fail": "❌ 失败"}.get(status, "⚠️ 不完整(有应查未查)")


def build_report(samples_path: Path, results_path: Path, judgments_path: Path) -> str:
    samples_payload = _json(samples_path.read_text(encoding="utf-8"), {})
    samples = samples_payload.get("samples") or []
    results = latest_results_by_chain(results_path)
    nli = _json(judgments_path.read_text(encoding="utf-8"), {}) if judgments_path.exists() else {}
    meta = samples_payload.get("meta") or {}

    isolation = check_contact_isolation(samples, results)
    contract = check_task_contract(samples, results)
    consistency = check_manifest_badge_consistency(samples, results)
    privacy = check_privacy_redline(samples, results, judgments_path)
    stats = latency_stats(results)

    lines: list[str] = []
    lines.append("# G1 端到端验收报告")
    lines.append("")
    lines.append(f"- 报告版本:`{REPORT_VERSION}`")
    lines.append(f"- 样例:`{samples_path.name}`({len(samples)} 条,装载器 {meta.get('loader_version')})")
    annotation = meta.get("expected_annotation") or {}
    lines.append(
        f"- 预期标注:{annotation.get('version')}"
        f"({annotation.get('reviewer') or 'AI 初判'};确认 {annotation.get('confirmed', '-')}/"
        f"改判 {annotation.get('overridden', '-')};**人工终审前不作门禁**)"
    )
    lines.append(f"- 模型:{(meta.get('active_model') or {}).get('name')} / {(meta.get('active_model') or {}).get('model_id')}")
    lines.append(f"- 基线代码:`{str(meta.get('code_commit'))[:12]}`")
    lines.append("")

    lines.append("## 门禁检查")
    lines.append("")
    lines.append("| 门禁 | 结果 | 明细 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| 联系人隔离 | {_gate_mark(isolation)} | "
        f"检查 {isolation['checked']} 条范围受限样例 × 3 链路,违规 {len(isolation['violations'])},"
        f"缺结果 {len(isolation.get('missing') or [])} |"
    )
    lines.append(
        f"| 任务契约 | {_gate_mark(contract)} | "
        f"g1 路由与预期一致 {contract['matches']}/{contract['matches'] + len(contract['mismatches'])};"
        f"输出契约违规 {len(contract.get('output_violations') or [])}(要话术无话术/直答无 reply) |"
    )
    for violation in (contract.get("output_violations") or [])[:6]:
        lines.append(f"  - {violation['sample_id']}: {violation['issue']}")
    lines.append(
        f"| 发送清单一致性 | {_gate_mark(consistency)} | "
        f"badge=实际发送 {consistency['checked']}/{consistency['checked'] + len(consistency['violations'])},"
        f"缺结果 {len(consistency.get('missing') or [])} |"
    )
    lines.append(
        f"| 隐私红线 | {_gate_mark(privacy)} | "
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
    unparsed = sum(
        1
        for entry in nli.get("judgments") or []
        for judgment in entry.get("judgments") or []
        if judgment.get("reason") in {"judge_response_unparseable", "missing_judgment"}
    )
    nli_stale = bool(nli.get("outputs_fingerprint")) and nli.get("outputs_fingerprint") != _outputs_fingerprint(results)
    lines.append("## 忠实度(NLI 初判,冻结证据)")
    lines.append("")
    lines.append(f"- judge:{nli.get('judge_version')} / prompt `{nli.get('judge_prompt_version')}` / 模型 {(nli.get('model') or {}).get('model_id')}")
    lines.append(
        f"- 汇总:**entailed={label_counts.get('entailed', 0)}, contradicted={label_counts.get('contradicted', 0)}, "
        f"unknown={label_counts.get('unknown', 0)}, 解析失败={unparsed}(单列,不计入 unknown)**"
    )
    if nli_stale:
        lines.append("- ⚠️ **判定已过期**:判定时的输出指纹与当前回放结果不一致,须重跑 `g1_nli_judge.py` 后本节才有效。")
    lines.append("- 说明:建议话术多为新措辞,unknown 占多数是预期分布;关键红线是 contradicted=0(输出不得与已发送事实冲突)。")
    lines.append(f"- 证据来源:回放结果内冻结的 `context_snapshot.sent_evidence`(不再事后重读数据库)")
    lines.append("- 状态:`model_judged_pending_human`")
    lines.append("")

    lines.append("## 结论与限制")
    lines.append("")
    gates = {
        "联系人隔离": isolation,
        "任务契约": contract,
        "发送清单一致性": consistency,
        "隐私红线": privacy,
    }
    for gate, check in gates.items():
        lines.append(f"- {_gate_mark(check)} {gate}(`{check.get('status')}`)")
    lines.append("")
    lines.append("已知限制(不影响门禁判定,但验收时必须知情):")
    lines.append("")
    lines.append("- 回放只覆盖**手动生成入口**(`manual_request`);自动触发、开场、全自动入口的端到端行为尚未回放,待真实环境冒烟验证。")
    lines.append("- 窗口与证据快照已随回放冻结(`context_snapshot`);审核包以冻结快照为准。")
    lines.append("- 任务契约含输出契约(要话术必须有话术/直答必须有 reply),但**回答质量**(是否切题、可发送)由审核包人工/agent 终审判断。")
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
