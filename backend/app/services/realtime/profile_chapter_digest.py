"""画像章节摘要注入：把章节摘要金字塔产物喂给画像 prompt。

C2 之前画像的语义层只有 rolling 窗样本（长会话 90 天窗只罩尾部 8%）
+ RAG 事实（结构化短句）；本模块注入【关系章节摘要】块——全量语料
经月摘要→章节归并的语义压缩，画像立即引用全部年份的叙事。摘要由
chapter_summaries 任务产出落库，本模块纯 SQL 读取（零 LLM 调用）。

口径：
- rolling（from_ts/to_ts 缺省 0）：注入全部章节——对齐长期背景/事实
  块的全时段注入语义（rolling 是尾部窗，章节摘要给全局坐标）；
- custom 指定窗：只注入与窗口有交叠的章节（画像演变各段聚焦自身
  时段，段外章不进 prompt）；
- 版本过滤 SUMMARY_VERSION（旧口径摘要失明）；
- 章摘要存的是 LLM 产出原文，注入前逐条过 PrivacyRedactor 规则脱敏
  （对齐 profile_facts 纪律：全时段数据不过脱敏不出网；脱敏异常丢章
  fail-closed）；
- 表缺失（未跑过摘要任务的库）静默降级为空。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .privacy_redactor import PrivacyRedactor

logger = logging.getLogger(__name__)

# 注入章数上限：章摘要 ~160 字/章，8 章 ≈ 1.3K 字，画像 prompt 可承受；
# 超出按时间倒序截断（近端章信息密度高）
PROFILE_CHAPTER_INJECT_LIMIT = 8


def collect_chapter_digest(
    conn,
    conversation_id: int,
    from_ts: int = 0,
    to_ts: int = 0,
    limit: int = PROFILE_CHAPTER_INJECT_LIMIT,
) -> list[dict[str, Any]]:
    """取章节摘要（新版口径），按时间序。rolling（0/0）取全部。"""
    try:
        from ..analysis.chapter_summaries import SUMMARY_VERSION

        if from_ts or to_ts:
            where = ("AND cs.from_ts <= ? AND cs.to_ts >= ?")
            params: list[Any] = [int(conversation_id), SUMMARY_VERSION, int(to_ts), int(from_ts)]
        else:
            where = ""
            params = [int(conversation_id), SUMMARY_VERSION]
        rows = conn.execute(
            f"""
            SELECT cs.from_ts, cs.to_ts, cs.summary_json
            FROM chapter_summaries cs
            WHERE cs.conversation_id = ? AND cs.version = ? {where}
            ORDER BY cs.from_ts DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit))),
        ).fetchall()
    except Exception as exc:
        logger.debug("[画像章节] 取数降级为空: %s", exc)
        return []

    redactor = PrivacyRedactor()  # 无连接实例：纯规则替换，不落隐私表
    digest: list[dict[str, Any]] = []
    for row in rows:
        try:
            summary = json.loads(row["summary_json"])
        except Exception:
            continue
        text = " ".join(str(summary.get("summary") or "").split())
        if not text:
            continue
        try:
            text = redactor.redact(text).redacted_text
        except Exception as exc:
            logger.warning("[画像章节] 脱敏失败，丢弃该章不注入: %s", exc)
            continue
        if not text:
            continue
        digest.append({
            "from_ts": int(row["from_ts"] or 0),
            "to_ts": int(row["to_ts"] or 0),
            "summary": text,
            "phase": " ".join(str(summary.get("phase") or "").split()),
        })
    digest.reverse()  # SQL 按时间倒序取近端优先，注入时恢复时间正序
    return digest


def render_chapter_digest_block(digest: list[dict[str, Any]]) -> str:
    """渲染【关系章节摘要】块；空列表返回空串（调用方跳过注入）。"""
    if not digest:
        return ""
    lines = [
        "【关系章节摘要】（全部语料经月度摘要归并的章节叙事，含窗口外时期；"
        "观察性描述，供了解这段关系的长期走向）"
    ]
    for i, item in enumerate(digest, 1):
        span = _fmt_range(item["from_ts"], item["to_ts"])
        phase = f"（{item['phase']}）" if item.get("phase") else ""
        lines.append(f"- 第{i}章 {span}{phase}: {item['summary']}")
    return "\n".join(lines)


def _fmt_range(from_ts: int, to_ts: int) -> str:
    a = time.localtime(int(from_ts))
    b = time.localtime(int(to_ts))
    return f"{a.tm_year}-{a.tm_mon:02d}~{b.tm_year}-{b.tm_mon:02d}"
