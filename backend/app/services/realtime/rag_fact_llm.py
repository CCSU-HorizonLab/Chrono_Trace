"""LLM adapter for structured contact-memory fact extraction (P1.2).

把激活的 LLM 模型适配为 StructuredFactExtractor 的 llm_call。复用
contact_profiler 的模型配置读取与 post_json_with_retries 基础设施。

红线与成本约束：
- 远程模型发送前逐条消息脱敏（PrivacyRedactor）；本地模型发原文。
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
- 一次性的转账、拼单、链接等交易细节
- 推测和不确定的判断
- 敏感隐私原文（身份证号、手机号、银行卡号、住址——即使对话出现也不要输出）

输出严格 JSON：
{"facts": [{"subject": "对方" 或 "我", "kind": "preference|plan|promise|personal_fact|event|boundary|relation_state", "content": "一句完整的事实陈述，主语明确", "confidence": 0.0~1.0, "sensitivity": "normal" 或 "sensitive", "evidence_message_ids": [对话中的消息id]}]}

content 必须是自包含的陈述句，例如"对方对虾过敏"、"我们约了周五在五道口见面"。没有可抽取事实时输出 {"facts": []}。"""


class LLMFactExtractorAdapter:
    """Adapt the active chat model into a StructuredFactExtractor llm_call."""

    def __init__(self, model_config: dict[str, Any], redactor_factory: Callable[[], Any] | None = None):
        self.model_config = dict(model_config)
        self.redactor_factory = redactor_factory
        self.remote = is_remote_llm_model(self.model_config)
        self.timeout = 120

    def __call__(self, prompt: str) -> Any:
        payload = self._parse_payload(prompt)
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

    def _render_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_messages = payload.get("messages") or []
        redactor = None
        if self.remote and self.redactor_factory is not None:
            try:
                redactor = self.redactor_factory()
            except Exception:
                redactor = None
        lines: list[str] = []
        for msg in raw_messages:
            msg_id = int(msg.get("id") or 0)
            sender = "我" if int(msg.get("is_sender") or 0) == 1 else "对方"
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            if redactor is not None:
                try:
                    content = redactor.redact(
                        content,
                        account_wxid=payload.get("account_wxid") or "",
                        conversation_id=payload.get("conversation_id"),
                        source_table="rag_fact_extraction",
                        source_id=str(msg_id),
                    ).redacted_text
                except Exception:
                    continue  # 远程脱敏失败的单条消息宁可不发
            lines.append(f"[{msg_id}] {sender}: {content}")
        user_prompt = (
            "对话片段（[消息id] 发送者: 内容）：\n"
            + "\n".join(lines)
            + "\n\n请按系统指令抽取事实，输出 JSON。"
        )
        return [
            {"role": "system", "content": FACT_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

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
