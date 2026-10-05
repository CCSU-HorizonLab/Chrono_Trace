"""微信V4数据导入服务 (仅支持4.0+版本)"""
import json
import os
import time
import logging
from typing import Dict, Any, Optional, Callable
from .path_finder import WeChatPathFinder
from .db_decryptor_v2 import WeChatDBDecryptor  # V1 已退役，V2 尾部同名兼容类
from .db.v4.contact import ContactDBV4
from .db.v4.message import MessageDBV4
from .contact_filters import EXCLUDED_CONTACT_USERNAMES, is_excluded_contact_username
from ...db.connection import get_db
from ..analysis.preprocessing import PreprocessingService


logger = logging.getLogger(__name__)
class WeChatIngestService:
    """微信V4数据导入服务"""

    def __init__(self):
        pass  # get_db() removed for thread safety
        self.preprocessor = PreprocessingService()

    def get_wechat_paths(self) -> Dict[str, Any]:
        """
        获取微信数据库路径信息(供前端展示)

        Returns:
            dict: {
                "ok": True,
                "data": {
                    "wechat_dir": "...",
                    "current_user": "wxid_xxx",
                    "databases": {...}
                }
            }
        """
        try:
            paths = WeChatPathFinder.find_all_wechat_dbs()

            if not paths:
                # 4.0+ 未命中：探测 3.9 旧版结构，命中则引导用户升级微信
                legacy_v3 = WeChatPathFinder.find_legacy_v3_info()
                if legacy_v3:
                    return {
                        "ok": False,
                        "code": "legacy_wechat_v3",
                        "error": "检测到旧版微信 3.9 数据目录，请将微信升级到 4.0 及以上版本后重试",
                        "v3": legacy_v3,
                    }
                return {
                    "ok": False,
                    "error": "未找到微信数据目录,请确保微信已安装并登录"
                }

            return {
                "ok": True,
                "data": paths
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"查找微信路径失败: {str(e)}"
            }

    def verify_key(self, db_key: str, custom_paths: Optional[Dict] = None,
                   key_type: str = "passphrase", raw_keys: Optional[Dict] = None) -> Dict[str, Any]:
        """
        验证密钥是否有效

        Args:
            db_key: 32位hex密钥
            key_type: "passphrase"（默认）或 "raw"（Windows 只读扫描产物）
            raw_keys: key_type="raw" 时的 {salt_hex: enc_key_hex} 映射

        Returns:
            dict: {"ok": bool, "error": str}
        """
        try:
            # 查找数据库路径，优先使用前端已确认的目录
            paths = self.resolve_wechat_paths(custom_paths)
            if not paths:
                return {"ok": False, "error": "未找到微信数据库"}

            if key_type == "raw" and raw_keys:
                return self._verify_raw_keys(paths, raw_keys)

            # 选择第一个消息库进行验证
            message_dbs = paths["databases"]["message"]
            if not message_dbs:
                # 尝试联系人库
                contact_db = paths["databases"].get("contact")
                if contact_db:
                    is_valid = WeChatDBDecryptor.verify_key(contact_db, db_key)
                    return {"ok": True} if is_valid else {"ok": False, "error": "密钥错误"}
                return {"ok": False, "error": "未找到任何数据库"}

            # 验证密钥
            is_valid = WeChatDBDecryptor.verify_key(message_dbs[0], db_key)

            if is_valid:
                return {"ok": True}
            else:
                return {"ok": False, "error": "密钥错误,无法解密数据库"}

        except Exception as e:
            return {"ok": False, "error": f"验证失败: {str(e)}"}

    def _verify_raw_keys(self, paths: Dict[str, Any], raw_keys: Dict[str, str]) -> Dict[str, Any]:
        """Windows 只读扫描产物验证：按库 salt 逐一直取 raw key 做 HMAC 校验。"""
        from .db_decryptor_v2 import WeChatDBDecryptorV2

        databases = paths.get("databases") or {}
        targets: list[str] = list(databases.get("message") or [])
        targets += list(databases.get("contact") or [])
        if not targets:
            return {"ok": False, "error": "未找到任何数据库"}

        dec = WeChatDBDecryptorV2()
        dec.set_raw_key_map(raw_keys)
        verified = 0
        for db_path in targets:
            try:
                with open(db_path, "rb") as f:
                    page1 = f.read(4096)
                if len(page1) == 4096 and dec.validate_key(page1, b"\x00" * 32):
                    verified += 1
            except OSError:
                continue
        if verified:
            return {"ok": True}
        return {
            "ok": False,
            "error": "raw 密钥映射无法验证任何数据库（salt 不匹配或微信已换密钥）",
        }

    def resolve_wechat_paths(self, custom_paths: Optional[Dict] = None) -> Dict[str, Any]:
        """Resolve the active WeChat data paths for import and incremental checks."""
        if custom_paths and custom_paths.get("wechat_dir") and custom_paths.get("current_user"):
            wechat_dir = custom_paths["wechat_dir"]
            wxid = custom_paths["current_user"]
            databases = WeChatPathFinder.find_databases(wxid, wechat_dir)
            return {
                "wechat_dir": wechat_dir,
                "current_user": wxid,
                "account_wxid": str(custom_paths.get("account_wxid") or wxid),
                "databases": databases
            }

        paths = WeChatPathFinder.find_all_wechat_dbs()
        if not paths:
            raise Exception("WeChat database path not found")
        paths["account_wxid"] = str(paths.get("account_wxid") or paths.get("current_user") or "")
        return paths

    def build_file_size_snapshot(self, custom_paths: Optional[Dict] = None) -> Dict[str, Any]:
        """Collect current file sizes for WeChat database files and WAL sidecars."""
        paths = self.resolve_wechat_paths(custom_paths)
        databases = paths.get("databases") or {}
        snapshot_files = []
        seen_paths = set()

        def _add_file(file_path: Optional[str], kind: str):
            if not file_path:
                return
            normalized = os.path.normpath(file_path)
            if normalized in seen_paths:
                return
            seen_paths.add(normalized)
            if not os.path.exists(normalized):
                return

            snapshot_files.append({
                "path": normalized,
                "kind": kind,
                "size": os.path.getsize(normalized)
            })

            wal_path = normalized + "-wal"
            if os.path.exists(wal_path):
                snapshot_files.append({
                    "path": wal_path,
                    "kind": f"{kind}_wal",
                    "size": os.path.getsize(wal_path)
                })

        for message_db in databases.get("message") or []:
            _add_file(message_db, "message")
        _add_file(databases.get("contact"), "contact")
        _add_file(databases.get("session"), "session")

        return {
            "wechat_dir": paths.get("wechat_dir"),
            "current_user": paths.get("current_user"),
            "account_wxid": paths.get("account_wxid") or paths.get("current_user"),
            "files": snapshot_files,
            "total_size": sum(item["size"] for item in snapshot_files),
            "captured_at": int(time.time())
        }

    def import_wechat_data(
        self,
        db_key: str,
        options: Optional[Dict] = None,
        custom_paths: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        raw_keys: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        完整的微信数据导入流程

        Args:
            db_key: 32位hex密钥
            options: 导入选项 {
                "import_contacts": bool,    # 是否导入联系人
                "import_messages": bool,    # 是否导入消息
                "limit": int                # 消息数量限制(0=全部)
            }
            custom_paths: 自定义路径(如果提供则使用,否则自动检测)
            progress_callback: 进度回调 callback(status, current, total)

        Returns:
            dict: {
                "ok": True,
                "stats": {
                    "contacts": 120,
                    "messages": 15230,
                    "conversations": 45
                },
                "warnings": [...]
            }
        """
        options = options or {}
        import_contacts = options.get("import_contacts", True)
        import_messages = options.get("import_messages", True)
        limit = options.get("limit", 0)
        # 水位增量：bridge 注入账号当前水位；force_full 显式忽略走全量（逃生门）
        force_full = bool(options.get("force_full"))
        watermark_in = 0 if force_full else int(options.get("import_watermark_ts") or 0)

        warnings = []
        stats = {
            "contacts": 0,
            "messages": 0,
            "conversations": 0,
            "inserted_contacts": 0,
            "inserted_messages": 0,
            "skipped": 0
        }

        import_id = None
        account_wxid = ""

        try:
            # 1. 获取数据库路径
            if progress_callback:
                progress_callback("查找数据库路径...", 0, 100)

            logger.info("\n[DEBUG] === 开始导入流程 ===")
            logger.debug(f"[DEBUG] custom_paths: {custom_paths}")

            paths = self.resolve_wechat_paths(custom_paths)
            wxid = paths["current_user"]
            account_wxid = str(paths.get("account_wxid") or wxid)
            databases = paths["databases"]
            import_id = self._create_import_record(account_wxid)

            logger.debug(f"[DEBUG] wxid: {wxid}")
            logger.debug(f"[DEBUG] databases: {databases}")

            # 2. 导入联系人
            imported_contacts = False

            logger.debug(f"\n[DEBUG] import_contacts={import_contacts}, has contact db={databases.get('contact')}")
            if import_contacts and databases.get("contact"):
                if progress_callback:
                    progress_callback("导入联系人...", 10, 100)

                contact_count = self._import_contacts_v4(
                    databases["contact"],
                    db_key,
                    account_wxid,
                    raw_keys=raw_keys,
                )
                stats["inserted_contacts"] = contact_count
                imported_contacts = True
                logger.debug(f"[DEBUG] 联系人导入结果: {contact_count}")

            # 3. 导入消息
            logger.debug(f"\n[DEBUG] import_messages={import_messages}, message dbs={databases.get('message')}")
            if import_messages and databases.get("message"):
                if progress_callback:
                    progress_callback("导入消息...", 30, 100)

                message_stats = self._import_messages_v4(
                    databases["message"],
                    db_key,
                    wxid,
                    account_wxid,
                    limit,
                    progress_callback,
                    raw_keys=raw_keys,
                    watermark_ts=watermark_in,
                )

                stats["inserted_messages"] = message_stats["total"]
                stats["skipped"] += message_stats.get("skipped", 0)
                # 成功后才透出新水位（bridge 在基线保存处落库；异常路径不携带）
                stats["import_watermark_ts"] = message_stats.get("watermark_ts", watermark_in)
                logger.debug(f"[DEBUG] 消息导入结果: {message_stats}")

            if imported_contacts:
                synced_conversations = self._sync_conversation_avatar_metadata(account_wxid)
                logger.debug(f"[DEBUG] 已同步 {synced_conversations} 个会话头像")

            cleanup_stats = self._soft_delete_excluded_contacts_and_conversations(account_wxid)
            if cleanup_stats["contacts"] or cleanup_stats["conversations"]:
                logger.info(
                    "[DEBUG] Soft-deleted excluded accounts: contacts=%s, conversations=%s",
                    cleanup_stats["contacts"],
                    cleanup_stats["conversations"],
                )

            stats.update(self._collect_import_totals(account_wxid))

            logger.debug(f"\n[DEBUG] 最终统计: {stats}")

            # 4. 预处理和特征提取已改为懒加载模式
            # 不再在导入时自动执行,而是在用户点击"开始分析"时按需处理
            # 优点:
            # - 导入速度快,用户无需等待
            # - 按联系人独立处理,数据量小,不易中断
            # - 用户可选择性分析感兴趣的联系人
            # 注: 如需批量预处理,可调用 _auto_preprocess_messages() 和 _auto_extract_features()
            logger.info("[INFO] 数据导入完成,预处理将在首次分析时自动执行")

            # 6. 更新导入记录
            if import_id is not None:
                self._update_import_record(import_id, "success", stats, account_wxid=account_wxid)

            if progress_callback:
                progress_callback("导入完成", 100, 100)

            return {
                "ok": True,
                "stats": stats,
                "warnings": warnings
            }

        except Exception as e:
            if import_id is not None:
                self._update_import_record(import_id, "failed", stats, str(e), account_wxid=account_wxid)
            return {
                "ok": False,
                "error": f"导入失败: {str(e)}",
                "stats": stats
            }

    def refresh_contact_avatars(
        self,
        db_key: str,
        custom_paths: Optional[Dict] = None,
        raw_keys: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Re-read the WeChat contact DB and backfill avatar metadata only."""
        try:
            paths = self.resolve_wechat_paths(custom_paths)
            contact_db_path = (paths.get("databases") or {}).get("contact")
            account_wxid = str(paths.get("account_wxid") or paths.get("current_user") or "")
            if not contact_db_path:
                return {"ok": False, "error": "未找到联系人数据库"}

            contact_db = ContactDBV4(contact_db_path, db_key, raw_keys=raw_keys)
            try:
                contacts_data = contact_db.get_contacts(include_chatroom=True)
            finally:
                contact_db.close()

            store_stats = self._upsert_contacts(contacts_data, account_wxid)
            conversation_updates = self._sync_conversation_avatar_metadata(account_wxid)
            self._soft_delete_excluded_contacts_and_conversations(account_wxid)

            return {
                "ok": True,
                "stats": {
                    "scanned": store_stats["scanned"],
                    "contact_updates": store_stats["avatar_updates"],
                    "conversation_updates": conversation_updates,
                    "skipped_empty": store_stats["skipped_empty"],
                }
            }
        except Exception as e:
            logger.error(f"[DEBUG] 刷新联系人头像失败: {e}")
            return {"ok": False, "error": f"刷新联系人头像失败: {str(e)}"}

    def _import_contacts_v4(self, contact_db_path: str, db_key: str, account_wxid: str,
                            raw_keys: Optional[Dict] = None) -> int:
        """导入联系人(V4版本)"""
        logger.info("\n[DEBUG] 开始导入联系人")
        logger.debug(f"[DEBUG] 联系人数据库路径: {contact_db_path}")

        contact_db = ContactDBV4(contact_db_path, db_key, raw_keys=raw_keys)

        try:
            # include_chatroom=True：群聊联系人一并入库，群名(nick_name)
            # 经 _upsert_contacts 回填 conversations.display_name——否则群
            # 会话在下拉里只显示 xxx@chatroom 原始 ID，无法辨认
            contacts_data = contact_db.get_contacts(include_chatroom=True)
            logger.debug(f"[DEBUG] 从数据库读取到 {len(contacts_data)} 个联系人")
            store_stats = self._upsert_contacts(contacts_data, account_wxid)
            logger.info(
                "[DEBUG] Contacts imported: %s, filtered: %s, avatar updates: %s",
                store_stats["processed"],
                store_stats["filtered"],
                store_stats["avatar_updates"],
            )
            return store_stats["processed"]
        finally:
            contact_db.close()

    def _upsert_contacts(self, contacts_data: list[dict[str, Any]], account_wxid: str) -> Dict[str, int]:
        """Store contacts while preserving an existing avatar when the new one is blank."""
        db = get_db()
        now = int(time.time())
        existing_avatars = self._fetch_existing_contact_avatars(
            [contact.get("username", "") for contact in contacts_data],
            account_wxid,
        )

        processed = 0
        filtered = 0
        skipped_empty = 0
        avatar_updates = 0

        for contact_dict in contacts_data:
            username = (contact_dict.get("username") or "").strip()
            if not username:
                filtered += 1
                continue

            if is_excluded_contact_username(username, exclude_chatroom=False):
                filtered += 1
                continue

            avatar_url = (contact_dict.get("avatar_url") or "").strip()
            if avatar_url:
                if existing_avatars.get(username, "") != avatar_url:
                    avatar_updates += 1
            else:
                skipped_empty += 1

            try:
                db.execute(
                    """
                    INSERT INTO contacts
                    (account_wxid, username, nickname, remark, alias, phone, avatar_path, is_friend, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_wxid, username) DO UPDATE SET
                        nickname = excluded.nickname,
                        remark = excluded.remark,
                        alias = excluded.alias,
                        phone = excluded.phone,
                        avatar_path = CASE
                            WHEN excluded.avatar_path IS NOT NULL AND TRIM(excluded.avatar_path) != ''
                                THEN excluded.avatar_path
                            ELSE contacts.avatar_path
                        END,
                        is_friend = excluded.is_friend,
                        updated_at = excluded.updated_at,
                        is_deleted = 0
                """,
                    (
                        account_wxid,
                        username,
                        contact_dict.get("nickname", ""),
                        contact_dict.get("remark", ""),
                        contact_dict.get("alias", ""),
                        contact_dict.get("phone", ""),
                        avatar_url or None,
                        1 if contact_dict.get("is_friend") else 0,
                        now,
                        now,
                    ),
                )
                #同步更新 conversations 表的冗余名称字段，确保备注名/昵称变更后显示一致
                display_name =(
                    (contact_dict.get("remark")or"").strip()
                    or (contact_dict.get("nickname")or "").strip()
                    or username
                )
                db.execute(
                    """
                    UPDATE conversations
                    SET display_name = ?,
                        remark = ?,
                        nickname = ?,
                        updated_at = ?
                    WHERE account_wxid = ? AND username = ? AND platform = 'wechat'
                """,
                    (
                        display_name,
                        contact_dict.get("remark",""),
                        contact_dict.get("nickname",""),
                        now,
                        account_wxid,
                        username,
                    ),
                )
                processed += 1
            except Exception as e:
                logger.error(f"[DEBUG] 插入联系人失败: {e}")

        db.commit()
        return {
            "scanned": len(contacts_data),
            "processed": processed,
            "filtered": filtered,
            "skipped_empty": skipped_empty,
            "avatar_updates": avatar_updates,
        }

    def _collect_import_totals(self, account_wxid: str) -> Dict[str, int]:
        """Return current visible totals for the imported WeChat account."""
        db = get_db()

        contacts_row = db.execute(
            """
            SELECT COUNT(*) AS total
            FROM contacts
            WHERE account_wxid = ?
              AND is_deleted = 0
            """,
            (account_wxid,),
        ).fetchone()

        conversations_row = db.execute(
            """
            SELECT COUNT(*) AS total
            FROM conversations
            WHERE account_wxid = ?
              AND platform = 'wechat'
              AND is_deleted = 0
            """,
            (account_wxid,),
        ).fetchone()

        messages_row = db.execute(
            """
            SELECT COUNT(*) AS total
            FROM messages m
            INNER JOIN conversations c ON c.id = m.conversation_id
            WHERE c.account_wxid = ?
              AND c.platform = 'wechat'
              AND c.is_deleted = 0
            """,
            (account_wxid,),
        ).fetchone()

        return {
            "contacts": int((contacts_row or {})["total"] if contacts_row else 0),
            "conversations": int((conversations_row or {})["total"] if conversations_row else 0),
            "messages": int((messages_row or {})["total"] if messages_row else 0),
        }

    def _fetch_existing_contact_avatars(self, usernames: list[str], account_wxid: str) -> dict[str, str]:
        """Load current avatar paths once so we can report actual avatar updates."""
        normalized_usernames = sorted({username.strip() for username in usernames if username and username.strip()})
        if not normalized_usernames:
            return {}

        placeholders = ", ".join(["?"] * len(normalized_usernames))
        cursor = get_db().execute(
            f"""
            SELECT username, COALESCE(avatar_path, '') AS avatar_path
            FROM contacts
            WHERE account_wxid = ? AND username IN ({placeholders})
            """,
            (account_wxid, *normalized_usernames),
        )
        return {
            str(row["username"]): (row["avatar_path"] or "").strip()
            for row in cursor.fetchall()
        }

    def _sync_conversation_avatar_metadata(self, account_wxid: str) -> int:
        """Backfill conversation avatars from imported contact metadata."""
        cursor = get_db().execute(
            """
            UPDATE conversations
            SET avatar_path = (
                SELECT ct.avatar_path
                FROM contacts ct
                WHERE ct.account_wxid = conversations.account_wxid
                  AND ct.username = conversations.username
            )
            WHERE account_wxid = ?
              AND platform = 'wechat'
              AND EXISTS (
                    SELECT 1
                    FROM contacts ct
                    WHERE ct.account_wxid = conversations.account_wxid
                      AND ct.username = conversations.username
                      AND ct.avatar_path IS NOT NULL
                      AND TRIM(ct.avatar_path) != ''
                )
              AND COALESCE(TRIM(conversations.avatar_path), '') != COALESCE(TRIM((
                    SELECT ct.avatar_path
                    FROM contacts ct
                    WHERE ct.account_wxid = conversations.account_wxid
                      AND ct.username = conversations.username
                )), '')
            """,
            (account_wxid,),
        )
        get_db().commit()
        return int(cursor.rowcount or 0)

    def _import_messages_v4(
        self,
        message_db_paths: list,
        db_key: str,
        wxid: str,
        account_wxid: str,
        limit: int,
        progress_callback: Optional[Callable] = None,
        raw_keys: Optional[Dict] = None,
        watermark_ts: int = 0,
    ) -> Dict:
        """导入消息(V4版本)

        watermark_ts > 0 时启用时间水位增量读取：只读 [水位-24h, now+24h]
        窗口（安全窗覆盖 WAL 延迟/偶发乱序，窗内重扫由判重集合去重）。
        返回 stats 带 watermark_ts = max(水位, 本次见过最大 create_time)，
        只增不减；导入异常时调用方不落库 → 水位不推进 → 下次重扫（安全方向）。
        """
        logger.info("[DEBUG] Start importing messages")
        logger.debug(f"[DEBUG] 消息数据库数量: {len(message_db_paths)}")
        logger.debug(f"[DEBUG] 我的wxid: {wxid}")

        # 24h 安全窗：微信 create_time 实际单调、WAL 延迟秒级，一天冗余足够保守
        SAFETY_WINDOW = 86400
        if watermark_ts > 0:
            read_range = (max(0, watermark_ts - SAFETY_WINDOW), int(time.time()) + SAFETY_WINDOW)
            logger.info(f"[导入] 水位增量读取: watermark={watermark_ts}, 窗口起点={read_range[0]}")
        else:
            read_range = None  # 首导/force_full：全量

        total_messages = 0
        conversations_set = set()
        skipped_conversations = 0
        failed_conversations = 0
        skipped_messages = 0
        conversation_cache: dict[str, int] = {}
        touched_conversations: dict[int, int] = {}
        max_seen_ts = 0

        t_read = 0.0
        t_insert = 0.0
        t_total = time.time()

        message_db = MessageDBV4(message_db_paths, db_key, my_wxid=wxid, raw_keys=raw_keys)

        try:
            if progress_callback:
                progress_callback("扫描消息表...", 30, 100)

            # 预载判重集合（一次 SELECT 替代逐条 OR IGNORE 的 20 万次 execute）
            existing_keys = self._load_existing_message_keys()

            # 获取所有对话username
            all_usernames = message_db.get_all_conversation_usernames(include_chatroom=True)
            logger.debug(f"[DEBUG] Found conversations: {len(all_usernames)}")

            if len(all_usernames) > 0:
                logger.debug(f"[DEBUG] 前3个会话: {all_usernames[:3]}")

            for idx, username in enumerate(all_usernames):
                if is_excluded_contact_username(username, exclude_chatroom=False):
                    skipped_conversations += 1
                    continue

                if progress_callback:
                    progress = 30 + int((idx / max(len(all_usernames), 1)) * 60)
                    progress_callback(f"导入对话 {idx+1}/{len(all_usernames)}...", progress, 100)

                # 获取该用户的消息
                try:
                    t0 = time.time()
                    messages_data = message_db.get_messages(
                        username,
                        time_range=read_range,
                        limit=limit if limit > 0 else None
                    )
                    t_read += time.time() - t0

                   # logger.debug(f"[DEBUG] 会话 {username}: 读取到 {len(messages_data)} 条消息")

                    # 批量插入
                    batch = []
                    for msg_dict in messages_data:
                        ts = int(msg_dict.get('timestamp') or 0)
                        if ts > max_seen_ts:
                            max_seen_ts = ts

                        if is_excluded_contact_username(msg_dict.get('talker'), exclude_chatroom=False):
                            skipped_messages += 1
                            continue

                        conversations_set.add(msg_dict['talker'])
                        batch.append(msg_dict)

                        # 每1000条批量插入
                        if len(batch) >= 1000:
                            t0 = time.time()
                            batch_stats = self._insert_message_batch(
                                batch,
                                account_wxid,
                                conversation_cache,
                                touched_conversations,
                                existing_keys=existing_keys
                            )
                            t_insert += time.time() - t0
                            total_messages += batch_stats["inserted"]
                            skipped_messages += batch_stats["skipped"]
                            batch = []

                    # 插入剩余
                    if batch:
                        t0 = time.time()
                        batch_stats = self._insert_message_batch(
                            batch,
                            account_wxid,
                            conversation_cache,
                            touched_conversations,
                            existing_keys=existing_keys
                        )
                        t_insert += time.time() - t0
                        total_messages += batch_stats["inserted"]
                        skipped_messages += batch_stats["skipped"]

                except Exception as e:
                    # 某个对话导入失败,跳过继续（W3：计数并汇总，不再只留零散日志）
                    failed_conversations += 1
                    logger.error(f"[DEBUG] 导入对话 {username} 失败: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        finally:
            message_db.close()

        self._refresh_conversation_stats(touched_conversations)
        # 导入后冷构建：只写脏标记（dirty_since），不自动入队重建——
        # 大批量导入后全量构建耗时且用户无预期；首次建议/打开记忆时由
        # ensure_contact_index 按需构建，或由"全面分析"完成点主动触发。
        try:
            from ..realtime.rag.store import RagStore

            store = RagStore()
            for conversation_id in touched_conversations:
                store.mark_dirty(account_wxid, int(conversation_id))
            store.conn.commit()
        except Exception as rag_e:
            logger.debug("[RAG] import dirty mark skipped: %s", rag_e)

        # 分析结果打脏：touched 只含本批有新插入消息的会话（OR IGNORE 全
        # 跳过的重复导入不进入），stale 由分析完成点清除
        try:
            from ..analysis.analysis_state import mark_conversations_stale

            mark_conversations_stale(touched_conversations)
        except Exception as stale_e:
            logger.debug("[分析状态] import stale mark skipped: %s", stale_e)

        logger.info(
            f"[DEBUG] Messages imported: {total_messages}, conversations: {len(conversations_set)}"
            f" (读取 {t_read:.1f}s / 插入 {t_insert:.1f}s / 总 {time.time() - t_total:.1f}s"
            f"{' / 水位增量' if read_range else ' / 全量'})"
        )
        logger.debug(f"[DEBUG] Filtered conversations: {skipped_conversations}")
        if failed_conversations:
            # 解密缺口/读取异常等导致的会话级失败（W3）：显式汇总，避免静默缺失
            logger.warning(
                f"[导入] {failed_conversations} 个对话导入失败（常见原因：微信在线写入导致"
                "个别页面解密失败；可关闭微信后重新导入补全）"
            )

        return {
            "total": total_messages,
            "conversations": len(conversations_set),
            "skipped": skipped_messages,
            "failed_conversations": failed_conversations,
            # 只增不减；零消息读取（无新聊天）时维持原水位
            "watermark_ts": max(watermark_ts, max_seen_ts),
        }

    def _load_existing_message_keys(self) -> set:
        """预载 (conversation_id, local_id, timestamp) 判重集合。

        替代此前逐条 OR IGNORE 的 20 万次 execute：一次 SELECT 建立，
        导入全程内存判重，新插入的 key 增量补入。local_id IS NULL 的
        实时行不参与（它们本来就不受唯一索引约束）。
        timestamp 必须进键：微信 V4 分片库 local_id 是分片内自增，
        跨分片同号消息会被旧二元键误判为重复而整片吞掉。
        """
        return {
            (row[0], row[1], row[2])
            for row in get_db().execute(
                "SELECT conversation_id, local_id, timestamp FROM messages WHERE local_id IS NOT NULL"
            )
        }

    def _insert_message_batch(
        self,
        messages: list,
        account_wxid: str,
        conversation_cache: dict[str, int],
        touched_conversations: dict[int, int],
        existing_keys: Optional[set] = None,
    ) -> Dict[str, int]:  # pyright: ignore[reportMissingTypeArgument]
        """批量插入消息（内存判重 + 分会话 executemany）。

        existing_keys 由调用方在导入全程预载一次并传递（跨批去重）；
        None 时本调用自载（直接调用/测试场景）。返回 inserted/skipped
        语义与旧逐条路径一致；touched 仅含有新插入的会话。
        """
        inserted = 0
        skipped = 0
        db = get_db()
        if existing_keys is None:
            existing_keys = self._load_existing_message_keys()

        # 收集新消息：会话确保仅 cache miss 时执行（每 talker 一次，
        # 此前在 per-message 循环里跑了 20 万次）
        rows_by_conv: dict[int, list] = {}
        now = int(time.time())
        for msg in messages:
            talker = msg.get('talker')
            if not talker or is_excluded_contact_username(talker, exclude_chatroom=False):
                skipped += 1
                continue

            conversation_id = conversation_cache.get(talker)
            if conversation_id is None:
                from .chatroom import is_chatroom_username
                conv_type = "group" if is_chatroom_username(talker) else "private"
                db.execute("""
                    INSERT OR IGNORE INTO conversations
                    (account_wxid, username, display_name, platform, conversation_type, created_at, updated_at, message_count)
                    VALUES (?, ?, ?, 'wechat', ?, ?, ?, 0)
                """, (account_wxid, talker, talker, conv_type, now, now))
                row = db.execute(
                    "SELECT id FROM conversations WHERE account_wxid = ? AND username = ? AND platform = 'wechat'",
                    (account_wxid, talker)
                ).fetchone()
                if not row:
                    skipped += 1
                    continue
                conversation_id = row[0]
                conversation_cache[talker] = conversation_id

            local_id = msg.get('local_id')
            ts = int(msg.get('timestamp') or 0)
            # 判重键含 timestamp：local_id 仅分片内唯一（见 _load_existing_message_keys）
            key = (conversation_id, local_id, ts) if local_id is not None else None
            if key is not None and key in existing_keys:
                skipped += 1
                continue
            if key is not None:
                # 同批重复 key：首条计插入，后续按已存在跳过（与旧 OR IGNORE 行为一致）
                existing_keys.add(key)

            inserted += 1
            touched_conversations[conversation_id] = max(
                touched_conversations.get(conversation_id, 0), ts
            )
            rows_by_conv.setdefault(conversation_id, []).append((
                conversation_id,
                local_id,
                talker,
                msg.get('sender', ''),
                1 if msg.get('is_sender') else 0,
                msg.get('message_type', 1),
                msg['content'],
                ts,
                now,
            ))

        # 分会话 executemany（插入语句保持 OR IGNORE 兜底并发安全）
        for rows in rows_by_conv.values():
            db.executemany("""
                INSERT OR IGNORE INTO messages
                (conversation_id, local_id, talker, sender, is_sender, message_type, content, timestamp, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'long', ?)
            """, rows)

        # 实时与导入消息对账（W1）：实时行不再占用 local_id 后，同一物理消息可能
        # 同时存在 realtime 行（UIA 分钟级时间戳）与 long 行（微信库精确时间戳）。
        # 对含实时行的会话，删除已被权威导入数据覆盖（同发送方/类型/内容、±59 秒
        # 窗口容差）的冗余实时行，避免统计、预处理与 RAG 重复计数。
        reconciled = 0
        for conv_id in touched_conversations:
            has_realtime = db.execute(
                """
                SELECT 1 FROM messages
                WHERE conversation_id = ? AND source IN ('realtime', 'realtime_backfill')
                LIMIT 1
                """,
                (conv_id,),
            ).fetchone()
            if not has_realtime:
                continue
            cursor = db.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ?
                  AND source IN ('realtime', 'realtime_backfill')
                  AND EXISTS (
                      SELECT 1 FROM messages m2
                      WHERE m2.conversation_id = messages.conversation_id
                        AND m2.source = 'long'
                        AND m2.is_sender = messages.is_sender
                        AND m2.message_type = messages.message_type
                        AND m2.timestamp BETWEEN messages.timestamp - 59 AND messages.timestamp + 59
                        AND COALESCE(m2.content, '') = COALESCE(messages.content, '')
                  )
                """,
                (conv_id,),
            )
            reconciled += cursor.rowcount or 0
        if reconciled:
            logger.info(f"[导入对账] 清理被导入数据覆盖的冗余实时消息 {reconciled} 条")

        db.commit()
        return {"inserted": inserted, "skipped": skipped}

    def _soft_delete_excluded_contacts_and_conversations(self, account_wxid: str) -> Dict[str, int]:
        """Hide imported WeChat system accounts from relationship analysis."""
        usernames = sorted(EXCLUDED_CONTACT_USERNAMES)
        if not account_wxid or not usernames:
            return {"contacts": 0, "conversations": 0}

        placeholders = ", ".join(["?"] * len(usernames))
        now = int(time.time())
        db = get_db()

        contacts_cursor = db.execute(
            f"""
            UPDATE contacts
            SET is_deleted = 1, updated_at = ?
            WHERE account_wxid = ?
              AND is_deleted = 0
              AND LOWER(TRIM(username)) IN ({placeholders})
            """,
            (now, account_wxid, *usernames),
        )
        conversations_cursor = db.execute(
            f"""
            UPDATE conversations
            SET is_deleted = 1, updated_at = ?
            WHERE account_wxid = ?
              AND is_deleted = 0
              AND LOWER(TRIM(username)) IN ({placeholders})
            """,
            (now, account_wxid, *usernames),
        )
        db.commit()
        return {
            "contacts": int(contacts_cursor.rowcount or 0),
            "conversations": int(conversations_cursor.rowcount or 0),
        }

    def _refresh_conversation_stats(self, touched_conversations: dict[int, int]) -> None:
        """Refresh denormalized counters for conversations touched by the import."""
        if not touched_conversations:
            return

        db = get_db()
        for conversation_id, latest_timestamp in touched_conversations.items():
            db.execute(
                """
                UPDATE conversations
                SET updated_at = MAX(updated_at, ?),
                    message_count = (
                        SELECT COUNT(*)
                        FROM messages
                        WHERE messages.conversation_id = conversations.id
                    )
                WHERE id = ?
                """,
                (latest_timestamp, conversation_id)
            )
        db.commit()

    def _auto_preprocess_messages(
        self,
        progress_callback: Optional[Callable] = None
    ) -> int:
        """
        自动预处理新导入的消息

        Returns:
            预处理的消息数量
        """
        try:
            logger.info("\n[预处理] 开始自动预处理新导入的消息...")

            # 查找未预处理的消息（不在缓存表中的消息）
            cursor = get_db().execute("""
                SELECT m.id, m.conversation_id
                FROM messages m
                LEFT JOIN message_preprocessed mp ON m.id = mp.message_id
                WHERE mp.id IS NULL
                    AND m.message_type = 1
                    AND m.content IS NOT NULL
                    AND m.content != ''
                ORDER BY m.conversation_id, m.timestamp
            """)

            unprocessed = cursor.fetchall()

            if not unprocessed:
                logger.debug("[Preprocess] No messages need preprocessing")
                return 0

            logger.debug(f"[预处理] 找到 {len(unprocessed)} 条未预处理的消息")

            # 按会话分组
            conv_messages = {}
            for msg_id, conv_id in unprocessed:
                if conv_id not in conv_messages:
                    conv_messages[conv_id] = []
                conv_messages[conv_id].append(msg_id)

            logger.debug(f"[Preprocess] Conversations to preprocess: {len(conv_messages)}")

            # 批量预处理（每个会话独立处理）
            total_processed = 0
            for idx, (conv_id, message_ids) in enumerate(conv_messages.items()):
                if progress_callback:
                    progress = 95 + int((idx / len(conv_messages)) * 4)
                    progress_callback(f"预处理会话 {idx+1}/{len(conv_messages)}...", progress, 100)

                count = self.preprocessor.preprocess_message_batch(conv_id, message_ids)
                total_processed += count

            logger.info(f"[Preprocess] Completed preprocessing messages: {total_processed}")
            return total_processed

        except Exception as e:
            logger.error(f"[预处理] 自动预处理失败: {e}")
            import traceback
            traceback.print_exc()
            return 0

    def _auto_extract_features(
        self,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        自动提取所有会话的特征（会话切分、响应时间、主动性、字数统计）

        Returns:
            特征提取统计信息
        """
        try:
            logger.info("\n[特征提取] 开始自动特征提取...")

            # 延迟导入特征提取服务（避免循环导入）
            from ..analysis.feature_extraction_service import FeatureExtractionService

            # 查找所有有消息的会话
            cursor = get_db().execute("""
                SELECT id, display_name, message_count
                FROM conversations
                WHERE message_count > 0
                ORDER BY message_count DESC
            """)

            conversations = cursor.fetchall()

            if not conversations:
                logger.debug("[特征提取] 没有找到会话")
                return {
                    "total_conversations": 0,
                    "processed": 0,
                    "failed": 0
                }

            # logger.debug(f"[特征提取] 找到 {len(conversations)} 个会话")

            # 初始化特征提取服务
            feature_service = FeatureExtractionService()

            # 批量提取特征
            stats = {
                "total_conversations": len(conversations),
                "processed": 0,
                "failed": 0,
                "skipped": 0
            }

            for idx, (conv_id, name, msg_count) in enumerate(conversations):
                try:
                    # 显示详细进度（明确是"联系人"而不是"会话"）
                    logger.debug(f"[特征提取] 联系人 {idx+1}/{len(conversations)} - {name} ({msg_count}条消息)")

                    if progress_callback:
                        progress = 97 + int((idx / len(conversations)) * 3)
                        progress_callback(f"提取特征 {idx+1}/{len(conversations)}: {name}", progress, 100)

                    # 检查是否已经提取过特征
                    cursor = get_db().execute("""
                        SELECT COUNT(*) FROM sessions WHERE conversation_id = ?
                    """, (conv_id,))
                    session_count = cursor.fetchone()[0]

                    if session_count > 0:
                        logger.debug(f"  → 已有 {session_count} 个会话记录，跳过")
                        stats["skipped"] += 1
                        continue

                    # 执行特征提取（切分会话）
                    result = feature_service.extract_features(conv_id)

                    # 显示生成的会话数量
                    if result and "sessions" in result:
                        num_sessions = len(result["sessions"])
                        logger.info(f"  → 切分完成，生成 {num_sessions} 个会话")

                    stats["processed"] += 1

                except Exception as e:
                    logger.error(f"[特征提取] 会话 {conv_id} 提取失败: {e}")
                    stats["failed"] += 1
                    continue

            # 显示完成信息
            logger.error(f"[特征提取] 完成! 处理={stats['processed']}, 跳过={stats['skipped']}, 失败={stats['failed']}")

            return stats

        except Exception as e:
            logger.error(f"[特征提取] 自动特征提取失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "total_conversations": 0,
                "processed": 0,
                "failed": 0,
                "error": str(e)
            }

    def _create_import_record(self, account_wxid: str) -> int:
        """创建导入记录"""
        cursor = get_db().execute("""
            INSERT INTO import_records (import_type, status, started_at, metadata_json)
            VALUES ('wechat_full', 'pending', ?, ?)
        """, (int(time.time()), json.dumps({"account_wxid": account_wxid}, ensure_ascii=False)))
        get_db().commit()
        return cursor.lastrowid  # pyright: ignore[reportReturnType]

    def _update_import_record(
        self,
        import_id: int,
        status: str,
        stats: Dict,
        error: str = None,
        account_wxid: str = "",
    ):
        """更新导入记录"""
        import json
        metadata = dict(stats)
        metadata["account_wxid"] = account_wxid

        get_db().execute("""
            UPDATE import_records
            SET status = ?,
                total_messages = ?,
                total_conversations = ?,
                error_message = ?,
                completed_at = ?,
                metadata_json = ?
            WHERE id = ?
        """, (
            status,
            stats.get('messages', 0),  # 修复: messages不是total_messages
            stats.get('conversations', 0),  # 修复: conversations不是total_conversations
            error,
            int(time.time()),
            json.dumps(metadata, ensure_ascii=False),
            import_id
        ))
        get_db().commit()
