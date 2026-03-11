"""
建议引擎抽象层

定义 SuggestionEngine ABC 和 SuggestionResult 数据类，
提供统一的建议生成接口和工厂类。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
@dataclass
class SuggestionResult:
    """建议结果"""
    trigger_type: str        # 触发该建议的原因
    intent: str              # 该建议的走向目标
    summary: str             # 一句话摘要（如“拉近距离，分享日常”）
    speeches: list[str] = field(default_factory=list)      # 具体话术选项（2-3条）
    severity: str = "medium" # 严重程度: low, medium, high, critical
    confidence: float = 1.0  # 置信度 (0.0 - 1.0)
    thought_process: str | None = None # AI 思考过程 (CoT)
    reply: str | None = None  # AI 对用户输入的自然语言回应


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
    def create(cls, engine_type: str = "llm") -> SuggestionEngine:
        """
        创建或获取建议引擎实例

        Args:
            engine_type: 引擎类型
                - 'llm', 'local_llm', 'cloud_api': LLM 引擎

        Returns:
            SuggestionEngine 实例

        Raises:
            ValueError: 未知引擎类型
        """
        if engine_type in cls._engine_cache:
            return cls._engine_cache[engine_type]

        if engine_type in ("llm", "local_llm", "cloud_api"):
            from .llm_engine import LLMSuggestionEngine
            engine = LLMSuggestionEngine()
        else:
            raise ValueError(f"未知引擎类型: {engine_type}")

        cls._engine_cache[engine_type] = engine
        return engine
