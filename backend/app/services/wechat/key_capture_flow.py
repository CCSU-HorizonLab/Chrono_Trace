"""兼容 shim：旧路径 `app.services.wechat.key_capture_flow` → `keys/flow_win.py`。"""
from .keys.flow_win import (  # noqa: F401
    _list_wechat_processes,
    _window_texts,
    inspect_wechat_login_state,
    restart_wechat_for_key_capture,
)
