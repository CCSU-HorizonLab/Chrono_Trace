"""态度倾向统计（AttitudeStatistics + AttitudePreprocessingService）。（拆分自原 preprocessing_service.py）"""
import re
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ....db.connection import get_db

logger = logging.getLogger(__name__)


# ============================================================
# 态度预处理服务 - 收集态度倾向统计
# ============================================================

from dataclasses import dataclass


@dataclass
class AttitudeStatistics:
    """态度统计数据结构"""
    emoji_message_count: int = 0          # 表情包消息数
    voice_message_count: int = 0          # 语音消息数
    video_message_count: int = 0          # 视频通话消息数
    nickname_message_count: int = 0       # 专属称呼消息数
    sender_nickname_message_count: int = 0
    contact_nickname_message_count: int = 0
    privacy_message_count: int = 0        # 隐私分享消息数
    holiday_message_count: int = 0        # 节日祝福消息数
    holidays_sent_count: int = 0          # 独立节日日期数(去重)
    
    # 新增：用于强化主动性和深夜语境分析的字段
    # 这部分不在这里直接聚合情感词频率（因为在基础统计中），但是我们需要基础情感消息数按语境区分
    # 为了避免重复造轮子，这里只记录深夜产生的特殊行为（如深度分享、专属称呼）
    late_night_nickname_count: int = 0    # 深夜说的专属称呼
    late_night_privacy_count: int = 0     # 深夜说的隐私分享
    late_night_message_count: int = 0     # 深夜消息总数


