"""
规则模板建议引擎

基于触发类型 × 发展走向查表匹配预设建议模板，
不依赖任何外部服务，延迟 < 10ms。
"""

import random
from .suggestion_engine import SuggestionEngine, SuggestionResult
from .suggestion_templates import TEMPLATES, VALID_TRIGGER_TYPES, VALID_INTENTS


class TemplateSuggestionEngine(SuggestionEngine):
    """
    模板建议引擎

    从 suggestion_templates.py 中的 18 套模板匹配结果。
    完全本地，无网络依赖。
    """

    def generate(
        self,
        trigger_type: str,
        intent: str,
        context: dict | None = None,
    ) -> SuggestionResult:
        """
        根据触发类型和发展走向生成建议

        Args:
            trigger_type: 触发类型
            intent: 发展走向 (intimate/maintain/distance)
            context: 附加上下文（当前版本未使用，预留给 LLM 引擎）

        Returns:
            SuggestionResult
        """
        # 参数验证与 fallback
        if trigger_type not in VALID_TRIGGER_TYPES:
            return self._fallback_result(trigger_type, intent)

        if intent not in VALID_INTENTS:
            intent = "maintain"  # 默认走向兜底

        # 查表
        template = TEMPLATES[trigger_type][intent]

        # 确定严重度
        severity_map = {
            "negative_streak": "high",
            "emotion_shift": "high",
            "perfunctory": "medium",
            "silence": "medium",
            "positive_window": "low",
            "topic_cooling": "medium",
        }

        return SuggestionResult(
            trigger_type=trigger_type,
            intent=intent,
            summary=template["summary"],
            speeches=list(template["speeches"]),  # 拷贝，避免外部修改
            severity=severity_map.get(trigger_type, "medium"),
            confidence=1.0,
        )

    def _fallback_result(self, trigger_type: str, intent: str) -> SuggestionResult:
        """未知触发类型的兜底建议"""
        return SuggestionResult(
            trigger_type=trigger_type,
            intent=intent,
            summary="当前情况建议谨慎回应，观察对方态度",
            speeches=["可以先简单回应，看看对方的反应再做下一步"],
            severity="low",
            confidence=0.5,
        )
