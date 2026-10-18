"""问问微信：当前联系人历史自然语言问答（混合检索 + LLM 引用溯源）。

检索两路 RRF 融合：
- 关键词通道：jieba 分词后在 messages.content 上 LIKE 匹配
- 向量通道：问题嵌入与 sentiment_cache.embedding_vector 暴力余弦
  （复用联系人记忆索引落库的嵌入缓存，未建索引时该通道静默缺席；
  向量按联系人 LRU 缓存 + 指纹校验，不每次全表反序列化）

远程模型发送前问题与聊天记录逐条过 PrivacyRedactor（失败即阻断，
绝不降级发原文——问题里常直接含手机号/真实姓名，同样不能外发）；
回答要求带 [n] 引用编号，citations 按 [n] 过滤为实际引用子集，
引用原文（仅本地展示，不外发）随结果返回。

LLM 调用为交互式：短超时少重试，且支持取消（request_cancel 置位，
bridge 线程轮询后立即返回，在途请求在工作线程退出）。
"""
from __future__ import annotations

import logging
import pickle
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db
from ..realtime.llm_http import (
    LLMRequestAborted,
    apply_interactive_fast_mode,
    post_json_with_retries,
    request_llm_cancel,
    run_cancelable,
    take_llm_cancel,
)

logger = logging.getLogger(__name__)

try:
    import numpy as _np
except Exception:  # onnxruntime 环境必有 numpy；缺库退化为纯 Python 点积
    _np = None

# 检索规模：两路各取候选池，融合后截断
# 关键词通道按「每个关键词各自 top-N」取数：此前单条 OR 查询 LIMIT 全局
# 40，高频词把候选池刷满 newest，冷门关键词的更早消息永远进不了池
KEYWORD_PER_TERM_LIMIT = 12
VECTOR_POOL = 40
TOP_K = 12
RRF_K = 60
MAX_MESSAGE_CHARS = 200
# 多轮问答：携带的近期问答轮数与单段截断
HISTORY_TURNS = 3
HISTORY_TURN_CHARS = 400
# 交互式问答：短超时 + 少重试（默认 3 次重试最坏可挂 8 分钟，见取消机制）
LLM_TIMEOUT = 60
LLM_MAX_RETRIES = 1
# 交互式调用取消的 scope（llm_http 共享注册表）
QA_CANCEL_SCOPE = "history_qa"


def request_cancel(conversation_id: int) -> None:
    """标记取消某联系人的进行中提问（bridge 取消入口）。"""
    request_llm_cancel(QA_CANCEL_SCOPE, conversation_id)


def _escape_like(keyword: str) -> str:
    """LIKE 通配符转义（% _ \，配合 ESCAPE '\'）——用户问句里的百分号/
    下划线不应被当作通配符放大召回。"""
    return (
        str(keyword)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# ---------------------------------------------------------------------------
# 联系人级向量缓存：sentiment_cache 全表拉取 + 逐条 pickle 反序列化每次
# 提问重复做，正是 rag/retriever.py 头注释批评的反模式。LRU + 指纹校验：
# 指纹 = (向量行数, 最大 message_id)，新增/改写向量行即触发重建，免去
# 在 sentiment_service 写入路径挂失效钩子。指纹或行抓取失败均不缓存
# （瞬时 DB 异常不得把空结果毒化进缓存）。
# ---------------------------------------------------------------------------
_VECTOR_CACHE: Dict[int, Dict[str, Any]] = {}
_VECTOR_CACHE_LOCK = threading.Lock()
_VECTOR_CACHE_MAX = 4

SYSTEM_PROMPT = """你是聊天记录问答助手。只依据【聊天记录】回答【问题】，不允许编造记录里没有的内容。

规则：
- 回答末尾用 [n] 标注依据的记录编号（如 [2][5]），只引用真正用到的条目
- 【长期记忆】是从历史聊天提炼的背景参考，不是原文记录，禁止用 [n] 引用；与聊天记录冲突时以聊天记录为准
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
        from .onnx_inference import get_shared_engine, has_embedding_model

        if not has_embedding_model():
            return None
        engine = get_shared_engine("embedding")
        vector = engine.encode([str(question)])
        return list(vector[0]) if len(vector) else None
    except Exception as exc:
        logger.debug("[问问微信] 问题嵌入跳过（向量通道缺席）: %s", exc)
        return None


def _filter_citations(answer: str, citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只保留回答 [n] 实际引用的条目；条目 index 由调用方随后重排为连续序号。

    回答未带有效编号时返回空——模型没引用就不能把全量上下文冒充
    「引用溯源」展示。
    """
    cited = {int(n) for n in CITATION_MARK.findall(answer)}
    cited = {n for n in cited if 1 <= n <= len(citations)}
    if not cited:
        return []
    return [c for c in citations if c["index"] in cited]


def _strip_citation_marks(answer: str) -> str:
    """去掉回答里的 [n] 引用编号（引用条目单独展示），清理残留空白。"""
    stripped = CITATION_MARK.sub("", str(answer or ""))
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r"\s+([，。；、！？：）])", r"\1", stripped)
    return stripped.strip()


