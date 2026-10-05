from typing import Any, Optional
import json
import os
import logging
import sys
import threading
import time
import re
import uuid
from pathlib import Path
from ..config import SETTINGS_PATH
from ..services.wechat.ingest_service import WeChatIngestService
from ..services.wechat.path_finder import WeChatPathFinder
from ..services.wechat.db.v4.contact import ContactDBV4
from ..services.wechat.account_settings import (
    LEGACY_WECHAT_KEYS,
    WECHAT_ACCOUNTS_KEY,
    WECHAT_ACTIVE_ACCOUNT_KEY,
    build_custom_paths,
    get_active_wechat_account,
    get_active_wechat_account_wxid,
    get_wechat_account,
    get_wechat_accounts,
    load_settings_from_file,
    normalize_wechat_accounts,
    save_settings_to_file,
    set_active_wechat_account,
    upsert_wechat_account,
    update_wechat_account_import_state,
)
from ..services.analysis.feature_extraction_config import (
    ANALYSIS_DEVICE_MODE_AUTO,
    normalize_analysis_device_mode,
)
from ..services.model_paths import (
    EMBEDDING_MODEL_DIM,
    EMBEDDING_MODEL_REPO_ID,
    MODEL_ROOT_DIR_KEY,
    get_default_model_root_dir,
    get_embedding_model_dir,
    get_sentiment_model_dir,
    normalize_model_root_dir,
)

logger = logging.getLogger(__name__)
from .api.affinity import AffinityApiMixin
from .api.rag_admin import RagAdminApiMixin
from .api.key_capture import KeyCaptureApiMixin
from .api.llm_models import LlmModelsApiMixin
from .api.analysis_read import AnalysisReadApiMixin
from .api.window import WindowApiMixin
from .api.gpu import GpuApiMixin
from .api.model_mgmt import ModelMgmtApiMixin
from .api.profile import ProfileApiMixin


