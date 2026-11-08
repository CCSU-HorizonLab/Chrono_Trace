"""问问微信 + 回复陪练：当前联系人的两类对话式 AI（智囊页问答/陪练模式）。

问答：混合检索 + LLM 引用溯源。检索两路 RRF 融合：
- 关键词通道：jieba 分词后在 messages.content 上 LIKE 匹配
- 向量通道：问题嵌入与 sentiment_cache.embedding_vector 暴力余弦
  （复用联系人记忆索引落库的嵌入缓存，未建索引时该通道静默缺席；
  向量按联系人 LRU 缓存 + 指纹校验，不每次全表反序列化）

中文单语口径：嵌入模型（bge-small-zh）与 jieba 分词均为中文语料训练，
英文问题经分词退化后的片段只构成字面召回、不构成语义对齐保证——
微信记录以中文为绝对主体，跨语检索刻意不做。

陪练（rehearse）：贴一段 TA 发来的消息 → 三个温度档（稳一稳/进一步/
缓一缓）回复方向 + 后果预判。上下文三路：近期对话窗口、消息本身为
查询的语义相关历史、RAG 长期记忆。

远程模型发送前问题与聊天记录逐条过 PrivacyRedactor（失败即阻断，
绝不降级发原文——问题里常直接含手机号/真实姓名，同样不能外发）；
问答回答要求带 [n] 引用编号，citations 按 [n] 过滤为实际引用子集，
引用原文（仅本地展示，不外发）随结果返回。

LLM 调用为交互式：短超时少重试，且支持取消（request_cancel 置位，
bridge 线程轮询后立即返回，在途请求在工作线程退出）。问答与陪练
共用会话级串行门闩与取消 scope——同会话一次只有一个在途请求。
"""
from __future__ import annotations

