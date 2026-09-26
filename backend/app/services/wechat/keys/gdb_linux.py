"""Linux 微信数据库密钥提取（阶段二移植）。

原理（参考并适配自 MIT 许可的 wcdb-key-tool，https://github.com/TANGandXUE/wcdb-key-tool）：
1. ELF 静态分析：在微信二进制 .rodata 中定位 WCDB 特征字符串
   "com.Tencent.WCDB.Config.Cipher"，沿 RIP 相对引用交叉定位密钥处理函数入口，
   得到断点虚拟地址（随版本自动适配，无需人工逆向）。
2. GDB 断点捕获：附加到运行中的微信进程，在函数入口下断点；微信 4.1+ 只在
   「登录」时计算一次 passphrase（不再缓存明文密钥，内存扫描已失效），断点
   命中后按 x86-64 SysV ABI 从寄存器读出 32 字节 passphrase。
3. passphrase 即项目 db_key 语义：db_decryptor_v2.derive_keys 会按各库 salt
   做 PBKDF2-HMAC-SHA512(256000) 派生 + HMAC 校验，与 Windows 路径完全一致。

注意：微信二进制更新后旧进程仍运行旧 inode（/proc/<pid>/exe 带 "(deleted)"），
所有定位一律通过 /proc/<pid>/exe 与 maps 的真实运行 inode 进行。
"""
from __future__ import annotations

import logging
import os
import pathlib
import re
import shutil
import struct
import subprocess
import tempfile
import textwrap
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ELF 特征（与 wcdb-key-tool 保持一致）
ANCHOR_STRING = b"com.Tencent.WCDB.Config.Cipher"
LEA_RSI = b"\x48\x8D\x35"
LEA_RDI = b"\x48\x8D\x3D"
FUNC_HEAD = b"\x55\x41\x57"
ELF_MAGIC = b"\x7fELF"
EM_X86_64 = 62

PASSPHRASE_RE = re.compile(r"WECHAT_PASSPHRASE=([0-9a-fA-F]{64})")
CAPTURE_ERROR_RE = re.compile(r"CAPTURE_ERROR=(.*)")


def _strip_deleted_suffix(path: str) -> str:
    return path.removesuffix(" (deleted)")


def _process_state(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1].split()[0]
    except (OSError, IndexError):
        return ""


def find_linux_wechat_pids() -> list[int]:
    """枚举微信主进程 PID，按启动时间降序（最新优先）。

    - exe basename == wechat（wxocr/wxplayer 等 helper 天然排除）
    - 过滤僵尸进程（「退出登录」后旧进程会残留为 Z，readlink 会失败）
    - 容忍二进制更新后的 "(deleted)" 后缀
    """
    entries: list[tuple[int, int]] = []  # (starttime, pid)
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if _process_state(pid) == "Z":
            continue
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            continue
        if os.path.basename(_strip_deleted_suffix(exe)) != "wechat":
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                starttime = int(f.read().split(") ", 1)[1].split()[19])
        except (OSError, IndexError, ValueError):
            starttime = 0
        entries.append((starttime, pid))
    return [pid for _start, pid in sorted(entries, reverse=True)]


def _check_ptrace_permission(pid: int) -> Optional[str]:
    """返回不可附加的原因描述，None 表示可尝试。"""
    try:
        scope = int(pathlib.Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip())
    except (OSError, ValueError):
        scope = 0
    try:
        with open(f"/proc/{pid}/mem", "rb"):
            pass
        return None
    except PermissionError:
        if scope > 0:
            return (
                f"ptrace_scope={scope} 且无权限附加调试器。"
                "请执行: echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope 后重试，"
                "或使用手动输入密钥。"
            )
        return "无权限读取微信进程内存（尝试用 sudo 运行本应用）。"
    except OSError:
        return None  # 打开成功与否的其余情况交给 GDB 阶段判断


def _check_tracer(pid: int) -> Optional[str]:
    try:
        for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("TracerPid:"):
                tracer = int(line.split(":")[1].strip())
                if tracer != 0:
                    return f"微信进程已被 PID={tracer} 的调试器占用，请先关闭它。"
    except OSError:
        pass
    return None


# ============================================================
# ELF 静态分析（适配自 wcdb-key-tool，MIT）
# ============================================================

