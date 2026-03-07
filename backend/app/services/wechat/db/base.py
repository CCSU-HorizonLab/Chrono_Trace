"""微信数据库基类定义"""
import logging

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


logger = logging.getLogger(__name__)
class WeChatDBBase(ABC):
    """微信数据库基类 - 定义统一的接口"""
    
    @abstractmethod
    def get_contacts(self) -> List[dict]:
        """
        获取所有联系人
        
        Returns:
            List[dict]: 联系人列表,每个元素包含:
            {
                'username': str,      # wxid
                'nickname': str,      # 昵称
                'remark': str,        # 备注名
                'alias': str,         # 微信号
                'phone': str,         # 电话
                'is_friend': bool,    # 是否为好友
                'avatar_url': str,    # 头像URL
                'extra': dict         # 额外信息(性别/签名/地区等)
            }
        """
        pass
    
    @abstractmethod
    def get_contact_by_username(self, username: str) -> Optional[dict]:
        """
        根据username获取单个联系人
        
        Args:
            username: 微信ID (如 wxid_abc123)
            
        Returns:
            dict: 联系人信息,未找到返回None
        """
        pass
    
    @abstractmethod
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
            List[dict]: 消息列表,每个元素包含:
            {
                'local_id': int,      # 本地消息ID
                'talker': str,        # 对话对象username
                'sender': str,        # 发送者username
                'is_sender': bool,    # 是否为本人发送
                'message_type': int,  # 消息类型
                'content': str,       # 消息内容
                'timestamp': int,     # Unix时间戳(秒)
                'media_path': str     # 媒体路径(可选)
            }
        """
        pass
    
    @abstractmethod
    def close(self):
        """关闭数据库连接"""
        pass
