"""存量「[压缩消息]」占位修复——zstd 真解压找回真实长文本（一次性）。

背景：content_codec 2026-11 前无 zstd 解压，type=1 压缩通道消息（29~352
字长文本，实测占 4.7%）入库为占位符。本库已装 zstandard 并改
decode_message_content 真解压（导入/监听新消息自动生效），本脚本把
存量占位行从解密缓存分片库解压回填。

对齐口径：messages(talker, local_id, timestamp) ↔ Msg_{md5(talker)} 表
(local_id, create_time)（与 ingest/reader 同源，见 db/v4/message.py:430-436）。

失效联动（UPDATE 不触发 CASCADE，显式精准清理）：
  messages.content            ← 解压文本
  sentiment_cache             ← 修复行删除（旧占位的 neu 记录作废）
  message_preprocessed        ← 修复行删除（清洗缓存重建）
  embedding_cache             ← 不动（sha1(text) 键控，新文本自动 miss）

用法：python repair_compressed_messages.py [--dry-run]
"""
import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.wechat.content_codec import decode_message_content  # noqa: E402

CHRONO_DB = backend_dir / "data" / "chrono_trace.db"
SHARD_DBS = sorted((backend_dir / "data" / "temp" / "import_cache").glob("message_*.dec.db"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    chrono = sqlite3.connect(str(CHRONO_DB))
    chrono.row_factory = sqlite3.Row
    pending = chrono.execute(
        "SELECT id, talker, local_id, timestamp FROM messages "
        "WHERE content = '[压缩消息]' AND local_id IS NOT NULL"
    ).fetchall()
    print(f"[chrono] 待修复占位行 {len(pending)}")

    if not SHARD_DBS:
        print(f"[错误] 解密分片缓存不存在：{SHARD_DBS}（需先完成一次导入）")
        return 1

    # 分片表名索引：table → [(shard_path, conn)]
    shards = [(p, sqlite3.connect(f"file:{p}?mode=ro", uri=True)) for p in SHARD_DBS]
    table_index: dict[str, list] = {}
    for path, conn in shards:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
        for n in names:
            table_index.setdefault(n, []).append((path, conn))
    print(f"[分片] {len(shards)} 个分片，Msg_ 表 {len(table_index)} 张")

    # 按-talker 分组拉压缩行（只拉需要的表）
    talkers = {r["talker"] for r in pending}
    blob_map: dict[tuple[str, int, int], str] = {}   # (talker, local_id, create_time) → 文本
    n_hit_tables = 0
    for talker in talkers:
        table = f"Msg_{hashlib.md5(talker.encode('utf-8')).hexdigest()}"
        for path, conn in table_index.get(table, []):
            rows = conn.execute(
                f"SELECT local_id, create_time, message_content FROM {table} "
                f"WHERE typeof(message_content)='blob' "
                f"AND (local_type & 4294967295) = 1 AND length(message_content) > 8"
            ).fetchall()
            if rows:
                n_hit_tables += 1
            for local_id, create_time, blob in rows:
                text = decode_message_content(bytes(blob), 1)
                if text and text != "[压缩消息]":
                    blob_map[(talker, local_id, create_time)] = text
    print(f"[解压] 分片中压缩文本 {len(blob_map)} 条（命中表 {n_hit_tables}）")

    fixed, missed = 0, 0
    fix_ids: list[int] = []
    for row in pending:
        text = blob_map.get((row["talker"], row["local_id"], row["timestamp"]))
        if not text:
            missed += 1
            continue
        fixed += 1
        fix_ids.append(row["id"])
        if not args.dry_run:
            chrono.execute("UPDATE messages SET content = ? WHERE id = ?", (text, row["id"]))

    if not args.dry_run and fix_ids:
        ph = ",".join("?" * len(fix_ids))
        chrono.execute(f"DELETE FROM sentiment_cache WHERE message_id IN ({ph})", fix_ids)
        chrono.execute(f"DELETE FROM message_preprocessed WHERE message_id IN ({ph})", fix_ids)
        chrono.commit()
    print(f"[结果] {'（dry-run）' if args.dry_run else ''}修复 {fixed} / 未找回 {missed}"
          f"（分片缺表或对不上时间戳的保留占位）")
    for path, conn in shards:
        conn.close()
    chrono.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
