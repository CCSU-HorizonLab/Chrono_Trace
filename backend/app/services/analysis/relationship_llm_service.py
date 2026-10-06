"""LLM 关系评估维度：采样交互对 → 脱敏 → 大模型关系判断。

作为独立维度参与好感度加权（缺席时权重归一自动剔除）：
- 采样代表性交互对（极性 9 桶分层 + 近期优先），渲染为带月份/时差的
  双方对话样本；
- RelationshipContext（关系类型/时长/沟通风格）注入提示词；
- 远程模型必经 PrivacyRedactor（脱敏器不可用=整维缺席，绝不发原文，
  对齐 rag/fact_llm 的红线模式）；本地 loopback 模型免脱敏；
- 每次分析恰好一次 HTTP 调用（max_retries=1），超时/解析失败=缺席。

跨域依赖全部构造器注入/函数内延迟导入，便于测试与避免循环。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ...db.connection import get_db

logger = logging.getLogger(__name__)

# 预算与采样常量
MAX_PAIRS = 40
MIN_PAIRS = 10
MAX_TOTAL_INPUT_CHARS = 8000
PER_UNIT_CHAR_LIMIT = 120
TIMEOUT_SECONDS = 90
# 思考模型（实测 Qwen3.5-9B）把推理写进 content：1024 会被 think 段
# 耗尽导致 JSON 未闭合即截断（finish_reason=length）——真答案在最后
MAX_TOKENS = 3072

SYSTEM_PROMPT = """你是一位关系分析专家。基于给出的两人聊天交互对样本（[对方] 与 [我]），
评估这两人的关系质量。注意：衡量的不是单方情绪，而是双方关系的亲密与
健康程度。

严格按以下 JSON 输出，不要输出任何其他文字：
{"score": 0-100 的整数（关系质量总分，50 为中性）,
 "sub_scores": {"communication_quality": 0-100（沟通质量：互相理解与回应质量）,
                "relationship_warmth": 0-100（关系温度：亲近与信任程度）,
                "risk_signals": 0-100（风险信号：注意高分=风险多，如冷淡/敷衍/冲突）},
 "evidence": [{"quote": "支撑判断的原文短句（≤30字）", "month": "出现月份"}]（最多5条）,
 "insight": "一段不超过120字的关系洞察，指出最关键的关系特征"}

