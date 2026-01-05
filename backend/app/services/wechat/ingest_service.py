"""微信V4数据导入服务 (仅支持4.0+版本)"""
import time
from typing import Dict, Any, Optional, Callable
from .path_finder import WeChatPathFinder
from .db_decryptor import WeChatDBDecryptor
from .db.v4.contact import ContactDBV4
from .db.v4.message import MessageDBV4
from ...db.connection import get_db
from ..analysis.preprocessing_service import PreprocessingService


class WeChatIngestService:
    """微信V4数据导入服务"""
    
    def __init__(self):
        self.db = get_db()
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
            "conversations": 0
        }
        
        # 创建导入记录
        import_id = self._create_import_record()
        
        try:
            # 1. 获取数据库路径
            if progress_callback:
                progress_callback("查找数据库路径...", 0, 100)
            
            print(f"\n[DEBUG] === 开始导入流程 ===")
            print(f"[DEBUG] custom_paths: {custom_paths}")
            
            if custom_paths and custom_paths.get("wechat_dir") and custom_paths.get("current_user"):
                # 使用自定义路径,但重新查找数据库文件
                wechat_dir = custom_paths["wechat_dir"]
                wxid = custom_paths["current_user"]
                print(f"[DEBUG] 使用自定义路径: {wechat_dir}")
                print(f"[DEBUG] 用户wxid: {wxid}")
                
                # 重新查找该wxid下的所有数据库文件
                databases = WeChatPathFinder.find_databases(wxid, wechat_dir)
                print(f"[DEBUG] 重新查找到的数据库: {databases}")
                
                paths = {
                    "wechat_dir": wechat_dir,
                    "current_user": wxid,
                    "databases": databases
                }
            else:
                # 自动检测
                print(f"[DEBUG] 开始自动检测微信路径...")
                paths = WeChatPathFinder.find_all_wechat_dbs()
                print(f"[DEBUG] 自动检测结果: {paths}")
                
                if not paths:
                    raise Exception("未找到微信数据库,请在设置中手动指定路径")
                
                wxid = paths["current_user"]
                databases = paths["databases"]
            
            print(f"[DEBUG] wxid: {wxid}")
            print(f"[DEBUG] databases: {databases}")
            
            # 2. 导入联系人
            print(f"\n[DEBUG] import_contacts={import_contacts}, has contact db={databases.get('contact')}")
            if import_contacts and databases.get("contact"):
                if progress_callback:
                    progress_callback("导入联系人...", 10, 100)
                
                contact_count = self._import_contacts_v4(
                    databases["contact"],
                    db_key
                )
                stats["contacts"] = contact_count
                print(f"[DEBUG] 联系人导入结果: {contact_count}")
            
            # 3. 导入消息
            print(f"\n[DEBUG] import_messages={import_messages}, message dbs={databases.get('message')}")
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
                print(f"[DEBUG] 消息导入结果: {message_stats}")
            
            print(f"\n[DEBUG] 最终统计: {stats}")
            
            # 4. 自动预处理消息
            if stats["messages"] > 0 and import_messages:
                if progress_callback:
                    progress_callback("预处理消息数据...", 95, 100)
                
                preprocessed_count = self._auto_preprocess_messages(progress_callback)
                stats["preprocessed"] = preprocessed_count
                print(f"[DEBUG] 预处理完成: {preprocessed_count} 条消息")
            
            # 5. 更新导入记录
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
        print(f"\n[DEBUG] 开始导入联系人")
        print(f"[DEBUG] 联系人数据库路径: {contact_db_path}")
        
        contact_db = ContactDBV4(contact_db_path, db_key)
        
        try:
            contacts_data = contact_db.get_contacts()
            print(f"[DEBUG] 从数据库读取到 {len(contacts_data)} 个联系人")
            
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
                    self.db.execute("""
                        INSERT OR REPLACE INTO contacts 
                        (username, nickname, remark, alias, phone, is_friend, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        username,
                        contact_dict['nickname'],
                        contact_dict['remark'],
                        contact_dict['alias'],
                        contact_dict['phone'],
                        1 if contact_dict['is_friend'] else 0,
                        int(time.time())
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"[DEBUG] 插入联系人失败: {e}")
                    pass  # 忽略单条错误
            
            self.db.commit()
            print(f"[DEBUG] 成功插入 {inserted} 个联系人, 跳过 {skipped} 个群聊/公众号")
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
        print(f"\n[DEBUG] 开始导入消息")
        print(f"[DEBUG] 消息数据库数量: {len(message_db_paths)}")
        print(f"[DEBUG] 我的wxid: {wxid}")
        
        total_messages = 0
        conversations_set = set()
        skipped_conversations = 0
        
        message_db = MessageDBV4(message_db_paths, db_key, my_wxid=wxid)
        
        try:
            if progress_callback:
                progress_callback("扫描消息表...", 30, 100)
            
            # 获取所有对话username
            all_usernames = message_db.get_all_conversation_usernames()
            print(f"[DEBUG] 找到 {len(all_usernames)} 个会话")
            
            if len(all_usernames) > 0:
                print(f"[DEBUG] 前3个会话: {all_usernames[:3]}")
             
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
                    
                    print(f"[DEBUG] 会话 {username}: 读取到 {len(messages_data)} 条消息")
                    
                    # 批量插入
                    batch = []
                    for msg_dict in messages_data:
                        conversations_set.add(msg_dict['talker'])
                        batch.append(msg_dict)
                        
                        # 每1000条批量插入
                        if len(batch) >= 1000:
                            self._insert_message_batch(batch, wxid)
                            total_messages += len(batch)
                            batch = []
                    
                    # 插入剩余
                    if batch:
                        self._insert_message_batch(batch, wxid)
                        total_messages += len(batch)
                
                except Exception as e:
                    # 某个对话导入失败,跳过继续
                    print(f"[DEBUG] 导入对话 {username} 失败: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
        
        finally:
            message_db.close()
        
        print(f"[DEBUG] 消息导入完成: 总计 {total_messages} 条, {len(conversations_set)} 个会话")
        print(f"[DEBUG] 跳过 {skipped_conversations} 个群聊/公众号会话")
        
        return {"total": total_messages,"conversations": len(conversations_set)}  
    
    def _insert_message_batch(self, messages: list, wxid: str):  # pyright: ignore[reportMissingTypeArgument]
        """批量插入消息"""
        for msg in messages:
            try:
                talker = msg['talker']
                
                # 再次过滤群聊和公众号(双重保险)
                if '@chatroom' in talker or talker.startswith('gh_'):
                    continue
                
                # 确保会话存在 (修复: 使用 username 字段而不是 name)
                self.db.execute("""
                    INSERT OR IGNORE INTO conversations (username, display_name, platform, created_at, updated_at, message_count)
                    VALUES (?, ?, 'wechat', ?, ?, 0)
                """, (talker, talker, int(time.time()), int(time.time())))
                
                # 获取conversation_id (修复: 使用 username 字段)
                cursor = self.db.execute(
                    "SELECT id FROM conversations WHERE username = ? AND platform = 'wechat'",
                    (talker,)
                )
                row = cursor.fetchone()
                if not row:
                    continue
                
                conversation_id = row[0]
                
                # 插入消息 (修复: 添加必需的字段)
                is_sender = 1 if msg['is_sender'] else 0
                
                self.db.execute("""
                    INSERT OR IGNORE INTO messages 
                    (conversation_id, talker, sender, is_sender, message_type, content, timestamp, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'long', ?)
                """, (  
                    conversation_id,
                    talker,
                    msg.get('sender', ''),
                    is_sender,
                    msg.get('message_type', 1),
                    msg['content'],
                    msg['timestamp'],
                    int(time.time())
                ))
                # 更新会话消息计数和更新时间
                self.db.execute(""" 
                    UPDATE conversations 
                    SET message_count = message_count + 1,
                        updated_at = ?
                    WHERE id = ?
                """, 
                (msg['timestamp'], conversation_id)) # pyright: ignore[reportUnusedCallResult]
            
            except Exception as e:
                print(f"[DEBUG] 插入消息失败: {e}")
                pass  # 忽略单条错误
        
        self.db.commit()
    
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
            print(f"\n[预处理] 开始自动预处理新导入的消息...")
            
            # 查找未预处理的消息（不在缓存表中的消息）
            cursor = self.db.execute("""
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
                print(f"[预处理] 没有需要预处理的消息")
                return 0
            
            print(f"[预处理] 找到 {len(unprocessed)} 条未预处理的消息")
            
            # 按会话分组
            conv_messages = {}
            for msg_id, conv_id in unprocessed:
                if conv_id not in conv_messages:
                    conv_messages[conv_id] = []
                conv_messages[conv_id].append(msg_id)
            
            print(f"[预处理] 涉及 {len(conv_messages)} 个会话")
            
            # 批量预处理（每个会话独立处理）
            total_processed = 0
            for idx, (conv_id, message_ids) in enumerate(conv_messages.items()):
                if progress_callback:
                    progress = 95 + int((idx / len(conv_messages)) * 4)
                    progress_callback(f"预处理会话 {idx+1}/{len(conv_messages)}...", progress, 100)
                
                count = self.preprocessor.preprocess_message_batch(conv_id, message_ids)
                total_processed += count
            
            print(f"[预处理] 完成! 共预处理 {total_processed} 条消息")
            return total_processed
        
        except Exception as e:
            print(f"[预处理] 自动预处理失败: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def _create_import_record(self) -> int:
        """创建导入记录"""
        cursor = self.db.execute("""
            INSERT INTO import_records (import_type, status, started_at)
            VALUES ('wechat_full', 'pending', ?)
        """, (int(time.time()),))
        self.db.commit()
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
        
        self.db.execute("""
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
        self.db.commit()
