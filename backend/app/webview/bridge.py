from typing import Any, Optional
import json
import os
import logging
import importlib
import shutil
import threading
import time
import re
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
        self._load_settings()

        # 延迟加载特征提取服务（避免循环导入）
        self._feature_service = None

        # 悬浮窗管理服务
        from ..services.realtime.floating_window_service import FloatingWindowService
        self._floating_service = FloatingWindowService()
        self._model_download_status: dict[str, dict[str, Any]] = {}
        self._model_download_lock = threading.Lock()
        self._webview_window = None  # 由 app_dev.py 注入
        self._analysis_cancel_event = None  # 用于取消好感度分析

    def _load_settings(self):
        """加载设置"""
        self.settings = load_settings_from_file(self.settings_file)
        self.settings["analysis_device_mode"] = normalize_analysis_device_mode(
            self.settings.get("analysis_device_mode", ANALYSIS_DEVICE_MODE_AUTO)
        )
        self.settings[MODEL_ROOT_DIR_KEY] = normalize_model_root_dir(
            self.settings.get(MODEL_ROOT_DIR_KEY)
        )

    def _save_settings(self):
        """保存设置"""
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
        with self._model_download_lock:
            current = self._model_download_status.get(task_id, {}).copy()
            current.update(updates)
            self._model_download_status[task_id] = current

    def _get_model_download_status(self, task_id: str) -> dict[str, Any]:
        with self._model_download_lock:
            status = self._model_download_status.get(task_id)
        return status.copy() if status else {}

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

    def _build_wechat_user_candidates(self, wxid: str) -> list[str]:
        candidates: list[str] = []
        normalized = str(wxid or "").strip()
        if not normalized:
            return candidates
        candidates.append(normalized)
        match = re.match(r"^(wxid_[a-z0-9]+)_([a-z0-9]{4,6})$", normalized)
        if match:
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
                update_wechat_account_import_state(
                    self.settings,
                    resolved_wxid,
                    db_key=db_key,
                    wechat_dir=str(preferred_paths.get("wechat_dir") or "") or None,
                    source="custom" if custom_paths else None,
                )
                self._save_settings()
        return result

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
            logger.debug(f"[DEBUG Bridge] 未配置自定义路径,将使用自动检测")

        result = self.wechat_service.import_wechat_data(db_key, options, custom_paths)
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
        result = self.wechat_service.refresh_contact_avatars(db_key, preferred_paths)
        if result.get("ok") and preferred_paths:
            resolved_wxid = str(preferred_paths.get("account_wxid") or preferred_paths.get("current_user") or self._resolve_account_wxid(account_wxid))
            if resolved_wxid:
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
    # ==================== 长程对话继承 ====================
    def get_latest_thread(self, display_name: str) -> dict[str, Any]:
        """获取联系人最近的一次会话归档，用于“继续上次指导”"""
        try:
            from ..services.realtime.session_thread_service import SessionThreadService
            thread = SessionThreadService().get_latest_thread(display_name)
            if thread:
                return {"ok": True, "thread": thread}
            return {"ok": False}
        except Exception as e:
            logger.error(f"[Bridge] 获取最近线程异常: {e}")
            return {"ok": False, "error": str(e)}

    def load_thread_context(self, thread_id: int) -> dict[str, Any]:
        """加载历史线程的完整对话上下文与建议"""
        try:
            from ..services.realtime.session_thread_service import SessionThreadService
            data = SessionThreadService().load_thread_context(thread_id)
            if data:
                # 确保所有值都是 JSON 可序列化的
                safe_data = {}
                for k, v in data.items():
                    if isinstance(v, bytes):
                        safe_data[k] = v.decode('utf-8', errors='replace')
                    elif isinstance(v, (dict, list, str, int, float, bool)) or v is None:
                        safe_data[k] = v
                    else:
                        safe_data[k] = str(v)
                
                result = {"ok": True, "data": safe_data}
                # 预检序列化
                try:
                    import json as _json
                    test = _json.dumps(result, ensure_ascii=False)
                    logger.info(f"[Bridge] load_thread_context 返回成功: keys={list(safe_data.keys())}, "
                               f"suggestions={len(safe_data.get('suggestions', []))}, "
                               f"messages={len(safe_data.get('messages', []))}, "
                               f"json_size={len(test)}")
                except Exception as je:
                    logger.error(f"[Bridge] load_thread_context 序列化预检失败: {je}")
                    return {"ok": False, "error": f"序列化失败: {je}"}
                return result
            return {"ok": False, "error": "未找到上下文"}
        except Exception as e:
            logger.error(f"[Bridge] 加载线程上下文异常: {e}")
            return {"ok": False, "error": str(e)}

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

    def generate_suggestion(self, intent: str, context: dict[str, Any]) -> dict[str, Any]:
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

            logger.debug(f"[Bridge] generate_suggestion: engine_type={engine_type}, intent={intent}")

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
                        account_wxid=str(getattr(monitor, "current_account_wxid", "") or ""),
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
                account_wxid = str(getattr(monitor, "current_account_wxid", "") or self._get_active_wechat_account_wxid() or "")
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
                    from ..services.realtime.suggestion_observer import (
                        EVENT_SHOWN,
                        EVENT_VIEWED,
                        record_observation,
                    )

                    record_observation(
                        conn,
                        suggestion_id=inserted_id,
                        account_wxid=account_wxid,
                        event_type=EVENT_SHOWN,
                        batch_id=monitor.current_batch_id or 'manual',
                        display_name=monitor.current_display_name,
                        trigger_type=result.trigger_type,
                        metadata={'source': 'manual_generate'},
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
                        metadata={'source': 'manual_generate'},
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
        if "analysis_device_mode" in payload:
            payload["analysis_device_mode"] = normalize_analysis_device_mode(payload["analysis_device_mode"])
        if MODEL_ROOT_DIR_KEY in payload:
            payload[MODEL_ROOT_DIR_KEY] = normalize_model_root_dir(payload[MODEL_ROOT_DIR_KEY])

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
        return {
            "saved": True,
            "payload": payload,
            "model_root_dir": self.settings.get(MODEL_ROOT_DIR_KEY),
            **self._serialize_wechat_accounts(),
        }
    
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

            # 兼容直接选中了某个账号目录的情况
            if (target_dir / "db_storage").is_dir() and target_dir.name.startswith("wxid_"):
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
            from ..services.realtime.providers.factory import normalize_listener_backend

            return {
                "ok": True, 
                "config": {
                    "trigger_mode": self.settings.get("trigger_mode", "semi_auto"),
                    "intent": self.settings.get("intent", "maintain"),
                    "auto_rate_limit": int(self.settings.get("auto_rate_limit", 10)),
                    "engine_type": "llm",
                    "listener_backend": normalize_listener_backend(
                        self.settings.get("listener_backend", "native_uia")
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
            import time as _time

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
                "max_tokens": int,
                "temperature": float
            }
        """
        try:
            import time as _time
            from ..db.connection import get_db

            conn = get_db()
            now = int(_time.time())

            model_id = model.get('id')

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
                         model.get('max_tokens', 512), model.get('temperature', 0.7), _time.time(), model['id'])
                    )
            else:
                conn.execute(
                    '''INSERT INTO llm_models (name, provider, model_id, api_base_url, 
                       api_key, is_active, max_tokens, temperature, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (model.get('name', ''), model.get('provider', ''), model.get('model_id', ''),
                     model.get('api_base_url', ''), model.get('api_key', ''), 1 if model.get('is_active') else 0,
                     model.get('max_tokens', 512), model.get('temperature', 0.7), _time.time(), _time.time())
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

            import threading
            self._analysis_cancel_event = threading.Event()
            
            # 执行特征提取（异步任务）
            result = service.extract_features(conversation_id, cancel_event=self._analysis_cancel_event)

            return {
                "success": True,
                "data": {
                    "task_id": result["task_id"],
                    "status": "completed",
                    "message": "Feature extraction completed"
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

            result = {
                "ok": True,
                "cuda_available": torch.cuda.is_available(),
                "has_nvidia_gpu": GpuInstallerService.has_nvidia_gpu(),
                "gpu_name": None,
                "torch_version": torch.__version__,
                "cuda_version": current_cuda_version,
                "gpu_memory_total_mb": 0,
                "gpu_memory_free_mb": 0,
                "build_variant": get_build_variant(),
                "gpu_overlay_installed": overlay_installed,
                "gpu_overlay_torch_version": overlay_state.get("torch_version"),
                "gpu_overlay_cuda_version": overlay_state.get("cuda_version"),
                "restart_required": bool(
                    overlay_installed
                    and (
                        str(torch.__version__) != str(overlay_state.get("torch_version") or "")
                        or str(current_cuda_version or "") != str(overlay_state.get("cuda_version") or "")
                    )
                ),
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
            return {
                "ok": False,
                "cuda_available": False,
                "has_nvidia_gpu": getattr(GpuInstallerService, "has_nvidia_gpu", lambda: False)(),
                "gpu_name": None,
                "torch_version": "unknown",
                "cuda_version": None,
                "gpu_memory_total_mb": 0,
                "gpu_memory_free_mb": 0,
                "build_variant": get_build_variant(),
                "gpu_overlay_installed": has_gpu_overlay(),
                "gpu_overlay_torch_version": overlay_state.get("torch_version"),
                "gpu_overlay_cuda_version": overlay_state.get("cuda_version"),
                "restart_required": bool(has_gpu_overlay()),
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

            task_id = f"analysis_model_download_{int(time.time())}"
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

            AffinityAnalysisService = self._get_fresh_affinity_service_class()
            service = AffinityAnalysisService()            # 保存服务实例引用，供 get_affinity_progress 查询进度
            self._affinity_service = service
            self._analysis_cancel_event = threading.Event()
            effective_force_reanalyze = True

            # 预生成 task_id，与 service.analyze 内部生成的保持一致
            task_id = f"affinity_{conversation_id}_{int(_time.time())}"

            def _run_analysis():
                try:
                    service.analyze(
                        conversation_id,
                        effective_force_reanalyze,
                        config_overrides,
                        cancel_event=self._analysis_cancel_event,
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 异步好感度分析失败: {e}")
                    import traceback
                    traceback.print_exc()

            t = threading.Thread(target=_run_analysis, daemon=True)
            t.start()

            # 等一小段时间让 service.analyze 初始化 task_id
            _time.sleep(0.1)

            # 从 service._task_status 中找到真正的 task_id
            real_task_id = None
            for tid in service._task_status:
                if tid.startswith(f"affinity_{conversation_id}_"):
                    real_task_id = tid
                    break

            return {
                "ok": True,
                "task_id": real_task_id or task_id
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
