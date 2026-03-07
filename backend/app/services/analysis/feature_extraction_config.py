"""特征提取配置类"""
from dataclasses import dataclass
from typing import Optional
import logging


logger = logging.getLogger(__name__)
@dataclass
class FeatureExtractionConfig:
    """特征提取配置"""

    # 会话切分参数
    session_gap_threshold: int = 1800  # 30分钟（秒）
    sleep_start_hour: int = 0          # 00:00
    sleep_end_hour: int = 7            # 07:00

    # 响应时间参数
    max_response_time: int = 86400     # 24小时（秒）

    # 性能参数
    batch_size: int = 1000             # 批处理大小
    db_commit_interval: int = 5000     # 数据库提交间隔

    @classmethod
    def from_settings(cls) -> 'FeatureExtractionConfig':
        """从settings.json加载配置"""
        import json
        from pathlib import Path

        settings_path = Path(__file__).parent.parent.parent.parent / 'data' / 'settings.json'

        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                config_dict = settings.get('feature_extraction', {})
                return cls(**config_dict)

        return cls()  # 返回默认配置

    def validate(self) -> None:
        """验证配置合法性"""
        if self.session_gap_threshold < 60:
            raise ValueError("session_gap_threshold must be >= 60 seconds")

        if not (0 <= self.sleep_start_hour <= 23):
            raise ValueError("sleep_start_hour must be 0-23")

        if not (1 <= self.sleep_end_hour <= 24):
            raise ValueError("sleep_end_hour must be 1-24")

        if self.max_response_time < 0:
            raise ValueError("max_response_time must be >= 0")

        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        if self.db_commit_interval < 1:
            raise ValueError("db_commit_interval must be >= 1")
