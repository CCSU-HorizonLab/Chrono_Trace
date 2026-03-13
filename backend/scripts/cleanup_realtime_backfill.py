import argparse
import sqlite3
from pathlib import Path


def resolve_db_path(db_path: str | None) -> Path:
    if db_path:
        return Path(db_path).resolve()
    return (Path(__file__).resolve().parent.parent / "data" / "chrono_trace.db").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete realtime_backfill test data for a conversation.")
    parser.add_argument("--conversation-id", type=int, required=True, help="Target conversation_id")
    parser.add_argument("--db", type=str, default=None, help="Optional chrono_trace.db path")
    parser.add_argument("--dry-run", action="store_true", help="Only show rows that would be deleted")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT id, content, timestamp, created_at
        FROM messages
        WHERE conversation_id = ?
          AND source = 'realtime_backfill'
        ORDER BY id DESC
        """,
        (args.conversation_id,),
    ).fetchall()

    print(f"db={db_path}")
    print(f"conversation_id={args.conversation_id}")
    print(f"realtime_backfill_rows={len(rows)}")

    for row in rows[:20]:
        print(
            f"id={row['id']} ts={row['timestamp']} created_at={row['created_at']} "
            f"content={row['content']!r}"
        )

    if args.dry_run:
        print("dry_run=true, no rows deleted")
        return 0

    conn.execute(
        """
        DELETE FROM messages
        WHERE conversation_id = ?
          AND source = 'realtime_backfill'
        """,
        (args.conversation_id,),
    )
    conn.commit()
    print(f"deleted={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
