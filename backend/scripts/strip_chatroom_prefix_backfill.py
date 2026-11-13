"""一次性清洗：群聊消息 username 前缀剥离 + sender 显示名回填。

背景（2026-11）：`_CHATROOM_PREFIX` 此前只识别 wxid_/纯数字两种前缀，
自定义微信号（`wwmilk:\\n内容`）未剥——内容带前缀入库污染词频/情感，
sender 停留在 username 形态。正则修复后新导入自然正确，本脚本清洗
存量库（重导不会更新已判重的行，必须就地 UPDATE）。

口径与导入侧完全一致（chatroom.parse_chatroom_message + 昵称映射），
仅处理群聊（@chatroom 会话）非本人消息。

衍生缓存不会因 UPDATE 自动失效，--apply 时本脚本按会话显式清理
（可再生缓存，删后由下次分析/索引全量重建）：
- sentiment_cache：主键 message_id 存在即命中，旧行是带前缀文本的错值；
- emoji_stats_v1_{id} 快照（settings）：指纹 count:id_sum:max_ts 对
  等量 UPDATE 有盲区，旧快照继续命中；
- RAG 五表 + rag_index_status：游标 last_message_id 只进不退，
  已扫过的旧行永不重扫——会话级删除使其回到 pending 全量重建。

用法：
    python backend/scripts/strip_chatroom_prefix_backfill.py [--apply]
        默认 dry-run 只统计；--apply 实际写库（应用运行中也可跑，
        WAL 短事务，busy_timeout 兜底锁竞争）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connection import get_db  # noqa: E402
from app.services.wechat.chatroom import (  # noqa: E402
    parse_chatroom_message,
    resolve_chatroom_display_name,
)


def load_name_map() -> dict:
    """wxid/username→显示名映射：账号密钥解密 contact.db（同导入链路）。"""
    import json

    from app.services.wechat.account_settings import build_custom_paths
    from app.services.wechat.db.v4.contact import ContactDBV4

    settings = json.loads(
        (Path(__file__).parent.parent / "data" / "settings.json").read_text("utf-8")
    )
    accounts = settings.get("wechat_accounts") or []
    acc = next((a for a in accounts if a.get("passphrase") or a.get("db_key")), None)
    if not acc:
        print("!! settings.json 无可用账号密钥，映射为空（仅剥前缀不改 sender）")
        return {}
    paths = build_custom_paths(acc) or {}
    wechat_dir, wxid = paths.get("wechat_dir"), paths.get("current_user")
    if not wechat_dir or not wxid:
        print("!! 账号缺 wechat_dir/wxid，映射为空")
        return {}
    contact_path = Path(wechat_dir) / wxid / "db_storage" / "contact" / "contact.db"
    if not contact_path.is_file():
        print(f"!! contact.db 不存在: {contact_path}")
        return {}
    key = acc.get("passphrase") or acc.get("db_key")
    db = ContactDBV4(str(contact_path), key, raw_keys=acc.get("raw_keys") or None)
    try:
        return db.get_display_name_map()
    finally:
        db.close()


def invalidate_derived_caches(con, gid: int) -> None:
    """有行的 UPDATE 才调用：会话级衍生缓存失效（见模块 docstring）。"""
    con.execute(
        "DELETE FROM sentiment_cache WHERE message_id IN"
        " (SELECT id FROM messages WHERE conversation_id = ?)",
        (gid,),
    )
    con.execute("DELETE FROM settings WHERE key = ?", (f"emoji_stats_v1_{gid}",))
    for table in ("rag_embeddings", "rag_fact_embeddings",
                  "rag_documents", "rag_facts", "rag_index_status"):
        con.execute(f"DELETE FROM {table} WHERE conversation_id = ?", (gid,))


def main() -> None:
    apply = "--apply" in sys.argv
    name_map = load_name_map()
    print(f"昵称映射 {len(name_map)} 条；模式: {'实跑' if apply else 'dry-run'}")

    con = get_db()
    con.execute("PRAGMA busy_timeout=10000")
    group_ids = [
        r[0]
        for r in con.execute(
            "SELECT id FROM conversations WHERE conversation_type = 'group'"
        )
    ]
    print(f"群聊会话 {len(group_ids)} 个")

    total = scanned = content_fixed = sender_fixed = 0
    known_ids = set(name_map) or None  # 前缀剥离白名单（同导入侧口径）
    for gid in group_ids:
        rows = con.execute(
            "SELECT id, content, sender FROM messages WHERE conversation_id = ?",
            (gid,),
        ).fetchall()
        updates: list[tuple[str, str, int]] = []
        for mid, content, sender in rows:
            total += 1
            text = content or ""
            new_sender = sender or ""
            new_content = text
            sid, stripped = parse_chatroom_message(text, known_ids=known_ids)
            if sid is not None:
                scanned += 1
                new_content = stripped
                new_sender = resolve_chatroom_display_name(sid, name_map=name_map)
            elif new_sender and name_map:
                new_sender = name_map.get(new_sender) or new_sender
            if new_content != text or new_sender != (sender or ""):
                if new_content != text:
                    content_fixed += 1
                if new_sender != (sender or ""):
                    sender_fixed += 1
                updates.append((new_sender, new_content, mid))
        if apply and updates:
            con.executemany(
                "UPDATE messages SET sender = ?, content = ? WHERE id = ?",
                updates,
            )
            # UPDATE 与缓存失效同事务：要么都生效要么都不
            invalidate_derived_caches(con, gid)
            con.commit()  # type: ignore[attr-defined]
        if updates:
            print(f"  会话 {gid}: 待更新 {len(updates)} 行")

    print(
        f"扫描 {total} 行 | 剥前缀 {scanned} | 内容修正 {content_fixed} | "
        f"sender 修正 {sender_fixed}"
    )
    if not apply:
        print("dry-run 未写库；加 --apply 执行")


if __name__ == "__main__":
    main()
