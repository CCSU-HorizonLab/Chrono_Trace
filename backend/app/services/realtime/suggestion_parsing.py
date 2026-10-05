"""建议话术清洗与响应解析：从 LLM 输出提取可发送建议。

从 llm_engine.py 拆出（步骤 2B）——LLMSuggestionEngine 继承此 Mixin。
域1（话术清洗）+ 域12（响应解析）共 25 方法，全部为纯文本处理逻辑。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from .llm_client import REPAIR_SYSTEM_PROMPT
from .style_constraints import StyleConstraints, compute_style_constraints, load_cached_style_inputs
from .suggestion_engine import SuggestionResult

logger = logging.getLogger(__name__)
_print = print


class SuggestionParsingMixin:
    """话术清洗 + 响应解析：纯文本逻辑，无网络调用。"""

    def _resolve_style_constraints(self, context: dict | None = None) -> StyleConstraints:
        """Resolve style constraints from prebuilt historical context or raw cached inputs."""
        context = context or {}
        historical_ctx = context.get("historical_context", {})
        if isinstance(historical_ctx, dict):
            raw_constraints = historical_ctx.get("style_constraints")
            if isinstance(raw_constraints, dict):
                try:
                    return StyleConstraints(**raw_constraints)
                except TypeError:
                    pass

        return compute_style_constraints(
            self_profile_features=context.get("self_profile_features"),
            preprocessed_stats=context.get("preprocessed_stats"),
            affinity_result=context.get("affinity_result"),
        )

    def _has_empirical_style_constraints(self, style_constraints: StyleConstraints) -> bool:
        return (
            style_constraints.avg_msg_length > 0
            or style_constraints.emoji_density > 0
            or style_constraints.nickname_usage
            or style_constraints.communication_type != "balanced"
            or style_constraints.emotional_style != "neutral"
            or style_constraints.max_speech_length != 15
        )

    def _emoji_policy(self, style_constraints: StyleConstraints) -> str:
        if style_constraints.emoji_density >= 0.05:
            return "free"
        if style_constraints.emoji_density >= 0.01:
            return "limited"
        return "forbidden"

    def _count_emojis(self, text: str) -> int:
        return len(self.EMOJI_PATTERN.findall(text or ""))

    def _sanitize_speech_candidate(
        self,
        text: str,
        style_constraints: StyleConstraints | None = None,
    ) -> str:
        """Apply lightweight cleanup before validating sendable speech."""
        candidate = str(text or "").strip()
        if not candidate:
            return ""

        candidate = candidate.strip("`\"'“”‘’ ")
        candidate = re.sub(r"\s+", " ", candidate).strip()
        candidate = re.sub(r"([!?！？])\1+", r"\1", candidate)
        candidate = re.sub(r"([~～])\1+", r"\1", candidate)

        constraints = style_constraints or StyleConstraints(max_speech_length=48)
        emoji_policy = self._emoji_policy(constraints)
        if emoji_policy == "forbidden":
            candidate = self.EMOJI_PATTERN.sub("", candidate)
            candidate = re.sub(r"\s+", " ", candidate).strip()
        elif emoji_policy == "limited":
            chars = list(candidate)
            emoji_indexes = [
                index for index, char in enumerate(chars)
                if self.EMOJI_PATTERN.fullmatch(char)
            ]
            if len(emoji_indexes) > 1:
                keep_index = emoji_indexes[-1]
                candidate = "".join(
                    char
                    for index, char in enumerate(chars)
                    if index == keep_index or index not in emoji_indexes
                ).strip()

        if not self._has_empirical_style_constraints(constraints):
            candidate = re.sub(r"([!?！？])\1+", r"\1", candidate)

        return candidate.strip()

    def _contains_ai_antipattern(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        for phrase in self.AI_ANTIPATTERN_PHRASES:
            normalized_phrase = re.sub(r"\s+", "", phrase)
            if normalized == normalized_phrase:
                return True
            if normalized.startswith(normalized_phrase):
                remainder = normalized[len(normalized_phrase):]
                if remainder and re.fullmatch(r"[!！,，。.\-~～…]+", remainder):
                    return True
            if normalized.endswith(normalized_phrase):
                prefix = normalized[:-len(normalized_phrase)]
                if prefix and re.fullmatch(r"[\"'“”‘’\(\)（）\[\]【】]+", prefix):
                    return True
        return False

    @staticmethod
    def _strip_reasoning_text(text: str) -> str:
        """思考模型把思维链写进 content（实测 Qwen3.5-9B/Ollama：content =
        思考段 + </think> + 真答案）。取最后一个 </think> 之后；无标记原样返回。
        此前思维链直接漏进建议 summary（用户可见的泄漏）。"""
        if "</think>" not in text:
            return text
        tail = text.rsplit("</think>", 1)[-1].strip()
        return tail or text

    def _extract_message_text(
        self,
        message_obj: dict,
        *,
        allow_reasoning_fallback: bool = True,
    ) -> str:
        """兼容不同 OpenAI 兼容厂商返回的文本字段。"""
        content = self._strip_reasoning_text(message_obj.get("content", "") or "")
        reasoning = message_obj.get("reasoning_content", "") or ""

        if not content and reasoning and allow_reasoning_fallback:
            _print("[LLM Engine] ⚠️ message.content 为空，回退使用 reasoning_content")
            return reasoning

        if not content and reasoning:
            _print("[LLM Engine] ⚠️ message.content 为空，JSON 模式下忽略 reasoning_content")
            return ""

        if not content and not reasoning:
            logger.error(
                "[LLM Engine] message.content 与 reasoning_content 均为空: %s",
                json.dumps(message_obj, ensure_ascii=False)[:2000],
            )

        return content

    def _extract_json_candidate(self, text: str) -> str:
        """尽量从模型输出中提取一个可解析的 JSON 对象字符串。"""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1]
            cleaned = cleaned.split("```", 1)[0]
            return cleaned.strip()

        if "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1]
            cleaned = cleaned.split("```", 1)[0]
            return cleaned.strip()

        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned

        # 思考模型残段含多个 JSON（回显模板+真答案）：首个 { 到末个 } 的跨度
        # 会拼出非法串——平衡扫描取最后一个可解析对象（真答案在末尾）
        candidates: list[str] = []
        depth = 0
        start: int | None = None
        in_str = False
        esc = False
        for i, ch in enumerate(cleaned):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(cleaned[start:i + 1])
                    start = None
        for cand in reversed(candidates):
            try:
                json.loads(cand)
                return cand
            except Exception:
                continue
        if candidates:
            return candidates[-1]

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1].strip()

        return cleaned

    def _extract_json_array_candidate(self, text: str) -> str:
        """尽量从模型输出中提取一个可解析的 JSON 数组字符串。"""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1]
            cleaned = cleaned.split("```", 1)[0]
            cleaned = cleaned.strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1]
            cleaned = cleaned.split("```", 1)[0]
            cleaned = cleaned.strip()

        if cleaned.startswith("[") and cleaned.endswith("]"):
            return cleaned

        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                candidate, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, list):
                return json.dumps(candidate, ensure_ascii=False)
            if isinstance(candidate, dict):
                prompts = candidate.get("prompts")
                if isinstance(prompts, list):
                    return json.dumps(prompts, ensure_ascii=False)
                speeches = candidate.get("speeches")
                if isinstance(speeches, list):
                    return json.dumps(speeches, ensure_ascii=False)
        return ""

    def _normalize_quick_prompt_items(self, prompts: list, default_prompts: list[str]) -> list[str]:
        """过滤并标准化联想词，确保返回 4 个可展示的短词。"""
        valid_prompts: list[str] = []
        for item in prompts:
            if not isinstance(item, str):
                continue
            normalized = re.sub(r"^[\-\d\.\s]+", "", item).strip()
            normalized = normalized.replace("：", "").replace(":", "").strip()
            if not normalized:
                continue
            if any(keyword in normalized for keyword in self.META_SPEECH_KEYWORDS):
                continue
            normalized = re.sub(r"\s+", "", normalized)
            normalized = normalized[:8]
            if normalized and normalized not in valid_prompts:
                valid_prompts.append(normalized)

        if len(valid_prompts) >= 4:
            return valid_prompts[:4]
        if valid_prompts:
            return (valid_prompts + default_prompts)[:4]
        return default_prompts

    def _sanitize_json_candidate(self, text: str) -> str:
        """修正常见的 JSON 非法控制字符，尤其是字符串中的裸换行。"""
        if not text:
            return ""

        result: list[str] = []
        in_string = False
        escape = False

        for char in text:
            if in_string:
                if escape:
                    result.append(char)
                    escape = False
                    continue
                if char == "\\":
                    result.append(char)
                    escape = True
                    continue
                if char == "\"":
                    result.append(char)
                    in_string = False
                    continue
                if char == "\n":
                    result.append("\\n")
                    continue
                if char == "\r":
                    result.append("\\r")
                    continue
                if char == "\t":
                    result.append("\\t")
                    continue
                result.append(char)
                continue

            result.append(char)
            if char == "\"":
                in_string = True

        return "".join(result)

    def _extract_closed_json_string_field(self, text: str, field: str) -> str:
        pattern = re.compile(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', re.S)
        match = pattern.search(text or "")
        if not match:
            return ""
        raw = match.group(1)
        try:
            return json.loads(f'"{raw}"')
        except Exception:
            return raw.replace('\\"', '"').replace("\\n", "\n").strip()

    def _extract_partial_speeches(self, text: str) -> list[str]:
        """Recover completed, and last unterminated, speech strings from a cut JSON array."""
        match = re.search(r'"speeches"\s*:\s*\[', text or "")
        if not match:
            return []

        chunk = text[match.end():]
        speeches: list[str] = []
        buffer: list[str] = []
        in_string = False
        escape = False

        for char in chunk:
            if not in_string:
                if char == "]":
                    break
                if char == '"':
                    in_string = True
                    buffer = []
                continue

            if escape:
                buffer.append(char)
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                candidate = "".join(buffer).strip()
                if candidate:
                    speeches.append(candidate)
                in_string = False
                buffer = []
                continue
            buffer.append(char)

        if in_string:
            candidate = "".join(buffer).strip()
            if len(candidate) >= 2:
                speeches.append(candidate)

        deduped: list[str] = []
        for speech in speeches:
            if speech and speech not in deduped:
                deduped.append(speech)
        return deduped[:3]

    def _parse_truncated_json_fallback(
        self,
        text: str,
        trigger_type: str,
        intent: str,
        style_constraints: StyleConstraints | None = None,
    ) -> Optional[SuggestionResult]:
        """Last local fallback for API responses cut in the middle of a JSON object."""
        cleaned = self._extract_json_candidate(text)
        if not cleaned.startswith("{") or '"speeches"' not in cleaned:
            return None

        speeches = [
            self._sanitize_speech_candidate(speech, style_constraints)
            for speech in self._extract_partial_speeches(cleaned)
        ]
        speeches = [
            speech
            for speech in speeches
            if speech
            and (
                self._is_sendable_speech(speech, style_constraints)
                or (trigger_type == "manual_request" and self._is_reference_sendable_speech(speech, style_constraints))
            )
        ][:3]
        if not speeches:
            return None

        summary = self._extract_closed_json_string_field(cleaned, "summary")[:80]
        thought_process = self._extract_closed_json_string_field(cleaned, "thought_process")[:200]
        return SuggestionResult(
            trigger_type=trigger_type,
            intent=intent,
            summary=summary or "已从截断响应中提取可直接发送的话术",
            speeches=speeches,
            severity="medium",
            confidence=0.55,
            thought_process=thought_process or "模型响应被截断，已本地提取可用话术。",
            reply=None,
        )

    def _clean_speech_candidate(self, line: str) -> str:
        """清洗 reasoning 文本里候选话术的前缀噪音。"""
        candidate = re.sub(r"^[-*•\s]+", "", line.strip())
        candidate = re.sub(r"^\d+[.)、．]\s*", "", candidate)
        candidate = re.sub(r"^话术(?:建议|例子|示例)?[:：]\s*", "", candidate)
        candidate = candidate.strip("`\"'“”‘’ ")
        if "：" in candidate and candidate.split("：", 1)[0] in {"话术1", "话术2", "话术3"}:
            candidate = candidate.split("：", 1)[1].strip()
        return candidate

    def _is_sendable_speech(
        self,
        text: str,
        style_constraints: StyleConstraints | None = None,
    ) -> bool:
        """判断一段文本是否像用户可以直接发送的话术，而不是规则说明。"""
        constraints = style_constraints or StyleConstraints(max_speech_length=48)
        candidate = self._sanitize_speech_candidate(text, constraints)
        if not candidate:
            return False
        if candidate.startswith(("**", "#", "【")):
            return False
        if len(candidate) > constraints.max_speech_length:
            return False
        if any(keyword in candidate for keyword in self.META_SPEECH_KEYWORDS):
            return False
        if re.fullmatch(r"话术\d+", candidate):
            return False
        if self._contains_ai_antipattern(candidate):
            return False
        emoji_count = self._count_emojis(candidate)
        emoji_policy = self._emoji_policy(constraints)
        if emoji_policy == "forbidden" and emoji_count:
            return False
        if emoji_policy == "limited" and emoji_count > 1:
            return False
        return True

    def _is_reference_sendable_speech(
        self,
        text: str,
        style_constraints: StyleConstraints | None = None,
    ) -> bool:
        """
        更宽松地判断一段文本是否至少值得展示给用户参考。
        用于 manual_request 场景下，避免因为长度略长把整组话术全部降级成 PURE_CHAT。
        """
        constraints = style_constraints or StyleConstraints(max_speech_length=48)
        candidate = self._sanitize_speech_candidate(text, constraints)
        if not candidate:
            return False
        if candidate.startswith(("**", "#", "【")):
            return False
        if len(candidate) > max(80, constraints.max_speech_length):
            return False
        if any(keyword in candidate for keyword in self.META_SPEECH_KEYWORDS):
            return False
        if re.fullmatch(r"话术\d+", candidate):
            return False
        if self._contains_ai_antipattern(candidate):
            return False
        emoji_count = self._count_emojis(candidate)
        emoji_policy = self._emoji_policy(constraints)
        if emoji_policy == "forbidden" and emoji_count:
            return False
        if emoji_policy == "limited" and emoji_count > 1:
            return False
        return True

    def _looks_like_meta_reasoning(self, text: str) -> bool:
        meta_keywords = (
            "JSON",
            "reply",
            "summary",
            "thought_process",
            "speeches",
            "输出格式",
            "用户目标",
            "当前对话",
            "规则",
            "结构",
            "模式",
            "触发",
            "关系状态",
        )
        return any(keyword in text for keyword in meta_keywords)

    def _extract_speeches_from_reasoning(
        self,
        text: str,
        style_constraints: StyleConstraints | None = None,
    ) -> list[str]:
        """从 reasoning 型自由文本中尽量提取可发送的话术。"""
        lines = [line.rstrip() for line in (text or "").splitlines()]
        speeches: list[str] = []
        collecting = False
        markers = ("话术例子", "建议话术", "示例话术", "可以发", "可直接发", "可发")
        stop_markers = ("输出必须", "输出格式", "结构：", "所以，结构", "因此，结构", "`reply`", "`thought_process`")

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                if collecting and speeches:
                    break
                continue

            if any(marker in line for marker in markers):
                collecting = True
                remainder = re.split(r"[:：]", line, maxsplit=1)
                if len(remainder) == 2:
                    candidate = self._clean_speech_candidate(remainder[1])
                    candidate = self._sanitize_speech_candidate(candidate, style_constraints)
                    if candidate and self._is_sendable_speech(candidate, style_constraints):
                        speeches.append(candidate)
                continue

            if not collecting:
                continue

            if any(marker in line for marker in stop_markers):
                if speeches:
                    break
                collecting = False
                continue

            bullet_like = bool(re.match(r"^[-*•]\s*", line) or re.match(r"^\d+[.)、．]\s*", line))
            if not bullet_like:
                if speeches:
                    break
                continue

            candidate = self._clean_speech_candidate(line)
            candidate = self._sanitize_speech_candidate(candidate, style_constraints)
            if not self._is_sendable_speech(candidate, style_constraints):
                continue
            speeches.append(candidate)
            if len(speeches) >= 3:
                break

        if not speeches:
            for raw_line in lines:
                line = raw_line.strip()
                if not (re.match(r"^[-*•]\s*", line) or re.match(r"^\d+[.)、．]\s*", line)):
                    continue
                candidate = self._clean_speech_candidate(line)
                candidate = self._sanitize_speech_candidate(candidate, style_constraints)
                if not self._is_sendable_speech(candidate, style_constraints):
                    continue
                speeches.append(candidate)
                if len(speeches) >= 3:
                    break

        deduped: list[str] = []
        for speech in speeches:
            if speech not in deduped:
                deduped.append(speech)
        return deduped[:3]

    def _build_reasoning_fallback_summary(
        self, text: str, trigger_type: str, speeches: list[str]
    ) -> str:
        """为非 JSON reasoning 输出构造一个可显示的摘要。"""
        if trigger_type == "manual_request":
            if "开启话题" in text or "开场" in text:
                return "给出几条可直接发送的开启话题话术"
            return "已从思考输出中提取可直接发送的话术"
        if trigger_type == "emotion_shift":
            return "顺着对方最新情绪做轻量回应"
        if trigger_type == "topic_cooling":
            return "顺着当前语境补一条自然续聊的话术"
        if speeches:
            return "已从思考输出中提取建议话术"
        return ""

    def _is_placeholder_structured_output(self, data: dict) -> bool:
        """识别模型复读输出格式示例时产生的占位 JSON。"""
        summary = str(data.get("summary", "")).strip()
        reply = str(data.get("reply", "")).strip()
        thought_process = str(data.get("thought_process", "")).strip()
        speeches = data.get("speeches", [])

        if summary in self.PLACEHOLDER_SUMMARIES:
            return True
        if reply.startswith("（如果用户有提问或反馈"):
            return True
        if thought_process.startswith("用一两句话简述"):
            return True

        if isinstance(speeches, list):
            normalized = [str(item).strip() for item in speeches if str(item).strip()]
            if normalized and all(re.fullmatch(r"话术\d+", item) for item in normalized):
                return True

        return False

    def _parse_reasoning_fallback(
        self,
        text: str,
        trigger_type: str,
        intent: str,
        style_constraints: StyleConstraints | None = None,
    ) -> Optional[SuggestionResult]:
        """当模型没有返回 JSON 时，尽量从 reasoning 自由文本中兜底提取结果。"""
        cleaned = (text or "").strip()
        if not cleaned:
            return None

        speeches = self._extract_speeches_from_reasoning(cleaned, style_constraints)
        if not speeches:
            return None
        summary = self._build_reasoning_fallback_summary(cleaned, trigger_type, speeches)
        if not summary:
            return None

        return SuggestionResult(
            trigger_type=trigger_type,
            intent=intent,
            summary=summary or "[PURE_CHAT]",
            speeches=speeches,
            severity="medium",
            confidence=0.65,
            thought_process=cleaned,
            reply=None,
        )

    def _repair_response(
        self, model_config: dict, user_prompt: str, raw_response: str
    ) -> str:
        """当首轮输出偏 meta / 非 JSON 时，做一次轻量结构化整理。"""
        repair_prompt = (
            "【当前聊天建议任务上下文】\n"
            f"{user_prompt[:3200]}\n\n"
            "【失败说明】\n"
            "上一次输出不是合法 JSON，或者结果里混入了规则说明/Prompt 片段。"
            "请不要解释失败原因，不要续写旧输出，直接重新给最终 JSON。\n\n"
            "如果你能从下面的坏输出片段里借用少量有价值的信息可以参考，否则忽略它：\n"
            f"{raw_response[:220] if raw_response.strip() else '（无）'}"
        )
        try:
            return self._call_api_with_messages(
                model_config,
                [
                    {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ],
                temperature=0.2,
                request_tag="repair",
            )
        except Exception as e:
            _print(f"[LLM Engine] 修复响应失败: {e}")
            return ""

    def _parse_response(
        self,
        text: str,
        trigger_type: str,
        intent: str,
        style_constraints: StyleConstraints | None = None,
    ) -> Optional[SuggestionResult]:
        """解析 LLM 返回的 JSON"""
        try:
            cleaned = self._extract_json_candidate(text)
            cleaned = cleaned.strip()
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                sanitized = self._sanitize_json_candidate(cleaned)
                data = json.loads(sanitized)
            if self._is_placeholder_structured_output(data):
                raise ValueError("模型返回了输出格式占位 JSON")

            thought_process = data.get("thought_process", "").strip()
            summary = data.get("summary", "").strip()
            speeches = data.get("speeches", [])
            reply = data.get("reply", "").strip()

            # 确保 speeches 是合法的列表
            if isinstance(speeches, str):
                # 如果大模型返回的是纯字符串，包裹一层
                speeches = [speeches]
            elif not isinstance(speeches, list):
                speeches = []

            # 确保 speeches 是字符串列表
            speeches = [
                self._sanitize_speech_candidate(str(s).strip(), style_constraints)
                for s in speeches
                if s
            ]
            speeches = [speech for speech in speeches if speech]
            valid_speeches = [
                speech for speech in speeches if self._is_sendable_speech(speech, style_constraints)
            ]
            if speeches and not valid_speeches:
                if trigger_type == "manual_request":
                    relaxed_speeches = [
                        speech
                        for speech in speeches
                        if self._is_reference_sendable_speech(speech, style_constraints)
                    ]
                    if relaxed_speeches and (reply or len(relaxed_speeches) == len(speeches)):
                        _print("[LLM Engine] ⚠️ manual_request 话术未通过严格校验，已保留为参考话术展示")
                        speeches = relaxed_speeches[:3]
                    elif reply:
                        speeches = []
                    else:
                        raise ValueError("模型返回的 speeches 更像规则说明，不是可发送话术")
                elif not reply:
                    raise ValueError("模型返回的 speeches 更像规则说明，不是可发送话术")
                else:
                    speeches = []
            else:
                speeches = valid_speeches
            if speeches:
                if not summary or summary == "[SILENT]":
                    summary = "已生成可直接发送的话术"
            elif reply:
                summary = "[PURE_CHAT]"
            elif not summary:
                # 允许模型保持沉默（既没建议也不回复用户）
                summary = "[SILENT]"

            return SuggestionResult(
                trigger_type=trigger_type,
                intent=intent,
                summary=summary,
                speeches=speeches,
                severity="medium",
                confidence=0.9,
                thought_process=thought_process or None,
                reply=reply or None
            )
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            candidate = self._extract_json_candidate(text).strip()
            if isinstance(e, json.JSONDecodeError) or (candidate.startswith("{") and not candidate.endswith("}")):
                truncated_result = self._parse_truncated_json_fallback(
                    text,
                    trigger_type,
                    intent,
                    style_constraints=style_constraints,
                )
                if truncated_result:
                    _print("[LLM Engine] ⚠️ JSON 响应疑似被截断，已本地提取可用话术")
                    return truncated_result
            fallback_result = self._parse_reasoning_fallback(
                text,
                trigger_type,
                intent,
                style_constraints=style_constraints,
            )
            if fallback_result:
                _print("[LLM Engine] ⚠️ 检测到非 JSON reasoning 输出，已本地提取建议结果")
                return fallback_result
            preview = (text or "")[:2000]
            logger.error("[LLM Engine] JSON 解析失败: %s | 原始响应: %s", e, preview)
            _print(f"[LLM Engine] JSON 解析失败: {e}, 原始文本: {preview[:200]}")
            return None

