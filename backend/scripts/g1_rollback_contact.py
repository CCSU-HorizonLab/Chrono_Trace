"""按联系人回滚:安全指标回退时切回旧文档读侧或 inherit,不删任何数据。

用法(仓库根目录)::

    # 查看某账号下各会话的当前读侧模式
    python backend/scripts/g1_rollback_contact.py --account wxid_xxx --list

    # 把指定会话切回旧文档读侧(事实链路停用,文档链路照旧)
    python backend/scripts/g1_rollback_contact.py --account wxid_xxx --conversation 91 --mode documents

    # 恢复跟随全局设置
    python backend/scripts/g1_rollback_contact.py --account wxid_xxx --conversation 91 --mode inherit

    # 彻底停用该联系人的 RAG 检索(保留全部事实/索引/审计数据)
    python backend/scripts/g1_rollback_contact.py --account wxid_xxx --conversation 91 --disable

契约(上游文档第五节):失败回滚不删除事实、策略、发送清单和诊断日志;
本脚本只改 ``rag_index_status.fact_read_mode / enabled``,可随时再用
``--mode inherit``/``--enable`` 恢复。默认需要 ``--yes`` 才落库,
否则只打印将要执行的变更(dry-run)。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VALID_MODES = ("inherit", "facts", "documents")


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def list_conversations(db_path: str, account_wxid: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT c.id, c.display_name, c.username, c.message_count,
               s.fact_read_mode, s.enabled, s.status AS index_status
        FROM conversations c
        LEFT JOIN rag_index_status s
          ON s.account_wxid = c.account_wxid AND s.conversation_id = c.id
        WHERE c.account_wxid = ? AND c.is_deleted = 0
        ORDER BY c.message_count DESC
        """,
        (account_wxid,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def resolve_conversation(db_path: str, account_wxid: str, conversation_id: int | None, display_name: str) -> int:
    if conversation_id is not None:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id FROM conversations WHERE account_wxid = ? AND id = ? AND is_deleted = 0",
            (account_wxid, conversation_id),
        ).fetchone()
        conn.close()
        if not row:
            raise SystemExit(f"[Rollback] 会话 {conversation_id} 不属于账号 {account_wxid},拒绝操作")
        return int(row["id"])
    if display_name:
        rows = [r for r in list_conversations(db_path, account_wxid) if r["display_name"] == display_name]
        matches = {int(r["id"]) for r in rows}
        if len(matches) == 1:
            return matches.pop()
        if len(matches) > 1:
            raise SystemExit(f"[Rollback] 显示名 {display_name!r} 命中 {len(matches)} 个会话({sorted(matches)}),请用 --conversation 显式指定")
    raise SystemExit("[Rollback] 需要 --conversation 或唯一的 --display-name")


def apply_rollback(db_path: str, account_wxid: str, conversation_id: int, *, mode: str, disable: bool, enable: bool, yes: bool) -> None:
    from app.db.connection import DatabaseConnection
    from app.services.realtime.rag.store import RagStore

    if not yes:
        actions = []
        if disable:
            actions.append("enabled=0(停用该联系人 RAG 检索)")
        if enable:
            actions.append("enabled=1")
        if mode:
            actions.append(f"fact_read_mode={mode}")
        print(f"[Rollback] dry-run:将对 {account_wxid} / 会话 {conversation_id} 执行: {'; '.join(actions) or '(无变更)'}")
        print("[Rollback] 加 --yes 落库")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    current = store.get_status(account_wxid, conversation_id) or {}
    store.upsert_status(
        account_wxid,
        conversation_id,
        status=str(current.get("status") or "ready"),
        fact_read_mode=mode or None,
        enabled=False if disable else (True if enable else None),
    )
    conn.commit()
    conn.close()
    after = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT fact_read_mode, enabled FROM rag_index_status WHERE account_wxid = ? AND conversation_id = ?",
        (account_wxid, conversation_id),
    ).fetchone()
    conn.close()
    if row:
        after = dict(row)
    print(f"[Rollback] 已回滚 {account_wxid} / 会话 {conversation_id}: fact_read_mode={after.get('fact_read_mode')}, enabled={after.get('enabled')}")
    print("[Rollback] 事实/策略/发送清单/诊断日志全部保留;恢复用 --mode inherit 或 --enable")


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "chrono_trace.db"))
    parser.add_argument("--account", required=True, help="account_wxid")
    parser.add_argument("--conversation", type=int, default=None, help="会话 ID")
    parser.add_argument("--display-name", default="", help="显示名(仅唯一命中时可用)")
    parser.add_argument("--mode", choices=VALID_MODES, default="", help="documents=旧文档读侧;inherit=跟随全局")
    parser.add_argument("--disable", action="store_true", help="停用该联系人 RAG 检索")
    parser.add_argument("--enable", action="store_true", help="重新启用")
    parser.add_argument("--list", action="store_true", help="列出会话与当前模式")
    parser.add_argument("--yes", action="store_true", help="实际落库(缺省 dry-run)")
    args = parser.parse_args()

    if args.list:
        rows = list_conversations(args.db, args.account)
        print(f"[Rollback] {args.account}: {len(rows)} 个会话")
        for row in rows[:50]:
            print(
                f"  #{row['id']:<4} {str(row['display_name'])[:20]:<20} "
                f"msgs={row['message_count'] or 0:<6} fact_read_mode={row['fact_read_mode'] or 'inherit'} "
                f"enabled={1 if row['enabled'] is None else row['enabled']} index={row['index_status'] or '-'}"
            )
        return 0

    if not (args.mode or args.disable or args.enable):
        print("[Rollback] 未指定动作:用 --mode documents/inherit、--disable 或 --enable")
        return 1

    conversation_id = resolve_conversation(args.db, args.account, args.conversation, args.display_name)
    apply_rollback(
        args.db, args.account, conversation_id,
        mode=args.mode, disable=args.disable, enable=args.enable, yes=args.yes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
