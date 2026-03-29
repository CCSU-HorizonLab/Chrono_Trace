"""Feature extraction configuration."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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

        settings_path = Path(__file__).parent.parent.parent.parent / "data" / "settings.json"

        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            config_dict = dict(settings.get("feature_extraction", {}))
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