class _ELFSection:
    __slots__ = ("name", "addr", "offset", "size", "data")

    def __init__(self, name: str, addr: int, offset: int, size: int, data: bytes) -> None:
        self.name = name
        self.addr = addr
        self.offset = offset
        self.size = size
        self.data = data


def _load_elf_sections(binary_path: pathlib.Path) -> dict[str, _ELFSection]:
    data = binary_path.read_bytes()
    if data[:4] != ELF_MAGIC:
        raise RuntimeError(f"不是 ELF 文件: {binary_path}")
    if data[4] != 2 or data[5] != 1:
        raise RuntimeError(f"仅支持 ELF64 小端序: {binary_path}")

    (
        _etype, machine, _version, _entry, _phoff, shoff,
        _flags, _ehsize, _phentsize, _phnum,
        shentsize, shnum, shstrndx,
    ) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)

    if machine != EM_X86_64:
        raise RuntimeError(f"仅支持 x86_64 架构: {binary_path}")

    sections_raw: list[tuple[int, int, int, int]] = []
    for index in range(shnum):
        offset = shoff + (index * shentsize)
        sh_name, _sh_type, _flags2, sh_addr, sh_offset, sh_size = (
            struct.unpack_from("<IIQQQQIIQQ", data, offset)[:6]
        )
        sections_raw.append((sh_name, sh_addr, sh_offset, sh_size))

    if shstrndx >= len(sections_raw):
        raise RuntimeError("无效的节字符串表索引")
    _, _, shstr_offset, shstr_size = sections_raw[shstrndx]
    shstr_data = data[shstr_offset: shstr_offset + shstr_size]

    sections: dict[str, _ELFSection] = {}
    for sh_name, sh_addr, sh_offset, sh_size in sections_raw:
        end = shstr_data.find(b"\0", sh_name)
        if end == -1:
            end = len(shstr_data)
        name = shstr_data[sh_name:end].decode("utf-8", errors="replace")
        if not name:
            continue
        sections[name] = _ELFSection(
            name=name, addr=sh_addr, offset=sh_offset, size=sh_size,
            data=data[sh_offset: sh_offset + sh_size],
        )
    return sections


def _find_rip_relative_refs(text: _ELFSection, opcode: bytes, target_va: int) -> list[int]:
    hits = []
    # bytes.find 为 C 速度扫描：纯 Python 逐字节循环扫 ~100MB .text 需 ~1 分钟，
    # 会拖爆 start() 的 ready 等待（release 版「准备超时」根因）
    limit = len(text.data) - 7
    pos = text.data.find(opcode, 0, limit + 1)
    while pos != -1:
        disp = struct.unpack_from("<i", text.data, pos + 3)[0]
        resolved = text.addr + pos + 7 + disp
        if resolved == target_va:
            hits.append(pos)
        pos = text.data.find(opcode, pos + 1)
    return hits


def find_hook_offsets(binary_path: str | pathlib.Path) -> list[int]:
    """分析 ELF，返回全部候选断点虚拟地址（随微信版本自动适配）。"""
    binary_path = pathlib.Path(binary_path)
    sections = _load_elf_sections(binary_path)
    try:
        rodata = sections[".rodata"]
        text = sections[".text"]
    except KeyError as exc:
        raise RuntimeError(f"ELF 缺少必要的节: {exc.args[0]}") from exc

    candidates: list[int] = []
    search_from = 0
    while True:
        anchor_offset = rodata.data.find(ANCHOR_STRING, search_from)
        if anchor_offset == -1:
            break
        search_from = anchor_offset + 1
        anchor_va = rodata.addr + anchor_offset

        for first_ref_offset in _find_rip_relative_refs(text, LEA_RSI, anchor_va):
            if first_ref_offset < 7:
                continue
            if text.data[first_ref_offset - 7: first_ref_offset - 4] != LEA_RDI:
                continue
            unk_disp = struct.unpack_from("<i", text.data, first_ref_offset - 4)[0]
            unk_va = text.addr + first_ref_offset + unk_disp

            for second_ref_offset in _find_rip_relative_refs(text, LEA_RSI, unk_va):
                scan_start = max(0, second_ref_offset - 0x500)
                for candidate_offset in range(second_ref_offset, scan_start - 1, -1):
                    if text.data[candidate_offset: candidate_offset + len(FUNC_HEAD)] == FUNC_HEAD:
                        va = text.addr + candidate_offset
                        if va not in candidates:
                            candidates.append(va)
                        break

    if not candidates:
        raise RuntimeError("未能在微信二进制中定位密钥断点，可能是不支持的微信版本。")
    offsets = sorted(candidates)
    logger.info("[LinuxKey] 候选断点虚拟地址: %s", ", ".join(f"0x{x:X}" for x in offsets))
    return offsets


