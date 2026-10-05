"""LLM API 客户端层：网络/重试/流式/预算/模型发现。

从 llm_engine.py 拆出（步骤 2A）——LLMSuggestionEngine 继承此 Mixin，
方法名不变、测试直调兼容。唯一实例态 `_models_cache`/`_cache_ttl` 仍由
引擎 __init__ 初始化（Mixin 通过 self 访问）。
"""
from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

BASE_RETRY_DELAY = 1.5
MAX_RETRIES = 3

_print = print


SYSTEM_PROMPT = """你是一个专业的聊天沟通顾问，但你当前必须作为【用户本人】的思考替身。你的任务是根据当前的对话情绪状态和长期记忆，为用户提供接下来该怎么回复的建议。

【核心克隆规则】
1. **千人千面，消除机味**：你必须彻底抛开所有 AI 常用的客套话、转折词、反问句、安抚腔和过度同理心。
2. **先适配对方，再贴近自己**：建议话术首先应适合「对方画像」呈现的性格、聊天风格与沟通注意事项（策略正确优先）；在此基础上尽量贴近「用户表达风格」与「量化风格硬约束」的打字风格、标点、句式与长度（读起来像用户本人写的）。两者冲突时，选择适配对方；风格模仿不能损害当前对话目标。
3. 内容必须贴合当前情境和已有的关系进度，严禁空泛。
4. **身份区分**："我"是用户本人（发建议的人），"对方"是聊天对象。在引用记忆/事实时，严禁混淆谁做了什么。
5. **【时效优先】核心注意力规则**：
   - 你的注意力必须优先集中在【最近对话】中，先理解眼前正在发生什么
   - 默认按时间顺序阅读最近 20 条消息，但注意力必须随时间递增：越新的消息权重越高，越早的消息只作背景参考
   - 【被唤醒的历史记忆】只有在对方最近消息里明确提到相关话题时才能使用
   - 禁止主动翻出历史记忆作为建议主轴，除非对方刚刚提起
   - 如果历史记忆与当前对话无关，直接忽略它
   - 规则、画像和长期偏好只能约束“怎么说”，不能决定“聊什么”
   - 如果规则/画像与【最近对话】冲突，必须以【最近对话】和当前触发为准
   - **仲裁规则：【用户需求与反馈】里用户的显式提问,永远高于你对【最近对话】走向的自行解读**。用户问"怎么回 X",就必须回答怎么回 X;不得因为窗口看起来"话题已变/事情已过去"而改答别的或宣布"不用再提 X"。窗口与提问冲突时,先回答用户问的,再把窗口里的新情况作为补充。
   - 如果触发是 emotion_shift，只能围绕对方最新那条偏负面的表达做轻量关心或顺势接话，禁止脑补重大心事或过度安慰
6. **回应用户与纯对话**：如果【用户需求与反馈】中有用户的提问或想法，你必须在 reply 字段直接回应他的问题。
   - 当 `reply` 是 AI 对用户本人说的话时，必须使用自然、简洁的助手口吻。
   - 此时不要模仿用户给对方发消息的语气，不要使用“宝贝”等对方专属称呼，也不要套用联系人关系设定。
7. **【极其重要】判定模式机制**：
   - 模式 A（纯聊天/指令/修改规则）：如果用户输入只是打招呼（如“你好”）、闲聊、或是要求修改你的回复规则，你**绝对不可提供任何对话建议**！你只能在 `reply` 字段内回答他，同时**必须**将 `summary` 设为空字符串 `""`，`speeches` 设为空数组 `[]`！禁止硬凑无关紧要的建议卡片！
   - 模式 B（请求指导/冷场）：只有在用户明确请教怎么回复对方、或者你检测到聊天即将冷场必须介入时，才能提供 `summary` 和 `speeches`。
   - 模式 C（具体事项求助）：用户在请教一件具体事项（例如想约对方见面/打游戏、想推进关系）时，在 `reply` 中直接回应用户的想法，同时在 `speeches` 中给出 2-3 条可直接发送给对方的原话；`summary` 概括建议。两者都要有内容，缺一不可。
8. **反 AI 腔**：禁止输出下列典型句式或近似表达：“我理解你的感受”“别太难过了”“你说得对”“有什么我能帮到你的吗”“要不要我陪你聊聊”“你值得被温柔以待”“加油哦”“抱抱你”。
9. **短句优先**：真人微信更像碎片化短句，不要为了完整而完整，不要硬凑主谓宾，不要把一句话写成小作文。
10. 严格按 JSON 格式输出，禁止输出引导语或 Markdown。
11. 输出必须短：reply 不超过 80 字，thought_process 不超过 80 字，summary 不超过 40 字，每条 speeches 不超过 30 字。

输出格式（纯 JSON，无 markdown）：
{
  "reply": "（如果用户有提问或反馈，在这里直接回应用户的话；如果没有用户输入，此字段留空字符串）",
  "thought_process": "用一两句话简述你是如何推断对方的情感以及为什么提供以下建议的",
  "summary": "一句话建议摘要（若无须提供建议则留空）", 
  "speeches": ["话术1", "话术2", "话术3"]
}"""

