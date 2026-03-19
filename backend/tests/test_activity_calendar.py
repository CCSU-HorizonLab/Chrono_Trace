import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.analysis import analysis_service as analysis_service_module
from app.webview.bridge import Bridge


class StubCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class StubDb:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, query, params):
        return StubCursor(self._rows)


def test_get_activity_calendar_aggregates_days(monkeypatch):
    rows = [
        (1704067200, 1704069000, 10, "user"),   # 2024-01-01
        (1704070800, 1704072000, 5, "other"),   # 2024-01-01
        (1704153600, 1704154500, 8, "other"),   # 2024-01-02
        (1735689600, 1735691400, 20, "user"),   # 2025-01-01
    ]

    monkeypatch.setattr(analysis_service_module, "get_db", lambda: StubDb(rows))

    service = analysis_service_module.AnalysisService()
    result = service.get_activity_calendar(7, 2024)

    assert result["year"] == 2024
    assert result["years"] == [2024, 2025]
    assert len(result["entries"]) == 2
    assert result["entries"][0]["date"] == "2024-01-01"
    assert result["entries"][0]["message_count"] == 15
    assert result["entries"][0]["session_count"] == 2
    assert result["entries"][0]["user_initiated_sessions"] == 1
    assert result["entries"][0]["other_initiated_sessions"] == 1
    assert result["summary"]["active_days"] == 2
    assert result["summary"]["total_messages"] == 23
    assert result["summary"]["current_streak"] == 2
    assert result["summary"]["longest_streak"] == 2
    assert result["summary"]["peak_day"]["date"] == "2024-01-01"


def test_get_activity_calendar_defaults_to_latest_year(monkeypatch):
    rows = [
        (1704067200, 1704069000, 4, "user"),    # 2024-01-01
        (1735689600, 1735693200, 6, "other"),   # 2025-01-01
    ]

    monkeypatch.setattr(analysis_service_module, "get_db", lambda: StubDb(rows))

    service = analysis_service_module.AnalysisService()
    result = service.get_activity_calendar(7)

    assert result["year"] == 2025
    assert result["entries"][0]["date"] == "2025-01-01"


def test_bridge_get_activity_calendar_returns_service_payload(monkeypatch):
    expected = {
        "year": 2026,
        "years": [2026],
        "entries": [{"date": "2026-03-19", "activity_score": 100}],
        "summary": {
            "active_days": 1,
            "total_messages": 12,
            "current_streak": 1,
            "longest_streak": 1,
            "peak_day": {"date": "2026-03-19", "message_count": 12, "session_count": 1, "activity_score": 100},
        },
        "max_activity_score": 100,
    }

    class StubAnalysisService:
        def get_activity_calendar(self, conversation_id: int, year=None):
            assert conversation_id == 42
            assert year == 2026
            return expected

    monkeypatch.setattr(analysis_service_module, "AnalysisService", StubAnalysisService)

    bridge = Bridge.__new__(Bridge)
    result = bridge.get_activity_calendar(42, 2026)

    assert result["success"] is True
    assert result["data"] == expected
