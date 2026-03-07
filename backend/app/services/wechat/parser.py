"""微信V4数据库解析模块 (仅支持4.0+版本)"""
from typing import List, Optional, Generator
from dataclasses import dataclass
import sqlite3
import logging


logger = logging.getLogger(__name__)
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
        """显示名称(备注 > 昵称 > username)"""
        return self.remark or self.nickname or self.username


@dataclass
class Message:
    """消息数据结构"""
    local_id: int
    talker: str              # 对话对象username
    sender: Optional[str]    # 实际发送者username
    is_sender: bool          # 是否为本人发送
    message_type: int        # 消息类型
    content: str             # 消息内容
    timestamp: int           # Unix时间戳(秒)
    media_path: Optional[str] = None
    
    @property
    def conversation_id(self) -> str:
        """会话标识符"""
        return self.talker


class WeChatDBParser:
    """微信V4数据库解析器"""
    
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
            my_wxid: 当前用户wxid
        """
        self.conn = conn
        self.my_wxid = my_wxid
    
    def parse_contacts(self, limit: Optional[int] = None) -> List[Contact]:
        """
        解析联系人表 (V4标准结构)
        
        表名: contact
        字段: username, nick_name, remark, alias, local_type
        
        Args:
            limit: 限制数量
            
        Returns:
            List[Contact]: 联系人列表
        """
        sql = """
            SELECT 
                username,
                nick_name,
                remark,
                alias,
                local_type
            FROM contact
            WHERE local_type IN (1, 2, 5)
            ORDER BY 
                CASE 
                    WHEN remark_quan_pin = '' THEN quan_pin
                    ELSE remark_quan_pin
                END ASC
        """
        
        if limit:
            sql += f" LIMIT {limit}"
        
        try:
            cursor = self.conn.execute(sql)
            contacts = []
            
            for row in cursor:
                row_dict = dict(row)
                contacts.append(Contact(
                    username=row_dict.get('username', ''),
                    nickname=row_dict.get('nick_name'),
                    remark=row_dict.get('remark'),
                    alias=row_dict.get('alias'),
                    phone=None,  # V4不直接存储电话
                    is_friend=row_dict.get('local_type') == 1
                ))
            
            return contacts
        except sqlite3.OperationalError as e:
            logger.error(f"解析联系人失败: {e}")
            return []
    
    def parse_messages(
        self,
        table_name: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> Generator[Message, None, None]:
        """
        解析消息表 (V4标准结构)
        
        表名格式: Msg_{MD5(username)}
        字段: local_id, real_sender_id, local_type, create_time, message_content
        辅助表: Name2Id (real_sender_id <-> user_name映射)
        
        Args:
            table_name: 消息表名
            limit: 限制数量
            offset: 偏移量
            
        Yields:
            Message: 消息对象
        """
        # 检查表是否存在
        try:
            cursor = self.conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"
            )
            if not cursor.fetchone():
                logger.warning(f"警告: 表 {table_name} 不存在")
                return
        except:
            return
        
        # V4标准SQL
        sql = f"""
            SELECT 
                msg.local_id,
                msg.local_type,
                msg.create_time,
                msg.message_content,
                msg.compress_content,
                Name2Id.user_name AS sender_username
            FROM {table_name} AS msg
            LEFT JOIN Name2Id ON msg.real_sender_id = Name2Id.rowid
            ORDER BY msg.create_time DESC
        """
        
        if limit:
            sql += f" LIMIT {limit} OFFSET {offset}"
        
        try:
            cursor = self.conn.execute(sql)
            
            # 从表名推断talker
            talker = self._extract_talker_from_table(table_name)
            
            for row in cursor:
                row_dict = dict(row)
                
                # 判断是否为本人发送
                sender_username = row_dict.get('sender_username')
                is_sender = False
                if self.my_wxid and sender_username:
                    is_sender = (sender_username == self.my_wxid)
                
                # 提取消息内容
                content = row_dict.get('message_content') or ''
                if not content and row_dict.get('compress_content'):
                    # 尝试解码压缩内容
                    try:
                        content = row_dict['compress_content'].decode('utf-8', errors='ignore')
                    except:
                        content = '[媒体消息]'
                
                yield Message(
                    local_id=row_dict['local_id'],
                    talker=talker,
                    sender=sender_username,
                    is_sender=is_sender,
                    message_type=row_dict.get('local_type', 1),
                    content=content,
                    timestamp=row_dict['create_time']
                )
        except sqlite3.OperationalError as e:
            logger.error(f"解析消息失败: {e}")
            return
    
    def get_all_message_tables(self) -> List[str]:
        """
        获取所有消息表名
        
        Returns:
            List[str]: 消息表名列表
        """
        cursor = self.conn.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' 
               AND name LIKE 'Msg_%'
               ORDER BY name"""
        )
        tables = [row[0] for row in cursor]
        return tables
    
    def get_message_count(self, table_name: str) -> int:
        """获取消息表的消息总数"""
        try:
            cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cursor.fetchone()[0]
        except:
            return 0
    
    def _extract_talker_from_table(self, table_name: str) -> str:
        """从消息表名推断对话对象"""
        # 简化:直接返回表名作为标识
        return table_name.replace("Msg_", "")
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