import json
import logging
import pickle
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from ...db.connection import get_db
from ..realtime.llm_http import (
    LLMRequestAborted,
    apply_interactive_fast_mode,
    post_json_stream,
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
TOP_K = 16
RRF_K = 60
# 查询词覆盖率乘性因子（借鉴 offline-kb 的 coverage 设计）：融合分乘
# BASE + (1-BASE)×coverage——「7 个查询词只碰中 1 个」的碰撞候选压到
# 0.45 倍，多词命中的候选相对上浮。RRF 纯排名轴对此无惩罚：碰巧含
# 一个高频词的最新消息能在单路排 rank1。只重排不删除，纯向量召回
# （语义相关但零字面命中，乘到底 0.45）只要 RRF 分尚可仍在 TOP_K 内
COVERAGE_BASE = 0.45
MAX_MESSAGE_CHARS = 250
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


class HistoryQABlocked(HistoryQAError):
    """脱敏阻断（红线）：失败即阻断，不降级发原文、不回退检索直出。"""


class HistoryQACancelled(HistoryQAError):
    """用户主动取消：不回退检索直出（取消就是不要结果）。"""


# ---------------------------------------------------------------------------
# 陪练模式（智囊页）：贴一段收到的消息 → 三个温度档回复方向 + 后果预判
# ---------------------------------------------------------------------------

# 温度三档固定口径（重设计 §4.4「2-3 个不同温度的回复方向及后果预判」）
REHEARSAL_TONES = ("steady", "closer", "cooler")

REHEARSAL_SYSTEM_PROMPT = """你是微信回复参谋。用户收到对方一条消息不知怎么回，你依据背景资料给出 3 个不同温度的回复方向。

温度三档固定（tone 只能取这三个值）：
- steady 稳一稳：接住话题但不推进，最不容易出错
- closer 进一步：在稳的基础上带一点主动，小幅升温
- cooler 缓一缓：礼貌回应但保留空间，适当降温

只输出一个 JSON 对象，不要输出其他文字：
{"options": [{"tone": "steady", "label": "四字以内档名", "direction": "这个方向怎么拿捏（一句话）", "draft": "可直接参考的回复草稿，口语短句，六十字以内", "consequence": "这么回之后关系的可能走向（一句话）"}]}

规则：
- draft 要像本人发微信的口吻：口语、短句、可用表情；禁止 AI 腔与书面语
- 背景资料不足以判断对方偏好的，direction 里明说依据不足，不要编造
- 三档草稿之间要有明显温差，不要写成三句差不多的话"""

# 陪练近期对话窗口：时间近邻语境优先于全历史检索（「怎么回」先看刚才聊到哪）
REHEARSAL_RECENT_LIMIT = 20
# 陪练一次调用的输出预算：三档 JSON 结构化文本
REHEARSAL_MAX_TOKENS = 1024


# 会话级串行门闩：取消标记按 (scope, conversation_id) 定址且单消费，
# 并发的两个 ask 共享一枚标记时，谁的轮询点先到谁消费——「停止后立即
# 重发」会把用户刚发的新问题杀掉而旧问题跑完（方向恰好反了）。串行后
# 标记属主明确：新请求等旧请求真正退出，再清死残留标记自己起步
_QA_INFLIGHT_LOCK = threading.Lock()
_QA_CONV_LOCKS: dict = {}


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
    # 停用词与 RAG 门控同一份表（延迟导入：问答不硬依赖 realtime 包路径）
    try:
        from ..realtime.rag.relevance_gate import RagRelevanceGate

        stopwords = RagRelevanceGate.QUERY_STOPWORDS
    except Exception:
        stopwords = frozenset()
    # 单字/纯符号无区分度；去重保序——重复词只会重复命中同一批 LIKE
    # 行，还挤占 8 个检索槽位
    seen: set = set()
    kept: List[str] = []
    for w in words:
        if len(w) < 2 or w in stopwords or w in seen:
            continue
        seen.add(w)
        kept.append(w)
        if len(kept) >= 8:
            break
    return kept


def _load_question_vector(question: str) -> Optional[List[float]]:
    """问题嵌入（与分析/RAG 同源共享漏斗 L1→L2→ONNX；模型不可用返回 None）。

    此前直连 engine.encode 绕过 L1/L2——全仓唯一缓存旁路，且同一
    retrieval_query 随后在 RAG 记忆槽 retriever.embed_text 再嵌一次
    （旁路不写缓存故必 miss），每次问答同一文本 2 次 ONNX 推理；入
    漏斗后跨槽经 L2 归一、重复提问持久命中。服务实例模块级复用：
    L1 缓存是实例级 dict，每次 new 等于放弃进程内命中。
    """
    try:
        from .onnx_inference import has_embedding_model

        if not has_embedding_model():
            return None
        service = _qa_sentiment_service()
        vectors = service.embed_texts_batch([str(question)])
        return list(vectors[0]) if vectors and vectors[0] else None
    except Exception as exc:
        logger.debug("[问问微信] 问题嵌入跳过（向量通道缺席）: %s", exc)
        return None


_QA_SENTIMENT_SERVICE = None


def _qa_sentiment_service():
    """问答侧共享 SentimentService（模型懒加载，构造轻；复用保住 L1）。"""
    global _QA_SENTIMENT_SERVICE
    if _QA_SENTIMENT_SERVICE is None:
        from .sentiment_service import SentimentService

        _QA_SENTIMENT_SERVICE = SentimentService()
    return _QA_SENTIMENT_SERVICE


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


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中尽力提取一个可解析的 JSON 对象（陪练三档卡解析用）。

    与 realtime/suggestion_parsing 同思路的轻量版：剥离 ```json 代码围栏
    与思考模型的前后杂文字，取首个 { 到末个 } 的跨度解析；任何失败返回
    None（调用方按可重试错误处理，不猜结构）。
    """
    cleaned = str(text or "").strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1]
        cleaned = cleaned.split("```", 1)[0]
    elif cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-4] if len(cleaned) > 7 else ""
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


