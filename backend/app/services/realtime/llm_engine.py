"""
LLM 建议引擎

基于 OpenAI 兼容格式的 LLM 建议引擎，
支持远程 API（DeepSeek/OpenAI）和本地推理（Ollama/LM Studio）。
超时或异常时自动降级到模板引擎。
"""

import json
import logging
import random
import re
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
5. **【时效优先】核心注意力规则**：
   - 你的注意力必须优先集中在【最近对话】中，先理解眼前正在发生什么
   - 【被唤醒的历史记忆】只有在对方最近消息里明确提到相关话题时才能使用
   - 禁止主动翻出历史记忆作为建议主轴，除非对方刚刚提起
   - 如果历史记忆与当前对话无关，直接忽略它
   - 规则、画像和长期偏好只能约束“怎么说”，不能决定“聊什么”
   - 如果规则/画像与【最近对话】冲突，必须以【最近对话】和当前触发为准
   - 如果触发是 emotion_shift，只能围绕对方最新那条偏负面的表达做轻量关心或顺势接话，禁止脑补重大心事或过度安慰
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

ANALYSIS_SYSTEM_PROMPT = """你是用户的聊天思考助手。请先只做分析，不要输出 JSON。

要求：
1. 只分析眼前这段聊天上下文现在该聊什么、为什么这么聊。
2. 可以参考用户风格和对方画像，但不要复述整段 prompt。
3. 不要输出规则标题，不要输出“reply/summary/speeches/thought_process”这类字段名。
4. 最后单独给出 1 到 3 条“可直接发送的话术草稿”，每条单独成行，以 `- ` 开头。
5. 除了分析和草稿，不要输出别的格式说明。"""

