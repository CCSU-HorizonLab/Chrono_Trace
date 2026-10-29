"""V4 消息读取的 OperationalError 分流（补充#3）。

此前 get_messages 把一切 OperationalError 当「表不存在」吞掉——锁/
磁盘满/I/O 等运行时错误同样静默跳过，缺口不进 read_errors，ingest
水位无感知推进，缺口消息被增量永久跳过（绕过 W4 护栏）。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.wechat.db.v4.message import MessageDBV4


def _repo(monkeypatch, raise_exc):
    repo = MessageDBV4.__new__(MessageDBV4)
    repo.connections = [object()]
    repo._shard_msg_tables = [None]  # 预映射缺失：回退逐分片试查语义
    repo._table_columns_cache = {}
    repo.read_errors = []

    def _boom(conn, table_name, username, time_range, limit, *extra):
        raise raise_exc

    monkeypatch.setattr(MessageDBV4, "_query_messages_from_db", _boom)
    return repo


def test_no_s_table_error_still_silently_skipped(monkeypatch):
    """表不存在：维持试查语义，不记缺口。"""
    repo = _repo(monkeypatch, sqlite3.OperationalError("no such table: Msg_abc"))
    assert repo.get_messages("wxid_x") == []
    assert repo.read_errors == []


def test_runtime_operational_error_records_read_gap(monkeypatch):
    """锁/磁盘满等运行时错误：进 read_errors（水位护栏可感知）。"""
    repo = _repo(
        monkeypatch, sqlite3.OperationalError("database is locked")
    )
    assert repo.get_messages("wxid_x") == []
    assert len(repo.read_errors) == 1
    assert "database is locked" in repo.read_errors[0]


def test_name2id_missing_table_is_benign(monkeypatch):
    """无 Name2Id 表的结构变体分片：良性豁免，不得记缺口冻结水位。"""
    repo = MessageDBV4.__new__(MessageDBV4)
    repo.connections = [object()]
    repo.read_errors = []

    class _Conn:
        @staticmethod
        def execute(sql):
            raise sqlite3.OperationalError("no such table: Name2Id")

    repo.connections = [_Conn]

    # get_all_conversation_usernames 的游标在 conn.execute 上取得
    class _ConnInstance:
        def execute(self, sql):
            raise sqlite3.OperationalError("no such table: Name2Id")

    repo.connections = [_ConnInstance()]
    assert repo.get_all_conversation_usernames() == []
    assert repo.read_errors == []


def test_name2id_runtime_error_records_gap(monkeypatch):
    """锁/磁盘满等运行时错误：照旧记缺口（W4 水位护栏可感知）。"""

    class _ConnInstance:
        def execute(self, sql):
            raise sqlite3.OperationalError("database is locked")

    repo = MessageDBV4.__new__(MessageDBV4)
    repo.connections = [_ConnInstance()]
    repo.read_errors = []

    assert repo.get_all_conversation_usernames() == []
    assert len(repo.read_errors) == 1
    assert "database is locked" in repo.read_errors[0]
