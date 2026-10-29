"""自动探测同步的账号候选不得清空已有捕获态（第三轮抽查 W7）。

bridge._build_wechat_account_candidate 构造的候选不含 key_type/raw_keys/
import_watermark_ts——upsert 时 normalize 填默认值（passphrase/{}/0）直接
覆盖已有记录，raw key 通道失效、导入水位清零退化为全量重导。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.wechat.account_settings import get_wechat_account, upsert_wechat_account
from app.webview.bridge import Bridge


def _bridge_with_settings() -> Bridge:
    bridge = object.__new__(Bridge)
    bridge.settings = {}
    return bridge


def test_auto_sync_candidate_preserves_captured_key_state():
    bridge = _bridge_with_settings()
    # Windows 只读扫描已捕获 raw 密钥与导入水位的既有账号
    # （raw_keys 为 {salt_hex(32): enc_key_hex(64)}，_normalize_raw_keys 校验长度）
    salt = "a1b2c3d4" * 4
    enc_key = "0f1e2d3c" * 8
    upsert_wechat_account(bridge.settings, {
        "wxid": "wxid_a",
        "wechat_dir": "/old",
        "db_key": "passphrase-hex",
        "key_type": "raw",
        "raw_keys": {salt: enc_key},
        "import_watermark_ts": 12345,
        "import_completed": True,
    })

    # 自动探测同步：微信目录变化的候选（不含捕获态字段，db_key 也为空）
    candidate = bridge._build_wechat_account_candidate(
        "wxid_a", wechat_dir="/new", source="auto", db_key="", avatar="", label=None,
    )
    assert "key_type" in candidate and "raw_keys" in candidate
    upsert_wechat_account(bridge.settings, candidate)

    merged = get_wechat_account(bridge.settings, "wxid_a")
    assert merged["wechat_dir"] == "/new", "探测到的目录变化正常更新"
    assert merged["key_type"] == "raw", "捕获的密钥类型不得被默认值覆盖"
    assert merged["raw_keys"] == {salt: enc_key}, "raw 密钥表不得被清空"
    assert merged["import_watermark_ts"] == 12345, "导入水位不得清零"
    assert merged["db_key"] == "passphrase-hex", "空候选不得清已有密钥"
    assert merged["import_completed"] is True


def test_auto_sync_candidate_new_account_uses_defaults():
    bridge = _bridge_with_settings()
    candidate = bridge._build_wechat_account_candidate(
        "wxid_new", wechat_dir="/found", source="auto", db_key="", avatar="", label=None,
    )
    upsert_wechat_account(bridge.settings, candidate)

    created = get_wechat_account(bridge.settings, "wxid_new")
    assert created["key_type"] == "passphrase"
    assert created["raw_keys"] == {}
    assert created["import_watermark_ts"] == 0
    assert created["wechat_dir"] == "/found"


def test_realtime_messages_baseline_only_from_same_batch(monkeypatch):
    """W15：基线尾部只并入单例当前批次。

    前端轮询旧批次（悬浮窗残页/重启恢复）时，监听单例可能已在新会话
    （另一对话）——_baseline_tail 不校验归属会把别的对话的基线并进本
    批次展示。
    """
    from app.webview.bridge import Bridge

    class _FakeMonitor:
        def __init__(self):
            self.current_batch_id = "b_new"
            self._baseline_tail = [
                {
                    "sender_attr": "friend",
                    "content": "别的对话的基线",
                    "message_type": "text",
                    "timestamp": 1_700_000_100,
                },
            ]

    monkeypatch.setattr(
        "app.services.realtime.monitor_service.RealtimeMonitorService", _FakeMonitor
    )
    monkeypatch.setattr(
        "app.services.realtime.message_query.get_messages_with_sentiment",
        lambda batch_id, limit, account_wxid="": [],
    )

    bridge = object.__new__(Bridge)
    bridge._get_active_wechat_account_wxid = lambda: "acct"

    # 旧批次轮询：不并入新会话（另一对话）的基线
    stale = bridge.get_realtime_messages("b_old", limit=50)
    assert stale["ok"] is True
    assert stale["messages"] == []

    # 当前批次：并入基线
    fresh = bridge.get_realtime_messages("b_new", limit=50)
    assert fresh["ok"] is True
    assert [m["content"] for m in fresh["messages"]] == ["别的对话的基线"]
