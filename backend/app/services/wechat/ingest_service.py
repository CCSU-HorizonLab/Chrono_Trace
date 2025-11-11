"""微信数据导入服务（整合路径查找、解密、解析、入库）"""
import time
from typing import Dict, Any, Optional, Callable
from .path_finder import WeChatPathFinder
from .db_decryptor import WeChatDBDecryptor
from .parser import WeChatDBParser, Contact, Message
from ...db.connection import get_db


class WeChatIngestService:
    """微信数据导入服务"""
    
    def __init__(self):
        self.db = get_db()
    
    def get_wechat_paths(self) -> Dict[str, Any]:
        """
        获取微信数据库路径信息（供前端展示）
        
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
                    "error": "未找到微信数据目录，请确保微信已安装并登录"
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
                return {"ok": False, "error": "未找到消息数据库"}
            
            # 验证密钥
            is_valid = WeChatDBDecryptor.verify_key(message_dbs[0], db_key)
            
            if is_valid:
                return {"ok": True}
            else:
                return {"ok": False, "error": "密钥错误，无法解密数据库"}
        
        except Exception as e:
            return {"ok": False, "error": f"验证失败: {str(e)}"}
    
    def import_wechat_data(
        self,
        db_key: str,
        options: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        完整的微信数据导入流程
        
        Args:
            db_key: 32位hex密钥
            options: 导入选项 {
                "import_contacts": bool,    # 是否导入联系人
                "import_messages": bool,    # 是否导入消息
                "limit": int                # 消息数量限制（0=全部）
            }
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
            # 1. 查找数据库路径
            if progress_callback:
                progress_callback("查找数据库路径...", 0, 100)
            
            paths = WeChatPathFinder.find_all_wechat_dbs()
            if not paths:
                raise Exception("未找到微信数据库")
            
            wxid = paths["current_user"]
            databases = paths["databases"]
            
            # 2. 导入联系人（如果有contact.db）
            if import_contacts and databases.get("contact"):
                if progress_callback:
                    progress_callback("导入联系人...", 10, 100)
                
                contact_count = self._import_contacts(
                    databases["contact"],
                    db_key
                )
                stats["contacts"] = contact_count
            
            # 3. 导入消息
            if import_messages and databases.get("message"):
                if progress_callback:
                    progress_callback("导入消息...", 30, 100)
                
                message_stats = self._import_messages(
                    databases["message"],
                    db_key,
                    wxid,
                    limit,
                    progress_callback
                )
                
                stats["messages"] = message_stats["total"]
                stats["conversations"] = message_stats["conversations"]
            
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
    
    def _import_contacts(self, contact_db_path: str, db_key: str) -> int:
        """导入联系人"""
        conn = WeChatDBDecryptor.open_encrypted_db(contact_db_path, db_key)
        
        try:
            parser = WeChatDBParser(conn)
            contacts = parser.parse_contacts()
            
            # 批量插入联系人
            inserted = 0
            for contact in contacts:
                try:
                    self.db.execute("""
                        INSERT OR REPLACE INTO contacts 
                        (username, nickname, remark, alias, phone, is_friend, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        contact.username,
                        contact.nickname,
                        contact.remark,
                        contact.alias,
                        contact.phone,
                        1 if contact.is_friend else 0,
                        int(time.time())
                    ))
                    inserted += 1
                except Exception:
                    pass  # 忽略单条错误
            
            self.db.commit()
            return inserted
        
        finally:
            conn.close()
    
    def _import_messages(
        self,
        message_db_paths: list,
        db_key: str,
        wxid: str,
        limit: int,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """导入消息"""
        total_messages = 0
        conversations_set = set()
        
        # 处理所有消息数据库
        for db_path in message_db_paths:
            conn = WeChatDBDecryptor.open_encrypted_db(db_path, db_key)
            
            try:
                parser = WeChatDBParser(conn, my_wxid=wxid)
                
                # 获取所有消息表
                tables = parser.get_all_message_tables()
                
                for idx, table in enumerate(tables):
                    if progress_callback:
                        progress = 30 + int((idx / len(tables)) * 60)
                        progress_callback(f"导入消息表 {idx+1}/{len(tables)}...", progress, 100)
                    
                    # 解析消息
                    messages = parser.parse_messages(table, limit=limit)
                    
                    # 批量插入
                    batch = []
                    for msg in messages:
                        conversations_set.add(msg.talker)
                        batch.append(msg)
                        
                        # 每1000条批量插入
                        if len(batch) >= 1000:
                            self._insert_message_batch(batch, wxid)
                            total_messages += len(batch)
                            batch = []
                    
                    # 插入剩余
                    if batch:
                        self._insert_message_batch(batch, wxid)
                        total_messages += len(batch)
            
            finally:
                conn.close()
        
        return {
            "total": total_messages,
            "conversations": len(conversations_set)
        }
    
    def _insert_message_batch(self, messages: list, wxid: str):
        """批量插入消息"""
        for msg in messages:
            # 获取或创建会话
            conversation_id = self._get_or_create_conversation(msg.talker)
            
            # 插入消息
            try:
                self.db.execute("""
                    INSERT INTO messages 
                    (conversation_id, local_id, talker, sender, is_sender, 
                     message_type, content, timestamp, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    msg.local_id,
                    msg.talker,
                    msg.sender,
                    1 if msg.is_sender else 0,
                    msg.message_type,
                    msg.content,
                    msg.timestamp,
                    "long",  # 长期导入
                    int(time.time())
                ))
            except Exception:
                pass  # 忽略重复等错误
        
        self.db.commit()
    
    def _get_or_create_conversation(self, username: str) -> int:
        """获取或创建会话"""
        cursor = self.db.execute(
            "SELECT id FROM conversations WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        
        if row:
            return row['id']
        
        # 创建新会话
        cursor = self.db.execute("""
            INSERT INTO conversations 
            (username, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (
            username,
            username,  # 默认使用username，后续可更新
            int(time.time()),
            int(time.time())
        ))
        
        self.db.commit()
        return cursor.lastrowid
    
    def _create_import_record(self) -> int:
        """创建导入记录"""
        cursor = self.db.execute("""
            INSERT INTO import_records (import_type, status, started_at)
            VALUES (?, ?, ?)
        """, ("wechat_full", "pending", int(time.time())))
        
        self.db.commit()
        return cursor.lastrowid
    
    def _update_import_record(
        self,
        import_id: int,
        status: str,
        stats: Dict,
        error_message: Optional[str] = None
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
            stats.get("messages", 0),
            stats.get("conversations", 0),
            error_message,
            int(time.time()),
            json.dumps(stats),
            import_id
        ))
        
        self.db.commit()
