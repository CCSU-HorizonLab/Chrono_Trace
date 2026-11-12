"""AI 分身：以 TA 的口吻进行模拟对话（画像页·分身聊天，重设计 §6.3）。

人格提示词三路素材：
- 画像档案（contact_profiles 最新快照：性格标签/说话风格/兴趣/关系背景）
  ——LLM 提炼的稳定印象，缺席时降级为语气+记忆
- 语气采样（近窗 TA 消息实时统计：中位句长/短句占比/高频词/常用表情/
  原话样本）——纯本地毫秒级，不依赖跑过分析
- RAG 长期记忆（与当前话题相关的事实，复用问答同款检索器+门控）

骨架组合 HistoryQAService：会话串行门闩（问答/陪练/分身同会话一次只有
一个在途）、取消 scope（cancel_history_qa / cancel_avatar_chat 同一注册
表）、批量脱敏红线（远程模型逐条过 PrivacyRedactor，任何一条失败即整
体阻断，绝不降级发原文）与交互式 LLM 调用（流式+守护线程取消）全部
借用——分身只新增人格组装与语气采样。

边界（与产品约定一致）：模拟止于应用内对话，不提供任何「代发消息」
能力；开场横幅由前端常驻明示「这是基于聊天记录的 AI 模拟，不是 TA
本人」；系统提示词要求无依据的具体事实（时间/地点/事件）直接说不
记得，不编造。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any, Callable, Dict, List, Optional

from ...db.connection import get_db
from .history_qa_service import HistoryQAError, HistoryQAService

logger = logging.getLogger(__name__)

# 语气采样窗口：近期 TA 文本消息上限（2000 条 jieba 分词毫秒级，
# 再大只多算冷数据——口吻由近期习惯代表）
VOICE_SAMPLE_LIMIT = 2000
# 原话样本条数（口吻模仿参考；等距抽样避免全取最近的事务性短句）
VOICE_QUOTE_COUNT = 8
VOICE_QUOTE_MAX_CHARS = 60
# 高频词/表情档位：给 LLM 的参考面，堆太多反而稀释特征
VOICE_TOP_WORDS = 12
VOICE_TOP_EMOJIS = 6
VOICE_SHORT_LEN = 10  # 「短句」判定线（字）
# 分身成立的最低语料：少于这个量语气档案全是噪音
AVATAR_MIN_SAMPLES = 30
# 携带对话轮数（user+assistant 各算一轮）
AVATAR_HISTORY_TURNS = 8
AVATAR_HISTORY_TURN_CHARS = 400

# 微信内置表情码（[呲牙]/[破涕为笑]…）：中文 1-6 字方括号形态
_EMOJI_CODE = re.compile(r"\[[一-龥]{1,6}\]")
_CJK_WORD = re.compile(r"^[一-龥]{2,}$")
# 高频词的功能词类黑名单（jieba 词性）：代词/连词/介词/助词/副词/数词/
# 量词/时间词/方位词/区别词——「我们/什么/这个」这类词堆满 Top 也带不来
# 口吻信息。刻意不套词云的 CONTENT_POS_TAGS 白名单、也不套 CHAT_STOP_WORDS：
# 两者为内容词设计，会把语气词/叹词（嗯嗯/哈哈——分身最想要的口头禅）
# 整类滤掉；黑名单口径正好相反，只杀功能词、保留语气特征。
_VOICE_FUNC_POS = frozenset("rcpudmqtfbz")


class AvatarChatService:
    """TA 分身对话：人格组装 → 脱敏 → LLM → 口吻回复。"""

    def __init__(self) -> None:
        # 借用问答服务的门闩/脱敏/RAG 检索/LLM 调用骨架（见模块 docstring）
        self._qa = HistoryQAService()

    # ---- 对外入口 ----

    def chat(
        self,
        conversation_id: int,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """一轮分身对话：message 为用户这轮说的话，history 为此前轮次
        （时间升序，{role: 'user'|'assistant', content}），on_delta 为
        流式打字机回调。返回 {"reply", "profile_used", "voice"}。"""
        message = str(message or "").strip()
        if not message:
            raise HistoryQAError("说点什么吧")
        with self._qa._serial_gate(conversation_id):
            return self._chat(conversation_id, message, history, on_delta)

    # ---- 主链路 ----

    def _chat(
        self,
        conversation_id: int,
        message: str,
        history: Optional[List[Dict[str, str]]],
        on_delta: Optional[Callable[[str], None]],
    ) -> Dict[str, Any]:
        turns = self._normalize_history(history)
        account_wxid, display_name = self._qa._load_conversation(conversation_id)

        voice = self._sample_voice(conversation_id)
        if voice["sample_count"] < AVATAR_MIN_SAMPLES:
            raise HistoryQAError(
                f"TA 的文本消息只有 {voice['sample_count']} 条，"
                "还撑不起一个分身——等记录再多一些吧"
            )

        profile = self._load_profile(conversation_id)
        memory_refs, memory_no_hit = self._qa._retrieve_rag_memories(
            account_wxid, conversation_id,
            f"{turns[-1]['content'] if turns else ''} {message}".strip()
            if turns else message,
        )

        # 五路素材统一过批量脱敏（红线同问答：任何一条失败即阻断）——
        # 姓名/画像/语气高频词与表情/原话样本/记忆都含真实细节，与用户
        # 消息同一出口。高频词是人名/称呼的高发形态（≥2 字纯中文），
        # 绝不经红线直发远程；表情码方括号形态可嵌自定义称呼，同样过检
        quotes = [q["text"] for q in voice["quotes"]]
        profile_texts = self._profile_redact_units(profile)
        voice_words = "、".join(voice["top_words"])
        voice_emojis = "".join(voice["top_emojis"])
        pairs = (
            [(message, "avatar_message")]
            + [(t["content"], f"avatar_history_{i}") for i, t in enumerate(turns, 1)]
            + [(display_name, "avatar_name")]
            + [(text, f"avatar_profile_{i}") for i, text in enumerate(profile_texts, 1)]
            + [(voice_words, "avatar_voice_words")]
            + [(voice_emojis, "avatar_voice_emojis")]
            + [(q, f"avatar_quote_{i}") for i, q in enumerate(quotes, 1)]
            + [(m["content"], f"avatar_memory_{i}") for i, m in enumerate(memory_refs, 1)]
        )
        texts = self._qa._redact_batch_for_remote(
            pairs, account_wxid, conversation_id, source_table="avatar_chat"
        )
        it = iter(texts)
        redacted_message = next(it)
        redacted_turns = [{"role": t["role"], "content": next(it)} for t in turns]
        redacted_name = next(it)
        redacted_profile_texts = [next(it) for _ in profile_texts]
        redacted_words = next(it)
        redacted_emojis = next(it)
        redacted_quotes = [next(it) for _ in quotes]
        redacted_memories = [next(it) for _ in memory_refs]

        system_prompt = self._build_system_prompt(
            redacted_name, redacted_profile_texts if profile else None,
            voice, redacted_words, redacted_emojis,
            redacted_quotes, redacted_memories, memory_no_hit,
        )
        messages = (
            [{"role": "system", "content": system_prompt}]
            + redacted_turns
            + [{"role": "user", "content": redacted_message}]
        )
        # 温度比问答（0.3 求准）高：口吻自然比事实精确更重要——事实
        # 面已经由画像/记忆/样本锚定，幻觉风险在系统提示词里封死
        reply, truncated = self._qa._post_llm_chat(
            conversation_id, messages,
            temperature=0.7, max_tokens=1024,
            on_delta=on_delta, log_prefix="[AI分身]",
        )
        result: Dict[str, Any] = {
            "reply": reply,
            "profile_used": profile is not None,
            # 前端页头小字：基于多少条 TA 消息采样（本地统计，无敏感面）
            "voice": {
                "sample_count": voice["sample_count"],
                "median_len": voice["median_len"],
            },
        }
        if truncated:
            result["truncated"] = True
        return result

    # ---- 人格素材 ----

    def _sample_voice(self, conversation_id: int, side: int = 0) -> Dict[str, Any]:
        """语气采样：近窗文本消息实时统计（纯本地，毫秒级）。

        side=0 取 TA 侧（分身人格素材）、1 取我侧（陪练注入我的表达
        风格）。返回 {"sample_count", "median_len", "short_ratio",
        "top_words", "top_emojis", "quotes"}；quotes 为等距抽样的原话
        （含 message_id，供上层脱敏与调试溯源）。
        """
        conn = get_db()
        rows = conn.execute(
            """
            SELECT id, content FROM messages
            WHERE conversation_id = ?
              AND is_sender = ? AND message_type = 1
              AND content IS NOT NULL AND TRIM(content) != ''
            ORDER BY timestamp DESC LIMIT ?
            """,
            (int(conversation_id), int(side), VOICE_SAMPLE_LIMIT),
        ).fetchall()
        texts = [(int(r[0]), str(r[1]).strip()) for r in rows]
        if not texts:
            return {
                "sample_count": 0, "median_len": 0, "short_ratio": 0.0,
                "top_words": [], "top_emojis": [], "quotes": [],
            }

        lens = sorted(len(t) for _, t in texts)
        median_len = lens[len(lens) // 2]
        short_ratio = sum(1 for n in lens if n <= VOICE_SHORT_LEN) / len(lens)

        # 高频词：jieba 词性分词后留 ≥2 字纯中文的非功能词（语气词/称呼/
        # 口头禅都在这层；功能词类黑名单见 _VOICE_FUNC_POS 注释）
        import jieba
        import jieba.posseg as pseg

        jieba.setLogLevel(60)
        word_counter: Dict[str, int] = {}
        for _, text in texts:
            for pair in pseg.cut(text):
                w = pair.word
                if _CJK_WORD.match(w) and pair.flag[0] not in _VOICE_FUNC_POS:
                    word_counter[w] = word_counter.get(w, 0) + 1
        top_words = [
            w for w, _ in sorted(
                word_counter.items(), key=lambda kv: -kv[1]
            )[:VOICE_TOP_WORDS]
        ]

        emoji_counter: Dict[str, int] = {}
        for _, text in texts:
            for code in _EMOJI_CODE.findall(text):
                emoji_counter[code] = emoji_counter.get(code, 0) + 1
        top_emojis = [
            c for c, _ in sorted(
                emoji_counter.items(), key=lambda kv: -kv[1]
            )[:VOICE_TOP_EMOJIS]
        ]

        # 原话样本：等距抽样（时间正序语义下 spread 到整窗），滤纯表情/
        # 过短句——样本是「口吻参考」不是「事实来源」
        candidates = [
            (mid, t) for mid, t in texts
            if len(t) >= 4 and not _EMOJI_CODE.fullmatch(t)
        ]
        quotes: List[Dict[str, Any]] = []
        if candidates:
            step = max(1, len(candidates) // VOICE_QUOTE_COUNT)
            for mid, t in candidates[::step][:VOICE_QUOTE_COUNT]:
                quotes.append(
                    {"message_id": mid, "text": t[:VOICE_QUOTE_MAX_CHARS]}
                )
        return {
            "sample_count": len(texts),
            "median_len": median_len,
            "short_ratio": round(short_ratio, 2),
            "top_words": top_words,
            "top_emojis": top_emojis,
            "quotes": quotes,
        }

    def _load_profile(self, conversation_id: int) -> Optional[Dict[str, Any]]:
        """最新画像快照（任意窗口取 window_to 最大者）；无画像/解析失败
        返回 None——分身降级为语气+记忆，不因此失败。"""
        from ..realtime.contact_profiler import PROFILE_SNAPSHOT_SCHEMA

        try:
            conn = get_db()
            row = conn.execute(
                """
                SELECT profile_json FROM contact_profiles
                WHERE conversation_id = ? AND schema_version = ?
                ORDER BY window_to DESC, created_at DESC LIMIT 1
                """,
                (int(conversation_id), PROFILE_SNAPSHOT_SCHEMA),
            ).fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            return data if isinstance(data, dict) else None
        except (sqlite3.Error, ValueError) as exc:
            logger.warning("[AI分身] 画像快照读取失败（按无画像继续）: %s", exc)
            return None

    @staticmethod
    def _profile_redact_units(profile: Optional[Dict[str, Any]]) -> List[str]:
        """画像 JSON 拆成逐条脱敏单元（远程红线逐条过检的最小粒度）。"""
        if not profile:
            return []
        units: List[str] = []
        tags = profile.get("personality_tags") or []
        if tags:
            units.append("、".join(str(t) for t in tags if t))
        for key in ("chat_style", "relationship_note"):
            val = str(profile.get(key) or "").strip()
            if val:
                units.append(val)
        interests = profile.get("interests") or []
        if interests:
            units.append("、".join(str(i) for i in interests if i))
        return [u for u in units if u.strip()]

    def _build_system_prompt(
        self,
        display_name: str,
        profile_units: Optional[List[str]],
        voice: Dict[str, Any],
        voice_words: str,
        voice_emojis: str,
        quotes: List[str],
        memories: List[str],
        memory_no_hit: bool = False,
    ) -> str:
        """人格系统提示词：身份边界 + 三路素材 + 口吻规则。

        入参一律是脱敏副本（display_name/voice_words/voice_emojis 调用方
        已过批量脱敏；voice 仅取中位句长/短句比等无敏感数值）。"""
        parts = [
            f"你在扮演微信聊天里的「{display_name}」——一个基于真实聊天记录"
            "的 AI 模拟，不是本人。用户是和你聊过很多天的微信好友，你们正在"
            "微信里聊天。"
        ]
        if profile_units:
            parts.append(
                "\n\n【TA 的画像】（从聊天记录提炼的稳定印象）\n"
                + "\n".join(f"- {u}" for u in profile_units)
            )
        short_pct = int(round(voice.get("short_ratio") or 0, 2) * 100)
        lines = [
            f"- 中位句长 {voice.get('median_len')} 字，{short_pct}% 的消息不超过"
            f"{VOICE_SHORT_LEN} 字——回复保持相近长度，像微信聊天不像作文"
        ]
        if voice_words:
            lines.append("- 高频词（自然带出，不堆砌）：" + voice_words)
        if voice_emojis:
            lines.append("- 常用表情（偶尔用，不是每句都带）：" + voice_emojis)
        parts.append("\n\n【TA 的语气档案】（真实消息统计）\n" + "\n".join(lines))
        if quotes:
            parts.append(
                "\n\n【TA 的原话样本】（模仿口吻的参考，不是这次对话的内容）\n"
                + "\n".join(f"{i}. {q}" for i, q in enumerate(quotes, 1))
            )
        if memories:
            parts.append(
                "\n\n【相关记忆】（长期记忆库中与此话题相关的事实）\n"
                + "\n".join(f"- {m}" for m in memories)
            )
        elif memory_no_hit:
            # 同问答 no_hit 反幻觉提示：温度 0.7 的口吻生成恰恰最容易
            # 硬凑事实——检索有结果但全被门控拒时显式告知无可靠记录
            parts.append(
                "\n\n【相关记忆】长期记忆库中没有与此话题直接相关的可靠"
                "记录；具体的时间、地点、事件没依据就说不记得，不要从"
                "原话样本或语气里推断。\n"
            )
        parts.append(
            "\n\n规则：\n"
            "- 用 TA 的口吻回话：短句、口语化，参照语气档案与原话样本，"
            "不用列表或长篇大论\n"
            "- 具体事实（时间/地点/事件/数字）只依据画像、记忆和原话样本；"
            "没依据就自然地说不太记得了，不编造\n"
            "- 不主动跳出角色；被问「你是 AI 吗」可以大方承认是模拟\n"
            "- 直接回话，不要客套开场和自我介绍"
        )
        return "".join(parts)

    @staticmethod
    def _normalize_history(history: Any) -> List[Dict[str, str]]:
        """清洗前端回传的对话轮次：只留 user/assistant 的非空内容，
        截最近几轮、每轮限长（分身对话历史是上下文不是检索素材）。"""
        if not isinstance(history, (list, tuple)):
            return []
        turns: List[Dict[str, str]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                turns.append(
                    {"role": role, "content": content[:AVATAR_HISTORY_TURN_CHARS]}
                )
        return turns[-AVATAR_HISTORY_TURNS:]
