import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.analysis import analysis_service as analysis_service_module
from app.webview.bridge import Bridge


def test_get_response_times_includes_distribution(monkeypatch):
    expected_stats = {
        "count": 4,
        "avg": 312.5,
        "median": 180.0,
        "min": 30.0,
        "max": 1200.0,
        "stddev": None,
        "abnormal_count": 1,
        "distribution": {
            "<1m": 1,
            "1m-10m": 2,
            "10m-30m": 1,
            "30m-1h": 0,
            "1h-6h": 0,
            "6h-24h": 0,
            ">1d": 0,
        },
    }

    class StubAnalysisService:
        def get_response_time_stats(self, conversation_id: int):
            assert conversation_id == 42
            return expected_stats

    monkeypatch.setattr(analysis_service_module, "AnalysisService", StubAnalysisService)

    bridge = Bridge.__new__(Bridge)
    result = bridge.get_response_times(42)

    assert result["success"] is True
    assert result["data"] == expected_stats
    assert result["data"]["distribution"]["1m-10m"] == 2
