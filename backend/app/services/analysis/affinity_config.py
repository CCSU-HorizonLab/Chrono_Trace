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

    weight_emotional_resonance: float = 0.40
    weight_chat_positivity: float = 0.35
    weight_attitude_tendency: float = 0.25
    preference_bonus_factor: float = 0.10

    reply_timeliness_threshold_seconds: int = 300
    topic_continuity_window_days: int = 7
    similarity_threshold: float = 0.4
    sliding_window_size: int = 10
    long_text_threshold: int = 100

    preference_keywords: List[str] = field(default_factory=list)

    conversation_id: int = 0
    updated_at: int = 0


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
                config_dict.pop("weight_preference_compatibility", None)

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
        kwargs.pop("weight_preference_compatibility", None)

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
        """Validate a config object."""
        total_weight = (
            config.weight_emotional_resonance
            + config.weight_chat_positivity
            + config.weight_attitude_tendency
        )

        if not (0.99 <= total_weight <= 1.01):
            raise ValueError(f"维度权重总和必须为 1.0，当前为 {total_weight}")

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

    def get_dimension_weights(self, conversation_id: int) -> dict:
        """Return fixed display weights for all dimensions."""
        return {
            "emotional_resonance": 0.40,
            "chat_positivity": 0.35,
            "attitude_tendency": 0.25,
            "preference_compatibility": 0.00,
        }
