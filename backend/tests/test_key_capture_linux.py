"""key_capture_linux 单测：ELF 锚点链分析、PT_LOAD 地址换算、/proc 枚举与会话状态机。

全部用合成 ELF / 伪造 /proc 树离线验证（不依赖真实微信进程与 gdb）。
"""
from __future__ import annotations

import io
import struct
import sys
import time
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.services.wechat import key_capture_linux as kcl
from fixtures.wcdb_factory import build_synth_elf


# ============================================================
# ELF 锚点链静态分析
# ============================================================

def _build_anchor_elf(tmp_path, *, text_vaddr=0x44EC000, rodata_vaddr=0x1000):
    """构造含完整 LEA 引用链的合成 ELF，返回 (elf_path, 期望断点 VA)。"""
    rodata = b"\x00" * 0x100 + kcl.ANCHOR_STRING + b"\x00" * 0x40
    anchor_va = rodata_vaddr + 0x100
    unk_va = anchor_va + 0x40

    buf = bytearray(0x800)
    a = 0x40
    # 第一层：LEA rdi,[unk] 紧跟 LEA rsi,[anchor]
    struct.pack_into("<i", buf, a + 3, unk_va - text_vaddr - (a + 7))
    buf[a:a + 3] = kcl.LEA_RDI
    first = a + 7
    struct.pack_into("<i", buf, first + 3, anchor_va - text_vaddr - first - 7)
    buf[first:first + 3] = kcl.LEA_RSI
    # 第二层：LEA rsi,[unk]；其前方是函数头 prologue
    second = 0x200
    struct.pack_into("<i", buf, second + 3, unk_va - text_vaddr - second - 7)
    buf[second:second + 3] = kcl.LEA_RSI
    func_head_off = second - 0x20
    buf[func_head_off:func_head_off + 3] = kcl.FUNC_HEAD

    elf = build_synth_elf(
        [(".text", text_vaddr, bytes(buf)), (".rodata", rodata_vaddr, rodata)]
    )
    path = tmp_path / "wechat"
    path.write_bytes(elf)
    return path, text_vaddr + func_head_off


def test_find_hook_offsets_locates_function_head(tmp_path):
    path, expected_va = _build_anchor_elf(tmp_path)
    assert kcl.find_hook_offsets(path) == [expected_va]
    assert kcl.find_hook_offset(path) == expected_va


def test_find_hook_offsets_without_anchor_raises(tmp_path):
    elf = build_synth_elf([
        (".text", 0x1000, b"\x90" * 0x100),
        (".rodata", 0x2000, b"nothing here"),
    ])
    path = tmp_path / "wechat"
    path.write_bytes(elf)
    with pytest.raises(RuntimeError):
        kcl.find_hook_offsets(path)


def test_find_hook_offsets_rejects_non_x86_64(tmp_path):
    # ARM 机器码 + 无节名 → 节缺失或架构报错都应抛 RuntimeError
    path = tmp_path / "wechat"
    path.write_bytes(b"not an elf at all")
    with pytest.raises(RuntimeError):
        kcl.find_hook_offsets(path)


# ============================================================
# PT_LOAD 感知地址换算（核心坑：.text vaddr 从 0x44EC000 起）
# ============================================================

_MAPS = "\n".join([
    "7f0000000000-7f0044eb000 r--p 00000000 08:01 1        /opt/wechat/wechat",
    "7f0044eb000-7f00a600000 r-xp 0044eb000 08:01 1        /opt/wechat/wechat",
    "7f00a600000-7f00a700000 rw-p 00a670ed0 08:01 1        /opt/wechat/wechat",
    "7fff00000000-7fff00001000 rw-p 00000000 00:00 0        [heap]",
]) + "\n"

_LOADS = [
    (0x0, 0x0, 0x44EB000, 0x44EB000),                 # r-- 段
    (0x44EB000, 0x44EC000, 0x6100000, 0x6100000),     # r-x 段：vaddr≠offset，差 0x1000
    (0xA670ED0, 0xA680000, 0x100000, 0x100000),       # rw- 段
]


def _patch_proc(monkeypatch):
    monkeypatch.setattr(kcl, "_load_elf_loads", lambda _p: _LOADS)

    class _FakePath:
        def __init__(self, s):
            self._s = str(s)

        def read_text(self, encoding=None):
            assert self._s.endswith("/maps"), self._s
            return _MAPS

    class _FakePathlib:
        Path = staticmethod(_FakePath)

    monkeypatch.setattr(kcl, "pathlib", _FakePathlib)


def test_va_to_runtime_addr_uses_pt_load_translation(monkeypatch):
    _patch_proc(monkeypatch)
    va = 0x44EC000 + 0x1234
    runtime = kcl.va_to_runtime_addr(1234, "/opt/wechat/wechat", va)
    # 正确换算：r-x 段运行时起点 + (VA - 段 vaddr)
    assert runtime == 0x7f0044eb000 + 0x1234
    # 反例：朴素「映射基址 + VA」会偏移整个 r-- 段长度（真实事故中偏 4.5MB）
    assert runtime != 0x7f0044eb000 + va
    assert runtime != 0x7f0000000000 + va


def test_va_to_runtime_addr_tolerates_deleted_suffix(monkeypatch):
    _patch_proc(monkeypatch)
    runtime = kcl.va_to_runtime_addr(1234, "/opt/wechat/wechat (deleted)", 0x44EC100)
    assert runtime == 0x7f0044eb000 + 0x100


