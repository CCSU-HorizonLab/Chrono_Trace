"""微信V4数据导入服务 (仅支持4.0+版本)"""
import os
import time
import logging
from typing import Dict, Any, Optional, Callable
from .path_finder import WeChatPathFinder
from .db_decryptor import WeChatDBDecryptor
from .db.v4.contact import ContactDBV4
from .db.v4.message import MessageDBV4
from ...db.connection import get_db
from ..analysis.preprocessing_service import PreprocessingService


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

    def verify_key(self, db_key: str) -> Dict[str, Any]:
        """
        验证密钥是否有效

        Args:
            db_key: 32位hex密钥

        Returns:
            dict: {"ok": bool, "error": str}
        """
        try:
            # 查找数据库路径
            paths = WeChatPathFinder.find_all_wechat_dbs()
            if not paths:
                return {"ok": False, "error": "未找到微信数据库"}

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

    def resolve_wechat_paths(self, custom_paths: Optional[Dict] = None) -> Dict[str, Any]:
        """Resolve the active WeChat data paths for import and incremental checks."""
        if custom_paths and custom_paths.get("wechat_dir") and custom_paths.get("current_user"):
            wechat_dir = custom_paths["wechat_dir"]
            wxid = custom_paths["current_user"]
            databases = WeChatPathFinder.find_databases(wxid, wechat_dir)
            return {
                "wechat_dir": wechat_dir,
                "current_user": wxid,
                "databases": databases
            }

        paths = WeChatPathFinder.find_all_wechat_dbs()
        if not paths:
            raise Exception("WeChat database path not found")
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
            "files": snapshot_files,
            "total_size": sum(item["size"] for item in snapshot_files),
            "captured_at": int(time.time())
        }

    def import_wechat_data(
        self,
        db_key: str,
        options: Optional[Dict] = None,
        custom_paths: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
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

        warnings = []
        stats = {
            "contacts": 0,
            "messages": 0,
            "conversations": 0,
            "skipped": 0
        }

        # 创建导入记录
        import_id = self._create_import_record()

        try:
            # 1. 获取数据库路径
            if progress_callback:
                progress_callback("查找数据库路径...", 0, 100)

            logger.info(f"\n[DEBUG] === 开始导入流程 ===")
            logger.debug(f"[DEBUG] custom_paths: {custom_paths}")

            paths = self.resolve_wechat_paths(custom_paths)
            wxid = paths["current_user"]
            databases = paths["databases"]

            logger.debug(f"[DEBUG] wxid: {wxid}")
            logger.debug(f"[DEBUG] databases: {databases}")

            # 2. 导入联系人
            logger.debug(f"\n[DEBUG] import_contacts={import_contacts}, has contact db={databases.get('contact')}")
            if import_contacts and databases.get("contact"):
                if progress_callback:
                    progress_callback("导入联系人...", 10, 100)

                contact_count = self._import_contacts_v4(
                    databases["contact"],
                    db_key
                )
                stats["contacts"] = contact_count
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
                    limit,
                    progress_callback
                )

                stats["messages"] = message_stats["total"]
                stats["conversations"] = message_stats["conversations"]
                stats["skipped"] += message_stats.get("skipped", 0)
                logger.debug(f"[DEBUG] 消息导入结果: {message_stats}")

            logger.debug(f"\n[DEBUG] 最终统计: {stats}")

            # 4. 预处理和特征提取已改为懒加载模式
            # 不再在导入时自动执行,而是在用户点击"开始分析"时按需处理
            # 优点:
            # - 导入速度快,用户无需等待
            # - 按联系人独立处理,数据量小,不易中断
            # - 用户可选择性分析感兴趣的联系人
            # 注: 如需批量预处理,可调用 _auto_preprocess_messages() 和 _auto_extract_features()
            logger.info(f"[INFO] 数据导入完成,预处理将在首次分析时自动执行")

            # 6. 更新导入记录
            self._update_import_record(import_id, "success", stats)

            if progress_callback:
                progress_callback("导入完成", 100, 100)

            return {
                "ok": True,
                "stats": stats,
                "warnings": warnings
            }

        except Exception as e:
            self._update_import_record(import_id, "failed", stats, str(e))
            return {
                "ok": False,
                "error": f"导入失败: {str(e)}",
                "stats": stats
            }

    def _import_contacts_v4(self, contact_db_path: str, db_key: str) -> int:
        """导入联系人(V4版本)"""
        logger.info(f"\n[DEBUG] 开始导入联系人")
        logger.debug(f"[DEBUG] 联系人数据库路径: {contact_db_path}")

        contact_db = ContactDBV4(contact_db_path, db_key)

        try:
            contacts_data = contact_db.get_contacts()
            logger.debug(f"[DEBUG] 从数据库读取到 {len(contacts_data)} 个联系人")

            # 批量插入联系人
            inserted = 0
            skipped = 0
            for contact_dict in contacts_data:
                username = contact_dict['username']

                # 过滤群聊和公众号
                if '@chatroom' in username or username.startswith('gh_'):
                    skipped += 1
                    continue

                try:
                    now = int(time.time())
                    get_db().execute("""
                        INSERT INTO contacts
                        (username, nickname, remark, alias, phone, is_friend, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(username) DO UPDATE SET
                            nickname = excluded.nickname,
                            remark = excluded.remark,
                            alias = excluded.alias,
                            phone = excluded.phone,
                            is_friend = excluded.is_friend,
                            updated_at = excluded.updated_at,
                            is_deleted = 0
                    """, (
                        username,
                        contact_dict['nickname'],
                        contact_dict['remark'],
                        contact_dict['alias'],
                        contact_dict['phone'],
                        1 if contact_dict['is_friend'] else 0,
                        now,
                        now
                    ))
                    inserted += 1
                except Exception as e:
                    logger.error(f"[DEBUG] 插入联系人失败: {e}")
                    pass  # 忽略单条错误

            get_db().commit()
            logger.info(f"[DEBUG] Contacts imported: {inserted}, filtered: {skipped}")
            return inserted
        finally:
            contact_db.close()

    def _import_messages_v4(
        self,
        message_db_paths: list,
        db_key: str,
        wxid: str,
        limit: int,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """导入消息(V4版本)"""
        logger.info("[DEBUG] Start importing messages")
        logger.debug(f"[DEBUG] 消息数据库数量: {len(message_db_paths)}")
        logger.debug(f"[DEBUG] 我的wxid: {wxid}")

        total_messages = 0
        conversations_set = set()
        skipped_conversations = 0
        skipped_messages = 0
        conversation_cache: dict[str, int] = {}
        touched_conversations: dict[int, int] = {}

        message_db = MessageDBV4(message_db_paths, db_key, my_wxid=wxid)

        try:
            if progress_callback:
                progress_callback("扫描消息表...", 30, 100)

            # 获取所有对话username
            all_usernames = message_db.get_all_conversation_usernames()
            logger.debug(f"[DEBUG] Found conversations: {len(all_usernames)}")

            if len(all_usernames) > 0:
                logger.debug(f"[DEBUG] 前3个会话: {all_usernames[:3]}")

            for idx, username in enumerate(all_usernames):
                # 过滤群聊、公众号、商业号
                if '@chatroom' in username or '@openim' in username or username.startswith('gh_'):
                    skipped_conversations += 1
                    continue

                if progress_callback:
                    progress = 30 + int((idx / max(len(all_usernames), 1)) * 60)
                    progress_callback(f"导入对话 {idx+1}/{len(all_usernames)}...", progress, 100)

                # 获取该用户的消息
                try:
                    messages_data = message_db.get_messages(
                        username,
                        time_range=None,
                        limit=limit if limit > 0 else None
                    )

                   # logger.debug(f"[DEBUG] 会话 {username}: 读取到 {len(messages_data)} 条消息")

                    # 批量插入
                    batch = []
                    for msg_dict in messages_data:
                        conversations_set.add(msg_dict['talker'])
                        batch.append(msg_dict)

                        # 每1000条批量插入
                        if len(batch) >= 1000:
                            batch_stats = self._insert_message_batch(
                                batch,
                                conversation_cache,
                                touched_conversations
                            )
                            total_messages += batch_stats["inserted"]
                            skipped_messages += batch_stats["skipped"]
                            batch = []

                    # 插入剩余
                    if batch:
                        batch_stats = self._insert_message_batch(
                            batch,
                            conversation_cache,
                            touched_conversations
                        )
                        total_messages += batch_stats["inserted"]
                        skipped_messages += batch_stats["skipped"]

                except Exception as e:
                    # 某个对话导入失败,跳过继续
                    logger.error(f"[DEBUG] 导入对话 {username} 失败: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        finally:
            message_db.close()

        self._refresh_conversation_stats(touched_conversations)

        logger.info(f"[DEBUG] Messages imported: {total_messages}, conversations: {len(conversations_set)}")
        logger.debug(f"[DEBUG] Filtered conversations: {skipped_conversations}")

        return {
            "total": total_messages,
            "conversations": len(conversations_set),
            "skipped": skipped_messages
        }

    def _insert_message_batch(
        self,
        messages: list,
        conversation_cache: dict[str, int],
        touched_conversations: dict[int, int]
    ) -> Dict[str, int]:  # pyright: ignore[reportMissingTypeArgument]
        """批量插入消息"""
        inserted = 0
        skipped = 0
        db = get_db()
        for msg in messages:
            try:
                talker = msg['talker']

                # 再次过滤群聊和公众号(双重保险)
                if '@chatroom' in talker or talker.startswith('gh_'):
                    continue

                # 确保会话存在 (修复: 使用 username 字段而不是 name)
                db.execute("""
                    INSERT OR IGNORE INTO conversations (username, display_name, platform, created_at, updated_at, message_count)
                    VALUES (?, ?, 'wechat', ?, ?, 0)
                """, (talker, talker, int(time.time()), int(time.time())))

                conversation_id = conversation_cache.get(talker)
                if conversation_id is None:
                    cursor = db.execute(
                        "SELECT id FROM conversations WHERE username = ? AND platform = 'wechat'",
                        (talker,)
                    )
                    row = cursor.fetchone()
                    if not row:
                        skipped += 1
                        continue
                    conversation_id = row[0]
                    conversation_cache[talker] = conversation_id

                # 插入消息 (修复: 添加必需的字段)
                is_sender = 1 if msg['is_sender'] else 0

                cursor = db.execute("""
                    INSERT OR IGNORE INTO messages
                    (conversation_id, local_id, talker, sender, is_sender, message_type, content, timestamp, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'long', ?)
                """, (
                    conversation_id,
                    msg.get('local_id'),
                    talker,
                    msg.get('sender', ''),
                    is_sender,
                    msg.get('message_type', 1),
                    msg['content'],
                    msg['timestamp'],
                    int(time.time())
                ))
                if cursor.rowcount == 1:
                    inserted += 1
                    touched_conversations[conversation_id] = max(
                        touched_conversations.get(conversation_id, 0),
                        int(msg['timestamp'])
                    )
                else:
                    skipped += 1

            except Exception as e:
                logger.error(f"[DEBUG] 插入消息失败: {e}")
                pass  # 忽略单条错误

        db.commit()
        return {"inserted": inserted, "skipped": skipped}

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
            logger.info(f"\n[预处理] 开始自动预处理新导入的消息...")

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
            logger.info(f"\n[特征提取] 开始自动特征提取...")

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
                logger.debug(f"[特征提取] 没有找到会话")
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

    def _create_import_record(self) -> int:
        """创建导入记录"""
        cursor = get_db().execute("""
            INSERT INTO import_records (import_type, status, started_at)
            VALUES ('wechat_full', 'pending', ?)
        """, (int(time.time()),))
        get_db().commit()
        return cursor.lastrowid  # pyright: ignore[reportReturnType]

    def _update_import_record(
        self,
        import_id: int,
        status: str,
        stats: Dict,
        error: str = None
    ):
        """更新导入记录"""
        import json

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
            json.dumps(stats),
            import_id
        ))
        get_db().commit()
