"""
建议引擎抽象层
import logging

定义 SuggestionEngine ABC 和 SuggestionResult 数据类，
提供统一的建议生成接口和工厂类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)
@dataclass
class SuggestionResult:
    """建议生成结果"""
    trigger_type: str             # 触发类型标识
    intent: str                   # intimate / maintain / distance
    summary: str                  # 建议摘要（一句话）
    speeches: list[str] = field(default_factory=list)  # 具体话术列表
    severity: str = "medium"      # high / medium / low
    confidence: float = 1.0       # 置信度 0-1


class SuggestionEngine(ABC):
    """
    建议引擎抽象基类

    所有建议引擎（模板、本地 LLM、云端 API）都需实现此接口。
    """

    @abstractmethod
    def generate(self, trigger_type: str, intent: str, context: dict | None = None) -> SuggestionResult:
        """
        根据触发类型和发展走向生成建议

        Args:
            trigger_type: 触发类型（如 'negative_streak'）
            intent: 发展走向（'intimate' / 'maintain' / 'distance'）
            context: 附加上下文（可选，如消息内容、情绪摘要等）

        Returns:
            SuggestionResult 实例
        """
        ...


class SuggestionEngineFactory:
    """建议引擎工厂"""

    _engine_cache: dict[str, SuggestionEngine] = {}

    @classmethod
    def create(cls, engine_type: str = "template") -> SuggestionEngine:
        """
        创建或获取建议引擎实例

        Args:
            engine_type: 引擎类型
                - 'template': 规则模板引擎（默认）
                - 'local_llm': 本地 LLM 引擎（暂未实现）
                - 'cloud_api': 云端 API 引擎（暂未实现）

        Returns:
            SuggestionEngine 实例

        Raises:
            ValueError: 未知引擎类型
        """
        if engine_type in cls._engine_cache:
            return cls._engine_cache[engine_type]

        if engine_type == "template":
            from .template_engine import TemplateSuggestionEngine
            engine = TemplateSuggestionEngine()
        elif engine_type in ("llm", "local_llm", "cloud_api"):
            from .llm_engine import LLMSuggestionEngine
            engine = LLMSuggestionEngine()
        else:
            raise ValueError(f"未知引擎类型: {engine_type}")

        cls._engine_cache[engine_type] = engine
        return engine
