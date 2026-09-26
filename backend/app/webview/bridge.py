from typing import Any, Optional
import json
import os
import logging
import importlib
import shutil
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
    EMBEDDING_MODEL_DIRNAME,
    EMBEDDING_MODEL_DIM,
    EMBEDDING_MODEL_REPO_ID,
    MODEL_ROOT_DIR_KEY,
    SENTIMENT_MODEL_DIRNAME,
    SENTIMENT_MODEL_REPO_ID,
    get_default_model_root_dir,
    get_embedding_model_dir,
    get_model_root_dir,
    get_sentiment_model_dir,
    normalize_model_root_dir,
)

logger = logging.getLogger(__name__)
class Bridge:
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

    def _prewarm_current_rag_index(
        self,
        *,
        account_wxid: str,
        display_name: str = "",
        username: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        try:
            from ..services.realtime.rag.config import load_rag_settings

            if not load_rag_settings().get("rag_enabled"):
                return
            raw_conversation_id = (context or {}).get("conversation_id") or (context or {}).get("_rag_conversation_id")
            conversation_id = int(raw_conversation_id) if raw_conversation_id else None
            if not conversation_id:
                conversation_id = self._resolve_current_conversation_id(
                    account_wxid=account_wxid,
                    display_name=display_name,
                    username=username,
                )
            if not account_wxid or not conversation_id:
                return
            if context is not None:
                context.setdefault("conversation_id", conversation_id)
            from ..services.realtime.rag.indexer import RagIndexer

            RagIndexer().ensure_contact_index(
                account_wxid=str(account_wxid),
                conversation_id=int(conversation_id),
            )
        except Exception as exc:
            logger.debug("[Bridge] RAG prewarm skipped: %s", exc)

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

    def _prune_task_dicts(self, max_age_hours: float = 24.0) -> None:
        """按 TTL 清理三个任务字典（建议流/密钥捕获/模型下载）中的过期条目。

        - 终态条目（建议流 done/error、捕获已出结果、下载 completed/failed）
          超过 1 小时即删除；
        - 运行中条目超过 max_age_hours（默认 24 小时）也删除（视作僵死任务）。
        时间戳兼容秒/毫秒两种单位。调用方不得在持有这三个任务锁时调用（会死锁）。
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

    def _get_sentiment_model_manager(self):
        from ..services.model_manager import ModelManager

        return ModelManager(
            model_dir=str(get_sentiment_model_dir(self.settings)),
            repo_id=SENTIMENT_MODEL_REPO_ID,
        )

    def _diagnose_embedding_model_status(self) -> dict[str, Any]:
        from ..services.model_manager import ModelManager

        diagnosis = ModelManager(
            model_dir=str(get_embedding_model_dir(self.settings)),
            repo_id=EMBEDDING_MODEL_REPO_ID,
        ).diagnose_model_status()
        diagnosis["can_recover"] = True
        return diagnosis

    def _download_embedding_model(self, progress_callback=None) -> dict[str, Any]:
        from ..services.model_manager import ModelManager

        return ModelManager(
            model_dir=str(get_embedding_model_dir(self.settings)),
            repo_id=EMBEDDING_MODEL_REPO_ID,
        ).download_model(progress_callback=progress_callback)

    def _get_model_root_dir(self) -> Path:
        return get_model_root_dir(self.settings)

    def _migrate_model_root_dir(self, target_dir: str) -> dict[str, Any]:
        with self._settings_lock:
            current_root = self._get_model_root_dir()
            next_root = Path(normalize_model_root_dir(target_dir))
            next_root.mkdir(parents=True, exist_ok=True)

            if current_root == next_root:
                self.settings[MODEL_ROOT_DIR_KEY] = str(next_root)
                self._save_settings()
                return {
                    "ok": True,
                    "model_root_dir": str(next_root),
                    "migrated_models": [],
                    "skipped_models": [SENTIMENT_MODEL_DIRNAME, EMBEDDING_MODEL_DIRNAME],
                }

            moved: list[tuple[Path, Path]] = []
            skipped: list[str] = []
            try:
                for dirname in (SENTIMENT_MODEL_DIRNAME, EMBEDDING_MODEL_DIRNAME):
                    source = current_root / dirname
                    destination = next_root / dirname
                    if not source.exists():
                        skipped.append(dirname)
                        continue
                    if destination.exists():
                        raise FileExistsError(f"目标目录已存在: {destination}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination))
                    moved.append((source, destination))

                self.settings[MODEL_ROOT_DIR_KEY] = str(next_root)
                self._save_settings()
                return {
                    "ok": True,
                    "model_root_dir": str(next_root),
                    "migrated_models": [dst.name for _, dst in moved],
                    "skipped_models": skipped,
                }
            except Exception:
                for source, destination in reversed(moved):
                    if destination.exists() and not source.exists():
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(destination), str(source))
                raise

    def update_model_root_dir(self, new_dir: str) -> dict[str, Any]:
        try:
            result = self._migrate_model_root_dir(new_dir)
            return {
                **result,
                "sentiment_model_dir": str(get_sentiment_model_dir(self.settings)),
                "embedding_model_dir": str(get_embedding_model_dir(self.settings)),
            }
        except Exception as e:
            logger.error(f"[Bridge] 更新模型目录失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "model_root_dir": str(self._get_model_root_dir()),
                "migrated_models": [],
                "skipped_models": [],
            }

    def ping(self) -> str:
        return "pong"

    def _get_fresh_affinity_service_class(self):
        """Reload affinity analysis modules so updated scoring code takes effect immediately."""
        module_names = [
            "backend.app.services.analysis.emotional_resonance_service",
            "backend.app.services.analysis.affinity_analysis_service",
        ]
        reloaded = None
        for module_name in module_names:
            module = importlib.import_module(module_name)
            reloaded = importlib.reload(module)
        return reloaded.AffinityAnalysisService

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

    def verify_wechat_key(
        self,
        db_key: str,
        custom_paths: dict[str, str] | None = None,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        验证微信数据库密钥是否有效
        
        Args:
            db_key: 32位hex密钥字符串
            
        Returns:
            {"ok": True} 或 {"ok": False, "error": "..."}
        """
        preferred_paths = custom_paths or self._get_wechat_custom_paths(account_wxid)
        result = self.wechat_service.verify_key(db_key, preferred_paths)
        if result.get("ok") and preferred_paths:
            resolved_wxid = str(preferred_paths.get("account_wxid") or preferred_paths.get("current_user") or self._resolve_account_wxid(account_wxid))
            if resolved_wxid:
                with self._settings_lock:
                    update_wechat_account_import_state(
                        self.settings,
                        resolved_wxid,
                        db_key=db_key,
                        wechat_dir=str(preferred_paths.get("wechat_dir") or "") or None,
                        source="custom" if custom_paths else None,
                    )
                    self._save_settings()
        return result

    def capture_wechat_db_key(
        self,
        account_wxid: str = "",
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Automatically capture, verify, and persist the active account DB key."""
        try:
            from ..services.wechat.keys import create_key_provider

            provider = create_key_provider(
                wechat_dir=self._key_scan_wechat_dir(account_wxid)
            )
            result = provider.capture_db_key(
                timeout_seconds=timeout_seconds,
                account_wxid=account_wxid,
            )
            if not result.get("ok"):
                return result
            return self._finalize_captured_wechat_db_key(result, account_wxid)
        except Exception as exc:
            logger.error("[Bridge] automatic WeChat DB key capture failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "code": "capture_failed",
                "error": str(exc),
                "account_wxid": str(account_wxid or ""),
            }

    def _finalize_captured_wechat_db_key(
        self,
        result: dict[str, Any],
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Verify and persist a key captured by either synchronous or session flow."""
        db_key = str(result.get("db_key") or "").strip().lower()
        key_type = str(result.get("key_type") or "passphrase").strip() or "passphrase"
        raw_keys = result.get("raw_keys") if key_type == "raw" else None
        preferred_paths = self._get_wechat_custom_paths(account_wxid)
        verified = self.wechat_service.verify_key(
            db_key, preferred_paths, key_type=key_type, raw_keys=raw_keys
        )
        if not verified.get("ok"):
            return {
                **result,
                "ok": False,
                "code": "key_verification_failed",
                "error": verified.get("error") or "自动获取的密钥无法验证当前数据库",
            }

        resolved_paths = preferred_paths
        if not resolved_paths:
            try:
                resolved_paths = self.wechat_service.resolve_wechat_paths()
            except Exception:
                resolved_paths = None

        resolved_wxid = str(
            (resolved_paths or {}).get("account_wxid")
            or (resolved_paths or {}).get("current_user")
            or self._resolve_account_wxid(account_wxid)
            or ""
        ).strip()
        if resolved_wxid:
            with self._settings_lock:
                update_wechat_account_import_state(
                    self.settings,
                    resolved_wxid,
                    db_key=db_key,
                    key_type=key_type,
                    raw_keys=raw_keys if key_type == "raw" else {},
                    wechat_dir=str((resolved_paths or {}).get("wechat_dir") or "") or None,
                )
                self._save_settings()

        return {
            **result,
            "ok": True,
            "db_key": db_key,
            "account_wxid": resolved_wxid,
        }

    def get_wechat_key_capture_status(self) -> dict[str, Any]:
        """Inspect whether WeChat is at its login screen or already logged in."""
        try:
            if sys.platform != "win32":
                # Linux：无需重启微信，只需「退出登录后重新登录」触发断点
                from ..services.wechat.keys.gdb_linux import find_linux_wechat_pids

                pids = find_linux_wechat_pids()
                return {
                    "ok": True,
                    "running": bool(pids),
                    "login_state": "logged_in" if pids else "not_running",
                    "processes": [{"pid": p} for p in pids],
                    "restart_required": False,
                }
            from ..services.wechat.keys.flow_win import inspect_wechat_login_state

            return inspect_wechat_login_state()
        except Exception as exc:
            logger.error("[Bridge] inspect WeChat key-capture state failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "running": False,
                "login_state": "unknown",
                "processes": [],
                "error": str(exc),
            }

    def restart_wechat_for_key_capture(self) -> dict[str, Any]:
        """Restart WeChat for key capture after the frontend obtains confirmation."""
        if sys.platform != "win32":
            # Linux 密钥捕获不需要重启微信（静态内存断点等待重新登录即可）
            return {
                "ok": True,
                "restarted": False,
                "restart_required": False,
                "message": "Linux 无需重启微信，请在微信中退出登录后重新登录。",
            }
        try:
            from ..services.wechat.keys.flow_win import restart_wechat_for_key_capture

            return restart_wechat_for_key_capture()
        except Exception as exc:
            logger.error("[Bridge] restart WeChat for key capture failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "code": "restart_failed",
                "error": str(exc),
            }

    def start_wechat_db_key_capture(
        self,
        account_wxid: str = "",
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        """Install the Hook and return as soon as it is ready for a login event."""
        try:
            from ..services.wechat.keys import create_key_provider

            provider = create_key_provider(
                wechat_dir=self._key_scan_wechat_dir(account_wxid)
            )
            session = provider.create_capture_session(
                timeout_seconds=timeout_seconds,
                account_wxid=account_wxid,
            )
            initial = session.start()
            if initial.get("status") not in {"hook_ready", "captured"}:
                return initial

            session_id = uuid.uuid4().hex
            now_ms = int(time.time() * 1000)
            with self._wechat_key_capture_lock:
                self._wechat_key_capture_sessions[session_id] = {
                    "session": session,
                    "account_wxid": str(account_wxid or ""),
                    "final_result": None,
                    "created_at": now_ms,
                    "updated_at": now_ms,
                }
            # 新增条目时顺带清理过期会话（锁外调用，避免锁内嵌套死锁）
            self._prune_task_dicts()
            return {
                **initial,
                "ok": True,
                "session_id": session_id,
            }
        except Exception as exc:
            logger.error("[Bridge] start WeChat DB key capture failed: %s", exc, exc_info=True)
            return {
                "ok": False,
                "status": "failed",
                "code": "capture_start_failed",
                "error": str(exc),
            }

    def get_wechat_db_key_capture_session(self, session_id: str) -> dict[str, Any]:
        """Return Hook progress; verify and persist the key once it is captured."""
        with self._wechat_key_capture_lock:
            entry = self._wechat_key_capture_sessions.get(str(session_id or ""))
        if not entry:
            return {
                "ok": False,
                "status": "failed",
                "code": "capture_session_not_found",
                "error": "数据库密钥获取会话不存在或已失效。",
            }

        session = entry["session"]
        snapshot = session.snapshot()
        if snapshot.get("status") != "captured":
            return snapshot

        with self._wechat_key_capture_lock:
            final_result = entry.get("final_result")
            if final_result is None:
                final_result = self._finalize_captured_wechat_db_key(
                    snapshot,
                    str(entry.get("account_wxid") or ""),
                )
                entry["final_result"] = final_result
                entry["updated_at"] = int(time.time() * 1000)

        return {
            **final_result,
            "status": "completed" if final_result.get("ok") else "failed",
            "message": "数据库密钥已验证，正在开始导入。"
            if final_result.get("ok")
            else str(final_result.get("error") or "数据库密钥验证失败。"),
        }

    def import_wechat_data(
        self,
        db_key: str,
        options: dict[str, Any] | None = None,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        导入微信数据（完整流程）
        
        Args:
            db_key: 32位hex密钥
            options: 导入选项 {
                "import_contacts": bool,
                "import_messages": bool,
                "limit": int
            }
            
        Returns:
            {
                "ok": True,
                "stats": {"contacts": 120, "messages": 15230, "conversations": 45},
                "warnings": [...]
            }
        """
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

        result = self.wechat_service.import_wechat_data(
            db_key, options, custom_paths, raw_keys=raw_keys
        )
        if result.get("ok"):
            snapshot = self.wechat_service.build_file_size_snapshot(custom_paths)
            self._save_wechat_import_baseline(snapshot, account_wxid=resolved_wxid, db_key=db_key)
        return result

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

            # 自动补充上下文：情绪摘要
            if 'emotion_summary' not in context and monitor.emotion_tracker:
                context['emotion_summary'] = monitor.emotion_tracker.get_emotion_summary()

            # 自动补充上下文：最近消息
            if 'recent_messages' not in context and monitor.current_batch_id:
                try:
                    from ..services.realtime.message_query import get_messages_with_sentiment
                    recent = get_messages_with_sentiment(
                        monitor.current_batch_id,
                        50,
                        account_wxid=account_wxid,
                    )
                    context['recent_messages'] = recent
                except Exception as e:
                    logger.error(f"[Bridge] 获取最近消息失败: {e}")

            # 自动补充上下文：联系人画像与本体画像
            self_profile_cache = None
            if monitor.current_display_name:
                try:
                    from ..services.realtime.contact_profiler import ContactProfiler
                    from ..services.realtime.self_profiler import SelfProfiler
                    
                    if 'contact_profile' not in context:
                        profiler = ContactProfiler()
                        cached = profiler.get_profile(monitor.current_display_name)
                        if cached and not cached['expired']:
                            context['contact_profile'] = cached['profile']
                            
                    if 'self_profile' not in context:
                        s_profiler = SelfProfiler()
                        s_cached = s_profiler.get_profile(monitor.current_display_name)
                        if s_cached and not s_cached['expired']:
                            context['self_profile'] = s_cached['profile']
                            self_profile_cache = s_cached
                except Exception as e:
                    logger.error(f"[Bridge] 获取画像失败: {e}")

            try:
                from ..services.realtime.historical_context import (
                    augment_context_with_historical_data,
                )

                augment_context_with_historical_data(
                    context,
                    self_profile_cache=self_profile_cache,
                )
            except Exception as e:
                logger.error(f"[Bridge] 构建 historical_context 失败: {e}")

            # 传递联系人名称以便查询调教规则
            if monitor.current_display_name:
                context['display_name'] = monitor.current_display_name
            self._prewarm_current_rag_index(
                account_wxid=account_wxid,
                display_name=str(monitor.current_display_name or context.get("display_name") or ""),
                username=str(getattr(monitor, "current_talker", "") or ""),
                context=context,
            )

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
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS realtime_suggestions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_wxid TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        severity TEXT DEFAULT 'medium',
                        summary TEXT NOT NULL,
                        speeches TEXT NOT NULL,
                        confidence REAL DEFAULT 1.0,
                        status TEXT DEFAULT 'pending',
                        engine_type TEXT DEFAULT 'llm',
                        trigger_context TEXT,
                        created_at INTEGER NOT NULL,
                        read_at INTEGER,
                        dismissed_at INTEGER,
                        reply TEXT,
                        thought_process TEXT
                    )
                ''')
                try:
                    conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN reply TEXT")
                except:
                    pass
                try:
                    conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN thought_process TEXT")
                except:
                    pass
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

    def get_rag_log_detail(self, log_id: int) -> dict[str, Any]:
        """Return what one retrieval log actually injected, for badge drill-down.

        只读、本地展示给用户本人；注入列表本身经过敏感门控，此处对
        sensitivity=sensitive 的行做深度防御过滤，绝不回传敏感原文。
        """
        try:
            from ..db.connection import get_db
            from ..services.realtime.rag.store import RagStore

            conn = get_db()
            store = RagStore(conn)

            row = conn.execute(
                "SELECT * FROM rag_retrieval_logs WHERE id = ?", (int(log_id),)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "log_not_found"}

            def _load_json_ids(raw: Any) -> list[int]:
                try:
                    values = json.loads(raw or "[]")
                except Exception:
                    return []
                ids: list[int] = []
                for value in values:
                    try:
                        parsed = int(value)
                    except (TypeError, ValueError):
                        continue
                    if parsed > 0:
                        ids.append(parsed)
                return ids

            fact_ids = _load_json_ids(row["fact_ids_json"])
            injected_ids = _load_json_ids(row["document_ids_json"])
            candidate_ids = _load_json_ids(row["candidate_ids_json"]) or injected_ids
            evidence_ids_all = _load_json_ids(row["evidence_ids_json"])

            # fact 与 document 是两张表的自增主键，数字可能撞号；必须用与
            # document_ids_json 同源同序的 selected_doc_types_json 区分类型，
            # 不能只靠 fact_ids_json 推断。
            try:
                selected_types = [str(t or "") for t in json.loads(row["selected_doc_types_json"] or "[]")]
            except Exception:
                selected_types = []
            if len(selected_types) == len(injected_ids):
                fact_ids = [
                    i for i, t in zip(injected_ids, selected_types) if t == "fact_memory"
                ]
                doc_ids = [
                    i for i, t in zip(injected_ids, selected_types) if t != "fact_memory"
                ]
            else:
                fact_id_set = set(fact_ids)
                fact_ids = [i for i in injected_ids if i in fact_id_set]
                doc_ids = [i for i in injected_ids if i not in fact_id_set]

            def _evidence_excerpts(evidence_ids: list[int], limit: int = 3) -> list[str]:
                if not evidence_ids:
                    return []
                placeholders = ",".join("?" for _ in evidence_ids)
                try:
                    rows = conn.execute(
                        f"SELECT CAST(content AS BLOB) AS content FROM messages WHERE id IN ({placeholders})",
                        evidence_ids,
                    ).fetchall()
                except Exception:
                    return []
                excerpts = []
                for r in rows[:limit]:
                    value = r[0]
                    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
                    text = " ".join(text.split())
                    if text:
                        excerpts.append(text[:120] + ("…" if len(text) > 120 else ""))
                return excerpts

            injected_items: list[dict[str, Any]] = []

            # 事实条目（document_id 即 rag_facts.id）
            if fact_ids:
                placeholders = ",".join("?" for _ in fact_ids)
                fact_rows = conn.execute(
                    f"""
                    SELECT id, subject, kind, content, as_of, confidence, sensitivity,
                           evidence_message_ids_json
                    FROM rag_facts WHERE id IN ({placeholders})
                    """,
                    fact_ids,
                ).fetchall()
                for fr in fact_rows:
                    if str(fr["sensitivity"] or "normal") == "sensitive":
                        continue
                    evidence_ids = [
                        i for i in json.loads(fr["evidence_message_ids_json"] or "[]")
                        if isinstance(i, int)
                    ] if fr["evidence_message_ids_json"] else []
                    injected_items.append(
                        {
                            "source": "fact",
                            "id": fr["id"],
                            "doc_type": "fact_memory",
                            "content": fr["content"],
                            "subject": fr["subject"],
                            "kind": fr["kind"],
                            "as_of": fr["as_of"],
                            "confidence": fr["confidence"],
                            "evidence_excerpts": _evidence_excerpts(evidence_ids),
                        }
                    )

            # 文档条目（shared_memory / dialogue_turn 等）
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                doc_rows = conn.execute(
                    f"""
                    SELECT id, doc_type, content, source_ts, sensitivity
                    FROM rag_documents WHERE id IN ({placeholders})
                    """,
                    doc_ids,
                ).fetchall()
                for dr in doc_rows:
                    if str(dr["sensitivity"] or "normal") == "sensitive":
                        continue
                    injected_items.append(
                        {
                            "source": "document",
                            "id": dr["id"],
                            "doc_type": dr["doc_type"],
                            "content": dr["content"],
                            "subject": None,
                            "kind": None,
                            "as_of": dr["source_ts"],
                            "confidence": None,
                            "evidence_excerpts": [],
                        }
                    )

            order = {fact_id: idx for idx, fact_id in enumerate(injected_ids)}
            injected_items.sort(key=lambda item: order.get(item["id"], 10**9))

            not_injected_ids = [i for i in candidate_ids if i not in set(injected_ids)]
            return {
                "ok": True,
                "log": {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "suggestion_id": row["suggestion_id"],
                    "gate_decision": row["rag_gate_decision"],
                    "gate_reason": row["rag_gate_reason"],
                    "strategy": row["rag_strategy"],
                    "injection_mode": row["rag_injection_mode"],
                    "elapsed_ms": row["rag_latency_ms"],
                    "hit_count": row["rag_hit_count"],
                    "hot_context_only": bool(row["hot_context_only"]) if "hot_context_only" in row.keys() else False,
                    "degrade_reason": row["rag_degraded_reason"],
                    "run_provenance": row["run_provenance"] if "run_provenance" in row.keys() else "production",
                },
                "injected": injected_items,
                "candidates": {
                    "count": len(candidate_ids),
                    "injected_count": len(injected_ids),
                    "not_injected_ids": not_injected_ids[:20],
                    "evidence_total": len(evidence_ids_all),
                },
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取 RAG 日志详情失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_contact_facts(
        self, conversation_id: int, account_wxid: str = "", limit: int = 200,
        offset: int = 0, sort: str = "time_desc", kind: str = "",
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """List contact memory facts with evidence for user review/correction.

        sort: time_desc / time_asc / conf_desc；kind 为空返回全部；
        返回 kinds 聚合（含计数）供前端 tag 筛选器构建。
        """
        try:
            from ..db.connection import get_db
            from ..services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            conn = get_db()
            store = RagStore(conn)
            page_limit = max(1, min(int(limit), 200))
            page_offset = max(0, int(offset))
            kind_filter = str(kind or "").strip()
            kind_clause = "AND kind = ?" if kind_filter else ""
            kind_args = (kind_filter,) if kind_filter else ()
            enabled_clause = "AND enabled = ?" if enabled is not None else ""
            enabled_args = (int(bool(enabled)),) if enabled is not None else ()

            order_by = {
                "time_asc": "enabled DESC, as_of ASC, id ASC",
                "conf_desc": "enabled DESC, confidence DESC, as_of DESC, id DESC",
            }.get(str(sort or "time_desc"), "enabled DESC, as_of DESC, id DESC")

            rows = conn.execute(
                f"""
                SELECT id, subject, kind, content, as_of, confidence, sensitivity, enabled,
                       evidence_message_ids_json
                FROM rag_facts
                WHERE account_wxid = ? AND conversation_id = ? AND status = 'active'
                  {kind_clause} {enabled_clause}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (resolved_account, int(conversation_id), *kind_args, *enabled_args, page_limit, page_offset),
            ).fetchall()
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS fact_count,
                       COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled_fact_count
                FROM rag_facts
                WHERE account_wxid = ? AND conversation_id = ? AND status = 'active'
                  {kind_clause}
                """,
                (resolved_account, int(conversation_id), *kind_args),
            ).fetchone()
            raw_count_row = conn.execute(
                "SELECT COUNT(*) FROM rag_facts WHERE account_wxid = ? AND conversation_id = ?",
                (resolved_account, int(conversation_id)),
            ).fetchone()
            raw_fact_count = int(raw_count_row[0]) if raw_count_row else 0
            logger.debug(
                "[Bridge] get_contact_facts conv=%s account=%s raw=%s listed=%s",
                conversation_id,
                resolved_account,
                raw_fact_count,
                len(rows),
            )
            feedback = store.list_fact_user_feedback(resolved_account, int(conversation_id))

            contact_avatar = ""
            try:
                conv_row = conn.execute(
                    "SELECT avatar_path FROM conversations WHERE id = ?",
                    (int(conversation_id),),
                ).fetchone()
                if conv_row and conv_row["avatar_path"]:
                    contact_avatar = str(conv_row["avatar_path"] or "").strip()
                if not contact_avatar:
                    c_row = conn.execute(
                        """
                        SELECT avatar_path FROM contacts
                        WHERE account_wxid = ? AND username = (SELECT username FROM conversations WHERE id = ?)
                        LIMIT 1
                        """,
                        (resolved_account, int(conversation_id)),
                    ).fetchone()
                    if c_row and c_row["avatar_path"]:
                        contact_avatar = str(c_row["avatar_path"] or "").strip()
            except Exception:
                pass

            user_avatar = ""
            try:
                user_prof = self.get_current_user_profile(account_wxid=resolved_account)
                if user_prof.get("ok") and user_prof.get("profile"):
                    user_avatar = str(user_prof["profile"].get("avatar") or "").strip()
            except Exception:
                pass

            evidence_ids_by_fact: dict[int, list[int]] = {}
            all_evidence_ids: set[int] = set()
            for row in rows:
                try:
                    ids = [int(v) for v in json.loads(row["evidence_message_ids_json"] or "[]") if str(v).isdigit()]
                except Exception:
                    ids = []
                ids = [i for i in ids if i > 0][:6]
                evidence_ids_by_fact[int(row["id"])] = ids
                all_evidence_ids.update(ids)

            evidence_msg_by_id: dict[int, dict[str, Any]] = {}
            if all_evidence_ids:
                ids = list(all_evidence_ids)
                placeholders = ",".join("?" for _ in ids)
                try:
                    cols = {
                        r["name"]
                        for r in conn.execute("PRAGMA table_info(messages)").fetchall()
                    }
                    sender_col = "is_sender" if "is_sender" in cols else "0 AS is_sender"
                    time_col = (
                        "timestamp"
                        if "timestamp" in cols
                        else ("created_at" if "created_at" in cols else "0 AS timestamp")
                    )
                    msg_rows = conn.execute(
                        f"""
                        SELECT id, {sender_col}, {time_col}, CAST(content AS BLOB) AS content
                        FROM messages
                        WHERE id IN ({placeholders})
                        ORDER BY {time_col} ASC, id ASC
                        """,
                        ids,
                    ).fetchall()
                    for msg_row in msg_rows:
                        value = msg_row["content"]
                        text_val = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
                        text_val = " ".join(text_val.split())
                        if text_val:
                            ts_val = (
                                msg_row["timestamp"]
                                if "timestamp" in msg_row.keys()
                                else (msg_row["created_at"] if "created_at" in msg_row.keys() else 0)
                            )
                            evidence_msg_by_id[int(msg_row["id"])] = {
                                "id": int(msg_row["id"]),
                                "is_sender": bool(msg_row["is_sender"]),
                                "timestamp": int(ts_val or 0),
                                "text": text_val[:180] + ("…" if len(text_val) > 180 else ""),
                            }
                except Exception as ex:
                    logger.warning("[Bridge] 查询证据消息失败: %s", ex)
                    evidence_msg_by_id = {}

            facts = []
            for row in rows:
                fact_msg_ids = evidence_ids_by_fact.get(int(row["id"]), [])
                fact_evidence_msgs = [
                    evidence_msg_by_id[i]
                    for i in fact_msg_ids
                    if i in evidence_msg_by_id
                ]
                fact_evidence_msgs.sort(key=lambda m: (m.get("timestamp") or 0, m.get("id") or 0))

                facts.append(
                    {
                        "id": row["id"],
                        "subject": row["subject"],
                        "kind": row["kind"],
                        "content": row["content"],
                        "as_of": row["as_of"],
                        "confidence": row["confidence"],
                        "sensitive": str(row["sensitivity"] or "normal") == "sensitive",
                        "enabled": bool(row["enabled"]),
                        "user_action": feedback.get(int(row["id"])),
                        "evidence_messages": fact_evidence_msgs,
                        "evidence_excerpts": [m["text"] for m in fact_evidence_msgs],
                    }
                )
            return {
                "ok": True,
                "conversation_id": int(conversation_id),
                "resolved_account_wxid": resolved_account,
                "contact_avatar": contact_avatar,
                "user_avatar": user_avatar,
                "raw_fact_count": raw_fact_count,
                "fact_count": int(count_row["fact_count"]),
                "enabled_fact_count": int(count_row["enabled_fact_count"]),
                "selected_fact_count": (
                    int(count_row["fact_count"])
                    if enabled is None else (
                        int(count_row["enabled_fact_count"])
                        if enabled else int(count_row["fact_count"]) - int(count_row["enabled_fact_count"])
                    )
                ),
                "offset": page_offset,
                "limit": page_limit,
                "total": len(facts),
                "disabled_count": sum(1 for f in facts if not f["enabled"]),
                "document_count": int(
                    (
                        conn.execute(
                            """
                            SELECT document_count FROM rag_index_status
                            WHERE account_wxid = ? AND conversation_id = ?
                            """,
                            (resolved_account, int(conversation_id)),
                        ).fetchone()
                        or {"document_count": 0}
                    )["document_count"]
                    or 0
                ),
                "kinds": [
                    {"kind": row["kind"], "count": int(row["n"])}
                    for row in conn.execute(
                        """
                        SELECT kind, COUNT(*) AS n FROM rag_facts
                        WHERE account_wxid = ? AND conversation_id = ? AND status = 'active'
                        GROUP BY kind ORDER BY n DESC
                        """,
                        (resolved_account, int(conversation_id)),
                    ).fetchall()
                ],
                "facts": facts,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取联系人记忆列表失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_fact_feedback(
        self, fact_id: int, action: str, reason: str = ""
    ) -> dict[str, Any]:
        """Apply user correction to one memory fact: inaccurate / forget / restore."""
        try:
            from ..db.connection import get_db
            from ..services.realtime.rag.store import RagStore

            conn = get_db()
            store = RagStore(conn)
            action = str(action or "").strip()
            if action == "restore":
                result = store.restore_fact(int(fact_id))
            else:
                result = store.set_fact_user_feedback(int(fact_id), action, reason or "")
            store.conn.commit()
            # 用户纠错后刷新关系策略影子：剔除已禁用事实的 evidence 引用
            # （P2.1 闭环；刷新受 shadow 开关保护，失败绝不阻塞反馈）
            if result.get("ok"):
                try:
                    from ..services.realtime.rag.relationship_policy import (
                        refresh_after_fact_feedback,
                    )

                    normalized = "restore" if action == "restore" else action
                    refresh_result = refresh_after_fact_feedback(
                        store, int(fact_id), action=normalized
                    )
                    store.conn.commit()
                    logger.debug(
                        "[Bridge] 记忆反馈后策略刷新 fact=%s result=%s",
                        fact_id,
                        refresh_result,
                    )
                except Exception as refresh_exc:
                    logger.warning(
                        "[Bridge] 记忆反馈后关系策略刷新失败（不影响反馈）: %s", refresh_exc
                    )
            return result
        except Exception as e:
            logger.error(f"[Bridge] 记忆反馈失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_rag_status(self, account_wxid: str = "", limit: int = 1000) -> dict[str, Any]:
        """Return per-contact RAG status summary for the settings page."""
        try:
            from ..db.connection import get_db
            from ..services.realtime.rag.store import RagStore
            from ..services.wechat.contact_filters import is_excluded_contact_username

            resolved_account = self._resolve_account_wxid(account_wxid)
            conn = get_db()
            RagStore(conn)

            # 检查表和列结构，确保兼容测试环境的精简 schema
            has_contacts_table = False
            conv_cols = set()
            ct_cols = set()
            try:
                table_check = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='contacts'"
                ).fetchone()
                has_contacts_table = bool(table_check)
                conv_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
                if has_contacts_table:
                    ct_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
            except Exception:
                pass

            c_avatar_expr = "NULLIF(TRIM(c.avatar_path), '')" if "avatar_path" in conv_cols else "NULL"
            ct_avatar_expr = "NULLIF(TRIM(ct.avatar_path), '')" if "avatar_path" in ct_cols else "NULL"
            c_display_expr = "NULLIF(TRIM(c.display_name), '')" if "display_name" in conv_cols else "NULL"
            ct_remark_expr = "NULLIF(TRIM(ct.remark), '')" if "remark" in ct_cols else "NULL"
            ct_nickname_expr = "NULLIF(TRIM(ct.nickname), '')" if "nickname" in ct_cols else "NULL"

            if has_contacts_table:
                query = f"""
                SELECT
                    c.id AS conversation_id,
                    COALESCE(
                        {ct_remark_expr},
                        {ct_nickname_expr},
                        {c_display_expr},
                        NULLIF(TRIM(c.username), ''),
                        '未知联系人'
                    ) AS display_name,
                    c.username,
                    COALESCE(
                        {c_avatar_expr},
                        {ct_avatar_expr}
                    ) AS avatar,
                    COALESCE(s.status, 'pending') AS status,
                    COALESCE(s.document_count, 0) AS document_count,
                    COALESCE(s.vector_count, 0) AS vector_count,
                    s.last_indexed_at,
                    s.last_error,
                    COALESCE(s.storage_bytes, 0) AS storage_bytes,
                    COALESCE(s.enabled, 1) AS enabled,
                    COALESCE(s.fact_read_mode, 'inherit') AS fact_read_mode,
                    c.updated_at
                FROM conversations c
                LEFT JOIN contacts ct
                  ON ct.account_wxid = c.account_wxid AND ct.username = c.username
                LEFT JOIN rag_index_status s
                  ON s.account_wxid = c.account_wxid AND s.conversation_id = c.id
                WHERE c.account_wxid = ? AND c.is_deleted = 0
                ORDER BY c.updated_at DESC
                LIMIT ?
                """
            else:
                query = f"""
                SELECT
                    c.id AS conversation_id,
                    COALESCE({c_display_expr}, NULLIF(TRIM(c.username), ''), '未知联系人') AS display_name,
                    c.username,
                    {c_avatar_expr} AS avatar,
                    COALESCE(s.status, 'pending') AS status,
                    COALESCE(s.document_count, 0) AS document_count,
                    COALESCE(s.vector_count, 0) AS vector_count,
                    s.last_indexed_at,
                    s.last_error,
                    COALESCE(s.storage_bytes, 0) AS storage_bytes,
                    COALESCE(s.enabled, 1) AS enabled,
                    COALESCE(s.fact_read_mode, 'inherit') AS fact_read_mode,
                    c.updated_at
                FROM conversations c
                LEFT JOIN rag_index_status s
                  ON s.account_wxid = c.account_wxid AND s.conversation_id = c.id
                WHERE c.account_wxid = ? AND c.is_deleted = 0
                ORDER BY c.updated_at DESC
                LIMIT ?
                """

            rows = conn.execute(query, (resolved_account, max(1, int(limit)))).fetchall()
            from ..services.realtime.rag.indexer import get_active_and_queued
            live_states = get_active_and_queued()
            items = []
            for row in rows:
                item = dict(row)
                if is_excluded_contact_username(item.get("username")):
                    continue
                live = live_states.get((resolved_account, int(item.get("conversation_id") or 0)))
                if live:
                    # 后台真值优先：构建中/排队中（DB status 在此期间不更新）
                    item["status"] = live
                items.append(item)
            return {
                "ok": True,
                "has_live": bool(live_states),
                "settings": {
                    key: self.settings.get(key)
                    for key in (
                        "rag_enabled",
                        "rag_remote_context_redaction",
                        "rag_allow_remote_embedding",
                        "rag_embedding_model",
                        "rag_embedding_dim",
                        "rag_privacy_mode",
                        "rag_fact_shadow_enabled",
                        "rag_fact_read_enabled",
                        "rag_fact_score_threshold",
                    )
                },
                "items": items,
                "total_documents": sum(int(item.get("document_count") or 0) for item in items),
                "total_storage_bytes": sum(int(item.get("storage_bytes") or 0) for item in items),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取 RAG 状态失败: {e}")
            return {"ok": False, "error": str(e), "items": []}

    def rebuild_rag_index(self, conversation_id: int, account_wxid: str = "") -> dict[str, Any]:
        """Rebuild one contact RAG index (always async via the single-worker queue).

        原实现锁空闲时在端点内联同步重建（阻塞分钟级且 UI 无构建中真值），
        现统一入队：状态经 get_rag_status 的 building/queued 覆盖可查。
        """
        try:
            from ..services.realtime.rag.config import load_rag_settings
            from ..services.realtime.rag.indexer import RagIndexQueue, get_active_and_queued

            resolved_account = self._resolve_account_wxid(account_wxid)
            if not load_rag_settings().get("rag_enabled"):
                # 主开关关闭时队列 worker 会丢弃任务——保持旧行为内联同步重建
                from ..services.realtime.rag.indexer import RagIndexer
                status = RagIndexer().rebuild_contact_index(
                    account_wxid=resolved_account,
                    conversation_id=int(conversation_id),
                )
                failed = str((status or {}).get("status") or "") == "failed"
                return {
                    "ok": not failed,
                    "status": status,
                    "error": (status or {}).get("last_error") if failed else None,
                }
            key = (resolved_account, int(conversation_id))
            live = get_active_and_queued().get(key)
            if live:
                return {
                    "ok": True,
                    "queued": True,
                    "already": True,
                    "state": live,
                    "message": "该联系人正在构建索引，无需重复发起" if live == "building"
                    else "该联系人已在索引队列中",
                }
            RagIndexQueue.enqueue(resolved_account, int(conversation_id))
            return {
                "ok": True,
                "queued": True,
                "state": "queued",
                "message": "已加入索引队列（单 worker 串行执行）",
            }
        except Exception as e:
            logger.error(f"[Bridge] 重建 RAG 索引失败: {e}")
            return {"ok": False, "error": str(e)}

    def clear_rag_index(self, conversation_id: int, account_wxid: str = "") -> dict[str, Any]:
        """Clear one contact RAG data without touching original messages."""
        try:
            from ..services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            store = RagStore()
            deleted = store.clear_conversation(resolved_account, int(conversation_id))
            store.conn.commit()
            return {"ok": True, "deleted": deleted}
        except Exception as e:
            logger.error(f"[Bridge] 清空 RAG 索引失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_rag_conversation_enabled(
        self,
        conversation_id: int,
        enabled: bool,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Enable or disable one contact's RAG candidates."""
        try:
            from ..services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            store = RagStore()
            store.set_conversation_enabled(resolved_account, int(conversation_id), bool(enabled))
            store.conn.commit()
            return {"ok": True, "enabled": bool(enabled)}
        except Exception as e:
            logger.error(f"[Bridge] 更新联系人 RAG 启用状态失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_rag_fact_read_mode(
        self,
        conversation_id: int,
        mode: str,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Switch one contact between fact-first and document rollback reads."""
        try:
            from ..services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            normalized_mode = str(mode or "").strip().lower()
            store = RagStore()
            store.set_fact_read_mode(resolved_account, int(conversation_id), normalized_mode)
            store.conn.commit()
            return {"ok": True, "fact_read_mode": normalized_mode}
        except Exception as e:
            logger.error(f"[Bridge] 更新联系人事实读侧模式失败: {e}")
            return {"ok": False, "error": str(e)}
    
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
            )
            
            # 只在消息数量变化时打印（避免每 3 秒重复刷屏）
            count = len(messages) if messages else 0
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

            # 确保表存在
            conn.execute('''
                CREATE TABLE IF NOT EXISTS realtime_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_wxid TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    severity TEXT DEFAULT 'medium',
                    summary TEXT NOT NULL,
                    speeches TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'pending',
                    engine_type TEXT DEFAULT 'llm',
                    trigger_context TEXT,
                    created_at INTEGER NOT NULL,
                    read_at INTEGER,
                    dismissed_at INTEGER,
                    reply TEXT,
                    thought_process TEXT
                    )
                ''')
            try:
                conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN reply TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN thought_process TEXT")
            except:
                pass

            # 查询 pending 状态的建议
            cursor = conn.execute('''
                SELECT id, trigger_type, intent, severity, summary, speeches,
                       confidence, engine_type, trigger_context, status, created_at, reply, thought_process
                FROM realtime_suggestions
                WHERE account_wxid = ? AND batch_id = ? AND status = 'pending'
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
            from ..services.realtime.providers.factory import (
                DEFAULT_LISTENER_BACKEND,
                normalize_listener_backend,
            )

            return {
                "ok": True, 
                "config": {
                    "trigger_mode": self.settings.get("trigger_mode", "semi_auto"),
                    "intent": self.settings.get("intent", "maintain"),
                    "auto_rate_limit": int(self.settings.get("auto_rate_limit", 10)),
                    "engine_type": "llm",
                    "listener_backend": normalize_listener_backend(
                        self.settings.get("listener_backend", DEFAULT_LISTENER_BACKEND)
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

    # ==================== LLM 模型管理 ====================

    def get_llm_models(self) -> dict[str, Any]:
        """获取所有已配置的 LLM 模型列表"""
        try:
            from ..db.connection import get_db

            conn = get_db()

            # 确保表存在
            conn.execute('''
                CREATE TABLE IF NOT EXISTS llm_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    api_base_url TEXT NOT NULL,
                    api_key TEXT,
                    is_active INTEGER DEFAULT 0,
                    max_tokens INTEGER DEFAULT 512,
                    temperature REAL DEFAULT 0.7,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            ''')

            cursor = conn.execute(
                'SELECT id, name, provider, model_id, api_base_url, '
                'api_key, is_active, max_tokens, temperature, '
                'created_at, updated_at FROM llm_models ORDER BY is_active DESC, updated_at DESC'
            )

            models = []
            for row in cursor.fetchall():
                m = dict(row)
                # API Key 脱敏展示：只显示前4和后4个字符
                key = m.get('api_key') or ''
                if len(key) > 10:
                    m['api_key_masked'] = f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"
                elif key:
                    m['api_key_masked'] = '****'
                else:
                    m['api_key_masked'] = ''
                models.append(m)

            return {"ok": True, "models": models}
        except Exception as e:
            logger.error(f"[Bridge] 获取模型列表失败: {e}")
            return {"ok": False, "error": str(e), "models": []}

    def save_llm_model(self, model: dict[str, Any]) -> dict[str, Any]:
        """
        新增或更新 LLM 模型配置

        Args:
            model: {
                "id": int (可选，有则更新),
                "name": str,
                "provider": str,
                "model_id": str,
                "api_base_url": str,
                "api_key": str (可选),
                "is_active": bool,
                "max_tokens": int (legacy/internal, optional),
                "temperature": float
            }
        """
        try:
            import time as _time
            from ..db.connection import get_db

            conn = get_db()
            now = int(_time.time())

            model_id = model.get('id')
            legacy_max_tokens = model.get('max_tokens')
            if legacy_max_tokens is None and model_id is not None:
                existing = conn.execute(
                    'SELECT max_tokens FROM llm_models WHERE id = ?',
                    (model_id,),
                ).fetchone()
                legacy_max_tokens = existing['max_tokens'] if existing else 512
            if legacy_max_tokens is None:
                legacy_max_tokens = 512

            # 如果设为激活，先把其他所有模型设为非激活
            if model.get('is_active'):
                conn.execute('UPDATE llm_models SET is_active = 0')

            if model.get('id') is not None:
                # 只更新状态，其他字段保持不变
                if len(model) == 2 and 'is_active' in model:
                    conn.execute(
                        'UPDATE llm_models SET is_active = ?, updated_at = ? WHERE id = ?',
                        (1 if model['is_active'] else 0, _time.time(), model['id'])
                    )
                else:
                    conn.execute(
                        '''UPDATE llm_models SET name = ?, provider = ?, model_id = ?, 
                           api_base_url = ?, api_key = ?, is_active = ?, max_tokens = ?, 
                           temperature = ?, updated_at = ? WHERE id = ?''',
                        (model.get('name', ''), model.get('provider', ''), model.get('model_id', ''),
                         model.get('api_base_url', ''), model.get('api_key', ''), 1 if model.get('is_active') else 0,
                         legacy_max_tokens, model.get('temperature', 0.7), _time.time(), model['id'])
                    )
            else:
                conn.execute(
                    '''INSERT INTO llm_models (name, provider, model_id, api_base_url, 
                       api_key, is_active, max_tokens, temperature, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (model.get('name', ''), model.get('provider', ''), model.get('model_id', ''),
                     model.get('api_base_url', ''), model.get('api_key', ''), 1 if model.get('is_active') else 0,
                     legacy_max_tokens, model.get('temperature', 0.7), _time.time(), _time.time())
                )

            conn.commit()

            # 如果激活了 LLM 模型，同步更新建议引擎类型
            if model.get('is_active'):
                try:
                    from ..services.realtime.monitor_service import RealtimeMonitorService
                    monitor = RealtimeMonitorService()
                    monitor.set_suggestion_config({'engine_type': 'llm'})
                except Exception:
                    pass

            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 保存模型配置失败: {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def delete_llm_model(self, model_id: int) -> dict[str, Any]:
        """删除 LLM 模型配置"""
        try:
            from ..db.connection import get_db

            conn = get_db()
            conn.execute('DELETE FROM llm_models WHERE id = ?', (model_id,))
            conn.commit()

            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 删除模型失败: {e}")
            return {"ok": False, "error": str(e)}

    def fetch_provider_models(self, base_url: str, api_key: str = "") -> dict[str, Any]:
        """查询厂商 API 可用的模型列表（通过 GET /models 端点）
        
        Args:
            base_url: API 基址址 (e.g. https://api.deepseek.com/v1)
            api_key: API 密钥
            
        Returns:
            {"ok": True, "models": ["deepseek-chat", "deepseek-reasoner", ...]}
        """
        try:
            from ..services.realtime.llm_engine import LLMSuggestionEngine
            engine = LLMSuggestionEngine()
            model_ids = engine._fetch_available_models(base_url, api_key)
            if model_ids is not None:
                return {"ok": True, "models": model_ids}
            else:
                return {"ok": False, "error": "无法查询可用模型，请检查 API 地址和密钥", "models": []}
        except Exception as e:
            logger.error(f"[Bridge] 查询厂商模型失败: {e}")
            return {"ok": False, "error": str(e), "models": []}

    def get_contact_profile(self, display_name: str, account_wxid: str = "") -> dict[str, Any]:
        """
        获取联系人画像（查缓存）

        Returns:
            {
                "ok": True,
                "has_profile": True/False,
                "expired": True/False,
                "profile": {...} or None,
                "estimated_tokens": int,  # 生成所需预估 token
            }
        """
        try:
            from ..services.realtime.contact_profiler import ContactProfiler
            profiler = ContactProfiler()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cached = profiler.get_profile(display_name, resolved_account_wxid)
            estimate = profiler.estimate_tokens(display_name, account_wxid=resolved_account_wxid)

            if cached:
                return {
                    'ok': True,
                    'has_profile': True,
                    'expired': cached['expired'],
                    'profile': cached['profile'],
                    'created_at': cached['created_at'],
                    'expires_at': cached['expires_at'],
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
            else:
                return {
                    'ok': True,
                    'has_profile': False,
                    'expired': False,
                    'profile': None,
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
        except Exception as e:
            logger.error(f"[Bridge] 获取联系人画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def generate_contact_profile(
        self,
        display_name: str,
        budget_level: str = 'medium',
        custom_budget: int = 0,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """
        生成联系人画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: token 预算档位 (low/medium/high/custom)
            custom_budget: 自定义 token 预算

        Returns:
            {"ok": True, "profile": {...}} 或 {"ok": False, "error": "..."}
        """
        try:
            from ..services.realtime.contact_profiler import ContactProfiler
            profiler = ContactProfiler()
            result = profiler.generate_profile(
                display_name,
                budget_level,
                custom_budget,
                self._resolve_account_wxid(account_wxid),
            )
            return result
        except Exception as e:
            logger.error(f"[Bridge] 生成联系人画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def get_self_profile(self, display_name: str, account_wxid: str = "") -> dict[str, Any]:
        """获取用户本人的专属克隆画像缓存"""
        try:
            from ..services.realtime.self_profiler import SelfProfiler
            profiler = SelfProfiler()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cached = profiler.get_profile(display_name, resolved_account_wxid)
            estimate = profiler.estimate_tokens(display_name, account_wxid=resolved_account_wxid)

            if cached:
                return {
                    'ok': True,
                    'has_profile': True,
                    'expired': cached['expired'],
                    'profile': cached['profile'],
                    'created_at': cached['created_at'],
                    'expires_at': cached['expires_at'],
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
            else:
                return {
                    'ok': True,
                    'has_profile': False,
                    'expired': False,
                    'profile': None,
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
        except Exception as e:
            logger.error(f"[Bridge] 获取本体克隆画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def generate_self_profile(
        self,
        display_name: str,
        budget_level: str = 'medium',
        custom_budget: int = 0,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """生成用户本体的聊天克隆画像"""
        try:
            from ..services.realtime.self_profiler import SelfProfiler
            profiler = SelfProfiler()
            result = profiler.generate_profile(
                display_name,
                budget_level,
                custom_budget,
                self._resolve_account_wxid(account_wxid),
            )
            return result
        except Exception as e:
            logger.error(f"[Bridge] 生成本体画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

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

    def get_sessions(self, conversation_id: int, limit: int = 50, offset: int = 0) -> dict:
        """
        获取会话列表

        Args:
            conversation_id: 对话ID
            limit: 返回数量限制
            offset: 分页偏移量

        Returns:
            {
                "success": True,
                "data": {
                    "sessions": [...],
                    "total": 150,
                    "limit": 50,
                    "offset": 0
                }
            }
        """
        try:
            from ..db.connection import get_db

            db = get_db()

            # 查询总数
            count_cursor = db.execute(
                "SELECT COUNT(*) as total FROM sessions WHERE conversation_id = ?",
                (conversation_id,)
            )
            total = count_cursor.fetchone()["total"]

            # 查询会话列表
            cursor = db.execute("""
                SELECT id, conversation_id, start_time, end_time, message_count, initiator, source
                FROM sessions
                WHERE conversation_id = ?
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
            """, (conversation_id, limit, offset))

            rows = cursor.fetchall()
            sessions = [dict(row) for row in rows]

            # 添加duration字段（分钟）
            for session in sessions:
                duration_seconds = session["end_time"] - session["start_time"]
                session["duration_minutes"] = round(duration_seconds / 60, 1)

            return {
                "success": True,
                "data": {
                    "sessions": sessions,
                    "total": total,
                    "limit": limit,
                    "offset": offset
                }
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取会话列表失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_session_messages(self, session_id: int) -> dict:
        """
        获取特定会话的消息列表
        """
        try:
            from ..db.connection import get_db
            db = get_db()
            
            # 查询会话信息以获得时间范围和conversation_id
            session_cursor = db.execute(
                "SELECT conversation_id, start_time, end_time FROM sessions WHERE id = ?",
                (session_id,)
            )
            session = session_cursor.fetchone()
            if not session:
                return {"success": False, "error": "会话不存在"}
                
            # 查询该时间范围内的消息
            cursor = db.execute("""
                SELECT id, sender, is_sender, content, timestamp as create_time
                FROM messages
                WHERE conversation_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (session["conversation_id"], session["start_time"], session["end_time"]))
            
            rows = cursor.fetchall()
            messages = []
            for row in rows:
                msg = dict(row)
                # 处理 sender_name
                is_me = msg["is_sender"] == 1
                sender_name = msg.get("sender")
                if not sender_name:
                    sender_name = "我" if is_me else "对方"
                
                messages.append({
                    "id": msg["id"],
                    "sender_name": sender_name,
                    "content": msg["content"],
                    "create_time": msg["create_time"],
                    "is_me": is_me
                })
                
            return {
                "success": True,
                "data": {
                    "messages": messages
                }
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取会话消息失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_response_times(self, conversation_id: int) -> dict:
        """
        获取响应时间统计

        Args:
            conversation_id: 对话ID

        Returns:
            {
                "success": True,
                "data": {
                    "count": 250,
                    "avg": 180.5,
                    "median": 120.0,
                    "min": 15.0,
                    "max": 3600.0,
                    "stddev": 300.2,
                    "abnormal_count": 5
                }
            }
        """
        try:
            from ..services.analysis.analysis_service import AnalysisService

            service = AnalysisService()
            stats = service.get_response_time_stats(conversation_id)

            return {
                "success": True,
                "data": stats
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取响应时间统计失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_initiative_stats(self, conversation_id: int) -> dict:
        """
        获取主动性统计

        Args:
            conversation_id: 对话ID

        Returns:
            {
                "success": True,
                "data": {
                    "total_sessions": 100,
                    "user_initiated_sessions": 55,
                    "other_initiated_sessions": 45,
                    "initiative_rate": 0.45,
                    "interpretation": "对方主动发起45%的会话，您更主动"
                }
            }
        """
        try:
            from ..db.connection import get_db

            db = get_db()

            cursor = db.execute("""
                SELECT total_sessions, user_initiated_sessions, other_initiated_sessions, initiative_rate
                FROM initiative_stats
                WHERE conversation_id = ?
            """, (conversation_id,))

            row = cursor.fetchone()

            if not row:
                return {
                    "success": True,
                    "data": {
                        "total_sessions": 0,
                        "user_initiated_sessions": 0,
                        "other_initiated_sessions": 0,
                        "initiative_rate": 0.0,
                        "interpretation": "无会话数据"
                    }
                }

            initiative_rate = row["initiative_rate"]
            if initiative_rate > 0.5:
                interpretation = f"对方主动发起{initiative_rate:.1%}的会话，对方更主动"
            elif initiative_rate < 0.5:
                interpretation = f"对方主动发起{initiative_rate:.1%}的会话，您更主动"
            else:
                interpretation = f"对方主动发起{initiative_rate:.1%}的会话，双方平衡"

            return {
                "success": True,
                "data": {
                    "total_sessions": row["total_sessions"],
                    "user_initiated_sessions": row["user_initiated_sessions"],
                    "other_initiated_sessions": row["other_initiated_sessions"],
                    "initiative_rate": initiative_rate,
                    "interpretation": interpretation
                }
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取主动性统计失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_word_counts(self, conversation_id: int, by_session: bool = False) -> dict:
        """
        获取字数统计

        Args:
            conversation_id: 对话ID
            by_session: 是否按会话分组

        Returns:
            {
                "success": True,
                "data": {
                    "overall": {
                        "user_char_count": 10000,
                        "other_char_count": 15000,
                        "char_ratio": 1.5,
                        "interpretation": "对方投入的字数是您的1.5倍"
                    },
                    "by_session": [...]
                }
            }
        """
        try:
            from ..db.connection import get_db

            db = get_db()

            # 查询整体统计
            overall_cursor = db.execute("""
                SELECT user_char_count, other_char_count, char_ratio
                FROM word_counts
                WHERE conversation_id = ? AND session_id IS NULL
            """, (conversation_id,))

            overall_row = overall_cursor.fetchone()

            if not overall_row:
                return {
                    "success": True,
                    "data": {
                        "overall": {
                            "user_char_count": 0,
                            "other_char_count": 0,
                            "char_ratio": 0,
                            "interpretation": "无字数数据"
                        },
                        "by_session": []
                    }
                }

            user_chars = overall_row["user_char_count"]
            other_chars = overall_row["other_char_count"]
            char_ratio = overall_row["char_ratio"] or 0

            if user_chars == 0 and other_chars == 0:
                interpretation = "无字数数据"
            elif char_ratio >= 1:
                interpretation = f"对方投入的字数是您的{char_ratio:.2f}倍"
            elif char_ratio > 0:
                interpretation = f"您投入的字数是对方的{1/char_ratio:.2f}倍"
            else:
                interpretation = "无对比数据"

            result = {
                "success": True,
                "data": {
                    "overall": {
                        "user_char_count": user_chars,
                        "other_char_count": other_chars,
                        "char_ratio": round(char_ratio, 2),
                        "interpretation": interpretation
                    },
                    "by_session": []
                }
            }

            # 如果需要按会话统计
            if by_session:
                session_cursor = db.execute("""
                    SELECT session_id, user_char_count, other_char_count, char_ratio
                    FROM word_counts
                    WHERE conversation_id = ? AND session_id IS NOT NULL
                    ORDER BY session_id ASC
                """, (conversation_id,))

                session_rows = session_cursor.fetchall()
                result["data"]["by_session"] = [
                    {
                        "session_id": row["session_id"],
                            "word_count": {
                                "user_char_count": row["user_char_count"],
                                "other_char_count": row["other_char_count"],
                                "char_ratio": round(row["char_ratio"] or 0, 2)
                            }
                        }
                    for row in session_rows
                ]

            return result
        except Exception as e:
            logger.error(f"[Bridge] 获取字数统计失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_activity_calendar(self, conversation_id: int, year: Optional[int] = None) -> dict:
        """
        获取互动活跃日历数据。
        """
        try:
            from ..services.analysis.analysis_service import AnalysisService

            service = AnalysisService()
            data = service.get_activity_calendar(conversation_id, year)

            return {
                "success": True,
                "data": data
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取活跃日历失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def reanalyze(self, conversation_id: int) -> dict:
        """
        重新分析对话（删除旧数据+重新提取特征）

        Args:
            conversation_id: 对话ID

        Returns:
            {
                "success": True,
                "data": {
                    "task_id": "extract_42_xxx",
                    "status": "started",
                    "message": "Re-analysis started"
                }
            }
        """
        try:
            logger.debug(f"[Bridge] 重新分析: conversation_id={conversation_id}")

            service = self._get_feature_service()

            # 删除旧数据
            service.delete_analysis_data(conversation_id)

            # 重新提取
            result = service.extract_features(conversation_id)

            return {
                "success": True,
                "data": {
                    "task_id": result["task_id"],
                    "status": "completed",
                    "message": "Re-analysis completed"
                }
            }
        except Exception as e:
            import traceback
            logger.error(f"[Bridge] 重新分析失败: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    # ==================== 悬浮窗管理 ====================

    def set_close_actions(self, minimize=None, exit=None) -> None:
        """由 close_guard 装配关闭确认动作（见 webview/close_guard.py）。"""
        self._close_actions = {"minimize": minimize, "exit": exit}

    def perform_close_action(self, action: str) -> dict[str, Any]:
        """执行关闭按钮选择（前端关闭确认对话框调用）。

        action: "minimize"（最小化到任务栏）| "exit"（退出应用）
        """
        action = str(action or "").strip().lower()
        fn = self._close_actions.get(action)
        if fn is None:
            return {"ok": False, "error": f"未知关闭动作: {action or '(空)'}"}
        try:
            fn()
            return {"ok": True, "action": action}
        except Exception as e:
            logger.error(f"[Bridge] 关闭动作执行失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_webview_window(self, window):
        """设置 PyWebView 窗口引用（由 app_dev.py 启动后注入）"""
        self._webview_window = window
        self._floating_service.set_webview_window(window)

    def enter_floating_mode(self) -> dict[str, Any]:
        """
        进入悬浮窗模式：窗口变为紧凑悬浮面板，跟随微信窗口

        Returns:
            {"ok": True, "message": "...", "wechat_found": True/False}
        """
        try:
            return self._floating_service.enter_floating_mode()
        except Exception as e:
            logger.error(f"[Bridge] 进入悬浮模式失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def exit_floating_mode(self) -> dict[str, Any]:
        """
        退出悬浮窗模式：恢复原始窗口尺寸和位置

        Returns:
            {"ok": True, "message": "..."}
        """
        try:
            return self._floating_service.exit_floating_mode()
        except Exception as e:
            logger.error(f"[Bridge] 退出悬浮模式失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def get_floating_status(self) -> dict[str, Any]:
        """
        获取悬浮窗状态

        Returns:
            {"ok": True, "is_floating": bool, "wechat_found": bool}
        """
        try:
            return self._floating_service.get_status()
        except Exception as e:
            logger.error(f"[Bridge] 获取悬浮状态失败: {e}")
            return {'ok': False, 'error': str(e)}

    def set_floating_expanded(self, expanded: bool) -> dict[str, Any]:
        """
        动态切换悬浮窗展开态。

        expanded=True: 展开辅助栏所需宽度
        expanded=False: 恢复紧凑宽度
        """
        try:
            return self._floating_service.set_expanded(expanded)
        except Exception as e:
            logger.error(f"[Bridge] 切换悬浮窗展开态失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def check_gpu_status(self) -> dict[str, Any]:
        """检测 GPU 加速可用性。"""
        try:
            import torch
            from ..services.gpu.gpu_installer import GpuInstallerService
            from ..runtime_overrides import get_build_variant, get_gpu_install_state, has_gpu_overlay

            overlay_state = get_gpu_install_state()
            overlay_installed = has_gpu_overlay()
            current_cuda_version = torch.version.cuda
            build_variant = get_build_variant()
            overlay_restart_required = bool(
                build_variant != "dev"
                and overlay_installed
                and (
                    str(torch.__version__) != str(overlay_state.get("torch_version") or "")
                    or str(current_cuda_version or "") != str(overlay_state.get("cuda_version") or "")
                )
            )

            result = {
                "ok": True,
                "cuda_available": torch.cuda.is_available(),
                "has_nvidia_gpu": GpuInstallerService.has_nvidia_gpu(),
                "gpu_name": None,
                "torch_version": torch.__version__,
                "cuda_version": current_cuda_version,
                "gpu_memory_total_mb": 0,
                "gpu_memory_free_mb": 0,
                "build_variant": build_variant,
                "gpu_overlay_installed": overlay_installed,
                "gpu_overlay_torch_version": overlay_state.get("torch_version"),
                "gpu_overlay_cuda_version": overlay_state.get("cuda_version"),
                "restart_required": overlay_restart_required,
            }

            if result["cuda_available"]:
                result["gpu_name"] = torch.cuda.get_device_name(0)

                mem_total = torch.cuda.get_device_properties(0).total_memory
                try:
                    mem_free, mem_total_runtime = torch.cuda.mem_get_info(0)
                    result["gpu_memory_total_mb"] = int(mem_total_runtime / 1024 / 1024)
                    result["gpu_memory_free_mb"] = int(mem_free / 1024 / 1024)
                except Exception:
                    mem_free = mem_total - torch.cuda.memory_allocated(0)
                    result["gpu_memory_total_mb"] = int(mem_total / 1024 / 1024)
                    result["gpu_memory_free_mb"] = int(mem_free / 1024 / 1024)

            return result

        except Exception as e:
            logger.error(f"[Bridge] GPU 检测失败: {e}")
            from ..services.gpu.gpu_installer import GpuInstallerService
            from ..runtime_overrides import get_build_variant, get_gpu_install_state, has_gpu_overlay

            overlay_state = get_gpu_install_state()
            build_variant = get_build_variant()
            return {
                "ok": False,
                "cuda_available": False,
                "has_nvidia_gpu": getattr(GpuInstallerService, "has_nvidia_gpu", lambda: False)(),
                "gpu_name": None,
                "torch_version": "unknown",
                "cuda_version": None,
                "gpu_memory_total_mb": 0,
                "gpu_memory_free_mb": 0,
                "build_variant": build_variant,
                "gpu_overlay_installed": has_gpu_overlay(),
                "gpu_overlay_torch_version": overlay_state.get("torch_version"),
                "gpu_overlay_cuda_version": overlay_state.get("cuda_version"),
                "restart_required": bool(build_variant != "dev" and has_gpu_overlay()),
                "error": str(e)
            }

    def start_gpu_install(self) -> dict[str, Any]:
        """开始异步安装 GPU 环境"""
        try:
            from ..services.gpu.gpu_installer import GpuInstallerService
            service = GpuInstallerService()
            return service.start_install()
        except Exception as e:
            logger.error(f"[Bridge] 开始安装 GPU 环境失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_gpu_install_progress(self) -> dict[str, Any]:
        """获取 GPU 环境安装进度"""
        try:
            from ..services.gpu.gpu_installer import GpuInstallerService
            service = GpuInstallerService()
            return service.get_progress()
        except Exception as e:
            logger.error(f"[Bridge] 获取 GPU 环境安装进度失败: {e}")
            return {"ok": False, "error": str(e)}

    # ==================== 好感度分析相关 ====================

    # -- 关系上下文 --

    def check_analysis_model_status(self) -> dict[str, Any]:
        """Check whether analysis models are available locally with detailed diagnosis."""
        try:
            sentiment_manager = self._get_sentiment_model_manager()
            sentiment_diagnosis = sentiment_manager.diagnose_model_status()
            embedding_diagnosis = self._diagnose_embedding_model_status()

            sentiment_model_ready = not sentiment_diagnosis["issue"]
            embedding_model_ready = not embedding_diagnosis["issue"]

            missing_models = []
            missing_details = []

            if not sentiment_model_ready:
                missing_models.append("sentiment")
                missing_details.append({
                    "model_name": "情感分类模型",
                    "model_key": "sentiment",
                    "repo_id": sentiment_diagnosis.get("repo_id"),
                    "issue": sentiment_diagnosis.get("issue") or "情感分类模型不可用",
                    "can_auto_download": True,
                })

            if not embedding_model_ready:
                missing_models.append("embedding")
                missing_details.append({
                    "model_name": "文本向量模型",
                    "model_key": "embedding",
                    "repo_id": embedding_diagnosis.get("repo_id"),
                    "issue": embedding_diagnosis.get("issue") or "文本向量模型不可用",
                    "can_auto_download": embedding_diagnosis.get("can_recover", True),
                })

            return {
                "ok": True,
                "analysis_available": sentiment_model_ready and embedding_model_ready,
                "sentiment_model_ready": sentiment_model_ready,
                "embedding_model_ready": embedding_model_ready,
                "missing_models": missing_models,
                "missing_details": missing_details,
                "sentiment_diagnosis": sentiment_diagnosis,
                "embedding_diagnosis": embedding_diagnosis,
                "error": None,
                "error_code": None,
                "error_detail": None,
            }
        except Exception as e:
            logger.error(f"[Bridge] 分析模型状态检查失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "analysis_available": False,
                "sentiment_model_ready": False,
                "embedding_model_ready": False,
                "missing_models": ["sentiment", "embedding"],
                "missing_details": [],
                "sentiment_diagnosis": {},
                "embedding_diagnosis": {},
                "error": str(e),
                "error_code": "UNKNOWN_ERROR",
                "error_detail": f"模型状态检查过程中发生异常: {type(e).__name__}: {e}",
            }

    def download_analysis_models(self) -> dict[str, Any]:
        """Start downloading all missing analysis models in the background."""
        try:
            model_status = self.check_analysis_model_status()
            if not model_status.get("ok"):
                return {
                    "ok": False,
                    "error": model_status.get("error") or "模型状态检查失败",
                    "error_code": model_status.get("error_code") or "UNKNOWN_ERROR",
                    "error_detail": model_status.get("error_detail") or "无法启动模型下载",
                }

            models_to_download = model_status.get("missing_models", [])
            if not models_to_download:
                return {
                    "ok": True,
                    "task_id": None,
                    "models_to_download": [],
                    "status": "completed",
                }

            # 加 uuid 后缀防撞号：同秒内重复点击下载时按秒生成的 task_id 会互相覆盖
            task_id = f"analysis_model_download_{int(time.time())}_{uuid.uuid4().hex[:8]}"
            self._update_model_download_status(
                task_id,
                status="downloading",
                overall_progress=0.0,
                current_model=models_to_download[0],
                current_step="等待开始下载...",
                completed_models=[],
                failed_models=[],
                error=None,
                error_code=None,
                error_detail=None,
                models_to_download=models_to_download,
            )

            def _run():
                completed_models = []
                failed_models = []
                total_models = len(models_to_download)

                try:
                    for index, model_key in enumerate(models_to_download):
                        base_progress = (index / total_models) * 100.0
                        span = 100.0 / total_models

                        def _progress(step: str, percent: float):
                            overall = base_progress + span * (max(0.0, min(100.0, float(percent))) / 100.0)
                            self._update_model_download_status(
                                task_id,
                                status="downloading",
                                overall_progress=overall,
                                current_model=model_key,
                                current_step=step,
                                completed_models=completed_models.copy(),
                                failed_models=failed_models.copy(),
                            )

                        if model_key == "sentiment":
                            result = self._get_sentiment_model_manager().download_model(progress_callback=_progress)
                        else:
                            result = self._download_embedding_model(progress_callback=_progress)

                        if result.get("success"):
                            completed_models.append(model_key)
                            self._update_model_download_status(
                                task_id,
                                status="downloading",
                                overall_progress=base_progress + span,
                                current_model=model_key,
                                current_step=f"{model_key} 模型下载完成",
                                completed_models=completed_models.copy(),
                                failed_models=failed_models.copy(),
                            )
                        else:
                            failed_models.append(model_key)
                            error = result.get("error") or f"{model_key} 模型下载失败"
                            error_code = result.get("error_code") or "UNKNOWN_ERROR"
                            self._update_model_download_status(
                                task_id,
                                status="failed",
                                overall_progress=base_progress,
                                current_model=model_key,
                                current_step=f"{model_key} 模型下载失败",
                                completed_models=completed_models.copy(),
                                failed_models=failed_models.copy(),
                                error=error,
                                error_code=error_code,
                                error_detail=error,
                            )
                            return

                    self._update_model_download_status(
                        task_id,
                        status="completed",
                        overall_progress=100.0,
                        current_model=models_to_download[-1],
                        current_step="缺失模型下载完成",
                        completed_models=completed_models.copy(),
                        failed_models=failed_models.copy(),
                        error=None,
                        error_code=None,
                        error_detail=None,
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 模型下载任务失败: {type(e).__name__}: {e}", exc_info=True)
                    current_status = self._get_model_download_status(task_id)
                    self._update_model_download_status(
                        task_id,
                        status="failed",
                        overall_progress=current_status.get("overall_progress", 0.0),
                        current_model=current_status.get("current_model"),
                        current_step="模型下载失败",
                        completed_models=completed_models.copy(),
                        failed_models=failed_models.copy(),
                        error=str(e),
                        error_code="UNKNOWN_ERROR",
                        error_detail=f"{type(e).__name__}: {e}",
                    )

            threading.Thread(target=_run, name=f"AnalysisModelDownload-{task_id}", daemon=True).start()

            return {
                "ok": True,
                "task_id": task_id,
                "models_to_download": models_to_download,
            }
        except Exception as e:
            logger.error(f"[Bridge] 启动模型下载失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "error": str(e),
                "error_code": "UNKNOWN_ERROR",
                "error_detail": f"{type(e).__name__}: {e}",
            }

    def get_model_download_progress(self, task_id: str) -> dict[str, Any]:
        """Query analysis model download progress."""
        try:
            status = self._get_model_download_status(task_id)
            if not status:
                return {
                    "ok": False,
                    "status": "not_found",
                    "overall_progress": 0.0,
                    "current_model": None,
                    "current_step": "",
                    "completed_models": [],
                    "failed_models": [],
                    "error": "下载任务不存在",
                    "error_code": "TASK_NOT_FOUND",
                    "error_detail": "未找到对应的模型下载任务",
                }

            return {
                "ok": True,
                "status": status.get("status", "downloading"),
                "overall_progress": status.get("overall_progress", 0.0),
                "current_model": status.get("current_model"),
                "current_step": status.get("current_step", ""),
                "completed_models": status.get("completed_models", []),
                "failed_models": status.get("failed_models", []),
                "error": status.get("error"),
                "error_code": status.get("error_code"),
                "error_detail": status.get("error_detail"),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取模型下载进度失败: {type(e).__name__}: {e}", exc_info=True)
            return {
                "ok": False,
                "status": "failed",
                "overall_progress": 0.0,
                "current_model": None,
                "current_step": "",
                "completed_models": [],
                "failed_models": [],
                "error": str(e),
                "error_code": "UNKNOWN_ERROR",
                "error_detail": f"{type(e).__name__}: {e}",
            }

    def get_relationship_context(self, conversation_id: int) -> dict[str, Any]:
        """获取会话的关系上下文信息"""
        try:
            from ..services.analysis.relationship_context_service import (
                RelationshipContextService
            )
            from dataclasses import asdict

            service = RelationshipContextService()
            ctx = service.get_context(conversation_id)

            return {
                "ok": True,
                "context": asdict(ctx) if ctx else None,
                "has_context": ctx is not None,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取关系上下文失败: {e}")
            return {"ok": False, "error": str(e)}

    def save_relationship_context(
        self, conversation_id: int, context: dict
    ) -> dict[str, Any]:
        """保存会话的关系上下文信息"""
        try:
            from ..services.analysis.relationship_context_service import (
                RelationshipContextService
            )
            from dataclasses import asdict

            service = RelationshipContextService()
            ctx = service.save_context(
                conversation_id=conversation_id,
                relationship_type=context.get("relationship_type", "friend"),
                interaction_duration=context.get("interaction_duration", "1_to_6_months"),
                communication_style=context.get("communication_style", "normal"),
            )

            return {
                "ok": True,
                "context": asdict(ctx),
                "message": "关系信息已保存",
            }
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Bridge] 保存关系上下文失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_relationship_field_options(self) -> dict[str, Any]:
        """获取关系信息表单的字段选项"""
        try:
            from ..services.analysis.relationship_context_service import (
                RelationshipContextService
            )

            options = RelationshipContextService.get_field_options()
            return {"ok": True, "options": options}
        except Exception as e:
            logger.error(f"[Bridge] 获取字段选项失败: {e}")
            return {"ok": False, "error": str(e)}

    # -- 好感度配置 --

    def get_affinity_config(self, conversation_id: int) -> dict[str, Any]:
        """获取好感度分析配置 (T018)"""
        try:
            from ..services.analysis.affinity_config import AffinityConfigService
            from dataclasses import asdict
            
            service = AffinityConfigService()
            config = service.get_config(conversation_id)
            
            return {
                "ok": True,
                "config": asdict(config)
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取好感度配置失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

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

    def update_affinity_config(self, conversation_id: int, config: dict) -> dict[str, Any]:
        """更新好感度分析配置 (T019)"""
        try:
            from ..services.analysis.affinity_config import AffinityConfigService
            from dataclasses import asdict
            
            service = AffinityConfigService()
            updated_config = service.update_config(conversation_id, **config)
            
            return {
                "ok": True,
                "config": asdict(updated_config),
                "message": "配置已更新"
            }
        except ValueError as e:
            logger.error(f"[Bridge] 配置验证失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"[Bridge] 更新好感度配置失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

    def get_affinity_keywords(self) -> dict[str, Any]:
        """获取所有关键词分类 (T020)"""
        try:
            from ..services.analysis.keyword_libraries import KeywordLibraries
            
            service = KeywordLibraries()
            keywords = service.get_all_keywords()
            
            return {
                "ok": True,
                "keywords": keywords
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "keywords": {}
            }

    def add_affinity_keywords(self, category: str, keywords: list) -> dict[str, Any]:
        """添加自定义关键词 (T021)"""
        try:
            from ..services.analysis.keyword_libraries import KeywordLibraries
            
            valid_categories = ["positive", "negative", "empathy", "soothing", 
                              "privacy", "holiday", "nickname"]
            if category not in valid_categories:
                return {
                    "ok": False,
                    "error": f"无效的分类: {category}，有效值: {valid_categories}"
                }
            
            service = KeywordLibraries()
            added_count = service.add_keywords(category, keywords)
            updated_keywords = service.get_keywords(category)
            
            return {
                "ok": True,
                "added_count": added_count,
                "keywords": updated_keywords
            }
        except Exception as e:
            logger.error(f"[Bridge] 添加关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "added_count": 0
            }

    def remove_affinity_keywords(self, category: str, keywords: list) -> dict[str, Any]:
        """删除关键词 (T022)"""
        try:
            from ..services.analysis.keyword_libraries import KeywordLibraries
            
            valid_categories = ["positive", "negative", "empathy", "soothing", 
                              "privacy", "holiday", "nickname"]
            if category not in valid_categories:
                return {
                    "ok": False,
                    "error": f"无效的分类: {category}"
                }
            
            service = KeywordLibraries()
            removed_count = service.remove_keywords(category, keywords)
            updated_keywords = service.get_keywords(category)
            
            return {
                "ok": True,
                "removed_count": removed_count,
                "keywords": updated_keywords
            }
        except Exception as e:
            logger.error(f"[Bridge] 删除关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "removed_count": 0
            }

    def get_preference_keywords(self, conversation_id: int) -> dict[str, Any]:
        """获取喜好关键词 (T023)"""
        try:
            from ..services.analysis.affinity_config import AffinityConfigService
            
            service = AffinityConfigService()
            keywords = service.get_preference_keywords(conversation_id)
            
            return {
                "ok": True,
                "keywords": keywords or []
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取喜好关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "keywords": []
            }

    def update_preference_keywords(self, conversation_id: int, keywords: list) -> dict[str, Any]:
        """更新喜好关键词 (T024)"""
        try:
            from ..services.analysis.affinity_config import AffinityConfigService
            
            service = AffinityConfigService()
            updated_keywords = service.update_preference_keywords(conversation_id, keywords)
            
            return {
                "ok": True,
                "keywords": updated_keywords,
                "message": "喜好关键词已更新"
            }
        except Exception as e:
            logger.error(f"[Bridge] 更新喜好关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }


    def cancel_analysis(self) -> dict[str, Any]:
        """取消正在进行的好感度分析 / 特征提取"""
        try:
            if self._analysis_cancel_event:
                self._analysis_cancel_event.set()
                logger.info("[Bridge] 已发送取消分析信号")
                return {"ok": True, "message": "已发送取消指令"}
            return {"ok": False, "message": "当前没有正在运行的分析"}
        except Exception as e:
            logger.error(f"[Bridge] 取消分析失败: {e}")
            return {"ok": False, "error": str(e)}

    def analyze_affinity(self, conversation_id: int, force_reanalyze: bool = True, config_overrides: dict = None) -> dict[str, Any]:
        """执行好感度分析（异步，立即返回 task_id 供轮询）"""
        try:
            import threading
            import time as _time

            # 复用守卫：旧服务实例上仍有本会话的运行中任务时不重复启动。
            # 此处必须查旧实例（本方法每次 reload 出新类，新实例看不到旧任务）；
            # 重复启动会替换取消事件，导致运行中的任务再也停不掉
            prev_service = getattr(self, "_affinity_service", None)
            if prev_service is not None:
                running = prev_service.find_running_task(conversation_id)
                if running:
                    return {
                        "ok": True,
                        "task_id": running,
                        "status": "started",
                        "message": "已有进行中的好感度分析，已复用",
                    }

            AffinityAnalysisService = self._get_fresh_affinity_service_class()
            service = AffinityAnalysisService()            # 保存服务实例引用，供 get_affinity_progress 查询进度
            self._affinity_service = service
            self._analysis_cancel_event = threading.Event()
            effective_force_reanalyze = True

            # 显式生成 task_id（带 uuid 后缀防撞号）并传给 analyze()，
            # 保证返回给前端的 task_id 与服务内注册的完全一致，无需 sleep+扫描猜测
            task_id = f"affinity_{conversation_id}_{int(_time.time())}_{uuid.uuid4().hex[:6]}"
            service.register_task(task_id, conversation_id)

            def _run_analysis():
                try:
                    service.analyze(
                        conversation_id,
                        effective_force_reanalyze,
                        config_overrides,
                        cancel_event=self._analysis_cancel_event,
                        task_id=task_id,
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 异步好感度分析失败: {e}")
                    import traceback
                    traceback.print_exc()

            t = threading.Thread(target=_run_analysis, daemon=True)
            t.start()

            return {
                "ok": True,
                "task_id": task_id
            }
        except Exception as e:
            logger.error(f"[Bridge] 好感度分析启动失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "ok": False,
                "error": str(e)
            }

    def get_affinity_progress(self, task_id: str) -> dict[str, Any]:
        """
        查询好感度分析进度

        Args:
            task_id: 从 analyze_affinity 返回的任务 ID

        Returns:
            {
                "ok": True,
                "status": "running" | "completed" | "failed",
                "progress_percent": 40,
                "current_step": "计算维度评分",
                "result": {...}  // 仅当 status == "completed" 时返回完整结果
            }
        """
        try:
            from dataclasses import asdict

            service = getattr(self, '_affinity_service', None)
            if not service:
                return {
                    "ok": False,
                    "error": "分析服务未初始化",
                    "status": "failed",
                    "progress_percent": 0,
                    "current_step": ""
                }

            progress = service.get_progress(task_id)
            if not progress:
                return {
                    "ok": True,
                    "status": "pending",
                    "progress_percent": 0,
                    "current_step": "等待启动..."
                }

            response = {
                "ok": True,
                "status": progress.status,
                "progress_percent": progress.progress_percent,
                "current_step": progress.current_step
            }

            # 分析完成时，返回完整结果
            if progress.status == "completed":
                response["result"] = asdict(progress)

            # 分析失败时，返回错误信息
            if progress.status == "failed":
                response["error"] = progress.error or "未知错误"

            return response
        except Exception as e:
            logger.error(f"[Bridge] 查询好感度进度失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "status": "failed",
                "progress_percent": 0,
                "current_step": ""
            }

    def get_affinity_scores(self, conversation_id: int) -> dict[str, Any]:
        """获取好感度分析结果"""
        try:
            from dataclasses import asdict
            
            AffinityAnalysisService = self._get_fresh_affinity_service_class()
            service = AffinityAnalysisService()
            result = service.get_scores(conversation_id)
            
            return {
                "ok": True,
                "result": asdict(result) if result else None
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取好感度结果失败: {e}")
            return {
                "ok": False,
                "error": str(e)
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
