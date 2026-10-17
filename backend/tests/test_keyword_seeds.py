"""关键词库种子扩充校验（schema.sql 建库脚本内联种子）。"""

import sqlite3
import sys
from collections import Counter
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

SCHEMA = backend_root / "app" / "db" / "schema.sql"

# 每类种子下限：扩充后基线（曾为每类 10/holiday 16）
EXPECTED_MIN = {
    "positive": 25, "negative": 25, "empathy": 25,
    "soothing": 25, "privacy": 25, "holiday": 30, "nickname": 25,
}


def _fresh_seeds():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    rows = conn.execute(
        "SELECT category, keyword, is_custom FROM keyword_libraries"
    ).fetchall()
    conn.close()
    return rows


def test_seed_counts_meet_baseline():
    rows = _fresh_seeds()
    counts = Counter(cat for cat, _, _ in rows)
    for category, minimum in EXPECTED_MIN.items():
        assert counts[category] >= minimum, (category, counts[category])
    assert all(custom == 0 for _, _, custom in rows)


def test_seeds_unique_and_nonempty():
    rows = _fresh_seeds()
    pairs = [(cat, kw) for cat, kw, _ in rows]
    assert len(pairs) == len(set(pairs))
    assert all(kw.strip() for _, kw in pairs)


def test_seed_expansion_reaches_existing_db_on_restart():
    """建库脚本每次启动重跑：已有库靠 INSERT OR IGNORE 自动补齐新种子"""
    conn = sqlite3.connect(":memory:")
    sql = SCHEMA.read_text(encoding="utf-8")
    conn.executescript(sql)
    before = conn.execute("SELECT COUNT(*) FROM keyword_libraries").fetchone()[0]
    conn.executescript(sql)  # 模拟下一次启动
    after = conn.execute("SELECT COUNT(*) FROM keyword_libraries").fetchone()[0]
    assert before == after
