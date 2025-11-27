"""微信 V4 版本 - 消息数据库"""

import sqlite3
import hashlib
from typing import List, Optional, Tuple
from ..base import WeChatDBBase


class MessageDBV4(WeChatDBBase):
    """微信 V4 消息数据库访问类
    
    数据库路径: WeChat Files/wxid_xxx/message/message_*.db
    主表: Msg_{MD5(username)}
    辅助表: Name2Id (username <-> rowid 映射)
    """
    
    def __init__(self, db_paths: List[str], db_key: str = None, my_wxid: str = None):
        """
        初始化消息数据库(可能有多个分片)
        
        Args:
            db_paths: message_*.db 文件路径列表
            db_key: 数据库密钥(如果需要解密)
            my_wxid: 当前用户wxid(用于判断is_sender)
        """
        self.db_paths = db_paths if isinstance(db_paths, list) else [db_paths]
        self.db_key = db_key
        self.my_wxid = my_wxid
        self.connections = []
        self._connect_all()
    
    def _connect_all(self):
        """连接所有数据库分片"""
        import tempfile
        
        self.temp_db_paths = []  # 存储临时文件路径
        
        for idx, db_path in enumerate(self.db_paths):
            print(f"[DEBUG MessageDB] 连接数据库 {idx+1}/{len(self.db_paths)}: {db_path}")
            
            if self.db_key:
                # 使用新的纯Python解密器
                from ...db_decryptor_v2 import WeChatDBDecryptorV2
                decryptor = WeChatDBDecryptorV2()
                
                # 验证密钥
                if not decryptor.verify_key_from_file(db_path, self.db_key):
                    print(f"[WARN] 跳过: 密钥验证失败 {db_path}")
                    continue
                
                print(f"[DEBUG MessageDB] ✅ 密钥验证成功")
                
                # 解密到临时文件
                temp_path = tempfile.mktemp(suffix=f'_message_{idx}.db')
                self.temp_db_paths.append(temp_path)
                
                print(f"[DEBUG MessageDB] 解密到: {temp_path}")
                decryptor.decrypt_database(db_path, temp_path, self.db_key)
                print(f"[DEBUG MessageDB] ✅ 解密完成")
                
                # 连接解密后的数据库
                conn = sqlite3.connect(temp_path)
                conn.row_factory = sqlite3.Row
            else:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
            
            self.connections.append(conn)
    
    def get_table_name(self, username: str) -> str:
        """
        生成消息表名
        
        规则: Msg_{MD5(username)}
        
        Args:
            username: 对话对象的 wxid
            
        Returns:
            str: 表名 (如 Msg_5d41402abc4b2a76b9719d911017c592)
            
        示例:
            username = "wxid_abc123"
            -> MD5 = "5d41402abc4b2a76b9719d911017c592"
            -> table_name = "Msg_5d41402abc4b2a76b9719d911017c592"
        """
        md5_hash = hashlib.md5(username.encode('utf-8')).hexdigest()
        return f"Msg_{md5_hash}"
    
    def get_messages(
        self,
        username: str,
        time_range: Optional[Tuple[int, int]] = None,
        limit: Optional[int] = None
    ) -> List[dict]:
        """
        获取指定用户的消息记录
        
        Args:
            username: 对话对象username
            time_range: 时间范围 (start_timestamp, end_timestamp)
            limit: 限制数量
            
        Returns:
            List[dict]: 消息列表
        """
        table_name = self.get_table_name(username)
        messages = []
        
        # 在所有数据库分片中查找
        for conn in self.connections:
            try:
                msgs = self._query_messages_from_db(
                    conn, table_name, username, time_range, limit
                )
                messages.extend(msgs)
            except sqlite3.OperationalError:
                # 表不存在,尝试下一个数据库
                continue
        
        # 按时间排序
        messages.sort(key=lambda m: m['timestamp'])
        
        # 应用限制
        if limit and len(messages) > limit:
            messages = messages[:limit]
        
        return messages
    
    def _query_messages_from_db(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        username: str,
        time_range: Optional[Tuple[int, int]],
        limit: Optional[int]
    ) -> List[dict]:
        """
        从单个数据库查询消息
        
        核心SQL逻辑:
        - JOIN Name2Id 表获取发送者username
        - 通过 create_time 过滤时间范围
        - 按 sort_seq 排序
        """
        # 构建SQL
        sql = f"""
            SELECT 
                msg.local_id,
                msg.server_id,
                msg.local_type,
                msg.sort_seq,
                msg.real_sender_id,
                msg.create_time,
                msg.message_content,
                msg.compress_content,
                Name2Id.user_name AS sender_username
            FROM {table_name} AS msg
            LEFT JOIN Name2Id ON msg.real_sender_id = Name2Id.rowid
        """
        
        # 添加时间过滤
        conditions = []
        params = []
        
        if time_range:
            start_ts, end_ts = time_range
            conditions.append("msg.create_time >= ?")
            conditions.append("msg.create_time <= ?")
            params.extend([start_ts, end_ts])
        
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY msg.sort_seq ASC"
        
        if limit:
            sql += f" LIMIT {limit}"
        
        # 执行查询
        cursor = conn.execute(sql, params)
        messages = []
        
        for row in cursor:
            # 判断是否为本人发送
            sender_username = row['sender_username'] or ''
            is_sender = (sender_username == self.my_wxid) if self.my_wxid else False
            
            # 提取内容
            content = row['message_content'] or ''
            
            # 如果是压缩内容(protobuf),需要解析
            if not content and row['compress_content']:
                content = self._parse_compress_content(row['compress_content'])
            
            message = {
                'local_id': row['local_id'],
                'talker': username,
                'sender': sender_username,
                'is_sender': is_sender,
                'message_type': row['local_type'],
                'content': content,
                'timestamp': row['create_time'],
                'media_path': None
            }
            
            messages.append(message)
        
        return messages
    
    def _parse_compress_content(self, buffer: bytes) -> str:
        """
        解析压缩内容(protobuf格式)
        
        Args:
            buffer: protobuf 二进制数据
            
        Returns:
            str: 解析后的文本内容
        """
        # TODO: 实现 protobuf 解析
        # 目前简化处理,返回占位符
        try:
            return buffer.decode('utf-8', errors='ignore')
        except:
            return '[媒体消息]'
    
    def get_all_conversation_usernames(self) -> List[str]:
        """
        获取所有对话的username列表
        
        通过扫描 Name2Id 表实现
        
        Returns:
            List[str]: username列表
        """
        usernames = set()
        
        for conn in self.connections:
            try:
                cursor = conn.execute("SELECT user_name FROM Name2Id")
                for row in cursor:
                    if row['user_name']:
                        usernames.add(row['user_name'])
            except:
                continue
        
        return list(usernames)
    
    def get_all_message_tables(self) -> List[str]:
        """
        获取所有消息表名
        
        Returns:
            List[str]: 表名列表 (如 ['Msg_xxx', 'Msg_yyy'])
        """
        tables = set()
        
        for conn in self.connections:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            )
            for row in cursor:
                tables.add(row['name'])
        
        return list(tables)
    
    def get_contacts(self) -> List[dict]:
        """
        消息数据库不存储联系人信息
        此方法保留以符合基类接口
        """
        return []
    
    def get_contact_by_username(self, username: str) -> Optional[dict]:
        """
        消息数据库不存储联系人信息
        此方法保留以符合基类接口
        """
        return None
    
    def close(self):
        """关闭所有数据库连接"""
        for conn in self.connections:
            if conn:
                conn.close()
        self.connections = []
        
        # 清理临时文件
        if hasattr(self, 'temp_db_paths'):
            import os
            for temp_path in self.temp_db_paths:
                try:
                    os.remove(temp_path)
                    print(f"[DEBUG MessageDB] 已删除临时文件: {temp_path}")
                except Exception as e:
                    print(f"[DEBUG MessageDB] 删除临时文件失败: {e}")
