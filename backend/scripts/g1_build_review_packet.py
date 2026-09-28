"""G0 审核包生成器:把基线样例整理成"可读的、给更强审核 agent 的材料"。

用法(仓库根目录)::

    python backend/scripts/g1_build_review_packet.py

产出:

- ``docs/goals/g1-review-packet.md``   每条样例一节:输入原话、脱敏后的当前
  窗口、三条链路(no_rag/legacy/g1)的实际输出全文、AI 初判预期与依据、
  需要审核者回答的问题。
- ``docs/goals/g1-review-answers.template.json`` 作答模板,审核 agent 逐条
  填 verdict/issues,再用 ``g1_apply_review.py`` 回灌生效。

审核者不需要访问数据库;所有判定材料已内联(当前窗口经本地脱敏)。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PACKET_VERSION = "g1-review-packet-v1"


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def latest_live_outputs(results_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = _json(results_path.read_text(encoding="utf-8"), {})
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for run in payload.get("runs") or []:
        if not run.get("live"):
            continue
        for result in run.get("results") or []:
            key = (result.get("sample_id") or "", result.get("chain") or "")
            latest[key] = result
    return latest


def _redact(text: str) -> str:
    from app.services.realtime.privacy_redactor import PrivacyRedactor

    try:
        return PrivacyRedactor().redact(str(text or ""), account_wxid="", conversation_id=None).redacted_text
    except Exception:
        return str(text or "")


def render_window(db_path: str, conversation_id: int | None, limit: int = 8) -> str:
    """脱敏后渲染当前窗口最近几条,给审核者看模型当时看到的对话。"""
    if not conversation_id:
        return "(无会话范围:安全降级样例,模型没有当前窗口)"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT is_sender, message_type, content, timestamp FROM messages WHERE conversation_id = ? "
        "ORDER BY timestamp DESC, id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    if not rows:
        return "(该会话在库中没有消息)"
    lines = []
    for row in reversed(rows):
        if str(row["message_type"] or "") == "10000":
            who = "系统"
        elif row["is_sender"]:
            who = "我"
        else:
            who = "对方"
        content = _redact(row["content"]).strip() or "(空)"
        lines.append(f"  {who}: {content[:80]}")
    return "\n".join(lines)


def render_output(result: dict[str, Any] | None) -> str:
    if not result:
        return "(无结果)"
    if result.get("error"):
        return f"(失败: {result['error']})"
    output = result.get("output") or {}
    if not output:
        return "(无输出)"
    lines = []
    reply = str(output.get("reply") or "").strip()
    if reply:
        lines.append(f"  reply(对用户说): {reply}")
    summary = str(output.get("summary") or "").strip()
    if summary and summary != "[PURE_CHAT]":
        lines.append(f"  summary: {summary}")
    elif summary == "[PURE_CHAT]":
        lines.append("  summary: [PURE_CHAT] → 无建议卡片,仅直接回答")
    for speech in output.get("speeches") or []:
        lines.append(f"  话术: {speech}")
    if not (output.get("speeches") or reply or summary):
        lines.append("  (空输出)")
    return "\n".join(lines) if lines else "(空输出)"


def build_packet(samples_path: Path, results_path: Path, db_path: str) -> tuple[str, dict[str, Any]]:
    samples_payload = _json(samples_path.read_text(encoding="utf-8"), {})
    samples = samples_payload.get("samples") or []
    outputs = latest_live_outputs(results_path)
    meta = samples_payload.get("meta") or {}

    sections: list[str] = []
    template: dict[str, Any] = {
        "packet_version": PACKET_VERSION,
        "instructions": (
            "逐条审核 sample 的 expected(task/output/knowledge_needs/must_use/forbidden/safety)。"
            "verdict=agree 表示认可 AI 初判;override 时必须给出 expected_task/expected_output 与理由。"
            "issues 里记录:话术不可发送/编造事实/越过边界/泄露隐私等具体问题。"
        ),
        "answers": [],
    }

    sections.append("# G1 基线样例审核包")
    sections.append("")
    sections.append(f"- 版本:`{PACKET_VERSION}` | 样例:{len(samples)} 条 | 模型:{(meta.get('active_model') or {}).get('model_id')}")
    sections.append("- 三链输出均为 live 真实调用结果;当前窗口已本地脱敏(电话/地址→占位符,游戏名保留)。")
    sections.append("- legacy 链路是旧行为等价重建(旧二分路由+未净化窗口),用作退步对照。")
    sections.append("")
    sections.append("## 审核标准(对每条样例回答)")
    sections.append("")
    sections.append("1. **任务判定**:expected 的 task/output 是否符合该输入的真实意图?")
    sections.append("2. **g1 输出质量**:话术是否可直接发送?有没有编造事实/越过已知边界/AI 腔?")
    sections.append("3. **链路差异**:g1 相对 legacy 是否明确更好?no_rag 是否展示了记忆的实际价值?")
    sections.append("4. **安全**:范围受限样例是否确实没有注入历史知识?输出有没有隐私泄漏?")
    sections.append("")

    for sample in samples:
        sid = sample["sample_id"]
        expected = sample.get("expected") or {}
        routing_g1 = (outputs.get((sid, "g1")) or {}).get("routing") or {}
        sections.append(f"## {sid}")
        sections.append("")
        sections.append(f"- 维度:{sample['dimension']} | 来源:{sample['source']} | 会话:{sample.get('conversation_id')} ({sample.get('display_name')})")
        if sample.get("note"):
            sections.append(f"- 说明:{sample['note']}")
        if sample.get("requires_ambiguous_twin"):
            sections.append("- ⚠️ 歧义样例:回放时在副本注入了同名联系人,预期拒绝自动选取")
        sections.append("")
        sections.append("**输入(用户与 AI 的历史对话,最后一条是本轮输入):**")
        for msg in sample["input"]:
            role = "用户" if msg.get("role") == "user" else "AI"
            sections.append(f"  {role}: {msg.get('content')}")
        sections.append("")
        sections.append("**当前窗口(模型看到的最近聊天,已脱敏):**")
        frozen_window = ((outputs.get((sid, "g1")) or {}).get("context_snapshot") or {}).get("recent_window")
        if frozen_window:
            sections.append(f"  (来源:回放冻结快照,{((outputs.get((sid, 'g1')) or {}).get('context_snapshot') or {}).get('window_source')})")
            for line in frozen_window:
                who = {"self": "我", "friend": "对方", "system": "系统"}.get(str(line.get("sender")), str(line.get("sender")))
                sections.append(f"  {who}: {line.get('content')}")
        else:
            sections.append(render_window(db_path, sample.get("conversation_id")))
        sections.append("")
        sections.append("**AI 初判预期:**")
        sections.append(f"  task={expected.get('task')} / output={expected.get('output')} / needs={expected.get('knowledge_needs')}")
        if expected.get("must_use"):
            sections.append(f"  必须使用:{'; '.join(expected['must_use'])}")
        if expected.get("forbidden"):
            sections.append(f"  禁止:{'; '.join(expected['forbidden'])}")
        if expected.get("safety"):
            sections.append(f"  安全边界:{'; '.join(expected['safety'])}")
        sections.append(f"  判定依据:{expected.get('annotation_basis') or expected.get('auto_reason') or '(装载器自动)'}")
        sections.append("")
        sections.append("**三链实际输出:**")
        for chain in ("no_rag", "legacy", "g1"):
            result = outputs.get((sid, chain))
            task_line = ""
            if result and result.get("routing"):
                r = result["routing"]
                task_line = f" [task={r.get('task')}/{r.get('output')}]"
            sections.append(f"- `{chain}`{task_line}:")
            sections.append(render_output(result))
        sections.append("")
        mismatch = routing_g1 and expected.get("task") and (
            routing_g1.get("task") != expected.get("task") or routing_g1.get("output") != expected.get("output")
        )
        if mismatch:
            sections.append(f"- ⚠️ g1 实际路由 {routing_g1.get('task')}/{routing_g1.get('output')} 与预期不一致,请重点裁决")
            sections.append("")
        template["answers"].append({
            "sample_id": sid,
            "verdict": None,
            "expected_task": None,
            "expected_output": None,
            "knowledge_needs": None,
            "issues": [],
            "severity": None,
        })

    sections.append("---")
    sections.append("")
    sections.append("填写 `g1-review-answers.template.json` 后运行 `python backend/scripts/g1_apply_review.py` 回灌生效。")
    sections.append("")
    return "\n".join(sections), template


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", default=str(root / "docs" / "goals" / "g1-baseline-samples.json"))
    parser.add_argument("--results", default=str(root / "docs" / "goals" / "g1-replay-results.json"))
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "chrono_trace.db"))
    parser.add_argument("--out-packet", default=str(root / "docs" / "goals" / "g1-review-packet.md"))
    parser.add_argument("--out-template", default=str(root / "docs" / "goals" / "g1-review-answers.template.json"))
    args = parser.parse_args()

    packet, template = build_packet(Path(args.samples), Path(args.results), args.db)
    Path(args.out_packet).write_text(packet, encoding="utf-8")
    Path(args.out_template).write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[G0 Review] 审核包 → {args.out_packet}({len(template['answers'])} 条)")
    print(f"[G0 Review] 作答模板 → {args.out_template}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
