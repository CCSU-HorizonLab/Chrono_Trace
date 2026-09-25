"""LLM adapter for structured contact-memory fact extraction (P1.2).

把激活的 LLM 模型适配为 StructuredFactExtractor 的 llm_call。复用
contact_profiler 的模型配置读取与 post_json_with_retries 基础设施。

红线与成本约束：
- 远程模型发送前逐条消息脱敏（PrivacyRedactor）；脱敏器不可用时阻断
  整段发送（抛 FactRedactionUnavailable），绝不降级为发原文；本地模型
  发原文。
- 载荷同时承载抽取（messages -> facts）与融合（new_fact/active_candidates
  -> decisions）两种任务，适配器按任务特征分流到各自的 prompt 协议。
- evidence_message_ids 只保留载荷中出现的真实消息 ID（防幻觉引用）。
- 连续失败由调用方（indexer）计数中止；本适配器每次调用独立重试。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .llm_http import post_json_with_retries
from .rag_config import is_remote_llm_model

logger = logging.getLogger(__name__)


class FactRedactionUnavailable(RuntimeError):
    """远程模型脱敏器不可用：阻断该段发送，由调用方按抽取失败处理。"""


FACT_EXTRACTION_SYSTEM_PROMPT = """你是一个聊天记录记忆抽取器。你的任务是从一段双人对话中抽取"值得长期记住的事实"，供之后给回复建议时引用。

只抽稳定的、对方或用户明确表达过的事实，每条必须能在对话中找到出处：
- 偏好（喜欢/讨厌/过敏/忌口）
- 计划与约定（时间、地点、要一起做的事）
- 承诺
- 个人情况（工作、学校、家乡、身体状况等稳定信息）
- 兴趣爱好（游戏、影视、运动等长期兴趣）
- 相处边界（对方明确表达的雷区、介意的事）
- 反复出现的习惯

不要抽取：
- 单纯的应答、寒暄、表情、语气词（好的/嗯/666/哈哈）
- 一次性的转账、收款、拼单、AA、报销、代付等金钱往来细节（如"早餐钱""转你20""记得还我"）——交易过程不是长期记忆
- 游戏内商店、卡牌、皮肤、道具等虚拟物品的购买过程（"买了战未来""删了牌买不了东西"）——游戏内的购买操作不是消费事实；只有当它反映稳定的长期偏好（如"对方在卡牌游戏里偏好攒钱买稀有卡"）时才作为偏好抽取，且必须写明是游戏内
- 一次性的链接、物流、快递单号等事务细节
- 推测和不确定的判断
- 敏感隐私原文（身份证号、手机号、银行卡号、住址——即使对话出现也不要输出）

content 必须是自包含的完整陈述句，把口语中的代词和省略还原成具体对象：
- 差（不可接受）："对方提到：就买一下下嘛"（买什么？没说清）
- 差（不可接受）："有钱了搞一台"（搞一台什么？删掉对话没人看得懂）
- 差（不可接受）："我们后天搬"（搬什么？去哪里？）
- 差（不可接受）："直接买80的""想买便宜点的"（80 的什么？代词结尾=对象已丢失）
- 好："对方撒娇要求购买之前讨论过的游戏皮肤"
- 好："对方对虾过敏"
- 好："两人计划后天把宿舍的行李搬到新租的房子"

输出前对每条事实做自检：删掉这段对话后，只看这句话本身，还能明白它在说什么吗？
如果结合上下文仍无法确定指代对象（买什么/去哪里/谁说的），就不要输出这条事实。宁可少抽，不可抽含糊的。

输出严格 JSON：
{"facts": [{"subject": "对方" 或 "我", "kind": "preference|plan|promise|personal_fact|event|boundary|relation_state", "content": "一句完整的事实陈述，主语明确", "confidence": 0.0~1.0, "sensitivity": "normal" 或 "sensitive", "evidence_message_ids": [对话中的消息id]}]}

没有可抽取事实时输出 {"facts": []}。"""


FACT_FUSION_SYSTEM_PROMPT = """你是一个联系人记忆事实维护器。对话中新抽取了一条关于对方或用户的事实，请判断它与每条已有旧事实的关系，输出维护决策。

决策含义（对每条候选旧事实必须各给一条）：
- ADD：旧事实与新事实主题无关，保留旧事实，新事实作为新增
- UPDATE：新事实修正、细化或取代旧事实——同一主题的信息演变，如旧事实是"对方不喜欢X"，新事实是"对方因为Y对X改观了，现在喜欢"
- INVALIDATE：新事实说明旧事实已不再成立
- MERGE：同一事实被再次表达，合并证据即可，不新增
- NOOP：无法判断关联，旧事实保持不变

