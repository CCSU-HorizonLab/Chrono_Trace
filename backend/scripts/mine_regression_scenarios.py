"""P0.3 人工建议回归集——场景挖掘脚本。

从真实使用数据自动抽取候选场景，标注者只做确认与补标（不从零编写）：

1. retrieval_log 源：每次真实建议生成（trigger/gate/注入策略）；
2. memory_reference 源：聊天中引用过去的消息（"还记得/上次/之前说过"），
   这些是"本应使用记忆"的时刻。

输出 JSONL（默认 backend/data/regression_scenarios.jsonl），每行一个待标注
场景，labels 字段留空待人工填写——schema 见
docs/p0.3-regression-labeling-guide.md。文本一律 strong_mask 脱敏。

用法：
    python scripts/mine_regression_scenarios.py [--limit 200] [--out path] \
        [--conversation 7191] [--days 30] [--extra-terms 还记得,上回]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.privacy_redactor import PrivacyRedactor  # noqa: E402

# 挖掘特征词：语言词表按 P2-1 精神可外部补充（--extra-terms），内置常用集
DEFAULT_MEMORY_REFERENCE_TERMS = (
    "还记得", "上次", "上回", "之前说", "之前提", "说过要", "不是说好",
    "我们不是", "去年", "那时候", "你以前",
)

LABEL_SCHEMA = {
    "scene": "ambient|manual_request|direct_reply|memory_lookup",
    "need": "no_memory|shared_memory|relationship_state|preference_avoid|user_style",
    "relationship_stage": "free text",
    "allowed_to_cite": "free text（允许引用范围）",
    "must_avoid": "free text（应避免引用/敏感）",
    "should_followup": "bool（无命中应追问）",
    "gold_fact_ids": "[int]",
    "gold_policy_ids": "[int]",
    "notes": "free text",
}


def _mask(redactor: PrivacyRedactor | None, text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())[:limit]
    if redactor is None:
        return text[:60]
    try:
        return redactor.strong_mask(text)
    except Exception:
        return text[:60]


def mine_retrieval_log_scenarios(conn, redactor, *, conversation_id, days, limit):
    rows = conn.execute(
        """
        SELECT l.id, l.account_wxid, l.conversation_id, l.suggestion_id,
               l.trigger_type_hint, l.rag_gate_decision, l.rag_injection_mode,
               l.rag_strategy, l.policy_ids_json, l.contact_preference_ids_json,
               l.memory_intent_mode, l.query_text, l.created_at,
               c.display_name
        FROM rag_retrieval_logs l
        LEFT JOIN conversations c ON c.id = l.conversation_id AND c.account_wxid = l.account_wxid
        WHERE l.run_provenance = 'production'
          AND (? = 0 OR l.conversation_id = ?)
          AND l.created_at >= ?
        ORDER BY l.created_at DESC LIMIT ?
        """,
        (conversation_id or 0, conversation_id or 0, int(time.time()) - days * 86400, limit),
    ).fetchall() if _column_exists(conn, "rag_retrieval_logs", "trigger_type_hint") else conn.execute(
        """
        SELECT l.id, l.account_wxid, l.conversation_id, l.suggestion_id,
               NULL AS trigger_type_hint, l.rag_gate_decision, l.rag_injection_mode,
               l.rag_strategy, l.policy_ids_json, l.contact_preference_ids_json,
               l.memory_intent_mode, l.query_text, l.created_at,
               c.display_name
        FROM rag_retrieval_logs l
        LEFT JOIN conversations c ON c.id = l.conversation_id AND c.account_wxid = l.account_wxid
        WHERE l.run_provenance = 'production'
          AND (? = 0 OR l.conversation_id = ?)
          AND l.created_at >= ?
        ORDER BY l.created_at DESC LIMIT ?
        """,
        (conversation_id or 0, conversation_id or 0, int(time.time()) - days * 86400, limit),
    ).fetchall()
    scenarios = []
    for row in rows:
        scenarios.append(
            {
                "scenario_id": f"rl-{row['id']}",
                "source": "retrieval_log",
                "account_wxid": row["account_wxid"],
                "conversation_id": row["conversation_id"],
                "display_name": row["display_name"],
                "timestamp": row["created_at"],
                "context_excerpt": _mask(redactor, row["query_text"]),
                "suggestion_id": row["suggestion_id"],
                "retrieval_log_id": row["id"],
                "gate_decision": row["rag_gate_decision"],
                "injection_mode": row["rag_injection_mode"],
                "memory_intent_mode": row["memory_intent_mode"],
                "candidate_gold_hint": {
                    "policy_ids": json.loads(row["policy_ids_json"] or "[]"),
                    "contact_preference_ids": json.loads(row["contact_preference_ids_json"] or "[]"),
                },
                "labels": dict(LABEL_SCHEMA),
            }
        )
    return scenarios


def mine_memory_reference_scenarios(conn, redactor, *, conversation_id, days, limit, terms):
    placeholders = ",".join("?" for _ in terms)
    rows = conn.execute(
        f"""
        SELECT m.id, m.conversation_id, c.account_wxid AS account_wxid, m.is_sender, m.content,
               m.timestamp, c.display_name
        FROM messages m
        LEFT JOIN conversations c ON c.id = m.conversation_id
        WHERE m.message_type = 1 AND m.content IS NOT NULL AND TRIM(m.content) != ''
          AND (? = 0 OR m.conversation_id = ?)
          AND m.timestamp >= ?
          AND ({" OR ".join("m.content LIKE '%' || ? || '%'" for _ in terms)})
        ORDER BY m.timestamp DESC LIMIT ?
        """,
        (conversation_id or 0, conversation_id or 0, int(time.time()) - days * 86400, *terms, limit),
    ).fetchall()
    scenarios = []
    for row in rows:
        # 找同会话该时刻前后的活跃事实作为 gold 提示
        hint_rows = conn.execute(
            """
            SELECT id FROM rag_facts
            WHERE conversation_id = ? AND status = 'active' AND enabled = 1
              AND as_of IS NOT NULL AND as_of <= ?
            ORDER BY as_of DESC LIMIT 5
            """,
            (row["conversation_id"], row["timestamp"]),
        ).fetchall()
        scenarios.append(
            {
                "scenario_id": f"mr-{row['id']}",
                "source": "memory_reference",
                "account_wxid": row["account_wxid"],
                "conversation_id": row["conversation_id"],
                "display_name": row["display_name"],
                "timestamp": row["timestamp"],
                "context_excerpt": _mask(redactor, row["content"]),
                "message_id": row["id"],
                "is_sender": row["is_sender"],
                "candidate_gold_hint": {
                    "recent_fact_ids": [int(r["id"]) for r in hint_rows],
                },
                "labels": dict(LABEL_SCHEMA),
            }
        )
    return scenarios


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(r["name"]) == column for r in rows)
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="P0.3 回归集场景挖掘")
    parser.add_argument("--db", default=os.path.join("backend", "data", "chrono_trace.db"))
    parser.add_argument("--out", default=os.path.join("backend", "data", "regression_scenarios.jsonl"))
    parser.add_argument("--conversation", type=int, default=0, help="限定会话（0=全部）")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--limit", type=int, default=100, help="每源上限")
    parser.add_argument("--extra-terms", default="", help="补充记忆引用特征词（逗号分隔）")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        redactor = PrivacyRedactor(conn)
    except Exception:
        redactor = None

    terms = list(DEFAULT_MEMORY_REFERENCE_TERMS) + [
        t.strip() for t in args.extra_terms.split(",") if t.strip()
    ]
    scenarios = mine_retrieval_log_scenarios(
        conn, redactor, conversation_id=args.conversation, days=args.days, limit=args.limit
    )
    scenarios += mine_memory_reference_scenarios(
        conn, redactor, conversation_id=args.conversation, days=args.days,
        limit=args.limit, terms=terms,
    )
    scenarios.sort(key=lambda item: int(item["timestamp"] or 0))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        for scenario in scenarios:
            fh.write(json.dumps(scenario, ensure_ascii=False) + "\n")
    by_source: dict[str, int] = {}
    for scenario in scenarios:
        by_source[scenario["source"]] = by_source.get(scenario["source"], 0) + 1
    print(f"mined {len(scenarios)} scenarios -> {args.out}")
    print(f"  by source: {by_source}")
    print("  next: 按 docs/p0.3-regression-labeling-guide.md 两轮标注（间隔>=48h）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