class HistoryQAService:
    """联系人历史问答：检索 → 脱敏 → LLM → 引用回填。"""

    @contextmanager
    def _serial_gate(self, conversation_id: int) -> Iterator[None]:
        """同会话串行门闩：问答与陪练共用（同取消 scope，一次只有一个在途）。

        拿锁瞬间之前注册的取消标记一律是死残留（指向的请求要么已消费、
        要么早已退出——如前端离开页面 onUnmounted 的无条件 cancel），
        入口清掉防毒化本轮；拿锁之后注册的才是对本轮的停止意图，交给
        轮询点生效（take_llm_cancel 的 before 界限，见 llm_http）。
        """
        key = int(conversation_id)
        with _QA_INFLIGHT_LOCK:
            gate = _QA_CONV_LOCKS.get(key)
            if gate is None:
                gate = threading.Lock()
                _QA_CONV_LOCKS[key] = gate
        with gate:
            take_llm_cancel(QA_CANCEL_SCOPE, conversation_id, before=time.time())
            yield

    def ask(
        self,
        conversation_id: int,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """多轮问答：history 为近期问答（时间升序，{question, answer}），
        用于理解「上次说的那件事」类指代并注入检索。

        on_delta：LLM 正文增量回调（打字机）。提供时走流式请求；取消/
        失败的终态语义不变——前端以 bridge 返回值为准，增量只管过程。

        同会话串行：重发等在途请求退出后再起步（见 _QA_CONV_LOCKS 注释）。"""
        with self._serial_gate(conversation_id):
            return self._ask(conversation_id, question, history, on_delta)

    def rehearse(
        self, conversation_id: int, received_text: str
    ) -> Dict[str, Any]:
        """陪练：贴一段 TA 发来的消息，给出三个温度档回复方向与后果预判。

        上下文三路（全走脱敏副本发远程）：近期对话窗口（时间近邻语境）、
        以消息本身为查询的语义相关历史（「TA 这类话以前怎么接的」）、
        RAG 长期记忆（沟通习惯背景）。与 ask 共用会话串行门闩和取消
        scope——同会话一次只有一个在途请求。"""
        with self._serial_gate(conversation_id):
            return self._rehearse(conversation_id, received_text)

    def _rehearse(self, conversation_id: int, received_text: str) -> Dict[str, Any]:
        received_text = str(received_text or "").strip()
        if not received_text:
            raise HistoryQAError("请先粘贴 TA 发来的消息")
        account_wxid, display_name = self._load_conversation(conversation_id)

        recent = self._recent_window(conversation_id, REHEARSAL_RECENT_LIMIT)
        recent_ids = {rec["message_id"] for rec in recent}
        related = [
            rec
            for rec in self._retrieve(conversation_id, received_text)
            if rec["message_id"] not in recent_ids
        ]
        memory_refs, _ = self._retrieve_rag_memories(
            account_wxid, conversation_id, received_text
        )

        # 四路输入统一过批量脱敏（红线同 ask：任何一条失败即阻断）
        texts = self._redact_batch_for_remote(
            [(received_text, "rehearsal_received")]
            + [(rec["text"], str(rec["message_id"])) for rec in recent + related]
            + [(m["content"], f"rehearsal_memory_{i}") for i, m in enumerate(memory_refs, 1)],
            account_wxid,
            conversation_id,
        )
        redacted_received = texts[0]
        redacted_recent = [
            {**rec, "text": t} for rec, t in zip(recent, texts[1 : 1 + len(recent)])
        ]
        redacted_related = [
            {**rec, "text": t}
            for rec, t in zip(related, texts[1 + len(recent) : 1 + len(recent) + len(related)])
        ]
        redacted_memories = texts[1 + len(recent) + len(related) :]

        user_prompt = self._build_rehearsal_prompt(
            redacted_received, redacted_recent, redacted_related, redacted_memories
        )
        content, _ = self._post_llm_chat(
            conversation_id,
            [
                {"role": "system", "content": REHEARSAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=REHEARSAL_MAX_TOKENS,
            log_prefix="[回复陪练]",
        )
        options = self._normalize_rehearsal_options(_extract_json_object(content))
        if not options:
            raise HistoryQAError("模型返回的回复方向无法解析，请重试")
        return {"ok": True, "contact_name": display_name, "options": options}

    def _recent_window(
        self, conversation_id: int, limit: int
    ) -> List[Dict[str, Any]]:
        """该会话最近 N 条文本消息（时间升序），近期语境的直取通道。"""
        rows = get_db().execute(
            "SELECT id, timestamp, is_sender, content FROM messages"
            " WHERE conversation_id = ? AND message_type = 1"
            " AND length(content) > 0"
            " ORDER BY timestamp DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        records = [self._row_to_record(row) for row in reversed(rows)]
        for rec in records:
            rec["text"] = _clip_text(rec["text"])
        return records

    @staticmethod
    def _build_rehearsal_prompt(
        received: str,
        recent: List[Dict[str, Any]],
        related: List[Dict[str, Any]],
        memories: List[str],
    ) -> str:
        def _line(rec: Dict[str, Any]) -> str:
            when = time.strftime("%m-%d %H:%M", time.localtime(rec["timestamp"]))
            who = "我" if rec["is_sender"] == 1 else "TA"
            return f"{when} {who}: {rec['text']}"

        parts = [f"【TA 的消息】{received}"]
        if recent:
            parts.append("【近期对话】（时间正序）\n" + "\n".join(map(_line, recent)))
        if related:
            parts.append(
                "【相关历史】（与这条消息语义相近的更早对话，供参考 TA 的习惯）\n"
                + "\n".join(map(_line, related))
            )
        if memories:
            parts.append(
                "【长期记忆】（从历史聊天提炼的背景参考）\n"
                + "\n".join(f"- {m}" for m in memories)
            )
        if len(parts) == 1:
            parts.append("（没有可用的背景资料，仅凭这条消息本身判断）")
        parts.append("请给出 3 个温度档的回复方向。")
        return "\n\n".join(parts)

    @staticmethod
    def _normalize_rehearsal_options(
        obj: Optional[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """LLM 输出 → 固定三档序的干净结构：非法 tone 丢弃、字段裁剪、
        重复档取首个。输出顺序不可信（模型可能先给 cooler），按
        REHEARSAL_TONES 固定序重排，前端渲染顺序稳定。"""
        raw = obj.get("options") if isinstance(obj, dict) else None
        if not isinstance(raw, list):
            return []
        clipped: Dict[str, Dict[str, str]] = {}
        limits = {"label": 8, "direction": 80, "draft": 120, "consequence": 80}
        for item in raw:
            if not isinstance(item, dict):
                continue
            tone = str(item.get("tone") or "").strip()
            if tone not in REHEARSAL_TONES or tone in clipped:
                continue
            entry = {
                field: str(item.get(field) or "").strip()[: cap]
                for field, cap in limits.items()
            }
            # draft 是用户真正要用的东西，空草稿的档位没有意义
            if not entry["draft"]:
                continue
            if not entry["label"]:
                entry["label"] = {"steady": "稳一稳", "closer": "进一步", "cooler": "缓一缓"}[tone]
            clipped[tone] = entry
        return [
            {"tone": tone, **clipped[tone]} for tone in REHEARSAL_TONES if tone in clipped
        ]

    def _ask(
        self,
        conversation_id: int,
        question: str,
        history: Optional[List[Dict[str, str]]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        question = str(question or "").strip()
        if not question:
            raise HistoryQAError("请输入问题")

        turns = self._normalize_history(history)
        # 检索问句并入上一问：指代消解不了的「那次/他说的那件事」靠
        # 上一问的实词补召回（仅取最近一问，避免旧问题稀释相关性）
        retrieval_query = f"{turns[-1]['question']} {question}" if turns else question

        account_wxid, display_name = self._load_conversation(conversation_id)
        records = self._retrieve(conversation_id, retrieval_query)
        if not records:
            raise HistoryQAError("没有找到与问题相关的聊天记录，试试换个说法或用更具体的关键词")

        # 引用全量先建（本地原文）：正常路径按 [n] 过滤为实际引用子集，
        # LLM 失败回退检索直出时全量带出
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
        try:
            redacted_question, redacted = self._redact_for_remote(
                question, records, account_wxid, conversation_id
            )
            redacted_turns = self._redact_history_for_remote(
                turns, account_wxid, conversation_id
            )
            # RAG 长期记忆槽：检索+门控该联系人事实/主题段作背景参考；门控
            # 全拒且判定 no_hit 时带「记忆库无此记录」提示（防从无关消息硬凑）
            memory_refs, memory_no_hit = self._retrieve_rag_memories(
                account_wxid, conversation_id, retrieval_query, turns=turns
            )
            memories: List[str] = []
            if memory_refs:
                # 远程模型只见脱敏副本；memory_refs（本地原文）随终态返回
                memories = self._redact_memories_for_remote(
                    [m["content"] for m in memory_refs], account_wxid, conversation_id
                )
            answer, truncated = self._call_llm(
                conversation_id, redacted_question, redacted,
                memories=memories, history=redacted_turns,
                memory_no_hit=memory_no_hit, on_delta=on_delta,
            )
        except (HistoryQABlocked, HistoryQACancelled):
            # 红线阻断与用户取消不回退（取消就是不要结果），原样上抛
            raise
        except HistoryQAError as exc:
            # LLM 层失败（未配置/网络抖动/空回答）不空手——借鉴 offline-kb
            # 的抽取式兜底：降级为检索直出，引用全量为本地原文，这一问
            # 不白费，用户仍能翻到相关记录自行核对
            return {
                "answer": (
                    f"模型暂不可用（{exc}），已降级为字面检索直出。"
                    "以下是与问题最相关的聊天记录，检查模型配置后可重试智能问答："
                ),
                "question": question,
                "contact_name": display_name,
                "citations": citations,
                "degraded": True,
            }
        citations = _filter_citations(answer, citations)
        # 回答正文去 [n] 编号（引用条目单独展示），引用重排为连续序号
        answer = _strip_citation_marks(answer)
        for idx, cite in enumerate(citations, start=1):
            cite["index"] = idx
        result = {
            "answer": answer,
            "question": question,
            "contact_name": display_name,
            "citations": citations,
        }
        if memory_refs:
            # 参考记忆溯源：AI 本轮回答实际采用的结构化记忆（敏感事实在
            # 检索层已被排除，不会出现在这里）
            result["memory_refs"] = memory_refs
        if truncated:
            # 流式中途断网：已收部分当结果，显式带标记（前端提示「已截断」，
            # 引用按截断文本实际到达的 [n] 过滤缩水属预期）
            result["truncated"] = True
        return result

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
        """关键词 + 向量两路召回，RRF 融合 × 词覆盖率因子，取 TOP_K，按时间升序组上下文。"""
        keywords = _extract_keywords(question)
        keyword_rows = self._keyword_channel(conversation_id, question, keywords)
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

        # 词覆盖率乘性因子：与 LIKE 同口径（SQLite LIKE 对 ASCII 不分
        # 大小写，中文无大小写），子串包含即命中
        if keywords:
            terms = [k.lower() for k in keywords]
            for item in fused.values():
                text = item["text"].lower()
                hit = sum(1 for k in terms if k in text)
                item["score"] *= COVERAGE_BASE + (1.0 - COVERAGE_BASE) * hit / len(terms)

        ranked = sorted(fused.values(), key=lambda r: r["score"], reverse=True)[:TOP_K]
        # 无需字符预算裁剪：硬上界 = TOP_K × MAX_MESSAGE_CHARS（16×250=4000），
        # 常量大幅上调时再引入预算逻辑（曾有按相关度丢弃的装填分支，
        # 现配常量下永不可达，属误导性复杂度，已删）
        for rec in ranked:
            rec["text"] = _clip_text(rec["text"])
        # 按时间升序组上下文（符合对话直觉）
        ranked.sort(key=lambda r: r["timestamp"])
        return ranked

    def _keyword_channel(
        self, conversation_id: int, question: str, keywords: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """逐关键词各自取最近 N 条命中后合并去重（单语句 UNION ALL）。

        单条 OR 查询全局 LIMIT 的老做法下，高频词（「我们」「聊天」）
        会把 newest 候选池刷满，冷门关键词更早但更相关的消息永远
        进不了池——这正是「问问微信答非所问」的主要来源。逐词取数
        合成一条 UNION ALL 语句执行：语义与逐词循环查询完全一致，
        但只占一次 DB 往返，不再串行跑最多 8 次查询。
        keywords 由 _retrieve 传入（分词一次两处用）；None 时自提取。
        """
        if keywords is None:
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
            if _np is not None and isinstance(cached, _np.ndarray):
                cached = cached.astype(_np.float32).tolist()  # float16 紧凑行
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
                raise HistoryQABlocked(f"脱敏失败，本次提问已阻断：{exc}") from exc
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
    # 放宽到 2s：大索引冷启动首次暖机常超检索器默认 800ms，超时静默
    # 等于记忆槽长期缺席。最坏多等 1.2s，换语义召回完整走完
    RAG_MEMORY_TIMEOUT_MS = 2000
    # 问答侧事实线比实时链路（settings 默认 0.30）收紧：融合分含
    # confidence×0.2 与 kind 加分 0.1 的恒定抬升，实测无关事实融合分
    # 落 0.35-0.40（纯向量余弦仅 0.26-0.31，真命中 0.68+）。实时链路
    # 0.30 线为 memory_request 低分兜底而设；问答直答没有该语义，
    # 沿用会放进无关事实，收到 0.42（≈纯向量 0.40，中等相关及以上）
    RAG_FACT_SCORE_THRESHOLD = 0.42

    def _retrieve_rag_memories(
        self,
        account_wxid: str,
        conversation_id: int,
        question: str,
        turns: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """检索并门控该联系人 RAG 长期记忆（复用实时建议同款检索器+门控）。

        返回 (memory_refs, no_hit)：refs 为结构化引用（content 本地原文，
        供前端「参考记忆」展示与就地纠错；发给远程 LLM 的文本由调用方
        另行走脱敏副本）。no_hit=True 表示检索有结果但全被门控拒——调用
        方注入「记忆库无此记录」提示，防 LLM 从无关消息硬凑（skip=低质/
        离题/超时降级则静默，不打扰）。任何缺位（未建索引/关闭/异常）
        返回 ([], False)，问答主链路只靠消息检索照常工作。
        """
        try:
            from ..realtime.memory_intent import detect_memory_intent
            from ..realtime.rag.config import load_rag_settings
            from ..realtime.rag.relevance_gate import RagRelevanceGate
            from ..realtime.rag.retriever import get_retriever

            if not load_rag_settings().get("rag_enabled"):
                return [], False
            # 多轮问答：历史问句并入 user_context——指代延续识别
            # （"上次说的那件事"）能吃到上一问的实词
            user_context = [
                {"role": "user", "content": t["question"]} for t in (turns or [])
            ] + [{"role": "user", "content": str(question or "")}]
            memory_intent = detect_memory_intent({"user_context": user_context})
            result = get_retriever().retrieve(
                account_wxid=account_wxid,
                conversation_id=int(conversation_id),
                query=str(question or ""),
                limit=self.RAG_MEMORY_LIMIT,
                timeout_ms=self.RAG_MEMORY_TIMEOUT_MS,
            )
            items = result.get("items") or []
            decision = RagRelevanceGate(
                fact_score_threshold=self.RAG_FACT_SCORE_THRESHOLD
            ).decide(
                query=str(question or ""),
                items=items,
                strategy=result.get("strategy"),
                output_mode="reply",          # 问答是直答不是建议卡
                trigger_type="memory_search", # 问答即显式记忆查询
                memory_intent=memory_intent.to_dict(),
                timed_out=bool(result.get("timed_out")),
                degraded_reason=result.get("degrade_reason"),
            )
            if decision.decision not in {"inject", "weak_inject"}:
                # 检索空手（no_hit）与「有结果但全在阈值线下」（low_score）
                # 对问答同义——记忆库没有相关记录，都给提示防 LLM 从
                # 无关消息硬凑；off_topic/超时/降级保持静默
                return [], decision.decision == "no_hit" or decision.reason == "low_score"

            def _content(it: Dict[str, Any]) -> str:
                # 事实通道平铺 content；文档通道只有嵌套 doc（此前按平铺
                # 取值，文档通道结果被静默丢弃）
                doc = it.get("doc") or {}
                return str(it.get("content") or doc.get("content") or "").strip()

            # 结构化引用：content 为本地原文（远程 LLM 只见脱敏副本）；
            # fact_memory 的 ref_id 是 rag_facts 主键——前端就地纠错的锚点
            refs: List[Dict[str, Any]] = []
            for it in items:
                if not it.get("_rag_gate_selected"):
                    continue
                content = _content(it)
                if not content:
                    continue
                doc = it.get("doc") or {}
                doc_type = str(it.get("doc_type") or doc.get("doc_type") or "unknown")
                # ref_id 一律是 rag_facts 主键（纠错按钮的锚点）：事实通道
                # 平铺 document_id；文档通道取 rag_documents.fact_id 外键，
                # 不取 doc.id——那是文档主键，跨表喂给 set_fact_feedback
                # 会改错对象。fact_id 挂不上（影子层关闭）时为 0，前端不渲染按钮
                refs.append(
                    {
                        "content": content,
                        "source": doc_type,
                        "ref_id": int(it.get("document_id") or doc.get("fact_id") or 0),
                        "subject": str(it.get("subject") or ""),
                        "as_of": it.get("as_of") or doc.get("source_ts"),
                        "confidence": it.get("fact_confidence"),
                    }
                )
            return refs, False
        except Exception as exc:
            # 静默吞掉曾让「记忆槽为何一直缺席」无从排查——留 WARNING 现场
            logger.warning("[问问微信] RAG 记忆槽检索失败（按无记忆继续）: %s", exc)
            return [], False

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
        memory_no_hit: bool = False,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, bool]:
        """返回 (正文, 是否截断)。截断 = 流式中途断网已收部分被当结果——
        调用方带出标记，前端显式提示而非把缩水答案当完整回答。"""
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
        elif memory_no_hit:
            # 门控判定检索有结果但无一可靠（低分/离题全拒）——显式告知
            # 无记录，防模型从无关聊天记录硬凑具体时间/地点/偏好
            memory_block = (
                "\n\n【长期记忆】该联系人的记忆库中没有与此问题直接相关"
                "的可靠记录；不要从无关聊天记录推断具体的时间、地点、"
                "偏好等事实，没有依据就明说不确定。\n"
            )
        user_prompt = (
            f"【问题】{question}" + history_block + memory_block
            + "\n\n【聊天记录】\n" + "\n".join(lines)
        )

        return self._post_llm_chat(
            conversation_id,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
            on_delta=on_delta,
        )

    def _post_llm_chat(
        self,
        conversation_id: int,
        messages: List[Dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        on_delta: Optional[Callable[[str], None]] = None,
        log_prefix: str = "[问问微信]",
    ) -> Tuple[str, bool]:
        """问答/陪练共用的交互式 LLM 调用骨架：模型配置校验 → 组包 →
        流式（可选）→ 守护线程 + 同 scope 取消 → 正文提取。

        返回 (正文, 是否截断)。截断 = 流式中途断网已收部分被当结果——
        调用方带出标记，前端显式提示而非把缩水答案当完整回答。"""
        from ..realtime.rag.fact_llm import get_active_model_config

        model_config = get_active_model_config()
        if not model_config:
            raise HistoryQAError("未配置 LLM 模型，请先在设置中启用")

        base_url = str(model_config.get("api_base_url") or "").rstrip("/")
        if not base_url:
            raise HistoryQAError("LLM 模型缺少 API 地址配置")
        headers = {}
        api_key = str(model_config.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model_config.get("model_id"),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 打字机输出走 SSE；端点不认 stream / 零 delta 瞬态失败时流式
            # 层抛回，此处回退整段（自带重试与 reasoning_effort 摘参），
            # 打字机缺席但回答照常
            "stream": on_delta is not None,
        }
        # 交互调用快速模式：思考模型附 reasoning_effort:"low" 兜底（含
        # glm-4.5+ 特例），模型级 extra_body 显式配置优先（详见 llm_http）
        apply_interactive_fast_mode(payload, model_config)

        def _post_full() -> Dict[str, Any]:
            return post_json_with_retries(
                url=f"{base_url}/chat/completions",
                payload=payload,
                headers=headers,
                timeout=LLM_TIMEOUT,
                max_retries=LLM_MAX_RETRIES,
                should_abort=abort.is_set,
                log=logger.debug,
                log_prefix=log_prefix,
            )

        truncated = False

        def _post() -> Dict[str, Any]:
            nonlocal truncated
            if on_delta is None:
                return _post_full()
            try:
                content, truncated = post_json_stream(
                    url=f"{base_url}/chat/completions",
                    payload=payload,
                    headers=headers,
                    timeout=LLM_TIMEOUT,
                    should_abort=abort.is_set,
                    on_delta=on_delta,
                    log=logger.debug,
                    log_prefix=log_prefix,
                )
            except Exception as exc:
                # 零 delta 的任何失败（端点不认 stream / 429、5xx、连接
                # 拒绝、首字节前超时）都回退整段：流式层无重试，瞬态抖动
                # 若直接上抛会被降级分支吃成检索直出，白白丢掉一次完整
                # 回答——post_json_with_retries 的重试回路在这里接手
                logger.info("%s 流式失败回退整段请求（%s）", log_prefix, exc)
                payload.pop("stream", None)
                return _post_full()
            # 包装成非流式响应形状，后续提取逻辑单点
            return {"choices": [{"message": {"content": content}}], "usage": {}}

        # HTTP 跑守护工作线程（在途 socket 无法强断，取消时 bridge 线程
        # 立即返回，工作线程经 should_abort 在尝试边界自行退出）
        abort = threading.Event()
        try:
            body = run_cancelable(
                _post,
                cancelled=lambda: take_llm_cancel(QA_CANCEL_SCOPE, conversation_id),
                on_cancel=abort.set,
                cancel_message="本次提问已取消",
            )
        except LLMRequestAborted as exc:
            raise HistoryQACancelled(str(exc)) from exc
        except Exception as exc:
            logger.error("%s LLM 调用失败: %s", log_prefix, exc)
            raise HistoryQAError(f"模型调用失败：{exc}") from exc

        content = self._extract_content(body or {})
        if not content:
            raise HistoryQAError(
                "模型返回了空回答，请重试；若用的是纯思考模式模型，请在模型设置中关闭"
            )
        return content, truncated

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