class Bridge(
    AffinityApiMixin, RagAdminApiMixin, KeyCaptureApiMixin,
    LlmModelsApiMixin, AnalysisReadApiMixin, WindowApiMixin,
    GpuApiMixin, ModelMgmtApiMixin, ProfileApiMixin,
):
    """PyWebView JS API Bridge: 暴露给前端调用的方法。"""

    def __init__(self):
        self.wechat_service = WeChatIngestService()
        self.settings_file = Path(SETTINGS_PATH)
        # 设置读写锁：每个 JS 调用跑在独立线程，settings 的「读-改-写」复合操作必须串行化
        self._settings_lock = threading.RLock()
        self._load_settings()

        # 延迟加载特征提取服务（避免循环导入）
        self._feature_service = None

        # 悬浮窗管理服务
        from ..services.realtime.floating_window_service import FloatingWindowService
        self._floating_service = FloatingWindowService()
        self._model_download_status: dict[str, dict[str, Any]] = {}
        self._model_download_lock = threading.Lock()
        self._suggestion_streams: dict[str, dict[str, Any]] = {}
        self._suggestion_stream_lock = threading.Lock()
        self._wechat_key_capture_sessions: dict[str, dict[str, Any]] = {}
        self._wechat_key_capture_lock = threading.Lock()
        self._wechat_import_tasks: dict[str, dict[str, Any]] = {}
        self._wechat_import_lock = threading.Lock()
        self._webview_window = None  # 由 app_dev.py 注入
        self._analysis_cancel_event = None  # 用于取消好感度分析
        self._affinity_service = None  # 好感度分析服务实例（analyze_affinity 中懒创建）
        self._close_actions: dict[str, Any] = {}  # 关闭守卫动作（close_guard 装配）

    def _load_settings(self):
        """加载设置"""
        with self._settings_lock:
            self.settings = load_settings_from_file(self.settings_file)
            self.settings["analysis_device_mode"] = normalize_analysis_device_mode(
                self.settings.get("analysis_device_mode", ANALYSIS_DEVICE_MODE_AUTO)
            )
            self.settings[MODEL_ROOT_DIR_KEY] = normalize_model_root_dir(
                self.settings.get(MODEL_ROOT_DIR_KEY)
            )

    def _save_settings(self):
        """保存设置"""
        with self._settings_lock:
            try:
                save_settings_to_file(self.settings, self.settings_file)
            except Exception as e:
                logger.error(f"保存设置失败: {e}")

    def _get_wechat_accounts(self) -> list[dict[str, Any]]:
        return get_wechat_accounts(self.settings)

    def _get_active_wechat_account_wxid(self) -> str:
        return get_active_wechat_account_wxid(self.settings)

    def _get_wechat_account(self, wxid: str) -> Optional[dict[str, Any]]:
        return get_wechat_account(self.settings, wxid)

    def _get_active_wechat_account(self) -> Optional[dict[str, Any]]:
        return get_active_wechat_account(self.settings)

    def _resolve_account_wxid(self, account_wxid: str = "") -> str:
        normalized = str(account_wxid or "").strip()
        if normalized:
            return normalized
        return self._get_active_wechat_account_wxid()

    def _resolve_current_conversation_id(
        self,
        *,
        account_wxid: str,
        display_name: str = "",
        username: str = "",
    ) -> int | None:
        account = str(account_wxid or "").strip()
        display = str(display_name or "").strip()
        user = str(username or "").strip()
        if not account or (not display and not user):
            return None
        try:
            from ..db.connection import get_db

            row = get_db().execute(
                """
                SELECT id
                FROM conversations
                WHERE account_wxid = ?
                  AND is_deleted = 0
                  AND (display_name = ? OR username = ? OR username = ? OR display_name = ?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (account, display, display, user, user),
            ).fetchone()
            return int(row["id"]) if row else None
        except Exception as exc:
            logger.debug("[Bridge] resolve current conversation skipped: %s", exc)
            return None

    def _resolve_wechat_account(self, account_wxid: str = "") -> Optional[dict[str, Any]]:
        resolved_wxid = self._resolve_account_wxid(account_wxid)
        if resolved_wxid:
            return self._get_wechat_account(resolved_wxid)
        return self._get_active_wechat_account()

    def _serialize_wechat_accounts(self) -> dict[str, Any]:
        return {
            "accounts": self._get_wechat_accounts(),
            "active_account_wxid": self._get_active_wechat_account_wxid(),
        }

    def _update_model_download_status(self, task_id: str, **updates: Any) -> None:
        now_ms = int(time.time() * 1000)
        with self._model_download_lock:
            is_new = task_id not in self._model_download_status
            current = self._model_download_status.get(task_id, {}).copy()
            if is_new:
                current["created_at"] = now_ms
            current["updated_at"] = now_ms
            current.update(updates)
            self._model_download_status[task_id] = current
        if is_new:
            # 新增条目时顺带清理过期任务，防止长驻进程内存无界增长。
            # 注意：必须在锁外调用，避免与 _prune_task_dicts 内部加锁形成 ABBA 死锁
            self._prune_task_dicts()

    def _get_model_download_status(self, task_id: str) -> dict[str, Any]:
        with self._model_download_lock:
            status = self._model_download_status.get(task_id)
        return status.copy() if status else {}

    def _update_wechat_import_status(self, task_id: str, **updates: Any) -> None:
        now_ms = int(time.time() * 1000)
        with self._wechat_import_lock:
            is_new = task_id not in self._wechat_import_tasks
            current = self._wechat_import_tasks.get(task_id, {}).copy()
            if is_new:
                current["created_at"] = now_ms
            current["updated_at"] = now_ms
            current.update(updates)
            self._wechat_import_tasks[task_id] = current
        if is_new:
            # 新增条目时顺带清理过期任务（锁外触发，防 ABBA 死锁，同上）
            self._prune_task_dicts()

    def _get_wechat_import_status(self, task_id: str) -> dict[str, Any]:
        with self._wechat_import_lock:
            status = self._wechat_import_tasks.get(task_id)
        return status.copy() if status else {}

    def _find_running_wechat_import(self) -> str | None:
        """返回当前运行中的导入任务 id（无则 None）。

        thread 存活判定兜底：条目缺 thread 键（如测试手工注入）时保守
        视为存活，宁可复用也不并发双跑。
        """
        with self._wechat_import_lock:
            for task_id, entry in self._wechat_import_tasks.items():
                if entry.get("status") != "running":
                    continue
                thread = entry.get("thread")
                if thread is None or thread.is_alive():
                    return task_id
        return None

    def _prune_task_dicts(self, max_age_hours: float = 24.0) -> None:
        """按 TTL 清理四个任务字典（建议流/密钥捕获/模型下载/微信导入）中的过期条目。

        - 终态条目（建议流 done/error、捕获已出结果、下载 completed/failed、
          导入 completed/failed）超过 1 小时即删除；
        - 运行中条目超过 max_age_hours（默认 24 小时）也删除（视作僵死任务）。
        时间戳兼容秒/毫秒两种单位。调用方不得在持有这四个任务锁时调用（会死锁）。
        """
        now_ms = int(time.time() * 1000)
        terminal_max_age_ms = 60 * 60 * 1000  # 终态条目保留 1 小时
        running_max_age_ms = int(max_age_hours * 3600 * 1000)

        def _entry_ts_ms(entry: dict[str, Any]) -> int | None:
            for key in ("updated_at", "created_at"):
                raw = entry.get(key)
                if raw is None:
                    continue
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
                if value <= 0:
                    continue
                # 小于 1e12 视为秒级时间戳，统一换算成毫秒
                return value if value > 10**12 else value * 1000
            return None

        with self._suggestion_stream_lock:
            expired = []
            for stream_id, state in self._suggestion_streams.items():
                ts = _entry_ts_ms(state)
                if ts is None:
                    continue
                status = str(state.get("status") or "")
                is_terminal = status in {"done", "error", "completed", "failed", "cancelled"}
                deadline = terminal_max_age_ms if is_terminal else running_max_age_ms
                if now_ms - ts > deadline:
                    expired.append(stream_id)
            for stream_id in expired:
                self._suggestion_streams.pop(stream_id, None)

        with self._wechat_key_capture_lock:
            expired = []
            for session_id, entry in self._wechat_key_capture_sessions.items():
                ts = _entry_ts_ms(entry)
                if ts is None:
                    continue
                is_terminal = entry.get("final_result") is not None
                deadline = terminal_max_age_ms if is_terminal else running_max_age_ms
                if now_ms - ts > deadline:
                    expired.append(session_id)
            for session_id in expired:
                self._wechat_key_capture_sessions.pop(session_id, None)

        with self._model_download_lock:
            expired = []
            for task_id, entry in self._model_download_status.items():
                ts = _entry_ts_ms(entry)
                if ts is None:
                    continue
                status = str(entry.get("status") or "")
                is_terminal = status in {"completed", "failed", "cancelled"}
                deadline = terminal_max_age_ms if is_terminal else running_max_age_ms
                if now_ms - ts > deadline:
                    expired.append(task_id)
            for task_id in expired:
                self._model_download_status.pop(task_id, None)

        with self._wechat_import_lock:
            expired = []
            for task_id, entry in self._wechat_import_tasks.items():
                ts = _entry_ts_ms(entry)
                if ts is None:
                    continue
                status = str(entry.get("status") or "")
                is_terminal = status in {"completed", "failed"}
                deadline = terminal_max_age_ms if is_terminal else running_max_age_ms
                if now_ms - ts > deadline:
                    expired.append(task_id)
            for task_id in expired:
                self._wechat_import_tasks.pop(task_id, None)


    def ping(self) -> str:
        return "pong"


    def _get_wechat_custom_paths(self, account_wxid: str = "") -> dict[str, str] | None:
        return build_custom_paths(self._resolve_wechat_account(account_wxid))

    def _key_scan_wechat_dir(self, account_wxid: str = "") -> str:
        """供 Windows 只读扫描引擎定位数据库目录（按 salt 验证候选）；Linux 引擎不使用。"""
        try:
            paths = self._get_wechat_custom_paths(account_wxid) or {}
            return str(paths.get("wechat_dir") or "")
        except Exception:
            return ""

    def _build_wechat_user_candidates(self, wxid: str) -> list[str]:
        candidates: list[str] = []
        normalized = str(wxid or "").strip()
        if not normalized:
            return candidates
        candidates.append(normalized)
        match = re.match(r"^(.+)_([0-9a-zA-Z]{4,6})$", normalized)
        if match and len(match.group(1)) >= 2:
            base_wxid = match.group(1)
            if base_wxid not in candidates:
                candidates.append(base_wxid)
        return candidates

    def _save_wechat_import_baseline(
        self,
        snapshot: dict[str, Any],
        *,
        account_wxid: str = "",
        db_key: str | None = None,
        import_watermark_ts: int | None = None,
    ) -> None:
        resolved_wxid = self._resolve_account_wxid(account_wxid) or str(snapshot.get("account_wxid") or snapshot.get("current_user") or "")
        if not resolved_wxid:
            return
        with self._settings_lock:
            update_wechat_account_import_state(
                self.settings,
                resolved_wxid,
                snapshot=snapshot,
                db_key=db_key,
                wechat_dir=str(snapshot.get("wechat_dir") or "") or None,
                import_completed=True,
                # 消息水位与文件基线同锁同批落库（导入成功路径才会到这）
                import_watermark_ts=import_watermark_ts,
            )
            self._save_settings()

    def _build_wechat_account_candidate(
        self,
        wxid: str,
        *,
        wechat_dir: str,
        source: str,
        db_key: str = "",
        avatar: str = "",
        label: str | None = None,
    ) -> dict[str, Any]:
        existing = self._get_wechat_account(wxid) or {}
        return {
            "wxid": wxid,
            "label": label or existing.get("label") or wxid,
            "avatar": avatar or existing.get("avatar") or "",
            "wechat_dir": wechat_dir or existing.get("wechat_dir") or "",
            "source": source or existing.get("source") or "auto",
            "db_key": db_key or existing.get("db_key") or "",
            "import_completed": bool(existing.get("import_completed")),
            "last_import_at": existing.get("last_import_at"),
            "last_import_total_size": int(existing.get("last_import_total_size") or 0),
            "last_import_files": existing.get("last_import_files") or [],
        }

    def _sync_wechat_account_candidates(self, accounts: list[dict[str, Any]]) -> None:
        with self._settings_lock:
            changed = False
            for account in accounts:
                normalized = self._build_wechat_account_candidate(
                    str(account.get("wxid") or ""),
                    wechat_dir=str(account.get("wechat_dir") or ""),
                    source=str(account.get("source") or "auto"),
                    db_key=str(account.get("db_key") or ""),
                    avatar=str(account.get("avatar") or ""),
                    label=str(account.get("label") or "") or None,
                )
                if not normalized["wxid"]:
                    continue
                existing = self._get_wechat_account(normalized["wxid"]) or {}
                if existing != normalized:
                    upsert_wechat_account(self.settings, normalized)
                    changed = True
            if changed:
                self._save_settings()

    # ==================== 微信数据导入相关 ====================

    def get_wechat_accounts(self) -> dict[str, Any]:
        payload = self._serialize_wechat_accounts()
        return {"ok": True, **payload}

    def set_active_wechat_account(self, wxid: str) -> dict[str, Any]:
        try:
            with self._settings_lock:
                active_wxid = set_active_wechat_account(self.settings, wxid)
                self._save_settings()
            return {"ok": True, "active_account_wxid": active_wxid}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_wechat_paths(self, account_wxid: str = "") -> dict[str, Any]:
        """
        获取微信数据库路径信息（用于前端展示）
        
        Returns:
            {"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
        """
        resolved_account = self._resolve_wechat_account(account_wxid)
        preferred_paths = self._get_wechat_custom_paths(account_wxid)

        if preferred_paths:
            try:
                data = self.wechat_service.resolve_wechat_paths(preferred_paths)
                data["source"] = str((resolved_account or {}).get("source") or "custom")
                data["account_wxid"] = str((resolved_account or {}).get("wxid") or data.get("current_user") or "")
                data["accounts"] = self._get_wechat_accounts()
                data["active_account_wxid"] = self._get_active_wechat_account_wxid()
                return {"ok": True, "data": data, **self._serialize_wechat_accounts()}
            except Exception as e:
                logger.warning(f"[Bridge] 读取已保存微信路径失败，将回退自动检测: {e}")

        detected = self.wechat_service.get_wechat_paths()
        if not detected.get("ok"):
            return {**detected, **self._serialize_wechat_accounts()}

        data = detected.get("data") or {}
        wechat_dir = str(data.get("wechat_dir") or "")
        available_users = [
            str(wxid).strip()
            for wxid in (data.get("available_users") or [])
            if str(wxid).strip()
        ]
        candidates = [
            self._build_wechat_account_candidate(
                wxid,
                wechat_dir=wechat_dir,
                source="auto",
            )
            for wxid in available_users
        ]
        if candidates:
            self._sync_wechat_account_candidates(candidates)

        selected_wxid = self._resolve_account_wxid(account_wxid)
        if not selected_wxid and len(candidates) == 1:
            selected_wxid = candidates[0]["wxid"]

        if selected_wxid and wechat_dir and selected_wxid != data.get("current_user"):
            data["databases"] = WeChatPathFinder.find_databases(selected_wxid, wechat_dir)
            data["current_user"] = selected_wxid

        data["account_wxid"] = str(data.get("current_user") or selected_wxid or "")
        data["accounts"] = self._get_wechat_accounts()
        data["active_account_wxid"] = self._get_active_wechat_account_wxid()
        return {"ok": True, "data": data, **self._serialize_wechat_accounts()}


    def import_wechat_data(
        self,
        db_key: str,
        options: dict[str, Any] | None = None,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """启动异步微信数据导入，立即返回 task_id 供 get_import_progress 轮询。

        导入在 daemon 线程执行（全量重扫可达数十分钟，同步阻塞会让前端
        进度全程冻结）；同一时刻只允许一个导入任务，重复调用复用运行中
        任务。

        Args:
            db_key: 32位hex密钥
            options: 导入选项 {
                "import_contacts": bool,
                "import_messages": bool,
                "limit": int,
                "force_full": bool
            }

        Returns:
            {"ok": True, "task_id": "...", "reused": bool}
        """
        # —— 配置解析保留在调用线程（读 settings 的快操作）——
        options = dict(options or {})
        resolved_wxid = self._resolve_account_wxid(str(options.pop("account_wxid", "") or account_wxid))
        custom_paths = self._get_wechat_custom_paths(resolved_wxid)
        if custom_paths:
            logger.debug(f"[DEBUG Bridge] 使用自定义路径: {custom_paths}")
        else:
            logger.debug("[DEBUG Bridge] 未配置自定义路径,将使用自动检测")

        # Windows 只读扫描账号：导入需带每库 raw key 映射（passphrase 账号不传）
        raw_keys = None
        account = self._resolve_wechat_account(resolved_wxid) or {}
        if str(account.get("key_type") or "passphrase") == "raw":
            raw_keys = account.get("raw_keys") or {}

        # 注入账号消息水位（时间增量读取；force_full 由 options 显式覆盖，service 侧忽略水位）
        if "import_watermark_ts" not in options:
            options["import_watermark_ts"] = int(account.get("import_watermark_ts") or 0)

        # —— 防重入与预注册在同一锁区间，杜绝「检查后、注册前」窗口双跑 ——
        with self._wechat_import_lock:
            for existing_id, entry in self._wechat_import_tasks.items():
                if entry.get("status") != "running":
                    continue
                thread = entry.get("thread")
                if thread is None or thread.is_alive():
                    return {"ok": True, "task_id": existing_id, "reused": True}
            task_id = f"wechat_import_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            now_ms = int(time.time() * 1000)
            self._wechat_import_tasks[task_id] = {
                "task_id": task_id,
                "status": "running",
                "phase": "resolving_paths",
                "phase_label": "查找数据库路径...",
                "percent": 0.0,
                "conversation_idx": 0,
                "conversation_total": 0,
                "inserted_messages": 0,
                "inserted_contacts": 0,
                "started_at": now_ms,
                "created_at": now_ms,
                "updated_at": now_ms,
                "error": None,
                "result": None,
                "thread": None,
            }

        def _progress(status_text: str, current: int, total: int, detail: dict | None = None) -> None:
            # 回调写入失败绝不杀死导入线程
            try:
                detail = detail or {}
                updates: dict[str, Any] = {
                    "status": "running",
                    "phase_label": status_text,
                    "percent": float(current),
                }
                if detail.get("phase"):
                    updates["phase"] = detail["phase"]
                for key in ("conversation_idx", "conversation_total", "inserted_messages"):
                    if key in detail:
                        updates[key] = int(detail[key] or 0)
                self._update_wechat_import_status(task_id, **updates)
            except Exception as exc:
                logger.debug("[Bridge] 导入进度回调写入失败(忽略): %s", exc)

        def _run() -> None:
            try:
                result = self.wechat_service.import_wechat_data(
                    db_key, options, custom_paths, progress_callback=_progress, raw_keys=raw_keys
                )
                if result.get("ok"):
                    # 基线保存在 worker 线程完成（内部走 self._settings_lock，线程安全）
                    snapshot = self.wechat_service.build_file_size_snapshot(custom_paths)
                    watermark_out = (result.get("stats") or {}).get("import_watermark_ts")
                    self._save_wechat_import_baseline(
                        snapshot, account_wxid=resolved_wxid, db_key=db_key,
                        import_watermark_ts=watermark_out,
                    )
                    self._update_wechat_import_status(
                        task_id, status="completed", phase="done", percent=100.0,
                        phase_label="导入完成",
                        inserted_contacts=(result.get("stats") or {}).get("inserted_contacts", 0),
                        result=result,
                    )
                else:
                    self._update_wechat_import_status(
                        task_id, status="failed",
                        error=str(result.get("error") or "导入失败"), result=result,
                    )
            except Exception as exc:
                logger.error("[Bridge] 异步微信导入失败: %s", exc, exc_info=True)
                self._update_wechat_import_status(task_id, status="failed", error=str(exc))

        thread = threading.Thread(target=_run, name=f"WechatImport-{task_id}", daemon=True)
        with self._wechat_import_lock:
            self._wechat_import_tasks[task_id]["thread"] = thread
        thread.start()
        return {"ok": True, "task_id": task_id, "reused": False}

    def get_import_progress(self, task_id: str) -> dict[str, Any]:
        """查询导入任务进度（前端 1s 轮询；终态时 result 携带完整 stats）。"""
        entry = self._get_wechat_import_status(str(task_id or ""))
        if not entry:
            return {"ok": False, "status": "not_found", "error": "导入任务不存在或已过期"}
        now_ms = int(time.time() * 1000)
        # 终态冻结耗时（updated_at-started_at），运行中实时计算
        try:
            started = int(entry.get("started_at") or 0)
            if entry.get("status") in {"completed", "failed"}:
                elapsed = max(0, int(entry.get("updated_at") or now_ms) - started)
            else:
                elapsed = max(0, now_ms - started)
        except (TypeError, ValueError):
            elapsed = 0
        return {
            "ok": True,
            "task_id": entry.get("task_id"),
            "status": entry.get("status"),
            "phase": entry.get("phase"),
            "phase_label": entry.get("phase_label"),
            "percent": float(entry.get("percent") or 0.0),
            "conversation_idx": int(entry.get("conversation_idx") or 0),
            "conversation_total": int(entry.get("conversation_total") or 0),
            "inserted_messages": int(entry.get("inserted_messages") or 0),
            "inserted_contacts": int(entry.get("inserted_contacts") or 0),
            "elapsed_ms": elapsed,
            "error": entry.get("error"),
            "result": entry.get("result"),
        }

    def refresh_wechat_contact_avatars(
        self,
        db_key: str,
        custom_paths: dict[str, str] | None = None,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Refresh imported contact avatar metadata without reimporting messages."""
        preferred_paths = custom_paths or self._get_wechat_custom_paths(account_wxid)
        # Windows 只读扫描账号：头像回读同样需要每库 raw key 映射
        raw_keys = None
        account = self._resolve_wechat_account(account_wxid) or {}
        if str(account.get("key_type") or "passphrase") == "raw":
            raw_keys = account.get("raw_keys") or {}
        result = self.wechat_service.refresh_contact_avatars(
            db_key, preferred_paths, raw_keys=raw_keys
        )
        if result.get("ok") and preferred_paths:
            resolved_wxid = str(preferred_paths.get("account_wxid") or preferred_paths.get("current_user") or self._resolve_account_wxid(account_wxid))
            if resolved_wxid:
                with self._settings_lock:
                    update_wechat_account_import_state(
                        self.settings,
                        resolved_wxid,
                        db_key=db_key,
                        wechat_dir=str(preferred_paths.get("wechat_dir") or "") or None,
                    )
                    self._save_settings()
        return result

    def detect_wechat_import_increment(self, account_wxid: str = "") -> dict[str, Any]:
        """Compare current WeChat DB file sizes with the last successful import baseline."""
        account = self._resolve_wechat_account(account_wxid)
        baseline_files = (account or {}).get("last_import_files") or []
        if not baseline_files:
            return {"ok": True, "has_increment": False}

        custom_paths = self._get_wechat_custom_paths(account_wxid)
        try:
            snapshot = self.wechat_service.build_file_size_snapshot(custom_paths)
        except Exception as e:
            logger.error(f"[Bridge] 增量检测失败: {e}")
            return {"ok": False, "error": str(e)}

        baseline_map = {
            os.path.normpath(item.get("path", "")): int(item.get("size", 0))
            for item in baseline_files
            if item.get("path")
        }
        current_map = {
            os.path.normpath(item.get("path", "")): int(item.get("size", 0))
            for item in snapshot.get("files", [])
            if item.get("path")
        }

        changed_files = []
        increment_size = 0
        for path, current_size in current_map.items():
            baseline_size = baseline_map.get(path, 0)
            if current_size > baseline_size:
                delta = current_size - baseline_size
                increment_size += delta
                changed_files.append({
                    "path": path,
                    "previous_size": baseline_size,
                    "current_size": current_size,
                    "delta": delta,
                })

        return {
            "ok": True,
            "has_increment": increment_size > 0,
            "increment_size": increment_size,
            "changed_files": changed_files,
            "last_import_at": (account or {}).get("last_import_at"),
            "snapshot": snapshot,
        }

    # ==================== 原有接口（保留） ====================

    def ingest_data(self, file_path: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": True, "file_path": file_path, "options": options or {}}

    # ==================== 历史数据分析相关 ====================
    
    def get_conversation_list(self, account_wxid: str = "") -> dict[str, Any]:
        """
        获取联系人列表（用于前端下拉选择）
        
        Returns:
            {
                "ok": True,
                "conversations": [
                    {"id": 1, "name": "张三", "message_count": 1234, ...},
                    ...
                ]
            }
        """
        from ..services.analysis.analysis_service import AnalysisService
        
        service = AnalysisService()
        return service.get_conversation_list(self._resolve_account_wxid(account_wxid))
    
    def export_chat_records(
        self,
        conversation_id: int,
        format: str = "txt",
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, Any]:
        """导出聊天记录为 TXT/CSV/HTML 文件。

        Args:
            conversation_id: 会话 ID
            format: "txt" | "csv" | "html"
            start_date/end_date: "YYYY-MM-DD" 可选日期范围

        Returns:
            {"ok": True, "file_path": "...", "file_name": "...", "record_count": N}
        """
        try:
            import time as _time

            from ..db.connection import get_db
            from ..services.analysis.chat_export import (
                format_csv, format_html, format_txt,
            )

            conn = get_db()
            conv_row = conn.execute(
                "SELECT display_name, username FROM conversations WHERE id = ?",
                (int(conversation_id),),
            ).fetchone()
            if not conv_row:
                return {"ok": False, "error": f"会话不存在: {conversation_id}"}
            conv_name = conv_row["display_name"] or conv_row["username"] or "聊天记录"

            conditions = ["conversation_id = ?"]
            params: list[Any] = [int(conversation_id)]
            if start_date:
                conditions.append("timestamp >= ?")
                params.append(int(_time.mktime(_time.strptime(start_date, "%Y-%m-%d"))))
            if end_date:
                # end_date 当天 23:59:59
                conditions.append("timestamp < ?")
                import datetime as _dt
                end_dt = _dt.datetime.strptime(end_date, "%Y-%m-%d") + _dt.timedelta(days=1)
                params.append(int(end_dt.timestamp()))
            sql = f"""
                SELECT id, talker, sender, is_sender, message_type, content, timestamp
                FROM messages WHERE {" AND ".join(conditions)}
                ORDER BY timestamp ASC
            """
            messages = [dict(row) for row in conn.execute(sql, params).fetchall()]
            if not messages:
                return {"ok": False, "error": "所选范围内没有消息"}

            fmt = str(format or "txt").lower()
            if fmt == "csv":
                text = format_csv(messages)
                ext = "csv"
            elif fmt == "html":
                text = format_html(messages, conv_name)
                ext = "html"
            else:
                text = format_txt(messages, conv_name)
                ext = "txt"

            # 写入临时目录，前端拿到后用 save_file 对话框让用户选保存位置
            import tempfile
            from pathlib import Path as _Path
            safe_name = "".join(c for c in conv_name if c.isalnum() or c in "（）()-_ ").strip() or "chat"
            file_name = f"{safe_name}_{_time.strftime('%Y%m%d')}.{ext}"
            tmp_dir = _Path(tempfile.gettempdir()) / "chrono_trace_export"
            tmp_dir.mkdir(exist_ok=True)
            file_path = tmp_dir / file_name
            file_path.write_text(text, encoding="utf-8")

            return {
                "ok": True,
                "file_path": str(file_path),
                "file_name": file_name,
                "record_count": len(messages),
                "format": ext,
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 导出聊天记录失败: {e}")
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def get_analysis(self, date_range: dict[str, str]) -> dict[str, Any]:
        """
        获取历史数据分析（词云 + 统计）
        
        Args:
            date_range: {
                "conversation_id": 15,        # 必填：会话ID
                "from": "2025-01-01",         # 必填：开始日期
                "to": "2025-01-07"            # 必填：结束日期
            }
        
        Returns:
            {
                "subject": {...},
                "timeseries": [],
                "wordcloud": [...]
            }
        """
        from ..services.analysis.analysis_service import AnalysisService
        
        conversation_id = date_range.get("conversation_id")
        from_date = date_range.get("from")
        to_date = date_range.get("to")
        
        # 参数校验
        if not conversation_id:
            return {
                "error": "缺少参数: conversation_id",
                "subject": None,
                "timeseries": [],
                "wordcloud": []
            }
        
        if not from_date or not to_date:
            return {
                "error": "缺少日期参数",
                "subject": None,
                "timeseries": [],
                "wordcloud": []
            }
        
        service = AnalysisService()
        return service.get_analysis(
            conversation_id=int(conversation_id),
            from_date=from_date,
            to_date=to_date
        )

    def _ensure_suggestion_stream_state(self) -> None:
        if not hasattr(self, "_suggestion_streams"):
            self._suggestion_streams = {}
        if not hasattr(self, "_suggestion_stream_lock"):
            self._suggestion_stream_lock = threading.Lock()

    def _append_suggestion_stream_event(self, stream_id: str, event: dict[str, Any]) -> None:
        self._ensure_suggestion_stream_state()
        with self._suggestion_stream_lock:
            state = self._suggestion_streams.get(stream_id)
            if not state:
                return
            events = state.setdefault("events", [])
            seq = int(state.get("next_seq") or 0)
            item = {
                "seq": seq,
                "ts": int(time.time() * 1000),
                **dict(event or {}),
            }
            events.append(item)
            state["next_seq"] = seq + 1
            # 事件持续到达视为活跃，刷新 TTL 基准
            state["updated_at"] = int(time.time() * 1000)
            # Keep the bridge memory bounded; frontend polls frequently.
            if len(events) > 400:
                del events[:-400]

    def start_suggestion_stream(self, intent: str, context: dict[str, Any]) -> dict[str, Any]:
        """Start manual suggestion generation in a background thread and expose stream events."""
        self._ensure_suggestion_stream_state()
        stream_id = uuid.uuid4().hex
        now_ms = int(time.time() * 1000)
        with self._suggestion_stream_lock:
            self._suggestion_streams[stream_id] = {
                "stream_id": stream_id,
                "status": "running",
                "events": [],
                "next_seq": 0,
                "result": None,
                "error": None,
                "created_at": now_ms,
                "updated_at": now_ms,
            }
        # 新增条目时顺带清理过期流（锁外调用，避免锁内嵌套死锁）
        self._prune_task_dicts()

        def _run() -> None:
            try:
                self._append_suggestion_stream_event(
                    stream_id,
                    {"type": "stage", "stage": "start", "message": "开始生成"},
                )
                result = self.generate_suggestion(
                    intent,
                    dict(context or {}),
                    _stream_callback=lambda event: self._append_suggestion_stream_event(stream_id, event),
                )
                with self._suggestion_stream_lock:
                    state = self._suggestion_streams.get(stream_id)
                    if state is not None:
                        state["status"] = "done" if result.get("ok") else "error"
                        state["result"] = result
                        state["error"] = None if result.get("ok") else result.get("error")
                        state["updated_at"] = int(time.time() * 1000)
                self._append_suggestion_stream_event(
                    stream_id,
                    {"type": "done" if result.get("ok") else "error", "message": "生成完成" if result.get("ok") else result.get("error")},
                )
            except Exception as exc:
                logger.exception("[Bridge] suggestion stream failed")
                with self._suggestion_stream_lock:
                    state = self._suggestion_streams.get(stream_id)
                    if state is not None:
                        state["status"] = "error"
                        state["error"] = str(exc)
                        state["updated_at"] = int(time.time() * 1000)
                self._append_suggestion_stream_event(
                    stream_id,
                    {"type": "error", "message": str(exc)},
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {"ok": True, "stream_id": stream_id}

    def get_suggestion_stream(self, stream_id: str, cursor: int = 0) -> dict[str, Any]:
        """Poll stream events for a running suggestion job."""
        self._ensure_suggestion_stream_state()
        normalized_id = str(stream_id or "").strip()
        if not normalized_id:
            return {"ok": False, "error": "missing_stream_id"}
        with self._suggestion_stream_lock:
            state = self._suggestion_streams.get(normalized_id)
            if not state:
                return {"ok": False, "error": "stream_not_found"}
            start = max(0, int(cursor or 0))
            events = [
                dict(event)
                for event in state.get("events", [])
                if int(event.get("seq") or 0) >= start
            ]
            next_cursor = int(state.get("next_seq") or 0)
            return {
                "ok": True,
                "stream_id": normalized_id,
                "status": state.get("status"),
                "events": events,
                "next_cursor": next_cursor,
                "done": state.get("status") in {"done", "error"},
                "result": state.get("result"),
                "error": state.get("error"),
            }

    def generate_suggestion(
        self,
        intent: str,
        context: dict[str, Any],
        _stream_callback=None,
    ) -> dict[str, Any]:
        """
        手动生成 AI 建议（Manual 模式或用户主动请求）

        Args:
            intent: 发展走向 (intimate/maintain/distance)
            context: 附加上下文 {"trigger_type": "...", ...}

        Returns:
            {"ok": True, "suggestion": {...}} 或 {"ok": False, "error": "..."}
        """
        try:
            from ..services.realtime.suggestion_engine import SuggestionEngineFactory
            from ..services.realtime.monitor_service import RealtimeMonitorService

            monitor = RealtimeMonitorService()

            # 从 MonitorService 的配置中读取引擎类型（而非 settings.json）
            engine_type = monitor._suggestion_config.get('engine_type', 'llm')
            engine = SuggestionEngineFactory.create(engine_type)
            account_wxid = str(getattr(monitor, "current_account_wxid", "") or self._get_active_wechat_account_wxid() or "")
            if account_wxid and not context.get("account_wxid"):
                context["account_wxid"] = account_wxid

            logger.debug(f"[Bridge] generate_suggestion: engine_type={engine_type}, intent={intent}")
            logger.debug(
                "[Bridge] generate_suggestion scope: account_wxid_present=%s, display_name_present=%s, batch_id=%s",
                bool(account_wxid),
                bool(getattr(monitor, "current_display_name", None)),
                monitor.current_batch_id or "manual",
            )

            # G1:手动入口统一走 assemble_generation_context——绑定稳定
            # account_wxid + conversation_id,范围缺失时安全降级为通用帮助。
            try:
                from ..services.realtime.generation_context import assemble_generation_context

                assemble_generation_context(
                    context,
                    entrypoint="manual",
                    account_wxid=account_wxid,
                    conversation_id=context.get("conversation_id") or context.get("_rag_conversation_id"),
                    display_name=str(
                        getattr(monitor, "current_display_name", "") or context.get("display_name") or ""
                    ),
                    username=str(getattr(monitor, "current_talker", "") or ""),
                    batch_id=str(monitor.current_batch_id or ""),
                    emotion_summary=(
                        monitor.emotion_tracker.get_emotion_summary() if monitor.emotion_tracker else None
                    ),
                    recent_limit=50,
                    prewarm_rag_index=True,
                )
            except Exception as assemble_e:
                logger.error(f"[Bridge] 统一上下文装配失败: {assemble_e}")
                if getattr(monitor, "current_display_name", ""):
                    context['display_name'] = monitor.current_display_name

            from ..services.realtime.trigger_resolver import resolve_suggestion_trigger

            resolved_trigger = resolve_suggestion_trigger(
                mode="manual",
                explicit_trigger_type=context.get("trigger_type"),
                explicit_trigger_context=context.get("trigger_context"),
                emotion_tracker=getattr(monitor, "emotion_tracker", None),
                recent_messages=context.get("recent_messages"),
            )
            trigger_type = resolved_trigger.trigger_type
            if resolved_trigger.trigger_context:
                merged_trigger_context = dict(context.get("trigger_context") or {})
                merged_trigger_context.update(resolved_trigger.trigger_context)
                context["trigger_context"] = merged_trigger_context

            import inspect

            if "stream_callback" in inspect.signature(engine.generate).parameters:
                result = engine.generate(
                    trigger_type,
                    intent,
                    context,
                    stream_callback=_stream_callback,
                )
            else:
                result = engine.generate(trigger_type, intent, context)

            # 将手动生成的建议也写入 DB（供隐式反馈对比使用）
            try:
                import time as _time
                from ..db.connection import get_db
                conn = get_db()
                now_time = int(_time.time())
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO realtime_suggestions
                    (account_wxid, batch_id, trigger_type, intent, severity, summary, speeches,
                     confidence, status, engine_type, trigger_context, created_at, reply, thought_process)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'displayed', ?, ?, ?, ?, ?)
                ''', (
                    account_wxid,
                    monitor.current_batch_id or 'manual',
                    result.trigger_type,
                    result.intent,
                    result.severity,
                    result.summary,
                    json.dumps(result.speeches, ensure_ascii=False),
                    result.confidence,
                    engine_type,
                    json.dumps({
                        'source': 'manual_generate',
                        'user_context': context.get('user_context'),
                        'resolved_trigger_source': resolved_trigger.source,
                        **(context.get('trigger_context') or {}),
                    }, ensure_ascii=False),
                    now_time,
                    getattr(result, 'reply', None),
                    getattr(result, 'thought_process', None),
                ))
                inserted_id = cursor.lastrowid
                try:
                    rag_log_id = getattr(result, 'rag_log_id', None)
                    if rag_log_id:
                        from ..services.realtime.rag.context_builder import RagContextBuilder

                        RagContextBuilder().attach_log_to_suggestion(rag_log_id, inserted_id)
                except Exception as rag_log_e:
                    logger.warning(f"[Bridge] RAG 检索日志关联建议失败: {rag_log_e}")
                try:
                    from ..services.realtime.suggestion_observer import (
                        EVENT_SHOWN,
                        EVENT_VIEWED,
                        record_observation,
                    )

                    rag_summary = getattr(result, 'rag_context', None) or {}
                    obs_metadata = {
                        'source': 'manual_generate',
                        'rag_state': rag_summary.get('state'),
                        'rag_referenced_count': rag_summary.get('referenced_count', 0),
                        'rag_log_id': getattr(result, 'rag_log_id', None),
                    }
                    record_observation(
                        conn,
                        suggestion_id=inserted_id,
                        account_wxid=account_wxid,
                        event_type=EVENT_SHOWN,
                        batch_id=monitor.current_batch_id or 'manual',
                        display_name=monitor.current_display_name,
                        trigger_type=result.trigger_type,
                        metadata=obs_metadata,
                        created_at=now_time,
                    )
                    record_observation(
                        conn,
                        suggestion_id=inserted_id,
                        account_wxid=account_wxid,
                        event_type=EVENT_VIEWED,
                        batch_id=monitor.current_batch_id or 'manual',
                        display_name=monitor.current_display_name,
                        trigger_type=result.trigger_type,
                        metadata=obs_metadata,
                        created_at=now_time,
                    )
                    conn.execute(
                        "UPDATE realtime_suggestions SET read_at = COALESCE(read_at, ?) WHERE id = ?",
                        (now_time, inserted_id),
                    )
                except Exception as obs_e:
                    logger.error(f"[Bridge] 记录手动建议观察事件失败: {obs_e}")
                conn.commit()
                logger.debug(f"[Bridge] 手动建议已写入 realtime_suggestions 表, id={inserted_id}")
            except Exception as db_e:
                inserted_id = None
                now_time = int(_time.time())
                logger.error(f"[Bridge] 写入建议到DB失败: {db_e}")

            # 提取 AI 实际参考的聊天记录（最多 20 条）
            recent_used = context.get('recent_messages', [])
            recent_for_display = []
            for msg in recent_used[-20:]:
                recent_for_display.append({
                    'sender': '我' if msg.get('sender_attr') == 'self' else '对方',
                    'content': (msg.get('content') or '')[:120],
                    'timestamp': msg.get('timestamp', 0),
                })

            return {
                "ok": True,
                "suggestion": {
                    "id": inserted_id,
                    "trigger_type": result.trigger_type,
                    "intent": result.intent,
                    "summary": result.summary,
                    "speeches": result.speeches,
                    "severity": result.severity,
                    "confidence": result.confidence,
                    "thought_process": getattr(result, "thought_process", None),
                    "reply": getattr(result, "reply", None),
                    "rag_context": getattr(result, "rag_context", None),
                    "created_at": now_time,
                },
                "context_used": {
                    "recent_messages": recent_for_display,
                    "message_count": len(recent_used),
                }
            }
        except TimeoutError as e:
            # 超时是正常情况，不需要打印完整堆栈
            logger.warning(f"[Bridge] 生成建议超时: {e}")
            return {"ok": False, "error": str(e)}
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 生成建议失败: {e}")
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def get_settings(self) -> dict[str, Any]:
        """获取设置"""
        with self._settings_lock:
            try:
                from ..services.realtime.rag.config import apply_rag_defaults

                apply_rag_defaults(self.settings)
            except Exception:
                pass
            self.settings["analysis_device_mode"] = normalize_analysis_device_mode(
                self.settings.get("analysis_device_mode", ANALYSIS_DEVICE_MODE_AUTO)
            )
            self.settings[MODEL_ROOT_DIR_KEY] = normalize_model_root_dir(self.settings.get(MODEL_ROOT_DIR_KEY))
            payload = dict(self.settings)
            active_account = self._get_active_wechat_account() or {}
            payload[WECHAT_ACCOUNTS_KEY] = self._get_wechat_accounts()
            payload[WECHAT_ACTIVE_ACCOUNT_KEY] = self._get_active_wechat_account_wxid()
            payload[MODEL_ROOT_DIR_KEY] = self.settings[MODEL_ROOT_DIR_KEY]
            payload["default_model_root_dir"] = str(get_default_model_root_dir())
            payload["sentiment_model_dir"] = str(get_sentiment_model_dir(self.settings))
            payload["embedding_model_dir"] = str(get_embedding_model_dir(self.settings))
            payload["wechat_use_custom_path"] = str(active_account.get("source") or "") == "custom"
            payload["wechat_data_dir"] = active_account.get("wechat_dir") or ""
            payload["wechat_user_wxid"] = active_account.get("wxid") or ""
            payload["wechat_db_key"] = active_account.get("db_key") or ""
            payload["wechat_import_completed"] = bool(active_account.get("import_completed"))
            payload["wechat_last_import_at"] = active_account.get("last_import_at")
            payload["wechat_last_import_total_size"] = int(active_account.get("last_import_total_size") or 0)
            payload["wechat_last_import_files"] = active_account.get("last_import_files") or []
        return payload

    def get_current_user_profile(self, account_wxid: str = "") -> dict[str, Any]:
        """Resolve the current WeChat account profile for the top-right header avatar."""
        account = self._resolve_wechat_account(account_wxid)
        wxid = str((account or {}).get("wxid") or self._resolve_account_wxid(account_wxid) or "").strip()
        if not wxid:
            return {"ok": False, "error": "未配置微信用户ID", "profile": None}
        wxid_candidates = self._build_wechat_user_candidates(wxid)

        profile = {
            "wxid": wxid,
            "name": "我",
            "avatar": "",
        }

        try:
            from ..db.connection import get_db

            db = get_db()
            for candidate in wxid_candidates:
                row = db.execute(
                    """
                    SELECT
                        username,
                        COALESCE(
                            NULLIF(TRIM(remark), ''),
                            NULLIF(TRIM(nickname), ''),
                            NULLIF(TRIM(alias), ''),
                            NULLIF(TRIM(username), ''),
                            '我'
                        ) AS name,
                        COALESCE(NULLIF(TRIM(avatar_path), ''), '') AS avatar
                    FROM contacts
                    WHERE account_wxid = ? AND username = ?
                    LIMIT 1
                    """,
                    (wxid, candidate),
                ).fetchone()
                if not row:
                    continue
                profile["wxid"] = row["username"] or profile["wxid"]
                profile["name"] = row["name"] or profile["name"]
                profile["avatar"] = row["avatar"] or ""
                if profile["avatar"]:
                    return {"ok": True, "profile": profile}
        except Exception as e:
            logger.warning(f"[Bridge] 从本地数据库读取当前用户头像失败: {e}")

        db_key = str((account or {}).get("db_key") or "").strip()
        custom_paths = self._get_wechat_custom_paths(account_wxid)
        if not db_key or not custom_paths:
            return {"ok": True, "profile": profile}

        try:
            paths = self.wechat_service.resolve_wechat_paths(custom_paths)
            contact_db_path = (paths.get("databases") or {}).get("contact")
            if not contact_db_path:
                return {"ok": True, "profile": profile}

            contact_db = ContactDBV4(contact_db_path, db_key)
            try:
                contact = None
                for candidate in wxid_candidates:
                    contact = contact_db.get_contact_by_username(candidate)
                    if contact:
                        break
            finally:
                contact_db.close()

            if not contact:
                return {"ok": True, "profile": profile}

            profile["wxid"] = contact.get("username") or profile["wxid"]
            profile["name"] = (
                contact.get("remark")
                or contact.get("nickname")
                or contact.get("alias")
                or profile["name"]
            )
            profile["avatar"] = (contact.get("avatar_url") or "").strip()
            return {"ok": True, "profile": profile}
        except Exception as e:
            logger.warning(f"[Bridge] 从微信联系人库读取当前用户头像失败: {e}")
            return {"ok": True, "profile": profile}

    def set_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存设置"""
        payload = dict(payload)
        for bool_key in (
            "rag_enabled",
            "rag_remote_context_redaction",
            "rag_allow_remote_embedding",
            "rag_cross_contact_style_enabled",
            "rag_remote_embedding_redaction_risk_confirmed",
        ):
            if bool_key in payload:
                payload[bool_key] = bool(payload[bool_key])
        if "rag_embedding_dim" in payload:
            try:
                payload["rag_embedding_dim"] = int(payload["rag_embedding_dim"] or EMBEDDING_MODEL_DIM)
            except (TypeError, ValueError):
                payload["rag_embedding_dim"] = EMBEDDING_MODEL_DIM
            if (
                payload.get("rag_embedding_model") == EMBEDDING_MODEL_REPO_ID
                and payload["rag_embedding_dim"] == 384
            ):
                payload["rag_embedding_dim"] = EMBEDDING_MODEL_DIM
        if (
            payload.get("rag_allow_remote_embedding")
            and payload.get("rag_remote_context_redaction") is False
            and not payload.get("rag_remote_embedding_redaction_risk_confirmed")
        ):
            return {
                "saved": False,
                "ok": False,
                "error": "同时开启远程 embedding 并关闭远程 RAG 脱敏前必须再次确认风险",
            }
        if "analysis_device_mode" in payload:
            payload["analysis_device_mode"] = normalize_analysis_device_mode(payload["analysis_device_mode"])
        if MODEL_ROOT_DIR_KEY in payload:
            payload[MODEL_ROOT_DIR_KEY] = normalize_model_root_dir(payload[MODEL_ROOT_DIR_KEY])

        with self._settings_lock:
            # 微信账号相关键先从 payload 摘出并合并进当前设置，避免与 self.settings.update 相互覆盖
            if WECHAT_ACCOUNTS_KEY in payload:
                self.settings[WECHAT_ACCOUNTS_KEY] = normalize_wechat_accounts(payload.pop(WECHAT_ACCOUNTS_KEY))
            if WECHAT_ACTIVE_ACCOUNT_KEY in payload:
                set_active_wechat_account(self.settings, str(payload.pop(WECHAT_ACTIVE_ACCOUNT_KEY) or ""))

            legacy_keys = {key: payload.pop(key) for key in list(payload.keys()) if key in LEGACY_WECHAT_KEYS}
            if legacy_keys:
                target_wxid = str(
                    legacy_keys.get("wechat_user_wxid")
                    or self._get_active_wechat_account_wxid()
                    or ""
                ).strip()
                if target_wxid:
                    update_wechat_account_import_state(
                        self.settings,
                        target_wxid,
                        db_key=str(legacy_keys.get("wechat_db_key") or "") if "wechat_db_key" in legacy_keys else None,
                        wechat_dir=str(legacy_keys.get("wechat_data_dir") or "") if "wechat_data_dir" in legacy_keys else None,
                        source="custom" if legacy_keys.get("wechat_use_custom_path") else "auto",
                        import_completed=legacy_keys.get("wechat_import_completed") if "wechat_import_completed" in legacy_keys else None,
                    )
                    merged_account = dict(self._get_wechat_account(target_wxid) or {"wxid": target_wxid})
                    if "wechat_last_import_at" in legacy_keys:
                        merged_account["last_import_at"] = legacy_keys.get("wechat_last_import_at")
                    if "wechat_last_import_total_size" in legacy_keys:
                        merged_account["last_import_total_size"] = legacy_keys.get("wechat_last_import_total_size")
                    if "wechat_last_import_files" in legacy_keys:
                        merged_account["last_import_files"] = legacy_keys.get("wechat_last_import_files") or []
                    upsert_wechat_account(self.settings, merged_account)
                    if legacy_keys.get("wechat_user_wxid"):
                        set_active_wechat_account(self.settings, target_wxid)

            self.settings.update(payload)
            self._save_settings()
            response = {
                "saved": True,
                "payload": payload,
                "model_root_dir": self.settings.get(MODEL_ROOT_DIR_KEY),
                **self._serialize_wechat_accounts(),
            }
        return response


    def select_file(self, title: str = "选择文件", file_types: str = "*.*") -> dict[str, Any]:
        """
        打开文件选择对话框
        
        Args:
            title: 对话框标题
            file_types: 文件类型过滤（如 "*.db"）
            
        Returns:
            {"path": "选择的文件路径"} 或 {"path": None}
        """
        try:
            import webview
            
            logger.debug(f"[DEBUG] 打开文件选择对话框: title={title}, file_types={file_types}")
            
            # 获取当前窗口
            if not webview.windows or len(webview.windows) == 0:
                logger.error("[ERROR] 没有可用的 webview 窗口")
                return {"path": None, "error": "No webview window available"}
            
            window = webview.windows[0]
            
            # 解析文件类型
            if file_types and file_types != "*.*":
                filter_name = f"数据库文件 ({file_types})"
                file_filter = (filter_name, file_types)
            else:
                file_filter = ("所有文件 (*.*)", "*.*")
            
            logger.debug(f"[DEBUG] 调用 create_file_dialog, filter={file_filter}")
            
            # 调用文件选择对话框
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory="",
                file_types=(file_filter,)
            )
            
            logger.debug(f"[DEBUG] 文件选择结果: {result}")
            
            if result and len(result) > 0:
                selected_path = result[0]
                logger.debug(f"[DEBUG] 已选择文件: {selected_path}")
                return {"path": selected_path}
            
            logger.debug("[DEBUG] 用户取消选择")
            return {"path": None}
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"[ERROR] 文件选择失败: {e}")
            logger.error("[ERROR] 详细错误:")
            logger.error(error_detail)
            return {"path": None, "error": str(e)}
    
    def select_directory(self, title: str = "选择目录") -> dict[str, Any]:
        """
        打开目录选择对话框
        
        Args:
            title: 对话框标题
            
        Returns:
            {"path": "选择的目录路径"} 或 {"path": None}
        """
        try:
            editable_result = self._select_directory_with_edit_box(title)
            if editable_result is not None:
                return editable_result

            import webview
            
            logger.debug(f"[DEBUG] 打开目录选择对话框: title={title}")
            
            # 获取当前窗口
            if not webview.windows or len(webview.windows) == 0:
                logger.error("[ERROR] 没有可用的 webview 窗口")
                return {"path": None, "error": "No webview window available"}
            
            window = webview.windows[0]
            
            logger.debug("[DEBUG] 调用 create_file_dialog (FOLDER_DIALOG)")
            
            # 调用目录选择对话框
            result = window.create_file_dialog(
                webview.FOLDER_DIALOG
            )
            
            logger.debug(f"[DEBUG] 目录选择结果: {result}")
            
            if result and len(result) > 0:
                selected_path = result[0]
                logger.debug(f"[DEBUG] 已选择目录: {selected_path}")
                return {"path": selected_path}
            
            logger.debug("[DEBUG] 用户取消选择")
            return {"path": None}
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"[ERROR] 目录选择失败: {e}")
            logger.error("[ERROR] 详细错误:")
            logger.error(error_detail)
            return {"path": None, "error": str(e)}

    def _select_directory_with_edit_box(self, title: str) -> Optional[dict[str, Any]]:
        """Use a Windows folder picker with an editable path box when available."""
        if os.name != "nt":
            return None

        co_initialized = False
        try:
            import pythoncom
            from win32com.shell import shell, shellcon

            pythoncom.CoInitialize()
            co_initialized = True

            # pywebview's FOLDER_DIALOG uses an old tree-only picker on Windows.
            # BIF_EDITBOX adds a text field so users can paste a full folder path.
            bif_newdialogstyle = getattr(shellcon, "BIF_NEWDIALOGSTYLE", 0x0040)
            flags = (
                shellcon.BIF_RETURNONLYFSDIRS
                | shellcon.BIF_EDITBOX
                | shellcon.BIF_VALIDATE
                | bif_newdialogstyle
            )
            logger.debug("[DEBUG] 调用 Windows 可输入路径目录选择框")
            result = shell.SHBrowseForFolder(0, None, title, flags)

            if not result:
                logger.debug("[DEBUG] 用户取消 Windows 目录选择")
                return {"path": None}

            pidl = result[0]
            selected_path = shell.SHGetPathFromIDList(pidl)
            if isinstance(selected_path, bytes):
                selected_path = selected_path.decode("mbcs", errors="replace")
            if selected_path:
                logger.debug(f"[DEBUG] 已选择目录: {selected_path}")
                return {"path": str(selected_path)}
            return {"path": None}
        except Exception as e:
            logger.warning(f"[DEBUG] Windows 可输入路径目录选择框失败，回退 pywebview: {e}")
            return None
        finally:
            if co_initialized:
                pythoncom.CoUninitialize()
    
    def scan_wechat_directory(self, wechat_dir: str) -> dict[str, Any]:
        """
        扫描微信数据目录，自动查找wxid和数据库文件
        
        Args:
            wechat_dir: 微信数据目录路径 (如: C:\\Users\\xxx\\Documents\\WeChat Files)
            
        Returns:
            {
                "ok": True,
                "wxids": ["wxid_xxx", "wxid_yyy"],
                "databases": {
                    "wxid_xxx": {
                        "msg_dbs": ["path1", "path2"],
                        "contact_db": "path"
                    }
                }
            }
        """
        try:
            logger.info(f"[DEBUG] 开始扫描目录: {wechat_dir}")

            target_dir = Path(wechat_dir)
            if not target_dir.exists():
                return {
                    "ok": False,
                    "error": f"目录不存在: {wechat_dir}",
                    "wxids": [],
                    "databases": {}
                }
            
            result = {
                "ok": True,
                "wxids": [],
                "databases": {},
                "accounts": [],
            }

            # 兼容直接选中了某个账号目录的情况（账号目录名不一定是 wxid_ 前缀，按结构特征识别）
            if WeChatPathFinder._looks_like_wechat_user_dir(target_dir):
                root_dir = target_dir.parent
                wxid_dirs = [target_dir.name]
            else:
                root_dir = WeChatPathFinder._resolve_wechat_data_dir(target_dir, aggressive_depth=2) or target_dir
                wxid_dirs = WeChatPathFinder.find_all_user_wxids(str(root_dir))

            if not wxid_dirs:
                # V4 未命中：探测 3.9 旧版结构，命中则引导用户升级微信
                legacy_v3 = WeChatPathFinder._inspect_legacy_v3_root(target_dir)
                if legacy_v3:
                    return {
                        "ok": False,
                        "code": "legacy_wechat_v3",
                        "error": "该目录为旧版微信 3.9 数据目录，请将微信升级到 4.0 及以上版本后重试",
                        "v3": legacy_v3,
                        "wxids": [],
                        "databases": {},
                        "accounts": [],
                    }
                return {
                    "ok": False,
                    "error": f"未在目录中找到微信 V4 数据目录: {wechat_dir}",
                    "wxids": [],
                    "databases": {},
                    "accounts": [],
                }

            logger.debug(f"[DEBUG] 找到 {len(wxid_dirs)} 个 wxid 目录")

            for wxid in wxid_dirs:
                databases = WeChatPathFinder.find_databases(wxid, str(root_dir))
                result["wxids"].append(wxid)
                result["databases"][wxid] = {
                    "msg_dbs": databases.get("message") or [],
                    "contact_db": databases.get("contact"),
                    "session_db": databases.get("session"),
                }
                result["accounts"].append(
                    self._build_wechat_account_candidate(
                        wxid,
                        wechat_dir=str(root_dir),
                        source="custom",
                    )
                )
            
            logger.info(f"[DEBUG] 扫描完成，找到 {len(result['wxids'])} 个wxid")
            return result
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"[ERROR] 扫描微信目录失败: {e}")
            logger.error(error_detail)
            return {
                "ok": False,
                "error": str(e),
                "wxids": [],
                "databases": {},
                "accounts": [],
            }

    # ==================== 实时监听相关 ====================
    
    def start_realtime_monitor(
        self,
        talker_display_name: str,
        resume_mode: str = "skip",
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        启动实时消息监听
        
        Args:
            talker_display_name: 监听对象的昵称/备注名
            
        Returns:
            {
                "ok": True/False,
                "success": True/False,
                "batch_id": "uuid",
                "message": "提示信息",
                "error": "错误信息"
            }
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService

            logger.debug(f"[Bridge] 启动实时监听: {talker_display_name}")
            # 监听启动即后台预热 embedding:用户第一次提问前模型就绪,
            # 避免首查落在懒加载窗口内导致事实被门禁丢弃。
            try:
                from ..services.realtime.rag.embedding import kick_background_prewarm

                kick_background_prewarm()
            except Exception:
                pass
            monitor_service = RealtimeMonitorService()
            result = monitor_service.start_monitoring(
                talker_username="",  # 由监听后端自行解析
                talker_display_name=talker_display_name,
                resume_mode=resume_mode,
                account_wxid=self._resolve_account_wxid(account_wxid),
            )
            
            return {
                "ok": result['success'],
                "success": result['success'],
                "batch_id": result.get('batch_id'),
                "message": result.get('message'),
                "error": result.get('error'),
                "uia_recovery_required": result.get('uia_recovery_required', False),
                "uia_recovery_phase": result.get('uia_recovery_phase', ''),
                "uia_recovery_prompt": result.get('uia_recovery_prompt', ''),
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 启动实时监听异常: {e}")
            traceback.print_exc()
            return {
                "ok": False,
                "success": False,
                "error": str(e)
            }

    def run_realtime_uia_recovery(self) -> dict[str, Any]:
        """Run the pending WeChat UIA recovery flow after the user confirms it in the frontend."""
        if sys.platform != "win32":
            return {"ok": False, "code": "unsupported_on_platform", "error": "UIA 界面修复为 Windows 专属能力；Linux 使用 db_watch 数据库监听，无需修复界面。"}
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService

            logger.debug("[Bridge] 执行实时监听 UIA 自动修复")
            monitor_service = RealtimeMonitorService()
            result = monitor_service.run_confirmed_uia_recovery()
            return {
                "ok": result.get("success", False),
                "success": result.get("success", False),
                "message": result.get("message", ""),
                "error": result.get("error", ""),
                "final_status": result.get("final_status", ""),
                "uia_recovery_summary": result.get("uia_recovery_summary", ""),
                "uia_recovery_actions": result.get("uia_recovery_actions", []),
                "uia_recovery_aborted": result.get("uia_recovery_aborted", False),
                "narrator_verification": result.get("narrator_verification", {}),
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 执行 UIA 自动修复异常: {e}")
            traceback.print_exc()
            return {
                "ok": False,
                "success": False,
                "error": str(e),
            }
    
    def stop_realtime_monitor(self, user_chat_history: Optional[list[dict]] = None) -> dict[str, Any]:
        """
        停止实时消息监听
        
        Returns:
            {
                "ok": True/False,
                "success": True/False,
                "batch_id": "uuid",
                "message_count": 123,
                "message": "提示信息"
            }
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService
            
            logger.debug("[Bridge] 停止实时监听")
            monitor_service = RealtimeMonitorService()

            # 停止前自动归档会话线程
            try:
                self._archive_current_session(monitor_service, user_chat_history)
            except Exception as arch_e:
                logger.error(f"[Bridge] 会话归档失败: {arch_e}")

            result = monitor_service.stop_monitoring()
            
            return {
                "ok": result['success'],
                "success": result['success'],
                "batch_id": result.get('batch_id'),
                "message_count": result.get('message_count', 0),
                "message": result.get('message')
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 停止实时监听异常: {e}")
            traceback.print_exc()
            return {
                "ok": False,
                "success": False,
                "error": str(e)
            }
    
    def get_realtime_status(self) -> dict[str, Any]:
        """
        获取实时监听状态
        
        Returns:
            {
                "ok": True,
                "is_monitoring": True/False,
                "talker_display_name": "张三",
                "batch_id": "uuid",
                "message_count": 10
            }
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService
            
            monitor_service = RealtimeMonitorService()
            status = monitor_service.get_status()
            
            return {
                "ok": True,
                "is_monitoring": status['is_monitoring'],
                "talker_display_name": status.get('talker_display_name'),
                "account_wxid": status.get('account_wxid'),
                "batch_id": status.get('batch_id'),
                "message_count": status.get('message_count', 0),
                "model_ready": status.get('model_ready', False),
                "chat_ready": status.get('chat_ready', False),
                "chat_error": status.get('chat_error', ''),
                "uia_recovery_required": status.get('uia_recovery_required', False),
                "uia_recovery_in_progress": status.get('uia_recovery_in_progress', False),
                "uia_recovery_phase": status.get('uia_recovery_phase', ''),
                "polling_alive": status.get('polling_alive', True),
                "provider": status.get('provider', ''),
                "listener_profile": status.get('listener_profile', ''),
                "wechat_version": status.get('wechat_version', ''),
                "uia_recovery_summary": status.get('uia_recovery_summary', ''),
                "uia_recovery_final_status": status.get('uia_recovery_final_status', ''),
                "uia_recovery_actions": status.get('uia_recovery_actions', []),
                "uia_recovery_aborted": status.get('uia_recovery_aborted', False),
                "uia_recovery_abort_reason": status.get('uia_recovery_abort_reason', ''),
                "narrator_verification": status.get('narrator_verification', {}),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取实时监听状态异常: {e}")
            return {
                "ok": False,
                "error": str(e),
                "is_monitoring": False,
                "message_count": 0
            }

    def debug_dump_wechat_uia(
        self,
        talker_display_name: str = "",
        max_depth: int = 4,
        max_nodes: int = 300,
    ) -> dict[str, Any]:
        """
        导出当前微信窗口的 UIA 树和可见消息快照，用于校准监听器。
        """
        try:
            from ..services.realtime.providers.debug_tools import dump_wechat_uia_snapshot

            result = dump_wechat_uia_snapshot(
                talker_display_name=talker_display_name or "",
                max_depth=max(1, int(max_depth)),
                max_nodes=max(50, int(max_nodes)),
            )
            return {"ok": True, **result}
        except Exception as e:
            logger.error(f"[Bridge] 导出微信 UIA 快照失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "messages": [],
                "tree": {},
            }

    def get_realtime_messages(self, batch_id: str, limit: int = 50) -> dict[str, Any]:
        """
        获取批次消息列表(带情感分析结果)
        
        Args:
            batch_id: 批次ID
            limit: 返回消息数量限制
            
        Returns:
            {
                "ok": True,
                "messages": [...]
            }
        """
        try:
            from ..services.realtime.message_query import get_messages_with_sentiment

            messages = get_messages_with_sentiment(
                batch_id,
                limit,
                account_wxid=self._resolve_account_wxid(""),
            ) or []

            # 新消息不足时并入监听基线尾部（预热已带 sentiment）——
            # 前端统计（发言比例/回复率/正面率）与情绪图表全部读本端点，
            # 此前基线不落 buffer 导致开场恒显 N/A/「正在分析」
            if len(messages) < int(limit):
                try:
                    from ..services.realtime.monitor_service import RealtimeMonitorService
                    from ..services.realtime.providers.native_uia import TIME_LABEL_RE

                    baseline_tail = getattr(RealtimeMonitorService(), "_baseline_tail", None) or []
                    if baseline_tail:
                        # 基线来自 UIA 当前可见列表，其中包含微信的日期/时间分隔线。
                        # 这些行不是聊天消息，不能并入消息气泡，否则前端会按
                        # sender_attr != self 误显示为“对方”。
                        baseline_items = [
                            {
                                "id": -(idx + 1),  # 负数伪 id 避免与 buffer 冲突
                                "sender": msg.get("sender_attr"),
                                "sender_attr": msg.get("sender_attr"),
                                "content": msg.get("content"),
                                "message_type": msg.get("message_type"),
                                "timestamp": msg.get("timestamp"),
                                "sentiment": msg.get("sentiment"),
                            }
                            for idx, msg in enumerate(baseline_tail)
                            if str(msg.get("sender_attr") or "").strip().lower() in {"self", "friend"}
                            and str(msg.get("message_type") or "text").strip().lower() != "system"
                            and not TIME_LABEL_RE.match(str(msg.get("content") or "").strip())
                        ]
                        messages = [
                            m for m in (baseline_items + messages)
                            if not TIME_LABEL_RE.match(str(m.get("content") or "").strip())
                        ][-int(limit):]
                except Exception as exc:
                    logger.debug("[Bridge] 基线尾部并入消息列表跳过: %s", exc)

            # 只在消息数量变化时打印（避免每 3 秒重复刷屏）
            count = len(messages)
            cache_key = f"_last_msg_count_{batch_id[:8]}"
            last_count = getattr(self, cache_key, 0)
            if count != last_count:
                setattr(self, cache_key, count)
                print(f"[Bridge] 消息轮询: batch={batch_id[:8]}..., 当前共 {count} 条消息", flush=True)
            
            return {
                "ok": True,
                "messages": messages
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 获取批次消息异常: {e}")
            traceback.print_exc()
            return {
                "ok": False,
                "error": str(e),
                "messages": []
            }

    # ==================== AI 建议相关 ====================

    def get_realtime_recent_messages(self, batch_id: str, limit: int = 12,
                                      account_wxid: str = "") -> dict[str, Any]:
        """返回批次内最近收到的原始消息（悬浮面板即时回显，不等 LLM 建议）。"""
        try:
            from ..services.realtime.message_buffer import MessageBuffer
            from ..services.realtime.providers.native_uia import TIME_LABEL_RE

            if not str(batch_id or "").strip():
                return {"ok": False, "error": "缺少 batch_id"}
            resolved = self._resolve_account_wxid(account_wxid)
            rows = MessageBuffer().get_batch_messages(batch_id, account_wxid=resolved)
            limit = max(1, int(limit))
            items = [
                {
                    "id": row.get("id"),
                    "sender_attr": row.get("sender_attr"),
                    "content": row.get("content"),
                    "message_type": row.get("message_type"),
                    "timestamp": row.get("timestamp") or row.get("created_at"),
                }
                for row in rows[-limit:]
                if str(row.get("sender_attr") or "").strip().lower() in {"self", "friend"}
                and str(row.get("message_type") or "text").strip().lower() != "system"
                and not TIME_LABEL_RE.match(str(row.get("content") or "").strip())
            ]
            # 新消息不足时并入监听基线尾部（启动前窗口内最近对话）——
            # 用户预期「进入监听能看到前几条聊天数据」，此前基线按设计不落
            # buffer 导致起始空白
            if len(items) < limit:
                try:
                    from ..services.realtime.monitor_service import RealtimeMonitorService
                    monitor = RealtimeMonitorService()
                    baseline_tail = getattr(monitor, "_baseline_tail", None) or []
                    if baseline_tail:
                        # 逐条 insert(0) 会把时间序倒置——先组好基线段再整体前置
                        baseline_items = [
                            {
                                "id": -(idx + 1),  # 负数伪 id 避免与 buffer 冲突
                                "sender_attr": msg.get("sender_attr"),
                                "content": msg.get("content"),
                                "message_type": msg.get("message_type"),
                                "timestamp": msg.get("timestamp"),
                            }
                            for idx, msg in enumerate(baseline_tail)
                            if str(msg.get("sender_attr") or "").strip().lower() in {"self", "friend"}
                            and str(msg.get("message_type") or "text").strip().lower() != "system"
                            and not TIME_LABEL_RE.match(str(msg.get("content") or "").strip())
                        ]
                        items = (baseline_items + items)[-limit:]
                except Exception as exc:
                    logger.debug("[Bridge] 基线尾部并入跳过: %s", exc)
            return {"ok": True, "messages": items}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_pending_suggestions(self, batch_id: str, account_wxid: str = "") -> dict[str, Any]:
        """
        获取当前批次的待处理 AI 建议

        Args:
            batch_id: 监听批次 ID

        Returns:
            {"ok": True, "suggestions": [...], "emotion_summary": {...}}
        """
        try:
            from ..db.connection import get_db
            from ..services.realtime.monitor_service import RealtimeMonitorService

            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            # 查询 pending 状态的建议
            cursor = conn.execute('''
                SELECT id, trigger_type, intent, severity, summary, speeches,
                       confidence, engine_type, trigger_context, status, created_at, reply, thought_process
                FROM realtime_suggestions
                WHERE account_wxid = ? AND batch_id = ?
                  AND status IN ('pending', 'attribution_window', 'feedback_processing')
                ORDER BY created_at DESC
                LIMIT 20
            ''', (resolved_account_wxid, batch_id))

            suggestions = []
            for row in cursor.fetchall():
                import json
                try:
                    from ..services.realtime.suggestion_observer import mark_suggestion_viewed

                    mark_suggestion_viewed(
                        conn,
                        row['id'],
                        account_wxid=resolved_account_wxid,
                        batch_id=batch_id,
                        trigger_type=row['trigger_type'],
                    )
                except Exception as obs_e:
                    logger.error(f"[Bridge] 标记建议已查看失败: {obs_e}")
                suggestions.append({
                    'id': row['id'],
                    'trigger_type': row['trigger_type'],
                    'intent': row['intent'],
                    'severity': row['severity'],
                    'summary': row['summary'],
                    'speeches': json.loads(row['speeches']),
                    'confidence': row['confidence'],
                    'engine_type': row['engine_type'],
                    'trigger_context': json.loads(row['trigger_context']) if row['trigger_context'] else None,
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'reply': row['reply'],
                    'thought_process': row['thought_process'],
                })
            conn.commit()

            # 获取情绪摘要
            emotion_summary = None
            monitor = RealtimeMonitorService()
            if monitor.emotion_tracker:
                emotion_summary = monitor.emotion_tracker.get_emotion_summary()

            return {
                "ok": True,
                "suggestions": suggestions,
                "emotion_summary": emotion_summary,
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 获取待处理建议失败: {e}")
            traceback.print_exc()
            return {"ok": False, "error": str(e), "suggestions": []}

    def dismiss_suggestion(self, suggestion_id: int, account_wxid: str = "") -> dict[str, Any]:
        """
        标记建议为已关闭

        Args:
            suggestion_id: 建议记录 ID
        """
        try:
            import time as _time
            from ..db.connection import get_db

            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)
            cursor = conn.execute('''
                UPDATE realtime_suggestions
                SET status = 'dismissed', dismissed_at = ?
                WHERE id = ? AND account_wxid = ?
            ''', (int(_time.time()), suggestion_id, resolved_account_wxid))
            conn.commit()

            if cursor.rowcount != 1:
                return {"ok": False, "error": "suggestion_not_found"}
            try:
                from ..services.realtime.suggestion_observer import EVENT_DISMISSED, record_observation

                record_observation(
                    conn,
                    suggestion_id=suggestion_id,
                    account_wxid=resolved_account_wxid,
                    event_type=EVENT_DISMISSED,
                )
                conn.commit()
            except Exception as obs_e:
                logger.error(f"[Bridge] 记录建议关闭观察事件失败: {obs_e}")
            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 关闭建议失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_suggestion_metrics(self, days: int = 7, account_wxid: str = "") -> dict[str, Any]:
        """Return aggregated suggestion observation metrics for recent days."""
        try:
            from ..db.connection import get_db
            from ..services.realtime.suggestion_observer import get_suggestion_metrics

            normalized_days = max(1, int(days or 7))
            conn = get_db()
            metrics = get_suggestion_metrics(
                conn,
                account_wxid=self._resolve_account_wxid(account_wxid),
                days=normalized_days,
            )
            return {
                "ok": True,
                "metrics": metrics,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取建议指标失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "metrics": {},
            }

    def get_suggestion_config(self) -> dict[str, Any]:
        """获取 AI 建议配置（从系统设置读取）"""
        try:
            from ..services.realtime.providers.factory import resolve_effective_listener_backend

            return {
                "ok": True, 
                "config": {
                    "trigger_mode": self.settings.get("trigger_mode", "semi_auto"),
                    "intent": self.settings.get("intent", "maintain"),
                    "auto_rate_limit": int(self.settings.get("auto_rate_limit", 10)),
                    "engine_type": "llm",
                    "listener_backend": resolve_effective_listener_backend(
                        self.settings.get("listener_backend")
                    ),
                }
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_dynamic_quick_prompts(self, batch_id: str) -> dict[str, Any]:
        """
        获取动态快捷回复联想词（最近聊天上下文生成）
        
        Args:
            batch_id: 当前监听批次 ID
            
        Returns:
            {"ok": True, "prompts": ["短语1", "短语2", "短语3", "短语4"]}
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService
            from ..services.realtime.message_query import get_messages_with_sentiment
            from ..services.realtime.suggestion_engine import SuggestionEngineFactory

            # 获取最近消息
            recent_messages = get_messages_with_sentiment(
                batch_id,
                10,
                account_wxid=self._resolve_account_wxid(""),
            )
            
            # 使用配置中的引擎（通常是 llm）
            monitor = RealtimeMonitorService()
            engine_type = monitor._suggestion_config.get('engine_type', 'llm')
            
            if engine_type != 'llm':
                return {"ok": False, "error": f"当前配置的引擎为 {engine_type}，动态联想词需要配置 llm 引擎才能使用"}

            engine = SuggestionEngineFactory.create("llm")
            
            context = {
                "recent_messages": recent_messages
            }
            
            # 加入联系人画像提升质量
            if monitor.current_display_name:
                try:
                    from ..services.realtime.contact_profiler import ContactProfiler
                    profiler = ContactProfiler()
                    cached = profiler.get_profile(monitor.current_display_name)
                    if cached and not cached['expired']:
                        context['contact_profile'] = cached['profile']
                except Exception as e:
                    logger.error(f"[Bridge] 获取画像失败(联想词阶段): {e}")

            # 调用特化的生成方法
            if hasattr(engine, 'generate_quick_prompts'):
                prompts = engine.generate_quick_prompts(context)
            else:
                return {"ok": False, "error": "当前引擎不支持动态联想词"}

            return {"ok": True, "prompts": prompts}

        except Exception as e:
            logger.error(f"[Bridge] 获取动态联想词失败: {e}")
            return {"ok": False, "error": str(e), "prompts": []}

    def set_suggestion_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """更新并持久化 AI 建议配置"""
        try:
            from ..services.realtime.providers.factory import normalize_listener_backend

            # 1. 更新通用设置文件
            with self._settings_lock:
                for key in ('trigger_mode', 'intent', 'auto_rate_limit', 'listener_backend'):
                    if key in config:
                        if key == 'listener_backend':
                            self.settings[key] = normalize_listener_backend(config[key])
                        else:
                            self.settings[key] = config[key]
                self._save_settings()

            # 2. 同时热更新给运行中的 RealtimeMonitorService
            try:
                from ..services.realtime.monitor_service import RealtimeMonitorService
                monitor = RealtimeMonitorService()
                monitor.set_suggestion_config(config)
            except Exception as inner_e:
                logger.debug(f"[Bridge] 热更新 MonitorService 失败（可能未运行）: {inner_e}")

            return {"ok": True, "config": self.get_suggestion_config().get("config", {})}
        except Exception as e:
            logger.error(f"[Bridge] 设置建议配置失败: {e}")
            return {"ok": False, "error": str(e)}

    # ==================== 特征提取分析相关 ====================

    def _get_feature_service(self):
        """延迟加载特征提取服务"""
        if self._feature_service is None:
            from ..services.analysis.feature_extraction_service import FeatureExtractionService
            self._feature_service = FeatureExtractionService()
        return self._feature_service

    def _build_feature_config(self, config: dict | None = None):
        """Merge caller overrides onto persisted feature extraction settings."""
        from ..services.analysis.feature_extraction_config import FeatureExtractionConfig

        base_config = FeatureExtractionConfig.from_settings()
        merged_config = {
            **base_config.__dict__,
            **dict(config or {}),
        }
        merged_config["analysis_device_mode"] = normalize_analysis_device_mode(
            merged_config.get("analysis_device_mode", self.settings.get("analysis_device_mode"))
        )
        return FeatureExtractionConfig(**merged_config)

    def extract_features(self, conversation_id: int, config: dict = None) -> dict:
        """
        执行完整的特征提取流程

        Args:
            conversation_id: 对话ID
            config: 可选配置参数

        Returns:
            {
                "success": True,
                "data": {
                    "task_id": "extract_42_xxx",
                    "status": "started",
                    "message": "Feature extraction started"
                }
            }
        """
        try:
            logger.info(f"[Bridge] 开始特征提取: conversation_id={conversation_id}")
            service = self._get_feature_service()
            service.config = self._build_feature_config(config)
            service.config.validate()

            # 同会话已有运行中的提取：直接返回该任务，防止并发提取互相删数据。
            # 必须在新建取消事件之前判断——否则运行中线程持有的旧事件被替换，
            # 之后点「停止」设置的将是新事件，旧任务再也停不掉
            running_task = service.find_running_task(conversation_id)
            if running_task:
                return {
                    "success": True,
                    "data": {"task_id": running_task, "status": "started", "message": "已有进行中的提取任务，已复用"},
                }

            import threading
            self._analysis_cancel_event = threading.Event()

            # 异步启动：立即返回 task_id，前端轮询 get_extraction_progress
            # （此前同步阻塞至完成，导致切页丢进度 + 重复发起时后端叠加运行）
            import uuid as _uuid
            task_id = f"extract_{conversation_id}_{int(time.time())}_{_uuid.uuid4().hex[:6]}"
            cancel_event = self._analysis_cancel_event
            threading.Thread(
                target=lambda: service.extract_features(
                    conversation_id, cancel_event=cancel_event, task_id=task_id
                ),
                daemon=True,
                name=f"feature-extract-{conversation_id}",
            ).start()

            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": "started",
                    "message": "Feature extraction started"
                }
            }
        except Exception as e:
            if "取消" in str(e):
                logger.info("[Bridge] 特征提取被用户取消")
                return {
                    "success": False,
                    "error": "分析已被用户取消"
                }
            else:
                import traceback
                logger.error(f"[Bridge] 特征提取失败: {e}")
                traceback.print_exc()
                return {
                    "success": False,
                    "error": str(e)
                }

    def get_extraction_progress(self, task_id: str) -> dict:
        """
        查询特征提取任务进度

        Args:
            task_id: 任务ID

        Returns:
            {
                "success": True,
                "data": {
                    "task_id": "extract_42_xxx",
                    "status": "in_progress",
                    "progress": 45.5,
                    "current_step": "Calculating response times",
                    "message": "Processing 25,000 / 50,000 messages"
                }
            }
        """
        try:
            service = self._get_feature_service()
            progress = service.get_task_progress(task_id)

            return {
                "success": True,
                "data": progress
            }
        except Exception as e:
            logger.error(f"[Bridge] 查询任务进度失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }


    # ==================== 实时监听恢复与回溯 ====================

    def get_realtime_resume_info(
        self,
        talker_display_name: str,
        threshold_seconds: int = 300,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        获取指定联系人的监听恢复探测信息。

        Returns:
            {
                "ok": True,
                "has_checkpoint": True/False,
                "should_offer_resume": True/False,
                "gap_seconds": 123,
                "last_message_timestamp": 1234567890,
                "last_message_preview": "..."
            }
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService

            monitor_service = RealtimeMonitorService()
            result = monitor_service.get_resume_probe(
                talker_display_name=talker_display_name,
                threshold_seconds=threshold_seconds,
                account_wxid=self._resolve_account_wxid(account_wxid),
            )
            return {"ok": True, **result}
        except Exception as e:
            logger.error(f"[Bridge] 获取恢复探测信息异常: {e}")
            return {
                "ok": False,
                "has_checkpoint": False,
                "should_offer_resume": False,
                "error": str(e),
            }

    def run_realtime_backfill(
        self,
        talker_display_name: str,
        threshold_seconds: int = 300,
        max_scroll_rounds: int = 80,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        执行指定联系人的回溯补全。
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService

            monitor_service = RealtimeMonitorService()
            monitor_service.current_account_wxid = self._resolve_account_wxid(account_wxid)
            result = monitor_service.run_backfill(
                talker_display_name=talker_display_name,
                threshold_seconds=threshold_seconds,
                max_scroll_rounds=max_scroll_rounds,
            )
            return {"ok": result.get('success', False), **result}
        except Exception as e:
            logger.error(f"[Bridge] 执行回溯补全异常: {e}")
            return {
                "ok": False,
                "success": False,
                "inserted_count": 0,
                "need_reimport": False,
                "error": str(e),
            }


    # ==================== 会话线程归档与继承 ====================

    def _archive_current_session(self, monitor_service, user_chat_history=None):
        """内部方法：将当前监听会话归档为线程"""
        if not monitor_service.is_monitoring:
            return

        batch_id = monitor_service.current_batch_id
        display_name = monitor_service.current_display_name
        if not batch_id or not display_name:
            return

        from ..services.realtime.session_thread_service import SessionThreadService
        from ..services.realtime.message_buffer import MessageBuffer

        # 读取消息
        buffer = MessageBuffer()
        messages = buffer.get_batch_messages(batch_id, account_wxid=monitor_service.current_account_wxid)

        # 读取建议
        suggestions = []
        try:
            from ..db.connection import get_db
            conn = get_db()
            rows = conn.execute(
                'SELECT * FROM realtime_suggestions WHERE account_wxid = ? AND batch_id = ? ORDER BY created_at',
                (monitor_service.current_account_wxid, batch_id)
            ).fetchall()
            suggestions = [dict(r) for r in rows]
        except Exception:
            pass

        if not messages and not suggestions:
            return

        # 归档（后台线程避免阻塞 UI）
        import threading
        svc = SessionThreadService()
        t = threading.Thread(
            target=svc.archive_thread,
            args=(batch_id, display_name, messages, suggestions, None, user_chat_history, monitor_service.current_account_wxid),
            daemon=True
        )
        t.start()
        logger.debug(f"[Bridge] 会话归档已启动 (batch={batch_id[:8]}...)")

    def get_latest_thread(self, display_name: str, account_wxid: str = "") -> dict[str, Any]:
        """获取该联系人最近的会话线程（24 小时内）"""
        try:
            from ..services.realtime.session_thread_service import SessionThreadService
            svc = SessionThreadService()
            thread = svc.get_latest_thread(display_name, account_wxid=self._resolve_account_wxid(account_wxid))
            return {
                "ok": True,
                "has_thread": thread is not None,
                "thread": thread
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取最近线程失败: {e}")
            return {"ok": False, "error": str(e)}

    def load_thread_context(self, thread_id: int) -> dict[str, Any]:
        """加载线程的完整上下文（用于继续上次指导）"""
        try:
            from ..services.realtime.session_thread_service import SessionThreadService
            svc = SessionThreadService()
            ctx = svc.load_thread_context(thread_id, account_wxid=self._resolve_account_wxid(""))
            return {
                "ok": True,
                "context": ctx
            }
        except Exception as e:
            logger.error(f"[Bridge] 加载线程上下文失败: {e}")
            return {"ok": False, "error": str(e)}

    def open_external_url(self, url: str) -> dict[str, Any]:
        """在系统默认浏览器中打开外部链接"""
        try:
            import webbrowser
            target = str(url or "").strip()
            if not target.startswith(("http://", "https://")):
                return {"ok": False, "error": "仅允许打开 http/https 链接"}
            webbrowser.open(target)
            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 打开外部链接失败: {e}")
            return {"ok": False, "error": str(e)}

