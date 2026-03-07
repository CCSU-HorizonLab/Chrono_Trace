"""
节日日期库 - 管理常见节日的日期映射
支持公历节日和农历节日的日期计算
"""
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import calendar
class HolidayLibrary:
    """节日日期库"""
    
    # 固定公历节日 (月-日)
    FIXED_HOLIDAYS = {
        "元旦": (1, 1),
        "情人节": (2, 14),
        "妇女节": (3, 8),
        "植树节": (3, 12),
        "愚人节": (4, 1),
        "劳动节": (5, 1),
        "青年节": (5, 4),
        "儿童节": (6, 1),
        "建党节": (7, 1),
        "建军节": (8, 1),
        "教师节": (9, 10),
        "国庆节": (10, 1),
        "万圣节": (10, 31),
        "光棍节": (11, 11),
        "感恩节": (11, 28),  # 近似值,实际为11月第四个周四
        "平安夜": (12, 24),
        "圣诞节": (12, 25),
    }
    
    # 农历节日 (需要转换,这里提供近似公历日期范围)
    # 格式: (最早可能月份, 最晚可能月份)
    LUNAR_HOLIDAYS_RANGE = {
        "春节": (1, 2),      # 1月21日-2月20日
        "元宵节": (2, 3),    # 2月4日-3月5日
        "清明节": (4, 4),    # 4月4日-4月6日
        "端午节": (5, 6),    # 5月下旬-6月下旬
        "七夕节": (8, 8),    # 8月上旬-8月下旬
        "中秋节": (9, 10),   # 9月上旬-10月上旬
        "重阳节": (10, 11),  # 10月上旬-11月上旬
        "腊八节": (1, 1),    # 1月上旬-1月下旬
        "小年": (1, 2),      # 1月中旬-2月中旬
        "除夕": (1, 2),      # 1月下旬-2月中旬
    }
    
    # 特殊节日(浮动日期)
    FLOATING_HOLIDAYS = {
        "母亲节": (5, 2, 0),   # 5月第二个周日
        "父亲节": (6, 3, 0),   # 6月第三个周日
    }
    
    @staticmethod
    def get_holiday_date(holiday_name: str, year: int) -> Optional[str]:
        """
        获取指定年份的节日日期
        
        Args:
            holiday_name: 节日名称
            year: 年份
            
        Returns:
            日期字符串 "YYYY-MM-DD",如果无法确定则返回None
        """
        # 固定公历节日
        if holiday_name in HolidayLibrary.FIXED_HOLIDAYS:
            month, day = HolidayLibrary.FIXED_HOLIDAYS[holiday_name]
            return f"{year}-{month:02d}-{day:02d}"
        
        # 浮动节日
        if holiday_name in HolidayLibrary.FLOATING_HOLIDAYS:
            month, week_num, weekday = HolidayLibrary.FLOATING_HOLIDAYS[holiday_name]
            date = HolidayLibrary._get_nth_weekday(year, month, week_num, weekday)
            if date:
                return date.strftime("%Y-%m-%d")
        
        # 农历节日 - 返回None(需要更复杂的农历转换)
        if holiday_name in HolidayLibrary.LUNAR_HOLIDAYS_RANGE:
            return None
        
        return None
    
    @staticmethod
    def _get_nth_weekday(year: int, month: int, week_num: int, weekday: int) -> Optional[datetime]:
        """
        获取某月第N个星期X的日期
        
        Args:
            year: 年份
            month: 月份
            week_num: 第几个(1-5)
            weekday: 星期几(0=周一,6=周日)
            
        Returns:
            日期对象
        """
        # 获取该月第一天
        first_day = datetime(year, month, 1)
        first_weekday = first_day.weekday()
        
        # 计算第一个目标星期几的日期
        days_until_target = (weekday - first_weekday) % 7
        first_target = first_day + timedelta(days=days_until_target)
        
        # 加上周数
        target_date = first_target + timedelta(weeks=week_num - 1)
        
        # 检查是否还在当月
        if target_date.month != month:
            return None
        
        return target_date
    
    @staticmethod
    def is_holiday_date(date_str: str, holiday_name: str, tolerance_days: int = 1) -> bool:
        """
        检查指定日期是否为某个节日(允许容错天数)
        
        Args:
            date_str: 日期字符串 "YYYY-MM-DD"
            holiday_name: 节日名称
            tolerance_days: 容错天数(前后N天内都算)
            
        Returns:
            是否为该节日
        """
        try:
            check_date = datetime.strptime(date_str, "%Y-%m-%d")
            year = check_date.year
            
            # 获取节日日期
            holiday_date_str = HolidayLibrary.get_holiday_date(holiday_name, year)
            if not holiday_date_str:
                # 农历节日 - 使用月份范围判断
                if holiday_name in HolidayLibrary.LUNAR_HOLIDAYS_RANGE:
                    month_range = HolidayLibrary.LUNAR_HOLIDAYS_RANGE[holiday_name]
                    return check_date.month in month_range
                return False
            
            holiday_date = datetime.strptime(holiday_date_str, "%Y-%m-%d")
            
            # 检查是否在容错范围内
            diff_days = abs((check_date - holiday_date).days)
            return diff_days <= tolerance_days
            
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def extract_holiday_from_keywords(text: str, holiday_keywords: list) -> Optional[str]:
        """
        从文本中提取节日名称
        
        Args:
            text: 文本内容
            holiday_keywords: 节日关键词列表
            
        Returns:
            节日名称,如果没有匹配则返回None
        """
        if not text or not holiday_keywords:
            return None
        
        text_lower = text.lower()
        
        # 遍历所有已知节日
        all_holidays = list(HolidayLibrary.FIXED_HOLIDAYS.keys()) + \
                      list(HolidayLibrary.LUNAR_HOLIDAYS_RANGE.keys()) + \
                      list(HolidayLibrary.FLOATING_HOLIDAYS.keys())
        
        for holiday in all_holidays:
            # 完整匹配，例如 "中秋节"
            if holiday in text or holiday.lower() in text_lower:
                return holiday
            
            # 部分匹配，去掉最后一个"节"字，例如 "中秋"
            if holiday.endswith("节"):
                short_name = holiday[:-1]
                if short_name in text or short_name.lower() in text_lower:
                    return holiday
        
        # 如果没有直接匹配,返回None
        return None
