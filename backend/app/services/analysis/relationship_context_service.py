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


@dataclass
class AnalysisAdjustments:
    """基于关系上下文的分析参数调整

    各个维度的校准系数,1.0表示不调整
    """
    # 日均消息数期望值乘数（话少内敛的人日均消息低是正常的）
    daily_message_expectation: float = 1.0

    # 消息长度期望值乘数（话少的人消息短是正常的）
    message_length_expectation: float = 1.0

    # 专属称呼频率期望乘数（恋人关系下称呼频率基线更高）
    nickname_expectation: float = 1.0

    # 多媒体使用期望乘数
    multimedia_expectation: float = 1.0

    # 隐私分享期望乘数（家人/恋人更容易分享隐私）
    privacy_sharing_expectation: float = 1.0

    # 信任倾诉加分系数（关系越亲密，对方向你倾诉负面情绪加分越高）
    trust_sharing_bonus_factor: float = 1.0


class RelationshipContextService:
    """关系上下文服务"""

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

    def get_adjustments(self, conversation_id: int) -> AnalysisAdjustments:
        """
        根据关系上下文生成分析参数调整

        Args:
            conversation_id: 会话ID

        Returns:
            AnalysisAdjustments: 分析参数调整
        """
        ctx = self.get_context(conversation_id)
        adj = AnalysisAdjustments()

        if not ctx:
            return adj  # 未填写则返回默认值（不做任何调整）

        # ===== 根据沟通风格调整 =====
        if ctx.communication_style == "reserved":
            # 话少内敛：降低对消息数量和长度的期望
            adj.daily_message_expectation = 0.6
            adj.message_length_expectation = 0.7
            adj.multimedia_expectation = 0.7
        elif ctx.communication_style == "talkative":
            # 话多热情：提高期望基线
            adj.daily_message_expectation = 1.3
            adj.message_length_expectation = 1.2
            adj.multimedia_expectation = 1.2

        # ===== 根据互动时长调整 =====
        if ctx.interaction_duration == "over_1_year":
            # 超过1年：日均消息可能自然下降，不应过多扣分
            adj.daily_message_expectation *= 0.7
        elif ctx.interaction_duration == "less_1_month":
            # 不到1个月：期望值应相对保守
            adj.daily_message_expectation *= 0.8

        # ===== 根据关系类型调整 =====
        if ctx.relationship_type == "lover":
            # 恋人：专属称呼和隐私分享期望更高
            adj.nickname_expectation = 1.5
            adj.privacy_sharing_expectation = 1.3
            adj.trust_sharing_bonus_factor = 1.5
        elif ctx.relationship_type == "crush":
            # 暧昧对象：信任倾诉加分适中
            adj.nickname_expectation = 1.2
            adj.trust_sharing_bonus_factor = 1.3
        elif ctx.relationship_type == "family":
            # 家人：隐私分享和信任倾诉较高
            adj.privacy_sharing_expectation = 1.4
            adj.trust_sharing_bonus_factor = 1.4
        elif ctx.relationship_type == "colleague":
            # 同事：降低亲密行为的期望
            adj.nickname_expectation = 0.6
            adj.privacy_sharing_expectation = 0.7
            adj.trust_sharing_bonus_factor = 0.8

        return adj

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
