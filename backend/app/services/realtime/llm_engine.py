"""
LLM 建议引擎

基于 OpenAI 兼容格式的 LLM 建议引擎，
支持远程 API（DeepSeek/OpenAI）和本地推理（Ollama/LM Studio）。
超时或异常时自动降级到模板引擎。
"""

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Optional

from .suggestion_engine import SuggestionEngine, SuggestionResult


# Prompt 系统模板
SYSTEM_PROMPT = """你是一个专业的聊天沟通顾问。你的任务是根据当前的对话情绪状态，为用户提供具体的沟通建议和话术。

规则：
1. 建议必须贴合当前情境，不要空泛
2. 话术要自然、口语化，像真实聊天一样
3. 严格按 JSON 格式输出，不要输出其他内容
4. 话术数量 2-3 条

输出格式（纯 JSON，无 markdown）：
{"summary": "一句话建议摘要", "speeches": ["话术1", "话术2", "话术3"]}"""

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


class LLMSuggestionEngine(SuggestionEngine):
    """
    LLM 建议引擎

    通过 OpenAI 兼容 API 生成建议，支持：
    - 远程 API：DeepSeek / OpenAI / Claude（需配置 api_key）
    - 本地推理：Ollama / LM Studio（无需 api_key）

    失败时自动降级到模板引擎。
    """

    def __init__(self, timeout: int = 15):
        """
        Args:
            timeout: API 请求超时时间（秒）
        """
        self.timeout = timeout

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
            _print("❌ [LLM Engine] 未配置激活模型！请在设置页添加并激活一个 LLM 模型")
            _print("❌ [LLM Engine] 降级使用模板引擎")
            return self._fallback(trigger_type, intent, context)

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
                _print(f"[LLM Engine] ✅ LLM 生成成功!")
                _print(f"[LLM Engine] 摘要: {result.summary}")
                _print(f"[LLM Engine] 话术: {result.speeches}")
                _print(f"{'='*60}\n")
                return result
            else:
                _print("❌ [LLM Engine] 响应解析失败 → 降级模板引擎")
                return self._fallback(trigger_type, intent, context)

        except urllib.error.URLError as e:
            _print(f"❌ [LLM Engine] 网络错误: {e} → 降级模板引擎")
            return self._fallback(trigger_type, intent, context)
        except TimeoutError:
            _print(f"❌ [LLM Engine] 请求超时({self.timeout}s) → 降级模板引擎")
            return self._fallback(trigger_type, intent, context)
        except Exception as e:
            _print(f"❌ [LLM Engine] 错误: {e} → 降级模板引擎")
            import traceback
            traceback.print_exc()
            return self._fallback(trigger_type, intent, context)

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
            parts.append("【联系人画像】")
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

        # 最近对话
        recent = context.get("recent_messages", [])
        if recent:
            parts.append("【最近对话】")
            for msg in recent[-8:]:  # 最多取最近 8 条
                sender = "我" if msg.get("sender_attr") == "self" else "对方"
                content = msg.get("content", "")[:100]
                parts.append(f"  {sender}：{content}")

        parts.append("\n请根据以上信息生成沟通建议（纯 JSON 输出）：")

        return "\n".join(parts)

    def _call_api(self, model_config: dict, user_prompt: str) -> str:
        """调用 OpenAI 兼容 API"""
        base_url = model_config["api_base_url"].rstrip("/")
        api_key = model_config.get("api_key", "")
        model_id = model_config["model_id"]
        max_tokens = model_config.get("max_tokens", 512)
        temperature = model_config.get("temperature", 0.7)

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

        start_time = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            status_code = resp.status
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - start_time

        _print(f"[LLM Engine] 📥 HTTP {status_code} ({elapsed:.2f}s)")

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

            summary = data.get("summary", "").strip()
            speeches = data.get("speeches", [])

            if not summary:
                return None

            # 确保 speeches 是字符串列表
            speeches = [str(s).strip() for s in speeches if s]

            return SuggestionResult(
                trigger_type=trigger_type,
                intent=intent,
                summary=summary,
                speeches=speeches,
                severity="medium",
                confidence=0.9,
            )
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            _print(f"[LLM Engine] JSON 解析失败: {e}, 原始文本: {text[:200]}")
            return None

    def _fallback(
        self, trigger_type: str, intent: str, context: dict | None = None
    ) -> SuggestionResult:
        """降级到模板引擎"""
        from .template_engine import TemplateSuggestionEngine
        return TemplateSuggestionEngine().generate(trigger_type, intent, context)
