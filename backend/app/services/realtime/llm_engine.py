"""
LLM 建议引擎

基于 OpenAI 兼容格式的 LLM 建议引擎，
支持远程 API（DeepSeek/OpenAI）和本地推理（Ollama/LM Studio）。
超时或异常时自动降级到模板引擎。
"""

import json
import logging
import re
import time
import urllib.request
import urllib.error
from typing import Any, Callable, Optional

from .providers.models import normalize_text
from .recent_window import KIND_TRANSFER_EVENT, purify_recent_window, transfer_event_line
from .suggestion_engine import SuggestionEngine, SuggestionResult
# SYSTEM_PROMPT 仅为兼容旧测试的 llm_engine.SYSTEM_PROMPT 引用而再导出
from .llm_client import LlmClientMixin, SYSTEM_PROMPT
from .suggestion_parsing import SuggestionParsingMixin
from .task_router import (
    KN_CONTACT_PROFILE,
    KN_FACTS,
    KN_RELATIONSHIP_SIGNALS,
    KN_USER_STYLE,
    OUTPUT_ANSWER_WITH_SPEECHES,
    OUTPUT_DIRECT_ANSWER,
    TASK_GENERAL_QA,
    TASK_INVITATION_PLANNING,
    TASK_MEMORY_QA,
    TASK_RELATIONSHIP_DISCUSSION,
    TASK_REPLY_SUGGESTION,
    TaskRouting,
    route_generation_task,
)


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


# 与 RagRelevanceGate.RELATIONSHIP_TYPES 保持一致；本地声明避免模块级循环依赖。
_RAG_RELATIONSHIP_DOC_TYPES = frozenset(
    {"relationship_state", "contact_preference", "communication_style"}
)


