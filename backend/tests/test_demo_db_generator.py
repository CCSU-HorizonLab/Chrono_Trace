"""虚构演示库生成器测试：确定性、落库一致性、应用可消费性。

生成即脱敏——本测试同时守住「不读真实库」的边界：生成器入参只有
seed/anchor/输出路径，产物里所有标识必须带 wxid_demo_ 前缀。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import sqlite3

import make_demo_db as gen  # noqa: E402

ANCHOR_TS = 1763121600  # 2026-11-14 20:00 (UTC+8)，固定锚点保证可复现


def _build(tmp_path, tag):
    db_path = tmp_path / tag / "chrono_trace.db"
    result = gen.build_demo_db(db_path, seed=20261116, anchor_ts=ANCHOR_TS)
    return db_path, result


def _fingerprint(db_path):
    conn = sqlite3.connect(str(db_path))
    msgs = conn.execute(
        "SELECT id, message_type, is_sender, COALESCE(content,''), timestamp,"
        " COALESCE(sender,'') FROM messages ORDER BY id").fetchall()
    convs = conn.execute(
        "SELECT id, username, display_name, message_count, created_at, updated_at"
        " FROM conversations ORDER BY id").fetchall()
    conn.close()
    return repr((msgs, convs))


def test_same_seed_anchor_reproducible(tmp_path):
    """同 seed+anchor 双跑产出逐条一致（复现包口径）。"""
    db1, r1 = _build(tmp_path, "a")
    db2, r2 = _build(tmp_path, "b")
    assert r1["messages"] == r2["messages"] and r1["messages"] > 30000
    assert _fingerprint(db1) == _fingerprint(db2)


def test_conversation_integrity(tmp_path):
    db_path, result = _build(tmp_path, "a")
    assert result["conversations"] == 8
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, username, conversation_type, message_count, created_at, updated_at"
        " FROM conversations").fetchall()
    assert {r[2] for r in rows} == {"private", "group"}
    for cid, username, _, count, created, updated in rows:
        assert username.startswith("wxid_demo_")
        real, mn, mx = conn.execute(
            "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM messages"
            " WHERE conversation_id=?", (cid,)).fetchone()
        assert real == count > 0
        assert (mn, mx) == (created, updated)
    conn.close()


def test_message_shapes(tmp_path):
    db_path, _ = _build(tmp_path, "a")
    conn = sqlite3.connect(str(db_path))
    # 文本消息内容非空；非文本 content 为 NULL
    empty = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE message_type=1"
        " AND (content IS NULL OR TRIM(content)='')").fetchone()[0]
    assert empty == 0
    nontext_with_content = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE message_type<>1 AND content IS NOT NULL"
    ).fetchone()[0]
    assert nontext_with_content == 0
    # 群聊消息 sender 非空且「我」的行 is_sender=1；单聊 sender 为 NULL
    bad_group = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id IN"
        " (SELECT id FROM conversations WHERE conversation_type='group')"
        " AND (sender IS NULL OR sender='')").fetchone()[0]
    assert bad_group == 0
    me_in_group = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id IN"
        " (SELECT id FROM conversations WHERE conversation_type='group')"
        " AND sender='我' AND is_sender<>1").fetchone()[0]
    assert me_in_group == 0
    single_sender = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id IN"
        " (SELECT id FROM conversations WHERE conversation_type='private')"
        " AND sender IS NOT NULL").fetchone()[0]
    assert single_sender == 0
    # 时间戳严格递增（去重/边界逻辑依赖）
    flat = conn.execute(
        "SELECT COUNT(*) FROM ("
        " SELECT timestamp - LAG(timestamp) OVER (PARTITION BY conversation_id ORDER BY id) AS d"
        " FROM messages) WHERE d IS NOT NULL AND d <= 0").fetchone()[0]
    assert flat == 0
    conn.close()


def test_decision_language_present_both_sides(tmp_path):
    """决策语言双侧在场——决策风格通道 B 的信号源（截图页需要非空卡）。"""
    db_path, _ = _build(tmp_path, "a")
    conn = sqlite3.connect(str(db_path))
    like = ("content LIKE '%帮我看看%' OR content LIKE '%帮我参谋%'"
            " OR content LIKE '%对比了%' OR content LIKE '%调研%'")
    for side in (0, 1):
        n = conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE is_sender={side} AND ({like})"
        ).fetchone()[0]
        assert n > 10, f"side={side} 决策语言样本不足: {n}"
    conn.close()


def test_demo_db_consumable_by_app(tmp_path):
    """应用自身能直接消费 demo 库（schema 兼容的最强断言）。"""
    from app.db.connection import DatabaseConnection
    from app.services.analysis.analysis_service import AnalysisService

    db_path, _ = _build(tmp_path, "a")
    DatabaseConnection.initialize(str(db_path))
    try:
        result = AnalysisService().get_conversation_list("")
        assert result["ok"]
        assert len(result["conversations"]) == 8
        names = {c["name"] for c in result["conversations"]}
        assert "陈工-山南" in names  # 备注名优先显示
    finally:
        DatabaseConnection.close()


def test_demo_settings_isolated():
    """demo settings 只含演示账号：无密钥、无真实 wechat_dir。"""
    import json
    from pathlib import Path

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "settings.json"
        gen.write_demo_settings(p, ANCHOR_TS)
        data = json.loads(p.read_text(encoding="utf-8"))
        acc = data["wechat_accounts"][0]
        assert acc["wxid"] == gen.DEMO_ACCOUNT_WXID
        assert acc["db_key"] == "" and acc["wechat_dir"] == ""