判断要点：
- 同一主题的立场变化是演变不是并存：应 UPDATE 或 INVALIDATE，让记忆形成"以前→现在"的演变链
- 主题（涉及的人/事物/对象）不同就 ADD；宁可多保留，不要误推翻
- 只是措辞不同、含义相同 → MERGE

输出严格 JSON：
{"decisions": [{"fact_id": 候选旧事实的id, "action": "ADD|UPDATE|INVALIDATE|MERGE|NOOP", "reason": "一句话理由"}]}"""


class LLMFactExtractorAdapter:
    """Adapt the active chat model into a StructuredFactExtractor llm_call."""

    def __init__(self, model_config: dict[str, Any], redactor_factory: Callable[[], Any] | None = None):
        self.model_config = dict(model_config)
        self.redactor_factory = redactor_factory
        self.remote = is_remote_llm_model(self.model_config)
        self.timeout = 120

    def __call__(self, prompt: str) -> Any:
        payload = self._parse_payload(prompt)
        if self._is_fusion_payload(payload):
            return self._fusion_call(payload)
        messages = self._render_messages(payload)
        body = self._call_chat(messages, max_tokens=payload.get("max_tokens") or 2048)
        content = self._extract_content(body)
        facts = self._parse_facts(content)
        self._filter_evidence(facts, payload)
        return {"facts": facts}

    # ---- payload / prompt ----

    def _parse_payload(self, prompt: str) -> dict[str, Any]:
        try:
            payload = json.loads(prompt)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_fusion_payload(payload: dict[str, Any]) -> bool:
        """融合任务特征：显式 task 标记或 new_fact/active_candidates 协议键。"""
        return (
            str(payload.get("task") or "") == "maintain_atomic_contact_facts"
            or "new_fact" in payload
            or bool(payload.get("active_candidates"))
        )

    def _require_redactor(self, payload: dict[str, Any]) -> Any | None:
        """远程模型必须有可用脱敏器，否则阻断发送（红线：绝不降级发原文）。

        本地模型返回 None（发原文）。单条消息 redact 抛异常仍按原逻辑
        跳过该条，但脱敏器本身构造失败是段级阻断。
        """
        if not self.remote:
            return None
        if self.redactor_factory is None:
            raise FactRedactionUnavailable(
                "remote model has no redactor factory; segment blocked"
            )
        try:
            redactor = self.redactor_factory()
        except Exception as exc:
            raise FactRedactionUnavailable(
                f"redactor construction failed; segment blocked: {exc}"
            ) from exc
        if redactor is None:
            raise FactRedactionUnavailable(
                "redactor factory returned None; segment blocked"
            )
        return redactor

    def _redact_text(
        self,
        text: str,
        redactor: Any,
        payload: dict[str, Any],
        *,
        source_id: str,
    ) -> str | None:
        """单条文本脱敏；失败返回 None（调用方丢弃该条，宁可不发）。"""
        if redactor is None:
            return text
        try:
            return redactor.redact(
                text,
                account_wxid=payload.get("account_wxid") or "",
                conversation_id=payload.get("conversation_id"),
                source_table="rag_fact_extraction",
                source_id=source_id,
            ).redacted_text
        except Exception:
            return None

    def _render_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = payload.get("messages") or []
        context_messages = payload.get("context_messages") or []
        redactor = self._require_redactor(payload)

        def _render(msg: dict[str, Any]) -> str | None:
            msg_id = int(msg.get("id") or 0)
            sender = "我" if int(msg.get("is_sender") or 0) == 1 else "对方"
            content = str(msg.get("content") or "").strip()
            if not content:
                return None
            content = self._redact_text(content, redactor, payload, source_id=str(msg_id))
            if content is None:
                return None  # 远程脱敏失败的单条消息宁可不发
            return f"[{msg_id}] {sender}: {content}"

        lines = [line for line in (_render(msg) for msg in raw_messages) if line]
        context_lines = [line for line in (_render(msg) for msg in context_messages) if line]
        user_prompt = "对话片段（[消息id] 发送者: 内容）：\n" + "\n".join(lines)
        if context_lines:
            user_prompt = (
                "（上一段结尾，仅供理解指代，勿从中抽取事实或引用证据）：\n"
                + "\n".join(context_lines)
                + "\n\n"
                + user_prompt
            )
        user_prompt += "\n\n请按系统指令抽取事实，输出 JSON。"
        return [
            {"role": "system", "content": FACT_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    # ---- fusion (P1.5 T2) ----

    def _fusion_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """渲染融合 prompt（新事实 + 候选旧事实）并解析 decisions 协议。

        解析失败向上抛 ValueError，由 StructuredFactExtractor.decide_fusion
        / indexer 按安全回退 ADD 处理——融合异常只 ADD 不误推翻。
        """
        redactor = self._require_redactor(payload)
        new_fact = payload.get("new_fact") or {}
        candidates = payload.get("active_candidates") or []

        def _redact(text: Any, source_id: str) -> str:
            rendered = self._redact_text(str(text or ""), redactor, payload, source_id=source_id)
            return rendered if rendered is not None else "（脱敏失败，内容已丢弃）"

        new_lines = [
            f"主题/对象：{_redact(new_fact.get('content'), source_id='new_fact')}",
            f"subject：{new_fact.get('subject', '')} kind：{new_fact.get('kind', '')}",
        ]
        candidate_lines = []
        for item in candidates:
            fact_id = int(item.get("fact_id") or 0)
            candidate_lines.append(
                f"[{fact_id}] {_redact(item.get('content'), source_id=str(fact_id))}"
            )
        user_prompt = (
            "新抽取的事实：\n"
            + "\n".join(new_lines)
            + "\n\n候选旧事实（[fact_id] 内容）：\n"
            + ("\n".join(candidate_lines) if candidate_lines else "（无）")
            + "\n\n请对每条候选旧事实输出决策 JSON。"
        )
        messages = [
            {"role": "system", "content": FACT_FUSION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        body = self._call_chat(messages, max_tokens=payload.get("max_tokens") or 2048)
        content = self._extract_content(body)
        candidate = self._json_candidate(content)
        if not candidate:
            # 诊断片段帮助区分"截断/无 JSON/围栏"——真实库失败主因是截断
            raise ValueError(
                f"fact fusion response has no JSON object (len={len(content)},"
                f" head={content[:120]!r})"
            )
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"fact fusion response invalid JSON ({exc}; candidate_len={len(candidate)},"
                f" tail={candidate[-120:]!r})"
            ) from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions"), list):
            raise ValueError("fact fusion response requires decisions")
        return parsed

    # ---- HTTP ----

    def _call_chat(self, messages: list[dict[str, Any]], *, max_tokens: int) -> dict[str, Any]:
        model = self.model_config
        base_url = str(model.get("api_base_url") or "").rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {}
        api_key = str(model.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model.get("model_id"),
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max(1024, int(max_tokens)),
            "stream": False,
        }
        return post_json_with_retries(
            url=url,
            payload=payload,
            headers=headers,
            timeout=self.timeout,
            log=logger.debug,
            log_prefix="[FactLLM]",
        )

    def _extract_content(self, body: dict[str, Any]) -> str:
        message_obj = (body.get("choices") or [{}])[0].get("message", {})
        content = str(message_obj.get("content") or "")
        if not content:
            reasoning = str(message_obj.get("reasoning_content") or "")
            content = self._json_candidate(reasoning)
        return content

    @staticmethod
    def _json_candidate(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return ""

    def _parse_facts(self, content: str) -> list[dict[str, Any]]:
        candidate = self._json_candidate(content)
        if not candidate:
            raise ValueError("fact extractor response has no JSON object")
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            facts = parsed.get("facts") or []
        else:
            facts = parsed
        if not isinstance(facts, list):
            raise ValueError("facts must be a list")
        return facts

    @staticmethod
    def _filter_evidence(facts: list[dict[str, Any]], payload: dict[str, Any]) -> None:
        valid_ids = {
            int(msg.get("id") or 0)
            for msg in (payload.get("messages") or [])
        }
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            evidence = fact.get("evidence_message_ids")
            if isinstance(evidence, list):
                fact["evidence_message_ids"] = [
                    int(v) for v in evidence if str(v).isdigit() and int(v) in valid_ids
                ]
            else:
                fact["evidence_message_ids"] = []


def get_active_model_config() -> dict[str, Any] | None:
    """Read the active chat model; returns None when unconfigured."""
    from ...db.connection import get_db

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM llm_models WHERE is_active = 1 LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def build_llm_fact_extractor() -> "LLMFactExtractorAdapter | None":
    """Construct the adapter from the active model, or None if unavailable.

    延迟导入避免循环依赖；redactor_factory 同样延迟构造。
    """
    model_config = get_active_model_config()
    if not model_config:
        return None

    def _redactor_factory():
        from ...db.connection import get_db
        from .privacy_redactor import PrivacyRedactor

        return PrivacyRedactor(get_db())

    return LLMFactExtractorAdapter(model_config, redactor_factory=_redactor_factory)
