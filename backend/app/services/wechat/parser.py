"""微信数据库解析模块"""
from typing import List, Dict, Any, Optional, Generator
from dataclasses import dataclass
import hashlib


@dataclass
class Contact:
    """联系人数据结构"""
    username: str
    nickname: Optional[str] = None
    remark: Optional[str] = None
    alias: Optional[str] = None
    phone: Optional[str] = None
    is_friend: bool = True
    
    @property
    def display_name(self) -> str:
        """显示名称（备注 > 昵称 > username）"""
        return self.remark or self.nickname or self.username


@dataclass
class Message:
    """消息数据结构"""
    local_id: int
    talker: str              # 对话对象username（群聊时为群ID）
    sender: Optional[str]    # 实际发送者username（群聊时有效）
    is_sender: bool          # 是否为本人发送
    message_type: int        # 消息类型
    content: str             # 消息内容
    timestamp: int           # Unix时间戳（秒）
    media_path: Optional[str] = None
    
    @property
    def conversation_id(self) -> str:
        """会话标识符（用于分组）"""
        return self.talker


class WeChatDBParser:
    """微信数据库解析器"""
    
    # 消息类型枚举
    MSG_TYPE_TEXT = 1
    MSG_TYPE_IMAGE = 3
    MSG_TYPE_VOICE = 34
    MSG_TYPE_VIDEO = 43
    MSG_TYPE_EMOJI = 47
    MSG_TYPE_LINK = 49
    
    def __init__(self, conn, my_wxid: Optional[str] = None):
        """
        初始化解析器
        
        Args:
            conn: 数据库连接
            my_wxid: 当前用户wxid（用于判断is_sender）
        """
        self.conn = conn
        self.my_wxid = my_wxid
    
    def parse_contacts(self, limit: Optional[int] = None) -> List[Contact]:
        """
        解析联系人表
        
        Args:
            limit: 限制数量
            
        Returns:
            List[Contact]: 联系人列表
        """
        sql = """
            SELECT username, nick_name, remark, alias, phone_number, type
            FROM contact
            WHERE delete_flag = 0
            ORDER BY remark, nick_name
        """
        
        if limit:
            sql += f" LIMIT {limit}"
        
        cursor = self.conn.execute(sql)
        contacts = []
        
        for row in cursor:
            # 判断是否为好友（type字段bit 0x1表示好友）
            is_friend = bool(row['type'] & 0x1) if row['type'] else False
            
            contacts.append(Contact(
                username=row['username'],
                nickname=row['nick_name'],
                remark=row['remark'],
                alias=row['alias'],
                phone=row['phone_number'] if 'phone_number' in row.keys() else None,
                is_friend=is_friend
            ))
        
        return contacts
    
    def parse_messages(
        self,
        table_name: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> Generator[Message, None, None]:
        """
        解析消息表（生成器，避免大量数据OOM）
        
        Args:
            table_name: 消息表名（如 Msg_{md5}）
            limit: 限制数量
            offset: 偏移量
            
        Yields:
            Message: 消息对象
        """
        sql = f"""
            SELECT 
                m.local_id,
                m.real_sender_id,
                m.local_type,
                m.message_content,
                m.compress_content,
                m.create_time,
                n.user_name AS sender_username
            FROM {table_name} m
            LEFT JOIN Name2Id n ON m.real_sender_id = n.rowid
            ORDER BY m.create_time DESC
        """
        
        if limit:
            sql += f" LIMIT {limit} OFFSET {offset}"
        
        cursor = self.conn.execute(sql)
        
        for row in cursor:
            # 判断是否为本人发送
            is_sender = False
            if self.my_wxid and row['sender_username']:
                is_sender = (row['sender_username'] == self.my_wxid)
            
            # 提取消息内容
            content = row['message_content'] or row['compress_content'] or ""
            
            # 从表名推断对话对象（Msg_{md5} -> username）
            # 注意：实际使用中需要从 Name2Id 表反查，这里简化处理
            talker = self._extract_talker_from_table(table_name)
            
            yield Message(
                local_id=row['local_id'],
                talker=talker,
                sender=row['sender_username'],
                is_sender=is_sender,
                message_type=row['local_type'],
                content=content,
                timestamp=row['create_time']
            )
    
    def get_conversation_table_name(self, username: str) -> Optional[str]:
        """
        根据username查找对应的消息表名
        
        Args:
            username: 对话对象username
            
        Returns:
            str: 表名（如 Msg_xxx），未找到返回None
        """
        # 计算username的MD5
        md5_hash = hashlib.md5(username.encode()).hexdigest()
        expected_table = f"Msg_{md5_hash}"
        
        # 检查表是否存在
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )
        
        tables = [row[0] for row in cursor]
        
        # 精确匹配
        if expected_table in tables:
            return expected_table
        
        # 模糊匹配（大小写、前缀）
        for table in tables:
            if table.lower() == expected_table.lower():
                return table
        
        return None
    
    def get_message_count(self, table_name: str) -> int:
        """获取消息表的消息总数"""
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
    
    def _extract_talker_from_table(self, table_name: str) -> str:
        """
        从消息表名推断对话对象（简化处理）
        实际应从 Name2Id 表反查
        """
        # 简化：直接返回表名作为标识
        return table_name.replace("Msg_", "")
    
    def get_all_message_tables(self) -> List[str]:
        """获取所有消息表名"""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )
        return [row[0] for row in cursor]
