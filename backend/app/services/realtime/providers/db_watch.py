"""db_watch 实时监听 provider（Linux）：直接监听微信加密消息库文件。

与 UIA 方案的语义映射：
- open_chat(display_name)   → 按 contacts/conversations 解析 username → Msg_{md5} 表
- list_visible_messages()   → 返回当前窗口最近 WINDOW 条（基线机制天然适配：
                              monitor 首调 seed 全窗口，之后靠 seen 集合去重）
- scroll_up/down            → 纯数据翻页（窗口向老方向扩展/收回）
- activate_main_window      → no-op（DB 方案无需窗口焦点）

数据来源：EncryptedShardWatcher 增量解密（mtime 触发 + WAL 帧合并），
db_key/wechat_dir 取自激活微信账号设置。
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import re
import select
import threading
from datetime import datetime
from pathlib import Path

from .base import ProviderInitError, RealtimeProvider
from .models import RealtimeMessage, build_message_hash
from ....config import TEMP_DIR_PATH
from ...wechat.account_settings import get_active_wechat_account, load_settings_from_file
from ...wechat.db_snapshot import EncryptedShardWatcher
from ...wechat.path_finder import WeChatPathFinder

logger = logging.getLogger(__name__)

# inotify 事件掩码（ctypes 直调系统调用，零第三方依赖）
_IN_MODIFY = 0x00000002
_IN_CLOSE_WRITE = 0x00000008
_IN_NONBLOCK = 0o4000  # O_NONBLOCK
_INOTIFY_EVENT_SIZE = 16  # struct inotify_event 固定头（不含 name）


def _inotify_available() -> bool:
    """进程级探测：inotify_init1 可调用即视为可用。"""
    global _INOTIFY_OK
    if _INOTIFY_OK is None:
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            fd = libc.inotify_init1(_IN_NONBLOCK)
            if fd >= 0:
                import os as _os
                _os.close(fd)
                _INOTIFY_OK = True
            else:
                _INOTIFY_OK = False
        except Exception:
            _INOTIFY_OK = False
    return _INOTIFY_OK


_INOTIFY_OK: bool | None = None


# local_type → 监听器词表（与 native_uia 的映射保持一致口径）
LOCAL_TYPE_TO_MESSAGE_TYPE = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    49: "file",
    10000: "system",
}

NON_TEXT_PLACEHOLDER = {
    "image": "[图片]",
    "voice": "[语音]",
    "video": "[视频]",
    "emoji": "[表情]",
    "file": "[文件]",
}


class DbWatchRealtimeProvider(RealtimeProvider):
    """以加密库文件为数据源的实时监听 provider。"""

    backend_name = "db_watch"
    WINDOW = 50
    PAGE = 200

    def __init__(self, listener_profile: str = "db_watch", wechat_version: str = "", hwnd: int = 0):
        super().__init__()
        self.listener_profile = listener_profile
        self.wechat_version = wechat_version
        self._watchers: list[EncryptedShardWatcher] = []
        self._my_rowids: dict[int, int | None] = {}  # shard_idx -> name2id rowid
        self._table = ""
        self._username = ""
        self._upper_seq = 0
        self._extra_older = 0
        # inotify 文件变化通知（不可用时降级为 stat 轮询——行为不变）
        self._wakeup_event = threading.Event()
        self._inotify_fd: int = -1
        self._inotify_thread: threading.Thread | None = None
        self._last_nochange_result: list | None = None  # 无变化缓存的上一轮消息

    # ---------- 契约实现 ----------

    def initialize(self) -> None:
        settings = load_settings_from_file()
        account = get_active_wechat_account(settings) or {}
        db_key = str(account.get("db_key") or "").strip()
        wechat_dir = str(account.get("wechat_dir") or "").strip()
        wxid = str(account.get("wxid") or "").strip()
        if not (db_key and wechat_dir and wxid):
            raise ProviderInitError(
                "缺少微信账号配置（密钥/数据目录），请先完成密钥获取与账号设置。"
            )

        databases = WeChatPathFinder.find_databases(wxid, wechat_dir)
        message_dbs = [p for p in databases.get("message", [])]
        if not message_dbs:
            raise ProviderInitError(f"未找到消息数据库: {wechat_dir}")

        # Windows 只读扫描账号：按库 salt 直取 raw key（Linux GDB 产物为 passphrase）
        raw_keys = None
        if str(account.get("key_type") or "passphrase") == "raw":
            raw_keys = dict(account.get("raw_keys") or {})

        # 密钥有效性抽查（首个分片首页 HMAC）
        from ...wechat.db_decryptor_v2 import WeChatDBDecryptorV2
        validator = WeChatDBDecryptorV2()
        if raw_keys:
            validator.set_raw_key_map(raw_keys)
        first_page = Path(message_dbs[0]).read_bytes()[:4096]
        if not validator.validate_key(first_page, bytes.fromhex(db_key)):
            raise ProviderInitError("密钥校验失败，请重新获取微信数据库密钥。")

        cache_dir = Path(TEMP_DIR_PATH) / "dbwatch"
        for shard_path in message_dbs:
            try:
                self._watchers.append(EncryptedShardWatcher(
                    Path(shard_path), db_key, cache_dir, raw_keys=raw_keys
                ))
            except Exception as exc:
                logger.warning("[db_watch] 分片初始化失败 %s: %s", shard_path, exc)
        if not self._watchers:
            raise ProviderInitError("消息数据库分片全部初始化失败。")
        self.account_name = wxid
        logger.info("[db_watch] 已初始化 %d 个消息分片", len(self._watchers))
        self._start_inotify()

    def activate_main_window(self) -> bool:
        return True  # DB 方案不依赖窗口焦点

    def open_chat(self, display_name: str, expected_display_name: str | None = None) -> bool:
        username = self._resolve_username(display_name)
        if not username:
            logger.warning("[db_watch] 无法解析联系人: %s", display_name)
            return False
        table = "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()
        for idx, watcher in enumerate(self._watchers):
            row = watcher.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if row:
                self._table = table
                self._username = username
                self.current_display_name = display_name
                self._upper_seq = self._max_seq(table)
                self._extra_older = 0
                self._my_rowids = {i: self._resolve_my_rowid(w) for i, w in enumerate(self._watchers)}
                return True
        logger.info("[db_watch] %s 的消息表不存在于任何分片", display_name)
        return False

    def list_visible_messages(self) -> list:
        if not self._table:
            return []

        # inotify 可用时：等事件（毫秒级响应）而非 stat 轮询；
        # 不可用时直接走 stat 轮询路径（每秒被 monitor 调用，行为不变）
        if self._inotify_fd >= 0:
            # 已有待处理事件或超时 → 走刷新；否则返回缓存（跳过全部 stat+SQL）
            if not self._wakeup_event.is_set():
                self._wakeup_event.wait(timeout=0.05)
            if not self._wakeup_event.is_set() and self._last_nochange_result is not None:
                return self._last_nochange_result
            self._wakeup_event.clear()

        any_refreshed = False
        for watcher in self._watchers:
            try:
                if watcher.refresh():
                    any_refreshed = True
            except Exception as exc:
                logger.debug("[db_watch] 分片刷新失败（沿用旧快照）: %s", exc)
        self._upper_seq = max(self._upper_seq, self._max_seq(self._table))

        # inotify 模式下无变化：缓存本轮结果供下次短路
        if self._inotify_fd >= 0 and not any_refreshed and self._last_nochange_result is not None:
            return self._last_nochange_result

        limit = self.WINDOW + max(0, self._extra_older)
        rows: list[tuple[int, dict]] = []
        for idx, watcher in enumerate(self._watchers):
            try:
                cur = watcher.connection.execute(
                    f"SELECT local_id, server_id, local_type, sort_seq, real_sender_id, "
                    f"create_time, message_content FROM [{self._table}] "
                    f"WHERE sort_seq <= ? ORDER BY sort_seq DESC LIMIT ?",
                    (self._upper_seq, limit),
                )
                rows.extend((idx, dict(r)) for r in cur.fetchall())
            except Exception as exc:
                logger.debug("[db_watch] 分片 %d 查询失败: %s", idx, exc)

        rows.sort(key=lambda item: item[1]["sort_seq"], reverse=True)
        rows = rows[:limit]
        rows.reverse()  # oldest → newest

        messages: list[RealtimeMessage] = []
        for visible_index, (shard_idx, row) in enumerate(rows):
            messages.append(self._to_message(shard_idx, row, visible_index))
        self._last_nochange_result = messages
        return messages

    def scroll_up(self, wheel_times: int = 2) -> bool:
        self._extra_older += self.PAGE * max(1, wheel_times)
        self._last_nochange_result = None  # 窗口扩展需重查
        return True

    def scroll_down(self, wheel_times: int = 4) -> bool:
        self._extra_older = max(0, self._extra_older - self.PAGE * max(1, wheel_times))
        self._last_nochange_result = None  # 窗口收缩需重查
        return True

    def close(self) -> None:
        self._stop_inotify()
        for watcher in self._watchers:
            try:
                watcher.close()
            except Exception:
                pass
        self._watchers = []
        self._last_nochange_result = None

    # ---------- 内部 ----------

    # ---------- inotify 文件变化通知 ----------

    def _start_inotify(self) -> None:
        """为每个分片的 .db 和 -wal 注册 inotify 监听；失败静默降级 stat 轮询。"""
        if not _inotify_available():
            logger.info("[db_watch] inotify 不可用，降级为 stat 轮询")
            return
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            fd = libc.inotify_init1(_IN_NONBLOCK)
            if fd < 0:
                logger.warning("[db_watch] inotify_init1 失败: errno={}".format(ctypes.get_errno()))
                return
            import os as _os
            watched = 0
            for watcher in self._watchers:
                for path in (str(watcher.src), str(watcher.src) + "-wal"):
                    if _os.path.exists(path):
                        wd = libc.inotify_add_watch(fd, path.encode(), _IN_MODIFY | _IN_CLOSE_WRITE)
                        if wd >= 0:
                            watched += 1
            if watched == 0:
                _os.close(fd)
                logger.warning("[db_watch] inotify 无可监听文件，降级为 stat 轮询")
                return
            self._inotify_fd = fd
            self._inotify_thread = threading.Thread(
                target=self._inotify_loop, daemon=True, name="db-watch-inotify"
            )
            self._inotify_thread.start()
            logger.info("[db_watch] inotify 监听 %d 个文件（毫秒级变化通知）", watched)
        except Exception as exc:
            logger.warning("[db_watch] inotify 启动失败（降级 stat 轮询）: %s", exc)
            self._stop_inotify()

    def _stop_inotify(self) -> None:
        if self._inotify_fd >= 0:
            try:
                import os as _os
                _os.close(self._inotify_fd)
            except Exception:
                pass
            self._inotify_fd = -1
        self._inotify_thread = None

    def _inotify_loop(self) -> None:
        """inotify 事件循环：select() 无忙等，事件到达设 wakeup_event。"""
        import os as _os
        buf = b""
        while self._inotify_fd >= 0:
            try:
                readable, _, _ = select.select([self._inotify_fd], [], [], 30.0)
                if not readable:
                    continue  # 30s 超时——保持 fd 存活检查
                chunk = _os.read(self._inotify_fd, 65536)
                if not chunk:
                    break
                buf += chunk
                # 解析事件（只需要知道「有事件」而非哪个文件——refresh 全分片 stat）
                while len(buf) >= _INOTIFY_EVENT_SIZE:
                    event_len = _INOTIFY_EVENT_SIZE + int.from_bytes(buf[16:20], "little")
                    if len(buf) < event_len:
                        break
                    buf = buf[event_len:]
                self._wakeup_event.set()
            except Exception:
                import time as _t
                _t.sleep(0.5)
                if self._inotify_fd < 0:
                    return

    def _max_seq(self, table: str) -> int:
        best = 0
        for watcher in self._watchers:
            try:
                row = watcher.connection.execute(
                    f"SELECT MAX(sort_seq) FROM [{table}]"
                ).fetchone()
                if row and row[0]:
                    best = max(best, int(row[0]))
            except Exception:
                continue
        return best

    def _resolve_username(self, display_name: str) -> str:
        name = str(display_name or "").strip()
        if not name:
            return ""
        try:
            from ....db.connection import get_db
            conn = get_db()
            row = conn.execute(
                """
                SELECT username FROM contacts
                WHERE (remark = ? OR nickname = ?)
                ORDER BY CASE WHEN remark = ? THEN 0 ELSE 1 END, username ASC LIMIT 1
                """,
                (name, name, name),
            ).fetchone()
            if row and row[0]:
                return str(row[0]).strip()
            row = conn.execute(
                """
                SELECT username FROM conversations
                WHERE display_name = ? OR username = ?
                ORDER BY message_count DESC, updated_at DESC LIMIT 1
                """,
                (name, name),
            ).fetchone()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception as exc:
            logger.debug("[db_watch] 解析联系人失败: %s", exc)
        return name

    def _resolve_my_rowid(self, watcher: EncryptedShardWatcher) -> int | None:
        """在分片 name2id 中解析本人 rowid（目录名后缀剥离，双候选匹配）。"""
        if not self.account_name:
            return None
        candidates = [self.account_name]
        m = re.match(r"^(.+)_([0-9a-zA-Z]{4,6})$", self.account_name)
        if m and len(m.group(1)) >= 2:
            candidates.append(m.group(1))
        for name in candidates:
            try:
                row = watcher.connection.execute(
                    "SELECT rowid FROM name2id WHERE user_name = ? LIMIT 1", (name,)
                ).fetchone()
                if row:
                    return int(row[0])
            except Exception:
                continue
        return None

    def _to_message(self, shard_idx: int, row: dict, visible_index: int) -> RealtimeMessage:
        local_type = int(row.get("local_type") or 1)
        message_type = LOCAL_TYPE_TO_MESSAGE_TYPE.get(local_type, "text")
        raw_content = row.get("message_content") or ""
        if isinstance(raw_content, bytes):
            raw_content = raw_content.decode("utf-8", errors="replace")
        if message_type == "text":
            content = str(raw_content)
        elif message_type == "system":
            content = re.sub(r"<[^>]+>", "", str(raw_content))[:80] or "[系统消息]"
        else:
            content = NON_TEXT_PLACEHOLDER.get(message_type, "[消息]")

        my_rowid = self._my_rowids.get(shard_idx)
        sender_attr = "self" if (my_rowid is not None and int(row.get("real_sender_id") or 0) == my_rowid) else "friend"

        timestamp = int(row.get("create_time") or 0)
        timestamp_label = datetime.fromtimestamp(timestamp).strftime("%H:%M") if timestamp else ""
        local_id = int(row.get("local_id") or 0)
        server_id = int(row.get("server_id") or 0)
        runtime_id = f"{shard_idx}:{local_id}:{server_id}"

        return RealtimeMessage(
            runtime_id=runtime_id,
            sender_attr=sender_attr,
            content=content,
            message_type=message_type,
            timestamp_label=timestamp_label,
            timestamp=timestamp,
            message_hash=build_message_hash(
                self.backend_name, sender_attr, message_type, content, timestamp, runtime_id
            ),
            is_system=(message_type == "system"),
            visible_index=visible_index,
            metadata={
                "sort_seq": int(row.get("sort_seq") or 0),
                "local_type": local_type,
                "username": self._username,
            },
        )
