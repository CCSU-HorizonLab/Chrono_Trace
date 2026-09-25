"""兼容 shim：旧路径 `app.services.wechat.key_provider` → `keys/wx_key_win.py`。

历史导入方（测试/外部脚本）保持可用；新代码请从 keys 包导入。
"""
from .keys.wx_key_win import WeChatKeyCaptureSession, WeChatKeyProvider  # noqa: F401
