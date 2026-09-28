"""G7 忠实度初判:对 g1 链路 live 输出做 蕴含/矛盾/未知 (NLI) 判定。

用法(仓库根目录)::

    python backend/scripts/g1_nli_judge.py            # 判定全部 g1 live 结果
    python backend/scripts/g1_nli_judge.py --sample real-2

契约(上游文档 G7):

- 证据只用**实际发送清单**里的事实,且先经 PrivacyRedactor 脱敏再送 judge;
- judge 使用当前激活模型,原始响应完整保留,标记为 ``model_judged_pending_human``;
- 输出 ``docs/goals/g1-nli-judgments.json``,供 e2e 报告与人工复核。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

JUDGE_VERSION = "g1-nli-judge-v1"
JUDGE_PROMPT_VERSION = "g1-faithfulness-v1"
LABELS = ("entailed", "contradicted", "unknown")


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def collect_g1_live_results(results_path: Path) -> dict[str, dict[str, Any]]:
    """取每个样例最后一次 g1 live 结果(重跑覆盖旧值)。"""
    payload = _json(results_path.read_text(encoding="utf-8"), {})
    latest: dict[str, dict[str, Any]] = {}
    for run in payload.get("runs") or []:
        if not run.get("live"):
            continue
        for result in run.get("results") or []:
            if result.get("chain") == "g1" and result.get("output"):
                latest[result["sample_id"]] = result
    return latest


def load_redacted_evidence(db_path: str, fact_ids: list[int]) -> list[dict[str, str]]:
    """按发送清单取事实原文,本地脱敏后作为 judge 证据(不回退明文)。"""
    from app.services.realtime.privacy_redactor import PrivacyRedactor

    if not fact_ids:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in fact_ids)
    rows = conn.execute(
        f"SELECT id, kind, content FROM rag_facts WHERE id IN ({placeholders}) AND status = 'active'",
        fact_ids,
    ).fetchall()
    conn.close()
    redactor = PrivacyRedactor()
    evidence = []
    for row in rows:
        content = str(row["content"] or "").strip()
        if not content:
            continue
        redacted = redactor.strong_mask(content)
        evidence.append({"fact_id": int(row["id"]), "kind": row["kind"], "evidence": redacted})
    return evidence


def extract_claims(result: dict[str, Any]) -> list[str]:
    output = result.get("output") or {}
    claims: list[str] = []
    for speech in output.get("speeches") or []:
        text = str(speech or "").strip()
        if text:
            claims.append(text)
    for field in ("reply", "summary"):
        text = str(output.get(field) or "").strip()
        if text and not text.startswith("["):
            claims.append(text)
    return claims[:6]


JUDGE_SYSTEM_PROMPT = """你是忠实度判定器。给定【证据】(来自记忆库的历史事实,已脱敏)和【陈述】
(一条面向用户的建议输出),逐条判断每条陈述相对证据的关系:
- entailed: 陈述的具体内容可由证据直接支持;
- contradicted: 陈述与证据明确冲突;
- unknown: 证据不足以判定(包括没有任何相关证据)。