要求：evidence 只能引用样本原文，禁止编造；风险信号方向注意与另两个
子分相反（高=差）。"""


class RelationshipLLMAbsent(RuntimeError):
    """LLM 关系评估缺席（未配置/样本不足/脱敏不可用/调用失败/解析失败）。"""


class RelationshipLLMService:
    """LLM 关系评估（构造器注入依赖，便于测试）。"""

    def __init__(
        self,
        model_config: dict,
        http: Optional[Callable[..., dict]] = None,
        is_remote: Optional[Callable[[dict], bool]] = None,
        redactor_factory: Optional[Callable[[], Any]] = None,
    ):
        self.model_config = model_config
        if http is None:
            from ..realtime.llm_http import post_json_with_retries

            self._http = post_json_with_retries
        else:
            self._http = http
        if is_remote is None:
            from ..realtime.rag.config import is_remote_llm_model

            self._is_remote = is_remote_llm_model
        else:
            self._is_remote = is_remote
        self._redactor_factory = redactor_factory

    # ---------- 对外 ----------

    def evaluate(
        self,
        conversation_id: int,
        account_wxid: str = "",
        context: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """评估并返回 {score, sub_scores, evidence, insight, meta}。

        任何失败抛 RelationshipLLMAbsent（调用方置缺席，不阻断其余维度）。
        """
        started = time.monotonic()
        pairs = self._sample_interaction_pairs(conversation_id)
        if len(pairs) < MIN_PAIRS:
            raise RelationshipLLMAbsent(
                f"交互对样本不足（{len(pairs)} < {MIN_PAIRS}），无法可靠评估"
            )

        remote = bool(self._is_remote(self.model_config))
        pair_texts = self._render_pair_texts(pairs)
        if remote:
            pair_texts = self._redact_pair_texts(
                pair_texts, account_wxid=account_wxid, conversation_id=conversation_id
            )

        messages = self._render_prompt(pair_texts, context or {})
        body = self._call_chat(messages)
        content = self._extract_content(body)
        finish_reason = ""
        try:
            finish_reason = str(body["choices"][0].get("finish_reason") or "")
        except (KeyError, IndexError, TypeError):
            pass
        if finish_reason == "length":
            raise RelationshipLLMAbsent(
                f"LLM 输出被 max_tokens={MAX_TOKENS} 截断（思考模型推理段过长）"
            )
        try:
            result = self._parse_response(content)
        except RelationshipLLMAbsent:
            # 带上下文的缺席原因：下次定位不用再盲猜输出形态
            logger.debug(
                "[关系评估] 解析失败 content(len=%d, finish=%s) 前300字: %s",
                len(content), finish_reason, content[:300],
            )
            raise RelationshipLLMAbsent(
                f"LLM 输出未包含可解析的 JSON 评估"
                f"（finish={finish_reason or 'unknown'}, len={len(content)}）"
            ) from None

        result["meta"] = {
            "model_name": str(self.model_config.get("name") or self.model_config.get("model_id") or ""),
            "model_id": str(self.model_config.get("model_id") or ""),
            "remote": remote,
            "sampled_pairs": len(pair_texts),
            "input_chars": sum(len(t["from_text"]) + len(t["to_text"]) for t in pair_texts),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        return result

    # ---------- 采样 ----------

    def _sample_interaction_pairs(self, conversation_id: int) -> List[Dict[str, Any]]:
        """极性 9 桶分层 + 近期优先，采样交互对文本。

        speech_units 不存内容（只有 message_ids/sender/时间戳），单元
        文本经 message_ids 回查 messages 拼接。
        """
        # SQL 侧按桶 LIMIT（ROW_NUMBER 分层 + 每桶配额）：此前全量拉取
        # 再 Python 采样，数万交互对的会话每次分析都白读 99% 数据
        bucket_count = get_db().execute(
            """
            SELECT COUNT(DISTINCT from_polarity || ':' || to_polarity)
            FROM interaction_pairs WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()[0]
        if not bucket_count:
            return []
        quota = max(2, MAX_PAIRS // int(bucket_count))
        rows = get_db().execute(
            """
            SELECT * FROM (
                SELECT ip.from_polarity, ip.to_polarity, ip.time_gap,
                       fs.message_ids AS from_ids, fs.sender AS from_sender,
                       fs.first_message_timestamp AS from_ts,
                       ts.message_ids AS to_ids, ts.sender AS to_sender,
                       ROW_NUMBER() OVER (
                           PARTITION BY ip.from_polarity, ip.to_polarity
                           ORDER BY fs.first_message_timestamp DESC
                       ) AS bucket_rank
                FROM interaction_pairs ip
                JOIN speech_units fs ON fs.id = ip.from_speech_unit_id
                JOIN speech_units ts ON ts.id = ip.to_speech_unit_id
                WHERE ip.conversation_id = ?
            ) ranked
            WHERE bucket_rank <= ?
            ORDER BY from_ts DESC
            LIMIT ?
            """,
            (conversation_id, quota, MAX_PAIRS),
        ).fetchall()
        if not rows:
            return []

        # 批量取全部涉及消息的文本（优先预处理净文本，回退原文）
        all_ids: List[int] = []
        for row in rows:
            for field in ("from_ids", "to_ids"):
                for part in str(row[field] or "").split(","):
                    part = part.strip()
                    if part.isdigit():
                        all_ids.append(int(part))
        content_by_id: Dict[int, str] = {}
        if all_ids:
            placeholders = ",".join("?" * len(all_ids))
            msg_rows = get_db().execute(
                f"""
                SELECT m.id, COALESCE(NULLIF(TRIM(mp.cleaned_content), ''), m.content) AS text
                FROM messages m
                LEFT JOIN message_preprocessed mp ON mp.message_id = m.id
                WHERE m.id IN ({placeholders})
                """,
                tuple(all_ids),
            ).fetchall()
            content_by_id = {int(r["id"]): str(r["text"] or "") for r in msg_rows}

        def _unit_text(ids_raw: Any) -> str:
            parts = []
            for part in str(ids_raw or "").split(","):
                part = part.strip()
                if part.isdigit() and int(part) in content_by_id:
                    text = content_by_id[int(part)].strip()
                    if text:
                        parts.append(text)
            return " ".join(parts)[:PER_UNIT_CHAR_LIMIT]

        # SQL 已按桶配额采样（≤40 对）；时间正序渲染（旧→新，便于读演变）
        sampled = sorted(rows, key=lambda r: int(r["from_ts"] or 0))

        pairs: List[Dict[str, Any]] = []
        for row in sampled:
            from_text = _unit_text(row["from_ids"])
            to_text = _unit_text(row["to_ids"])
            if not from_text and not to_text:
                continue
            pairs.append({
                "month": datetime.fromtimestamp(
                    int(row["from_ts"] or 0)
                ).strftime("%Y-%m"),
                "time_gap": int(row["time_gap"] or 0),
                "from_is_sender": str(row["from_sender"] or "") == "user",
                "from_text": from_text,
                "to_text": to_text,
            })

        # 总字符预算：超限时从最旧丢弃
        while pairs and sum(
            len(p["from_text"]) + len(p["to_text"]) for p in pairs
        ) > MAX_TOTAL_INPUT_CHARS:
            pairs.pop(0)
        return pairs

    # ---------- 渲染 ----------

    def _render_pair_texts(self, pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [dict(p) for p in pairs]

    def _redact_pair_texts(
        self,
        pairs: List[Dict[str, Any]],
        *,
        account_wxid: str,
        conversation_id: int,
    ) -> List[Dict[str, Any]]:
        """远程模型逐条脱敏（红线：脱敏器不可用=整维缺席）。"""
        if self._redactor_factory is None:
            raise RelationshipLLMAbsent("远程模型缺少脱敏器，按红线缺席")
        try:
            redactor = self._redactor_factory()
        except Exception as exc:
            raise RelationshipLLMAbsent(f"脱敏器构造失败: {exc}") from exc

        redacted: List[Dict[str, Any]] = []
        for pair in pairs:
            cleaned = dict(pair)
            ok = True
            for field in ("from_text", "to_text"):
                try:
                    result = redactor.redact(
                        str(pair[field]),
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        source_table="affinity_relationship_llm",
                        source_id=str(pair.get("month") or ""),
                    )
                    cleaned[field] = result.redacted_text
                except Exception as exc:
                    # 单条失败丢弃该条（对齐 fact_llm 口径），不阻断整维
                    logger.debug("[关系评估] 单条脱敏失败丢弃: %s", exc)
                    ok = False
                    break
            if ok:
                redacted.append(cleaned)
        if len(redacted) < MIN_PAIRS:
            raise RelationshipLLMAbsent(
                f"脱敏后可用样本不足（{len(redacted)} < {MIN_PAIRS}）"
            )
        return redacted

    def _render_prompt(
        self, pairs: List[Dict[str, Any]], context: Dict[str, str]
    ) -> List[dict]:
        lines: List[str] = []
        if context:
            ctx_parts = []
            if context.get("relationship_type"):
                ctx_parts.append(f"关系类型：{context['relationship_type']}")
            if context.get("interaction_duration"):
                ctx_parts.append(f"认识时长：{context['interaction_duration']}")
            if context.get("communication_style"):
                ctx_parts.append(f"沟通风格：{context['communication_style']}")
            if ctx_parts:
                lines.append("【关系背景】" + "；".join(ctx_parts))
        lines.append("【交互对样本】（时间从早到晚；格式：月份 | 回应间隔秒 | 发言）")
        for p in pairs:
            from_label = "我" if p["from_is_sender"] else "对方"
            to_label = "对方" if p["from_is_sender"] else "我"
            lines.append(
                f"{p['month']} | {p['time_gap']}s | [{from_label}] {p['from_text']}"
            )
            lines.append(f"{' ' * len(p['month'])} | → [{to_label}] {p['to_text']}")
        user_content = "\n".join(lines)
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content[:MAX_TOTAL_INPUT_CHARS + 2000]},
        ]

    # ---------- 调用与解析 ----------

    def _call_chat(self, messages: List[dict]) -> dict:
        model = self.model_config
        base_url = str(model.get("api_base_url") or "").rstrip("/")
        if not base_url:
            raise RelationshipLLMAbsent("模型配置缺少 api_base_url")
        headers = {}
        api_key = str(model.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model.get("model_id"),
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": MAX_TOKENS,
            "stream": False,
        }
        try:
            return self._http(
                url=f"{base_url}/chat/completions",
                payload=payload,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
                log=logger.debug,
                log_prefix="[关系评估]",
            )
        except RelationshipLLMAbsent:
            raise
        except Exception as exc:
            raise RelationshipLLMAbsent(f"LLM 调用失败: {exc}") from exc

    @staticmethod
    def _extract_content(body: dict) -> str:
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RelationshipLLMAbsent("LLM 响应缺少 choices") from exc
        content = message.get("content")
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
        return str(content or "")

    def _parse_response(self, content: str) -> Dict[str, Any]:
        from ..realtime.rag.fact_llm import LLMFactExtractorAdapter

        parsed: Optional[dict] = None
        for candidate in LLMFactExtractorAdapter._json_candidates(content):
            try:
                import json as _json

                obj = _json.loads(candidate)
            except Exception:
                continue
            if isinstance(obj, dict) and "score" in obj:
                parsed = obj
                break
        if parsed is None:
            raise RelationshipLLMAbsent("LLM 输出未包含可解析的 JSON 评估")

        def _clamp(value, default=50.0):
            try:
                return float(max(0.0, min(100.0, float(value))))
            except (TypeError, ValueError):
                return default

        sub_raw = parsed.get("sub_scores") or {}
        evidence = []
        for item in (parsed.get("evidence") or [])[:5]:
            if isinstance(item, dict) and item.get("quote"):
                evidence.append({
                    "quote": str(item["quote"])[:60],
                    "month": str(item.get("month") or ""),
                })
        return {
            "score": _clamp(parsed.get("score")),
            "sub_scores": {
                "communication_quality": _clamp(sub_raw.get("communication_quality")),
                "relationship_warmth": _clamp(sub_raw.get("relationship_warmth")),
                "risk_signals": _clamp(sub_raw.get("risk_signals")),
            },
            "evidence": evidence,
            "insight": str(parsed.get("insight") or "")[:300],
        }


def build_relationship_llm_service() -> Optional[RelationshipLLMService]:
    """从激活模型构造服务；未配置返回 None（延迟导入避免循环）。"""
    from ..realtime.rag.fact_llm import get_active_model_config

    model_config = get_active_model_config()
    if not model_config:
        return None

    def _redactor_factory():
        from ..realtime.privacy_redactor import PrivacyRedactor

        return PrivacyRedactor(get_db())

    return RelationshipLLMService(
        model_config, redactor_factory=_redactor_factory
    )