REPAIR_SYSTEM_PROMPT = """你是一个结果整理器。你会收到：
1. 当前聊天建议任务的上下文
2. 一次失败的历史说明（可选）

你的任务不是继续分析规则，而是直接重新给出最终结果。

要求：
1. 只输出纯 JSON，不要输出解释、前言、Markdown。
2. `speeches` 必须是用户可以直接发送给对方的原句，不能是规则、分析、Prompt 片段、字段说明。
3. 如果没有足够可靠的话术，就返回空 `speeches`，不要编造 prompt 规则。
4. `thought_process` 只保留一两句简短总结，不要复述长篇思维链。
5. 不要续写坏掉的 JSON，不要分析“你收到什么任务”，只给最终结果。

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

# 触发类型的中文描述
TRIGGER_DESCRIPTIONS = {
    "negative_streak": "对方连续发送了多条消极/负面情绪的消息",
    "emotion_shift": "对方近期情绪明显下坠，且最新表达偏负面",
    "perfunctory": "对方连续发送了多条很短的敷衍回复（如'嗯''哦''好'）",
    "silence": "对方已经很长时间没有回复消息了",
    "positive_window": "对方连续发送了多条积极正面的消息，氛围很好",
    "topic_cooling": "对话频率明显下降，话题正在变冷",
    "manual_request": "用户主动请求建议，需要基于当前上下文给出回复思路",
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
    RECENT_MESSAGE_LIMIT = 20
    RECENT_CHAR_GUARD = 300
    MSG_COMPRESS_THRESHOLD = 20
    MSG_SUMMARY_MAX_CHARS = 300
    MEMORY_LOOKBACK_MESSAGES = 5
    MEMORY_MAX_ITEMS = 3
    STYLE_RULE_KEYWORDS = (
        "短句",
        "长句",
        "连发",
        "图片",
        "表情",
        "语气",
        "语气词",
        "口语",
        "简短",
        "具体事实",
        "数字",
        "肯定",
        "自嘲",
        "措辞",
        "直接分享事实",
        "简短肯定",
        "抱怨",
        "吐槽",
        "文字",
    )
    CONTENT_RULE_KEYWORDS = (
        "转移话题",
        "开启新话题",
        "延续当前话题",
        "终止对话",
        "学习内容",
        "学业",
        "工作",
        "高数",
        "游戏",
        "回忆分享",
        "现实话题",
        "留学",
        "考研",
        "就业",
        "兼职",
        "生活费",
        "专业",
        "聊到",
        "话题",
    )
    JSON_MODE_PROVIDERS = {"openai", "deepseek"}
    PLACEHOLDER_SUMMARIES = {"...", "…", "一句话建议摘要（若无须提供建议则留空）"}
    META_SPEECH_KEYWORDS = (
        "AI",
        "用户",
        "对方",
        "规则",
        "模仿",
        "画像",
        "输出",
        "JSON",
        "reply",
        "summary",
        "thought_process",
        "speeches",
        "身份区分",
        "千人千面",
        "完美模仿",
        "克隆规则",
        "聊天对象",
        "当前上下文",
        "关系状态",
        "触发",
        "模式",
        "Prompt",
        "prompt",
        "字段",
        "性格标签",
        "聊天风格",
        "沟通注意",
        "关系状态",
        "打字排版风格",
        "高频语气词汇",
        "常用句式模板",
        "模仿禁忌",
    )

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

    def _is_reasoning_model(self, model_id: str) -> bool:
        normalized = (model_id or "").lower()
        return "reasoner" in normalized or "deepseek-r1" in normalized

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
            if self._is_reasoning_model(model_config.get("model_id", "")):
                analysis_text = self._generate_reasoning_analysis(model_config, user_prompt)
                _print(f"[LLM Engine] 🧠 分析阶段输出 ({len(analysis_text)} 字符): {analysis_text[:300]}")
                response_text = self._format_reasoning_result(model_config, user_prompt, analysis_text)
                _print(f"[LLM Engine] 📥 格式化阶段输出 ({len(response_text)} 字符): {response_text[:300]}")
                result = self._parse_response(response_text, trigger_type, intent)
                if not result:
                    repaired_text = self._repair_response(model_config, user_prompt, analysis_text)
                    if repaired_text:
                        _print(f"[LLM Engine] 🩹 修复后响应: {repaired_text[:300]}")
                        result = self._parse_response(repaired_text, trigger_type, intent)
                if result and analysis_text:
                    result.thought_process = analysis_text[:2000]
            else:
                # 调用 API
                response_text = self._call_api(model_config, user_prompt)
                _print(f"[LLM Engine] 📥 收到响应 ({len(response_text)} 字符):")
                _print(f"[LLM Engine] 响应内容: {response_text[:300]}")

                # 解析响应
                result = self._parse_response(response_text, trigger_type, intent)
                if not result:
                    repaired_text = self._repair_response(model_config, user_prompt, response_text)
                    if repaired_text:
                        _print(f"[LLM Engine] 🩹 修复后响应: {repaired_text[:300]}")
                        result = self._parse_response(repaired_text, trigger_type, intent)
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

    def _select_recent_messages(self, messages: list[dict]) -> tuple[list[dict], list[dict]]:
        """条数优先保留最近对话，字符数只作为兜底保护。"""
        messages = self._normalize_recent_messages(messages)
        if not messages:
            return [], []

        kept_reversed: list[dict] = []
        total_chars = 0

        for msg in reversed(messages):
            if len(kept_reversed) >= self.RECENT_MESSAGE_LIMIT:
                break

            content = str(msg.get("content", ""))
            if kept_reversed and total_chars + len(content) > self.RECENT_CHAR_GUARD:
                break

            kept_reversed.append(msg)
            total_chars += len(content)

        kept = list(reversed(kept_reversed))
        older = messages[:-len(kept)] if kept else messages
        return older, kept

    def _normalize_recent_messages(self, messages: list[dict]) -> list[dict]:
        """将最近消息统一归一化为时间正序，避免上游倒序查询导致截错窗口。"""
        if not messages:
            return []

        def _sort_key(item: dict) -> tuple[int, int]:
            timestamp = item.get("timestamp")
            message_id = item.get("id")
            try:
                safe_ts = int(timestamp)
            except (TypeError, ValueError):
                safe_ts = 0
            try:
                safe_id = int(message_id)
            except (TypeError, ValueError):
                safe_id = 0
            return safe_ts, safe_id

        ordered = sorted(messages, key=_sort_key)
        if ordered and messages and ordered[0] is not messages[0]:
            _print("[LLM Engine] ↕️ recent_messages 已按时间正序归一化")
        return ordered

    def _compress_messages(
        self, messages: list[dict], kept_messages: list[dict]
    ) -> str:
        """将最近窗口外的较早消息折叠为简短摘要。"""
        if len(messages) <= self.MSG_COMPRESS_THRESHOLD:
            return ""

        older_count = max(len(messages) - len(kept_messages), 0)
        if older_count <= 0:
            return ""

        older = messages[:older_count]
        self_count = sum(1 for m in older if m.get("sender_attr") == "self")
        other_count = older_count - self_count
        other_snippets = [
            str(m.get("content", "")).strip()[:30]
            for m in older[-5:]
            if m.get("sender_attr") != "self" and str(m.get("content", "")).strip()
        ]
        snippet_text = "；".join(other_snippets) if other_snippets else "内容略"
        summary = (
            f"（更早的 {older_count} 条消息已折叠：我发了 {self_count} 条，"
            f"对方发了 {other_count} 条，对方当时提到：{snippet_text}）"
        )
        return summary[: self.MSG_SUMMARY_MAX_CHARS]

    def _extract_memory_keywords(self, summary: str) -> list[str]:
        """从记忆摘要中提取简单关键词。"""
        tokens = re.split(r"[\s,，。！？；：、/()（）\[\]\-]+", summary)
        keywords = [token.strip() for token in tokens if len(token.strip()) >= 2]
        compact = re.sub(r"[\s,，。！？；：、/()（）\[\]\-]+", "", summary)
        if len(compact) >= 2:
            max_size = min(6, len(compact))
            for size in range(2, max_size + 1):
                for index in range(0, len(compact) - size + 1):
                    keywords.append(compact[index:index + size])
        deduped = list(dict.fromkeys(keywords))
        return deduped[:12]

    def _should_inject_memories(
        self, recent_messages: list[dict], memories: list[dict]
    ) -> list[dict]:
        """仅在对方最近消息主动提及相关话题时注入记忆。"""
        if not recent_messages or not memories:
            return []

        other_msgs = [
            str(msg.get("content", "")).strip()
            for msg in recent_messages[-self.MEMORY_LOOKBACK_MESSAGES:]
            if msg.get("sender_attr") != "self" and str(msg.get("content", "")).strip()
        ]
        if not other_msgs:
            return []

        combined_text = " ".join(other_msgs)
        matched = []
        for mem in memories:
            summary = str(mem.get("summary", "")).strip()
            if not summary:
                continue
            keywords = self._extract_memory_keywords(summary)
            if keywords and any(keyword in combined_text for keyword in keywords):
                matched.append(mem)
            if len(matched) >= self.MEMORY_MAX_ITEMS:
                break
        return matched

    def _is_style_rule(self, rule: str) -> bool:
        """仅保留措辞/表达习惯类规则，过滤掉内容和策略类规则。"""
        normalized = str(rule).strip()
        if not normalized:
            return False
        if any(keyword in normalized for keyword in self.CONTENT_RULE_KEYWORDS):
            return False
        return any(keyword in normalized for keyword in self.STYLE_RULE_KEYWORDS)

    def _filter_style_rules(self, rules: list[str]) -> list[str]:
        """运行时过滤规则，只把表达风格类规则传给 LLM。"""
        filtered = [rule for rule in rules if self._is_style_rule(rule)]
        if rules and not filtered:
            _print("[LLM Engine] 🎛️ 已过滤掉内容/策略类规则，仅保留最近对话决定选题")
        elif len(filtered) < len(rules):
            _print(
                f"[LLM Engine] 🎛️ 规则已收敛为表达风格参考: {len(filtered)}/{len(rules)}"
            )
        return filtered

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

        recent = self._normalize_recent_messages(context.get("recent_messages", []))
        _older_messages, recent_window = self._select_recent_messages(recent)
        compressed_summary = self._compress_messages(recent, recent_window)
        if recent_window:
            parts.append("\n【最近对话】")
            if compressed_summary:
                parts.append(f"  {compressed_summary}")
            for msg in recent_window:
                sender = "我" if msg.get("sender_attr") == "self" else "对方"
                content = str(msg.get("content", ""))[:200]
                parts.append(f"  {sender}：{content}")

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

        # 联系人画像（如有）
        profile = context.get("contact_profile")
        if profile:
            parts.append("\n【对方画像（低权重参考）】")
            tags = profile.get("personality_tags", [])
            if tags:
                parts.append(f"  性格标签: {', '.join(tags)}")
            style = profile.get("chat_style", "")
            if style:
                parts.append(f"  聊天风格: {style}")
            tips = profile.get("communication_tips", "")
            if tips:
                parts.append(f"  沟通注意: {tips}")
            note = profile.get("relationship_note", "")
            if note:
                parts.append(f"  关系状态: {note}")

        # 用户本体专属克隆画像
        self_profile = context.get("self_profile")
        if self_profile:
            parts.append("\n【用户本体语言风格参考（仅影响措辞）】")
            typing_style = self_profile.get("typing_style", "")
            if typing_style:
                parts.append(f"  打字排版风格: {typing_style}")
            catchphrases = self_profile.get("frequent_catchphrases", [])
            if catchphrases:
                parts.append(f"  高频语气词汇: {', '.join(catchphrases)}")
            patterns = self_profile.get("sentence_patterns", [])
            if patterns:
                parts.append(f"  常用句式模板（优先仿照这些结构写话术）: {' / '.join(patterns)}")
            donts = self_profile.get("do_and_donts", "")
            if donts:
                parts.append(f"  模仿禁忌: {donts}")

        relevant_memories = self._should_inject_memories(
            recent_window or recent,
            context.get("relevant_memories", []),
        )
        if relevant_memories:
            parts.append("\n【被唤醒的历史记忆（仅作辅助，不要盖过当前对话）】")
            for mem in relevant_memories:
                summary = str(mem.get("summary", "")).strip()
                created = mem.get("created_at", 0)
                age_hours = int((time.time() - created) / 3600) if created else 0
                time_label = f"{age_hours}小时前" if age_hours < 24 else f"{age_hours // 24}天前"
                parts.append(f"  {time_label}: {summary}")

        historical_ctx = context.get("historical_context", {})
        history_lines = []
        if historical_ctx:
            profile_ctx = historical_ctx.get("profile") or {}
            profile_bits = []
            if profile_ctx.get("chat_style"):
                profile_bits.append(f"历史沟通风格={profile_ctx.get('chat_style')}")
            if profile_ctx.get("communication_tips"):
                profile_bits.append(f"历史沟通提示={profile_ctx.get('communication_tips')}")
            if profile_ctx.get("personality_tags"):
                profile_bits.append(
                    f"历史性格标签={', '.join(profile_ctx.get('personality_tags', []))}"
                )
            if profile_bits:
                history_lines.append("；".join(profile_bits))

            emotion_ctx = historical_ctx.get("emotion_summary") or {}
            chart_stats = historical_ctx.get("chart_stats") or {}
            summary_bits = []
            if emotion_ctx:
                summary_bits.append(f"趋势={emotion_ctx.get('trend', 'unknown')}")
                summary_bits.append(f"平均极性={emotion_ctx.get('avg_polarity', 'N/A')}")
                summary_bits.append(f"平均强度={emotion_ctx.get('avg_intensity', 'N/A')}")
            if chart_stats:
                summary_bits.append(f"对方回复率={chart_stats.get('reply_rate', 'N/A')}")
                summary_bits.append(f"对方积极率={chart_stats.get('positive_rate', 'N/A')}")
                summary_bits.append(f"消息比={chart_stats.get('msg_ratio', 'N/A')}")
                summary_bits.append(f"平均回复时长={chart_stats.get('avg_reply_gap', 'N/A')} 秒")
            if summary_bits:
                history_lines.append("；".join(summary_bits))
        if history_lines:
            parts.append("\n【历史上下文补充（低权重）】")
            for line in history_lines:
                parts.append(f"  {line}")

        # 用户调教规则（最高优先级）
        display_name = context.get("display_name")
        if display_name:
            try:
                from .feedback_rule_extractor import FeedbackRuleExtractor
                rules = self._filter_style_rules(
                    FeedbackRuleExtractor().get_active_rules(display_name)
                )
                if rules:
                    parts.append("\n【表达偏好参考（仅影响措辞，不决定话题）】")
                    for i, rule in enumerate(rules, 1):
                        parts.append(f"  规则{i}: {rule}")
            except Exception as e:
                _print(f"[LLM Engine] 加载调教规则失败: {e}")

        if trigger_type == "manual_request":
            parts.append(
                "\n【手动求助模式】用户是主动来问该怎么聊的。"
                "请直接基于当前上下文给出可发送的话术，"
                "并且必须严格只输出 JSON，不要输出解释、前言或额外文本。"
            )

        parts.append("\n请根据以上信息生成思考过程和沟通建议（纯 JSON 输出）：")
        prompt = "\n".join(parts)
        total_chars = len(prompt)
        _print(f"[LLM Engine] 📏 Prompt 总长度: {total_chars} 字符")
        if total_chars > 3000:
            _print("[LLM Engine] ⚠️ Prompt 较长，建议检查最近对话窗口和压缩逻辑")
        return prompt

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

        if request_tag == "analysis":
            return max(max_tokens, 1536)
        if request_tag == "repair":
            return max(max_tokens, 768)
        if request_tag == "suggestion":
            return max(max_tokens, 1024)
        if request_tag == "format":
            return max(max_tokens, 768)
        return max_tokens

    def _call_api_with_messages(
        self,
        model_config: dict,
        messages: list[dict],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        request_tag: str = "suggestion",
        use_json_mode: bool = True,
    ) -> str:
        """调用 OpenAI 兼容 API，并允许传入自定义消息。"""
        base_url = model_config["api_base_url"].rstrip("/")
        api_key = model_config.get("api_key", "")
        model_id = model_config["model_id"]
        max_tokens = model_config.get("max_tokens", 512) if max_tokens is None else max_tokens
        temperature = model_config.get("temperature", 0.7) if temperature is None else temperature

        # Bug 2: 动态校验并修正 model_id
        model_id = self._validate_model_id(model_id, base_url, api_key)
        max_tokens = self._boost_reasoning_max_tokens(model_id, int(max_tokens), request_tag)

        url = f"{base_url}/chat/completions"

        payload = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
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

        body = None
        for attempt in range(MAX_API_RETRIES + 1):
            start_time = time.time()
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
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

        message_obj = choices[0].get("message", {})
        content = self._extract_message_text(message_obj)
        usage = body.get("usage", {})
        _print(
            f"[LLM Engine] 📥 tokens: prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')}, "
            f"total={usage.get('total_tokens', '?')}"
        )

        return content.strip()

    def _call_api(self, model_config: dict, user_prompt: str) -> str:
        """调用 OpenAI 兼容 API"""
        return self._call_api_with_messages(
            model_config,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            request_tag="suggestion",
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

    def _extract_message_text(self, message_obj: dict) -> str:
        """兼容不同 OpenAI 兼容厂商返回的文本字段。"""
        content = message_obj.get("content", "") or ""
        reasoning = message_obj.get("reasoning_content", "") or ""

        if not content and reasoning:
            _print("[LLM Engine] ⚠️ message.content 为空，回退使用 reasoning_content")
            return reasoning

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

    def _clean_speech_candidate(self, line: str) -> str:
        """清洗 reasoning 文本里候选话术的前缀噪音。"""
        candidate = re.sub(r"^[-*•\s]+", "", line.strip())
        candidate = re.sub(r"^\d+[.)、．]\s*", "", candidate)
        candidate = re.sub(r"^话术(?:建议|例子|示例)?[:：]\s*", "", candidate)
        candidate = candidate.strip("`\"'“”‘’ ")
        if "：" in candidate and candidate.split("：", 1)[0] in {"话术1", "话术2", "话术3"}:
            candidate = candidate.split("：", 1)[1].strip()
        return candidate

    def _is_sendable_speech(self, text: str) -> bool:
        """判断一段文本是否像用户可以直接发送的话术，而不是规则说明。"""
        candidate = str(text or "").strip()
        if not candidate:
            return False
        if candidate.startswith(("**", "#", "【")):
            return False
        if len(candidate) > 48:
            return False
        if any(keyword in candidate for keyword in self.META_SPEECH_KEYWORDS):
            return False
        if re.fullmatch(r"话术\d+", candidate):
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

    def _extract_speeches_from_reasoning(self, text: str) -> list[str]:
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
                    if candidate and self._is_sendable_speech(candidate):
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
            if not self._is_sendable_speech(candidate):
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
                if not self._is_sendable_speech(candidate):
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
        self, text: str, trigger_type: str, intent: str
    ) -> Optional[SuggestionResult]:
        """当模型没有返回 JSON 时，尽量从 reasoning 自由文本中兜底提取结果。"""
        cleaned = (text or "").strip()
        if not cleaned:
            return None

        speeches = self._extract_speeches_from_reasoning(cleaned)
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
            f"{raw_response[:600] if raw_response.strip() else '（无）'}"
        )
        try:
            return self._call_api_with_messages(
                model_config,
                [
                    {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ],
                max_tokens=min(max(int(model_config.get("max_tokens", 512)), 256), 512),
                temperature=0.2,
                request_tag="repair",
            )
        except Exception as e:
            _print(f"[LLM Engine] 修复响应失败: {e}")
            return ""

    def _parse_response(
        self, text: str, trigger_type: str, intent: str
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
            valid_speeches = [speech for speech in speeches if self._is_sendable_speech(speech)]
            if speeches and not valid_speeches:
                raise ValueError("模型返回的 speeches 更像规则说明，不是可发送话术")
            speeches = valid_speeches

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
            fallback_result = self._parse_reasoning_fallback(text, trigger_type, intent)
            if fallback_result:
                _print("[LLM Engine] ⚠️ 检测到非 JSON reasoning 输出，已本地提取建议结果")
                return fallback_result
            preview = (text or "")[:2000]
            logger.error("[LLM Engine] JSON 解析失败: %s | 原始响应: %s", e, preview)
            _print(f"[LLM Engine] JSON 解析失败: {e}, 原始文本: {preview[:200]}")
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

        prompt = "请阅读以下双方的最新聊天记录，推测用户（‘我’）下一步最可能想发起的话题方向或对话策略。\n"
        prompt += "要求：给出 4 个选项；每个选项必须是简短的动宾短语（限 4 个字内，如‘顺着话题’、‘转移话题’、‘约她吃饭’、‘表达心疼’）；只返回一个 JSON 格式的字符串数组，不要其他废话。\n\n"

        recent = self._normalize_recent_messages(context.get("recent_messages", []))
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
            response_text = self._call_quick_prompts_api(model_config, prompt)
            _print(f"[LLM Engine] 📥 收到联想词响应: {response_text}")

            cleaned = self._extract_json_array_candidate(response_text).strip()
            if not cleaned:
                _print("[LLM Engine] 联想词响应为空，回退默认词")
                return default_prompts

            try:
                prompts = json.loads(cleaned)
            except json.JSONDecodeError:
                _print("[LLM Engine] 联想词响应不是合法 JSON 数组，回退默认词")
                return default_prompts

            if isinstance(prompts, list) and len(prompts) > 0:
                normalized_prompts = self._normalize_quick_prompt_items(prompts, default_prompts)
                if normalized_prompts:
                    return normalized_prompts
            
            _print("❌ [LLM Engine] 联想词解析出来的不是有效数组或为空。")
            raise ValueError("大模型响应解析失败，未能生成有效联想词")

        except Exception as e:
            _print(f"❌ [LLM Engine] 生成联想词时出错: {e}")
            return default_prompts
