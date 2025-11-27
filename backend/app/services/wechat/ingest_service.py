"""微信V4数据导入服务 (仅支持4.0+版本)"""
import time
from typing import Dict, Any, Optional, Callable
from .path_finder import WeChatPathFinder
from .db_decryptor import WeChatDBDecryptor
from .db.v4.contact import ContactDBV4
from .db.v4.message import MessageDBV4
from ...db.connection import get_db


class WeChatIngestService:
    """微信V4数据导入服务"""
    
    def __init__(self):
        self.db = get_db()
    
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
            
            # 4. 更新导入记录
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
            for contact_dict in contacts_data:
                try:
                    self.db.execute("""
                        INSERT OR REPLACE INTO contacts 
                        (username, nickname, remark, alias, phone, is_friend, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        contact_dict['username'],
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
            print(f"[DEBUG] 成功插入 {inserted} 个联系人")
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
        
        return {
            "total": total_messages,
            "conversations": len(conversations_set)
        }
    
    def _insert_message_batch(self, messages: list, wxid: str):
        """批量插入消息"""
        for msg in messages:
            try:
                # 确保会话存在
                self.db.execute("""
                    INSERT OR IGNORE INTO conversations (name, platform, created_at)
                    VALUES (?, 'wechat', ?)
                """, (msg['talker'], int(time.time())))
                
                # 获取conversation_id
                cursor = self.db.execute(
                    "SELECT id FROM conversations WHERE name = ? AND platform = 'wechat'",
                    (msg['talker'],)
                )
                row = cursor.fetchone()
                if not row:
                    continue
                
                conversation_id = row[0]
                
                # 插入消息
                role = "assistant" if msg['is_sender'] else "user"
                
                self.db.execute("""
                    INSERT OR IGNORE INTO messages 
                    (conversation_id, role, ts, content, source)
                    VALUES (?, ?, ?, ?, 'long')
                """, (
                    conversation_id,
                    role,
                    msg['timestamp'],
                    msg['content']
                ))
            
            except Exception:
                pass  # 忽略单条错误
        
        self.db.commit()
    
    def _create_import_record(self) -> int:
        """创建导入记录"""
        cursor = self.db.execute("""
            INSERT INTO import_records (import_type, status, started_at)
            VALUES ('wechat_full', 'pending', ?)
        """, (int(time.time()),))
        self.db.commit()
        return cursor.lastrowid
    
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