def find_hook_offset(binary_path: str | pathlib.Path) -> int:
    """兼容旧调用：返回首个候选断点虚拟地址。"""
    return find_hook_offsets(binary_path)[0]


def _load_elf_loads(binary_path: pathlib.Path) -> list[tuple[int, int, int, int]]:
    """解析 PT_LOAD：返回 [(p_offset, p_vaddr, p_filesz, p_memsz), ...]。"""
    data = binary_path.read_bytes()
    e_phoff, = struct.unpack_from("<Q", data, 32)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 54)
    loads = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, _p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz = (
            struct.unpack_from("<IIQQQQQ", data, off)
        )
        if p_type == 1:  # PT_LOAD
            loads.append((p_offset, p_vaddr, p_filesz, p_memsz))
    return loads


def find_runtime_base(pid: int, exe_link: str) -> int:
    """兼容旧签名：返回 r-x 段运行时基址（注意配合 segment_vaddr 使用）。"""
    binary_name = os.path.basename(_strip_deleted_suffix(exe_link))
    try:
        maps_text = pathlib.Path(f"/proc/{pid}/maps").read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"无法读取 /proc/{pid}/maps: {exc}") from exc

    for line in maps_text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        if os.path.basename(_strip_deleted_suffix(parts[5])) != binary_name:
            continue
        if "r" in parts[1] and "x" in parts[1]:
            return int(parts[0].split("-")[0], 16)

    for line in maps_text.splitlines():
        parts = line.split()
        if len(parts) >= 6 and os.path.basename(_strip_deleted_suffix(parts[5])) == binary_name:
            return int(parts[0].split("-")[0], 16)

    raise RuntimeError(f"未找到 {binary_name} 的内存映射基址 (PID={pid})")


def va_to_runtime_addr(pid: int, exe_link: str, va: int) -> int:
    """模块虚拟地址 -> 运行时地址（按程序头 + maps 文件偏移精确换算）。

    微信二进制的 .text 段 vaddr 从 0x44EC000 起（前面有 ~70MB 只读段），
    「映射基址 + VA」的直接相加会整体偏移 4.5MB，此前的断点全部因此落空。
    """
    loads = _load_elf_loads(pathlib.Path(f"/proc/{pid}/exe"))
    seg = None
    for p_offset, p_vaddr, _filesz, p_memsz in loads:
        if p_vaddr <= va < p_vaddr + p_memsz:
            seg = (p_offset, p_vaddr)
            break
    if seg is None:
        raise RuntimeError(f"VA 0x{va:X} 不在任何 PT_LOAD 内")

    binary_name = os.path.basename(_strip_deleted_suffix(exe_link))
    page = seg[0] & ~0xFFF
    maps_text = pathlib.Path(f"/proc/{pid}/maps").read_text(encoding="utf-8")
    for line in maps_text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        if os.path.basename(_strip_deleted_suffix(parts[5])) != binary_name:
            continue
        if int(parts[2], 16) == page:
            seg_runtime = int(parts[0].split("-")[0], 16)
            return seg_runtime + (va - seg[1])
    raise RuntimeError(f"未找到文件偏移 0x{page:X} 的运行时映射")


# ============================================================
# GDB 捕获（适配自 wcdb-key-tool，MIT）
# ============================================================

