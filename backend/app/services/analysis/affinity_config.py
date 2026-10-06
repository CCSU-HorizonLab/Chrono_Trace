"""Affinity analysis configuration service."""

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import List

from ...db.connection import get_db

logger = logging.getLogger(__name__)


@dataclass
class AffinityConfig:
    """Affinity analysis configuration."""

    # 六维 declared 权重（点数制，不要求和为 1；评分引擎按在场维度归一，
    # 见 affinity_weights.resolve_dimension_plan）
    weight_emotional_resonance: float = 0.40
    weight_chat_positivity: float = 0.35
    weight_attitude_tendency: float = 0.25
    weight_preference_compatibility: float = 0.10
    weight_intimacy_signals: float = 0.12
    weight_llm_relationship: float = 0.08
    llm_relationship_enabled: bool = True
    preference_bonus_factor: float = 0.10

    reply_timeliness_threshold_seconds: int = 300
    topic_continuity_window_days: int = 7
    similarity_threshold: float = 0.4
    sliding_window_size: int = 10
    long_text_threshold: int = 100

    preference_keywords: List[str] = field(default_factory=list)

    conversation_id: int = 0
    updated_at: int = 0

    #: 参与评分与配置指纹的全部权重字段（新增权重必须同步登记）
    WEIGHT_FIELDS = (
        "weight_emotional_resonance",
        "weight_chat_positivity",
        "weight_attitude_tendency",
        "weight_preference_compatibility",
        "weight_intimacy_signals",
        "weight_llm_relationship",
    )


class AffinityConfigService:
    """Persistence and validation for affinity configuration."""

    def __init__(self):
        pass

    def get_config(self, conversation_id: int) -> AffinityConfig:
        """Load config for a conversation, falling back to defaults."""
        try:
            key = f"affinity_config_{conversation_id}"
            cursor = get_db().execute(
                """
                SELECT value FROM settings WHERE key = ?
                """,
                (key,),
            )

            row = cursor.fetchone()
            if row:
                config_dict = json.loads(row[0])

                config = AffinityConfig(**config_dict)
                config.conversation_id = conversation_id
                return config

            config = AffinityConfig()
            config.conversation_id = conversation_id
            return config
        except Exception as e:
            logger.error(f"获取配置失败: {e}")
            config = AffinityConfig()
            config.conversation_id = conversation_id
            return config

    def update_config(self, conversation_id: int, **kwargs) -> AffinityConfig:
        """Update and persist config for a conversation."""
        config = self.get_config(conversation_id)

        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

        self.validate_config(config)

        import time

        config.updated_at = int(time.time())
        config.conversation_id = conversation_id

        try:
            key = f"affinity_config_{conversation_id}"
            config_json = json.dumps(asdict(config), ensure_ascii=False)

            get_db().execute(
                """
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, config_json, config.updated_at),
            )
            get_db().commit()
            logger.info(f"配置已更新 (会话 {conversation_id})")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

        return config

    def validate_config(self, config: AffinityConfig) -> bool:
        """Validate a config object.

        权重为点数制：各维 0-1、至少一个 > 0（归一由评分引擎完成）——
        此前要求三权和恰为 1 是旧二档口径的遗留。
        """
        for name in AffinityConfig.WEIGHT_FIELDS:
            value = getattr(config, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} 必须在 0-1 之间，当前为 {value}")

        if all(getattr(config, name) <= 0 for name in AffinityConfig.WEIGHT_FIELDS):
            raise ValueError("至少一个维度权重要大于 0")

        if not isinstance(config.llm_relationship_enabled, bool):
            raise ValueError("llm_relationship_enabled 必须是布尔值")

        if config.reply_timeliness_threshold_seconds < 0:
            raise ValueError("回复及时阈值不能为负数")

        if config.topic_continuity_window_days < 1:
            raise ValueError("话题延续窗口至少为 1 天")

        if not (0.0 <= config.similarity_threshold <= 1.0):
            raise ValueError("相似度阈值必须在 0-1 之间")

        if config.sliding_window_size < 1:
            raise ValueError("滑动窗口大小至少为 1")

        if config.preference_bonus_factor < 0:
            raise ValueError("喜好加分系数不能为负数")

        for keyword in config.preference_keywords:
            if not isinstance(keyword, str) or not keyword.strip():
                raise ValueError("喜好关键词必须是非空字符串")

        return True

    def get_preference_keywords(self, conversation_id: int) -> List[str]:
        """Return preference keywords for a conversation."""
        return self.get_config(conversation_id).preference_keywords

    def update_preference_keywords(self, conversation_id: int, keywords: List[str]) -> List[str]:
        """Update preference keywords for a conversation."""
        cleaned = [k.strip() for k in keywords if k.strip()]
        config = self.update_config(conversation_id, preference_keywords=cleaned)
        return config.preference_keywords
