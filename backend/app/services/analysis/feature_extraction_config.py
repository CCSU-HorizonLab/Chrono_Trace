"""Feature extraction configuration."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ...config import SETTINGS_PATH


ANALYSIS_DEVICE_MODE_AUTO = "auto"
ANALYSIS_DEVICE_MODE_GPU = "gpu"
ANALYSIS_DEVICE_MODE_CPU = "cpu"
VALID_ANALYSIS_DEVICE_MODES = {
    ANALYSIS_DEVICE_MODE_AUTO,
    ANALYSIS_DEVICE_MODE_GPU,
    ANALYSIS_DEVICE_MODE_CPU,
}


def normalize_analysis_device_mode(value: Optional[str]) -> str:
    """Normalize persisted or caller-provided device mode."""
    normalized = str(value or ANALYSIS_DEVICE_MODE_AUTO).strip().lower()
    if normalized not in VALID_ANALYSIS_DEVICE_MODES:
        return ANALYSIS_DEVICE_MODE_AUTO
    return normalized


@dataclass
class FeatureExtractionConfig:
    """Feature extraction configuration."""

    session_gap_threshold: int = 1800
    sleep_start_hour: int = 0
    sleep_end_hour: int = 7
    max_response_time: int = 86400
    batch_size: int = 1000
    db_commit_interval: int = 5000
    analysis_device_mode: str = ANALYSIS_DEVICE_MODE_AUTO

    @classmethod
    def from_settings(cls) -> "FeatureExtractionConfig":
        """Load config from settings.json."""
        import json

        settings_path = Path(SETTINGS_PATH)

        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            config_dict = dict(settings.get("feature_extraction", {}))
            # 未知键剔除：settings.json 用户可编辑、跨版本演进（旧残留/未来
            # 新字段），原样 cls(**config_dict) 遇未知键即 TypeError 打崩
            # 整个特征提取与分析链路——静默忽略未知键才是持久配置的正确姿态
            import dataclasses

            field_names = {f.name for f in dataclasses.fields(cls)}
            config_dict = {k: v for k, v in config_dict.items() if k in field_names}
            config_dict["analysis_device_mode"] = normalize_analysis_device_mode(
                config_dict.get("analysis_device_mode", settings.get("analysis_device_mode"))
            )
            return cls(**config_dict)

        return cls()

    def validate(self) -> None:
        """Validate config values."""
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

        self.analysis_device_mode = normalize_analysis_device_mode(self.analysis_device_mode)