_GDB_SCRIPT_TEMPLATE = textwrap.dedent("""\
    set pagination off
    attach {pid}
    python
    import gdb

    class CaptureBreakpoint(gdb.Breakpoint):
        def stop(self):
            try:
                rsi = int(gdb.parse_and_eval("$rsi"))
                rdx = int(gdb.parse_and_eval("$rdx"))
                print("BP_HIT rsi=0x%x rdx=0x%x" % (rsi, rdx))
                # 方式 1：rsi=key 指针, rdx=长度 32
                if rsi and rdx == 32:
                    raw = gdb.selected_inferior().read_memory(rsi, 32).tobytes()
                    print("WECHAT_PASSPHRASE=" + raw.hex())
                    gdb.execute("detach")
                    gdb.execute("quit")
                    return True
                # 方式 2：rsi 指向结构体，key 在 *(rsi+8)，size 在 rsi+16
                if rsi:
                    try:
                        size_val = int(gdb.parse_and_eval("*(unsigned long long*)($rsi+16)"))
                        if size_val == 32:
                            key_ptr = int(gdb.parse_and_eval("*(unsigned long long*)($rsi+8)"))
                            if key_ptr:
                                raw = gdb.selected_inferior().read_memory(key_ptr, 32).tobytes()
                                print("WECHAT_PASSPHRASE=" + raw.hex())
                                gdb.execute("detach")
                                gdb.execute("quit")
                                return True
                    except:
                        pass
            except Exception as e:
                print("CAPTURE_ERROR=" + str(e))
            return False

    CaptureBreakpoint("*{breakpoint_addr:#x}")
    end
    continue
    quit
""")


def _pid_alive(pid: int) -> bool:
    """进程存活判定：僵尸视同死亡（微信重启链中旧进程会残留为 Z）。"""
    return _process_state(pid) not in {"", "Z"}


def _pdeathsig() -> None:  # pragma: no cover - 子进程侧执行
    """gdb 子进程随父（线程）退出被内核回收——防孤儿调试器永久占用微信 ptrace。

    实测事故：应用退出时 Python 清理不执行，gdb 野进程（PPID=1）持续附加微信，
    导致后续捕获报「微信进程已被 PID=xxx 的调试器占用」。
    """
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
    except Exception:
        pass