def _clip_text(text: str) -> str:
    """超长消息截断加省略号，不做硬切。"""
    text = str(text or "").strip()
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[: MAX_MESSAGE_CHARS - 1] + "…"


class HistoryQAService:
    """联系人历史问答：检索 → 脱敏 → LLM → 引用回填。"""

    def ask(
        self,
        conversation_id: int,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """多轮问答：history 为近期问答（时间升序，{question, answer}），
        用于理解「上次说的那件事」类指代并注入检索。"""
        question = str(question or "").strip()
        if not question:
            raise HistoryQAError("请输入问题")
        take_llm_cancel(QA_CANCEL_SCOPE, conversation_id)  # 清掉上一轮遗留的取消标记

        turns = self._normalize_history(history)
        # 检索问句并入上一问：指代消解不了的「那次/他说的那件事」靠
        # 上一问的实词补召回（仅取最近一问，避免旧问题稀释相关性）
        retrieval_query = f"{turns[-1]['question']} {question}" if turns else question

        account_wxid, display_name = self._load_conversation(conversation_id)
        records = self._retrieve(conversation_id, retrieval_query)
        if not records:
            raise HistoryQAError("没有找到与问题相关的聊天记录，试试换个说法或用更具体的关键词")

        redacted_question, redacted = self._redact_for_remote(
            question, records, account_wxid, conversation_id
        )
        redacted_turns = self._redact_history_for_remote(
            turns, account_wxid, conversation_id
        )
        # RAG 长期记忆槽：检索该联系人事实/主题段作背景参考（无索引/
        # 关闭/检索异常一律返回空，不阻断问答主链路）
        memories = self._retrieve_rag_memories(account_wxid, conversation_id, retrieval_query)
        if memories:
            memories = self._redact_memories_for_remote(
                memories, account_wxid, conversation_id
            )

        answer = self._call_llm(
            conversation_id, redacted_question, redacted,
            memories=memories, history=redacted_turns,
        )
        citations = [
            {
                "index": idx,  # 1 基编号，与回答 [n] 对应
                "message_id": rec["message_id"],
                "timestamp": rec["timestamp"],
                "is_sender": rec["is_sender"],
                "text": rec["text"],
            }
            for idx, rec in enumerate(records, start=1)
        ]
        citations = _filter_citations(answer, citations)
        # 回答正文去 [n] 编号（引用条目单独展示），引用重排为连续序号
        answer = _strip_citation_marks(answer)
        for idx, cite in enumerate(citations, start=1):
            cite["index"] = idx
        return {
            "answer": answer,
            "question": question,
            "contact_name": display_name,
            "citations": citations,
        }

    @staticmethod
    def _normalize_history(history: Any) -> List[Dict[str, str]]:
        """清洗前端传来的问答历史：只留成对的非空轮次，截最近几轮。"""
        if not isinstance(history, (list, tuple)):
            return []
        turns: List[Dict[str, str]] = []
        for item in history[-HISTORY_TURNS:]:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or "").strip()
            a = str(item.get("answer") or "").strip()
            if q and a:
                turns.append(
                    {
                        "question": q[:HISTORY_TURN_CHARS],
                        "answer": a[:HISTORY_TURN_CHARS],
                    }
                )
        return turns

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
        # 无需字符预算裁剪：硬上界 = TOP_K × MAX_MESSAGE_CHARS（12×200=2400），
        # 常量大幅上调时再引入预算逻辑（曾有按相关度丢弃的装填分支，
        # 现配常量下永不可达，属误导性复杂度，已删）
        for rec in ranked:
            rec["text"] = _clip_text(rec["text"])
        # 按时间升序组上下文（符合对话直觉）
        ranked.sort(key=lambda r: r["timestamp"])
        return ranked

    def _keyword_channel(self, conversation_id: int, question: str) -> List[Dict[str, Any]]:
        """逐关键词各自取最近 N 条命中后合并去重（单语句 UNION ALL）。

        单条 OR 查询全局 LIMIT 的老做法下，高频词（「我们」「聊天」）
        会把 newest 候选池刷满，冷门关键词更早但更相关的消息永远
        进不了池——这正是「问问微信答非所问」的主要来源。逐词取数
        合成一条 UNION ALL 语句执行：语义与逐词循环查询完全一致，
        但只占一次 DB 往返，不再串行跑最多 8 次查询。
        """
        keywords = _extract_keywords(question)
        if not keywords:
            return []
        # SQLite 复合语句不接受括号臂，每词的 LIMIT 须内嵌为 FROM 子查询
        branches = " UNION ALL ".join(
            "SELECT * FROM (SELECT id, timestamp, is_sender, content, ? AS term_rank "
            "FROM messages "
            "WHERE conversation_id = ? AND message_type = 1 "
            "AND length(content) > 0 AND content LIKE ? ESCAPE '\\' "
            "ORDER BY timestamp DESC LIMIT %d)" % KEYWORD_PER_TERM_LIMIT
            for _ in keywords
        )
        params: List[Any] = []
        for rank, kw in enumerate(keywords):
            params.extend([rank, conversation_id, f"%{_escape_like(kw)}%"])
        try:
            rows = get_db().execute(
                f"SELECT id, timestamp, is_sender, content FROM ({branches}) "
                "ORDER BY term_rank, timestamp DESC",
                params,
            ).fetchall()
        except Exception as exc:
            logger.warning("[问问微信] 关键词检索失败: %s", exc)
            return []
        merged: List[Dict[str, Any]] = []
        seen: set = set()
        for row in rows:
            rec = self._row_to_record(row)
            if rec["message_id"] in seen:
                continue
            seen.add(rec["message_id"])
            merged.append(rec)
        return merged

    def _vector_channel(self, conversation_id: int, question: str) -> List[Dict[str, Any]]:
        vector = _load_question_vector(question)
        if not vector:
            return []
        entry = self._load_vector_cache(conversation_id)
        dim = len(vector)
        bucket = entry["by_dim"].get(dim)
        if not bucket:
            return []  # 该宽度无缓存向量（旧模型宽度不同，不参与比较）
        vectors, metas = bucket["vectors"], bucket["metas"]
        if _np is not None and vectors:
            scores = (
                _np.asarray(vectors, dtype=_np.float32)
                @ _np.asarray(vector, dtype=_np.float32)
            )
            order = sorted(range(len(metas)), key=lambda i: float(scores[i]), reverse=True)
        else:
            order = sorted(
                range(len(metas)),
                key=lambda i: sum(a * b for a, b in zip(vector, vectors[i])),
                reverse=True,
            )
        return [metas[i] for i in order[:VECTOR_POOL]]

    def _load_vector_cache(self, conversation_id: int) -> Dict[str, Any]:
        """联系人级向量缓存（指纹未变直接复用，免去每次全表 pickle 反序列化）。"""
        conversation_id = int(conversation_id)
        fingerprint = self._vector_fingerprint(conversation_id)
        if fingerprint is not None:
            with _VECTOR_CACHE_LOCK:
                entry = _VECTOR_CACHE.get(conversation_id)
                if entry is not None and entry["fingerprint"] == fingerprint:
                    # LRU 触碰：挪到插入序末尾
                    _VECTOR_CACHE.pop(conversation_id, None)
                    _VECTOR_CACHE[conversation_id] = entry
                    return entry

        rows = self._fetch_vector_rows(conversation_id)
        if rows is None:
            # 行抓取失败（瞬时 DB 异常）：本次按无向量降级为纯关键词，
            # 不缓存空结果——否则该联系人向量通道会被毒化到指纹变化为止
            return {"fingerprint": None, "by_dim": {}}
        by_dim: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            try:
                cached = pickle.loads(row[4])
            except Exception:
                continue
            if not isinstance(cached, list) or not cached:
                continue
            bucket = by_dim.setdefault(len(cached), {"vectors": [], "metas": []})
            bucket["vectors"].append(cached)
            bucket["metas"].append(self._row_to_record(row))

        entry = {"fingerprint": fingerprint, "by_dim": by_dim}
        if fingerprint is not None:
            # 指纹查询失败（瞬时 DB 异常）时不缓存，避免空结果毒化缓存
            with _VECTOR_CACHE_LOCK:
                _VECTOR_CACHE[conversation_id] = entry
                while len(_VECTOR_CACHE) > _VECTOR_CACHE_MAX:
                    _VECTOR_CACHE.pop(next(iter(_VECTOR_CACHE)))
        return entry

    @staticmethod
    def _vector_fingerprint(conversation_id: int) -> Optional[Tuple[int, int]]:
        """轻量指纹：向量行数 + 最大 message_id（新增/改写必变，代价一次聚合查询）。

        查询失败返回 None（调用方退化为不缓存的直查路径）。
        """
        try:
            row = get_db().execute(
                """
                SELECT COUNT(*), COALESCE(MAX(s.message_id), 0)
                FROM sentiment_cache s
                JOIN messages m ON m.id = s.message_id
                WHERE m.conversation_id = ? AND m.message_type = 1
                  AND length(m.content) > 0 AND s.embedding_vector IS NOT NULL
                """,
                (conversation_id,),
            ).fetchone()
            return (int(row[0] or 0), int(row[1] or 0))
        except Exception as exc:
            logger.warning("[问问微信] 向量指纹查询失败: %s", exc)
            return None

    @staticmethod
    def _fetch_vector_rows(conversation_id: int) -> Optional[List[Tuple]]:
        """全量向量行；查询失败返回 None（调用方不缓存空结果）。"""
        try:
            return get_db().execute(
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
            return None

    @staticmethod
    def _row_to_record(row: Tuple) -> Dict[str, Any]:
        return {
            "message_id": int(row[0]),
            "timestamp": int(row[1]),
            "is_sender": int(row[2] or 0),
            "text": str(row[3] or "").strip(),
        }

    # ---- 脱敏与 LLM ----

    def _redact_batch_for_remote(
        self,
        pairs: List[Tuple[str, str]],
        account_wxid: str,
        conversation_id: int,
    ) -> List[str]:
        """批量脱敏核心：pairs 为 (文本, source_id)。

        本地模型原样返回；远程模型逐条过 PrivacyRedactor，任何一条
        失败即整体阻断（红线：不降级发原文）。问题/记录/历史问答/长期
        记忆四个入口共用本方法，阻断规则单点维护。
        """
        from ..realtime.rag.config import is_remote_llm_model
        from ..realtime.rag.fact_llm import get_active_model_config

        model_config = get_active_model_config()
        if not model_config:
            raise HistoryQAError("未配置 LLM 模型，请先在设置中启用")
        if not is_remote_llm_model(model_config):
            return [text for text, _ in pairs]

        from ..realtime.privacy_redactor import PrivacyRedactor

        redactor = PrivacyRedactor(get_db())
        redacted: List[str] = []
        for text, source_id in pairs:
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
            redacted.append(result.redacted_text)
        return redacted

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
        texts = self._redact_batch_for_remote(
            [(question, "question")]
            + [(rec["text"], str(rec["message_id"])) for rec in records],
            account_wxid,
            conversation_id,
        )
        redacted = [
            {**rec, "text": text} for rec, text in zip(records, texts[1:])
        ]
        return texts[0], redacted

    # ---- RAG 长期记忆槽 ----

    RAG_MEMORY_LIMIT = 5

    def _retrieve_rag_memories(
        self, account_wxid: str, conversation_id: int, question: str
    ) -> List[str]:
        """检索该联系人 RAG 长期记忆（复用实时建议同款检索器+门控）。

        任何缺位（未建索引/关闭/超时降级/异常）都返回空列表，问答
        主链路只靠消息检索照常工作。
        """
        try:
            from ..realtime.rag.config import load_rag_settings
            from ..realtime.rag.retriever import RagRetriever

            if not load_rag_settings().get("rag_enabled"):
                return []
            result = RagRetriever().retrieve(
                account_wxid=account_wxid,
                conversation_id=int(conversation_id),
                query=str(question or ""),
                limit=self.RAG_MEMORY_LIMIT,
            )
            items = result.get("items") or []
            return [
                str(it.get("content") or "").strip()
                for it in items
                if str(it.get("content") or "").strip()
            ]
        except Exception as exc:
            # 静默吞掉曾让「记忆槽为何一直缺席」无从排查——留 WARNING 现场
            logger.warning("[问问微信] RAG 记忆槽检索失败（按无记忆继续）: %s", exc)
            return []

    def _redact_memories_for_remote(
        self, memories: List[str], account_wxid: str, conversation_id: int
    ) -> List[str]:
        """远程模型时长期记忆同样过脱敏（红线同消息记录：失败即阻断）。"""
        return self._redact_batch_for_remote(
            [
                (text, f"rag_memory_{idx}")
                for idx, text in enumerate(memories, 1)
            ],
            account_wxid,
            conversation_id,
        )

    def _redact_history_for_remote(
        self,
        turns: List[Dict[str, str]],
        account_wxid: str,
        conversation_id: int,
    ) -> List[Dict[str, str]]:
        """远程模型时历史问答同样过脱敏（红线同消息记录：失败即阻断）。

        历史来自前端回传，虽然产出时已脱敏过，仍按不可信输入处理。
        """
        pairs = [
            (turn[field], f"qa_history_{idx}_{field}")
            for idx, turn in enumerate(turns, 1)
            for field in ("question", "answer")
        ]
        texts = iter(self._redact_batch_for_remote(pairs, account_wxid, conversation_id))
        return [{"question": next(texts), "answer": next(texts)} for _ in turns]

    def _call_llm(
        self,
        conversation_id: int,
        question: str,
        records: List[Dict[str, Any]],
        memories: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        from ..realtime.rag.fact_llm import get_active_model_config

        model_config = get_active_model_config()
        if not model_config:
            raise HistoryQAError("未配置 LLM 模型，请先在设置中启用")

        lines = []
        for idx, rec in enumerate(records, start=1):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(rec["timestamp"]))
            who = "我" if rec["is_sender"] == 1 else "对方"
            lines.append(f"[{idx}] {when} {who}: {rec['text']}")
        history_block = ""
        if history:
            qa_lines = "\n".join(
                f"问：{t['question']}\n答：{t['answer']}" for t in history
            )
            history_block = (
                "\n\n【历史问答】（此前的问答，帮助理解指代；不是聊天记录，"
                "禁止用 [n] 引用）\n" + qa_lines
            )
        memory_block = ""
        if memories:
            memory_lines = "\n".join(f"- {m}" for m in memories)
            memory_block = (
                "\n\n【长期记忆】（从历史聊天提炼的背景参考，非原文记录）\n"
                + memory_lines
            )
        user_prompt = (
            f"【问题】{question}" + history_block + memory_block
            + "\n\n【聊天记录】\n" + "\n".join(lines)
        )

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
        # 交互调用快速模式：思考模型附 reasoning_effort:"low"，模型级
        # extra_body 显式配置优先（详见 llm_http）
        apply_interactive_fast_mode(payload, model_config)

        # HTTP 跑守护工作线程（在途 socket 无法强断，取消时 bridge 线程
        # 立即返回，工作线程经 should_abort 在尝试边界自行退出）
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
                    log_prefix="[问问微信]",
                ),
                cancelled=lambda: take_llm_cancel(QA_CANCEL_SCOPE, conversation_id),
                on_cancel=abort.set,
                cancel_message="本次提问已取消",
            )
        except LLMRequestAborted as exc:
            raise HistoryQAError(str(exc)) from exc
        except Exception as exc:
            logger.error("[问问微信] LLM 调用失败: %s", exc)
            raise HistoryQAError(f"模型调用失败：{exc}") from exc

        content = self._extract_content(body or {})
        if not content:
            raise HistoryQAError(
                "模型返回了空回答，请重试；若用的是纯思考模式模型，请在模型设置中关闭"
            )
        return content

    @staticmethod
    def _extract_content(body: Dict[str, Any]) -> str:
        message_obj = (body.get("choices") or [{}])[0].get("message", {})
        content = str(message_obj.get("content") or "").strip()
        if content:
            return content
        # 思考模型正文为空常因 max_tokens 耗尽在思考段：不把 reasoning_content
        # 当回答吐给用户（那是思维链不是答案），留现场便于排查
        reasoning = str(message_obj.get("reasoning_content") or "")
        if reasoning:
            choices = body.get("choices") or [{}]
            logger.warning(
                "[问问微信] 回答为空但 reasoning_content 非空（长度 %d，finish=%s）",
                len(reasoning),
                (choices[0] or {}).get("finish_reason"),
            )
        return ""
