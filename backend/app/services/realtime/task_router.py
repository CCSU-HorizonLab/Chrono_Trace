"""G2 任务路由:把用户输入拆成 任务类型 / 输出形式 / 知识需求 三元组。

替代旧的 ``direct_reply | advice_request`` 二分。上游文档
``docs/goals/g1-generation-goal.md`` 第三节 G2 的契约:

- ``task`` 决定检索哪些知识、怎么排序;
- ``output`` 决定 JSON 契约(direct_answer 强制 summary/speeches 为空,
  answer_with_speeches 允许"回答 + 可发送话术"并存);
- ``knowledge_needs`` 决定最终 prompt 里画像/关系策略/用户风格块是否渲染。

两者解耦后,"我想约她打游戏"不再因为缺少建议关键词被判成纯聊天,
关系讨论即使直接回答也允许使用画像与关系证据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .memory_intent import _looks_like_history_question, _looks_like_relationship_question

# ---- 任务类型 ---------------------------------------------------------------
TASK_MEMORY_QA = "memory_qa"
TASK_REPLY_SUGGESTION = "reply_suggestion"
TASK_INVITATION_PLANNING = "invitation_planning"
TASK_RELATIONSHIP_DISCUSSION = "relationship_discussion"
TASK_GENERAL_QA = "general_qa"

# ---- 输出形式 ---------------------------------------------------------------
OUTPUT_DIRECT_ANSWER = "direct_answer"
OUTPUT_SUGGESTION_CARD = "suggestion_card"
OUTPUT_ANSWER_WITH_SPEECHES = "answer_with_speeches"

# ---- 知识需求 ---------------------------------------------------------------
KN_FACTS = "facts"
KN_CONTACT_PROFILE = "contact_profile"
KN_USER_STYLE = "user_style"
KN_RELATIONSHIP_SIGNALS = "relationship_signals"

_NEEDS_ALL = (KN_FACTS, KN_CONTACT_PROFILE, KN_USER_STYLE, KN_RELATIONSHIP_SIGNALS)

# ---- 关键词表(llm_engine 的旧二分以此为唯一事实来源) -----------------------

ADVICE_KEYWORDS = (
    "怎么回",
    "如何回",
    "回复什么",
    "怎么聊",
    "如何聊",
    "怎么说",
    "说什么",
    "怎么接",
    "如何接",
    "怎么开场",
    "如何开场",
    "开启话题",
    "帮我回",
    "给我建议",
    "给出建议",
    "给出相关建议",
    "给相关建议",
    "给我几个话术",
    "给我几句",
    "给出话术",
    "该发什么",
    "应该发什么",
    "回啥",
    "怎么回复",
    "生成建议",
    "生成回复",
    "生成话术",
    "建议话术",
    "给点建议",
    "给点话术",
    "建议呢",
    "来点建议",
    "来点话术",
    "模仿我说话",
    "模仿我的语气",
    "按我的语气",
    "按我的风格",
    "用我的语气",
    "换成我的语气",
    "换成我的风格",
    "改成我会说的",
    "像我会说的",
    "更像我",
    "像我一点",
)

REWRITE_KEYWORDS = (
    "模仿我说话",
    "模仿我的语气",
    "按我的语气",
    "按我的风格",
    "用我的语气",
    "换成我的语气",
    "换成我的风格",
    "改成我会说的",
    "像我会说的",
    "更像我",
    "像我一点",
    "换个说法",
    "润色一下",
    "改一下",
    "口语一点",
    "再口语一点",
    "短一点",
    "简短一点",
    "再来几句",
)

ADVICE_CONTEXT_HINTS = (
    "建议",
    "话术",
    "相关建议",
    "你可以说",
    "你可以回",
    "可以这样回",
    "可以这么回",
    "怎么回",
    "怎么说",
    "如何开口",
    "回复草稿",
    "化解尴尬",
    "真诚道歉",
    "问问",
    "可以就提",
    "可以，就提",
)

# 建议追问:输入本身不含建议关键词,但明显在追上一轮的建议任务。
FOLLOWUP_ADVICE_PATTERNS = (
    "没有建议",
    "没建议",
    "建议呢",
    "怎么没",
    "再来几条",
    "再来几句",
    "再来一点",
    "再来一批",
    "换一批",
    "换几个",
    "换点别的",
    "再给几条",
    "继续",
    "接着来",
    "还有吗",
    "还有别的",
    "别的呢",
    "第2条",
    "第二条",
    "第3条",
    "第三条",
    "上一条",
    "刚才那条",
)

# 邀约策划信号:用户想安排一次见面/共同活动。
INVITATION_PATTERNS = (
    "我想约",
    "想约她",
    "想约他",
    "想约ta",
    "想约对方",
    "约她",
    "约他",
    "约ta",
    "约对方",
    "约出来",
    "约个",
    "约着",
    "约她一起",
    "约他一起",
    "邀约",
    "邀请她",
    "邀请他",
    "约见面",
    "约着见",
    "约饭",
    "约吃饭",
    "约电影",
    "约看",
    "约玩",
    "约打游戏",
    "周末约",
    "假期约",
    "放假约",
    "找她玩",
    "找他玩",
    "约她玩",
    "约他玩",
    "想见面",
    "想见她",
    "想见她一面",
    "想见见",
    "想一起玩",
    "想一起吃",
    "想一起去看",
    "想去找她",
    "想去找他",
)

# 关系讨论信号(比 memory_intent 的原型更口语化)。
RELATIONSHIP_DISCUSSION_PATTERNS = (
    "她是不是讨厌",
    "他是不是讨厌",
    "是不是讨厌我",
    "她对我什么感觉",
    "他对我什么感觉",
    "对我有意思",
    "对我没意思",
    "我们算什么关系",
    "我们现在什么关系",
    "什么关系了",
    "该不该表白",
    "要不要表白",
    "该不该推进",
    "怎么推进关系",
    "怎么推进我们",
    "她还喜欢我",
    "他还喜欢我",
    "喜欢我吗",
    "在意我吗",
    "在乎我吗",
    "对我冷",
    "对我冷淡",
    "不想理我",
    "不理我",
    "不理人",
    "不回我消息",
    "是不是不喜欢我",
    "是不是不喜欢",
    "有没有戏",
    "还有机会吗",
    "还要不要继续",
)

# 记忆问答补充:偏好类事实查询("她喜欢什么"/"她电话多少")。
_PREFERENCE_LOOKUP_VERBS = (
    "喜欢", "讨厌", "爱", "想要", "生日", "多大", "属什么", "星座",
    "在哪", "哪里人", "电话", "号码", "微信号", "联系方式",
)
_ASK_MARKERS = ("什么", "吗", "么", "哪", "谁", "多少", "?", "？", "咋")
_THIRD_PARTY_MARKERS = ("她", "他", "对方", "ta", "TA", "人家")
# 无第三人称主语时的分寸/边界词:仍视为关系讨论("怎么开玩笑不越界")。
_BOUNDARY_ALONE_MARKERS = ("越界", "分寸", "边界", "雷区", "红线")

# 祈使式内容生成请求("表达想念""夸她一下""道个歉"):用户要的是话术本身。
# 真实使用发现这类短祈使句曾误判 general_qa,只能靠模型违规输出话术兜底。
_CONTENT_REQUEST_VERBS = (
    "表达", "夸", "夸夸", "哄", "道歉", "道个歉", "赔个不是", "赔不是",
    "安抚", "安慰", "关心", "问候", "打招呼", "祝福", "生日快乐",
    "表白", "告白", "撒娇", "卖个萌", "撩",
)
_CONTENT_REQUEST_OBJECTS = ("她", "他", "对方", "ta", "TA", "人家")


@dataclass(frozen=True)
class TaskRouting:
    """一次生成请求的三元路由结果。"""

    task: str
    output: str
    knowledge_needs: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""
    wants_speeches: bool = False
    manual_request: bool = False

    def needs(self, kind: str) -> bool:
        return kind in self.knowledge_needs

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "output": self.output,
            "knowledge_needs": list(self.knowledge_needs),
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
            "wants_speeches": self.wants_speeches,
            "manual_request": self.manual_request,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TaskRouting | None":
        if not isinstance(payload, dict) or not payload.get("task") or not payload.get("output"):
            return None
        needs = tuple(str(item) for item in payload.get("knowledge_needs") or ())
        wants_speeches = bool(payload.get("wants_speeches"))
        if not wants_speeches and str(payload.get("output")) != OUTPUT_DIRECT_ANSWER:
            wants_speeches = True
        return cls(
            task=str(payload.get("task")),
            output=str(payload.get("output")),
            knowledge_needs=needs,
            confidence=float(payload.get("confidence") or 0.0),
            reason=str(payload.get("reason") or ""),
            wants_speeches=wants_speeches,
            manual_request=bool(payload.get("manual_request")),
        )


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _latest_user_input(context: dict[str, Any]) -> str:
    user_context = context.get("user_context")
    if isinstance(user_context, list):
        for msg in reversed(user_context):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return str(msg.get("content") or "").strip()
        return ""
    if isinstance(user_context, str):
        return user_context.strip()
    trigger_context = context.get("trigger_context")
    if isinstance(trigger_context, dict):
        for key in ("user_input", "manual_input", "text", "content"):
            value = trigger_context.get(key)
            if value:
                return str(value).strip()
    return ""


def _previous_user_inputs(context: dict[str, Any]) -> list[str]:
    user_context = context.get("user_context")
    if not isinstance(user_context, list):
        return []
    return [
        str(msg.get("content") or "").strip()
        for msg in user_context[:-1]
        if isinstance(msg, dict) and msg.get("role") == "user" and str(msg.get("content") or "").strip()
    ]


def _previous_conversation_inputs(context: dict[str, Any]) -> list[str]:
    """当前输入之前的全部对话内容(含 AI 回复——AI 的建议措辞同样标志任务上下文)。"""
    user_context = context.get("user_context")
    if not isinstance(user_context, list):
        return []
    return [
        str(msg.get("content") or "").strip()
        for msg in user_context[:-1]
        if isinstance(msg, dict) and str(msg.get("content") or "").strip()
    ]


def _has_advice_context(context: dict[str, Any]) -> bool:
    """判断当前输入前,是否已经在围绕"给建议/改话术"这个任务继续追问。"""
    historical_inputs = _previous_conversation_inputs(context)
    if not historical_inputs:
        return False
    normalized = _compact("".join(historical_inputs))
    if any(keyword in normalized for keyword in ADVICE_KEYWORDS):
        return True
    return any(keyword in normalized for keyword in ADVICE_CONTEXT_HINTS)


def _looks_like_advice_followup(normalized_latest: str) -> bool:
    if not normalized_latest:
        return False
    if any(pattern in normalized_latest for pattern in FOLLOWUP_ADVICE_PATTERNS):
        return True
    if len(normalized_latest) <= 14 and any(
        keyword in normalized_latest for keyword in REWRITE_KEYWORDS
    ):
        return True
    return False


def _looks_like_topic_followup_in_advice(normalized_latest: str) -> bool:
    """建议上下文中的记忆型追问("她上次说的什么流派 我不知道")。

    仍在围绕上一轮建议追问给对方怎么说,应继承建议任务并修正输出,
    而不是回落成纯历史问答;仅在已有建议上下文时生效。
    """
    if not normalized_latest:
        return False
    third_party_hints = ("她", "他", "对方", "ta", "TA", "人家")
    memory_or_topic_hints = (
        "上次", "之前", "刚刚", "说的", "提到", "流派", "话题", "游戏",
        "店", "吃", "喝", "不知道", "不记得", "忘了",
    )
    return any(hint in normalized_latest for hint in third_party_hints) and any(
        hint in normalized_latest for hint in memory_or_topic_hints
    )


def _looks_like_invitation(normalized: str) -> bool:
    return any(pattern in normalized for pattern in INVITATION_PATTERNS)


def _looks_like_content_request(normalized: str) -> bool:
    """祈使式内容生成:短输入、动词打头(或"帮我/给我+动词")、指向对方。

    "表达想念"/"夸她一下"/"哄哄她"/"帮我道个歉" → 用户要话术,不是提问。
    """
    if len(normalized) > 16:
        return False
    body = normalized
    implied_object = False
    for prefix in ("帮我", "给我", "想", "怎么"):
        if body.startswith(prefix):
            implied_object = prefix in ("帮我", "给我")  # "帮我道个歉"隐含对方
            body = body[len(prefix):]
            break
    if not body:
        return False
    has_verb = any(body.startswith(verb) for verb in _CONTENT_REQUEST_VERBS) or any(
        verb in body[:4] for verb in _CONTENT_REQUEST_VERBS
    )
    has_object = (
        any(obj in body for obj in _CONTENT_REQUEST_OBJECTS)
        or any(token in body for token in ("想念", "思念", "晚安", "早安", "晚安问候"))
        or implied_object
    )
    asks_question = any(marker in normalized for marker in ("什么", "吗", "呢", "怎么", "为什么", "?", "？"))
    return has_verb and has_object and not asks_question


def _looks_like_relationship_discussion(normalized: str) -> bool:
    if any(pattern in normalized for pattern in RELATIONSHIP_DISCUSSION_PATTERNS):
        return True
    if _looks_like_relationship_question(normalized):
        return True
    # 无主语的分寸求助("怎么开玩笑不越界"):策略词+关系轴/边界词即可命中。
    asks_strategy = any(token in normalized for token in ("怎么", "如何", "该不该", "能不能"))
    relation_axis = any(
        token in normalized
        for token in ("开玩笑", "玩笑", "调侃", "关系", "边界", "分寸", "相处", "沟通", "习惯", "风格")
    )
    boundary_alone = any(token in normalized for token in _BOUNDARY_ALONE_MARKERS)
    return asks_strategy and (relation_axis or boundary_alone)


def _looks_like_preference_lookup(normalized: str) -> bool:
    has_actor = any(marker in normalized for marker in _THIRD_PARTY_MARKERS) or "我们" in normalized
    has_pref_verb = any(verb in normalized for verb in _PREFERENCE_LOOKUP_VERBS)
    asks = any(marker in normalized for marker in _ASK_MARKERS)
    return has_actor and has_pref_verb and asks


def _memory_followup(context: dict[str, Any]) -> bool:
    """追问历史细节("具体是哪家")继承上一轮记忆问答任务。"""
    historical_inputs = _previous_user_inputs(context)[-4:]
    return any(_looks_like_history_question(previous) for previous in reversed(historical_inputs))


def route_generation_task(context: dict[str, Any] | None, trigger_type: str = "") -> TaskRouting:
    """根据触发类型与用户输入产出 task / output / knowledge_needs 三元组。"""
    context = context or {}
    manual_request = str(trigger_type) == "manual_request"
    latest = _latest_user_input(context)

    # 非手动触发(半自动/全自动/开场):系统主动介入给建议,恒为建议卡片。
    if not manual_request:
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_SUGGESTION_CARD,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.95,
            reason=f"auto_trigger:{trigger_type or 'unknown'}",
            wants_speeches=True,
            manual_request=False,
        )

    # 手动请求但没有用户输入(开场建议复用 manual_request 触发):默认给建议。
    if not latest:
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_SUGGESTION_CARD,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.80,
            reason="manual_no_input_default",
            wants_speeches=True,
            manual_request=True,
        )

    normalized = _compact(latest)

    # 1) 建议追问:显式追问("没有建议么/再来几条")永远继承建议任务——
    #    即使上一轮是记忆问答,用户此刻要的就是话术;松散话题追问仍需
    #    已有建议上下文,避免把首次输入的普通提问误判成求助。
    if _looks_like_advice_followup(normalized):
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_SUGGESTION_CARD,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.82,
            reason=(
                "advice_followup_inherited"
                if _has_advice_context(context)
                else "explicit_advice_followup"
            ),
            wants_speeches=True,
            manual_request=True,
        )
    if _has_advice_context(context) and _looks_like_topic_followup_in_advice(normalized):
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_SUGGESTION_CARD,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.85,
            reason="advice_topic_followup_inherited",
            wants_speeches=True,
            manual_request=True,
        )

    # 2) 记忆问答:查历史/偏好,直接回答,不注入用户口头禅与建议风格。
    if _looks_like_history_question(latest) or _looks_like_preference_lookup(normalized):
        return TaskRouting(
            task=TASK_MEMORY_QA,
            output=OUTPUT_DIRECT_ANSWER,
            knowledge_needs=(KN_FACTS,),
            confidence=0.80,
            reason="history_answer_signal",
            wants_speeches=False,
            manual_request=True,
        )
    if (
        _memory_followup(context)
        and len(normalized) <= 16
        and not _looks_like_invitation(normalized)
        and not any(keyword in normalized for keyword in ADVICE_KEYWORDS)
    ):
        return TaskRouting(
            task=TASK_MEMORY_QA,
            output=OUTPUT_DIRECT_ANSWER,
            knowledge_needs=(KN_FACTS,),
            confidence=0.70,
            reason="memory_followup_inherited",
            wants_speeches=False,
            manual_request=True,
        )

    # 3) 显式回复求助("怎么回她…"):优先级高于邀约——用户在问怎么回话,
    #    即使话题与邀约相关,也是回复建议任务。
    if any(keyword in normalized for keyword in ADVICE_KEYWORDS):
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_SUGGESTION_CARD,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.90,
            reason="advice_keyword",
            wants_speeches=True,
            manual_request=True,
        )

    # 4) 祈使式内容生成("表达想念"/"夸她一下"):给回答附话术。
    if _looks_like_content_request(normalized):
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_ANSWER_WITH_SPEECHES,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.78,
            reason="content_generation_imperative",
            wants_speeches=True,
            manual_request=True,
        )

    # 5) 邀约策划:给回答 + 可直接发送的邀约话术。
    if _looks_like_invitation(normalized):
        return TaskRouting(
            task=TASK_INVITATION_PLANNING,
            output=OUTPUT_ANSWER_WITH_SPEECHES,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.85,
            reason="invitation_signal",
            wants_speeches=True,
            manual_request=True,
        )

    # 5) 关系讨论:允许画像与关系证据;要不要话术取决于是否求"怎么办"。
    if _looks_like_relationship_discussion(normalized):
        wants_speeches = any(
            keyword in normalized
            for keyword in (
                "怎么回", "怎么说", "怎么办", "怎么开口", "怎么推进", "如何推进",
                "怎么破", "该怎么做", "怎么开", "开玩笑", "怎么聊", "怎么相处", "怎么把握",
            )
        )
        return TaskRouting(
            task=TASK_RELATIONSHIP_DISCUSSION,
            output=OUTPUT_ANSWER_WITH_SPEECHES if wants_speeches else OUTPUT_DIRECT_ANSWER,
            knowledge_needs=(KN_FACTS, KN_CONTACT_PROFILE, KN_RELATIONSHIP_SIGNALS),
            confidence=0.78,
            reason="relationship_discussion_signal",
            wants_speeches=wants_speeches,
            manual_request=True,
        )

    # 6) 改写追问:继承建议任务。
    if (
        any(keyword in normalized for keyword in REWRITE_KEYWORDS)
        and _has_advice_context(context)
    ):
        return TaskRouting(
            task=TASK_REPLY_SUGGESTION,
            output=OUTPUT_SUGGESTION_CARD,
            knowledge_needs=_NEEDS_ALL,
            confidence=0.85,
            reason="rewrite_followup",
            wants_speeches=True,
            manual_request=True,
        )

    # 7) 不确定时保持安全输出:只直接回答,不代发话术。
    return TaskRouting(
        task=TASK_GENERAL_QA,
        output=OUTPUT_DIRECT_ANSWER,
        knowledge_needs=(KN_FACTS,),
        confidence=0.55,
        reason="general_qa_default",
        wants_speeches=False,
        manual_request=True,
    )
