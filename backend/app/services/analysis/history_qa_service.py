"""问问微信：当前联系人历史自然语言问答（混合检索 + LLM 引用溯源）。

检索两路 RRF 融合：
- 关键词通道：jieba 分词后在 messages.content 上 LIKE 匹配
- 向量通道：问题嵌入与 sentiment_cache.embedding_vector 暴力余弦
  （复用联系人记忆索引落库的嵌入缓存，未建索引时该通道静默缺席）

远程模型发送前问题与聊天记录逐条过 PrivacyRedactor（失败即阻断，
绝不降级发原文——问题里常直接含手机号/真实姓名，同样不能外发）；
回答要求带 [n] 引用编号，citations 按 [n] 过滤为实际引用子集，
引用原文（仅本地展示，不外发）随结果返回。
"""
from __future__ import annotations

import logging
import pickle
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db
from ..realtime.llm_http import post_json_with_retries

logger = logging.getLogger(__name__)

# 检索规模：两路各取候选池，融合后截断
KEYWORD_POOL = 40
VECTOR_POOL = 40
TOP_K = 12
RRF_K = 60
# 上下文预算：检索消息总字符上限（超限从相关度最低的开始丢弃）
MAX_CONTEXT_CHARS = 6000
MAX_MESSAGE_CHARS = 200
LLM_TIMEOUT = 120

SYSTEM_PROMPT = """你是聊天记录问答助手。只依据【聊天记录】回答【问题】，不允许编造记录里没有的内容。

规则：
- 回答末尾用 [n] 标注依据的记录编号（如 [2][5]），只引用真正用到的条目
- 记录不足以回答时，直接说明「聊天记录中没有足够信息」，不要猜测
- 引用原文时保持原样，不要改写称谓
- 回答用中文，简洁直接，先给结论再给依据"""

# 回答中的引用编号（[n]，n 对应聊天记录列表的 1 基序号）
CITATION_MARK = re.compile(r"\[(\d+)\]")


class HistoryQAError(Exception):
    """问答失败（无记录/无模型/脱敏阻断等，message 面向用户展示）"""


def _extract_keywords(question: str) -> List[str]:
    """问题分词取检索关键词（jieba 优先，缺库退化为剔除单字/停用片段）。"""
    text = re.sub(r"[，。？！、；：,.?!;:\s]+", " ", str(question or "")).strip()
    if not text:
        return []
    try:
        import jieba

        words = [w.strip() for w in jieba.cut(text)]
    except Exception:
        words = text.split(" ")
    # 单字与纯符号无区分度：只留 >=2 字的实词片段
    return [w for w in words if w and len(w) >= 2][:8]


def _load_question_vector(question: str) -> Optional[List[float]]:
    """问题嵌入（与分析同源 ONNX 引擎；模型不可用时返回 None 走纯关键词）。"""
    try:
        from .onnx_inference import get_shared_engine, has_onnx_models

        if not has_onnx_models():
            return None
        engine = get_shared_engine("embedding")
        vector = engine.encode([str(question)])
        return list(vector[0]) if len(vector) else None
    except Exception as exc:
        logger.debug("[问问微信] 问题嵌入跳过（向量通道缺席）: %s", exc)
        return None


