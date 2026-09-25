"""密钥提取子系统公共协议（双平台同形契约）。

各平台捕获引擎（Linux=GDB 断点、Windows=只读扫描/wx_key hook）共用同一套
会话状态字与结果字段，bridge 层的轮询/持久化逻辑对平台无感知。

状态机：preparing → hook_ready → captured / failed / timed_out
  - hook_ready 语义按平台有别的用户动作提示（Linux=重新登录；Win hook=重启登录；
    Win 扫描=无需动作，瞬时）
  - 快速引擎（扫描）可能在 start() 返回前直接进入 captured

snapshot() 基础形状（各引擎必须保证）：
  {"ok": bool, "status": str, "message": str, "account_wxid": str, ...}
  - ok = status not in {STATUS_FAILED, STATUS_TIMED_OUT}
  - captured 时附加 db_key（64 hex 小写）、pid
  - failed 时附加 code / error

code 命名空间（超集；各引擎按需使用）：
  引擎无关：wechat_not_running / hook_prepare_timeout
  wx_key(windows)：extension_missing / hook_initialize_failed /
                   hook_poll_failed / capture_timeout
  扫描(windows)：scan_no_match / scan_open_failed
  GDB(linux)：ptrace_denied / elf_analysis_failed / capture_failed

密钥类型（key_type，随捕获结果返回，默认 "passphrase"）：
  - "passphrase"：32B 口令 hex，按库 salt 经 PBKDF2(256000) 派生（Linux 断点 /
    Windows wx_key hook 产出）
  - "raw"：Windows 只读扫描产出的每库派生密钥 enc_key（无法反推 passphrase），
    附带 raw_keys: {salt_hex: enc_key_hex}，经 decryptor.set_raw_key_map 使用
"""
from __future__ import annotations

# 会话状态字
STATUS_PREPARING = "preparing"
STATUS_HOOK_READY = "hook_ready"
STATUS_CAPTURED = "captured"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed_out"

TERMINAL_STATUSES = {STATUS_CAPTURED, STATUS_FAILED, STATUS_TIMED_OUT}

# 密钥类型
KEY_TYPE_PASSPHRASE = "passphrase"
KEY_TYPE_RAW = "raw"