class LLMSuggestionEngine(SuggestionParsingMixin, LlmClientMixin, SuggestionEngine):
    """
    LLM 建议引擎

    通过 OpenAI 兼容 API 生成建议，支持：
    - 远程 API：DeepSeek / OpenAI / Claude（需配置 api_key）
    - 本地推理：Ollama / LM Studio（无需 api_key）

    """
    RECENT_MESSAGE_LIMIT = 20
    QUICK_PROMPT_MESSAGE_LIMIT = 20
    RECENT_CHAR_GUARD = 1900
    RECENT_MESSAGE_RENDER_CHARS = 90
    QUICK_PROMPT_RENDER_CHARS = 100
    RECENT_ATTENTION_TAIL = 6
    MSG_COMPRESS_THRESHOLD = 20
    MSG_SUMMARY_MAX_CHARS = 180
    MEMORY_LOOKBACK_MESSAGES = 5
    MEMORY_MAX_ITEMS = 3
    STYLE_RULE_KEYWORDS = (
        "短句",
        "长句",
        "连发",
        "图片",
        "语音",
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
    AI_ANTIPATTERN_PHRASES = (
        "我理解你的感受",
        "别太难过了",
        "你说得对",
        "有什么我能帮到你的吗",
        "要不要我陪你聊聊",
        "你值得被温柔以待",
        "加油哦",
        "抱抱你",
        "抱抱你~",
    )
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
    MANUAL_ADVICE_KEYWORDS = (
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
    MANUAL_REWRITE_KEYWORDS = (
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
    MANUAL_ADVICE_CONTEXT_HINTS = (
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
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "\u2600-\u26FF"
        "\u2700-\u27BF"
        "]",
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


    def generate(
        self,
        trigger_type: str,
        intent: str,
        context: dict | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
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
        self._emit_stream(stream_callback, "stage", stage="model_ready", message="模型已就绪")

        # G2 任务路由:task / output / knowledge_needs 三元组替代 direct_reply 二分。
        routing = self._resolve_task_routing(context, trigger_type)
        context["_task_routing"] = routing.to_dict()
        context["_rag_output_mode"] = (
            "reply" if routing.output == OUTPUT_DIRECT_ANSWER else "suggestion"
        )

        try:
            from .rag.context_builder import RagContextBuilder

            self._emit_stream(stream_callback, "stage", stage="rag", message="检索上下文")
            RagContextBuilder().enrich_context(
                context,
                trigger_type=trigger_type,
                intent=intent,
                model_config=model_config,
            )
        except Exception as rag_e:
            _print(f"[LLM Engine] RAG 上下文构造失败，已降级为原链路: {rag_e}")

        # 构造 prompt
        style_constraints = self._resolve_style_constraints(context)
        user_prompt = self._build_prompt(trigger_type, intent, context, model_config=model_config)
        self._emit_stream(
            stream_callback,
            "stage",
            stage="prompt",
            message="提示词已构建",
            prompt_chars=len(user_prompt),
        )
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
                result = self._parse_response(
                    response_text,
                    trigger_type,
                    intent,
                    style_constraints=style_constraints,
                )
                if not result:
                    repaired_text = self._repair_response(model_config, user_prompt, analysis_text)
                    if repaired_text:
                        _print(f"[LLM Engine] 🩹 修复后响应: {repaired_text[:300]}")
                        result = self._parse_response(
                            repaired_text,
                            trigger_type,
                            intent,
                            style_constraints=style_constraints,
                        )
                if result and analysis_text:
                    result.thought_process = analysis_text[:2000]
            else:
                # 调用 API
                self._emit_stream(stream_callback, "stage", stage="llm", message="模型生成中")
                response_text = self._call_api(
                    model_config,
                    user_prompt,
                    stream_callback=stream_callback,
                )
                _print(f"[LLM Engine] 📥 收到响应 ({len(response_text)} 字符):")
                _print(f"[LLM Engine] 响应内容: {response_text[:300]}")

                # 解析响应
                self._emit_stream(stream_callback, "stage", stage="parse", message="解析结果")
                result = self._parse_response(
                    response_text,
                    trigger_type,
                    intent,
                    style_constraints=style_constraints,
                )
                if not result:
                    repaired_text = self._repair_response(model_config, user_prompt, response_text)
                    if repaired_text:
                        _print(f"[LLM Engine] 🩹 修复后响应: {repaired_text[:300]}")
                        result = self._parse_response(
                            repaired_text,
                            trigger_type,
                            intent,
                            style_constraints=style_constraints,
                        )
            if result:
                # 复审 2:输出契约校验(资金推断等安全红线)——prompt 契约
                # 之外在输出侧再拦一道,违规先修复重试,仍违规则留痕。
                result = self._enforce_output_contracts(
                    result, context, model_config, user_prompt,
                    trigger_type, intent, style_constraints,
                )
                if context.get("_rag_log_id"):
                    setattr(result, "rag_log_id", context.get("_rag_log_id"))
                    setattr(result, "rag_conversation_id", context.get("_rag_conversation_id"))
                result.rag_context = self._build_rag_context_summary(context)
                # G6 发送审计:最终 prompt 渲染完才有清单,这里回填检索日志。
                self._persist_sent_manifest(context)
                if result.summary == "[SILENT]":
                    _print("[LLM Engine] 😶 LLM 决定保持沉默，无建议也不需回复。")
                    return result

                _print("[LLM Engine] ✅ LLM 生成成功!")
                _print(f"[LLM Engine] 思考过程: {result.thought_process}")
                _print(f"[LLM Engine] 摘要: {result.summary}")
                _print(f"[LLM Engine] 话术: {result.speeches}")
                _print(f"{'='*60}\n")
                self._emit_stream(stream_callback, "stage", stage="done", message="生成完成")
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

    def _emit_stream(
        self,
        callback: Callable[[dict[str, Any]], None] | None,
        event_type: str,
        **payload: Any,
    ) -> None:
        if not callback:
            return
        try:
            callback({"type": event_type, **payload})
        except Exception:
            pass

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
            estimated_render_len = min(len(content), self.RECENT_MESSAGE_RENDER_CHARS)
            if kept_reversed and total_chars + estimated_render_len > self.RECENT_CHAR_GUARD:
                break

            kept_reversed.append(msg)
            total_chars += estimated_render_len

        kept = list(reversed(kept_reversed))
        older = messages[:-len(kept)] if kept else messages
        return older, kept

    def _normalize_recent_messages(self, messages: list[dict]) -> list[dict]:
        """将最近消息统一归一化为时间正序，并折叠重复屏幕抓取。"""
        if not messages:
            return []

        def _sort_key(item: dict) -> tuple[int, int]:
            timestamp = item.get("timestamp")
            try:
                safe_ts = int(timestamp)
            except (TypeError, ValueError):
                safe_ts = 0
            try:
                safe_visible_index = int(item.get("visible_index", -1))
            except (TypeError, ValueError):
                safe_visible_index = -1
            try:
                safe_created_at = int(item.get("created_at", 0))
            except (TypeError, ValueError):
                safe_created_at = 0
            try:
                safe_captured_at = int(item.get("captured_at", 0))
            except (TypeError, ValueError):
                safe_captured_at = 0
            try:
                safe_id = int(item.get("id"))
            except (TypeError, ValueError):
                safe_id = 0
            if safe_visible_index >= 0:
                return safe_ts, 0, safe_visible_index, safe_created_at, safe_id
            return safe_ts, 1, safe_created_at or safe_captured_at, safe_id, safe_id

        def _dedupe_key(item: dict) -> str:
            semantic_key = "|".join(
                [
                    normalize_text(item.get("sender_attr")),
                    normalize_text(item.get("message_type") or item.get("type")).lower(),
                    normalize_text(item.get("content")),
                    str(_sort_key(item)[0]),
                ]
            )
            if semantic_key.strip("|"):
                return semantic_key

            message_hash = normalize_text(item.get("message_hash"))
            if message_hash:
                return f"hash:{message_hash}"

            return ""

        ordered = sorted(messages, key=_sort_key)
        if ordered and messages and ordered[0] is not messages[0]:
            _print("[LLM Engine] ↕️ recent_messages 已按时间正序归一化")

        deduped: list[dict] = []
        seen_dedupe_keys = set()
        for item in ordered:
            dedupe_key = _dedupe_key(item)
            if dedupe_key and dedupe_key in seen_dedupe_keys:
                continue
            if dedupe_key:
                seen_dedupe_keys.add(dedupe_key)
            deduped.append(item)

        if len(deduped) != len(ordered):
            _print(
                f"[LLM Engine] 🧹 recent_messages 去重: {len(ordered)} -> {len(deduped)}"
            )
        return deduped

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

    def _build_rag_context_summary(self, context: dict) -> dict:
        """Layered user-facing RAG badge states.

        hot_context 只代表正在进行的当前对话，绝不能展示为历史记忆命中。
        G6:badge 只依据"实际发送清单"(_rag_sent_manifest,脱敏并渲染进最终
        prompt 的那部分),候选命中但未注入/未渲染时不得显示"已参考"。
        """
        debug = context.get("_rag_debug") if isinstance(context, dict) else None
        retrieval_context = context.get("retrieval_context") if isinstance(context, dict) else None
        manifest = context.get("_rag_sent_manifest") if isinstance(context, dict) else None
        if not isinstance(debug, dict) or not debug.get("rag_enabled"):
            return {
                "state": "hidden",
                "label": "",
                "hit_count": 0,
                "referenced_count": 0,
                "log_id": context.get("_rag_log_id") if isinstance(context, dict) else None,
            }

        hit_count = int(debug.get("rag_hit_count") or 0)
        referenced_items = []
        if isinstance(retrieval_context, dict) and not retrieval_context.get("no_hit_guard"):
            referenced_items = list(retrieval_context.get("items") or [])
        referenced_count = len(referenced_items)

        # G6:有发送清单时以清单为准(它是渲染进最终 prompt 的真子集)。
        manifest_fact_count = 0
        manifest_doc_count = 0
        manifest_policy_sent = False
        if isinstance(manifest, dict):
            manifest_fact_count = len(manifest.get("fact_ids") or [])
            manifest_doc_count = len(manifest.get("document_ids") or [])
            blocks = set(manifest.get("blocks") or [])
            manifest_policy_sent = bool(
                blocks & {"relationship_policy", "contact_preferences", "relationship_signal"}
            )
            referenced_count = manifest_doc_count

        def _summary(state: str, label: str) -> dict:
            return {
                "state": state,
                "label": label,
                "hit_count": hit_count,
                "referenced_count": referenced_count,
                "log_id": context.get("_rag_log_id"),
            }

        if referenced_count > 0:
            doc_types = {
                str(item.get("doc_type") or "")
                for item in referenced_items
                if isinstance(item, dict)
            }
            hot_only = bool(referenced_items) and doc_types <= {"hot_context"}
            if isinstance(manifest, dict):
                if manifest_fact_count > 0:
                    return _summary("fact_hit", f"已参考 {manifest_fact_count} 条历史事实")
                if hot_only:
                    return _summary("hot_context", "仅参考当前对话上下文")
                if manifest_policy_sent:
                    return _summary("relationship_policy", "已参考关系画像")
                # 有发送清单但全部证据被剔除（fact/doc/policy 全 0）→ hidden
                # 而非"已参考 0 条"——badge 语义是"有没有用上"，不是计数
                if referenced_count == 0 and manifest_doc_count == 0:
                    return _summary("hidden", "")
                return _summary("document_hit", f"已参考 {referenced_count} 条历史记录")
            if "fact_memory" in doc_types:
                return _summary("fact_hit", f"已参考 {referenced_count} 条历史事实")
            if doc_types & _RAG_RELATIONSHIP_DOC_TYPES or debug.get("relationship_policy_injected") or debug.get("contact_preference_injected"):
                return _summary("relationship_policy", "已参考关系画像")
            if doc_types and doc_types <= {"hot_context"}:
                return _summary("hot_context", "仅参考当前对话上下文")
            return _summary("document_hit", f"已参考 {referenced_count} 条历史记录")

        if not isinstance(manifest, dict) and (
            debug.get("relationship_policy_injected") or debug.get("contact_preference_injected")
        ):
            return _summary("relationship_policy", "已参考关系画像")
        if isinstance(manifest, dict) and manifest_policy_sent:
            return _summary("relationship_policy", "已参考关系画像")

        if debug.get("hot_context_only"):
            return _summary("hot_context", "仅参考当前对话上下文")

        degraded_reason = str(debug.get("rag_degraded_reason") or "")
        if degraded_reason == "hot_context_only":
            return _summary("hot_context", "仅参考当前对话上下文")
        if degraded_reason:
            return _summary("degraded", "记忆检索降级")

        if hit_count > 0:
            return _summary("not_referenced", "未参考命中记录")

        memory_mode = str(debug.get("memory_intent_mode") or "")
        gate_decision = str(debug.get("rag_gate_decision") or "")
        if (
            debug.get("rag_no_hit_guard")
            or gate_decision == "no_hit"
            or (debug.get("rag_retrieved") and memory_mode in {"memory_request", "relationship_context"})
        ):
            return _summary("no_hit", "未命中相关记录")

        return _summary("hidden", "")

    def _resolve_task_routing(self, context: dict, trigger_type: str) -> TaskRouting:
        """读取本次请求的任务路由结果;generate() 已缓存时直接复用。"""
        cached = TaskRouting.from_dict(context.get("_task_routing") if isinstance(context, dict) else None)
        if cached is not None:
            return cached
        return route_generation_task(context, trigger_type)

    def _persist_sent_manifest(self, context: dict) -> None:
        """G6:把最终 prompt 发送清单回填到 rag_retrieval_logs(尽力而为,不阻塞生成)。"""
        manifest = context.get("_rag_sent_manifest") if isinstance(context, dict) else None
        log_id = context.get("_rag_log_id") if isinstance(context, dict) else None
        if not isinstance(manifest, dict) or not manifest.get("prompt_hash") or not log_id:
            return
        try:
            from ...db.connection import get_db
            from .rag.store import RagStore

            snapshot = None
            try:
                from .rag.config import load_rag_settings

                if load_rag_settings().get("rag_prompt_snapshot_enabled"):
                    snapshot = context.get("_rag_final_prompt")
            except Exception:
                snapshot = None
            RagStore(get_db()).update_retrieval_log_sent_manifest(
                int(log_id), manifest, prompt_snapshot=snapshot
            )
        except Exception as exc:
            logger.debug("[LLM Engine] 发送清单回填失败(log=%s): %s", log_id, exc)

    # ---- 输出契约校验层(复审 2) ------------------------------------------
    # prompt 契约存在 ≠ 模型遵守;资金推断这类安全边界必须在输出侧再拦一道。

    _TRANSFER_HINT_RE = re.compile(r"转账|红包|收款|转了钱|转你|转我|来回转|转了|那笔钱|笔钱")
    _RELATION_HINT_RE = re.compile(
        r"关系正常|关系好|不讨厌|讨厌你|不喜欢你|喜欢你|态度|冷淡|冷处理|"
        r"热情|在意你|在乎你|理你|回应你|积极|没生你的气|人还在|没回话|不想理|疏远|冷落"
    )

    def _check_output_contracts(self, result: "SuggestionResult", context: dict) -> list[str]:
        """检测输出是否违反硬契约。

        - 资金推断:窗口含资金事件时,输出不得把资金往来当作对方态度/关系
          结论的证据(句级共现;真实使用发现"她转账说明人还在"类措辞,已入词表);
        - 输出形式:direct_answer 不得带建议卡片话术;要话术的输出不得空话术
          (真实使用发现"表达想念"被判直答但模型违规给了话术)。
        """
        violations: list[str] = []

        routing_output = str((context.get("_task_routing") or {}).get("output") or "")
        has_speeches = bool([s for s in (result.speeches or []) if str(s).strip()])
        if routing_output == "direct_answer" and has_speeches:
            violations.append(
                f"输出形式:任务判定为直接回答,但生成了 {len(result.speeches)} 条建议卡片话术"
            )
        if routing_output not in ("", "direct_answer") and not has_speeches:
            violations.append("输出形式:任务需要话术,但 speeches 为空")

        if int(context.get("_window_transfer_event_count") or 0) > 0:
            fields = [("reply", result.reply or ""), ("summary", result.summary or "")]
            fields.extend(("speeches", speech) for speech in (result.speeches or []))
            for field_name, text in fields:
                for sentence in re.split(r"[。！？!?\n；;]+", str(text)):
                    sentence = sentence.strip()
                    if len(sentence) < 4:
                        continue
                    if self._TRANSFER_HINT_RE.search(sentence) and self._RELATION_HINT_RE.search(sentence):
                        violations.append(f"资金推断({field_name}):「{sentence[:60]}」")
        return violations

    def _build_contract_repair_prompt(self, user_prompt: str, violations: list[str]) -> str:
        return (
            f"{user_prompt}\n\n【硬性约束违规,必须重新生成】\n上一版输出违反了以下硬约束:\n"
            + "\n".join(f"- {v}" for v in violations)
            + "\n重新生成时严格遵守:资金往来(转账/红包/收款)只是事件,不能用来推断对方态度、"
            "关系冷热,也不能作为\"她不讨厌你/关系正常\"的证据;需要判断态度时,只能依据对方的"
            "文字聊天内容,证据不足就明说信息不足。其余要求不变,只输出 JSON。"
        )

    def _enforce_output_contracts(
        self,
        result: "SuggestionResult",
        context: dict,
        model_config: Optional[dict],
        user_prompt: str,
        trigger_type: str,
        intent: str,
        style_constraints: "StyleConstraints",
    ) -> "SuggestionResult":
        """违规时做一次修复重试;仍违规则保留输出并在结果上留痕 contract_warnings。"""
        violations = self._check_output_contracts(result, context)
        if not violations:
            return result
        _print(f"[LLM Engine] ⚠️ 输出契约违规 {len(violations)} 条,尝试修复重试")
        if model_config and not self._is_reasoning_model(model_config.get("model_id", "")):
            try:
                retry_prompt = self._build_contract_repair_prompt(user_prompt, violations)
                retry_text = self._call_api(model_config, retry_prompt)
                retry_result = self._parse_response(
                    retry_text, trigger_type, intent, style_constraints=style_constraints,
                )
                if retry_result and not self._check_output_contracts(retry_result, context):
                    setattr(retry_result, "contract_repair", "retry_fixed")
                    setattr(retry_result, "contract_warnings", [])
                    _print("[LLM Engine] ✅ 契约修复重试成功")
                    return retry_result
                if retry_result:
                    result = retry_result  # 重试未完全修复也采用新输出,下面统一留痕
            except Exception as exc:
                _print(f"[LLM Engine] 契约修复重试失败: {exc}")
        setattr(result, "contract_warnings", violations)
        _print(f"[LLM Engine] ⚠️ 输出仍带契约违规 {len(violations)} 条,已留痕")
        return result

    def _build_relationship_signal_lines(self, context: dict, purified: dict) -> list[str]:
        """G5:把好感分析与配对统计渲染成"带时间与不确定性"的关系信号块。

        审核返工 2:真实分析服务返回 ``AffinityAnalysisResult`` 数据类,
        这里必须同时接受对象与 dict(时间字段 ``analysis_timestamp``),
        不能因为类型不符就把 70 分渲染成 unknown。
        """
        from dataclasses import asdict, is_dataclass

        from .recent_window import compute_pairing_stats

        affinity = context.get("affinity_result")
        if is_dataclass(affinity) and not isinstance(affinity, type):
            try:
                affinity = asdict(affinity)
            except Exception:
                affinity = {}
        if not isinstance(affinity, dict):
            affinity = {}
        pairing = compute_pairing_stats(purified.get("chat_window") or [])

        friend_count = int(pairing.get("friend_msg_count") or 0)
        self_count = int(pairing.get("self_msg_count") or 0)
        lines: list[str] = []

        overall_score = affinity.get("overall_score")
        if isinstance(overall_score, (int, float)) and overall_score > 0:
            interpretation = str(affinity.get("overall_interpretation") or "").strip()
            lines.append(f"  好感综合分: {float(overall_score):.0f}/100" + (f"（{interpretation[:60]}）" if interpretation else ""))
        else:
            lines.append("  好感综合分: unknown（缺少分析数据，不要虚构分数）")

        analyzed_at = (
            affinity.get("analysis_timestamp")
            or affinity.get("cache_updated_at")
            or affinity.get("analyzed_at")
            or affinity.get("updated_at")
        )
        if analyzed_at:
            try:
                lines.append(f"  分析时间: {time.strftime('%Y-%m-%d %H:%M', time.localtime(int(analyzed_at)))}")
            except (TypeError, ValueError, OverflowError):
                lines.append("  分析时间: unknown")
        else:
            lines.append("  分析时间: unknown（缓存里没有时间戳）")

        lines.append(f"  数据量: 本次窗口人工聊天 我 {self_count} 条 / 对方 {friend_count} 条")
        trend = affinity.get("trend")
        lines.append(f"  趋势: {trend if trend else 'unknown（缺少趋势数据）'}")
        confidence = "低（样本不足，谨慎使用）" if friend_count + self_count < 10 else "中（基于近期窗口）"
        lines.append(f"  置信度: {confidence}")
        lines.append("  可用于: 判断语气分寸、邀约时机、是否需要降温")
        lines.append(
            "  不能推出: 聊天数量多不等于亲密度高；分数不授权推进关系或表白；"
            "未及时回复不能直接解读为拒绝；资金往来事件不反映对方态度；不要把这些信号说给对方听"
        )
        lines.append(
            "  表述要求: 涉及对方想法/态度的判断必须保留不确定性(可能/或许/更像),"
            "证据不足时明说'信息不足,无法判断',禁止下确定性结论"
        )
        return lines

    def _has_manual_advice_context(self, context: dict) -> bool:
        """判断当前用户输入前，是否已经在围绕“给建议/改话术”这个任务继续追问。"""
        user_context = context.get("user_context")
        if not isinstance(user_context, list):
            return False

        historical_inputs: list[str] = []
        for msg in user_context[:-1]:
            content = str(msg.get("content", "")).strip()
            if content:
                historical_inputs.append(content)

        if not historical_inputs:
            return False

        normalized = re.sub(r"\s+", "", "".join(historical_inputs))
        if any(keyword in normalized for keyword in self.MANUAL_ADVICE_KEYWORDS):
            return True
        return any(keyword in normalized for keyword in self.MANUAL_ADVICE_CONTEXT_HINTS)

    def _make_prompt_redactor(self, model_config: Optional[dict], context: dict) -> Callable[[str, str], str]:
        """构造 prompt 段落脱敏函数。

        与 RAG 上下文脱敏同条件：远程模型 + 脱敏开关开启才生效（本地模型跳过）。
        返回的函数签名为 (text, source_id) -> 脱敏后文本；需要脱敏但初始化或执行
        失败时按项目红线返回占位符并记录错误，绝不把原文发往远端。
        """
        try:
            from .rag.config import is_remote_llm_model, load_rag_settings

            redaction_required = is_remote_llm_model(model_config) and bool(
                load_rag_settings().get("rag_remote_context_redaction")
            )
        except Exception as e:
            logger.error("[LLM Engine] 读取脱敏开关失败，远程 prompt 将按需脱敏处理: %s", e)
            redaction_required = True

        if not redaction_required:
            return lambda text, source_id: text

        redactor = None
        try:
            from ...db.connection import get_db
            from .privacy_redactor import PrivacyRedactor

            redactor = PrivacyRedactor(get_db())
        except Exception as e:
            logger.error("[LLM Engine] prompt 脱敏器初始化失败，相关原文段将被省略: %s", e)

        account_wxid = str(context.get("account_wxid") or "")
        raw_conversation_id = context.get("conversation_id") or context.get("_rag_conversation_id")
        try:
            conversation_id = int(raw_conversation_id) if raw_conversation_id else None
        except (TypeError, ValueError):
            conversation_id = None

        def _redact_segment(text: str, source_id: str) -> str:
            raw = str(text or "")
            if redactor is None:
                return "[脱敏失败，已省略]"
            try:
                return redactor.redact(
                    raw,
                    account_wxid=account_wxid,
                    conversation_id=conversation_id,
                    source_table="llm_prompt",
                    source_id=source_id,
                ).redacted_text
            except Exception as e:
                logger.error("[LLM Engine] prompt 段脱敏失败(source=%s)，已按红线省略该段原文: %s", source_id, e)
                return "[脱敏失败，已省略]"

        return _redact_segment

    _TASK_LABELS = {
        TASK_MEMORY_QA: "回答关于历史聊天/记忆的问题",
        TASK_REPLY_SUGGESTION: "提供发给对方的回复建议",
        TASK_INVITATION_PLANNING: "帮用户策划一次邀约并给出可发送话术",
        TASK_RELATIONSHIP_DISCUSSION: "和用户讨论这段关系的分寸",
        TASK_GENERAL_QA: "直接回答用户的问题",
    }

    def _build_prompt(self, trigger_type: str, intent: str, context: dict, model_config: Optional[dict] = None) -> str:
        """构造用户 prompt"""
        parts = []
        # G2:任务三元组决定输出契约与知识注入,不再用 direct_reply 一票否决知识块。
        routing = self._resolve_task_routing(context, trigger_type)
        is_direct_reply = routing.output == OUTPUT_DIRECT_ANSWER
        needs_facts = routing.needs(KN_FACTS)
        needs_profile = routing.needs(KN_CONTACT_PROFILE)
        needs_style = routing.needs(KN_USER_STYLE)
        needs_signals = routing.needs(KN_RELATIONSHIP_SIGNALS)
        show_context_stats = (not is_direct_reply) or needs_signals
        sent_blocks: list[str] = []
        excluded_reasons: list[dict] = []
        style_constraints = self._resolve_style_constraints(context)

        # 远程模型发送前对最近对话/用户需求原文逐段脱敏（本地模型原样保留）
        redact_segment = self._make_prompt_redactor(model_config, context)

        # 触发原因
        trigger_desc = TRIGGER_DESCRIPTIONS.get(
            trigger_type, f"检测到触发条件: {trigger_type}"
        )
        parts.append(f"【触发原因】{trigger_desc}")

        # 审核返工 3:范围降级时显式封死"无依据具体化"——通用建议不得
        # 虚构店铺/地点/时间/承诺(对应 missing_scope_degrade-20 的教训)。
        if context.get("_generation_scope_missing"):
            parts.append(
                "【范围降级说明】当前缺少该联系人的记忆与画像:不要引用任何具体历史;"
                "不要虚构具体地点、店铺、时间或已发生的约定;给通用建议并说明信息不足。"
            )

        # 走向目标
        task_label = self._TASK_LABELS.get(routing.task, routing.task)
        if is_direct_reply:
            parts.append(f"【当前任务】{task_label}；直接回复用户本人，不是代用户给第三方发消息")
        else:
            intent_desc = INTENT_DESCRIPTIONS.get(intent, intent)
            parts.append(f"【当前任务】{task_label}")
            parts.append(f"【用户目标】{intent_desc}")

        # G3:净化后再选窗,系统通知不占聊天名额,转账渲染为事件行。
        # ``_legacy_prompt_chain``:G0/G7 三路对照用的旧链路等价开关——
        # 跳过净化,保持改造前的窗口选择行为(路由等价映射由回放脚本注入)。
        recent = self._normalize_recent_messages(context.get("recent_messages", []))
        if context.get("_legacy_prompt_chain"):
            _older_messages, recent_window = self._select_recent_messages(recent)
            purified = {
                "window": recent_window,
                "chat_window": recent_window,
                "all_chats": recent,
                "dropped_notices": 0,
                "dropped_unparseable": 0,
                "transfer_events": [],
                "chat_count": len(recent_window),
                "notice_only": False,
            }
        else:
            purified = purify_recent_window(recent, limit=self.RECENT_MESSAGE_LIMIT)
            window_messages = self._normalize_recent_messages(purified["window"])
            _older_messages, recent_window = self._select_recent_messages(window_messages)
        compressed_summary = self._compress_messages(purified["all_chats"], recent_window)
        if recent_window:
            parts.append("\n【最近对话】")
            parts.append(
                f"  注意力分配：按时间顺序理解最近 {len(recent_window)} 条，"
                f"越新的消息权重越高，最后 {min(self.RECENT_ATTENTION_TAIL, len(recent_window))} 条优先级最高。"
            )
            if compressed_summary:
                parts.append(f"  {redact_segment(compressed_summary, 'recent_summary')}")
            for idx, msg in enumerate(recent_window):
                if msg.get("_window_kind") == KIND_TRANSFER_EVENT:
                    # 转账/收款是事件,不是发言;不得据此推断对方态度。
                    parts.append(f"  {transfer_event_line(msg)}")
                    continue
                sender = "我" if msg.get("sender_attr") == "self" else "对方"
                # 先脱敏全文再截断，避免敏感串被截断后绕过模式匹配
                content = redact_segment(
                    str(msg.get("content", "")), f"recent_{idx}"
                )[: self.RECENT_MESSAGE_RENDER_CHARS]
                parts.append(f"  {sender}：{content}")
            if purified["transfer_events"]:
                parts.append(
                    "  ⚠️ 上方【事件】行是资金往来,不代表对方态度;"
                    "不得用它推断冷淡、热情或关系进展,也不得作为'她回应了我'的证据。"
                )
            # 供输出契约校验层使用:窗口里确实存在资金事件时才启用资金推断检测。
            context["_window_transfer_event_count"] = len(purified["transfer_events"])
            if purified["notice_only"]:
                parts.append(
                    "  ⚠️ 当前窗口没有任何有效人工聊天，以上只有系统事件；"
                    "不得据此推断对方冷淡、拒绝或已读不回。"
                )

        # 情绪摘要
        emotion = context.get("emotion_summary")
        if emotion and show_context_stats:
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
        if trigger_ctx and not is_direct_reply:
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
                for idx, msg in enumerate(user_context[-4:]):
                    role_label = "用户" if msg.get("role") == "user" else "AI"
                    content = redact_segment(
                        str(msg.get("content", "")), f"user_context_{idx}"
                    )[:140]
                    parts.append(f"  {role_label}：{content}")
            elif isinstance(user_context, str):
                parts.append(f"【用户需求】{redact_segment(user_context, 'user_context')[:320]}")

        # 历史聊天分析摘要（如请求包含历史数据）
        if context.get("include_history") and not is_direct_reply:
            history_summary = context.get("history_summary")
            if history_summary:
                parts.append(f"【历史关系分析】{history_summary[:500]}")

        # P1.3 关系策略结构化块：影子层派生的联系人级背景（独立小预算槽）
        # G2:是否注入由任务知识需求决定——关系讨论即使直接回答也允许使用。
        relationship_policy = context.get("relationship_policy")
        if relationship_policy and not (needs_signals or needs_profile):
            excluded_reasons.append({
                "kind": "relationship_policy",
                "id": relationship_policy.get("state_id"),
                "reason": "task_knowledge_not_needed",
            })
        if relationship_policy and (needs_signals or needs_profile):
            sent_blocks.append("relationship_policy")
            parts.append("\n【当前关系策略（联系人级背景，供判断分寸）】")
            if relationship_policy.get("stage"):
                parts.append(f"  关系阶段: {relationship_policy['stage']}")
            if relationship_policy.get("closeness_band"):
                band_label = {"high": "高", "medium": "中", "low": "低"}.get(
                    relationship_policy["closeness_band"], relationship_policy["closeness_band"]
                )
                parts.append(f"  亲密度: {band_label}")
            if relationship_policy.get("initiative_pattern"):
                parts.append(f"  主动性: {relationship_policy['initiative_pattern']}")
            if relationship_policy.get("boundary_summary"):
                parts.append(f"  相处边界: {relationship_policy['boundary_summary'][:160]}")
            if relationship_policy.get("communication_tips"):
                parts.append(f"  沟通建议: {relationship_policy['communication_tips'][:160]}")
            confidence = relationship_policy.get("confidence")
            if isinstance(confidence, (int, float)) and confidence > 0:
                parts.append(f"  置信度: {int(confidence * 100)}%")
            parts.append("  使用规则: 以上是系统从历史对话派生的关系背景，只在判断\"怎么回更合适\"时参考；不要向对方复述或主动提起这些结论")

        # P1.2 对方偏好/雷点速查：独立小预算槽，据此调整建议内容与措辞
        contact_preferences = context.get("contact_preferences")
        if contact_preferences and not (needs_signals or needs_profile):
            excluded_reasons.append({
                "kind": "contact_preferences",
                "id": None,
                "reason": "task_knowledge_not_needed",
            })
        if contact_preferences and (needs_signals or needs_profile):
            sent_blocks.append("contact_preferences")
            parts.append("\n【对方偏好与雷点（速查，据此调整建议内容与措辞）】")
            for pref in contact_preferences[:6]:
                kind_label = "雷点" if pref.get("slot_kind") == "avoid" else "偏好"
                summary = str(pref.get("summary") or "")[:120]
                if not summary:
                    continue
                confidence = pref.get("confidence")
                percent = f"（置信 {int(confidence * 100)}%）" if isinstance(confidence, (int, float)) and confidence > 0 else ""
                parts.append(f"  · [{kind_label}] {summary}{percent}")
            parts.append(
                "  使用规则: 建议内容尽量顺着偏好、避开雷点；给出每条话术前自查一遍——"
                "不得与上述任何雷点/偏好冲突；这只是历史倾向，当下对话有明确不同表态时以当下为准；不要向对方复述或主动提起"
            )

        # 联系人画像（如有）—— 策略优先参考：决定"怎么回更合适"
        profile = context.get("contact_profile")
        if profile and not needs_profile:
            excluded_reasons.append({
                "kind": "contact_profile",
                "reason": "task_knowledge_not_needed",
            })
        if profile and needs_profile:
            sent_blocks.append("contact_profile")
            stale_flag = "(较旧，仅供参考)" if context.get("_contact_profile_stale") else ""
            parts.append(f"\n【对方画像（策略优先参考）{stale_flag}】")
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
            parts.append(
                "  使用规则: 判断怎么回更合适时优先适配以上信息；与下方用户表达风格冲突时，以适配对方为先；"
                "画像中的兴趣只作话题线索，不等于双方共同经历"
            )

        # 用户本体专属克隆画像 —— 仅约束措辞，不决定策略
        # G2:纯历史问答/普通问答不强行注入用户口头禅与建议风格。
        self_profile = context.get("self_profile")
        if self_profile and not needs_style:
            excluded_reasons.append({
                "kind": "self_profile",
                "reason": "task_knowledge_not_needed",
            })
        if self_profile and needs_style:
            sent_blocks.append("self_profile")
            parts.append("\n【用户表达风格（仅约束措辞，不决定策略）】")
            typing_style = self_profile.get("typing_style", "")
            if typing_style:
                parts.append(f"  打字排版风格: {typing_style}")
            catchphrases = self_profile.get("frequent_catchphrases", [])
            if catchphrases:
                parts.append(f"  高频语气词汇: {', '.join(catchphrases)}")
            patterns = self_profile.get("sentence_patterns", [])
            if patterns:
                parts.append(f"  常用句式模板（在策略正确的前提下尽量贴近）: {' / '.join(patterns)}")
            donts = self_profile.get("do_and_donts", "")
            if donts:
                parts.append(f"  模仿禁忌: {donts}")
            parts.append("  使用规则: 以上仅决定话术的措辞、标点和长度，读起来像用户本人即可；不得为了模仿风格而放弃更合适的关系策略")
        elif needs_style:
            parts.append("\n【用户风格缺省约束】")
            parts.append("  当前无可用的用户画像缓存，默认每条话术不超过 15 字")
            parts.append("  禁止 emoji、连续感叹号、连续问号，优先短句和口语")

        if needs_style:
            sent_blocks.append("style_constraints")
            parts.append("\n【量化风格硬约束（必须遵守）】")
            if self._has_empirical_style_constraints(style_constraints):
                if style_constraints.avg_msg_length > 0:
                    parts.append(
                        f"  用户平均消息长度: {style_constraints.avg_msg_length:.1f} 字"
                        f" -> 每条话术严禁超过 {style_constraints.max_speech_length} 字"
                    )
                emoji_density_pct = style_constraints.emoji_density * 100
                emoji_rule = {
                    "forbidden": "话术中严禁出现任何 emoji",
                    "limited": "每条话术最多保留 1 个 emoji，且不要堆叠",
                    "free": "emoji 可自然使用，但仍需克制",
                }[self._emoji_policy(style_constraints)]
                parts.append(
                    f"  用户 emoji 使用率: {emoji_density_pct:.1f}% -> {emoji_rule}"
                )
                comm_desc = {
                    "proactive": "主动型，不要突然比本人更冷",
                    "reactive": "被动型，不要建议用户主动追问或过度热情",
                    "balanced": "均衡型，保持自然往返，不要抢节奏",
                }[style_constraints.communication_type]
                parts.append(f"  用户沟通类型: {style_constraints.communication_type} -> {comm_desc}")
                emo_desc = {
                    "cold": "冷淡型，禁止使用过热称呼和过度安慰",
                    "warm": "偏热情，可自然一些，但别用 AI 安抚腔",
                    "neutral": "中性，按当前上下文轻量表达",
                }[style_constraints.emotional_style]
                parts.append(f"  用户情感风格: {style_constraints.emotional_style} -> {emo_desc}")
                parts.append(
                    "  用户昵称习惯: "
                    + ("有专属昵称习惯，可在合适时轻量沿用" if style_constraints.nickname_usage else "没有明显昵称习惯，不要硬加亲昵称呼")
                )
            else:
                parts.append("  当前缺少历史统计缓存，默认每条话术 <= 15 字")
                parts.append("  严禁 emoji、连续感叹号、连续问号")
                parts.append("  优先短句、口语、直接表达，不要写成安慰小作文")

        relevant_memories = self._should_inject_memories(
            recent_window or recent,
            context.get("relevant_memories", []),
        )
        if relevant_memories and needs_facts:
            parts.append("\n【被唤醒的历史记忆（仅作辅助，不要盖过当前对话）】")
            for mem in relevant_memories:
                summary = str(mem.get("summary", "")).strip()
                created = mem.get("created_at", 0)
                age_hours = int((time.time() - created) / 3600) if created else 0
                time_label = f"{age_hours}小时前" if age_hours < 24 else f"{age_hours // 24}天前"
                parts.append(f"  {time_label}: {summary}")

        retrieval_context = context.get("retrieval_context")
        rendered_fact_ids: list[Any] = []
        rendered_doc_ids: list[Any] = []
        if retrieval_context:
            items = retrieval_context.get("items") or []
            no_hit_guard = bool(retrieval_context.get("no_hit_guard"))
            retrieval_status = str(retrieval_context.get("retrieval_status") or "")
            query = str(retrieval_context.get("query") or "").strip()
            memory_intent = retrieval_context.get("memory_intent") or context.get("memory_intent") or {}
            query_mode = str(memory_intent.get("mode") or "unknown") if isinstance(memory_intent, dict) else "unknown"
            time_strategy = "近期优先" if any(token in query for token in ("刚刚", "刚才", "上次", "之前")) else "相关优先"
            if no_hit_guard:
                parts.append("\n【历史记忆检索结果】")
                parts.append("  检索状态：no_hit")
                parts.append(f"  查询意图：{query_mode}")
                parts.append(f"  时间策略：{time_strategy}")
                if query:
                    parts.append(f"  说明：当前联系人历史中没有找到和“{query[:80]}”直接相关的可靠记忆。")
                else:
                    parts.append("  说明：当前联系人历史中没有找到直接相关的可靠记忆。")
                parts.append("  要求：没查到就说没查到；不要编造具体时间、地点、流派、店名、事件。")
                if is_direct_reply:
                    parts.append("  可以建议用户自然追问对方确认；不要生成建议卡片，除非用户明确要求话术。")
                else:
                    parts.append("  可以基于最近对话生成保守话术；优先建议自然追问对方确认。")
            elif items and retrieval_status == "weak_hit":
                parts.append("\n【联系人关系背景】")
                parts.append("  检索状态：weak_hit")
                parts.append("  说明：以下只作为关系策略参考，不要直接复述为具体历史事实。")
                parts.append("  内容：")
                for index, item in enumerate(items[:4], 1):
                    content = str(item.get("content") or "").strip()
                    if content:
                        time_label = str(item.get("time_label") or "").strip()
                        parts.append(f"  {index}. 时间：{time_label or '未知'}；内容：{content}")
                        rendered_doc_ids.append(item.get("document_id"))
            elif items:
                style_items = [
                    item
                    for item in items
                    if str(item.get("doc_type") or "") in {"self_style_example", "communication_style"}
                ]
                memory_items = [
                    item
                    for item in items
                    if str(item.get("doc_type") or "") not in {"self_style_example", "communication_style"}
                ]
                if memory_items:
                    parts.append("\n【历史记忆检索结果】")
                    parts.append("  检索状态：hit")
                    parts.append(f"  查询意图：{query_mode}")
                    parts.append(f"  时间策略：{time_strategy}")
                    parts.append("  优先级：当前对话和用户显式需求永远高于历史记忆。")
                    parts.append("  使用边界：只在历史内容直接服务当前回复目标时参考；不要为了使用记忆而引入旧话题。")
                    parts.append("  结果：")
                    sent_blocks.append("retrieval_memory")
                memory_limit = 8 if any(
                    str(item.get("doc_type") or "") == "fact_memory" for item in memory_items
                ) else 4
                for index, item in enumerate(memory_items[:memory_limit], 1):
                    content = str(item.get("content") or "").strip()
                    if content:
                        rendered_doc_ids.append(item.get("document_id"))
                        if str(item.get("doc_type") or "") == "fact_memory":
                            rendered_fact_ids.append(item.get("document_id"))
                        doc_type = str(item.get("doc_type") or "memory")
                        time_label = str(item.get("time_label") or "").strip()
                        parts.append(
                            f"  {index}. 时间：{time_label or '未知'}；类型：{doc_type}；"
                            f"相关度：{float(item.get('score') or 0):.2f}"
                        )
                        prefix = "原文" if doc_type == "evidence_excerpt" else "内容"
                        parts.append(f"     {prefix}：{content}")
                        if doc_type == "fact_memory":
                            evidence_ids = item.get("evidence_message_ids") or []
                            status = str(item.get("fact_status") or "active")
                            confidence = float(item.get("fact_confidence") or 0.0)
                            subject = str(item.get("subject") or "未知")
                            as_of = item.get("as_of") or item.get("source_ts")
                            try:
                                as_of_label = time.strftime("%Y-%m-%d", time.localtime(int(as_of)))
                            except (TypeError, ValueError, OverflowError):
                                as_of_label = "未知"
                            parts.append(f"     主体：{subject}；截至：{as_of_label}")
                            parts.append(
                                f"     事实状态：{status}；置信度：{confidence:.2f}；"
                                f"证据消息：{','.join(str(value) for value in evidence_ids) or '未知'}"
                            )
                if memory_items:
                    parts.append("  要求：只能基于以上结果回答历史细节；如果结果未包含具体细节，必须说没查到。")
                    parts.append(
                        "  区分：只有标注 主体=共同 的事实是双方共同经历；主体=对方/我 的是各自的兴趣或行为，"
                        "回答\"我们一起/我们玩过\"类问题时不得把各自兴趣说成共同经历。"
                    )
                    parts.append("  禁止：不要把历史里的地点、游戏、偏好、约定强行带入无关的当前回复。")
                    if is_direct_reply:
                        parts.append("  直接回答用户问题；不要生成建议卡片，除非用户明确要求话术。")
                if style_items:
                    parts.append("\n【用户表达风格参考】")
                    parts.append("  说明：以下只用于语气、长度、标点和亲密度；不得当作历史事实。")
                    sent_blocks.append("retrieval_style")
                    for index, item in enumerate(style_items[:3], 1):
                        content = str(item.get("content") or "").strip()
                        if content:
                            parts.append(f"  {index}. {content}")
                            rendered_doc_ids.append(item.get("document_id"))

        historical_ctx = context.get("historical_context", {})
        history_lines = []
        if historical_ctx and show_context_stats:
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

        # G5:好感分析以"带时间与不确定性的关系信号"注入,不直接等同亲密度。
        # G1 红线:联系人范围缺失/歧义时不注入——即使数据只来自当前窗口,
        # 也不给模型任何可归因到具体联系人的关系结论素材。
        if needs_signals and not context.get("_generation_scope_missing"):
            signal_lines = self._build_relationship_signal_lines(context, purified)
            if signal_lines:
                sent_blocks.append("relationship_signal")
                parts.append("\n【关系信号（带时间与不确定性，仅供参考）】")
                parts.extend(signal_lines)

        # 用户调教规则（最高优先级）
        display_name = context.get("display_name")
        if display_name and not needs_style:
            excluded_reasons.append({
                "kind": "feedback_rules",
                "reason": "task_knowledge_not_needed",
            })
        if display_name and needs_style:
            try:
                from .feedback_rule_extractor import FeedbackRuleExtractor
                rules = self._filter_style_rules(
                    FeedbackRuleExtractor().get_active_rules(
                        display_name,
                        str(context.get("account_wxid") or ""),
                    )
                )
                if rules:
                    sent_blocks.append("feedback_rules")
                    parts.append("\n【表达偏好参考（仅影响措辞，不决定话题）】")
                    for i, rule in enumerate(rules, 1):
                        parts.append(f"  规则{i}: {rule}")
            except Exception as e:
                _print(f"[LLM Engine] 加载调教规则失败: {e}")

        if trigger_type == "manual_request":
            if is_direct_reply:
                parts.append(
                    "\n【手动求助模式】当前更像是用户在直接和 AI 说话/提问，"
                    "不是在请教怎么回复对方。"
                    "此时必须优先在 `reply` 字段直接回应用户，"
                    "`reply` 不得为空字符串——没有回答比回答得不好更糟糕；"
                    "并将 `summary` 设为空字符串、`speeches` 设为空数组，"
                    "不要生成建议卡片。"
                    "reply 必须使用自然、简洁的助手口吻，"
                    "不要模仿用户给对方说话的口吻，不要使用对方专属称呼。"
                )
            elif routing.output == OUTPUT_ANSWER_WITH_SPEECHES:
                parts.append(
                    "\n【手动求助模式】当前是用户在请教一件具体事项（如邀约、关系推进）。"
                    "先在 `reply` 字段直接回应用户的问题或想法，"
                    "再在 `speeches` 中给出 2-3 条用户可以直接发送给对方的原话。"
                    "`reply` 和 `speeches` 都必须有内容；"
                    "不要只给分析不给话术，也不要把话术写进 reply。"
                    "话术必须贴合用户输入的目标——不得擅自引入用户没提到的行动、地点或既成事实。"
                )
            else:
                parts.append(
                    "\n【手动求助模式】当前是用户在请教怎么回复对方或怎么开启话题。"
                    "请基于当前上下文给出可发送的话术；"
                    "话术必须贴合用户输入的目标，不得擅自引入用户没提到的行动、地点或既成事实。"
                    "并且必须严格只输出 JSON，不要输出解释、前言或额外文本。"
                )

        if not is_direct_reply:
            parts.append("\n【禁止使用的 AI 典型句式】")
            parts.append("  我理解你的感受 / 别太难过了 / 你说得对")
            parts.append("  有什么我能帮到你的吗 / 要不要我陪你聊聊")
            parts.append("  你值得被温柔以待 / 加油哦 / 抱抱你")
            parts.append("  任何过度完整、过度客套、像心理咨询模板的话")

        parts.append("\n请根据以上信息生成思考过程和沟通建议（纯 JSON 输出）：")
        prompt = "\n".join(parts)
        total_chars = len(prompt)
        _print(f"[LLM Engine] 📏 Prompt 总长度: {total_chars} 字符")
        if total_chars > 3000:
            _print("[LLM Engine] ⚠️ Prompt 较长，建议检查最近对话窗口和压缩逻辑")

        # G6:候选命中但未渲染的条目记录排除原因,区分"召回/选中/实际发送"。
        # evidence_redacted_unusable 的条目先从 items 排除（下方单独记录），
        # 不再落入 prompt_budget 分支——同一 document 不双计
        rendered_id_set = {str(value) for value in rendered_doc_ids if value is not None}
        unusable_id_set = {str(v) for v in context.get("_rag_evidence_unusable_ids") or []}
        if isinstance(retrieval_context, dict):
            for item in retrieval_context.get("items") or []:
                item_id = str(item.get("document_id"))
                if item_id in unusable_id_set:
                    continue  # 由 evidence_redacted_unusable 单独记录
                if item_id not in rendered_id_set:
                    excluded_reasons.append({
                        "kind": "retrieval_item",
                        "id": item.get("document_id"),
                        "reason": "prompt_budget_or_not_rendered",
                    })
        for unusable_id in context.get("_rag_evidence_unusable_ids") or []:
            excluded_reasons.append({
                "kind": "retrieval_item",
                "id": unusable_id,
                "reason": "evidence_redacted_unusable",
            })

        import hashlib as _hashlib

        context["_rag_sent_manifest"] = {
            "request_id": context.get("_generation_request_id"),
            "entrypoint": context.get("_generation_entrypoint"),
            "task": routing.task,
            "output": routing.output,
            "blocks": sent_blocks,
            "fact_ids": [value for value in rendered_fact_ids if value is not None],
            "document_ids": [value for value in rendered_doc_ids if value is not None],
            "policy_ids": (
                [relationship_policy.get("state_id")]
                if "relationship_policy" in sent_blocks and relationship_policy
                else []
            ),
            "contact_preference_ids": (
                [pref.get("pref_id") for pref in (contact_preferences or [])[:6] if pref.get("pref_id")]
                if "contact_preferences" in sent_blocks
                else []
            ),
            "excluded": excluded_reasons,
            "prompt_chars": total_chars,
            "prompt_hash": _hashlib.sha256(prompt.encode("utf-8", "ignore")).hexdigest(),
        }
        context["_rag_final_prompt"] = prompt
        return prompt

    
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
        _print("[LLM Engine] 开始生成动态联想词")
        _print(f"{'='*60}")

        model_config = self._get_active_model()
        if not model_config:
            _print("❌ [LLM Engine] 未配置激活模型！")
            raise ValueError("未配置激活模型")

        prompt = "请阅读以下双方的最新聊天记录，推测用户（‘我’）下一步最可能想发起的话题方向或对话策略。\n"
        prompt += (
            "要求：给出 4 个选项；每个选项必须是简短的动宾短语（限 4 个字内，如‘顺着话题’、‘转移话题’、‘约她吃饭’、‘表达心疼’）；"
            "理解上下文时按时间顺序看最近对话，但越新的消息权重越高，最后几句优先。"
            "只返回一个 JSON 格式的字符串数组，不要其他废话。\n\n"
        )

        recent = self._normalize_recent_messages(context.get("recent_messages", []))
        if recent:
            # 与建议主链路同口径（L2 同类）：联想词 prompt 的最近对话块在发送
            # 远端前同样过脱敏器，本地模型不生效，脱敏失败按红线省略原文。
            redact_segment = self._make_prompt_redactor(model_config, context)
            _older_messages, recent_window = self._select_recent_messages(recent)
            prompt += "【最近对话】\n"
            prompt += (
                f"注意力分配：按时间顺序理解最近 {len(recent_window)} 条，"
                f"越新的消息权重越高，最后 {min(self.RECENT_ATTENTION_TAIL, len(recent_window))} 条优先级最高。\n"
            )
            for idx, msg in enumerate(recent_window, 1):
                sender = "我" if msg.get("sender_attr") == "self" else "对方"
                content = redact_segment(
                    str(msg.get("content", ""))[: self.QUICK_PROMPT_RENDER_CHARS],
                    f"quick_prompt_recent_{idx}",
                )
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
