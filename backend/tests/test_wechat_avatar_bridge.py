import sys
from pathlib import Path
from unittest.mock import MagicMock


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.webview.bridge import Bridge


def test_bridge_refresh_wechat_contact_avatars_prefers_saved_selected_paths():
    bridge = Bridge.__new__(Bridge)
    bridge.wechat_service = MagicMock()
    bridge.wechat_service.refresh_contact_avatars.return_value = {"ok": True, "stats": {"scanned": 1}}
    bridge.settings = {
        "wechat_data_dir": r"D:\WeChat\xwechat_files",
        "wechat_user_wxid": "wxid_selected",
    }

    result = bridge.refresh_wechat_contact_avatars("secret-key")

    assert result == {"ok": True, "stats": {"scanned": 1}}
    bridge.wechat_service.refresh_contact_avatars.assert_called_once_with(
        "secret-key",
        {
            "wechat_dir": r"D:\WeChat\xwechat_files",
            "current_user": "wxid_selected",
        },
    )
