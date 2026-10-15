"""群聊统计与群日报：按发言者聚合 + LLM 日报（远程脱敏同问答链路）。

局限（记录在案）：无群成员花名册，发言者名来自导入期 `sender` 列的
有损短名（`ingest_service` 的 resolve_chatroom_display_name 产物），
同名碰撞概率低；我方消息以 is_sender=1 归并为「我」。

无 LLM 模型时日报优雅降级：仅返回统计与提示，不报错。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db
from ..realtime.llm_http import (
    LLMRequestAborted,
    apply_interactive_fast_mode,
    post_json_with_retries,
    run_cancelable,
    take_llm_cancel,
)

logger = logging.getLogger(__name__)

# 统计规模上限（防大群全量拉内容）
MAX_TEXT_MESSAGES = 5000
TOP_WORDS_LIMIT = 30
TOP_WORDS_MIN_LEN = 2
# 日报上下文预算
PER_DAY_MESSAGES = 60
PER_MESSAGE_CHARS = 120
MAX_SUMMARY_CHARS = 7000
# 交互式日报：短超时 + 少重试 + 可取消（与问问微信同等待遇）
LLM_TIMEOUT = 60
LLM_MAX_RETRIES = 1
GS_CANCEL_SCOPE = "group_summary"

# 高频词停用：语气词/称呼/单字无信息量
STOP_WORDS = {
    "这个", "那个", "就是", "然后", "什么", "没有", "可以", "觉得", "现在",
    "一个", "还有", "已经", "不是", "怎么", "这样", "这样", "哈哈", "哈哈哈",
    "回复", "消息", "图片", "视频", "语音", "表情",
}

SUMMARY_SYSTEM_PROMPT = """你是群聊观察助手。根据【群聊记录】生成一份群日报，用中文分点输出，每点一行，总长不超过 300 字：

1. 主要话题：今天/近几天大家在聊什么（合并同类话题）
2. 群氛围：整体情绪基调（活跃/平淡/有争议等）
3. 值得注意的互动：谁提了重要的事、有无约定或提醒

