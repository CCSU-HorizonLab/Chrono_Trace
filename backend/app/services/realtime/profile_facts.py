"""画像长期事实注入：把 RAG 事实层（全时段结构化记忆）喂给画像 prompt。

画像的 LLM 语义层此前只有 rolling 窗样本（联系人B 2.5 年史 90 天窗只覆盖
8%），事实层是全时段的却从未进画像——本模块把活跃事实（supersede
演变链顶端，confidence 优先）注入【长期记忆事实】块，画像立即能引用
全部历史沉淀的结构化记忆，零新增 LLM 调用（事实本来就抽好了）。

口径：
- 只取 status='active' AND enabled=1——superseded（演变链旧环）/
  uncertain（质量隔离）/ 用户禁用的事实天然排除，list_facts 同款；
- 按置信度优先、更新时间次之排序，截断条数防 prompt 膨胀；
- rag_facts 表缺失（旧库/测试库）静默降级为空，画像链路不受 RAG
  开关影响——事实已落库即注入，无嵌入/检索成本。
"""
from __future__ import annotations

import time
from typing import Any

# 注入条数上限：事实 content 多为单句，24 条约 1~2K token，画像 prompt
# 可承受；超出按 confidence 截断（低置信事实的信息密度边际递减）
PROFILE_FACT_INJECT_LIMIT = 24


def collect_profile_facts(
    conn,
    account_wxid: str,
    conversation_id: int,
    limit: int = PROFILE_FACT_INJECT_LIMIT,
) -> list[dict[str, Any]]:
    """取活跃事实（链顶端），confidence DESC, updated_at DESC。"""
    try:
        rows = conn.execute(
            """
            SELECT content, as_of, confidence
            FROM rag_facts
            WHERE account_wxid = ? AND conversation_id = ?
              AND status = 'active' AND enabled = 1
            ORDER BY confidence DESC, updated_at DESC
            LIMIT ?
            """,
            (account_wxid, int(conversation_id), max(1, int(limit))),
        ).fetchall()
    except Exception:
        return []
    facts = []
    for row in rows:
        content = str(row["content"] or "").strip()
        if not content:
            continue
        facts.append(
            {
                "content": content,
                "as_of": int(row["as_of"] or 0) if row["as_of"] else 0,
                "confidence": float(row["confidence"] or 0.0),
            }
        )
    return facts


def render_facts_block(facts: list[dict[str, Any]]) -> str:
    """渲染【长期记忆事实】块；空列表返回空串（调用方跳过注入）。"""
    if not facts:
        return ""
    lines = ["【长期记忆事实】（全部历史沉淀的结构化记忆，含窗口外时期）"]
    for item in facts:
        time_note = ""
        if item.get("as_of"):
            time_struct = time.localtime(int(item["as_of"]))
            time_note = f"，截至 {time_struct.tm_year}-{time_struct.tm_mon:02d}"
        conf = item.get("confidence") or 0.0
        lines.append(f"- {item['content']}（置信{conf:.2f}{time_note}）")
    return "\n".join(lines)