ANALYSIS_SYSTEM_PROMPT = """你是用户的聊天思考助手。请先只做分析，不要输出 JSON。

要求：
1. 只分析眼前这段聊天上下文现在该聊什么、为什么这么聊。
2. 可以参考用户风格和对方画像，但不要复述整段 prompt。
3. 不要输出规则标题，不要输出“reply/summary/speeches/thought_process”这类字段名。
4. 如果上下文判断这是“用户在直接和 AI 说话/提问”，不要生成发给对方的话术草稿；只需说明应该直接回复用户。
5. 只有在上下文明确是在请教“怎么回复对方/怎么开启话题”时，最后才单独给出 1 到 3 条“可直接发送的话术草稿”，每条单独成行，以 `- ` 开头。
6. 除了分析和草稿，不要输出别的格式说明。"""

REPAIR_SYSTEM_PROMPT = """你是一个结果整理器。你会收到：
1. 当前聊天建议任务的上下文
2. 一次失败的历史说明（可选）

你的任务不是继续分析规则，而是直接重新给出最终结果。

要求：
1. 只输出纯 JSON，不要输出解释、前言、Markdown。
2. `speeches` 必须是用户可以直接发送给对方的原句，不能是规则、分析、Prompt 片段、字段说明。
3. 如果上下文属于“用户在直接和 AI 说话/提问”，则必须把最终回答放进 `reply`，并将 `summary` 设为空字符串、`speeches` 设为空数组，不要生成建议卡片。此时 `reply` 要使用自然、简洁的助手口吻，不要模仿用户对第三方说话的语气。
4. 如果没有足够可靠的话术，就返回空 `speeches`，不要编造 prompt 规则。
5. `thought_process` 只保留一两句简短总结，不要复述长篇思维链。
6. 输出必须短：reply 不超过 80 字，thought_process 不超过 80 字，summary 不超过 40 字，每条 speeches 不超过 30 字。
7. 不要续写坏掉的 JSON，不要分析“你收到什么任务”，只给最终结果。

输出格式：
{
  "reply": "",
  "thought_process": "",
  "summary": "",
  "speeches": []
}"""

QUICK_PROMPTS_SYSTEM_PROMPT = """你是一个聊天联想词生成器。
你的唯一任务是根据最近聊天记录，输出 4 个“用户下一步可能发起的话题方向/对话策略”短语。
要求：
1. 只能输出一个 JSON 字符串数组，例如 ["顺着话题","转移话题","表达关心","约她吃饭"]。
2. 每个元素都必须是简短的动宾短语，尽量控制在 4 个字内。
3. 不要输出分析、解释、思考过程、规则复述、字段名、Markdown 或代码块。
4. 如果上下文很少，也要基于当前最后几句聊天给出最可能的 4 个方向，不要拒答。
"""

BASE_RETRY_DELAY = 1.5

MAX_API_RETRIES = 3

RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


