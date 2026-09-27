"""密钥提取子系统（双平台）。

平台引擎：
- Linux：gdb_linux（wcdb-key-tool-plus 方案：ELF 锚点 + GDB 断点 + PT_LOAD 换算）
- Windows：wx_key_win（wx_key hook 登录捕获）；scan_win（只读 Config.Cipher 扫描）+
  chain_win（扫描优先 → hook 回退的降级链）

平台选择统一收敛到 create_key_provider()——bridge 与其它调用方不应再各自
做 sys.platform 分派。会话协议见 base.py。
"""
from __future__ import annotations

import sys


def create_key_provider(wechat_dir: str = ""):
    """按平台创建密钥提取 Provider。

    - Linux：LinuxWeChatKeyProvider（GDB 断点，免重启、重登触发）
    - Windows：WindowsKeyProviderChain（只读扫描优先 → wx_key hook 回退）
    wechat_dir 供扫描引擎定位数据库文件（按 salt 验证候选），Linux 引擎不使用。
    """
    if sys.platform != "win32":
        from .gdb_linux import LinuxWeChatKeyProvider
        return LinuxWeChatKeyProvider()
    from .chain_win import WindowsKeyProviderChain
    return WindowsKeyProviderChain(wechat_dir=wechat_dir)


def create_capture_session(timeout_seconds: int = 180, account_wxid: str = "",
                           wechat_dir: str = ""):
    """按平台创建捕获会话（状态机见 base.py）。"""
    return create_key_provider(wechat_dir=wechat_dir).create_capture_session(
        timeout_seconds=timeout_seconds, account_wxid=account_wxid,
    )


__all__ = ["create_key_provider", "create_capture_session"]

# 便捷再导出（keys.gdb_linux 等仍可直接 from-import）
if sys.platform != "win32":  # win32 分支由 Windows 测试覆盖
    from .gdb_linux import (  # noqa: F401
        LinuxKeyCaptureSession,
        LinuxWeChatKeyProvider,
        find_linux_wechat_pids,
    )
else:  # pragma: windows
    from .wx_key_win import WeChatKeyCaptureSession, WeChatKeyProvider  # noqa: F401
