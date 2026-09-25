"""兼容 shim：旧路径 `app.services.wechat.key_capture_linux` → `keys/gdb_linux.py`。"""
from .keys.gdb_linux import (  # noqa: F401
    ANCHOR_STRING,
    CAPTURE_ERROR_RE,
    ELF_MAGIC,
    EM_X86_64,
    FUNC_HEAD,
    LEA_RDI,
    LEA_RSI,
    PASSPHRASE_RE,
    LinuxKeyCaptureSession,
    LinuxWeChatKeyProvider,
    capture_passphrase_via_gdb,
    find_hook_offset,
    find_hook_offsets,
    find_linux_wechat_pids,
    find_runtime_base,
    va_to_runtime_addr,
)
