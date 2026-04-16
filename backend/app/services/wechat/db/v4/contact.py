"""微信 V4 版本 - 联系人数据库"""
import logging

import sqlite3
from typing import List, Optional
from ..base import WeChatDBBase
from ...contact_filters import is_excluded_contact_username


logger = logging.getLogger(__name__)
class ContactDBV4(WeChatDBBase):
    """微信 V4 联系人数据库访问类
    
    数据库路径: WeChat Files/wxid_xxx/contact/contact.db
    主表: contact
    """
    
    def __init__(self, db_path: str, db_key: str = None):
        """
        初始化联系人数据库
        
        Args:
            db_path: contact.db 文件路径
            db_key: 数据库密钥(如果需要解密)
        """
        self.db_path = db_path
        self.db_key = db_key
        self.conn = None
        self._connect()
    
    def _connect(self):
        """建立数据库连接"""
        import tempfile
        import os
        
        if self.db_key:
            logger.info(f"[DEBUG ContactDB] 开始解密联系人数据库: {self.db_path}")
            
            # 使用新的纯Python解密器
            from ...db_decryptor_v2 import WeChatDBDecryptorV2
            decryptor = WeChatDBDecryptorV2()
            
            # 先验证密钥
            if not decryptor.verify_key_from_file(self.db_path, self.db_key):
                raise ValueError(f"密钥验证失败: {self.db_path}")
            
            logger.info(f"[DEBUG ContactDB] ✅ 密钥验证成功")
            
            # 解密到临时文件
            self.temp_db_path = tempfile.mktemp(suffix='.db')
            logger.debug(f"[DEBUG ContactDB] 解密到临时文件: {self.temp_db_path}")
            
            decryptor.decrypt_database(self.db_path, self.temp_db_path, self.db_key)
            logger.info(f"[DEBUG ContactDB] ✅ 解密完成")
            
            # 连接解密后的数据库
            self.conn = sqlite3.connect(self.temp_db_path)
            self.conn.row_factory = sqlite3.Row
        else:
            # 明文数据库
            self.temp_db_path = None
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
    
    def get_contacts(self) -> List[dict]:
        """
        获取所有联系人
        
        SQL查询字段:
        - username: wxid (主键)
        - alias: 微信号
        - local_type: 1=普通, 2=群聊, 5=OpenIM
        - flag: 标志位 (bit6=星标, bit11=置顶)
        - remark: 备注名
        - nick_name: 昵称
        - small_head_url: 小头像URL
        - big_head_url: 大头像URL
        - extra_buffer: protobuf数据(性别/签名/地区)
        
        Returns:
            List[dict]: 联系人列表
        """
        sql = """
            SELECT 
                username,
                alias,
                local_type,
                flag,
                remark,
                nick_name,
                small_head_url,
                big_head_url,
                extra_buffer,
                remark_quan_pin,
                quan_pin
            FROM contact
            WHERE local_type IN (1, 2, 5)
            AND username NOT LIKE '%@chatroom%'
            AND username NOT LIKE 'gh_%'
            ORDER BY 
                CASE 
                    WHEN remark_quan_pin = '' THEN quan_pin
                    ELSE remark_quan_pin
                END ASC
        """
        
        cursor = self.conn.execute(sql)
        contacts = []
        
        for row in cursor:
            username = row['username']
            if is_excluded_contact_username(username):
                continue
            contact = {
                'username': username,
                'nickname': row['nick_name'] or '',
                'remark': row['remark'] or '',
                'alias': row['alias'] or '',
                'phone': '',  # V4 不直接存储电话
                'is_friend': row['local_type'] == 1,
                'avatar_url': row['big_head_url'] or row['small_head_url'] or '',
                'extra': self._parse_extra_buffer(row['extra_buffer']) if row['extra_buffer'] else {}
            }
            contacts.append(contact)
        
        return contacts
    
    def get_contact_by_username(self, username: str) -> Optional[dict]:
        """
        根据username查询单个联系人
        
        Args:
            username: 微信ID
            
        Returns:
            dict: 联系人信息,未找到返回None
        """
        sql = """
            SELECT 
                username,
                alias,
                local_type,
                flag,
                remark,
                nick_name,
                small_head_url,
                big_head_url,
                extra_buffer
            FROM contact
            WHERE username = ?
        """
        
        cursor = self.conn.execute(sql, (username,))
        row = cursor.fetchone()
        
        if not row:
            return None

        if is_excluded_contact_username(row['username']):
            return None
        
        return {
            'username': row['username'],
            'nickname': row['nick_name'] or '',
            'remark': row['remark'] or '',
            'alias': row['alias'] or '',
            'phone': '',
            'is_friend': row['local_type'] == 1,
            'avatar_url': row['big_head_url'] or row['small_head_url'] or '',
            'extra': self._parse_extra_buffer(row['extra_buffer']) if row['extra_buffer'] else {}
        }
    
    def get_messages(self, username: str, time_range=None, limit=None) -> List[dict]:
        """
        联系人数据库不存储消息
        此方法保留以符合基类接口
        """
        return []
    
    def _parse_extra_buffer(self, buffer: bytes) -> dict:
        """
        解析 extra_buffer 中的 protobuf 数据
        
        包含信息:
        - 性别 (gender)
        - 个性签名 (signature)
        - 地区 (region/city/province)
        
        Args:
            buffer: protobuf 二进制数据
            
        Returns:
            dict: 解析后的数据
        """
        # TODO: 实现 protobuf 解析
        # 目前简化处理,返回空字典
        return {
            'gender': None,
            'signature': '',
            'region': ''
        }
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
        
        # 清理临时文件
        if hasattr(self, 'temp_db_path') and self.temp_db_path:
            import os
            try:
                os.remove(self.temp_db_path)
                logger.debug(f"[DEBUG ContactDB] 已删除临时文件: {self.temp_db_path}")
            except Exception as e:
                logger.error(f"[DEBUG ContactDB] 删除临时文件失败: {e}")