class AttitudePreprocessingService:
    """态度预处理服务 - 单次遍历统计 O(N)"""

    # 微信消息类型常量
    MESSAGE_TYPE_TEXT = 1
    MESSAGE_TYPE_IMAGE = 3
    MESSAGE_TYPE_VOICE = 34
    MESSAGE_TYPE_VIDEO = 43
    MESSAGE_TYPE_EMOJI = 47
    
    # 消息类型到统计字段的映射(优化:减少if-elif链)
    TYPE_TO_FIELD = {
        47: 'emoji_message_count',   # MESSAGE_TYPE_EMOJI
        34: 'voice_message_count',   # MESSAGE_TYPE_VOICE
        43: 'video_message_count',   # MESSAGE_TYPE_VIDEO
    }

    def __init__(self, keyword_lib=None):
        """
        初始化服务

        Args:
            keyword_lib: 关键词库实例(可选,默认创建新实例)
        """
        from ..keyword_libraries import KeywordLibraries
        from ..holiday_library import HolidayLibrary
        
        self.keyword_lib = keyword_lib or KeywordLibraries()
        self.holiday_lib = HolidayLibrary()
        self._keywords_cache = None

    def collect_attitude_statistics(self, messages):
        """
        单次遍历收集态度统计数据 (O(N))

        Args:
            messages: 消息列表,每条消息格式:
                {
                    'content': str,        # 消息内容
                    'message_type': int,   # 消息类型
                    'timestamp': int,      # 时间戳
                    'is_sender': int       # 0=对方,1=用户
                }

        Returns:
            AttitudeStatistics: 态度统计结果
        """
        # 验证输入
        if not messages:
            return AttitudeStatistics()
        
        # 延迟加载关键词(只在第一次调用时加载)
        if self._keywords_cache is None:
            self._keywords_cache = self.keyword_lib.get_all_keywords()

        stats = AttitudeStatistics()
        holidays_seen = set()  # 用于去重节日(格式: "节日名-年份")

        for i, msg in enumerate(messages):
            try:
                # 验证消息格式
                if not isinstance(msg, dict):
                    logger.warning(f"[警告] 消息 #{i} 格式无效,跳过")
                    continue
                
                content = msg.get('content', '')
                msg_type = msg.get('message_type', self.MESSAGE_TYPE_TEXT)
                timestamp = msg.get('timestamp', 0)
                is_sender = int(msg.get('is_sender', 0) or 0)
                
                # 修复: sqlite可能会返回bytes
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='replace')

                # 优化1: 使用字典映射处理消息类型统计
                if msg_type in self.TYPE_TO_FIELD:
                    field = self.TYPE_TO_FIELD[msg_type]
                    setattr(stats, field, getattr(stats, field) + 1)

                # 只对文本消息进行关键词匹配
                if msg_type == self.MESSAGE_TYPE_TEXT and content:
                    # 判断是否为深夜 (23:00 - 05:00)
                    is_late_night = False
                    if timestamp:
                        msg_dt = datetime.fromtimestamp(timestamp)
                        if msg_dt.hour >= 23 or msg_dt.hour < 5:
                            is_late_night = True
                            stats.late_night_message_count += 1
                    
                    # 优化2: 一次性检查所有关键词类别
                    keyword_matches = self._check_all_keywords(content)
                    
                    # 统计专属称呼
                    if keyword_matches.get('nickname'):
                        stats.nickname_message_count += 1
                        if is_sender:
                            stats.sender_nickname_message_count += 1
                        else:
                            stats.contact_nickname_message_count += 1
                        if is_late_night:
                            stats.late_night_nickname_count += 1

                    # 统计隐私分享
                    if keyword_matches.get('privacy'):
                        stats.privacy_message_count += 1
                        if is_late_night:
                            stats.late_night_privacy_count += 1

                    # 优化3: 改进节日祝福统计 - 基于节日名称+日期匹配
                    if keyword_matches.get('holiday'):
                        # 双方任何一方发送了节日祝福都计入统计
                        stats.holiday_message_count += 1
                        
                        # 提取节日名称并验证日期
                        holiday_name = self._extract_holiday_name(content)
                        if timestamp:
                            msg_date = self._extract_date_from_timestamp(timestamp)
                            if msg_date:
                                if holiday_name:
                                    # 检查消息日期是否在节日当天(容错±1天)
                                    if self.holiday_lib.is_holiday_date(msg_date, holiday_name, tolerance_days=1):
                                        # 使用"节日名-年份"作为唯一标识
                                        year = datetime.fromtimestamp(timestamp).year
                                        holiday_key = f"{holiday_name}-{year}"
                                        holidays_seen.add(holiday_key)
                                    else:
                                        # 如果日期不匹配,仍然记录(可能是提前祝福)
                                        # 但使用消息日期作为标识
                                        holidays_seen.add(msg_date)
                                else:
                                    # 未提取到具体节日名（比如只说了"节日快乐"），按日期记录
                                    holidays_seen.add(msg_date)
            
            except Exception as e:
                # 优化4: 添加异常处理,确保单条消息异常不影响整体统计
                logger.error(f"[错误] 处理消息 #{i} 时出错: {e}")
                continue

        # 计算独立节日数
        stats.holidays_sent_count = len(holidays_seen)

        return stats

    def _check_all_keywords(self, text):
        """
        一次性检查文本中的所有关键词类别(优化:减少重复遍历)

        Args:
            text: 文本内容

        Returns:
            dict: {category: bool} 各类别是否匹配
        """
        results = {
            'nickname': False,
            'privacy': False,
            'holiday': False
        }
        
        if not text:
            return results
        
        # 使用优化后的正则预编译方法
        for category in results.keys():
            results[category] = self.keyword_lib.check_keywords_in_text_by_category(text, category)
        
        return results
    
    def _extract_holiday_name(self, text):
        """
        从文本中提取节日名称

        Args:
            text: 文本内容

        Returns:
            str: 节日名称,如果没有匹配则返回None
        """
        # 确保关键词缓存已初始化
        if self._keywords_cache is None:
            self._keywords_cache = self.keyword_lib.get_all_keywords()

        holiday_keywords = self._keywords_cache.get('holiday', [])
        return self.holiday_lib.extract_holiday_from_keywords(text, holiday_keywords)

    def _extract_date_from_timestamp(self, timestamp):
        """
        从时间戳提取日期字符串

        Args:
            timestamp: Unix时间戳

        Returns:
            str: 日期字符串 "YYYY-MM-DD"
        """
        if not timestamp:
            return ""

        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return ""
