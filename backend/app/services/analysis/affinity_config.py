"""好感度分析配置服务

管理好感度分析的配置参数，包括：
- 维度权重
- 阈值参数
- 喜好关键词
"""

import json
import logging
from dataclasses import dataclass, asdict, field
from typing import List, Optional

from ...db.connection import get_db

# 配置日志
logger = logging.getLogger(__name__)


@dataclass
class AffinityConfig:
    """好感度分析配置"""
    
    # 维度权重 (总和必须为 1.0)
    # 注: 这是有喜好关键词时的默认权重
    weight_emotional_resonance: float = 0.35
    weight_chat_positivity: float = 0.35
    weight_attitude_tendency: float = 0.20
    weight_preference_compatibility: float = 0.10
    
    # 阈值参数
    reply_timeliness_threshold_seconds: int = 300  # 5 分钟
    topic_continuity_window_days: int = 7
    similarity_threshold: float = 0.4
    sliding_window_size: int = 10
    long_text_threshold: int = 100  # 字符数
    
    # 喜好关键词
    preference_keywords: List[str] = field(default_factory=list)
    
    # 元数据
    conversation_id: int = 0
    updated_at: int = 0


class AffinityConfigService:
    """好感度分析配置服务"""
    
    def __init__(self):
        self.db = get_db()
    
    def get_config(self, conversation_id: int) -> AffinityConfig:
        """
        获取会话的配置 (含默认值)
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            AffinityConfig: 配置对象
        """
        try:
            key = f"affinity_config_{conversation_id}"
            cursor = self.db.execute("""
                SELECT value FROM settings WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            if row:
                config_dict = json.loads(row[0])
                return AffinityConfig(**config_dict)
            
            # 返回默认配置
            config = AffinityConfig()
            config.conversation_id = conversation_id
            return config
            
        except Exception as e:
            logger.error(f"获取配置失败: {e}")
            config = AffinityConfig()
            config.conversation_id = conversation_id
            return config
    
    def update_config(
        self,
        conversation_id: int,
        **kwargs
    ) -> AffinityConfig:
        """
        更新会话配置
        
        Args:
            conversation_id: 会话 ID
            **kwargs: 要更新的配置项
            
        Returns:
            AffinityConfig: 更新后的配置对象
        """
        # 获取现有配置
        config = self.get_config(conversation_id)
        
        # 更新配置项
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        # 验证配置
        self.validate_config(config)
        
        # 更新时间戳
        import time
        config.updated_at = int(time.time())
        config.conversation_id = conversation_id
        
        # 保存到数据库
        try:
            key = f"affinity_config_{conversation_id}"
            config_json = json.dumps(asdict(config), ensure_ascii=False)
            
            self.db.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, config_json, config.updated_at))
            
            self.db.commit()
            logger.info(f"配置已更新 (会话 {conversation_id})")
            
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
        
        return config
    
    def validate_config(self, config: AffinityConfig) -> bool:
        """
        验证配置有效性
        
        Args:
            config: 配置对象
            
        Returns:
            是否有效
            
        Raises:
            ValueError: 配置无效时抛出
        """
        # 验证权重总和为 1.0
        total_weight = (
            config.weight_emotional_resonance +
            config.weight_chat_positivity +
            config.weight_attitude_tendency +
            config.weight_preference_compatibility
        )
        
        if not (0.99 <= total_weight <= 1.01):  # 允许浮点误差
            raise ValueError(f"维度权重总和必须为 1.0，当前为 {total_weight}")
        
        # 验证阈值范围
        if config.reply_timeliness_threshold_seconds < 0:
            raise ValueError("回复及时阈值不能为负数")
        
        if config.topic_continuity_window_days < 1:
            raise ValueError("话题延续窗口至少为 1 天")
        
        if not (0.0 <= config.similarity_threshold <= 1.0):
            raise ValueError("相似度阈值必须在 0-1 之间")
        
        if config.sliding_window_size < 1:
            raise ValueError("滑动窗口大小至少为 1")
        
        # 验证喜好关键词
        if config.preference_keywords:
            for keyword in config.preference_keywords:
                if not isinstance(keyword, str) or not keyword.strip():
                    raise ValueError("喜好关键词必须是非空字符串")
        
        return True
    
    def get_preference_keywords(self, conversation_id: int) -> List[str]:
        """
        获取喜好关键词
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            喜好关键词列表
        """
        config = self.get_config(conversation_id)
        return config.preference_keywords
    
    def update_preference_keywords(
        self,
        conversation_id: int,
        keywords: List[str]
    ) -> List[str]:
        """
        更新喜好关键词
        
        Args:
            conversation_id: 会话 ID
            keywords: 关键词列表
            
        Returns:
            更新后的关键词列表
        """
        # 清理关键词
        cleaned = [k.strip() for k in keywords if k.strip()]
        
        # 更新配置
        config = self.update_config(
            conversation_id,
            preference_keywords=cleaned
        )
        
        return config.preference_keywords
    
    def get_dimension_weights(self, conversation_id: int) -> dict:
        """
        根据是否有喜好关键词,动态返回维度权重
        
        有喜好关键词时:
        - 情感共振率: 35%
        - 聊天积极度: 35%
        - 态度倾向: 20%
        - 喜好兼容度: 10%
        
        无喜好关键词时:
        - 情感共振率: 40%
        - 聊天积极度: 35%
        - 态度倾向: 25%
        - 喜好兼容度: 0%
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            包含各维度权重的字典
        """
        config = self.get_config(conversation_id)
        has_preference_keywords = bool(config.preference_keywords)
        
        if has_preference_keywords:
            # 有喜好关键词时的权重
            return {
                'emotional_resonance': 0.35,
                'chat_positivity': 0.35,
                'attitude_tendency': 0.20,
                'preference_compatibility': 0.10,
            }
        else:
            # 无喜好关键词时的权重(喜好维度权重为0)
            return {
                'emotional_resonance': 0.40,
                'chat_positivity': 0.35,
                'attitude_tendency': 0.25,
                'preference_compatibility': 0.00,
            }
