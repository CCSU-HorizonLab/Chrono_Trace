import os
import sqlite3
import sys
import threading


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import DatabaseConnection


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def test_old_wechat_schema_is_rebuilt_before_new_indexes(tmp_path):
    db_path = tmp_path / "old_chrono_trace.db"
    seed = sqlite3.connect(db_path)
    try:
        seed.execute(
            """
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                remark TEXT,
                nickname TEXT,
                platform TEXT DEFAULT 'wechat',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                message_count INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0
            )
            """
        )
        seed.execute(
            """
            CREATE TABLE contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                nickname TEXT,
                remark TEXT,
                avatar_path TEXT
            )
            """
        )
        seed.execute(
            """
            INSERT INTO conversations
            (username, display_name, created_at, updated_at)
            VALUES ('wxid_friend', 'Friend', 1, 1)
            """
        )
        seed.commit()
    finally:
        seed.close()

    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    try:
        conn = DatabaseConnection.initialize(str(db_path))

        assert "account_wxid" in _columns(conn, "conversations")
        assert "account_wxid" in _columns(conn, "contacts")
        assert "account_wxid" in _columns(conn, "realtime_message_buffer")
        assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0

        index_row = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_conversations_account_username'
            """
        ).fetchone()
        assert index_row is not None
    finally:
        DatabaseConnection.close()
        DatabaseConnection._db_path = None


def test_fresh_database_initialization_executes_schema_sql(tmp_path):
    db_path = tmp_path / "fresh_chrono_trace.db"

    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    try:
        conn = DatabaseConnection.initialize(str(db_path))

        realtime_buffer = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'realtime_message_buffer'
            """
        ).fetchone()
        realtime_suggestions = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'realtime_suggestions'
            """
        ).fetchone()

        assert realtime_buffer is not None
        assert realtime_suggestions is not None
    finally:
        DatabaseConnection.close()
        DatabaseConnection._db_path = None


def test_schema_initialization_runs_once_across_threads(tmp_path, monkeypatch):
    db_path = tmp_path / "threaded_chrono_trace.db"
    normalized_path = DatabaseConnection._normalize_db_path(str(db_path))
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    DatabaseConnection._schema_initialized_paths.discard(normalized_path)
    DatabaseConnection._wal_initialized_paths.discard(normalized_path)

    original_create_tables = DatabaseConnection._create_tables
    call_count = 0
    count_lock = threading.Lock()

    def counted_create_tables(cls):
        nonlocal call_count
        with count_lock:
            call_count += 1
        return original_create_tables()

    monkeypatch.setattr(DatabaseConnection, "_create_tables", classmethod(counted_create_tables))

    errors: list[Exception] = []

    def worker():
        try:
            conn = DatabaseConnection.initialize(str(db_path))
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        except Exception as exc:
            errors.append(exc)
        finally:
            DatabaseConnection.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert errors == []
        assert call_count == 1
    finally:
        DatabaseConnection.close()
        DatabaseConnection._db_path = None
        DatabaseConnection._schema_initialized_paths.discard(normalized_path)
        DatabaseConnection._wal_initialized_paths.discard(normalized_path)