def test_va_to_runtime_addr_rejects_va_outside_loads(monkeypatch):
    _patch_proc(monkeypatch)
    with pytest.raises(RuntimeError):
        kcl.va_to_runtime_addr(1234, "/opt/wechat/wechat", 0x1_0000_0000)


# ============================================================
# /proc 进程枚举
# ============================================================

def _fake_proc_tree():
    def stat(state, starttime):
        # comm 后字段：state 为 0 号，starttime 为 19 号
        fields = [state] + ["1"] * 18 + [str(starttime)]
        return "(wechat) " + " ".join(fields)

    return {
        "100": {"exe": "/usr/bin/wechat", "stat": stat("S", 1000)},
        "200": {"exe": "/usr/bin/wechat", "stat": stat("Z", 900)},   # 僵尸：应过滤
        "300": {"exe": "/opt/wechat/wechat (deleted)", "stat": stat("S", 2000)},
        "310": {"exe": "/usr/bin/wxocr", "stat": stat("S", 2100)},   # helper：应过滤
        "320": {"exe": "/usr/bin/wxplayer", "stat": stat("S", 2200)},
    }


def test_find_linux_wechat_pids_filters_and_orders(monkeypatch):
    tree = _fake_proc_tree()
    monkeypatch.setattr(kcl.os, "listdir", lambda _p: list(tree))
    monkeypatch.setattr(
        kcl.os, "readlink", lambda p: tree[p.rsplit("/", 2)[-2]]["exe"]
    )
    monkeypatch.setattr(
        kcl, "_process_state",
        lambda pid: tree[str(pid)]["stat"].split(") ", 1)[1].split()[0],
    )

    def fake_open(path, *args, **kwargs):
        pid = str(path).split("/")[2]
        return io.StringIO(str(pid) + tree[pid]["stat"])

    monkeypatch.setattr(kcl, "open", fake_open, raising=False)

    pids = kcl.find_linux_wechat_pids()
    # 僵尸与 helper 进程被排除；(deleted) 容忍；starttime 降序（最新优先）
    assert pids == [300, 100]


def test_pid_alive_treats_zombie_as_dead(monkeypatch):
    monkeypatch.setattr(kcl, "_process_state", lambda pid: "Z")
    assert kcl._pid_alive(123) is False
    monkeypatch.setattr(kcl, "_process_state", lambda pid: "S")
    assert kcl._pid_alive(123) is True
    monkeypatch.setattr(kcl, "_process_state", lambda pid: "")
    assert kcl._pid_alive(123) is False


# ============================================================
# 捕获会话状态机与 Provider
# ============================================================

def _patch_capture_success(monkeypatch, passphrase="AB" * 32):
    monkeypatch.setattr(kcl, "find_linux_wechat_pids", lambda: [4242])
    monkeypatch.setattr(kcl, "_check_ptrace_permission", lambda pid: None)
    monkeypatch.setattr(kcl, "_check_tracer", lambda pid: None)
    monkeypatch.setattr(kcl.os, "readlink", lambda p: "/usr/bin/wechat")
    monkeypatch.setattr(kcl, "find_hook_offset", lambda p: 0x87AC370)
    monkeypatch.setattr(
        kcl, "capture_passphrase_via_gdb",
        lambda pid, timeout=180, **kw: passphrase,
    )


def test_capture_session_failed_when_wechat_not_running(monkeypatch):
    monkeypatch.setattr(kcl, "find_linux_wechat_pids", lambda: [])
    session = kcl.LinuxKeyCaptureSession(timeout_seconds=30)
    result = session.start(ready_timeout_seconds=5)
    assert result["status"] == "failed"
    assert result["code"] == "wechat_not_running"
    assert result["ok"] is False


def test_capture_session_failed_on_ptrace_denied(monkeypatch):
    monkeypatch.setattr(kcl, "find_linux_wechat_pids", lambda: [4242])
    monkeypatch.setattr(
        kcl, "_check_ptrace_permission",
        lambda pid: "ptrace_scope=1 且无权限附加调试器。",
    )
    session = kcl.LinuxKeyCaptureSession(timeout_seconds=30)
    result = session.start(ready_timeout_seconds=5)
    assert result["status"] == "failed"
    assert result["code"] == "ptrace_denied"


def test_capture_session_success_flow(monkeypatch):
    _patch_capture_success(monkeypatch)
    session = kcl.LinuxKeyCaptureSession(timeout_seconds=30)
    snap = session.start(ready_timeout_seconds=5)
    assert snap["status"] in {"hook_ready", "captured"}
    # 后台捕获为异步：轮询到终态
    for _ in range(50):
        snap = session.snapshot()
        if snap.get("status") == "captured":
            break
        time.sleep(0.1)
    assert snap["status"] == "captured"
    assert snap["ok"] is True
    assert snap["db_key"] == "ab" * 32
    assert snap["pid"] == 4242


def test_provider_capture_db_key_waits_for_terminal_state(monkeypatch):
    _patch_capture_success(monkeypatch)
    result = kcl.LinuxWeChatKeyProvider.capture_db_key(timeout_seconds=30)
    assert result["ok"] is True
    assert result["db_key"] == "ab" * 32
    assert result["pid"] == 4242


def test_provider_create_capture_session_shape():
    session = kcl.LinuxWeChatKeyProvider.create_capture_session(
        timeout_seconds=60, account_wxid="wxid_test"
    )
    assert isinstance(session, kcl.LinuxKeyCaptureSession)
    assert session.account_wxid == "wxid_test"
    assert session.timeout_seconds == 60
