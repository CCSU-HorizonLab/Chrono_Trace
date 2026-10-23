"""画像长期事实注入：把 RAG 事实层（全时段结构化记忆）喂给画像 prompt。

画像的 LLM 语义层此前只有 rolling 窗样本（2.5 年会话 90 天窗只覆盖
8%），事实层是全时段的却从未进画像——本模块把活跃事实（supersede
演变链顶端，confidence 优先）注入【长期记忆事实】块，画像立即能引用
全部历史沉淀的结构化记忆，零新增 LLM 调用（事实本来就抽好了）。

口径：
- 只取 status='active' AND enabled=1——superseded（演变链旧环）/
  uncertain（质量隔离）/ 用户禁用的事实天然排除；
- sensitivity='sensitive' 排除：事实进的是远程 LLM prompt，对齐检索
  通道的隐私红线（retriever 同款排除，本地管理页不受影响）；
- 注入前逐条过 PrivacyRedactor（无连接实例：只做规则替换，占位符按
  值哈希稳定）——事实存的是未脱敏原文，画像 LLM 链路本身无脱敏环节，
  而事实层是全时段数据，明文注入等于把暴露面从窗口期扩到全部历史；
  词表 sensitive 标记只拦得住关键词命中的少数，规则脱敏兜住手机号/
  证件号/卡号/地址这类硬 PII。脱敏异常丢弃该条（fail-closed：脱不
  干净的不出网）；
- rag_enabled 关闭即不注入：用户关掉记忆子系统的预期是记忆内容
  不再参与任何远程交互（affinity/history_qa 同款门控）；
- 按置信度优先、更新时间次之排序，截断条数防 prompt 膨胀；空白
  content 在 SQL 层排除（不占 LIMIT 槽位），多行内容压平为单行
  （防破坏列表结构被 LLM 误读为指令）；
- rag_facts 表缺失（旧库/测试库）降级为空并留 debug 日志。
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 注入条数上限：事实 content 多为单句，24 条约 1~2K token，画像 prompt
# 可承受；超出按 confidence 截断（低置信事实的信息密度边际递减）
PROFILE_FACT_INJECT_LIMIT = 24


def collect_profile_facts(
    conn,
    account_wxid: str,
    conversation_id: int,
    limit: int = PROFILE_FACT_INJECT_LIMIT,
) -> list[dict[str, Any]]:
    """取活跃事实（链顶端、非敏感），confidence DESC, updated_at DESC。"""
    from .rag.config import load_rag_settings

    try:
        if not load_rag_settings().get("rag_enabled"):
            return []
    except Exception as exc:
        logger.debug("[画像事实] RAG 开关读取失败，保守跳过注入: %s", exc)
        return []
    try:
        rows = conn.execute(
            """
            SELECT content, as_of, confidence
            FROM rag_facts
            WHERE account_wxid = ? AND conversation_id = ?
              AND status = 'active' AND enabled = 1
              AND COALESCE(sensitivity, 'normal') != 'sensitive'
              AND TRIM(COALESCE(content, '')) != ''
            ORDER BY confidence DESC, updated_at DESC
            LIMIT ?
            """,
            (account_wxid, int(conversation_id), max(1, int(limit))),
        ).fetchall()
    except Exception as exc:
        logger.debug("[画像事实] 取数降级为空: %s", exc)
        return []
    facts = []
    # 无连接实例：纯规则替换不落隐私表，占位符按值哈希跨调用稳定
    from .privacy_redactor import PrivacyRedactor

    redactor = PrivacyRedactor()
    for row in rows:
        # 空白压平为单行：多行事实会破坏【长期记忆事实】的列表结构，
        # 后续行裸露在 prompt 里容易被 LLM 当指令读
        content = " ".join(str(row["content"] or "").split())
        if not content:
            continue
        try:
            content = redactor.redact(content).redacted_text
        except Exception as exc:
            logger.warning("[画像事实] 脱敏失败，丢弃该条不注入: %s", exc)
            continue
        if not content:
            continue
        facts.append(
            {
                "content": content,
                "as_of": int(row["as_of"] or 0),
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