def _filter_citations(answer: str, citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只保留回答 [n] 实际引用的条目；回答未带有效编号时退回全集。"""
    cited = {int(n) for n in CITATION_MARK.findall(answer)}
    cited = {n for n in cited if 1 <= n <= len(citations)}
    if not cited:
        return citations
    return [c for i, c in enumerate(citations, start=1) if i in cited]


class HistoryQAService:
    """联系人历史问答：检索 → 脱敏 → LLM → 引用回填。"""

    def ask(self, conversation_id: int, question: str) -> Dict[str, Any]:
        question = str(question or "").strip()
        if not question:
            raise HistoryQAError("请输入问题")

        account_wxid, display_name = self._load_conversation(conversation_id)
        records = self._retrieve(conversation_id, question)
        if not records:
            raise HistoryQAError("没有找到与问题相关的聊天记录，试试换个说法或用更具体的关键词")

        redacted_question, redacted = self._redact_for_remote(
            question, records, account_wxid, conversation_id
        )

        answer = self._call_llm(redacted_question, redacted)
        citations = [
            {
                "message_id": rec["message_id"],
                "timestamp": rec["timestamp"],
                "is_sender": rec["is_sender"],
                "text": rec["text"],
            }
            for rec in records
        ]
        return {
            "answer": answer,
            "question": question,
            "contact_name": display_name,
            "citations": _filter_citations(answer, citations),
        }

    # ---- 检索 ----

    def _load_conversation(self, conversation_id: int) -> Tuple[str, str]:
        row = get_db().execute(
            "SELECT account_wxid, display_name FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise HistoryQAError("会话不存在")
        return str(row[0] or ""), str(row[1] or "")

    def _retrieve(self, conversation_id: int, question: str) -> List[Dict[str, Any]]:
        """关键词 + 向量两路召回，RRF 融合取 TOP_K，按时间升序组上下文。"""
        keyword_rows = self._keyword_channel(conversation_id, question)
        vector_rows = self._vector_channel(conversation_id, question)

        # RRF：每路按序贡献 1/(K+rank)，两路同名消息得分累加
        fused: Dict[int, Dict[str, Any]] = {}
        for rows in (keyword_rows, vector_rows):
            for rank, row in enumerate(rows):
                item = fused.setdefault(
                    row["message_id"],
                    {
                        "message_id": row["message_id"],
                        "timestamp": row["timestamp"],
                        "is_sender": row["is_sender"],
                        "text": row["text"],
                        "score": 0.0,
                    },
                )
                item["score"] += 1.0 / (RRF_K + rank + 1)

        ranked = sorted(fused.values(), key=lambda r: r["score"], reverse=True)[:TOP_K]
        # 上下文按时间升序排列（符合对话直觉），并裁剪总字符预算
        ranked.sort(key=lambda r: r["timestamp"])
        kept: List[Dict[str, Any]] = []
        total = 0
        for rec in ranked:
            text = rec["text"][:MAX_MESSAGE_CHARS]
            if total + len(text) > MAX_CONTEXT_CHARS and kept:
                break
            rec["text"] = text
            kept.append(rec)
            total += len(text)
        return kept

    def _keyword_channel(self, conversation_id: int, question: str) -> List[Dict[str, Any]]:
        keywords = _extract_keywords(question)
        if not keywords:
            return []
        conditions = " OR ".join(["content LIKE ?"] * len(keywords))
        params: List[Any] = [conversation_id]
        params.extend(f"%{kw}%" for kw in keywords)
        try:
            rows = get_db().execute(
                f"""
                SELECT id, timestamp, is_sender, content
                FROM messages
                WHERE conversation_id = ? AND message_type = 1
                  AND length(content) > 0 AND ({conditions})
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (*params, KEYWORD_POOL),
            ).fetchall()
        except Exception as exc:
            logger.warning("[问问微信] 关键词检索失败: %s", exc)
            return []
        return [self._row_to_record(r) for r in rows]

    def _vector_channel(self, conversation_id: int, question: str) -> List[Dict[str, Any]]:
        vector = _load_question_vector(question)
        if not vector:
            return []
        try:
            rows = get_db().execute(
                """
                SELECT m.id, m.timestamp, m.is_sender, m.content, s.embedding_vector
                FROM sentiment_cache s
                JOIN messages m ON m.id = s.message_id
                WHERE m.conversation_id = ? AND m.message_type = 1
                  AND length(m.content) > 0 AND s.embedding_vector IS NOT NULL
                """,
                (conversation_id,),
            ).fetchall()
        except Exception as exc:
            logger.warning("[问问微信] 向量检索失败: %s", exc)
            return []

        dim = len(vector)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for row in rows:
            try:
                cached = pickle.loads(row[4])
            except Exception:
                continue
            if not isinstance(cached, list) or len(cached) != dim:
                continue  # 旧模型宽度不同，跳过不参与比较
            # 缓存向量与问题向量均已 L2 归一，点积即余弦
            cos = sum(a * b for a, b in zip(vector, cached))
            scored.append((cos, self._row_to_record(row)))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [rec for _, rec in scored[:VECTOR_POOL]]

    @staticmethod
    def _row_to_record(row: Tuple) -> Dict[str, Any]:
        return {
            "message_id": int(row[0]),
            "timestamp": int(row[1]),
            "is_sender": int(row[2] or 0),
            "text": str(row[3] or "").strip(),
        }

    # ---- 脱敏与 LLM ----

    def _redact_for_remote(
        self,
        question: str,
        records: List[Dict[str, Any]],
        account_wxid: str,
        conversation_id: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """远程模型：问题与记录逐条脱敏；任何一条失败即整体阻断（红线：不降级发原文）。

        问题同样过脱敏——用户常把手机号/真实姓名直接写进问题。
        本地模型原样返回。
        """
        from ..realtime.rag.config import is_remote_llm_model
        from ..realtime.rag.fact_llm import get_active_model_config

        model_config = get_active_model_config()
        if not model_config:
            raise HistoryQAError("未配置 LLM 模型，请先在设置中启用")
        if not is_remote_llm_model(model_config):
            return question, records

        from ..realtime.privacy_redactor import PrivacyRedactor

        redactor = PrivacyRedactor(get_db())

        def _redact(text: str, source_id: str) -> str:
            try:
                result = redactor.redact(
                    text,
                    account_wxid=account_wxid,
                    conversation_id=conversation_id,
                    source_table="history_qa",
                    source_id=source_id,
                )
            except Exception as exc:
                raise HistoryQAError(f"脱敏失败，本次提问已阻断：{exc}") from exc
            return result.redacted_text

        redacted_question = _redact(question, "question")
        redacted = [
            {**rec, "text": _redact(rec["text"], str(rec["message_id"]))} for rec in records
        ]
        return redacted_question, redacted

    def _call_llm(self, question: str, records: List[Dict[str, Any]]) -> str:
        from ..realtime.rag.fact_llm import get_active_model_config

        model_config = get_active_model_config()
        if not model_config:
            raise HistoryQAError("未配置 LLM 模型，请先在设置中启用")

        lines = []
        for idx, rec in enumerate(records, start=1):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(rec["timestamp"]))
            who = "我" if rec["is_sender"] == 1 else "对方"
            lines.append(f"[{idx}] {when} {who}: {rec['text']}")
        user_prompt = f"【问题】{question}\n\n【聊天记录】\n" + "\n".join(lines)

        base_url = str(model_config.get("api_base_url") or "").rstrip("/")
        if not base_url:
            raise HistoryQAError("LLM 模型缺少 API 地址配置")
        headers = {}
        api_key = str(model_config.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model_config.get("model_id"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
            "stream": False,
        }
        try:
            body = post_json_with_retries(
                url=f"{base_url}/chat/completions",
                payload=payload,
                headers=headers,
                timeout=LLM_TIMEOUT,
                log=logger.debug,
                log_prefix="[问问微信]",
            )
        except Exception as exc:
            logger.error("[问问微信] LLM 调用失败: %s", exc)
            raise HistoryQAError(f"模型调用失败：{exc}") from exc

        content = self._extract_content(body)
        if not content:
            raise HistoryQAError("模型返回了空回答，请重试或换个问法")
        return content

    @staticmethod
    def _extract_content(body: Dict[str, Any]) -> str:
        message_obj = (body.get("choices") or [{}])[0].get("message", {})
        content = str(message_obj.get("content") or "")
        if not content:
            # 思考模型可能把正文写进 reasoning_content
            content = str(message_obj.get("reasoning_content") or "")
        return content.strip()
