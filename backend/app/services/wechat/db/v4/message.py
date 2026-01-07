"""微信 V4 版本 - 消息数据库"""

import sqlite3
import hashlib
import re
from typing import List, Optional, Tuple, Dict, Set
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
        self._my_wxid_candidates = self._build_my_wxid_candidates(my_wxid)
        self.connections = []
        self._table_columns_cache: Dict[str, Set[str]] = {}
        self._connect_all()

    
    def _build_my_wxid_candidates(self, wxid: Optional[str]) -> List[str]:
        """生成 my_wxid 可能的别名列表，处理目录名带后缀的情况"""
        candidates: List[str] = []
        if not wxid:
            return candidates
        candidates.append(wxid)
        # 兼容目录名形如 wxid_xxx_9cc7，去掉最后一段下划线+4~6位字母数字
        m = re.match(r"^(wxid_[a-z0-9]+)_([a-z0-9]{4,6})$", wxid)
        if m:
            base = m.group(1)
            if base not in candidates:
                candidates.append(base)
        return candidates

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
    
    def _get_table_columns(self, conn: sqlite3.Connection, table_name: str) -> Set[str]:
        """获取指定表的列名集合（缓存）"""
        cache_key = f"{id(conn)}::{table_name}"
        if cache_key in self._table_columns_cache:
            return self._table_columns_cache[cache_key]

        cols: Set[str] = set()
        try:
            cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
            for row in cursor:
                # row[1] 是列名
                cols.add(str(row[1]).lower())
        except Exception as e:
            print(f"[MessageDB Warning] 获取表结构失败 {table_name}: {e}")

        self._table_columns_cache[cache_key] = cols
        return cols
    
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
        - 优先使用微信原始表 isSend/is_sender 字段判定本人发送
        - 回退 Name2Id 表获取发送者 username 判定
        - 通过 create_time 过滤时间范围
        - 按 sort_seq 排序
        """
        # 检查可用列
        cols = self._get_table_columns(conn, table_name)
        has = lambda name: name.lower() in cols

        # 选择可用的 isSend 字段（支持多别名，使用 COALESCE 统一）
        candidate_cols = []
        for name in [
            "isSend",
            "is_send",
            "is_sender",
            "is_sender_",
            "is_send_",
            "computed_is_send",
            "issender",
        ]:
            if has(name):
                candidate_cols.append(name)

        is_send_select = "NULL AS is_send_flag"
        if candidate_cols:
            joined = ", ".join([f"msg.{col}" for col in candidate_cols])
            is_send_select = f"COALESCE({joined}) AS is_send_flag"


        # 解析 my_wxid 在当前库的 rowid（支持别名）
        my_rowid: Optional[int] = None
        if self._my_wxid_candidates:
            placeholders = ",".join(["?"] * len(self._my_wxid_candidates))
            try:
                cur = conn.execute(
                    f"SELECT rowid FROM Name2Id WHERE user_name IN ({placeholders}) LIMIT 1",
                    self._my_wxid_candidates,
                )
                row = cur.fetchone()
                if row and 'rowid' in row.keys():
                    my_rowid = row['rowid']
            except Exception:
                my_rowid = None

        # 构建SQL（加入 computed_is_send 以回退 Name2Id rowid 比对）
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
                {is_send_select},
                CASE
                    WHEN ? IS NOT NULL THEN (
                        CASE WHEN msg.real_sender_id = ? THEN 1 ELSE 0 END
                    )
                    ELSE NULL
                END AS computed_is_send,
                Name2Id.user_name AS sender_username
            FROM {table_name} AS msg
            LEFT JOIN Name2Id ON msg.real_sender_id = Name2Id.rowid
        """
        
        # 添加时间过滤
        conditions = []
        params = []
        
        # computed_is_send 依赖 my_rowid，占用前两个参数
        params.extend([my_rowid, my_rowid])

        
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
            sender_username = row['sender_username'] or ''
            raw_flag = row['is_send_flag']
            computed_raw = row['computed_is_send']

            def _normalize_flag(value: Optional[object]) -> Optional[int]:
                if value is None:
                    return None
                if isinstance(value, bool):
                    return 1 if value else 0
                try:
                    return int(value)
                except Exception:
                    return None

            is_send_flag: Optional[int] = _normalize_flag(raw_flag)
            computed_flag: Optional[int] = _normalize_flag(computed_raw)

            # 判定本人发送优先级：isSend 标记 > computed_is_send (real_sender_id 对比) > Name2Id username 比对 > 简单回退
            if is_send_flag is not None:
                is_sender = is_send_flag != 0
            elif computed_flag is not None:
                is_sender = computed_flag != 0
            elif sender_username:
                if self._my_wxid_candidates:
                    is_sender = sender_username in self._my_wxid_candidates
                elif self.my_wxid:
                    is_sender = (sender_username == self.my_wxid)
                else:
                    # 无 my_wxid 时，若发送者不是对话对象，推断为本人
                    is_sender = (sender_username != username)
            else:
                # 无法判定，保守为接收
                is_sender = False


            # 调试：仅记录第一条消息的判断信息
            if len(messages) == 0:
                print(
                    f"[MessageDB] 首条消息: real_sender_id={row['real_sender_id']}, "
                    f"sender_username='{sender_username}', is_send_flag={raw_flag}, "
                    f"computed_is_send={computed_raw}, my_wxid='{self.my_wxid}', is_sender={is_sender}"
                )



            # 提取内容
            content = row['message_content'] or ''
            
            # 如果是压缩内容(protobuf),需要解析
            if not content and row['compress_content']:
                content = self._parse_compress_content(row['compress_content'])
            
            message = {
                'local_id': row['local_id'],
                'talker': username,
                'sender': sender_username,
                'is_sender': 1 if is_sender else 0,
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
        
        通过扫描 Name2Id 表实现,并过滤群聊和公众号
        
        Returns:
            List[str]: username列表(不包括群聊和公众号)
        """
        usernames = set()
        
        for conn in self.connections:
            try:
                cursor = conn.execute("SELECT user_name FROM Name2Id")
                for row in cursor:
                    username = row['user_name']
                    if username:
                        # 过滤群聊和公众号
                        if '@chatroom' not in username and not username.startswith('gh_'):
                            usernames.add(username)
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
