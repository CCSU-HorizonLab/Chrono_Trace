"""
LLM 建议引擎

基于 OpenAI 兼容格式的 LLM 建议引擎，
支持远程 API（DeepSeek/OpenAI）和本地推理（Ollama/LM Studio）。
超时或异常时自动降级到模板引擎。
"""

import json
import logging
import random
import socket
import time
import urllib.request
import urllib.error
from typing import Optional

from .suggestion_engine import SuggestionEngine, SuggestionResult


# Prompt 系统模板
SYSTEM_PROMPT = """你是一个专业的聊天沟通顾问，但你当前必须作为【用户本人】的思考替身。你的任务是根据当前的对话情绪状态和长期记忆，为用户提供接下来该怎么回复的建议。

【核心克隆规则】
1. **千人千面，消除机味**：你必须彻底抛开所有 AI 常用的客套话、转折词、反问句和过度同理心。
2. **完美模仿用户风格**：你给出的所有的"建议话术"，必须【逐字逐句完全模仿】提供的「用户本体克隆画像」中的打字风格、标点习惯、常用语气词、句式模板、建议字数区间和沟通态度。这非常关键！
3. 内容必须贴合当前情境和已有的关系进度，严禁空泛。
4. **身份区分**："我"是用户本人（发建议的人），"对方"是聊天对象。在引用记忆/事实时，严禁混淆谁做了什么。
5. **时效性**：优先利用近期记忆和事件，避免引用太久远的事情。如果记忆标注了时间，请根据新鲜度判断是否适合当前话题。
6. **回应用户与纯对话**：如果【用户需求与反馈】中有用户的提问或想法，你必须在 reply 字段直接回应他的问题。
7. **【极其重要】判定模式机制**：
   - 模式 A（纯聊天/指令/修改规则）：如果用户输入只是打招呼（如“你好”）、闲聊、或是要求修改你的回复规则，你**绝对不可提供任何对话建议**！你只能在 `reply` 字段内回答他，同时**必须**将 `summary` 设为空字符串 `""`，`speeches` 设为空数组 `[]`！禁止硬凑无关紧要的建议卡片！
   - 模式 B（请求指导/冷场）：只有在用户明确请教怎么回复对方、或者你检测到聊天即将冷场必须介入时，才能提供 `summary` 和 `speeches`。
8. 严格按 JSON 格式输出，禁止输出引导语或 Markdown。

输出格式（纯 JSON，无 markdown）：
{
  "reply": "（如果用户有提问或反馈，在这里直接回应用户的话；如果没有用户输入，此字段留空字符串）",
  "thought_process": "用一两句话简述你是如何推断对方的情感以及为什么提供以下建议的",
  "summary": "一句话建议摘要（若无须提供建议则留空）", 
  "speeches": ["话术1", "话术2", "话术3"]
}"""

# 触发类型的中文描述
TRIGGER_DESCRIPTIONS = {
    "negative_streak": "对方连续发送了多条消极/负面情绪的消息",
    "emotion_shift": "对方情绪发生了突变，从正面转为负面",
    "perfunctory": "对方连续发送了多条很短的敷衍回复（如'嗯''哦''好'）",
    "silence": "对方已经很长时间没有回复消息了",
    "positive_window": "对方连续发送了多条积极正面的消息，氛围很好",
    "topic_cooling": "对话频率明显下降，话题正在变冷",
}

# 走向的中文描述
INTENT_DESCRIPTIONS = {
    "intimate": "拉近关系、增进亲密度",
    "maintain": "维持现有关系、保持舒适距离",
    "distance": "礼貌疏远、减少互动",
}


logger = logging.getLogger(__name__)
def _print(msg: str):
    """统一打印"""
    logger.debug(msg)


RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_API_RETRIES = 3
BASE_RETRY_DELAY = 1.5