只依据给出的证据判断,不要用常识脑补,不要给聊天建议,不要输出分析过程。
只输出一个 JSON 对象(不要 Markdown、不要多余文本):
{"judgments": [{"claim": 1, "label": "entailed|contradicted|unknown", "reason": "一句话"}]}"""


def build_judge_prompt(claims: list[str], evidence: list[dict[str, str]]) -> str:
    lines = ["【证据】"]
    if evidence:
        for item in evidence:
            lines.append(f"- (fact#{item['fact_id']}/{item['kind']}) {item['evidence']}")
    else:
        lines.append("- (无:本次未发送任何历史事实证据)")
    lines.append("")
    lines.append("【陈述】")
    for index, claim in enumerate(claims, 1):
        lines.append(f"{index}. {claim}")
    return "\n".join(lines)


def parse_judge_response(text: str, claim_count: int) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    # 优先整体按 JSON 对象解析(JSON 模式);退化时抓取最后一个对象/数组片段。
    parsed: Any = _json(raw, None)
    if not isinstance(parsed, dict):
        parsed = None
        for candidate in reversed(re.findall(r"\{[\s\S]*\}|\[[\s\S]*\]", raw)):
            parsed = _json(candidate, None)
            if isinstance(parsed, (dict, list)):
                break
    items = []
    if isinstance(parsed, dict):
        items = parsed.get("judgments") or []
    elif isinstance(parsed, list):
        items = parsed
    judgments: dict[int, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        index = int(item.get("claim") or 0)
        label = str(item.get("label") or "").lower()
        if 1 <= index <= claim_count and label in LABELS:
            judgments[index] = {"claim": index, "label": label, "reason": str(item.get("reason") or "")[:200]}
    if not judgments:
        return [{"claim": i + 1, "label": "unknown", "reason": "judge_response_unparseable"} for i in range(claim_count)]
    return [judgments.get(i, {"claim": i, "label": "unknown", "reason": "missing_judgment"}) for i in range(1, claim_count + 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-replay-results.json"))
    parser.add_argument("--samples", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-baseline-samples.json"))
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "chrono_trace.db"))
    parser.add_argument("--sample", action="append", default=None)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-nli-judgments.json"))
    args = parser.parse_args()

    latest = collect_g1_live_results(Path(args.results))
    if args.sample:
        wanted = set(args.sample)
        latest = {sid: r for sid, r in latest.items() if sid in wanted}
    if not latest:
        print("[G7 NLI] 没有 g1 live 结果可判定(先运行 --chain g1 --live)")
        return 1

    from app.services.realtime.llm_engine import LLMSuggestionEngine

    engine = LLMSuggestionEngine()
    model_config = engine._get_active_model()
    if not model_config:
        print("[G7 NLI] 无激活模型")
        return 1

    judged: list[dict[str, Any]] = []
    label_counts = {label: 0 for label in LABELS}
    for sample_id, result in sorted(latest.items()):
        claims = extract_claims(result)
        if not claims:
            continue
        fact_ids = [int(fid) for fid in (result.get("manifest") or {}).get("fact_ids") or [] if fid]
        evidence = load_redacted_evidence(args.db, fact_ids)
        prompt = build_judge_prompt(claims, evidence)
        started = time.perf_counter()
        try:
            # 不走 _call_api(它强制挂聊天顾问系统提示);判定器用自己的系统提示。
            response_text = engine._call_api_with_messages(
                model_config,
                [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2400,
                temperature=0.1,
                request_tag="g1_nli_judge",
                use_json_mode=False,
            )
            judgments = parse_judge_response(response_text, len(claims))
            raw = str(response_text)[:2000]
        except Exception as exc:
            judgments = [{"claim": i + 1, "label": "unknown", "reason": f"judge_error: {exc}"} for i in range(len(claims))]
            raw = f"{type(exc).__name__}: {exc}"
        for judgment in judgments:
            label_counts[judgment["label"]] += 1
        judged.append({
            "sample_id": sample_id,
            "claims": claims,
            "evidence_fact_ids": fact_ids,
            "judgments": judgments,
            "judge_raw_response": raw,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        })
        summary = ", ".join(f"{j['claim']}={j['label']}" for j in judgments)
        print(f"  {sample_id:>34} | facts={len(fact_ids)} | {summary}")

    payload = {
        "judge_version": JUDGE_VERSION,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "model": {k: model_config.get(k) for k in ("provider", "model_id", "name")},
        "judged_at": int(time.time()),
        "status": "model_judged_pending_human",
        "label_counts": label_counts,
        "judgments": judged,
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[G7 NLI] {len(judged)} 条判定 → {out}")
    print(f"[G7 NLI] 汇总: {label_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
