"""增量分析真实库实测：冷跑→暖跑→增量→金标准对照（绝不碰原库）。

用法：
    python verify_incremental_analysis.py --db-source <生产库路径> \
        --conversation-id <会话id> [--append-synthetic 30]

流程（全部在临时副本上执行）：
  1. 复制生产库（含 -wal/-shm）到临时目录；
  2. 冷跑：清空全部分析缓存后跑「特征提取+好感度」，逐步计时；
  3. 暖跑：新进程语义（清内存缓存）再跑，计时 + 断言与冷跑产物 diff 为空；
  4. 增量：追加 N 条合成尾部消息（复刻导入语义）→ 再跑，计时；
  5. 金标准：另一副本全清冷跑同样消息集 → 与步骤 4 逐表 row-diff；
  6. 输出耗时表；diff 非空时退出码非 0。

同设备同模型下浮点列预期精确相等（float32 往返 bit 级一致）。
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))


def copy_database(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, dst.with_name(dst.name + suffix))
    return dst


def clear_analysis_state(db_path: Path) -> None:
    """全清冷跑准备：分析四表 + 三级缓存 + settings 两个缓存行。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for table in (
        "sessions", "response_times", "initiative_stats", "word_counts",
        "speech_units", "interaction_pairs",
        "sentiment_cache", "message_preprocessed", "embedding_cache",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.execute(
        "DELETE FROM settings WHERE key LIKE 'preprocessing_stats_v2_%' "
        "OR key LIKE 'affinity_scores_%'"
    )
    conn.commit()
    conn.close()


def snapshot_tables(db_path: Path, conversation_id: int) -> dict:
    """逐表快照（自增 id / created_at / last_updated 忽略，浮点精确比较）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    queries = {
        "sessions": "SELECT start_time, end_time, message_count, initiator FROM sessions WHERE conversation_id = ? ORDER BY start_time",
        "speech_units": "SELECT message_ids, sender, first_message_timestamp, last_message_timestamp, message_count FROM speech_units WHERE conversation_id = ? ORDER BY first_message_timestamp",
        "initiative_stats": "SELECT total_sessions, user_initiated_sessions, other_initiated_sessions, initiative_rate FROM initiative_stats WHERE conversation_id = ?",
        "word_counts": "SELECT user_char_count, other_char_count, char_ratio FROM word_counts WHERE conversation_id = ? AND session_id IS NULL",
    }
    snap = {}
    for name, sql in queries.items():
        snap[name] = [tuple(r) for r in conn.execute(sql, (conversation_id,))]

    def unit_anchor(unit_id):
        row = conn.execute(
            "SELECT first_message_timestamp, message_ids FROM speech_units WHERE id = ?",
            (unit_id,),
        ).fetchone()
        return tuple(row) if row else None

    pairs = []
    for r in conn.execute(
        "SELECT from_speech_unit_id, to_speech_unit_id, time_gap, semantic_similarity, "
        "from_polarity, to_polarity FROM interaction_pairs WHERE conversation_id = ?",
        (conversation_id,),
    ):
        pairs.append((unit_anchor(r[0]), unit_anchor(r[1]), r[2], r[3], r[4], r[5]))
    snap["interaction_pairs"] = sorted(pairs, key=repr)

    def msg_anchor(mid):
        row = conn.execute(
            "SELECT timestamp FROM messages WHERE id = ?", (mid,)
        ).fetchone()
        return row[0] if row else None

    rt = []
    for r in conn.execute(
        "SELECT sent_message_id, reply_message_id, response_time_seconds, is_abnormal "
        "FROM response_times WHERE conversation_id = ?",
        (conversation_id,),
    ):
        rt.append((msg_anchor(r[0]), msg_anchor(r[1]), r[2], r[3]))
    snap["response_times"] = sorted(rt, key=repr)
    conn.close()
    return snap


def run_analysis(db_path: Path, conversation_id: int) -> float:
    """在新进程语义下跑完整两阶段，返回耗时（秒）。"""
    import subprocess

    script = (
        "import sys, time; sys.path.insert(0, '.');"
        "from app.db.connection import DatabaseConnection;"
        f"DatabaseConnection.initialize(r'{db_path}');"
        "from app.services.analysis.feature_extraction_service import FeatureExtractionService;"
        "from app.services.analysis.affinity_analysis_service import AffinityAnalysisService;"
        f"t0=time.time(); FeatureExtractionService().extract_features({conversation_id});"
        f"AffinityAnalysisService().analyze({conversation_id}, force_reanalyze=True);"
        "print(time.time()-t0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("分析子进程失败")
    return float(result.stdout.strip().splitlines()[-1])


def append_synthetic(db_path: Path, conversation_id: int, count: int) -> None:
    """追加合成尾部消息（复刻导入语义：OR IGNORE + touched 打脏 + 计数刷新）。"""
    conn = sqlite3.connect(db_path)
    max_ts = conn.execute(
        "SELECT MAX(timestamp) FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0] or 1_700_000_000
    max_local = conn.execute(
        "SELECT MAX(local_id) FROM messages WHERE conversation_id = ? AND local_id IS NOT NULL",
        (conversation_id,),
    ).fetchone()[0] or 0
    for i in range(count):
        conn.execute(
            """
            INSERT OR IGNORE INTO messages
            (conversation_id, local_id, talker, is_sender, message_type,
             content, timestamp, source, created_at)
            VALUES (?, ?, 'synthetic', ?, 1, ?, ?, 'long', ?)
            """,
            (
                conversation_id, max_local + i + 1, i % 2,
                f"合成增量消息 {i}，用于验证增量分析正确性。", max_ts + 300 + i * 60,
                int(time.time()),
            ),
        )
    total = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
    ).fetchone()[0]
    conn.execute(
        "UPDATE conversations SET message_count = ?, analysis_stale = 1 WHERE id = ?",
        (total, conversation_id),
    )
    conn.commit()
    conn.close()


def diff_snapshots(a: dict, b: dict, atol: float = 0.0) -> list:
    """逐表 row-diff。atol=0 精确相等（同一初始编码的暖跑/增量路径）；
    跨独立冷跑对照需 atol≈1e-6——torch 编码结果随批组合有 float32 epsilon
    级噪声（实测 ~1.2e-7），远低于任何阈值语义，非缓存缺陷。
    """
    problems = []
    for name in a:
        rows_a, rows_b = a[name], b[name]
        if len(rows_a) != len(rows_b):
            problems.append(f"{name}: 行数 {len(rows_a)} != {len(rows_b)}")
            continue
        for i, (ra, rb) in enumerate(zip(rows_a, rows_b)):
            for j, (va, vb) in enumerate(zip(ra, rb)):
                if isinstance(va, float) or isinstance(vb, float):
                    if va != vb and abs((va or 0) - (vb or 0)) > atol:
                        problems.append(f"{name}[{i}].col{j}: {va!r} != {vb!r}")
                elif va != vb:
                    problems.append(f"{name}[{i}].col{j}: {va!r} != {vb!r}")
    return problems


def main():
    parser = argparse.ArgumentParser(description="增量分析真实库实测")
    parser.add_argument("--db-source", required=True, help="生产库路径（只读复制，绝不修改）")
    parser.add_argument("--conversation-id", type=int, required=True)
    parser.add_argument("--append-synthetic", type=int, default=30, help="增量追加的合成消息数")
    args = parser.parse_args()

    src = Path(args.db_source).resolve()
    if not src.exists():
        print(f"[!] 数据库不存在: {src}")
        sys.exit(1)

    timings = {}
    with tempfile.TemporaryDirectory(prefix="chrono_verify_") as tmp:
        tmp = Path(tmp)

        # 1) 主副本：冷跑
        main_db = copy_database(src, tmp / "main")
        from app.db.connection import DatabaseConnection

        clear_analysis_state(main_db)
        timings["① 冷跑（全清）"] = run_analysis(main_db, args.conversation_id)
        cold_snap = snapshot_tables(main_db, args.conversation_id)

        # 2) 暖跑（子进程 = 天然新进程，L2 在库里）
        timings["② 暖跑（跨进程）"] = run_analysis(main_db, args.conversation_id)
        warm_snap = snapshot_tables(main_db, args.conversation_id)
        warm_diff = diff_snapshots(cold_snap, warm_snap)

        # 3) 增量追加后重跑
        append_synthetic(main_db, args.conversation_id, args.append_synthetic)
        timings["③ 增量后重跑"] = run_analysis(main_db, args.conversation_id)
        incremental_snap = snapshot_tables(main_db, args.conversation_id)

        # 4) 金标准：同终态消息集全清冷跑
        gold_db = copy_database(main_db, tmp / "gold")
        clear_analysis_state(gold_db)
        timings["④ 金标准冷跑"] = run_analysis(gold_db, args.conversation_id)
        golden_snap = snapshot_tables(gold_db, args.conversation_id)

        gold_diff = diff_snapshots(golden_snap, incremental_snap, atol=1e-6)

    print("\n" + "=" * 56)
    print("    增量分析实测报告")
    print("=" * 56)
    for stage, seconds in timings.items():
        print(f"  {stage:<16} {seconds:8.2f}s")
    speedup = timings["① 冷跑（全清）"] / max(timings["③ 增量后重跑"], 0.001)
    print(f"\n  增量/冷跑 加速比: {speedup:.1f}x")
    print(f"  暖跑 vs 冷跑 diff: {'为空 ✓' if not warm_diff else warm_diff[:5]}")
    print(f"  增量 vs 金标准 diff: {'为空 ✓' if not gold_diff else gold_diff[:5]}")

    if warm_diff or gold_diff:
        print("\n[!] 等价性校验失败")
        sys.exit(1)
    print("\n[+] 全部等价性校验通过")


if __name__ == "__main__":
    main()