class LLMSuggestionEngine(SuggestionEngine):
    """
    LLM 建议引擎

    通过 OpenAI 兼容 API 生成建议，支持：
    - 远程 API：DeepSeek / OpenAI / Claude（需配置 api_key）
    - 本地推理：Ollama / LM Studio（无需 api_key）

    """

    def __init__(self, timeout: int = 60):
        """
        Args:
            timeout: API 请求超时时间（秒）
        """
        self.timeout = timeout
        # model_id 可用模型缓存: {base_url: (timestamp, [model_ids])}
        self._models_cache: dict[str, tuple[float, list[str]]] = {}
        self._cache_ttl = 300  # 缓存 TTL 5 分钟

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

    def generate(
        self,
        trigger_type: str,
        intent: str,
        context: dict | None = None,
    ) -> SuggestionResult:
        """
        调用 LLM 生成建议

        Args:
            trigger_type: 触发类型
            intent: 发展走向
            context: 附加上下文（emotion_summary, recent_messages 等）

        Returns:
            SuggestionResult
        """
        context = context or {}

        _print(f"\n{'='*60}")
        _print(f"[LLM Engine] 开始生成建议 | 触发: {trigger_type} | 走向: {intent}")
        _print(f"{'='*60}")

        # 获取激活的模型配置
        model_config = self._get_active_model()
        if not model_config:
            _print("❌ [LLM Engine] 未配置激活模型！")
            raise ValueError("未配置激活模型！请在设置页添加并激活一个 LLM 模型")

        _print(f"[LLM Engine] 使用模型: {model_config.get('name')} ({model_config.get('model_id')})")
        _print(f"[LLM Engine] API URL: {model_config.get('api_base_url')}")

        # 构造 prompt
        user_prompt = self._build_prompt(trigger_type, intent, context)
        _print(f"[LLM Engine] 📤 发送 prompt ({len(user_prompt)} 字符):")
        _print(f"{'─'*50}")
        _print(user_prompt)
        _print(f"{'─'*50}")

        try:
            # 调用 API
            response_text = self._call_api(model_config, user_prompt)
            _print(f"[LLM Engine] 📥 收到响应 ({len(response_text)} 字符):")
            _print(f"[LLM Engine] 响应内容: {response_text[:300]}")

            # 解析响应
            result = self._parse_response(response_text, trigger_type, intent)
            if result:
                if result.summary == "[SILENT]":
                    _print(f"[LLM Engine] 😶 LLM 决定保持沉默，无建议也不需回复。")
                    return result

                _print(f"[LLM Engine] ✅ LLM 生成成功!")
                _print(f"[LLM Engine] 思考过程: {result.thought_process}")
                _print(f"[LLM Engine] 摘要: {result.summary}")
                _print(f"[LLM Engine] 话术: {result.speeches}")
                _print(f"{'='*60}\n")
                return result
            else:
                _print("❌ [LLM Engine] 响应解析失败")
                raise ValueError("大模型响应解析失败，请重试或更换模型")

        except urllib.error.URLError as e:
            _print(f"❌ [LLM Engine] 网络错误: {e}")
            raise ConnectionError(f"大模型网络连接失败: {e}")
        except TimeoutError:
            _print(f"❌ [LLM Engine] 请求超时({self.timeout}s)")
            raise TimeoutError(f"大模型请求超时 ({self.timeout}s)")
        except Exception as e:
            _print(f"❌ [LLM Engine] 错误: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def _get_active_model(self) -> Optional[dict]:
        """从数据库获取当前激活的 LLM 模型配置"""
        try:
            from ...db.connection import get_db
            conn = get_db()

            # 确保表存在
            conn.execute('''
                CREATE TABLE IF NOT EXISTS llm_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    api_base_url TEXT NOT NULL,
                    api_key TEXT,
                    is_active INTEGER DEFAULT 0,
                    max_tokens INTEGER DEFAULT 512,
                    temperature REAL DEFAULT 0.7,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            ''')

            cursor = conn.execute(
                'SELECT * FROM llm_models WHERE is_active = 1 LIMIT 1'
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except Exception as e:
            _print(f"[LLM Engine] 获取模型配置失败: {e}")
            return None

    def _build_prompt(self, trigger_type: str, intent: str, context: dict) -> str:
        """构造用户 prompt"""
        parts = []

        # 触发原因
        trigger_desc = TRIGGER_DESCRIPTIONS.get(
            trigger_type, f"检测到触发条件: {trigger_type}"
        )
        parts.append(f"【触发原因】{trigger_desc}")

        # 走向目标
        intent_desc = INTENT_DESCRIPTIONS.get(intent, intent)
        parts.append(f"【用户目标】{intent_desc}")

        # 联系人画像（如有）
        profile = context.get("contact_profile")
        if profile:
            parts.append("\n【对方画像（分析对方心态时参考）】")
            tags = profile.get("personality_tags", [])
            if tags:
                parts.append(f"  性格标签: {', '.join(tags)}")
            style = profile.get("chat_style", "")
            if style:
                parts.append(f"  聊天风格: {style}")
            interests = profile.get("interests", [])
            if interests:
                parts.append(f"  兴趣话题: {', '.join(interests)}")
            tips = profile.get("communication_tips", "")
            if tips:
                parts.append(f"  沟通注意: {tips}")
            note = profile.get("relationship_note", "")
            if note:
                parts.append(f"  关系状态: {note}")

        # 用户本体专属克隆画像
        self_profile = context.get("self_profile")
        if self_profile:
            parts.append("\n【用户本体克隆画像（绝对强制按照此风格生成话术！）】")
            typing_style = self_profile.get("typing_style", "")
            if typing_style:
                parts.append(f"  打字排版风格: {typing_style}")
            catchphrases = self_profile.get("frequent_catchphrases", [])
            if catchphrases:
                parts.append(f"  高频语气词汇: {', '.join(catchphrases)}")
            patterns = self_profile.get("sentence_patterns", [])
            if patterns:
                parts.append(f"  常用句式模板（优先仿照这些结构写话术）: {' / '.join(patterns)}")
            attitude = self_profile.get("attitude_and_role", "")
            if attitude:
                parts.append(f"  本关系里的态度与角色: {attitude}")
            shared_mem = self_profile.get("shared_memories", [])
            if shared_mem:
                parts.append(f"  与对方共有的记忆常识(注意谁做了什么，优先使用近期事件): {', '.join(shared_mem)}")
            donts = self_profile.get("do_and_donts", "")
            if donts:
                parts.append(f"  模仿禁忌: {donts}")

        historical_ctx = context.get("historical_context", {})
        if historical_ctx:
            profile_ctx = historical_ctx.get("profile")
            if profile_ctx:
                parts.append("\n【历史联系人画像（辅助理解长期关系）】")
                if profile_ctx.get("chat_style"):
                    parts.append(f"  沟通风格: {profile_ctx.get('chat_style')}")
                tags = profile_ctx.get("personality_tags", [])
                if tags:
                    parts.append(f"  性格标签: {', '.join(tags)}")
                interests = profile_ctx.get("interests", [])
                if interests:
                    parts.append(f"  兴趣偏好: {', '.join(interests)}")
                if profile_ctx.get("communication_tips"):
                    parts.append(f"  沟通提示: {profile_ctx.get('communication_tips')}")

            emotion_ctx = historical_ctx.get("emotion_summary")
            if emotion_ctx:
                parts.append("\n【历史情绪摘要（对方近况）】")
                parts.append(f"  趋势: {emotion_ctx.get('trend', 'unknown')}")
                parts.append(f"  平均极性: {emotion_ctx.get('avg_polarity', 'N/A')}")
                parts.append(f"  平均强度: {emotion_ctx.get('avg_intensity', 'N/A')}")

            chart_stats = historical_ctx.get("chart_stats")
            if chart_stats:
                parts.append("\n【会话统计特征】")
                parts.append(f"  对方回复率: {chart_stats.get('reply_rate', 'N/A')}")
                parts.append(f"  对方积极率: {chart_stats.get('positive_rate', 'N/A')}")
                parts.append(f"  消息比（我:对方）: {chart_stats.get('msg_ratio', 'N/A')}")
                parts.append(f"  平均回复时长: {chart_stats.get('avg_reply_gap', 'N/A')} 秒")

        # 情绪摘要
        emotion = context.get("emotion_summary")
        if emotion:
            trend_map = {"positive": "正面", "negative": "负面", "neutral": "中性"}
            trend = trend_map.get(emotion.get("trend", ""), "未知")
            parts.append(
                f"【情绪走势】趋势={trend}, "
                f"平均极性={emotion.get('avg_polarity', 0):.2f}, "
                f"窗口消息数={emotion.get('window_size', 0)}"
            )
            polarities = emotion.get("recent_polarities", [])
            if polarities:
                polarity_str = " → ".join(
                    "正" if p > 0 else "负" if p < 0 else "中"
                    for p in polarities
                )
                parts.append(f"【极性序列】{polarity_str}")

        # 触发上下文
        trigger_ctx = context.get("trigger_context", {})
        if trigger_ctx:
            ctx_items = []
            for k, v in trigger_ctx.items():
                ctx_items.append(f"{k}={v}")
            if ctx_items:
                parts.append(f"【触发详情】{', '.join(ctx_items)}")

        # 用户自定义需求/上下文（悬浮模式下用户输入的想法和反馈）
        user_context = context.get("user_context")
        if user_context:
            if isinstance(user_context, list):
                # 对话历史格式: [{role: 'user', content: '...'}, ...]
                parts.append("【用户需求与反馈】")
                for msg in user_context[-6:]:  # 最多取最近 6 轮
                    role_label = "用户" if msg.get("role") == "user" else "AI"
                    parts.append(f"  {role_label}：{msg.get('content', '')[:200]}")
            elif isinstance(user_context, str):
                parts.append(f"【用户需求】{user_context[:500]}")

        # 历史聊天分析摘要（如请求包含历史数据）
        if context.get("include_history"):
            history_summary = context.get("history_summary")
            if history_summary:
                parts.append(f"【历史关系分析】{history_summary[:500]}")

        # 最近对话 (考虑传入的 window_size 控制的情绪窗口内最近聊天)
        recent = context.get("recent_messages", [])
        if recent:
            parts.append("【最近对话】")
            # 窗口大小默认为 8，如果有 emotion summary 的 window size，可采用，但不完全限制
            window_size = 5 # 根据用户要求修改为 5 条作为窗口基础
            if emotion and emotion.get('window_size'):
                window_size = int(emotion.get('window_size', 5))
            
            # 但最多还是取最近 8~10 条，避免 prompt 太长，这里先限制最多8条，如果要求5条也可以这里调整。
            for msg in recent[-8:]:  
                sender = "我" if msg.get("sender_attr") == "self" else "对方"
                content = msg.get("content", "")[:100]
                parts.append(f"  {sender}：{content}")

        # 用户调教规则（最高优先级）
        display_name = context.get("display_name")
        if display_name:
            try:
                from .feedback_rule_extractor import FeedbackRuleExtractor
                rules = FeedbackRuleExtractor().get_active_rules(display_name)
                if rules:
                    parts.append("\n【用户调教规则（绝对最高戒律！每一条都必须严格遵守）】")
                    for i, rule in enumerate(rules, 1):
                        parts.append(f"  规则{i}: {rule}")
            except Exception as e:
                _print(f"[LLM Engine] 加载调教规则失败: {e}")

        # 被唤醒的长期记忆（RAG）
        relevant_memories = context.get("relevant_memories", [])
        if relevant_memories:
            parts.append("\n【被唤醒的历史记忆（你们过去聊过的相关事件）】")
            for mem in relevant_memories[:3]:
                summary = mem.get('summary', '')
                # 计算时间距离
                import time as _time
                created = mem.get('created_at', 0)
                age_hours = int((_time.time() - created) / 3600) if created else 0
                if age_hours < 24:
                    time_label = f"{age_hours}小时前"
                else:
                    time_label = f"{age_hours // 24}天前"
                parts.append(f"  {time_label}: {summary}")

        parts.append("\n请根据以上信息生成思考过程和沟通建议（纯 JSON 输出）：")

        return "\n".join(parts)

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

    def _call_api(self, model_config: dict, user_prompt: str) -> str:
        """调用 OpenAI 兼容 API"""
        base_url = model_config["api_base_url"].rstrip("/")
        api_key = model_config.get("api_key", "")
        model_id = model_config["model_id"]
        max_tokens = model_config.get("max_tokens", 512)
        temperature = model_config.get("temperature", 0.7)

        # Bug 2: 动态校验并修正 model_id
        model_id = self._validate_model_id(model_id, base_url, api_key)

        url = f"{base_url}/chat/completions"

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        data = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        _print(f"[LLM Engine] 📤 POST {url}")
        _print(f"[LLM Engine] 📤 model={model_id}, temp={temperature}, max_tokens={max_tokens}")

        body = None
        for attempt in range(MAX_API_RETRIES + 1):
            start_time = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status_code = resp.status
                    body = json.loads(resp.read().decode("utf-8"))
                elapsed = time.time() - start_time
                _print(f"[LLM Engine] 📥 HTTP {status_code} ({elapsed:.2f}s)")
                break
            except urllib.error.HTTPError as e:
                status_code = getattr(e, "code", None)
                if status_code in RETRYABLE_HTTP_STATUS and attempt < MAX_API_RETRIES:
                    delay = self._compute_retry_delay(attempt, e.headers.get("Retry-After"))
                    _print(f"[LLM Engine] Retry on HTTP {status_code} after {delay:.1f}s (attempt {attempt + 1})")
                    time.sleep(delay)
                    continue
                raise
            except Exception as e:
                if self._is_timeout_error(e) and attempt < MAX_API_RETRIES:
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

        content = choices[0].get("message", {}).get("content", "")
        usage = body.get("usage", {})
        _print(
            f"[LLM Engine] 📥 tokens: prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')}, "
            f"total={usage.get('total_tokens', '?')}"
        )

        return content.strip()

    def _parse_response(
        self, text: str, trigger_type: str, intent: str
    ) -> Optional[SuggestionResult]:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试提取 JSON 块（LLM 有时会包裹在 ```json ... ``` 中）
            cleaned = text
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1]
                cleaned = cleaned.split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1]
                cleaned = cleaned.split("```", 1)[0]

            data = json.loads(cleaned.strip())

            thought_process = data.get("thought_process", "").strip()
            summary = data.get("summary", "").strip()
            speeches = data.get("speeches", [])
            reply = data.get("reply", "").strip()

            if not summary and not reply:
                # 允许模型保持沉默（既没建议也不回复用户）
                summary = "[SILENT]"

            # 若 summary 为空，给一个默认标记防止报错，前端可根据此标记隐藏卡片
            if not summary and reply:
                summary = "[PURE_CHAT]"

            # 确保 speeches 是合法的列表
            if isinstance(speeches, str):
                # 如果大模型返回的是纯字符串，包裹一层
                speeches = [speeches]
            elif not isinstance(speeches, list):
                speeches = []

            # 确保 speeches 是字符串列表
            speeches = [str(s).strip() for s in speeches if s]

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
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            _print(f"[LLM Engine] JSON 解析失败: {e}, 原始文本: {text[:200]}")
            return None

    def generate_quick_prompts(self, context: dict | None = None) -> list[str]:
        """
        根据当前聊天上下文生成 4 个动态快捷回复联想词（简短的、以行动为导向的短语）。
        
        Args:
            context: 附加上下文（包含 recent_messages 等）
            
        Returns:
            list[str]: 4个联想词组成的数组，如果失败则返回默认列表。
        """
        default_prompts = ['拉近距离', '化解尴尬', '延续话题', '表达关心']
        context = context or {}

        _print(f"\n{'='*60}")
        _print(f"[LLM Engine] 开始生成动态联想词")
        _print(f"{'='*60}")

        model_config = self._get_active_model()
        if not model_config:
            _print("❌ [LLM Engine] 未配置激活模型！")
            raise ValueError("未配置激活模型")

        prompt = "你是一个高情商聊天助手。请阅读以下双方的最新聊天记录，推测用户（‘我’）下一步最可能想发起的话题方向或对话策略。\n"
        prompt += "要求：给出 4 个选项；每个选项必须是简短的动宾短语（限 4 个字内，如‘顺着话题’、‘转移话题’、‘约她吃饭’、‘表达心疼’）；只返回一个 JSON 格式的字符串数组，不要其他废话。\n\n"

        recent = context.get("recent_messages", [])
        if recent:
            prompt += "【最近对话】\n"
            for msg in recent[-8:]:  # 最多取最近 8 条
                sender = "我" if msg.get("sender_attr") == "self" else "对方"
                content = msg.get("content", "")[:100]
                prompt += f"{sender}：{content}\n"
        else:
            prompt += "【最近对话】暂无。\n"

        _print(f"[LLM Engine] 📤 联想词 prompt ({len(prompt)} 字符):")
        _print(prompt)

        try:
            response_text = self._call_api(model_config, prompt)
            _print(f"[LLM Engine] 📥 收到联想词响应: {response_text}")

            # 解析 JSON 数组
            cleaned = response_text
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1]
                cleaned = cleaned.split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1]
                cleaned = cleaned.split("```", 1)[0]

            cleaned = cleaned.strip()
            if not cleaned:
                _print("[LLM Engine] 联想词响应为空，回退默认词")
                return default_prompts

            try:
                prompts = json.loads(cleaned)
            except json.JSONDecodeError:
                # 某些模型会在数组前后夹带说明文字，这里尽量截取数组主体。
                array_start = cleaned.find("[")
                array_end = cleaned.rfind("]")
                if array_start == -1 or array_end == -1 or array_end < array_start:
                    _print("[LLM Engine] 联想词响应不是合法 JSON 数组，回退默认词")
                    return default_prompts
                prompts = json.loads(cleaned[array_start:array_end + 1])
            
            if isinstance(prompts, list) and len(prompts) > 0:
                # 过滤掉非字符串，限制长度，并只取前 4 个
                valid_prompts = [str(p).strip()[:8] for p in prompts if isinstance(p, str) and str(p).strip()]
                if len(valid_prompts) >= 4:
                    return valid_prompts[:4]
                elif len(valid_prompts) > 0:
                    # 数量不足时用默认词补充
                    return (valid_prompts + default_prompts)[:4]
            
            _print("❌ [LLM Engine] 联想词解析出来的不是有效数组或为空。")
            raise ValueError("大模型响应解析失败，未能生成有效联想词")

        except Exception as e:
            _print(f"❌ [LLM Engine] 生成联想词时出错: {e}")
            return default_prompts
