"""关系上下文服务 - 管理好感度分析的前置关系信息

提供3个字段的CRUD操作:
1. 关系类型 (relationship_type)
2. 互动时长 (interaction_duration)
3. 沟通风格 (communication_style)

这些信息用于校准好感度分析中各维度的阈值和期望基线。
"""

import json
import time
import logging
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

from ...db.connection import get_db

logger = logging.getLogger(__name__)


# ===== 常量定义 =====

# 关系类型
RELATIONSHIP_TYPES = {
    "lover": "恋人",
    "crush": "暧昧对象",
    "friend": "朋友",
    "colleague": "同事",
    "family": "家人",
    "other": "其他",
}

# 互动时长
INTERACTION_DURATIONS = {
    "less_1_month": "不到1个月",
    "1_to_6_months": "1-6个月",
    "6_to_12_months": "6-12个月",
    "over_1_year": "1年以上",
}

# 沟通风格
COMMUNICATION_STYLES = {
    "talkative": "话多热情",
    "normal": "正常",
    "reserved": "话少内敛",
}


@dataclass
class RelationshipContext:
    """关系上下文数据"""
    relationship_type: str = "friend"           # 关系类型
    interaction_duration: str = "1_to_6_months"  # 互动时长
    communication_style: str = "normal"          # 沟通风格
    conversation_id: int = 0
    updated_at: int = 0


class RelationshipContextService:
    """关系上下文服务"""

    MEDIA_THRESHOLDS_BY_RELATIONSHIP = {
        "lover": {"video": 4.0, "voice": 20.0},
        "crush": {"video": 4.0, "voice": 20.0},
        "friend": {"video": 3.0, "voice": 20.0},
        "family": {"video": 3.0, "voice": 20.0},
        "colleague": {"video": 1.0, "voice": 10.0},
        "other": {"video": 1.0, "voice": 10.0},
    }
    DEFAULT_MEDIA_RELATIONSHIP_TYPE = "friend"

    def __init__(self):
        pass  # get_db() removed for thread safety

    def get_context(self, conversation_id: int) -> Optional[RelationshipContext]:
        """
        获取会话的关系上下文

        Args:
            conversation_id: 会话ID

        Returns:
            RelationshipContext 或 None（未填写时）
        """
        try:
            key = f"relationship_context_{conversation_id}"
            cursor = get_db().execute("""
                SELECT value FROM settings WHERE key = ?
            """, (key,))

            row = cursor.fetchone()
            if not row:
                return None

            ctx_dict = json.loads(row[0])
            return RelationshipContext(**ctx_dict)

        except Exception as e:
            logger.error(f"获取关系上下文失败: {e}")
            return None

    def save_context(
        self,
        conversation_id: int,
        relationship_type: str,
        interaction_duration: str,
        communication_style: str,
    ) -> RelationshipContext:
        """
        保存关系上下文

        Args:
            conversation_id: 会话ID
            relationship_type: 关系类型
            interaction_duration: 互动时长
            communication_style: 沟通风格

        Returns:
            RelationshipContext: 保存后的上下文

        Raises:
            ValueError: 参数无效
        """
        # 验证参数
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"无效的关系类型: {relationship_type}")
        if interaction_duration not in INTERACTION_DURATIONS:
            raise ValueError(f"无效的互动时长: {interaction_duration}")
        if communication_style not in COMMUNICATION_STYLES:
            raise ValueError(f"无效的沟通风格: {communication_style}")

        ctx = RelationshipContext(
            relationship_type=relationship_type,
            interaction_duration=interaction_duration,
            communication_style=communication_style,
            conversation_id=conversation_id,
            updated_at=int(time.time()),
        )

        try:
            key = f"relationship_context_{conversation_id}"
            ctx_json = json.dumps(asdict(ctx), ensure_ascii=False)

            get_db().execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, ctx_json, ctx.updated_at))

            get_db().commit()
            logger.info(f"关系上下文已保存 (会话 {conversation_id})")

        except Exception as e:
            logger.error(f"保存关系上下文失败: {e}")

        return ctx

    def has_context(self, conversation_id: int) -> bool:
        """检查是否已填写关系上下文"""
        return self.get_context(conversation_id) is not None

    def get_multimedia_thresholds(self, conversation_id: int) -> Dict[str, float]:
        """Return relationship-derived multimedia thresholds."""
        ctx = self.get_context(conversation_id)
        relationship_type = (
            ctx.relationship_type
            if ctx and ctx.relationship_type in self.MEDIA_THRESHOLDS_BY_RELATIONSHIP
            else self.DEFAULT_MEDIA_RELATIONSHIP_TYPE
        )
        thresholds = self.MEDIA_THRESHOLDS_BY_RELATIONSHIP[relationship_type]
        return {
            "relationship_type": relationship_type,
            "video": float(thresholds["video"]),
            "voice": float(thresholds["voice"]),
        }

    @staticmethod
    def get_field_options() -> Dict[str, Any]:
        """
        获取表单字段的所有选项（供前端渲染表单使用）

        Returns:
            各字段的选项列表
        """
        return {
            "relationship_types": [
                {"value": k, "label": v}
                for k, v in RELATIONSHIP_TYPES.items()
            ],
            "interaction_durations": [
                {"value": k, "label": v}
                for k, v in INTERACTION_DURATIONS.items()
            ],
            "communication_styles": [
                {"value": k, "label": v}
                for k, v in COMMUNICATION_STYLES.items()
            ],
        }