def _wait_for_new_wechat_pid(old_pid: int, timeout: float = 20.0) -> Optional[int]:
    """等待「退出登录」拉起的新微信进程（旧 pid 死亡后出现的新 pid）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = [p for p in find_linux_wechat_pids() if p != old_pid]
        if pids:
            return pids[0]
        time.sleep(0.2)
    return None


# 二进制未变时复用断点偏移（ELF 全量分析约 1 分钟，重登转挂时不能重复花）
_cached_offsets: dict[str, list[int]] = {}


def _hook_offsets_cached(pid: int) -> list[int]:
    exe = os.readlink(f"/proc/{pid}/exe")
    try:
        stat = os.stat(f"/proc/{pid}/exe")
        cache_key = f"{exe}:{stat.st_ino}:{stat.st_size}"
    except OSError:
        cache_key = exe
    if cache_key not in _cached_offsets:
        _cached_offsets[cache_key] = find_hook_offsets(f"/proc/{pid}/exe")
    return _cached_offsets[cache_key]


def capture_passphrase_via_gdb(pid: int, timeout: int = 180) -> str:
    """GDB 断点捕获 passphrase。需要用户在此期间于微信「退出登录并重新登录」。

    微信「退出登录」会重启主进程：本函数带 pid 监护——附加中的进程一旦死亡，
    立即寻找新进程并转挂（登录扫码窗口足够完成转挂），确保断点始终在
    「即将执行登录」的进程上。
    """
    if not shutil.which("gdb"):
        raise RuntimeError("未安装 GDB，请运行: sudo apt install gdb")

    deadline = time.monotonic() + max(30, timeout)
    current_pid = pid
    gdb_proc: subprocess.Popen | None = None
    gdb_outputs: list[str] = []

    def _launch_gdb(target_pid: int) -> subprocess.Popen:
        exe_link = os.readlink(f"/proc/{target_pid}/exe")
        hook_vas = _hook_offsets_cached(target_pid)
        breakpoint_addrs = [va_to_runtime_addr(target_pid, exe_link, va) for va in hook_vas]
        logger.info(
            "[LinuxKey] 转挂 PID=%s 断点: %s",
            target_pid, ", ".join(f"0x{a:X}" for a in breakpoint_addrs),
        )
        breakpoint_lines = "\n".join(
            f'    CaptureBreakpoint("*{addr:#x}")' for addr in breakpoint_addrs
        )
        script = _GDB_SCRIPT_TEMPLATE.format(pid=target_pid, breakpoint_addr=breakpoint_addrs[0])
        script = script.replace(
            f'    CaptureBreakpoint("*{breakpoint_addrs[0]:#x}")', breakpoint_lines
        )
        tmpdir = tempfile.mkdtemp(prefix="chrono-key-")
        script_path = pathlib.Path(tmpdir) / "capture.gdb"
        script_path.write_text(script)
        return subprocess.Popen(
            ["gdb", "-q", "--nx", "-batch", "-x", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=_pdeathsig,
        )

    try:
        while time.monotonic() < deadline:
            # 1) 上一轮 gdb 已结束（成功或异常退出）：检查输出
            if gdb_proc is not None and gdb_proc.poll() is not None:
                output = gdb_proc.stdout.read() if gdb_proc.stdout else ""
                gdb_outputs.append(output)
                match = PASSPHRASE_RE.search(output)
                if match:
                    logger.info("[LinuxKey] passphrase 捕获成功")
                    return match.group(1).lower()
                logger.info("[LinuxKey] gdb 会话结束（未捕获），重新附加…")
                gdb_proc = None

            # 2) 目标进程死亡（完全退出/重登重启）：清理并等待新进程
            if not _pid_alive(current_pid):
                if gdb_proc is not None:
                    gdb_proc.kill()
                    try:
                        gdb_outputs.append(gdb_proc.stdout.read() or "")
                    except Exception:
                        pass
                    gdb_proc = None
                    subprocess.run(["killall", "-9", "gdb"], capture_output=True, timeout=5)
                remaining = deadline - time.monotonic()
                new_pid = _wait_for_new_wechat_pid(current_pid, timeout=min(30, max(1, remaining)))
                if new_pid is None:
                    if remaining <= 0:
                        break
                    time.sleep(0.3)
                    continue
                current_pid = new_pid
                logger.info("[LinuxKey] 检测到微信进程重启，转挂新 PID=%s", current_pid)

            # 3) 附加当前进程（首次启动与转挂共用）
            if gdb_proc is None:
                gdb_proc = _launch_gdb(current_pid)
                time.sleep(1.0)  # 给 gdb 一点附加时间，下一轮再检查状态

            time.sleep(0.3)

        # 超时收尾
        if gdb_proc is not None:
            gdb_proc.kill()
            try:
                gdb_outputs.append(gdb_proc.stdout.read() or "")
            except Exception:
                pass
            subprocess.run(["killall", "-9", "gdb"], capture_output=True, timeout=5)
    finally:
        if gdb_proc is not None and gdb_proc.poll() is None:
            gdb_proc.kill()
            subprocess.run(["killall", "-9", "gdb"], capture_output=True, timeout=5)

    combined = "\n".join(gdb_outputs)
    if "Operation not permitted" in combined or "ptrace" in combined.lower():
        raise RuntimeError(
            "GDB 无法附加微信进程：请执行 echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope，"
            "或以 sudo 运行本应用。"
        )
    error_match = CAPTURE_ERROR_RE.search(combined)
    if error_match:
        raise RuntimeError(f"捕获出错: {error_match.group(1)}")
    hit_lines = [ln for ln in combined.splitlines() if ln.startswith("BP_HIT")]
    detail = f"（断点命中 {len(hit_lines)} 次：{hit_lines[-3:]}）" if hit_lines else "（断点未命中）"
    raise RuntimeError(
        f"超时未捕获 passphrase。{detail} 请确保在捕获期间于微信中重新登录。"
        f" gdb 输出尾部: {combined[-400:]}"
    )


# ============================================================
# 会话与 Provider（与 Windows WeChatKeyCaptureSession 同形契约）
# ============================================================

class LinuxKeyCaptureSession:
    """Linux 密钥捕获会话：状态字与结果字段与 Windows 版保持同形。

    状态流：preparing → hook_ready（GDB 已附加，等待重新登录）→ captured /
    failed / timed_out。Linux 免重启微信——只需「退出登录并重新登录」。
    """

    def __init__(self, *, timeout_seconds: int = 180, account_wxid: str = ""):
        self.timeout_seconds = max(30, int(timeout_seconds or 180))
        self.account_wxid = str(account_wxid or "")
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = "preparing"
        self._message = "正在准备密钥捕获。"
        self._result: dict[str, Any] | None = None

    def start(self, ready_timeout_seconds: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="linux-wechat-key-capture", daemon=True
                )
                self._thread.start()
        if ready_timeout_seconds is None:
            # 冷启动 ELF 锚点分析余量（bytes.find 优化后秒级，90s 为异常兜底）
            ready_timeout_seconds = 90
        if not self._ready.wait(timeout=max(1, int(ready_timeout_seconds))):
            return {
                "ok": False,
                "status": "failed",
                "code": "hook_prepare_timeout",
                "error": "密钥捕获准备超时。",
            }
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = {
                "ok": self._status not in {"failed", "timed_out"},
                "status": self._status,
                "message": self._message,
                "account_wxid": self.account_wxid,
            }
            if self._result:
                payload.update(self._result)
            return payload

    def _set_result(self, status: str, message: str, result: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._status = status
            self._message = message
            self._result = dict(result or {})

    def _run(self) -> None:
        pids = find_linux_wechat_pids()
        if not pids:
            self._set_result(
                "failed", "微信未运行，请先启动微信。",
                {"code": "wechat_not_running", "error": "微信未运行，请先启动微信。"},
            )
            self._ready.set()
            return
        pid = pids[0]

        reason = _check_ptrace_permission(pid) or _check_tracer(pid)
        if reason:
            self._set_result(
                "failed", reason,
                {"code": "ptrace_denied", "error": reason},
            )
            self._ready.set()
            return

        try:
            os.readlink(f"/proc/{pid}/exe")
            find_hook_offset(f"/proc/{pid}/exe")
        except Exception as exc:
            self._set_result(
                "failed", f"微信二进制分析失败: {exc}",
                {"code": "elf_analysis_failed", "error": str(exc)},
            )
            self._ready.set()
            return

        self._set_result(
            "hook_ready",
            "已附加微信进程，请在微信中「退出登录并重新登录」以触发密钥捕获…",
        )
        self._ready.set()

        try:
            passphrase = capture_passphrase_via_gdb(pid, timeout=self.timeout_seconds)
        except Exception as exc:
            self._set_result(
                "failed", f"密钥捕获失败: {exc}",
                {"code": "capture_failed", "error": str(exc)},
            )
            return

        self._set_result(
            "captured",
            "密钥捕获成功。",
            {"db_key": passphrase.lower(), "pid": pid},
        )


class LinuxWeChatKeyProvider:
    """与 Windows WeChatKeyProvider 同形结果协议的 Linux 实现。"""

    @staticmethod
    def capture_db_key(timeout_seconds: int = 180, account_wxid: str = "") -> dict[str, Any]:
        session = LinuxKeyCaptureSession(
            timeout_seconds=timeout_seconds, account_wxid=account_wxid
        )
        session.start()
        # 一次性调用需等到终态（start 只等到 hook_ready，后台捕获仍在进行）
        deadline = time.monotonic() + session.timeout_seconds + 5
        snapshot = session.snapshot()
        while time.monotonic() < deadline and snapshot.get("status") not in {
            "captured", "failed", "timed_out",
        }:
            time.sleep(0.3)
            snapshot = session.snapshot()
        if snapshot.get("status") == "captured":
            return {
                "ok": True,
                "db_key": snapshot.get("db_key"),
                "pid": snapshot.get("pid"),
            }
        return {
            "ok": False,
            "error": snapshot.get("error") or snapshot.get("message") or "密钥捕获失败。",
            "code": snapshot.get("code"),
        }

    @staticmethod
    def create_capture_session(
        timeout_seconds: int = 180, account_wxid: str = ""
    ) -> LinuxKeyCaptureSession:
        return LinuxKeyCaptureSession(
            timeout_seconds=timeout_seconds, account_wxid=account_wxid
        )


if __name__ == "__main__":
    # CLI 冒烟：python -m app.services.wechat.keys.gdb_linux
    import sys as _sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _pids = find_linux_wechat_pids()
    if not _pids:
        print("微信未运行")
        _sys.exit(1)
    print(f"微信 PID: {_pids[0]}")
    print("请在微信中「退出登录并重新登录」…")
    session = LinuxKeyCaptureSession(timeout_seconds=180)
    session.start()
    # CLI 场景阻塞轮询到终态（应用内由前端轮询 snapshot）
    import time as _time

    while True:
        snap = session.snapshot()
        if snap.get("status") in {"captured", "failed", "timed_out"}:
            break
        print(f"[状态] {snap.get('status')}: {snap.get('message')}", flush=True)
        _time.sleep(2)
    print(snap)
    _sys.exit(0 if snap.get("status") == "captured" else 1)