class LlmClientMixin:
    """API 客户端：网络调用/重试/流式读取/token 预算/模型发现。"""

    def _is_timeout_error(self, err: Exception) -> bool:
        if isinstance(err, (TimeoutError, socket.timeout)):
            return True
        if isinstance(err, urllib.error.URLError):
            reason = getattr(err, "reason", None)
            return isinstance(reason, (TimeoutError, socket.timeout))
        return False

    def _compute_retry_delay(self, attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                pass
        return BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0.0, 0.5)

    def _is_reasoning_model(self, model_id: str) -> bool:
        normalized = (model_id or "").lower()
        return any(tag in normalized for tag in (
            "reasoner", "deepseek-r1", "-r1", "qwen3", "qwq",
            "o1", "o3", "thinking",
        ))

    def _fetch_available_models(self, base_url: str, api_key: str = "") -> list[str] | None:
        """查询厂商 /models 端点获取可用模型列表，带缓存"""
        # 检查缓存
        cached = self._models_cache.get(base_url)
        if cached:
            ts, model_ids = cached
            if time.time() - ts < self._cache_ttl:
                return model_ids
        
        url = f"{base_url.rstrip('/')}/models"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            
            # OpenAI 兼容格式: {"data": [{"id": "model-name", ...}, ...]}
            models_data = body.get("data", [])
            if isinstance(models_data, list):
                model_ids = [m.get("id", "") for m in models_data if isinstance(m, dict) and m.get("id")]
                self._models_cache[base_url] = (time.time(), model_ids)
                _print(f"[LLM Engine] 📋 查询到 {len(model_ids)} 个可用模型: {model_ids[:10]}")
                return model_ids
            
            return None
        except Exception as e:
            _print(f"[LLM Engine] ⚠️ 查询可用模型列表失败 ({url}): {e}")
            return None

    def _validate_model_id(self, model_id: str, base_url: str, api_key: str = "") -> str:
        """校验 model_id 是否在厂商可用列表中，不在则模糊匹配修正"""
        available = self._fetch_available_models(base_url, api_key)
        if available is None:
            # 查询失败，保持原值
            return model_id
        
        # 精确匹配
        if model_id in available:
            return model_id
        
        # 模糊匹配：找到包含 model_id 的模型（如 "deepseek" 匹配 "deepseek-chat"）
        model_id_lower = model_id.lower().strip()
        candidates = []
        for m in available:
            m_lower = m.lower()
            if model_id_lower in m_lower or m_lower.startswith(model_id_lower):
                candidates.append(m)
        
        if len(candidates) == 1:
            corrected = candidates[0]
            _print(f"[LLM Engine] ⚠️ model_id \"{model_id}\" 已自动修正为 \"{corrected}\"")
            return corrected
        elif len(candidates) > 1:
            # 多个匹配，优先选 chat 类型的
            for c in candidates:
                if 'chat' in c.lower():
                    _print(f"[LLM Engine] ⚠️ model_id \"{model_id}\" 有多个匹配 {candidates}，选择 \"{c}\"")
                    return c
            # 没有 chat 类型，选第一个
            corrected = candidates[0]
            _print(f"[LLM Engine] ⚠️ model_id \"{model_id}\" 有多个匹配 {candidates}，选择 \"{corrected}\"")
            return corrected
        
        # 没有匹配，保持原值（可能是自定义/私有部署模型）
        _print(f"[LLM Engine] ⚠️ model_id \"{model_id}\" 不在可用列表中，保持原值（可用: {available[:5]}...）")
        return model_id

    def _supports_json_mode(self, model_config: dict, base_url: str) -> bool:
        """仅对较稳定支持 response_format 的远端厂商启用 JSON 模式。"""
        provider = str(model_config.get("provider", "")).lower()
        if provider in self.JSON_MODE_PROVIDERS:
            return True

        normalized_url = base_url.lower()
        return "api.openai.com" in normalized_url or "api.deepseek.com" in normalized_url

    def _boost_reasoning_max_tokens(self, model_id: str, max_tokens: int, request_tag: str) -> int:
        """reasoning 模型容易把输出预算耗在思维过程上，给结构化结果更高上限。"""
        is_reasoning_model = self._is_reasoning_model(model_id)
        if not is_reasoning_model:
            return max_tokens

        # 思维链本身耗 500-2000+ token（实测 Qwen3.5-9B），预算需覆盖
        # 思考段+结构化结果，否则截断到无 JSON/无建议
        if request_tag == "analysis":
            return max(max_tokens, 4096)
        if request_tag == "repair":
            return max(max_tokens, 2048)
        if request_tag == "suggestion":
            return max(max_tokens, 3072)
        if request_tag == "format":
            return max(max_tokens, 2048)
        return max(max_tokens, 2048)

    def _estimate_message_tokens(self, messages: list[dict]) -> int:
        """Rough local estimate used only to size completion budget before the API call."""
        chars = 0
        for message in messages:
            chars += len(str(message.get("content") or ""))
        return max(1, int(chars / 2.4))

    def _dynamic_completion_tokens(self, messages: list[dict], request_tag: str) -> int:
        """Raise JSON completion budget only when the current prompt is likely to need it."""
        prompt_tokens = self._estimate_message_tokens(messages)
        if request_tag == "suggestion":
            if prompt_tokens <= 650:
                return 768
            if prompt_tokens <= 1100:
                return 1024
            if prompt_tokens <= 1800:
                return 1280
            return 1536
        if request_tag == "repair":
            if prompt_tokens <= 900:
                return 896
            if prompt_tokens <= 1600:
                return 1152
            return 1408
        if request_tag == "format":
            if prompt_tokens <= 1200:
                return 768
            if prompt_tokens <= 2200:
                return 1024
            return 1280
        return 0

    def _default_completion_tokens(self, request_tag: str) -> int:
        """Internal defaults for non-user-facing completion sizing."""
        if request_tag == "analysis":
            return 1024
        if request_tag == "quick_prompts":
            return 128
        return 0

    def _call_api_with_messages(
        self,
        model_config: dict,
        messages: list[dict],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        request_tag: str = "suggestion",
        use_json_mode: bool = True,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """调用 OpenAI 兼容 API，并允许传入自定义消息。"""
        base_url = model_config["api_base_url"].rstrip("/")
        api_key = model_config.get("api_key", "")
        model_id = model_config["model_id"]
        max_tokens = self._default_completion_tokens(request_tag) if max_tokens is None else int(max_tokens)
        temperature = model_config.get("temperature", 0.7) if temperature is None else temperature

        # Bug 2: 动态校验并修正 model_id
        model_id = self._validate_model_id(model_id, base_url, api_key)
        max_tokens = max(
            self._boost_reasoning_max_tokens(model_id, int(max_tokens), request_tag),
            self._dynamic_completion_tokens(messages, request_tag),
        )

        url = f"{base_url}/chat/completions"

        payload = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stream_callback:
            payload["stream"] = True
        if use_json_mode and self._supports_json_mode(model_config, base_url):
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        _print(f"[LLM Engine] 📤 POST {url}")
        _print(
            f"[LLM Engine] 📤 [{request_tag}] model={model_id}, temp={temperature}, max_tokens={max_tokens}"
        )
        if payload.get("response_format"):
            _print("[LLM Engine] 📤 已启用 response_format=json_object")
        if payload.get("stream"):
            _print("[LLM Engine] 📤 已启用 stream=true")

        body = None
        streamed_content = ""
        for attempt in range(MAX_API_RETRIES + 1):
            start_time = time.time()
            # 记录本轮是否已向前端下发过流式增量：一旦发过，超时就不能再静默从头重试，
            # 否则重试会把同样的 delta 再发一遍，前端拼接出重复文本。
            emitted_any_delta = False
            emitted_content_parts: list[str] = []
            emitted_reasoning_parts: list[str] = []

            def _tracked_stream_callback(event: dict[str, Any]) -> None:
                nonlocal emitted_any_delta
                if stream_callback is None:
                    return
                if event.get("type") == "delta":
                    emitted_any_delta = True
                    if event.get("channel") == "reasoning":
                        emitted_reasoning_parts.append(str(event.get("text") or ""))
                    else:
                        emitted_content_parts.append(str(event.get("text") or ""))
                stream_callback(event)

            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status_code = resp.status
                    if payload.get("stream"):
                        streamed_content = self._read_streaming_response(
                            resp,
                            stream_callback=_tracked_stream_callback,
                            allow_reasoning_fallback=not use_json_mode,
                        )
                        body = {"choices": [{"message": {"content": streamed_content}}], "usage": {}}
                    else:
                        body = json.loads(resp.read().decode("utf-8"))
                elapsed = time.time() - start_time
                _print(f"[LLM Engine] 📥 HTTP {status_code} ({elapsed:.2f}s)")
                break
            except urllib.error.HTTPError as e:
                status_code = getattr(e, "code", None)
                if payload.get("stream") and status_code in {400, 404, 422}:
                    _print(f"[LLM Engine] ⚠️ stream 请求被拒绝(HTTP {status_code})，回退非流式")
                    self._emit_stream(
                        stream_callback,
                        "stage",
                        stage="fallback",
                        message="模型不支持流式，切回普通生成",
                    )
                    return self._call_api_with_messages(
                        model_config,
                        messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        request_tag=request_tag,
                        use_json_mode=use_json_mode,
                        stream_callback=None,
                    )
                if status_code in RETRYABLE_HTTP_STATUS and attempt < MAX_API_RETRIES:
                    delay = self._compute_retry_delay(attempt, e.headers.get("Retry-After"))
                    _print(f"[LLM Engine] Retry on HTTP {status_code} after {delay:.1f}s (attempt {attempt + 1})")
                    time.sleep(delay)
                    continue
                raise
            except Exception as e:
                if self._is_timeout_error(e) and attempt < MAX_API_RETRIES:
                    if emitted_any_delta:
                        # 本轮已下发过增量，重试会导致前端重复拼接；
                        # 放弃重试，把已收到的部分作为截断结果返回，
                        # 交给上层与"JSON 截断"一致的兜底解析路径处理。
                        partial = "".join(emitted_content_parts)
                        if not partial and not use_json_mode:
                            partial = "".join(emitted_reasoning_parts)
                        if partial:
                            _print(
                                "[LLM Engine] ⚠️ 流式响应中途超时且已下发增量，"
                                f"放弃重试，按截断结果返回已收到的 {len(partial)} 字符"
                            )
                            return partial.strip()
                        _print("[LLM Engine] ⚠️ 流式响应中途超时且已下发增量但无可用文本，按超时失败处理")
                        raise
                    delay = self._compute_retry_delay(attempt)
                    _print(f"[LLM Engine] Retry on timeout after {delay:.1f}s (attempt {attempt + 1})")
                    time.sleep(delay)
                    continue
                raise

        if body is None:
            raise RuntimeError("LLM API did not return a response body")

        # 提取生成文本
        choices = body.get("choices", [])
        if not choices:
            raise ValueError("API 返回空 choices")

        message_obj = choices[0].get("message", {})
        content = self._extract_message_text(
            message_obj,
            allow_reasoning_fallback=not use_json_mode,
        )
        usage = body.get("usage", {})
        _print(
            f"[LLM Engine] 📥 tokens: prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')}, "
            f"total={usage.get('total_tokens', '?')}"
        )

        return content.strip()

    def _read_streaming_response(
        self,
        resp: Any,
        *,
        stream_callback: Callable[[dict[str, Any]], None] | None,
        allow_reasoning_fallback: bool,
    ) -> str:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        for raw_line in resp:
            try:
                line = raw_line.decode("utf-8").strip()
            except Exception:
                continue
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except Exception:
                continue
            choices = payload.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content") or ""
            reasoning = delta.get("reasoning_content") or ""
            if text:
                content_parts.append(str(text))
                self._emit_stream(stream_callback, "delta", text=str(text), channel="content")
            elif reasoning:
                reasoning_parts.append(str(reasoning))
                self._emit_stream(stream_callback, "delta", text=str(reasoning), channel="reasoning")
        content = "".join(content_parts)
        if content:
            return content
        if allow_reasoning_fallback:
            return "".join(reasoning_parts)
        return ""

    def _fast_suggestion_mode_enabled(self) -> bool:
        """实时建议快速模式：思考模型前置 /no_think（实测 Qwen3.5 30-60s→1.5s）。

        深度类调用（RAG 事实抽取/分析）不走此开关，保留思考能力。
        """
        try:
            from ..wechat.account_settings import load_settings_from_file
            return bool(load_settings_from_file().get("llm_fast_suggestion_mode", True))
        except Exception:
            return True

    def _suggestion_system_prompt(self, model_config: dict) -> str:
        if self._fast_suggestion_mode_enabled() and self._is_reasoning_model(
            str(model_config.get("model_id") or "")
        ):
            return "/no_think\n" + SYSTEM_PROMPT
        return SYSTEM_PROMPT

    def _call_api(
        self,
        model_config: dict,
        user_prompt: str,
        *,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """调用 OpenAI 兼容 API"""
        return self._call_api_with_messages(
            model_config,
            [
                {"role": "system", "content": self._suggestion_system_prompt(model_config)},
                {"role": "user", "content": user_prompt},
            ],
            request_tag="suggestion",
            stream_callback=stream_callback,
        )

    def _resolve_formatter_model_config(self, model_config: dict) -> dict:
        """reasoner 负责思考，格式化阶段尽量切到同厂商 chat 模型。"""
        if not self._is_reasoning_model(model_config.get("model_id", "")):
            return dict(model_config)

        base_url = model_config["api_base_url"].rstrip("/")
        api_key = model_config.get("api_key", "")
        available = self._fetch_available_models(base_url, api_key) or []
        for candidate in available:
            if candidate.lower() == "deepseek-chat":
                formatter_config = dict(model_config)
                formatter_config["model_id"] = candidate
                _print(f"[LLM Engine] 🔀 格式化阶段使用 chat 模型: {candidate}")
                return formatter_config
        return dict(model_config)

    def _generate_reasoning_analysis(self, model_config: dict, user_prompt: str) -> str:
        """第一阶段：仅生成思考过程和候选话术草稿。"""
        return self._call_api_with_messages(
            model_config,
            [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            request_tag="analysis",
            use_json_mode=False,
        )

    def _format_reasoning_result(self, model_config: dict, user_prompt: str, analysis_text: str) -> str:
        """第二阶段：基于上下文和分析文本，只输出最终 JSON。"""
        formatter_config = self._resolve_formatter_model_config(model_config)
        format_prompt = (
            "【当前聊天建议任务上下文】\n"
            f"{user_prompt[:3200]}\n\n"
            "【分析阶段输出】\n"
            f"{analysis_text[:2200]}\n\n"
            "请直接输出最终 JSON。"
            "如果上下文显示这是在直接回复用户而不是代用户给对方发消息，"
            "请把正文放进 reply，并将 summary 置空、speeches 置为空数组。"
            "此时 reply 必须使用自然、简洁的助手口吻。"
            "注意：speeches 必须是用户可以直接复制发送给对方的话，不得复述画像字段、规则标题或 prompt 原文。"
        )
        return self._call_api_with_messages(
            formatter_config,
            [
                {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": format_prompt},
            ],
            temperature=0.2,
            request_tag="format",
        )

    def _call_quick_prompts_api(self, model_config: dict, user_prompt: str) -> str:
        """联想词使用独立 system prompt，避免被建议卡片的规则污染。"""
        formatter_config = self._resolve_formatter_model_config(model_config)
        return self._call_api_with_messages(
            formatter_config,
            [
                {"role": "system", "content": QUICK_PROMPTS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=128,
            temperature=0.2,
            request_tag="quick_prompts",
            use_json_mode=False,
        )

