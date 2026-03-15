"""寰俊V4鏁版嵁瀵煎叆鏈嶅姟 (浠呮敮鎸?.0+鐗堟湰)"""
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
    """寰俊V4鏁版嵁瀵煎叆鏈嶅姟"""
    
    def __init__(self):
        pass  # get_db() removed for thread safety
        self.preprocessor = PreprocessingService()
    
    def get_wechat_paths(self) -> Dict[str, Any]:
        """
        鑾峰彇寰俊鏁版嵁搴撹矾寰勪俊鎭?渚涘墠绔睍绀?
        
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
                    "error": "?????????????????????"
                }
            
            return {
                "ok": True,
                "data": paths
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"鏌ユ壘寰俊璺緞澶辫触: {str(e)}"
            }
    
    def verify_key(self, db_key: str) -> Dict[str, Any]:
        """
        楠岃瘉瀵嗛挜鏄惁鏈夋晥
        
        Args:
            db_key: 32浣峢ex瀵嗛挜
            
        Returns:
            dict: {"ok": bool, "error": str}
        """
        try:
            # 鏌ユ壘鏁版嵁搴撹矾寰?
            paths = WeChatPathFinder.find_all_wechat_dbs()
            if not paths:
                return {"ok": False, "error": "鏈壘鍒板井淇℃暟鎹簱"}
            
            # 閫夋嫨绗竴涓秷鎭簱杩涜楠岃瘉
            message_dbs = paths["databases"]["message"]
            if not message_dbs:
                # 灏濊瘯鑱旂郴浜哄簱
                contact_db = paths["databases"].get("contact")
                if contact_db:
                    is_valid = WeChatDBDecryptor.verify_key(contact_db, db_key)
                    return {"ok": True} if is_valid else {"ok": False, "error": "瀵嗛挜閿欒"}
                return {"ok": False, "error": "鏈壘鍒颁换浣曟暟鎹簱"}
            
            # 楠岃瘉瀵嗛挜
            is_valid = WeChatDBDecryptor.verify_key(message_dbs[0], db_key)
            
            if is_valid:
                return {"ok": True}
            else:
                return {"ok": False, "error": "????????????"}
        
        except Exception as e:
            return {"ok": False, "error": f"楠岃瘉澶辫触: {str(e)}"}
    
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
        瀹屾暣鐨勫井淇℃暟鎹鍏ユ祦绋?
        
        Args:
            db_key: 32浣峢ex瀵嗛挜
            options: 瀵煎叆閫夐」 {
                "import_contacts": bool,    # 鏄惁瀵煎叆鑱旂郴浜?
                "import_messages": bool,    # 鏄惁瀵煎叆娑堟伅
                "limit": int                # 娑堟伅鏁伴噺闄愬埗(0=鍏ㄩ儴)
            }
            custom_paths: 鑷畾涔夎矾寰?濡傛灉鎻愪緵鍒欎娇鐢?鍚﹀垯鑷姩妫€娴?
            progress_callback: 杩涘害鍥炶皟 callback(status, current, total)
            
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
        
        # 鍒涘缓瀵煎叆璁板綍
        import_id = self._create_import_record()
        
        try:
            # 1. 鑾峰彇鏁版嵁搴撹矾寰?
            if progress_callback:
                progress_callback("鏌ユ壘鏁版嵁搴撹矾寰?..", 0, 100)
            
            logger.info(f"\n[DEBUG] === 寮€濮嬪鍏ユ祦绋?===")
            logger.debug(f"[DEBUG] custom_paths: {custom_paths}")

            paths = self.resolve_wechat_paths(custom_paths)
            wxid = paths["current_user"]
            databases = paths["databases"]
            
            logger.debug(f"[DEBUG] wxid: {wxid}")
            logger.debug(f"[DEBUG] databases: {databases}")
            
            # 2. 瀵煎叆鑱旂郴浜?
            logger.debug(f"\n[DEBUG] import_contacts={import_contacts}, has contact db={databases.get('contact')}")
            if import_contacts and databases.get("contact"):
                if progress_callback:
                    progress_callback("瀵煎叆鑱旂郴浜?..", 10, 100)
                
                contact_count = self._import_contacts_v4(
                    databases["contact"],
                    db_key
                )
                stats["contacts"] = contact_count
                logger.debug(f"[DEBUG] 鑱旂郴浜哄鍏ョ粨鏋? {contact_count}")
            
            # 3. 瀵煎叆娑堟伅
            logger.debug(f"\n[DEBUG] import_messages={import_messages}, message dbs={databases.get('message')}")
            if import_messages and databases.get("message"):
                if progress_callback:
                    progress_callback("瀵煎叆娑堟伅...", 30, 100)
                
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
                logger.debug(f"[DEBUG] 娑堟伅瀵煎叆缁撴灉: {message_stats}")
            
            logger.debug(f"\n[DEBUG] 鏈€缁堢粺璁? {stats}")
            
            # 4. 棰勫鐞嗗拰鐗瑰緛鎻愬彇宸叉敼涓烘噿鍔犺浇妯″紡
            # 涓嶅啀鍦ㄥ鍏ユ椂鑷姩鎵ц,鑰屾槸鍦ㄧ敤鎴风偣鍑?寮€濮嬪垎鏋?鏃舵寜闇€澶勭悊
            # 浼樼偣:
            # - 瀵煎叆閫熷害蹇?鐢ㄦ埛鏃犻渶绛夊緟
            # - 鎸夎仈绯讳汉鐙珛澶勭悊,鏁版嵁閲忓皬,涓嶆槗涓柇
            # - 鐢ㄦ埛鍙€夋嫨鎬у垎鏋愭劅鍏磋叮鐨勮仈绯讳汉
            # 娉? 濡傞渶鎵归噺棰勫鐞?鍙皟鐢?_auto_preprocess_messages() 鍜?_auto_extract_features()
            logger.info(f"[INFO] 鏁版嵁瀵煎叆瀹屾垚,棰勫鐞嗗皢鍦ㄩ娆″垎鏋愭椂鑷姩鎵ц")

            # 6. 鏇存柊瀵煎叆璁板綍
            self._update_import_record(import_id, "success", stats)
            
            if progress_callback:
                progress_callback("瀵煎叆瀹屾垚", 100, 100)
            
            return {
                "ok": True,
                "stats": stats,
                "warnings": warnings
            }
        
        except Exception as e:
            self._update_import_record(import_id, "failed", stats, str(e))
            return {
                "ok": False,
                "error": f"瀵煎叆澶辫触: {str(e)}",
                "stats": stats
            }
    
    def _import_contacts_v4(self, contact_db_path: str, db_key: str) -> int:
        """瀵煎叆鑱旂郴浜?V4鐗堟湰)"""
        logger.info(f"\n[DEBUG] 寮€濮嬪鍏ヨ仈绯讳汉")
        logger.debug(f"[DEBUG] 鑱旂郴浜烘暟鎹簱璺緞: {contact_db_path}")
        
        contact_db = ContactDBV4(contact_db_path, db_key)
        
        try:
            contacts_data = contact_db.get_contacts()
            logger.debug(f"[DEBUG] 浠庢暟鎹簱璇诲彇鍒?{len(contacts_data)} 涓仈绯讳汉")
            
            # 鎵归噺鎻掑叆鑱旂郴浜?
            inserted = 0
            skipped = 0
            for contact_dict in contacts_data:
                username = contact_dict['username']
                
                # 杩囨护缇よ亰鍜屽叕浼楀彿
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
                    logger.error(f"[DEBUG] 鎻掑叆鑱旂郴浜哄け璐? {e}")
                    pass  # 蹇界暐鍗曟潯閿欒
            
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
        """瀵煎叆娑堟伅(V4鐗堟湰)"""
        logger.info("[DEBUG] Start importing messages")
        logger.debug(f"[DEBUG] 娑堟伅鏁版嵁搴撴暟閲? {len(message_db_paths)}")
        logger.debug(f"[DEBUG] 鎴戠殑wxid: {wxid}")
        
        total_messages = 0
        conversations_set = set()
        skipped_conversations = 0
        skipped_messages = 0
        conversation_cache: dict[str, int] = {}
        touched_conversations: dict[int, int] = {}
        
        message_db = MessageDBV4(message_db_paths, db_key, my_wxid=wxid)
        
        try:
            if progress_callback:
                progress_callback("鎵弿娑堟伅琛?..", 30, 100)
            
            # 鑾峰彇鎵€鏈夊璇漸sername
            all_usernames = message_db.get_all_conversation_usernames()
            logger.debug(f"[DEBUG] Found conversations: {len(all_usernames)}")
            
            if len(all_usernames) > 0:
                logger.debug(f"[DEBUG] 鍓?涓細璇? {all_usernames[:3]}")
             
            for idx, username in enumerate(all_usernames):
                # 杩囨护缇よ亰銆佸叕浼楀彿銆佸晢涓氬彿
                if '@chatroom' in username or '@openim' in username or username.startswith('gh_'):
                    skipped_conversations += 1
                    continue
                
                if progress_callback:
                    progress = 30 + int((idx / max(len(all_usernames), 1)) * 60)
                    progress_callback(f"瀵煎叆瀵硅瘽 {idx+1}/{len(all_usernames)}...", progress, 100)
                
                # 鑾峰彇璇ョ敤鎴风殑娑堟伅
                try:
                    messages_data = message_db.get_messages(
                        username,
                        time_range=None,
                        limit=limit if limit > 0 else None
                    )
                    
                   # logger.debug(f"[DEBUG] 浼氳瘽 {username}: 璇诲彇鍒?{len(messages_data)} 鏉℃秷鎭?)
                    
                    # 鎵归噺鎻掑叆
                    batch = []
                    for msg_dict in messages_data:
                        conversations_set.add(msg_dict['talker'])
                        batch.append(msg_dict)
                        
                        # 姣?000鏉℃壒閲忔彃鍏?
                        if len(batch) >= 1000:
                            batch_stats = self._insert_message_batch(
                                batch,
                                conversation_cache,
                                touched_conversations
                            )
                            total_messages += batch_stats["inserted"]
                            skipped_messages += batch_stats["skipped"]
                            batch = []
                    
                    # 鎻掑叆鍓╀綑
                    if batch:
                        batch_stats = self._insert_message_batch(
                            batch,
                            conversation_cache,
                            touched_conversations
                        )
                        total_messages += batch_stats["inserted"]
                        skipped_messages += batch_stats["skipped"]
                
                except Exception as e:
                    # 鏌愪釜瀵硅瘽瀵煎叆澶辫触,璺宠繃缁х画
                    logger.error(f"[DEBUG] 瀵煎叆瀵硅瘽 {username} 澶辫触: {e}")
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
        """鎵归噺鎻掑叆娑堟伅"""
        inserted = 0
        skipped = 0
        db = get_db()
        for msg in messages:
            try:
                talker = msg['talker']
                
                # 鍐嶆杩囨护缇よ亰鍜屽叕浼楀彿(鍙岄噸淇濋櫓)
                if '@chatroom' in talker or talker.startswith('gh_'):
                    continue
                
                # 纭繚浼氳瘽瀛樺湪 (淇: 浣跨敤 username 瀛楁鑰屼笉鏄?name)
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
                
                # 鎻掑叆娑堟伅 (淇: 娣诲姞蹇呴渶鐨勫瓧娈?
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
                logger.error(f"[DEBUG] 鎻掑叆娑堟伅澶辫触: {e}")
                pass  # 蹇界暐鍗曟潯閿欒
        
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
        鑷姩棰勫鐞嗘柊瀵煎叆鐨勬秷鎭?
        
        Returns:
            棰勫鐞嗙殑娑堟伅鏁伴噺
        """
        try:
            logger.info(f"\n[棰勫鐞哴 寮€濮嬭嚜鍔ㄩ澶勭悊鏂板鍏ョ殑娑堟伅...")
            
            # 鏌ユ壘鏈澶勭悊鐨勬秷鎭紙涓嶅湪缂撳瓨琛ㄤ腑鐨勬秷鎭級
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
            
            logger.debug(f"[棰勫鐞哴 鎵惧埌 {len(unprocessed)} 鏉℃湭棰勫鐞嗙殑娑堟伅")
            
            # 鎸変細璇濆垎缁?
            conv_messages = {}
            for msg_id, conv_id in unprocessed:
                if conv_id not in conv_messages:
                    conv_messages[conv_id] = []
                conv_messages[conv_id].append(msg_id)
            
            logger.debug(f"[Preprocess] Conversations to preprocess: {len(conv_messages)}")
            
            # 鎵归噺棰勫鐞嗭紙姣忎釜浼氳瘽鐙珛澶勭悊锛?
            total_processed = 0
            for idx, (conv_id, message_ids) in enumerate(conv_messages.items()):
                if progress_callback:
                    progress = 95 + int((idx / len(conv_messages)) * 4)
                    progress_callback(f"棰勫鐞嗕細璇?{idx+1}/{len(conv_messages)}...", progress, 100)
                
                count = self.preprocessor.preprocess_message_batch(conv_id, message_ids)
                total_processed += count
            
            logger.info(f"[Preprocess] Completed preprocessing messages: {total_processed}")
            return total_processed

        except Exception as e:
            logger.error(f"[棰勫鐞哴 鑷姩棰勫鐞嗗け璐? {e}")
            import traceback
            traceback.print_exc()
            return 0

    def _auto_extract_features(
        self,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        鑷姩鎻愬彇鎵€鏈変細璇濈殑鐗瑰緛锛堜細璇濆垏鍒嗐€佸搷搴旀椂闂淬€佷富鍔ㄦ€с€佸瓧鏁扮粺璁★級

        Returns:
            鐗瑰緛鎻愬彇缁熻淇℃伅
        """
        try:
            logger.info(f"\n[鐗瑰緛鎻愬彇] 寮€濮嬭嚜鍔ㄧ壒寰佹彁鍙?..")

            # 寤惰繜瀵煎叆鐗瑰緛鎻愬彇鏈嶅姟锛堥伩鍏嶅惊鐜鍏ワ級
            from ..analysis.feature_extraction_service import FeatureExtractionService

            # 鏌ユ壘鎵€鏈夋湁娑堟伅鐨勪細璇?
            cursor = get_db().execute("""
                SELECT id, display_name, message_count
                FROM conversations
                WHERE message_count > 0
                ORDER BY message_count DESC
            """)

            conversations = cursor.fetchall()

            if not conversations:
                logger.debug(f"[鐗瑰緛鎻愬彇] 娌℃湁鎵惧埌浼氳瘽")
                return {
                    "total_conversations": 0,
                    "processed": 0,
                    "failed": 0
                }

            # logger.debug(f"[鐗瑰緛鎻愬彇] 鎵惧埌 {len(conversations)} 涓細璇?)

            # 鍒濆鍖栫壒寰佹彁鍙栨湇鍔?
            feature_service = FeatureExtractionService()

            # 鎵归噺鎻愬彇鐗瑰緛
            stats = {
                "total_conversations": len(conversations),
                "processed": 0,
                "failed": 0,
                "skipped": 0
            }

            for idx, (conv_id, name, msg_count) in enumerate(conversations):
                try:
                    # 鏄剧ず璇︾粏杩涘害锛堟槑纭槸"鑱旂郴浜?鑰屼笉鏄?浼氳瘽"锛?
                    logger.debug(f"[鐗瑰緛鎻愬彇] 鑱旂郴浜?{idx+1}/{len(conversations)} - {name} ({msg_count}鏉℃秷鎭?")

                    if progress_callback:
                        progress = 97 + int((idx / len(conversations)) * 3)
                        progress_callback(f"鎻愬彇鐗瑰緛 {idx+1}/{len(conversations)}: {name}", progress, 100)

                    # 妫€鏌ユ槸鍚﹀凡缁忔彁鍙栬繃鐗瑰緛
                    cursor = get_db().execute("""
                        SELECT COUNT(*) FROM sessions WHERE conversation_id = ?
                    """, (conv_id,))
                    session_count = cursor.fetchone()[0]

                    if session_count > 0:
                        logger.debug(f"  鈫?宸叉湁 {session_count} 涓細璇濊褰曪紝璺宠繃")
                        stats["skipped"] += 1
                        continue

                    # 鎵ц鐗瑰緛鎻愬彇锛堝垏鍒嗕細璇濓級
                    result = feature_service.extract_features(conv_id)

                    # 鏄剧ず鐢熸垚鐨勪細璇濇暟閲?
                    if result and "sessions" in result:
                        num_sessions = len(result["sessions"])
                        logger.info(f"  -> sessions generated: {num_sessions}")

                    stats["processed"] += 1

                except Exception as e:
                    logger.error(f"[鐗瑰緛鎻愬彇] 浼氳瘽 {conv_id} 鎻愬彇澶辫触: {e}")
                    stats["failed"] += 1
                    continue

            # 鏄剧ず瀹屾垚淇℃伅
            logger.error(f"[鐗瑰緛鎻愬彇] 瀹屾垚! 澶勭悊={stats['processed']}, 璺宠繃={stats['skipped']}, 澶辫触={stats['failed']}")

            return stats

        except Exception as e:
            logger.error(f"[鐗瑰緛鎻愬彇] 鑷姩鐗瑰緛鎻愬彇澶辫触: {e}")
            import traceback
            traceback.print_exc()
            return {
                "total_conversations": 0,
                "processed": 0,
                "failed": 0,
                "error": str(e)
            }
    
    def _create_import_record(self) -> int:
        """鍒涘缓瀵煎叆璁板綍"""
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
        """鏇存柊瀵煎叆璁板綍"""
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
            stats.get('messages', 0),  # 淇: messages涓嶆槸total_messages
            stats.get('conversations', 0),  # 淇: conversations涓嶆槸total_conversations
            error,
            int(time.time()),
            json.dumps(stats),
            import_id
        ))
        get_db().commit()