只依据记录内容，不要编造；记录太少时说明信息不足。"""


class GroupSummaryError(Exception):
    """群统计失败（会话不存在/非群聊等，message 面向用户展示）"""


class GroupSummaryService:
    """群聊发言统计（纯本地）与 LLM 日报。"""

    # ---- 统计 ----

    def get_group_stats(
        self,
        conversation_id: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._require_group(conversation_id)
        rows = self._fetch_range_rows(conversation_id, start, end)
        return self._stats_from_rows(conversation_id, rows)

    @staticmethod
    def _fetch_range_rows(
        conversation_id: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Tuple]:
        """一次扫描取范围内全部消息（含非文本，统计需要）；时间升序。

        统计与日报分段共用本方法产物，避免同范围全表扫两遍。
        """
        where, params = GroupSummaryService._range_where(conversation_id, start, end)
        return get_db().execute(
            f"""
            SELECT CASE WHEN is_sender = 1 THEN '我' ELSE COALESCE(NULLIF(sender, ''), '未知成员') END AS name,
                   is_sender,
                   message_type,
                   content,
                   timestamp
            FROM messages {where}
            ORDER BY timestamp ASC
            """,
            params,
        ).fetchall()

    @staticmethod
    def _stats_from_rows(conversation_id: int, rows: List[Tuple]) -> Dict[str, Any]:
        total_messages = len(rows)
        if not total_messages:
            return {
                "conversation_id": conversation_id,
                "total_messages": 0,
                "total_chars": 0,
                "members": [],
                "my_rank": None,
                "active_hours": {},
                "top_words": [],
            }

        counts: Counter = Counter()
        chars: Counter = Counter()
        hour_counter: Counter = Counter()
        texts: List[str] = []
        for name, _is_sender, mtype, content, ts in rows:
            counts[name] += 1
            text = str(content or "") if mtype == 1 else ""
            chars[name] += len(text)
            if text.strip():
                hour_counter[int(time.strftime("%H", time.localtime(ts)))] += 1
                if len(texts) < MAX_TEXT_MESSAGES:
                    texts.append(text)

        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        members = [
            {
                "name": name,
                "message_count": count,
                "char_count": chars.get(name, 0),
                "share": round(count / total_messages, 4),
            }
            for name, count in ranked
        ]
        my_rank = next(
            (i + 1 for i, (name, _) in enumerate(ranked) if name == "我"), None
        )

        return {
            "conversation_id": conversation_id,
            "total_messages": total_messages,
            "total_chars": sum(chars.values()),
            "members": members,
            "my_rank": my_rank,
            "active_hours": {str(h): c for h, c in sorted(hour_counter.items())},
            "top_words": GroupSummaryService._top_words(texts),
        }

    @staticmethod
    def _range_where(conversation_id: int, start: Optional[int], end: Optional[int]) -> Tuple[str, List[Any]]:
        clauses = ["conversation_id = ?"]
        params: List[Any] = [conversation_id]
        if start:
            clauses.append("timestamp >= ?")
            params.append(int(start))
        if end:
            clauses.append("timestamp <= ?")
            params.append(int(end))
        return "WHERE " + " AND ".join(clauses), params

    @staticmethod
    def _top_words(texts: List[str]) -> List[Dict[str, int]]:
        counter: Counter = Counter()
        try:
            import jieba

            for text in texts:
                for word in jieba.cut(text):
                    word = word.strip()
                    if len(word) >= TOP_WORDS_MIN_LEN and word not in STOP_WORDS and not re.match(r"^[\W_]+$", word):
                        counter[word] += 1
        except Exception as exc:
            logger.debug("[群统计] 分词跳过（jieba 不可用）: %s", exc)
        return [{"word": word, "count": count} for word, count in counter.most_common(TOP_WORDS_LIMIT)]

    def _require_group(self, conversation_id: int) -> str:
        """校验群聊并返回 account_wxid（脱敏占位符键需要）。"""
        row = get_db().execute(
            "SELECT conversation_type, account_wxid FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise GroupSummaryError("会话不存在")
        if str(row[0] or "private") != "group":
            raise GroupSummaryError("该会话不是群聊")
        return str(row[1] or "")

    # ---- 日报 ----

    def generate_group_summary(self, conversation_id: int, days: int = 7) -> Dict[str, Any]:
        """近 N 天群日报：按日分段截断组 prompt，LLM 总结；无模型降级为仅统计。

        统计与分段共用一次范围扫描（大群避免全表扫两遍）。
        """
        account_wxid = self._require_group(conversation_id)
        take_llm_cancel(GS_CANCEL_SCOPE, conversation_id)  # 清掉上一轮遗留取消
        days = max(1, min(int(days or 7), 30))
        now = int(time.time())
        rows = self._fetch_range_rows(conversation_id, now - days * 86400, now)
        stats = self._stats_from_rows(conversation_id, rows)
        segments = self._segments_from_rows(rows)
        if not segments:
            return {
                "ok": True,
                "summary": "",
                "days": days,
                "degraded": True,
                "degraded_reason": f"近 {days} 天没有可用的文本消息",
                "stats": stats,
            }

        model_config = self._active_model()
        if not model_config:
            return {
                "ok": True,
                "summary": "",
                "days": days,
                "degraded": True,
                "degraded_reason": "未配置 LLM 模型，仅提供发言统计（设置 → 模型服务）",
                "stats": stats,
            }

        lines = self._render_segments(segments)
        if not lines:
            return {
                "ok": True,
                "summary": "",
                "days": days,
                "degraded": True,
                "degraded_reason": "记录量超出日报预算，请缩短时间范围",
                "stats": stats,
            }
        if self._is_remote(model_config):
            lines = self._redact_lines(lines, conversation_id, account_wxid)
        answer = self._call_llm(model_config, days, lines, conversation_id)

        return {"ok": True, "summary": answer, "days": days, "degraded": False, "stats": stats}

    @staticmethod
    def _segments_from_rows(rows: List[Tuple]) -> Dict[str, List[Tuple[str, str, int]]]:
        """文本消息按本地日聚合：{日期: [(发言人, 文本, 时间戳)]}，每日截断。"""
        segments: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
        for name, _is_sender, mtype, content, ts in rows:
            text = str(content or "").strip() if mtype == 1 else ""
            if not text:
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(ts))
            if len(segments[day]) >= PER_DAY_MESSAGES:
                continue
            segments[day].append((name, text[:PER_MESSAGE_CHARS], int(ts)))
        return segments

    @staticmethod
    def _render_segments(segments: Dict[str, List[Tuple[str, str, int]]]) -> List[str]:
        """渲染 prompt 行；总字符超预算时从最早的日期开始丢，只剩一天时
        日内从最早的消息行开始丢（保底 1 行——单行远低于预算）。"""

        def _total(rendered: List[Tuple[str, List[str]]]) -> int:
            parts: List[str] = []
            for day, lines in rendered:
                parts.append(f"—— {day} ——")
                parts.extend(lines)
            return len("\n".join(parts))

        rendered: List[Tuple[str, List[str]]] = []
        for day in sorted(segments):
            lines = [
                f"{time.strftime('%H:%M', time.localtime(ts))} {name}: {text}"
                for name, text, ts in segments[day]
            ]
            rendered.append((day, lines))

        total = _total(rendered)
        # 预算超限从最早一天开始丢，但至少保留最近一天
        while len(rendered) > 1 and total > MAX_SUMMARY_CHARS:
            rendered.pop(0)
            total = _total(rendered)
        # 单日仍超预算：日内从最早的消息行开始丢（行数保底 1）
        while len(rendered) == 1 and total > MAX_SUMMARY_CHARS and len(rendered[0][1]) > 1:
            rendered[0][1].pop(0)
            total = _total(rendered)
        if not rendered:
            return []

        out: List[str] = []
        for day, lines in rendered:
            out.append(f"—— {day} ——")
            out.extend(lines)
        return out

    @staticmethod
    def _active_model() -> Optional[Dict[str, Any]]:
        from ..realtime.rag.fact_llm import get_active_model_config

        return get_active_model_config()

    @staticmethod
    def _is_remote(model_config: Dict[str, Any]) -> bool:
        from ..realtime.rag.config import is_remote_llm_model

        return is_remote_llm_model(model_config)

    @staticmethod
    def _redact_lines(
        lines: List[str], conversation_id: int, account_wxid: str
    ) -> List[str]:
        """远程模型逐行脱敏；失败即阻断（与问答链路同红线）。

        account_wxid 必传：占位符持久表以 (account_wxid, conversation_id,
        实体) 为键做跨调用一致替换，缺省空串会生成另一套占位符。
        """
        from ..realtime.privacy_redactor import PrivacyRedactor

        redactor = PrivacyRedactor(get_db())
        redacted: List[str] = []
        for line in lines:
            try:
                result = redactor.redact(
                    line,
                    account_wxid=account_wxid,
                    conversation_id=conversation_id,
                    source_table="group_summary",
                )
            except Exception as exc:
                raise GroupSummaryError(f"脱敏失败，日报生成已阻断：{exc}") from exc
            redacted.append(result.redacted_text)
        return redacted

    @staticmethod
    def _call_llm(
        model_config: Dict[str, Any], days: int, lines: List[str], conversation_id: int
    ) -> str:
        base_url = str(model_config.get("api_base_url") or "").rstrip("/")
        if not base_url:
            raise GroupSummaryError("LLM 模型缺少 API 地址配置")
        headers = {}
        api_key = str(model_config.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model_config.get("model_id"),
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"【时间范围】近 {days} 天\n\n【群聊记录】\n" + "\n".join(lines),
                },
            ],
            "temperature": 0.4,
            "max_tokens": 1024,
            "stream": False,
        }
        # 交互调用快速模式：思考模型附 reasoning_effort:"low"，模型级
        # extra_body 显式配置优先（详见 llm_http）
        apply_interactive_fast_mode(payload, model_config)
        # 与问问微信同款：守护工作线程跑 HTTP，取消时 bridge 线程立即返回
        abort = threading.Event()
        try:
            body = run_cancelable(
                lambda: post_json_with_retries(
                    url=f"{base_url}/chat/completions",
                    payload=payload,
                    headers=headers,
                    timeout=LLM_TIMEOUT,
                    max_retries=LLM_MAX_RETRIES,
                    should_abort=abort.is_set,
                    log=logger.debug,
                    log_prefix="[群日报]",
                ),
                cancelled=lambda: take_llm_cancel(GS_CANCEL_SCOPE, conversation_id),
                on_cancel=abort.set,
                cancel_message="本次日报生成已取消",
            )
        except LLMRequestAborted as exc:
            raise GroupSummaryError(str(exc)) from exc
        except Exception as exc:
            logger.error("[群日报] LLM 调用失败: %s", exc)
            raise GroupSummaryError(f"模型调用失败：{exc}") from exc
        message_obj = (body.get("choices") or [{}])[0].get("message", {})
        content = str(message_obj.get("content") or message_obj.get("reasoning_content") or "")
        content = content.strip()
        if not content:
            raise GroupSummaryError("模型返回了空日报，请重试")
        return content
