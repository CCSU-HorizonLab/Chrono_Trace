"""微信数据库适配层

支持不同版本的微信数据库结构:
- V4: 新版微信 (contact/contact.db, message/message_*.db)
- V3: 旧版微信 (Msg/MicroMsg.db, MSG*.db)
"""

from .detector import detect_wechat_version
from .v4.contact import ContactDBV4
from .v4.message import MessageDBV4

__all__ = [
    'detect_wechat_version',
    'ContactDBV4',
    'MessageDBV4',
]
