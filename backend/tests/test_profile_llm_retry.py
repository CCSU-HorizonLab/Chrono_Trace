import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.error


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.self_profiler import SelfProfiler


def _build_model_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE llm_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            api_base_url TEXT NOT NULL,
            api_key TEXT,
            is_active INTEGER DEFAULT 0,
            max_tokens INTEGER DEFAULT 512,
            temperature REAL DEFAULT 0.7,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO llm_models (
            name, provider, model_id, api_base_url, api_key,
            is_active, max_tokens, temperature, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "deepseek chat",
            "deepseek",
            "deepseek-chat",
            "https://api.deepseek.com/v1",
            "token",
            1,
            1024,
            0.3,
            now,
            now,
        ),
    )
    conn.commit()
    return conn


class _DummyResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "typing_style": "short",
                                    "frequent_catchphrases": ["ok"],
                                    "sentence_patterns": ["[x] ok"],
                                    "shared_memories": ["self did something recently"],
                                    "attitude_and_role": "calm",
                                    "do_and_donts": "keep it short",
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode("utf-8")


def test_self_profiler_call_llm_retries_ssl_eof_and_succeeds(monkeypatch):
    conn = _build_model_db()
    profiler = SelfProfiler(timeout=5)
    attempts = {"count": 0}

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr("app.services.realtime.llm_http.time.sleep", lambda _seconds: None)

    def fake_urlopen(req, timeout=0, context=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise urllib.error.URLError(
                ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
            )
        return _DummyResponse()

    monkeypatch.setattr("app.services.realtime.llm_http.urllib.request.urlopen", fake_urlopen)

    result = profiler._call_llm("test prompt", 4000)

    assert attempts["count"] == 2
    assert result["typing_style"] == "short"
    assert result["do_and_donts"] == "keep it short"


def test_self_profiler_call_llm_raises_clear_error_after_ssl_retries_exhausted(monkeypatch):
    conn = _build_model_db()
    profiler = SelfProfiler(timeout=5)

    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    monkeypatch.setattr("app.services.realtime.llm_http.time.sleep", lambda _seconds: None)

    def fake_urlopen(req, timeout=0, context=None):
        raise urllib.error.URLError(
            ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        )

    monkeypatch.setattr("app.services.realtime.llm_http.urllib.request.urlopen", fake_urlopen)

    try:
        profiler._call_llm("test prompt", 4000)
    except ConnectionError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected ConnectionError")

    assert "LLM network request failed" in message
    assert "EOF occurred in violation of protocol" in message
