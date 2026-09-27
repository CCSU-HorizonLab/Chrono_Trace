"""Windows 密钥提取降级链：只读扫描优先 → wx_key hook 回退。

链路（Windows 微信 4.1+ 内存行为与 Linux 不同——WCDB Config.Cipher 运行时
对象保留密钥，只读扫描可行）：
1. scan_win 只读扫描：免重启、秒级、纯 ctypes、无注入；产出每库 raw enc_key
   （key_type="raw" + raw_keys 映射），经 db_decryptor_v2 按 salt HMAC 验证
2. wx_key hook 登录捕获：现役已验证方案，产出 passphrase（key_type="passphrase"）
3. 手动输入：bridge 层既有兜底，不在链内
"""
from __future__ import annotations

from typing import Any

from .wx_key_win import WeChatKeyProvider


class WindowsKeyProviderChain:
    """Windows 平台 Provider：对外保持与 WeChatKeyProvider 同形的方法面。"""

    def __init__(self, wechat_dir: str = ""):
        self.wechat_dir = str(wechat_dir or "").strip()
        self._wxkey = WeChatKeyProvider()

    def capture_db_key(self, timeout_seconds: int = 60, account_wxid: str = "") -> dict:
        """一次性捕获：先只读扫描（秒级），未命中回退 wx_key hook。"""
        if self.wechat_dir:
            from .scan_win import scan_wechat_raw_keys
            result = scan_wechat_raw_keys(self.wechat_dir, timeout_seconds=timeout_seconds)
            if result.get("ok"):
                return result
        return self._wxkey.capture_db_key(
            timeout_seconds=timeout_seconds, account_wxid=account_wxid
        )

    def create_capture_session(self, timeout_seconds: int = 120,
                               account_wxid: str = ""):
        """会话式捕获：扫描阶段命中即免重启完成；未命中转入 wx_key 登录捕获。"""
        from .chain_session_win import WindowsChainSession
        return WindowsChainSession(
            wechat_dir=self.wechat_dir,
            timeout_seconds=timeout_seconds,
            account_wxid=account_wxid,
            wxkey_provider=self._wxkey,
        )
