"""外键约束开启验证（W5）。

schema.sql 的 21 个 FOREIGN KEY ... ON DELETE CASCADE 此前从未生效
（连接未开 PRAGMA foreign_keys）：脏 conversation_id 静默入库成孤儿行。
开启后插入受约束、级联生效。全库无删父行的代码路径——级联不改变现有
删除行为，只补上完整性。
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.db.connection import DatabaseConnection


@pytest.fixture
def test_db(tmp_path):
    DatabaseConnection.close()
    DatabaseConnection._db_path = None
    conn = DatabaseConnection.initialize(str(tmp_path / "chrono_fk.db"))
    yield conn
    DatabaseConnection.close()
    DatabaseConnection._db_path = None


def test_foreign_keys_pragma_enabled(test_db):
    """连接必须开 PRAGMA foreign_keys = ON（每连接独立开关）。"""
    assert test_db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_orphan_insert_rejected(test_db):
    """子行指向不存在的父行：插入被拒（此前静默入库成孤儿行）。"""
    # messages.conversation_id REFERENCES conversations(id)（schema 71 行）
    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            "INSERT INTO messages (conversation_id, talker, is_sender,"
            " message_type, content, timestamp, created_at)"
            " VALUES (999999, 'wxid_x', 0, 1, 'hi', ?, ?)",
            (int(time.time()), int(time.time())),
        )


def test_valid_insert_accepted_and_cascade_works(test_db):
    """正常父子插入不受影响；级联删除生效。"""
    now = int(time.time())
    cur = test_db.execute(
        "INSERT INTO conversations (account_wxid, username, display_name,"
        " platform, created_at, updated_at) VALUES ('acct', 'wxid_x', 'X',"
        " 'wechat', ?, ?)",
        (now, now),
    )
    conv_id = cur.lastrowid
    test_db.execute(
        "INSERT INTO messages (conversation_id, talker, is_sender,"
        " message_type, content, timestamp, created_at)"
        " VALUES (?, 'wxid_x', 0, 1, 'hi', ?, ?)",
        (conv_id, now, now),
    )
    assert test_db.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)
    ).fetchone()[0] == 1

    # 级联：删父行 → 子行随之消失（ON DELETE CASCADE 生效）
    test_db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    assert test_db.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)
    ).fetchone()[0] == 0
