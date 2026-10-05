"""
实时消息监听服务
基于监听 provider 实现单对象消息监听
"""
import sys
import logging
import time
import uuid
import json
import threading
import re
from datetime import datetime, timedelta
from .message_buffer import MessageBuffer
from .realtime_sentiment_service import RealtimeSentimentService
from .emotion_state_tracker import EmotionStateTracker
from .providers.base import UINotAccessibleError
from .providers.models import build_message_hash, normalize_text
from .providers.native_uia import TIME_LABEL_RE
from .providers.factory import normalize_listener_backend
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file

logger = logging.getLogger(__name__)
def _print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(arg) for arg in args) + end
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe_text)
        if kwargs.get("flush", False):
            sys.stdout.flush()


# P1.1 画像 TTL 修复：过期画像降级注入 + 后台续期防重入
_profile_renewal_inflight: set = set()


def _renew_profiles_in_background(display_name: str, account_wxid: str = "") -> None:
    key = f"{account_wxid}:{display_name}"
    if not display_name or key in _profile_renewal_inflight:
        return
    _profile_renewal_inflight.add(key)

    def _run():
        try:
            from .contact_profiler import ContactProfiler
            from .self_profiler import SelfProfiler

            ContactProfiler().generate_profile(display_name, account_wxid=account_wxid)
            SelfProfiler().generate_profile(display_name, account_wxid=account_wxid)
        except Exception as renew_e:
            _print(f"⚠️ 画像后台续期失败（保留旧缓存）: {renew_e}")
        finally:
            _profile_renewal_inflight.discard(key)

    threading.Thread(
        target=_run, daemon=True, name=f"profile-renewal-{display_name[:16]}"
    ).start()


from .uia_recovery import UiaRecoveryMixin
from .backfill_matcher import BackfillMatcherMixin


class RealtimeMonitorService(UiaRecoveryMixin, BackfillMatcherMixin):
    """
    实时监听服务
    单例模式,同一时间只监听一个对象
    """

    _UIA_MANUAL_RESTART_GUARD_SECONDS = 180.0
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.wx = None                      # WeChat实例
            self.current_batch_id = None        # 当前批次ID
            self.current_talker = None          # 当前监听对象username
            self.current_display_name = None    # 当前监听对象显示名
            self.current_account_wxid = ""
            self.is_monitoring = False          # 监听状态
            self._session_generation = 0        # 会话代数：start_monitoring/run_backfill 接管单例时递增（R2）
            self._chat_ready = False            # 聊天切换是否完成
            self._chat_error = ''               # 聊天切换出错信息
            self._chat_ui_inaccessible = False
            self._uia_recovery_attempts = 0
            self._last_uia_recovery = None
            self._uia_recovery_required = False
            self._uia_recovery_in_progress = False
            self._uia_recovery_context = {}
            self._uia_manual_restart_guard_until = 0.0
            self._uia_manual_restart_guard_reason = ""
            self._uia_manual_restart_guard_phase = ""
            self._start_time = 0                # 开始监听时间戳
            self._last_known_ts = 0
            self._chat_timed_out = False
            self._resume_mode = 'skip'
            self.message_buffer = MessageBuffer()
            self.seen_hashes = set()            # 消息去重集合
            self.seen_message_keys = set()      # 轮询周期内的稳定消息身份集合
            self.polling_thread = None          # 轮询线程
            self.stop_polling = False           # 停止轮询标志
            self._stop_event = None
            self._monitor_session_token = 0
            self.emotion_tracker = None
            self.provider = None
            self._provider_name = ''
            self._listener_profile = ''
            self._wechat_version = ''
            # 实时情感分析服务
            self.sentiment_service = RealtimeSentimentService()
            # 情绪状态追踪器（每次 start_monitoring 时重建）
            # AI 建议配置: 从 global settings.json 中读取
            try:
                settings = load_settings_from_file()
                self._listener_backend = normalize_listener_backend(
                    settings.get('listener_backend', 'native_uia')
                )
                self._suggestion_config = {
                    'trigger_mode': settings.get('trigger_mode', 'semi_auto'),
                    'intent': settings.get('intent', 'maintain'),
                    'auto_rate_limit': int(settings.get('auto_rate_limit', 10)),
                    'engine_type': 'llm',           # llm
                }
            except Exception as e:
                self._listener_backend = 'native_uia'
                _print(f"[RealtimeMonitorService] 获取全局设置失败: {e}")
                self._suggestion_config = {
                    'trigger_mode': 'semi_auto',    # full_auto / semi_auto / manual
                    'intent': 'maintain',           # intimate / maintain / distance
                    'auto_rate_limit': 10,          # 全自动模式更新频率上限（秒）
                    'engine_type': 'llm',           # llm
                }
            self._last_auto_suggestion_time = 0
            self._listen_start_suggestion_at = 0
            try:
                self.current_account_wxid = get_active_wechat_account_wxid(load_settings_from_file())
            except Exception:
                self.current_account_wxid = ""
            self._initialized = True
            _print(f"[RealtimeMonitorService] 服务已初始化，引擎类型: {self._suggestion_config['engine_type']}")

    def _resolve_account_wxid(self, account_wxid: str | None = None) -> str:
        normalized = str(account_wxid or "").strip()
        if normalized:
            return normalized
        current = str(getattr(self, "current_account_wxid", "") or "").strip()
        if current:
            return current
        try:
            return get_active_wechat_account_wxid(load_settings_from_file())
        except Exception:
            return ""
    
    def start_monitoring(
        self, 
        talker_username: str,
        talker_display_name: str,
        resume_mode: str = 'skip',
        account_wxid: str = '',
    ) -> dict:
        """
        启动实时监听
        
        Args:
            talker_username: 对话对象username
            talker_display_name: 对话对象显示名
        
        Returns:
            {
                'success': bool,
                'batch_id': str,
                'message': str,
                'error': str (如果失败)
            }
        """
        # 1. 检查是否已在监听
        if self.is_monitoring:
            return {
                'success': False,
                'message': '已有监听任务在运行',
                'error': f'当前正在监听: {self.current_display_name}'
            }
        
        try:
            # 2. 初始化监听后端
            self._reset_wechat_instance()
            self._uia_recovery_attempts = 0
            self._last_uia_recovery = None
            self._uia_recovery_required = False
            self._uia_recovery_in_progress = False
            self._uia_recovery_context = {}
            if self.wx is None:
                _print("[RealtimeMonitorService] 初始化监听后端...")
                try:
                    self._create_wechat_instance_with_recovery(phase="initialize")
                except Exception as e:
                    return {
                        'success': False,
                        'message': '监听后端初始化失败',
                        'error': self._format_listener_init_error(e),
                        'uia_recovery_required': self._uia_recovery_required,
                        'uia_recovery_phase': (self._uia_recovery_context or {}).get('phase', ''),
                        'uia_recovery_prompt': self._chat_error,
                    }
            
            # 3. 生成批次ID
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)
            resolved_talker_username = self._resolve_talker_username(
                talker_username,
                talker_display_name,
                resolved_account_wxid,
            )

            self.current_batch_id = str(uuid.uuid4())
            self.current_talker = resolved_talker_username
            self.current_display_name = talker_display_name
            self.current_account_wxid = resolved_account_wxid
            self._resume_mode = resume_mode or 'skip'
            self.seen_hashes.clear()
            self.seen_message_keys.clear()
            self._last_known_ts = 0
            self._monitor_session_token += 1
            session_token = self._monitor_session_token
            self._stop_event = threading.Event()
            self._prewarm_rag_index_for_current_contact()
            
            # 创建情绪追踪器
            self.emotion_tracker = EmotionStateTracker()
            self._baseline_tail = []  # 会话隔离：旧会话基线不得泄入新会话显示
            _print("[RealtimeMonitorService] 情绪追踪器已创建")
            
            _print(f"[RealtimeMonitorService] 开始监听: {talker_display_name} (batch_id: {self.current_batch_id})")
            
            # 4. 立即设置状态（让前端可以先进入悬浮模式）
            self._session_generation += 1  # 新会话接管单例（R2）：使进行中的回溯不再清理本会话状态
            self.is_monitoring = True
            self._chat_ready = False
            self._chat_error = ''
            import time
            self._start_time = int(time.time())
            _print(f"✅ 监听已启动！批次ID: {self.current_batch_id[:8]}...")
            
            # 5. 启动轮询线程（ChatWith 和模型预加载在线程中异步执行）
            _print("🔄 启动消息轮询线程...")
            self.stop_polling = False
            self.polling_thread = threading.Thread(
                target=self._polling_loop,
                args=(session_token, self._stop_event),
                daemon=True,
            )
            self.polling_thread.start()
            
            # 8. 记录事件到运行时事件表
            self._log_runtime_event('realtime_monitor_start', {
                'batch_id': self.current_batch_id,
                'account_wxid': self.current_account_wxid,
                'talker_username': resolved_talker_username,
                'talker_display_name': talker_display_name
            })
            
            return {
                'success': True,
                'batch_id': self.current_batch_id,
                'message': f'已开始监听 {talker_display_name}'
            }
            
        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 启动监听异常: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'message': '启动监听失败',
                'error': str(e)
            }


    def _build_chatwith_candidates(self) -> list[str]:
        """Build fallback ChatWith search targets from the display name."""
        raw_name = (self.current_display_name or '').strip()
        if not raw_name:
            return []

        candidates = [raw_name]
        simplified = re.sub(r'[\(（【\[].*?[\)）】\]]', '', raw_name).strip()
        simplified = re.sub(r'\s+', ' ', simplified).strip()
        if simplified and simplified not in candidates:
            candidates.append(simplified)

        compact = re.sub(r'[^\w\u4e00-\u9fff]', '', raw_name).strip()
        if compact and compact not in candidates:
            candidates.append(compact)

        return candidates

    def _get_talker_key(self, talker_username: str | None, talker_display_name: str | None) -> str:
        """Build a stable talker key for persistence when username may be unavailable."""
        return (talker_username or talker_display_name or '').strip()

    def _resolve_talker_username(
        self,
        talker_username: str | None,
        talker_display_name: str | None,
        account_wxid: str | None = None,
    ) -> str:
        """Resolve the canonical conversation username from contacts/conversations when possible."""
        if talker_username and str(talker_username).strip():
            return str(talker_username).strip()

        display_name = str(talker_display_name or '').strip()
        if not display_name:
            return ''

        try:
            from ...db.connection import get_db

            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)
            row = conn.execute(
                '''
                SELECT username
                FROM contacts
                WHERE account_wxid = ?
                  AND (remark = ? OR nickname = ?)
                ORDER BY
                    CASE
                        WHEN remark = ? THEN 0
                        WHEN nickname = ? THEN 1
                        ELSE 2
                    END,
                    username ASC
                LIMIT 1
                ''',
                (resolved_account_wxid, display_name, display_name, display_name, display_name)
            ).fetchone()
            if row and row[0]:
                return str(row[0]).strip()

            row = conn.execute(
                '''
                SELECT username
                FROM conversations
                WHERE account_wxid = ?
                  AND (display_name = ? OR username = ?)
                ORDER BY message_count DESC, updated_at DESC
                LIMIT 1
                ''',
                (resolved_account_wxid, display_name, display_name)
            ).fetchone()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception as e:
            _print(f"[RealtimeMonitorService] 解析 talker username 失败: {e}")

        return display_name

    def _message_identity(self, msg) -> str:
        """Build a stable identity for a realtime message object."""
        msg_hash = getattr(msg, 'hash', None)
        if msg_hash:
            return f"hash:{msg_hash}"
        runtime_id = getattr(msg, 'id', None)
        if runtime_id:
            return f"id:{runtime_id}"
        return (
            f"fallback:{getattr(msg, 'is_self', False)}:"
            f"{getattr(msg, 'type', 'text')}:{getattr(msg, 'content', '')}:{getattr(msg, 'time', '')}"
        )

    def _resolve_visible_sender_attr(self, msg) -> str:
        """Resolve sender_attr from a visible provider message object."""
        if getattr(msg, 'is_system', False):
            return 'system'
        return 'self' if getattr(msg, 'is_self', False) else 'friend'


    def _prepare_visible_messages(self, visible_messages: list) -> list[dict]:
        """Normalize one visible snapshot so dedupe can survive runtime_id churn."""
        listener_profile = normalize_text(
            self._listener_profile or getattr(self.wx, 'listener_profile', '') or 'unknown'
        )
        prepared_messages: list[dict] = []
        occurrence_map: dict[str, int] = {}
        self._last_known_ts = 0

        for msg in visible_messages or []:
            is_self = getattr(msg, 'is_self', False)
            is_system = getattr(msg, 'is_system', False)
            content = str(getattr(msg, 'content', '') or '')
            message_type = str(getattr(msg, 'type', 'text') or 'text')
            if not is_system and content and TIME_LABEL_RE.match(content.strip()):
                is_system = True
                message_type = 'system'
            sender_attr = 'self' if is_self else 'friend'
            if is_system:
                sender_attr = 'system'
            runtime_id = str(getattr(msg, 'id', '') or '')
            visible_index = str(getattr(msg, 'visible_index', '') or '')
            explicit_timestamp = int(getattr(msg, 'timestamp', 0) or 0)
            timestamp_label = normalize_text(
                str(getattr(msg, 'time', None) or getattr(msg, 'CreateTime', '') or '')
            )
            previous_known_ts = int(self._last_known_ts or 0)
            resolved_timestamp = self._resolve_message_timestamp(msg, sender_attr, content)
            dedupe_timestamp = int(
                resolved_timestamp
                if (explicit_timestamp or timestamp_label or sender_attr == 'system' or previous_known_ts)
                else 0
            )

            occurrence_identity = [
                listener_profile,
                normalize_text(message_type).lower(),
                normalize_text(content),
            ]
            if dedupe_timestamp:
                occurrence_identity.append(f"ts:{dedupe_timestamp}")
            elif timestamp_label:
                occurrence_identity.append(f"label:{timestamp_label}")
            occurrence_key = "|".join(occurrence_identity)
            occurrence_map[occurrence_key] = occurrence_map.get(occurrence_key, 0) + 1
            occurrence = occurrence_map[occurrence_key]

            prepared_messages.append(
                {
                    'msg': msg,
                    'sender_attr': sender_attr,
                    'content': content,
                    'message_type': message_type,
                    'runtime_id': runtime_id,
                    'visible_index': visible_index,
                    'resolved_timestamp': resolved_timestamp,
                    'dedupe_timestamp': dedupe_timestamp,
                    'occurrence': occurrence,
                    'message_key': self._build_message_key(
                        msg,
                        sender_attr,
                        message_type,
                        content,
                        resolved_timestamp=dedupe_timestamp,
                        occurrence=occurrence,
                    ),
                }
            )

        return prepared_messages

    def _build_message_key(
        self,
        msg,
        sender_attr: str,
        message_type: str,
        content: str,
        resolved_timestamp: int = 0,
        occurrence: int = 1,
    ) -> str:
        """Build a stable per-session identity used for polling dedupe.

        sender_attr is intentionally excluded so the same visible bubble is not
        re-ingested when screenshot/UIA sender classification jitters, and
        runtime_id is not treated as authoritative because Qt re-renders can
        recycle it for already visible bubbles.
        """
        listener_profile = normalize_text(
            self._listener_profile or getattr(self.wx, 'listener_profile', '') or 'unknown'
        )
        timestamp_label = normalize_text(
            str(getattr(msg, 'time', None) or getattr(msg, 'CreateTime', '') or '')
        )
        parts = [
            listener_profile,
            normalize_text(message_type).lower(),
            normalize_text(content),
        ]
        if resolved_timestamp:
            parts.append(f"ts:{int(resolved_timestamp)}")
        elif timestamp_label:
            parts.append(f"label:{timestamp_label}")
        parts.append(f"occ:{max(1, int(occurrence or 1))}")
        return "|".join(parts)

    def _build_final_message_hash(
        self,
        sender_attr: str,
        message_type: str,
        content: str,
        resolved_timestamp: int,
        runtime_id: str,
        fallback_occurrence: str,
    ) -> str:
        """Build the canonical hash persisted in realtime_message_buffer."""
        return build_message_hash(
            self._listener_profile or getattr(self.wx, 'listener_profile', '') or 'unknown',
            'system' if sender_attr == 'system' else '',
            message_type,
            content,
            int(resolved_timestamp or 0),
            fallback_occurrence or runtime_id,
        )

    def _build_session_state(self, session_token: int) -> dict:
        """Freeze the current monitoring context for one polling thread."""
        return {
            'session_token': int(session_token),
            'batch_id': self.current_batch_id,
            'account_wxid': self.current_account_wxid,
            'talker_username': self.current_talker,
            'display_name': self.current_display_name,
        }

    def _session_is_current(self, session_state: dict | None) -> bool:
        """Check whether a frozen session snapshot still belongs to the active monitor run."""
        if not session_state:
            return False
        token = int(session_state.get('session_token') or 0)
        batch_id = session_state.get('batch_id')
        if token != int(self._monitor_session_token or 0):
            return False
        if not self.is_monitoring:
            return False
        if not batch_id or batch_id != self.current_batch_id:
            return False
        return True

    def _session_should_continue(self, session_state: dict | None, stop_event) -> bool:
        """Whether the polling thread should continue doing work for this session."""
        if stop_event is not None and stop_event.is_set():
            return False
        return self._session_is_current(session_state)

    def _scroll_chat_history_up(self, wheel_times: int = 3) -> bool:
        """Scroll the current chat message list upward to load older history."""
        try:
            if not self.wx or not hasattr(self.wx, 'ChatBox'):
                return False
            msgbox = self.wx.ChatBox.msgbox
            msgbox.MiddleClick()
            msgbox.WheelUp(wheelTimes=wheel_times)
            time.sleep(0.12)
            return True
        except Exception as e:
            _print(f"[Backfill] 向上滚动消息窗口失败: {e}")
            return False

    def _scroll_chat_history_down(self, wheel_times: int = 3) -> bool:
        """Scroll the current chat message list downward toward the latest messages."""
        try:
            if not self.wx or not hasattr(self.wx, 'ChatBox'):
                return False
            msgbox = self.wx.ChatBox.msgbox
            msgbox.MiddleClick()
            msgbox.WheelDown(wheelTimes=wheel_times)
            time.sleep(0.1)
            return True
        except Exception as e:
            _print(f"[Backfill] Scroll down failed: {e}")
            return False

    def _scroll_chat_to_latest(
        self,
        max_rounds: int = 20,
        wheel_times: int = 3,
        stagnant_threshold: int = 6,
    ) -> None:
        """Best-effort scroll back to the latest visible messages after backfill."""
        seen_bottom_signature = None
        stagnant_rounds = 0
        for _ in range(max_rounds):
            visible_messages = self.wx.GetAllMessage() if self.wx else []
            if not visible_messages:
                break
            bottom_signature = self._visible_message_signature(visible_messages, from_tail=True)
            if bottom_signature == seen_bottom_signature:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
                seen_bottom_signature = bottom_signature
            if stagnant_rounds >= max(1, int(stagnant_threshold or 1)):
                break
            if not self._scroll_chat_history_down(wheel_times=wheel_times):
                break

    def _try_chat_with(self, target_name: str) -> bool:
        """尝试执行 ChatWith，带 15 秒超时。成功返回 True，失败设置 _chat_error 并返回 False"""
        self._chat_timed_out = False
        self._chat_ui_inaccessible = False
        started_at = time.time()
        before_info = self._get_foreground_window_info()
        _print(
            f"[OpenChat] 调用前前台窗口: hwnd={before_info.get('hwnd')} "
            f"class={before_info.get('class_name')} title={before_info.get('title')}"
        )

        try:
            if not self.wx:
                raise RuntimeError("No realtime provider instance")
            expected_name = (self.current_display_name or target_name or "").strip()
            self.wx.ChatWith(target_name, expected_display_name=expected_name)
            _print(
                f"[OpenChat] 已调用 provider.open_chat(search='{target_name}', expected='{expected_name}')"
            )
        except Exception as e:
            after_info = self._get_foreground_window_info()
            elapsed = time.time() - started_at
            error_text = str(e)
            self._chat_timed_out = ('timeout' in error_text.lower()) or ('超时' in error_text)
            self._chat_ui_inaccessible = isinstance(e, UINotAccessibleError) or ('ui_not_accessible' in error_text.lower())
            if self._chat_ui_inaccessible:
                self._attempt_auto_recover_shell_only_uia(phase="chat_switch", error_text=error_text)
                _print(
                    f"[OpenChat] UIA 不可访问: hwnd={after_info.get('hwnd')} "
                    f"class={after_info.get('class_name')} title={after_info.get('title')} error={error_text}"
                )
                return False
            error_prefix = '切换聊天窗口超时' if self._chat_timed_out else '切换聊天窗口失败'
            self._chat_error = (
                f"{error_prefix}（{elapsed:.1f}秒）"
                f"，target='{target_name}'，原因={error_text}，"
                f"前台窗口={after_info.get('title') or after_info.get('class_name')}"
            )
            _print(
                f"[OpenChat] 失败: hwnd={after_info.get('hwnd')} "
                f"class={after_info.get('class_name')} title={after_info.get('title')}"
            )
            return False

        after_info = self._get_foreground_window_info()
        elapsed = time.time() - started_at
        """
            worker_result = {
                'ok': False,
                'error': f'子进程未返回结果(exitcode={chat_process.exitcode})',
                'elapsed': time.time() - started_at,
            }

        if not worker_result.get('ok'):
            elapsed = float(worker_result.get('elapsed') or (time.time() - started_at))
            self._chat_error = (
                f"切换聊天窗口失败: {worker_result.get('error', '')} "
                f"(target='{target_name}', elapsed={elapsed:.2f}s)"
            )
            _print(
                f"[ChatWith] 失败后前台窗口: hwnd={after_info.get('hwnd')} "
                f"class={after_info.get('class_name')} title={after_info.get('title')}"
            )
            return False

        """
        _print(
            f"[OpenChat] 成功: target='{target_name}', elapsed={elapsed:.2f}s, "
            f"前台窗口={after_info.get('title') or after_info.get('class_name')}"
        )
        self._chat_error = ''
        return True

    def _seed_visible_message_baseline(self, session_state: dict) -> int:
        """
        Seed the current visible chat items into the in-memory dedupe cache so
        startup/history snapshots do not trigger realtime side effects.
        """
        if not self.wx or not self._session_is_current(session_state):
            return 0

        seeded = 0
        tail_messages: list[dict] = []
        visible_messages = self.wx.GetAllMessage() or []
        if not visible_messages:
            return 0

        for prepared_message in self._prepare_visible_messages(visible_messages):
            try:
                msg = prepared_message['msg']
                sender_attr = prepared_message['sender_attr']
                content = prepared_message['content']
                message_type = prepared_message['message_type']
                runtime_id = prepared_message['runtime_id']
                occurrence = str(prepared_message['occurrence'])
                message_key = prepared_message['message_key']
                resolved_timestamp = int(prepared_message['resolved_timestamp'] or 0)
                dedupe_timestamp = int(prepared_message['dedupe_timestamp'] or 0)
                message_hash = self._build_final_message_hash(
                    sender_attr=sender_attr,
                    message_type=message_type,
                    content=content,
                    resolved_timestamp=dedupe_timestamp,
                    runtime_id=runtime_id,
                    fallback_occurrence=occurrence,
                )
                self.seen_message_keys.add(message_key)
                if message_hash:
                    self.seen_hashes.add(message_hash)
                seeded += 1
                # 暂存窗口尾部（开场建议的上下文源——基线消息按设计不落
                # realtime_message_buffer，批量查询查不到，此前导致开场建议
                # 恒判「消息不足」）
                tail_messages.append({
                    'sender_attr': sender_attr,
                    'content': content,
                    'timestamp': resolved_timestamp,
                    'message_type': message_type,
                })
            except Exception:
                continue
        session_state['baseline_tail'] = tail_messages[-12:]
        self._baseline_tail = session_state['baseline_tail']  # 供 bridge 最近消息端点读取

        # 情绪追踪器用基线上下文真实预热：跑情感模型而非中性占位——
        # 此前 polarity=0/confidence=0 导致 UI 恒显「正在分析情绪数据」
        # 和比例 N/A（有窗口数据但全是零，没有有效情绪信号）
        if self.emotion_tracker:
            try:
                warmup_texts = []
                warmup_msgs = []
                for msg in session_state['baseline_tail']:
                    if msg.get('sender_attr') not in ('self', 'friend'):
                        continue
                    if str(msg.get('message_type') or 'text') != 'text':
                        continue
                    content = str(msg.get('content') or '').strip()
                    if not content:
                        continue
                    warmup_texts.append(content)
                    warmup_msgs.append(msg)

                if warmup_texts:
                    _print(f"🌡️ 情绪基线预热: {len(warmup_texts)} 条消息跑情感模型…")
                    for msg, content in zip(warmup_msgs, warmup_texts):
                        try:
                            sentiment = self.sentiment_service.analyze(content)
                            # sentiment 附到基线尾部——bridge 合并基线给前端时，
                            # 图表统计/情绪历史才能拿到极性信号（否则比例恒 N/A）
                            msg['sentiment'] = sentiment
                            self.emotion_tracker.update(
                                sentiment,
                                {
                                    'content': content,
                                    'sender_attr': msg.get('sender_attr'),
                                    'timestamp': int(msg.get('timestamp') or 0),
                                },
                            )
                        except Exception as sent_e:
                            # 单条失败不阻断——降级中性占位
                            msg['sentiment'] = {'polarity': 0, 'intensity': 0.0, 'confidence': 0.0, 'rules_applied': []}
                            self.emotion_tracker.update(
                                msg['sentiment'],
                                {'content': content, 'sender_attr': msg.get('sender_attr'),
                                 'timestamp': int(msg.get('timestamp') or 0)},
                            )
                    _print(f"✅ 情绪基线预热完成（{len(warmup_texts)} 条真实分析）")
            except Exception as exc:
                _print(f"⚠️ 情绪基线预热失败: {exc}")
        self._last_known_ts = 0
        return seeded

    def _polling_loop(self, session_token: int, stop_event):
        """轮询线程：先完成聊天切换和模型预加载，再开始抓取消息"""
        session_state = self._build_session_state(session_token)
        _print("🔄 轮询线程已启动")
        
        # -- 1. 将微信窗口置顶 --
        self._bring_wechat_to_front()
        time.sleep(0.35)
        
        # -- 2. 切换聊天窗口（带重试循环，最多 3 次） --
        _print(f"👂 切换到聊天窗口: {session_state.get('display_name')}")
        MAX_CHAT_RETRIES = 3
        CHAT_RETRY_DELAY = 5  # 秒
        chat_connected = False
        chat_targets = self._build_chatwith_candidates()
        _print(f"[OpenChat] 候选搜索名: {chat_targets}")

        for attempt in range(1, MAX_CHAT_RETRIES + 1):
            if not self._session_should_continue(session_state, stop_event):
                _print("🛑 收到停止信号，中止聊天切换重试")
                return
            
            _print(f"🔄 聊天切换尝试 {attempt}/{MAX_CHAT_RETRIES}...")
            try:
                if attempt == 1 and self.wx is not None:
                    _print("[OpenChat] 复用当前监听后端实例进行首次聊天切换")
                else:
                    self._create_wechat_instance_with_recovery(phase="chat_retry")
                self._bring_wechat_to_front()
                time.sleep(0.4)
                for target_name in chat_targets:
                    _print(f"[OpenChat] 本轮尝试搜索名: {target_name}")
                    if self._try_chat_with(target_name):
                        _print(f"✅ 已切换到聊天窗口: {target_name}")
                        chat_connected = True
                        break
                    _print(f"⚠️ 第 {attempt} 次聊天切换失败: {self._chat_error}")
                    if self._chat_ui_inaccessible:
                        _print("⚠️ 检测到微信 UIA 树当前不可访问，停止本轮其余候选名和后续自动重试")
                        break
                    if self._chat_timed_out:
                        _print("⚠️ 检测到聊天切换超时，停止本轮其余候选名和后续自动重试，避免堆积挂起线程")
                        break
                if chat_connected:
                    break
                if self._chat_timed_out or self._chat_ui_inaccessible:
                    break
            except Exception as e:
                self._chat_error = f'切换聊天窗口异常: {e}'
                _print(f"❌ 第 {attempt} 次聊天切换异常: {e}")
            
            if self._chat_timed_out or self._chat_ui_inaccessible:
                break

            if attempt < MAX_CHAT_RETRIES:
                _print(f"⏳ {CHAT_RETRY_DELAY} 秒后重试...")
                time.sleep(CHAT_RETRY_DELAY)
        
        # 重试 3 次仍失败 → 进入「等待恢复」模式，而不是终止线程
        if not chat_connected:
            if self._chat_ui_inaccessible:
                _print("🛑 微信 UIA 树当前不可访问，停止监听线程，不进入等待恢复模式")
                self.is_monitoring = False
                return
            _print(f"⚠️ 初始聊天切换 {MAX_CHAT_RETRIES} 次尝试均失败，进入等待恢复模式...")
            RECOVERY_INTERVAL = 10  # 每 10 秒重试一次
            while self._session_should_continue(session_state, stop_event):
                time.sleep(RECOVERY_INTERVAL)
                _print("🔄 [等待恢复] 重试聊天切换...")
                try:
                    if self.wx is None:
                        self._create_wechat_instance_with_recovery(phase="chat_recovery_loop")
                    self._bring_wechat_to_front()
                    time.sleep(0.4)
                    for target_name in chat_targets:
                        _print(f"[OpenChat] [恢复模式] 尝试搜索名: {target_name}")
                        if self._try_chat_with(target_name):
                            _print(f"✅ [恢复成功] 已切换到聊天窗口: {target_name}")
                            chat_connected = True
                            break
                        if self._chat_ui_inaccessible:
                            _print("⚠️ [恢复模式] 微信 UIA 树当前不可访问，停止恢复尝试")
                            break
                        if self._chat_timed_out:
                            _print("⚠️ [恢复模式] 聊天切换超时，停止本轮恢复尝试")
                            break
                    if chat_connected:
                        break
                    if self._chat_timed_out or self._chat_ui_inaccessible:
                        break
                except Exception as e:
                    _print(f"⚠️ [等待恢复] 聊天切换仍然失败: {e}")

                if self._chat_timed_out or self._chat_ui_inaccessible:
                    break
            
            if not chat_connected:
                if self._chat_ui_inaccessible:
                    _print("🛑 微信 UIA 树当前不可访问，轮询线程退出")
                    self.is_monitoring = False
                    return
                _print("🛑 等待恢复被中断（收到停止信号），轮询线程退出")
                return

        if not self._session_should_continue(session_state, stop_event):
            _print("🛑 聊天切换完成后检测到会话已停止，轮询线程退出")
            return
        
        if self._resume_mode == 'backfill':
            _print("[Backfill] 已并入监听启动头部，开始补全历史消息")
            # 回溯段（probe 查库 + UIA 滚动抓取）在主循环之前执行，若异常未捕获会
            # 直接杀死轮询线程，导致 is_monitoring 永久卡 True，这里统一兜底（R3）
            try:
                probe = self.get_resume_probe(
                    talker_display_name=session_state.get('display_name') or '',
                    talker_username=session_state.get('talker_username') or '',
                    threshold_seconds=300,
                )
                if probe.get('has_checkpoint') and probe.get('should_offer_resume'):
                    backfill_result = self._run_backfill_in_current_chat_context(
                        probe=probe,
                        talker_username=session_state.get('talker_username') or '',
                        talker_display_name=session_state.get('display_name') or '',
                        max_scroll_rounds=80,
                        wheel_times=3,
                    )
                    if not backfill_result.get('success'):
                        self._chat_error = backfill_result.get('message') or '回溯补全失败'
                        self.is_monitoring = False
                        _print(f"[Backfill] 监听启动前回溯失败: {self._chat_error}")
                        return
                    _print(
                        f"[Backfill] 启动前回溯完成: inserted={backfill_result.get('inserted_count', 0)}, "
                        f"existing={backfill_result.get('existing_count', 0)}"
                    )
                    self._scroll_chat_to_latest()
                else:
                    _print("[Backfill] 未命中回溯条件，直接进入正常监听")
                self._resume_mode = 'skip'
            except Exception as e:
                self._chat_error = f'监听启动前回溯异常: {e}'
                self.is_monitoring = False
                _print(f"❌ {self._chat_error}")
                return

        if not self._session_should_continue(session_state, stop_event):
            _print("🛑 回溯/启动基线前检测到会话已停止，轮询线程退出")
            return

        # 启动基线内部会调用 UIA 抓取当前可见消息，主循环之前同样需要兜底，
        # 避免异常直接杀死轮询线程导致 is_monitoring 永久卡 True（R3）
        try:
            seeded_count = self._seed_visible_message_baseline(session_state)
        except Exception as e:
            self._chat_error = f'建立启动基线异常: {e}'
            self.is_monitoring = False
            _print(f"❌ {self._chat_error}")
            return
        if seeded_count:
            _print(f"[RealtimeMonitorService] 已建立启动基线，忽略当前可见历史消息 {seeded_count} 条")

        if not self._session_should_continue(session_state, stop_event):
            _print("🛑 启动基线完成后检测到会话已停止，轮询线程退出")
            return

        # -- 3. 预加载情感分析模型 --
        _print("🤖 正在预加载情感分析模型...")
        try:
            self.sentiment_service.analyze("测试")
            _print("✅ 情感分析模型加载完成")
        except Exception as e:
            _print(f"⚠️ 情感分析模型加载失败: {e}")
            _print("💡 将继续监听,但情感分析功能可能不可用")

        if not self._session_should_continue(session_state, stop_event):
            _print("🛑 模型预加载完成后检测到会话已停止，轮询线程退出")
            return
        
        # -- 4. 标记就绪 --
        self._chat_ready = True
        self._chat_error = ''
        _print("🟢 准备就绪，开始抓取消息...")

        # 开场建议：基于窗口内最近消息立即生成一次（后台线程执行，不阻塞轮询）
        threading.Thread(
            target=self._generate_listen_start_suggestion,
            args=(session_state,), daemon=True, name="listen-start-suggestion",
        ).start()
        
        gdi_fail_count = 0  # GDI 异常连续失败计数（Bug 3）
        GDI_MAX_CONSECUTIVE = 5  # 连续 GDI 失败上限
        poll_fail_count = 0  # 非已知类别异常连续失败计数（R1）
        POLL_MAX_CONSECUTIVE = 10  # 连续失败上限：超过视为监听通道失效（如微信已关闭）
        
        while self._session_should_continue(session_state, stop_event):
            try:
                if not self.wx or not session_state.get('display_name'):
                    break
                
                # 获取当前窗口的所有消息（通过去重逻辑只处理新消息）
                try:
                    new_messages = self.wx.GetAllMessage()
                    gdi_fail_count = 0  # 成功则重置计数
                    poll_fail_count = 0
                except Exception as gdi_err:
                    err_msg = str(gdi_err)
                    # Bug 3: GDI 截图异常专项捕获
                    if 'CreateCompatibleDC' in err_msg or 'GDI' in err_msg.upper() or 'ScreenShot' in err_msg:
                        gdi_fail_count += 1
                        if gdi_fail_count <= GDI_MAX_CONSECUTIVE:
                            _print(f"⚠️ GDI 截图异常 ({gdi_fail_count}/{GDI_MAX_CONSECUTIVE}): {err_msg}")
                            time.sleep(2)  # 等待 GDI 资源释放
                            continue
                        else:
                            self._chat_error = f'GDI 截图连续失败 {gdi_fail_count} 次，消息获取暂时不可用'
                            _print(f"❌ {self._chat_error}")
                            gdi_fail_count = 0  # 重置后继续尝试
                            time.sleep(5)
                            continue
                    else:
                        raise  # 非 GDI 异常，交给外层处理
                
                if new_messages:
                    # 处理每条消息
                    for prepared_message in self._prepare_visible_messages(new_messages):
                        self._process_message(
                            prepared_message['msg'],
                            session_state=session_state,
                            prepared_message=prepared_message,
                        )
                
                # 周期性 silence 检测（即使没有新消息也需要检测）
                if self.emotion_tracker:
                    silence_event = self.emotion_tracker.check_silence()
                    if silence_event:
                        self._handle_trigger_events([silence_event], session_state=session_state)
                
                # 每1秒检查一次
                time.sleep(0.3)
                
            except Exception as e:
                poll_fail_count += 1
                _print(f"❌ 轮询出错 ({poll_fail_count}/{POLL_MAX_CONSECUTIVE}): {e}")
                import traceback
                traceback.print_exc()
                if poll_fail_count >= POLL_MAX_CONSECUTIVE:
                    # 连续失败视为监听通道失效（如微信已关闭/UIA 不可访问）：
                    # 置错误状态并停止轮询，前端经 get_status 的 chat_error 可见，
                    # 不再无限自旋刷日志（R1）
                    self._chat_error = f'消息轮询连续失败 {poll_fail_count} 次，监听已停止：{e}'
                    self.is_monitoring = False
                    break
                time.sleep(1)
        
        _print("🛑 轮询线程已停止")
    
    def _process_message(
        self,
        msg,
        session_state: dict | None = None,
        prepared_message: dict | None = None,
    ):
        """处理单条消息（从轮询或回调中调用）"""
        try:
            session_state = session_state or self._build_session_state(self._monitor_session_token)
            if not self._session_is_current(session_state):
                return

            batch_id = session_state.get('batch_id')
            talker_username = session_state.get('talker_username')
            display_name = session_state.get('display_name')
            if not batch_id or not display_name:
                return

            prepared_message = prepared_message or self._prepare_visible_messages([msg])[0]

            # 1. 判断发送者
            sender_attr = prepared_message['sender_attr']
            is_self = sender_attr == 'self'
            is_system = sender_attr == 'system'

            sender_name = "我" if is_self else "对方"
            if is_system:
                sender_name = "系统"
            
            # 5. 提取消息内容
            content = prepared_message['content']
            message_type = prepared_message['message_type']
            runtime_id = prepared_message['runtime_id']
            occurrence = str(prepared_message['occurrence'])
            visible_index = int(prepared_message.get('visible_index', -1) or -1)
            message_key = prepared_message['message_key']
            resolved_timestamp = int(prepared_message['resolved_timestamp'] or 0)
            dedupe_timestamp = int(prepared_message['dedupe_timestamp'] or 0)

            # 2. 轮询去重：同一条 UI 消息在同一次监听内只处理一次
            if message_key in self.seen_message_keys:
                return
            
            # 显示简洁的消息预览
            content_preview = str(content)[:30] + '...' if len(str(content)) > 30 else str(content)
            _print(f"📩 收到消息 [{sender_name}]: {content_preview}")
            
            # 6. 构建消息数据
            message_data = {
                'message_hash': str(getattr(msg, 'hash', '') or ''),
                'runtime_id': runtime_id,
                'sender_attr': sender_attr,
                'content': str(content) if content else '',
                'message_type': message_type,
                'timestamp': resolved_timestamp,
                'visible_index': visible_index,
            }
            message_data['message_hash'] = self._build_final_message_hash(
                sender_attr=sender_attr,
                message_type=message_type,
                content=message_data['content'],
                resolved_timestamp=dedupe_timestamp,
                runtime_id=message_data['runtime_id'],
                fallback_occurrence=occurrence,
            )
            message_hash = message_data.get('message_hash')

            # 3. Canonical hash 去重：防止同一条消息因为时间补全变化而重复入库
            if message_hash and message_hash in self.seen_hashes:
                self.seen_message_keys.add(message_key)
                return
            if message_hash and self.message_buffer.message_exists(message_hash, self.current_account_wxid):
                self.seen_message_keys.add(message_key)
                self.seen_hashes.add(message_hash)
                return
            
            # 7. 保存到数据库
            success = self.message_buffer.save_message(
                batch_id,
                self.current_account_wxid,
                talker_username,
                display_name,
                message_data
            )
            
            if success:
                self.seen_message_keys.add(message_key)
                # 记录哈希
                if message_hash:
                    self.seen_hashes.add(message_hash)
                
                # 自动进行实时情感分析(排除系统消息)
                sentiment_result = None
                triggers = []
                if sender_attr != 'system' and message_data['content'] and str(message_data['content']).strip():
                    try:
                        sentiment_result = self.sentiment_service.analyze(
                            str(message_data['content'])
                        )
                        # 同时缓存到数据库
                        self.sentiment_service.analyze_and_cache(
                            message_id=message_hash,
                            text=str(message_data['content'])
                        )
                        _print(f"💭 情感分析完成: polarity={sentiment_result.get('polarity')}")
                    except Exception as e:
                        _print(f"⚠️ 情感分析失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 更新情绪追踪器并检测触发条件
                if self.emotion_tracker and sentiment_result:
                    try:
                        triggers = self.emotion_tracker.update(
                            sentiment_result, message_data
                        )
                        if (triggers
                                and self._suggestion_config.get('trigger_mode') != 'full_auto'):
                            self._handle_trigger_events(triggers, session_state=session_state)
                    except Exception as e:
                        _print(f"⚠️ 情绪追踪更新失败: {e}")
                
                # 全自动模式：每条消息都尝试生成建议
                if (self._suggestion_config.get('trigger_mode') == 'full_auto'
                        and sentiment_result
                        and sender_attr == 'friend'):
                    self._handle_full_auto_suggestion(
                        sentiment_result,
                        triggers,
                        session_state=session_state,
                    )
                
                # 隐式反馈：用户自己发了消息 → 对比最近的 AI 建议
                if sender_attr == 'self' and message_data['content']:
                    self._check_feedback(
                        message_data['content'],
                        session_state=session_state,
                        user_message_type=message_data.get('message_type'),
                    )
                
                # 显示统计
                _print(f"✅ 已保存！累计: {len(self.seen_hashes)} 条\n")
            else:
                _print("❌ 保存失败！\n")
            
        except Exception as e:
            _print(f"❌ 消息处理出错: {e}")
            import traceback
            traceback.print_exc()
    
    def _resolve_message_timestamp(self, msg, sender_attr: str, content) -> int:
        """Resolve a best-effort message timestamp from realtime metadata or system labels."""
        now_ts = int(time.time())
        explicit_ts = int(getattr(msg, 'timestamp', 0) or 0)
        if explicit_ts:
            self._last_known_ts = explicit_ts
            return explicit_ts
        direct_label = getattr(msg, 'time', None) or getattr(msg, 'CreateTime', None)
        parsed_direct = self._resolve_time_label(direct_label, 0) if direct_label else 0
        if parsed_direct:
            self._last_known_ts = parsed_direct

        if sender_attr == 'system':
            parsed_system = self._resolve_time_label(content, 0)
            if parsed_system:
                self._last_known_ts = parsed_system
                return parsed_system
            if parsed_direct:
                self._last_known_ts = parsed_direct
                return parsed_direct
            return self._last_known_ts or 0

        return parsed_direct or self._last_known_ts or now_ts


    def _map_message_type(self, message_type: str) -> int:
        """Map normalized listener message types to the app's integer message types."""
        type_map = {
            'text': 1,
            'image': 3,
            'voice': 34,
            'video': 43,
            'emoji': 47,
            'file': 49,
            'link': 1,
            'system': 1,
        }
        return type_map.get(str(message_type or 'text').lower(), 1)

    def _get_or_create_conversation_id(self, talker_username: str, talker_display_name: str) -> int:
        """Return the conversation id for a talker, creating it when missing."""
        from ...db.connection import get_db

        conn = get_db()
        talker_key = self._get_talker_key(talker_username, talker_display_name)
        account_wxid = self._resolve_account_wxid()
        row = conn.execute(
            'SELECT id FROM conversations WHERE account_wxid = ? AND username = ? AND platform = ?',
            (account_wxid, talker_key, 'wechat')
        ).fetchone()
        if row:
            return row[0]

        now_ts = int(time.time())
        cursor = conn.execute(
            '''
            INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count)
            VALUES (?, ?, ?, 'wechat', ?, ?, 0)
            ''',
            (account_wxid, talker_key, talker_display_name or talker_key, now_ts, now_ts)
        )
        conn.commit()
        return cursor.lastrowid

    def _prewarm_rag_index_for_current_contact(self) -> None:
        try:
            from .rag.config import load_rag_settings

            if not load_rag_settings().get("rag_enabled"):
                return
            account_wxid = str(self.current_account_wxid or "").strip()
            talker = str(self.current_talker or "").strip()
            display_name = str(self.current_display_name or "").strip()
            if not account_wxid or (not talker and not display_name):
                return
            from ...db.connection import get_db

            row = get_db().execute(
                """
                SELECT id
                FROM conversations
                WHERE account_wxid = ?
                  AND is_deleted = 0
                  AND (username = ? OR display_name = ? OR username = ? OR display_name = ?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (account_wxid, talker, talker, display_name, display_name),
            ).fetchone()
            if not row:
                return
            from .rag.indexer import RagIndexer

            RagIndexer().ensure_contact_index(
                account_wxid=account_wxid,
                conversation_id=int(row["id"]),
            )
        except Exception as exc:
            logger.debug("[RAG] prewarm on monitor start skipped: %s", exc)

    def _message_exists_in_history(
        self,
        conversation_id: int,
        message_data: dict,
        occurrence_index: int = 1,
    ) -> bool:
        """Check whether a buffered realtime message has already been migrated.

        occurrence_index 为该消息在缓冲区同签名（发送方+类型+时间戳+内容）消息中的
        序号（从 1 开始）：历史表中同签名消息数达到该序号才判为已存在。
        """
        from ...db.connection import get_db

        conn = get_db()
        # 注意：不按 runtime_id 查 local_id —— 实时 runtime_id 与微信库 local_id 属于
        # 两个无关 ID 空间，数值撞车会把真实新消息误判为已存在而静默丢弃（W1）。
        # UIA 时间标签只有分钟精度、实时侧时间戳按分钟截断，同分钟消息落库后时间戳
        # 可能有秒级偏差，精确等值判重会把同分钟连发的相同内容消息静默丢掉；这里放宽
        # 为 ±59 秒窗口并按签名计数，仅当历史同签名数 >= 缓冲内序号时才判已存在（R4）。
        try:
            occurrence_index = max(1, int(occurrence_index))
        except (TypeError, ValueError):
            occurrence_index = 1
        timestamp = int(message_data.get('timestamp') or 0)
        count = conn.execute(
            '''
            SELECT COUNT(*)
            FROM messages
            WHERE conversation_id = ?
              AND is_sender = ?
              AND message_type = ?
              AND timestamp BETWEEN ? - 59 AND ? + 59
              AND COALESCE(content, '') = ?
            ''',
            (
                conversation_id,
                1 if message_data.get('sender_attr') == 'self' else 0,
                self._map_message_type(message_data.get('message_type')),
                timestamp,
                timestamp,
                message_data.get('content') or '',
            )
        ).fetchone()[0]
        return int(count or 0) >= occurrence_index

    def _ensure_checkpoint_table(self) -> None:
        """Ensure the realtime checkpoint table exists for resume probing."""
        from ...db.connection import get_db

        conn = get_db()
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS realtime_monitor_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                talker_key TEXT NOT NULL,
                talker_username TEXT,
                talker_display_name TEXT NOT NULL,
                last_batch_id TEXT,
                last_message_timestamp INTEGER NOT NULL,
                last_message_hash TEXT,
                last_runtime_id TEXT,
                last_message_preview TEXT,
                last_message_context TEXT,
                message_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'realtime',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(account_wxid, talker_key)
            )
            '''
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_realtime_checkpoint_account_updated ON realtime_monitor_checkpoints(account_wxid, updated_at DESC)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_realtime_checkpoint_account_display_name ON realtime_monitor_checkpoints(account_wxid, talker_display_name)'
        )
        columns = {
            str(row['name'])
            for row in conn.execute('PRAGMA table_info(realtime_monitor_checkpoints)').fetchall()
        }
        if 'last_message_context' not in columns:
            conn.execute('ALTER TABLE realtime_monitor_checkpoints ADD COLUMN last_message_context TEXT')
        conn.commit()

    def _save_monitor_checkpoint(
        self,
        batch_id: str,
        talker_username: str,
        talker_display_name: str,
        message_count: int,
    ) -> None:
        """Persist the last captured non-system message as a resume checkpoint."""
        talker_key = self._get_talker_key(talker_username, talker_display_name)
        if not talker_key or not batch_id:
            return

        account_wxid = self._resolve_account_wxid()
        messages = self.message_buffer.get_batch_messages(batch_id, account_wxid=account_wxid)
        last_message = None
        for msg in reversed(messages):
            if msg.get('sender_attr') == 'system':
                continue
            if not (msg.get('content') or '').strip() and not msg.get('runtime_id'):
                continue
            last_message = msg
            break

        if not last_message:
            return

        checkpoint_context = self._build_checkpoint_context(last_message, messages)
        checkpoint_context_json = (
            json.dumps(checkpoint_context, ensure_ascii=False)
            if checkpoint_context else None
        )

        self._ensure_checkpoint_table()
        from ...db.connection import get_db

        now_ts = int(time.time())
        conn = get_db()
        conn.execute(
            '''
            INSERT INTO realtime_monitor_checkpoints (
                account_wxid, talker_key, talker_username, talker_display_name, last_batch_id,
                last_message_timestamp, last_message_hash, last_runtime_id,
                last_message_preview, last_message_context, message_count, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'realtime', ?, ?)
            ON CONFLICT(account_wxid, talker_key) DO UPDATE SET
                talker_username = excluded.talker_username,
                talker_display_name = excluded.talker_display_name,
                last_batch_id = excluded.last_batch_id,
                last_message_timestamp = excluded.last_message_timestamp,
                last_message_hash = excluded.last_message_hash,
                last_runtime_id = excluded.last_runtime_id,
                last_message_preview = excluded.last_message_preview,
                last_message_context = excluded.last_message_context,
                message_count = excluded.message_count,
                updated_at = excluded.updated_at
            ''',
            (
                account_wxid,
                talker_key,
                talker_username or None,
                talker_display_name or talker_key,
                batch_id,
                int(last_message.get('timestamp') or now_ts),
                last_message.get('message_hash'),
                last_message.get('runtime_id'),
                (last_message.get('content') or '')[:120],
                checkpoint_context_json,
                int(message_count or 0),
                now_ts,
                now_ts,
            )
        )
        conn.commit()

    def get_resume_checkpoint(self, talker_display_name: str, talker_username: str = '', account_wxid: str = '') -> dict:
        """Return checkpoint information for the requested talker."""
        resolved_account_wxid = self._resolve_account_wxid(account_wxid)
        resolved_talker_username = self._resolve_talker_username(talker_username, talker_display_name, resolved_account_wxid)
        talker_key = self._get_talker_key(resolved_talker_username, talker_display_name)
        if not talker_key:
            return {'has_checkpoint': False}

        self._ensure_checkpoint_table()
        from ...db.connection import get_db

        conn = get_db()
        row = conn.execute(
            '''
            SELECT account_wxid, talker_key, talker_username, talker_display_name, last_batch_id,
                   last_message_timestamp, last_message_hash, last_runtime_id,
                   last_message_preview, last_message_context, message_count, source, created_at, updated_at
            FROM realtime_monitor_checkpoints
            WHERE account_wxid = ? AND talker_key = ?
            ''',
            (resolved_account_wxid, talker_key)
        ).fetchone()
        if not row and talker_display_name:
            row = conn.execute(
                '''
                SELECT account_wxid, talker_key, talker_username, talker_display_name, last_batch_id,
                       last_message_timestamp, last_message_hash, last_runtime_id,
                       last_message_preview, last_message_context, message_count, source, created_at, updated_at
                FROM realtime_monitor_checkpoints
                WHERE account_wxid = ? AND talker_display_name = ?
                ORDER BY updated_at DESC
                LIMIT 1
                ''',
                (resolved_account_wxid, talker_display_name)
            ).fetchone()

        if not row:
            return {'has_checkpoint': False}

        return {
            'has_checkpoint': True,
            'account_wxid': row['account_wxid'],
            'talker_key': row['talker_key'],
            'talker_username': row['talker_username'],
            'talker_display_name': row['talker_display_name'],
            'last_batch_id': row['last_batch_id'],
            'last_message_timestamp': row['last_message_timestamp'],
            'last_message_hash': row['last_message_hash'],
            'last_runtime_id': row['last_runtime_id'],
            'last_message_preview': row['last_message_preview'],
            'last_message_context': self._normalize_checkpoint_context(row['last_message_context']),
            'message_count': row['message_count'],
            'source': row['source'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }

    def get_resume_probe(
        self,
        talker_display_name: str,
        talker_username: str = '',
        threshold_seconds: int = 300,
        account_wxid: str = '',
    ) -> dict:
        """Return whether the UI should offer resume/backfill for this talker."""
        checkpoint = self.get_resume_checkpoint(talker_display_name, talker_username, account_wxid)
        if not checkpoint.get('has_checkpoint'):
            return {
                'has_checkpoint': False,
                'should_offer_resume': False,
                'threshold_seconds': int(threshold_seconds),
            }

        now_ts = int(time.time())
        gap_seconds = max(0, now_ts - int(checkpoint['last_message_timestamp']))
        checkpoint['has_checkpoint'] = True
        checkpoint['threshold_seconds'] = int(threshold_seconds)
        checkpoint['gap_seconds'] = gap_seconds
        checkpoint['should_offer_resume'] = gap_seconds >= int(threshold_seconds)

        # 缺口已被导入覆盖则不再询问：距上次监听超阈值就弹「是否补全」的
        # 提示，从不检查缺口消息是否已通过增量导入进库——频繁导入的用户
        # 每次进监听都被打扰（实测：丰瑶会话每次必弹）。
        if checkpoint['should_offer_resume'] and self._checkpoint_gap_covered_by_import(
            checkpoint, resolved_account_wxid
        ):
            checkpoint['should_offer_resume'] = False
            checkpoint['resume_skip_reason'] = 'covered_by_import'
        return checkpoint

    def _checkpoint_gap_covered_by_import(self, checkpoint: dict, account_wxid: str) -> bool:
        """检查 checkpoint 之后该会话是否已有导入消息（缺口已被导入补上）。"""
        try:
            from ...db.connection import get_db

            talker_username = str(checkpoint.get('talker_username') or '').strip()
            if not talker_username:
                return False
            conn = get_db()
            conv = conn.execute(
                "SELECT id FROM conversations WHERE account_wxid = ? AND username = ? "
                "AND is_deleted = 0",
                (account_wxid, talker_username),
            ).fetchone()
            if not conv:
                return False
            covered = conn.execute(
                "SELECT 1 FROM messages WHERE conversation_id = ? AND source = 'long' "
                "AND timestamp > ? LIMIT 1",
                (conv['id'], int(checkpoint.get('last_message_timestamp') or 0)),
            ).fetchone()
            return covered is not None
        except Exception as exc:
            logger.debug("[Checkpoint] 缺口覆盖检查失败（按未覆盖处理）: %s", exc)
            return False

    def _checkpoint_match_reason(
        self,
        checkpoint: dict,
        msg,
        resolved_timestamp: int,
        visible_messages: list | None = None,
        visible_index: int = -1,
    ) -> str | None:
        """Return the checkpoint match reason, or None if the message is not the saved checkpoint."""
        checkpoint_runtime_id = normalize_text(str(checkpoint.get('last_runtime_id') or ''))
        visible_runtime_id = normalize_text(str(getattr(msg, 'id', '') or ''))
        if checkpoint_runtime_id and visible_runtime_id and checkpoint_runtime_id == visible_runtime_id:
            return 'runtime_id_exact'

        checkpoint_preview = re.sub(r'\s+', ' ', str(checkpoint.get('last_message_preview') or '')).strip()
        checkpoint_ts = int(checkpoint.get('last_message_timestamp') or 0)
        content = re.sub(r'\s+', ' ', str(getattr(msg, 'content', '') or '')).strip()

        if not checkpoint_preview or not content:
            return None

        exact_match = checkpoint_preview == content
        truncated_prefix_match = (
            len(checkpoint_preview) >= 100 and
            content.startswith(checkpoint_preview)
        )
        if not (exact_match or truncated_prefix_match):
            return None

        checkpoint_context = self._normalize_checkpoint_context(
            checkpoint.get('last_message_context')
        )
        if checkpoint_context and visible_messages and visible_index >= 0:
            visible_context = self._extract_visible_checkpoint_context(
                visible_messages,
                visible_index,
            )
            context_reason = self._context_window_match_reason(
                checkpoint_context,
                visible_context,
            )
            if context_reason:
                return context_reason

        ts_diff = abs(int(resolved_timestamp or 0) - checkpoint_ts)
        if ts_diff > 300:
            if exact_match and len(checkpoint_preview) >= 8:
                _print(
                    "[Backfill] checkpoint 文本精确命中，但时间差过大，降级按内容命中: "
                    f"content={content!r}, resolved_ts={resolved_timestamp}, checkpoint_ts={checkpoint_ts}, diff={ts_diff}"
                )
                return 'content_exact_fallback'
            return None

        return 'content_exact' if exact_match else 'content_truncated_prefix'

    def _store_backfill_messages(
        self,
        talker_username: str,
        talker_display_name: str,
        messages: list[dict],
    ) -> dict:
        """Persist recovered history directly into messages with a backfill source tag."""
        from ...db.connection import get_db

        talker_key = self._get_talker_key(talker_username, talker_display_name)
        if not talker_key or not messages:
            return {
                'inserted_count': 0,
                'existing_count': 0,
            }

        conn = get_db()
        conversation_id = self._get_or_create_conversation_id(talker_key, talker_display_name or talker_key)
        inserted = 0
        existing = 0
        latest_ts = 0
        inserted_samples: list[str] = []
        existing_samples: list[str] = []

        # 遍历时累计同签名（发送方+类型+时间戳+内容）出现次数作为判重序号，
        # 配合 ±59 秒窗口计数判重，避免同分钟连发的相同内容消息被静默丢掉（R4）
        occurrence_counts: dict[tuple, int] = {}
        for message_data in messages:
            latest_ts = max(latest_ts, int(message_data.get('timestamp') or 0))
            signature = (
                1 if message_data.get('sender_attr') == 'self' else 0,
                self._map_message_type(message_data.get('message_type')),
                int(message_data.get('timestamp') or 0),
                message_data.get('content') or '',
            )
            occurrence_counts[signature] = occurrence_counts.get(signature, 0) + 1
            if self._message_exists_in_history(
                conversation_id,
                message_data,
                occurrence_index=occurrence_counts[signature],
            ):
                existing += 1
                if len(existing_samples) < 12:
                    existing_samples.append(
                        f"{message_data.get('sender_attr')}|{int(message_data.get('timestamp') or 0)}|{(message_data.get('content') or '')!r}"
                    )
                continue

            # runtime_id 与微信库 local_id 属不同 ID 空间，实时消息不占用 local_id（W1）
            local_id = None
            cursor = conn.execute(
                '''
                INSERT OR IGNORE INTO messages
                (conversation_id, local_id, talker, sender, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'realtime_backfill', ?)
                ''',
                (
                    conversation_id,
                    local_id,
                    talker_key,
                    None if message_data.get('sender_attr') == 'self' else talker_key,
                    1 if message_data.get('sender_attr') == 'self' else 0,
                    self._map_message_type(message_data.get('message_type')),
                    message_data.get('content') or '',
                    int(message_data.get('timestamp') or int(time.time())),
                    int(time.time()),
                )
            )
            if cursor.rowcount == 1:
                inserted += 1
                if len(inserted_samples) < 12:
                    inserted_samples.append(
                        f"{message_data.get('sender_attr')}|{int(message_data.get('timestamp') or 0)}|{(message_data.get('content') or '')!r}"
                    )
            else:
                existing += 1

        if inserted:
            total_count = conn.execute(
                'SELECT COUNT(*) FROM messages WHERE conversation_id = ?',
                (conversation_id,)
            ).fetchone()[0]
            conn.execute(
                '''
                UPDATE conversations
                SET display_name = ?, updated_at = ?, message_count = ?
                WHERE id = ?
                ''',
                (
                    talker_display_name or talker_key,
                    latest_ts or int(time.time()),
                    total_count,
                    conversation_id,
                )
            )
            conn.commit()
            # 回溯写入也是消息集变化：分析结果打脏（失败仅丢提示）
            try:
                from ..analysis.analysis_state import mark_conversations_stale

                mark_conversations_stale([conversation_id])
            except Exception as stale_e:
                logger.debug("[分析状态] backfill stale mark skipped: %s", stale_e)

        if messages:
            _print(f"[Backfill] 已存在样本({existing}/{len(messages)}): {existing_samples}")
            _print(f"[Backfill] 实际插入样本({inserted}/{len(messages)}): {inserted_samples}")

        return {
            'inserted_count': inserted,
            'existing_count': existing,
        }

    def _merge_backfill_into_current_batch(
        self,
        talker_username: str,
        talker_display_name: str,
        messages: list[dict],
    ) -> int:
        """Append recovered messages into the active realtime batch for polling and archive."""
        if not self.current_batch_id or not messages:
            return 0

        merged = 0
        for message_data in messages:
            message_hash = message_data.get('message_hash')
            if message_hash and self.message_buffer.message_exists(message_hash, self.current_account_wxid):
                self.seen_hashes.add(message_hash)
                continue

            success = self.message_buffer.save_message(
                self.current_batch_id,
                self.current_account_wxid,
                talker_username,
                talker_display_name,
                message_data,
            )
            if not success:
                continue

            merged += 1
            if message_hash:
                self.seen_hashes.add(message_hash)
                content = str(message_data.get('content') or '').strip()
                if message_data.get('sender_attr') != 'system' and content:
                    try:
                        self.sentiment_service.analyze_and_cache(
                            message_id=message_hash,
                            text=content,
                        )
                    except Exception as e:
                        _print(f"[Backfill] 情感缓存失败: {e}")

        return merged

    def _run_backfill_in_current_chat_context(
        self,
        probe: dict,
        talker_username: str,
        talker_display_name: str,
        max_scroll_rounds: int = 80,
        wheel_times: int = 3,
    ) -> dict:
        """Run backfill using the current wx/chat context without re-running ChatWith."""
        collected: dict[str, dict] = {}
        seen_top_signature = None
        stagnant_rounds = 0
        checkpoint_found = False
        latest_step = min(8, max(int(wheel_times or 1) + 3, 6))

        _print(f"[Backfill] 预定位到最新消息区域，scroll_step={latest_step}")
        self._scroll_chat_to_latest(
            max_rounds=18,
            wheel_times=latest_step,
            stagnant_threshold=3,
        )

        for round_index in range(1, max_scroll_rounds + 1):
            visible_messages = self.wx.GetAllMessage() if self.wx else []
            if not visible_messages:
                _print(f"[Backfill] 第 {round_index} 轮未读取到可见消息，停止回溯")
                break

            _print(f"[Backfill] 第 {round_index}/{max_scroll_rounds} 轮，可见消息 {len(visible_messages)} 条")

            visible_top_signature = self._visible_message_signature(visible_messages, from_tail=False)
            if visible_top_signature == seen_top_signature:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
                seen_top_signature = visible_top_signature

            self._last_known_ts = 0
            checkpoint_index = -1
            round_messages: list[dict] = []
            round_identity_counts: dict[str, int] = {}

            for idx, msg in enumerate(visible_messages):
                sender_attr = 'self' if getattr(msg, 'is_self', False) else 'friend'
                if getattr(msg, 'is_system', False):
                    sender_attr = 'system'
                content = str(getattr(msg, 'content', '') or '')
                resolved_timestamp = self._resolve_message_timestamp(msg, sender_attr, content)

                if sender_attr == 'system':
                    continue

                match_reason = self._checkpoint_match_reason(
                    probe,
                    msg,
                    resolved_timestamp,
                    visible_messages=visible_messages,
                    visible_index=idx,
                )
                if match_reason:
                    _print(
                        "[Backfill] 命中 checkpoint: "
                        f"reason={match_reason}, "
                        f"content={content!r}, "
                        f"runtime_id={getattr(msg, 'id', None)!r}, "
                        f"hash={getattr(msg, 'hash', None)!r}, "
                        f"timestamp={resolved_timestamp}"
                    )
                    checkpoint_index = idx
                    checkpoint_found = True
                    continue

                base_identity = self._message_identity(msg)
                round_identity_counts[base_identity] = round_identity_counts.get(base_identity, 0) + 1
                identity = f"{base_identity}#occ{round_identity_counts[base_identity]}"
                runtime_id = str(getattr(msg, 'id', '') or '')
                round_messages.append({
                    'identity': identity,
                    'message_hash': build_message_hash(
                        self._listener_profile or getattr(self.wx, 'listener_profile', '') or 'unknown',
                        sender_attr,
                        getattr(msg, 'type', 'text'),
                        content,
                        int(resolved_timestamp or 0),
                        runtime_id or f"{idx}:{round_index}:{round_identity_counts[base_identity]}",
                    ),
                    'runtime_id': runtime_id,
                    'sender_attr': sender_attr,
                    'content': content,
                    'message_type': getattr(msg, 'type', 'text'),
                    'timestamp': resolved_timestamp,
                    'visible_index': idx,
                    'round_index': round_index,
                })

            if checkpoint_found:
                round_messages = [
                    item for item in round_messages
                    if int(item.get('visible_index', -1)) > checkpoint_index
                ]
                _print(
                    f"[Backfill] 第 {round_index} 轮命中 checkpoint，位置 idx={checkpoint_index}，"
                    f"本轮保留 {len(round_messages)} 条较新消息"
                )
            else:
                _print(f"[Backfill] 第 {round_index} 轮未命中 checkpoint，暂存 {len(round_messages)} 条消息")

            for item in round_messages:
                identity = str(item.pop('identity'))
                collected[identity] = item

            if checkpoint_found:
                break

            if stagnant_rounds >= 6:
                _print("[Backfill] 可见顶部消息连续未变化，停止继续上翻")
                break

            proximity = self._estimate_backfill_checkpoint_proximity(probe, visible_messages)
            time_gap_seconds = self._estimate_backfill_time_gap_seconds(probe, visible_messages)
            scroll_direction = self._choose_backfill_scroll_direction(
                proximity=proximity,
                time_gap_seconds=time_gap_seconds,
            )
            scroll_step = self._choose_backfill_scroll_step(
                checkpoint=probe,
                visible_messages=visible_messages,
                round_index=round_index,
                default_wheel_times=wheel_times,
                proximity=proximity,
                time_gap_seconds=time_gap_seconds,
            )
            scroll_repeats = self._choose_backfill_scroll_repeats(
                proximity=proximity,
                time_gap_seconds=time_gap_seconds,
            )
            _print(
                f"[Backfill] 第 {round_index} 轮继续滚动，direction={scroll_direction}, "
                f"scroll_step={scroll_step}, repeats={scroll_repeats}, "
                f"time_gap_seconds={time_gap_seconds}"
            )
            moved = False
            for _ in range(max(1, int(scroll_repeats or 1))):
                if scroll_direction == 'down':
                    moved = self._scroll_chat_history_down(wheel_times=scroll_step)
                else:
                    moved = self._scroll_chat_history_up(wheel_times=scroll_step)
                if not moved:
                    break
            if not moved:
                break

        if not checkpoint_found:
            return {
                'success': False,
                'inserted_count': 0,
                'message': '回溯达到阈值仍未找到断点，建议重新导入数据库',
                'need_reimport': True,
                'scanned_count': len(collected),
            }

        ordered_messages = sorted(
            collected.values(),
            key=lambda item: (
                int(item.get('timestamp') or 0),
                int(item.get('round_index') or 0),
                int(item.get('visible_index') or 0),
                str(item.get('runtime_id') or ''),
                item.get('content') or '',
            )
        )
        candidate_samples = [
            f"{item.get('sender_attr')}|{int(item.get('timestamp') or 0)}|{(item.get('content') or '')!r}"
            for item in ordered_messages[:12]
        ]
        _print(f"[Backfill] 候选样本({len(ordered_messages)}): {candidate_samples}")
        store_result = self._store_backfill_messages(
            talker_username=talker_username,
            talker_display_name=talker_display_name,
            messages=ordered_messages,
        )
        merged_batch_count = self._merge_backfill_into_current_batch(
            talker_username=talker_username,
            talker_display_name=talker_display_name,
            messages=ordered_messages,
        )
        inserted_count = int(store_result.get('inserted_count') or 0)
        existing_count = int(store_result.get('existing_count') or 0)
        _print(
            "[Backfill] 汇总: "
            f"当前命中轮保留={len(round_messages) if checkpoint_found else 0}, "
            f"最终候选={len(ordered_messages)}, "
            f"已存在跳过={existing_count}, "
            f"实际插入={inserted_count}, "
            f"当前batch并入={merged_batch_count}"
        )
        return {
            'success': True,
            'inserted_count': inserted_count,
            'existing_count': existing_count,
            'merged_batch_count': merged_batch_count,
            'scanned_count': len(ordered_messages),
            'message': f'回溯完成，补入 {inserted_count} 条消息',
            'need_reimport': False,
        }

    def run_backfill(
        self,
        talker_display_name: str,
        talker_username: str = '',
        threshold_seconds: int = 300,
        max_scroll_rounds: int = 80,
        wheel_times: int = 3,
    ) -> dict:
        """Backfill missing history between the last checkpoint and now."""
        if self.is_monitoring:
            return {
                'success': False,
                'message': '当前存在进行中的监听任务',
                'need_reimport': False,
            }

        probe = self.get_resume_probe(
            talker_display_name=talker_display_name,
            talker_username=talker_username,
            threshold_seconds=threshold_seconds,
        )
        if not probe.get('has_checkpoint'):
            return {
                'success': True,
                'inserted_count': 0,
                'message': '未找到可用断点，无需回溯',
                'need_reimport': False,
            }
        if not probe.get('should_offer_resume'):
            return {
                'success': True,
                'inserted_count': 0,
                'message': '断点时间间隔未达到回溯阈值',
                'need_reimport': False,
                'gap_seconds': probe.get('gap_seconds', 0),
            }

        self._session_generation += 1  # 回溯接管单例（R2）
        backfill_generation = self._session_generation
        self.current_display_name = talker_display_name
        self.current_talker = talker_username
        self._last_known_ts = 0

        try:
            self._create_wechat_instance_with_recovery(phase="backfill")
            self._bring_wechat_to_front()
            time.sleep(1.0)

            switched = False
            for target_name in self._build_chatwith_candidates():
                if self._try_chat_with(target_name):
                    switched = True
                    break
            if not switched:
                return {
                    'success': False,
                    'message': f"回溯前切换聊天失败: {self._chat_error}",
                    'need_reimport': False,
                }

            return self._run_backfill_in_current_chat_context(
                probe=probe,
                talker_username=talker_username,
                talker_display_name=talker_display_name,
                max_scroll_rounds=max_scroll_rounds,
                wheel_times=wheel_times,
            )
        finally:
            if self._session_generation != backfill_generation:
                # 回溯期间已有新监听会话启动并接管单例状态：
                # 不得清空新会话字段、不得销毁新会话的 wx 实例（R2）
                _print("⏭️ 回溯结束：检测到新监听会话已启动，跳过单例状态清理")
            else:
                self.current_display_name = None
                self.current_talker = None
                self._last_known_ts = 0
                self._reset_wechat_instance()

    def _migrate_buffer_to_messages(self, batch_id: str, talker_username: str, talker_display_name: str) -> int:
        """Move realtime buffered messages into the historical messages table."""
        from ...db.connection import get_db

        talker_key = self._get_talker_key(talker_username, talker_display_name)
        if not batch_id or not talker_key:
            return 0

        buffer_messages = self.message_buffer.get_batch_messages(batch_id, account_wxid=self.current_account_wxid)
        if not buffer_messages:
            return 0

        conn = get_db()
        conversation_id = self._get_or_create_conversation_id(
            talker_key,
            talker_display_name or talker_key
        )
        migrated = 0
        latest_ts = 0

        # 遍历时累计同签名（发送方+类型+时间戳+内容）出现次数作为判重序号，
        # 配合 ±59 秒窗口计数判重，避免同分钟连发的相同内容消息被静默丢掉（R4）
        occurrence_counts: dict[tuple, int] = {}
        for msg in buffer_messages:
            if msg.get('sender_attr') == 'system':
                continue
            signature = (
                1 if msg.get('sender_attr') == 'self' else 0,
                self._map_message_type(msg.get('message_type')),
                int(msg.get('timestamp') or 0),
                msg.get('content') or '',
            )
            occurrence_counts[signature] = occurrence_counts.get(signature, 0) + 1
            if self._message_exists_in_history(
                conversation_id,
                msg,
                occurrence_index=occurrence_counts[signature],
            ):
                continue

            # runtime_id 与微信库 local_id 属不同 ID 空间，实时消息不占用 local_id（W1）
            local_id = None
            timestamp = int(msg.get('timestamp') or int(time.time()))
            latest_ts = max(latest_ts, timestamp)

            cursor = conn.execute(
                '''
                INSERT OR IGNORE INTO messages
                (conversation_id, local_id, talker, sender, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'realtime', ?)
                ''',
                (
                    conversation_id,
                    local_id,
                    talker_key,
                    None if msg.get('sender_attr') == 'self' else talker_key,
                    1 if msg.get('sender_attr') == 'self' else 0,
                    self._map_message_type(msg.get('message_type')),
                    msg.get('content') or '',
                    timestamp,
                    int(time.time()),
                )
            )
            if cursor.rowcount == 1:
                migrated += 1

        if migrated:
            total_count = conn.execute(
                'SELECT COUNT(*) FROM messages WHERE conversation_id = ?',
                (conversation_id,)
            ).fetchone()[0]
            conn.execute(
                '''
                UPDATE conversations
                SET display_name = ?, updated_at = ?, message_count = ?
                WHERE id = ?
                ''',
                (
                    talker_display_name or talker_key,
                    latest_ts or int(time.time()),
                    total_count,
                    conversation_id,
                )
            )
            conn.commit()
            # 监听期间的消息并入历史：分析结果打脏（失败仅丢提示）
            try:
                from ..analysis.analysis_state import mark_conversations_stale

                mark_conversations_stale([conversation_id])
            except Exception as stale_e:
                logger.debug("[分析状态] migrate stale mark skipped: %s", stale_e)
        else:
            conn.commit()

        self.message_buffer.mark_as_processed(batch_id, self.current_account_wxid)

        return migrated

    def stop_monitoring(self) -> dict:
        """
        停止实时监听
        
        Returns:
            {
                'success': bool,
                'batch_id': str,
                'message_count': int,
                'message': str
            }
        """
        _print("\n🛑 收到停止监听请求")
        _print(f"📊 当前监听状态: is_monitoring={self.is_monitoring}")
        
        if not self.is_monitoring:
            _print("⚠️  当前没有活跃的监听任务")
            return {
                'success': False,
                'message': '当前没有监听任务',
                'error': '未找到活跃的监听会话'
            }
        
        try:
            _print(f"⏹️  正在停止监听: {self.current_display_name}")
            
            # 1. 停止轮询线程
            self.stop_polling = True
            stop_event = self._stop_event
            if stop_event is not None:
                stop_event.set()
            _print("🛑 已发送停止轮询信号")
            
            # 2. 清理状态标志（防止前端继续查询时认为还在监听）
            self.is_monitoring = False
            _print("✅ 监听状态已设为 False")
            
            # 3. 等待轮询线程结束（最多约5秒，给当前轮处理留出收尾时间）
            if self.polling_thread and self.polling_thread.is_alive():
                _print("⏳ 等待轮询线程结束...")
                waited = 0.0
                while self.polling_thread.is_alive() and waited < 5.0:
                    self.polling_thread.join(timeout=0.5)
                    waited += 0.5
                if self.polling_thread.is_alive():
                    _print(f"⚠️  轮询线程未在{waited:.1f}秒内结束，继续收尾流程...")
                else:
                    _print(f"✅ 轮询线程已结束（等待 {waited:.1f} 秒）")
            
            # 4. 不调用 RemoveListenChat（避免卡顿）
            if self.wx and self.current_display_name:
                try:
                    _print("⚠️  跳过 RemoveListenChat 调用（避免卡顿）")
                except Exception as e:
                    _print(f"❌ 移除监听异常: {e}")
            
            # 3. 获取消息数量
            message_count = self.message_buffer.get_batch_count(self.current_batch_id, self.current_account_wxid)
            
            # 4. 保存批次ID用于返回
            batch_id = self.current_batch_id
            talker_username = self.current_talker
            talker_display_name = self.current_display_name

            self._save_monitor_checkpoint(
                batch_id,
                talker_username,
                talker_display_name,
                message_count
            )

            migrated_count = self._migrate_buffer_to_messages(
                batch_id,
                talker_username,
                talker_display_name
            )
            if migrated_count:
                _print(f"✅ 已迁移 {migrated_count} 条消息到历史数据表")
            
            # 5. 记录事件
            self._log_runtime_event('realtime_monitor_stop', {
                'batch_id': batch_id,
                'talker_username': talker_username,
                'talker_display_name': talker_display_name,
                'message_count': message_count,
                'migrated_count': migrated_count
            })
            
            # 6. 清理状态
            self.current_batch_id = None
            self.current_talker = None
            self.current_display_name = None
            self.seen_hashes.clear()
            self.seen_message_keys.clear()
            self._last_known_ts = 0
            self._chat_timed_out = False
            self._chat_ui_inaccessible = False
            self._uia_recovery_attempts = 0
            self._last_uia_recovery = None
            self._uia_recovery_required = False
            self._uia_recovery_in_progress = False
            self._uia_recovery_context = {}
            self._resume_mode = 'skip'
            self._stop_event = None
            
            # 7. 重置情绪追踪器
            if self.emotion_tracker:
                self.emotion_tracker.reset()
                self.emotion_tracker = None
            self._last_auto_suggestion_time = 0
            self._reset_wechat_instance()
            
            _print(f"✅ 监听已完全停止！累计抓取: {message_count} 条\n")
            
            return {
                'success': True,
                'batch_id': batch_id,
                'message_count': message_count,
                'message': f'监听已停止,共抓取 {message_count} 条消息'
            }
            
        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 停止监听异常: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'message': '停止监听失败',
                'error': str(e)
            }
    
    
    def get_status(self) -> dict:
        """
        获取当前监听状态
        
        Returns:
            {
                'is_monitoring': bool,
                'talker_username': str or None,
                'talker_display_name': str or None,
                'batch_id': str or None,
                'message_count': int
            }
        """
        try:
            message_count = 0
            if self.is_monitoring and self.current_batch_id:
                message_count = self.message_buffer.get_batch_count(self.current_batch_id, self.current_account_wxid)
            recovery_snapshot = self._extract_uia_recovery_snapshot()
            
            # 检测轮询线程是否仍然存活
            polling_alive = (
                self.polling_thread is not None 
                and self.polling_thread.is_alive()
            )
            
            return {
                'is_monitoring': self.is_monitoring,
                'talker_username': self.current_talker,
                'talker_display_name': self.current_display_name,
                'account_wxid': self.current_account_wxid,
                'batch_id': self.current_batch_id,
                'message_count': message_count,
                'model_ready': self.sentiment_service.is_ready(),
                'chat_ready': self._chat_ready,
                'chat_error': self._chat_error,
                'uia_recovery_required': self._uia_recovery_required,
                'uia_recovery_in_progress': self._uia_recovery_in_progress,
                'uia_recovery_phase': (self._uia_recovery_context or {}).get('phase', ''),
                'polling_alive': polling_alive,
                'provider': self._provider_name or getattr(self.wx, 'backend_name', ''),
                'listener_profile': self._listener_profile or getattr(self.wx, 'listener_profile', ''),
                'wechat_version': self._wechat_version or getattr(self.wx, 'wechat_version', ''),
                'uia_recovery_summary': recovery_snapshot.get('summary', ''),
                'uia_recovery_final_status': recovery_snapshot.get('final_status', ''),
                'uia_recovery_actions': recovery_snapshot.get('action_steps', []),
                'uia_recovery_aborted': recovery_snapshot.get('aborted', False),
                'uia_recovery_abort_reason': recovery_snapshot.get('abort_reason', ''),
                'narrator_verification': recovery_snapshot.get('narrator_verification', {}),
            }
            
        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 获取状态失败: {e}")
            return {
                'is_monitoring': False,
                'error': str(e)
            }
    
    def _log_runtime_event(self, event_type: str, payload: dict):
        """
        记录运行时事件到数据库
        
        Args:
            event_type: 事件类型
            payload: 事件数据
        """
        try:
            import json
            from ...db.connection import get_db
            
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO runtime_events (event_type, payload_json, created_at)
                VALUES (?, ?, ?)
            ''', (event_type, json.dumps(payload, ensure_ascii=False), int(time.time())))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 记录运行时事件失败: {e}")
    
    def _handle_trigger_events(self, triggers, session_state: dict | None = None):
        """
        处理触发事件：根据触发模式决定是否生成建议并存入数据库
        
        Args:
            triggers: TriggerEvent 列表
        """
        session_state = session_state or self._build_session_state(self._monitor_session_token)
        if not self._session_is_current(session_state):
            return

        mode = self._suggestion_config.get('trigger_mode', 'semi_auto')
        
        if mode == 'manual':
            # 纯手动模式不自动生成建议，只打印日志
            for trigger in triggers:
                _print(f"📊 [手动模式] 检测到触发: {trigger.trigger_type} (已忽略)")
            return
        
        intent = self._suggestion_config.get('intent', 'maintain')
        batch_id = session_state.get('batch_id')
        display_name = session_state.get('display_name')
        account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
        
        for trigger in triggers:
            try:
                if not self._session_is_current(session_state):
                    return
                # 开场建议后的冷却窗:silence 触发通常源于监听启动前的旧静默
                # 基线,与开场建议内容重复,直接跳过。
                if (
                    trigger.trigger_type == 'silence'
                    and time.time() - getattr(self, '_listen_start_suggestion_at', 0) < 60
                ):
                    _print("🔕 [开场冷却] 跳过与开场建议重复的 silence 触发")
                    continue
                _print(f"🔔 触发事件: {trigger.trigger_type} (severity={trigger.severity})")
                
                # 构建完整的 context (融合 trigger.context 和 画外特征)
                # G1:所有入口统一走 assemble_generation_context,绑定稳定联系人范围。
                ctx = trigger.context.copy() if trigger.context else {}

                try:
                    from .generation_context import assemble_generation_context
                    assemble_generation_context(
                        ctx,
                        entrypoint='semi_auto_trigger',
                        account_wxid=account_wxid,
                        display_name=str(display_name or ''),
                        username=str(session_state.get('talker_username') or ''),
                        batch_id=str(batch_id or ''),
                        emotion_summary=(
                            self.emotion_tracker.get_emotion_summary() if self.emotion_tracker else None
                        ),
                        recent_limit=50,
                        renew_stale_profiles=_renew_profiles_in_background,
                    )
                except Exception as assemble_e:
                    _print(f"⚠️ 统一上下文装配失败,退回最小上下文: {assemble_e}")
                    ctx['display_name'] = display_name
                    ctx['account_wxid'] = account_wxid

                # 生成建议
                from .suggestion_engine import SuggestionEngineFactory
                engine_type = self._suggestion_config.get('engine_type', 'llm')
                engine = SuggestionEngineFactory.create(engine_type)
                result = engine.generate(
                    trigger.trigger_type, intent, ctx
                )
                if not self._session_is_current(session_state):
                    _print("[RealtimeMonitorService] 已忽略过期会话的建议结果")
                    return
                
                # 存入数据库
                self._save_suggestion_to_db(trigger, result, session_state=session_state)
                _print(f"💡 建议已生成: {result.summary}")
                
            except Exception as e:
                _print(f"⚠️ 生成建议失败: {e}")
    
    def _select_full_auto_trigger(self, runtime_triggers=None):
        """为 full_auto 模式选择一个合适的触发类型。"""
        from .trigger_resolver import resolve_suggestion_trigger

        resolved = resolve_suggestion_trigger(
            mode='full_auto',
            runtime_triggers=runtime_triggers,
            emotion_tracker=self.emotion_tracker,
        )
        return resolved.trigger_type, resolved.trigger_context

    def _handle_full_auto_suggestion(self, sentiment_result, runtime_triggers=None, session_state: dict | None = None):
        """
        全自动模式：每条对方消息都生成建议（受频率限制）
        """
        session_state = session_state or self._build_session_state(self._monitor_session_token)
        if not self._session_is_current(session_state):
            return

        now = time.time()
        rate_limit = self._suggestion_config.get('auto_rate_limit', 10)
        
        if now - self._last_auto_suggestion_time < rate_limit:
            return  # 频率限制内，跳过
        
        try:
            intent = self._suggestion_config.get('intent', 'maintain')
            account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))

            trigger_type, trigger_context = self._select_full_auto_trigger(runtime_triggers)
            if not trigger_type:
                _print("📭 [全自动] 当前消息未命中触发，且趋势不足以支撑建议，已跳过")
                return

            self._last_auto_suggestion_time = now
            
            from .suggestion_engine import SuggestionEngineFactory
            from .emotion_state_tracker import TriggerEvent
            engine = SuggestionEngineFactory.create(
                self._suggestion_config.get('engine_type', 'llm')
            )
            
            ctx = self._build_llm_suggestion_context(
                session_state, mode='full_auto', trigger_context=trigger_context,
            )

            result = engine.generate(trigger_type, intent, ctx)
            if not self._session_is_current(session_state):
                _print("[RealtimeMonitorService] 已忽略过期会话的全自动建议结果")
                return
            
            trigger = TriggerEvent(
                trigger_type=trigger_type,
                timestamp=now,
                severity='low',
                context=ctx.get('trigger_context', {'mode': 'full_auto'})
            )
            self._save_suggestion_to_db(trigger, result, session_state=session_state)
            _print(f"💡 [全自动] 建议已生成: {result.summary}")
            
        except Exception as e:
            _print(f"⚠️ [全自动] 生成建议失败: {e}")
    
    def _build_llm_suggestion_context(self, session_state, mode, trigger_context=None,
                                       recent_limit=50) -> dict:
        """构建建议生成上下文（最近消息/双方画像/历史增强/RAG 记忆）——全自动与开场建议共用。"""
        account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
        ctx = {'mode': mode}
        if trigger_context:
            ctx['trigger_context'] = {**trigger_context, 'mode': mode}
        # G1:统一装配函数,绑定稳定联系人范围;范围缺失时安全降级。
        try:
            from .generation_context import assemble_generation_context
            assemble_generation_context(
                ctx,
                entrypoint=str(mode or 'auto'),
                account_wxid=account_wxid,
                display_name=str(session_state.get('display_name') or ''),
                username=str(session_state.get('talker_username') or ''),
                batch_id=str(session_state.get('batch_id') or ''),
                emotion_summary=(
                    self.emotion_tracker.get_emotion_summary() if self.emotion_tracker else None
                ),
                recent_limit=recent_limit,
                renew_stale_profiles=_renew_profiles_in_background,
            )
        except Exception as assemble_e:
            _print(f"⚠️ 统一上下文装配失败,退回最小上下文: {assemble_e}")
            if session_state.get('display_name'):
                ctx['display_name'] = session_state['display_name']
                ctx['account_wxid'] = account_wxid
        return ctx

    def _generate_listen_start_suggestion(self, session_state: dict | None = None) -> None:
        """开场建议：监听就绪后基于窗口内最近消息立即生成一次（此前面板空到首条新消息）。"""
        session_state = session_state or self._build_session_state(self._monitor_session_token)
        if not self._session_is_current(session_state):
            return
        if self._suggestion_config.get('trigger_mode', 'semi_auto') == 'manual':
            return  # 纯手动模式：用户已选择不自动生成
        try:
            ctx = self._build_llm_suggestion_context(
                session_state, mode='listen_start', recent_limit=12,
                trigger_context={'source': 'listen_start', 'note': '基于最近对话生成的开场建议'},
            )
            if len(ctx.get('recent_messages') or []) < 4:
                # 基线消息不落 buffer——回退到基线暂存的窗口尾部
                tail = session_state.get('baseline_tail') or []
                if len(tail) >= 4:
                    ctx['recent_messages'] = tail
                else:
                    _print("💭 最近消息不足 4 条，跳过开场建议")
                    return
            intent = self._suggestion_config.get('intent', 'maintain')
            from .emotion_state_tracker import TriggerEvent
            from .suggestion_engine import SuggestionEngineFactory
            engine = SuggestionEngineFactory.create(
                self._suggestion_config.get('engine_type', 'llm')
            )
            result = engine.generate('manual_request', intent, ctx)
            if not self._session_is_current(session_state):
                _print("[RealtimeMonitorService] 已忽略过期会话的开场建议结果")
                return
            trigger = TriggerEvent(
                trigger_type='manual_request',
                timestamp=time.time(),
                severity='low',
                context=ctx.get('trigger_context', {'source': 'listen_start'}),
            )
            self._save_suggestion_to_db(trigger, result, session_state=session_state)
            # 开场建议已覆盖"当前该说什么";短时间内跳过 silence 类自动触发,
            # 避免监听刚启动就同时弹出"开场建议+体面降温"两条重复卡片。
            self._listen_start_suggestion_at = time.time()
            _print("💡 [开场] 基于最近对话的建议已生成(60s 内抑制 silence 自动触发)")
        except Exception as e:
            _print(f"⚠️ [开场] 生成建议失败: {e}")

    def _save_suggestion_to_db(self, trigger, result, session_state: dict | None = None):
        """
        将建议存入 realtime_suggestions 表
        """
        try:
            session_state = session_state or self._build_session_state(self._monitor_session_token)
            batch_id = session_state.get('batch_id')
            if not batch_id:
                return

            from ...db.connection import get_db
            
            conn = get_db()
            
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
            
            cursor = conn.cursor()
            account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
            cursor.execute('''
                INSERT INTO realtime_suggestions
                (account_wxid, batch_id, trigger_type, intent, severity, summary, speeches,
                 confidence, status, engine_type, trigger_context, created_at, reply, thought_process)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account_wxid,
                batch_id,
                result.trigger_type,
                result.intent,
                result.severity,
                result.summary,
                json.dumps(result.speeches, ensure_ascii=False),
                result.confidence,
                'attribution_window',
                self._suggestion_config.get('engine_type', 'llm'),
                json.dumps(trigger.context, ensure_ascii=False) if trigger.context else None,
                int(time.time()),
                getattr(result, 'reply', None),
                getattr(result, 'thought_process', None)
            ))
            suggestion_id = cursor.lastrowid
            try:
                rag_log_id = getattr(result, 'rag_log_id', None)
                if rag_log_id:
                    from .rag.context_builder import RagContextBuilder

                    RagContextBuilder().attach_log_to_suggestion(rag_log_id, suggestion_id)
            except Exception as rag_log_e:
                _print(f"⚠️ RAG 检索日志关联建议失败: {rag_log_e}")
            try:
                from .feedback_attribution import SuggestionFeedbackAttributor
                from ...db.connection import get_db as _get_db

                SuggestionFeedbackAttributor.schedule_check(_get_db, suggestion_id)
            except Exception as attr_schedule_e:
                _print(f"⚠️ 反馈归因窗口调度失败: {attr_schedule_e}")
            try:
                from .suggestion_observer import EVENT_SHOWN, record_observation

                record_observation(
                    conn,
                    suggestion_id=suggestion_id,
                    account_wxid=account_wxid,
                    event_type=EVENT_SHOWN,
                    batch_id=batch_id,
                    display_name=session_state.get('display_name'),
                    trigger_type=result.trigger_type,
                )
            except Exception as obs_e:
                _print(f"⚠️ 建议观察记录失败: {obs_e}")
            conn.commit()
            
        except Exception as e:
            _print(f"⚠️ 保存建议到数据库失败: {e}")
    
    def get_suggestion_config(self) -> dict:
        """获取 AI 建议配置"""
        config = dict(self._suggestion_config)
        config['listener_backend'] = self._listener_backend
        return config
    
    def set_suggestion_config(self, config: dict):
        """更新 AI 建议配置"""
        for key in ('trigger_mode', 'intent', 'auto_rate_limit', 'engine_type'):
            if key in config:
                self._suggestion_config[key] = config[key]
        if 'listener_backend' in config:
            self._listener_backend = normalize_listener_backend(config['listener_backend'])
        _print(f"[RealtimeMonitorService] 建议配置已更新: {self._suggestion_config}")

    def _check_feedback(
        self,
        user_message: str,
        session_state: dict | None = None,
        user_message_type: int | str | None = None,
    ):
        """
        隐式反馈：将用户实际发送的消息与最近的 AI 建议进行对比，
        提取调教规则。
        """
        try:
            session_state = session_state or self._build_session_state(self._monitor_session_token)
            if not self._session_is_current(session_state):
                return

            batch_id = session_state.get('batch_id')
            display_name = session_state.get('display_name') or ''
            account_wxid = self._resolve_account_wxid(session_state.get('account_wxid'))
            if not batch_id:
                return

            from ...db.connection import get_db
            conn = get_db()

            # 查询归因窗口内尚未完成反馈的建议。不能把下一条消息直接当作最终反馈。
            cutoff = int(time.time()) - 600
            cursor = conn.execute('''
                SELECT id, speeches FROM realtime_suggestions
                WHERE account_wxid = ? AND batch_id = ?
                  AND status IN ('pending', 'displayed', 'attribution_window')
                  AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
            ''', (account_wxid, batch_id, cutoff))

            row = cursor.fetchone()
            if not row:
                return  # 没有待处理建议，跳过

            suggestion_id = row['id']
            speeches = json.loads(row['speeches'])
            reserve = conn.execute(
                '''
                UPDATE realtime_suggestions
                SET status = 'feedback_processing'
                WHERE account_wxid = ? AND id = ?
                  AND status IN ('pending', 'displayed', 'attribution_window')
                ''',
                (account_wxid, suggestion_id)
            )
            conn.commit()
            if reserve.rowcount != 1:
                return

            _print(f"\ud83d\udd0d [反馈归因] 检测到用户发消息，进入归因窗口 (id={suggestion_id})")

            # 调用规则提取器
            from .feedback_rule_extractor import FeedbackRuleExtractor
            extractor = FeedbackRuleExtractor()
            captured_user_message = str(user_message or '')
            captured_display_name = str(display_name or '')

            # 在后台线程中执行（避免阻塞消息轮询）
            import threading
            def do_extract():
                try:
                    from .feedback_attribution import SuggestionFeedbackAttributor

                    try:
                        attr = SuggestionFeedbackAttributor(get_db()).attribute(
                            suggestion_id=suggestion_id,
                            allow_pending=True,
                        )
                    except Exception as attr_e:
                        _print(f"⚠️ [反馈归因] 窗口归因不可用，使用旧兼容路径: {attr_e}")
                        attr = {
                            "pending": False,
                            "attribution_type": "accepted",
                            "confidence": 0.0,
                            "final_message": captured_user_message,
                            "selected_speech": None,
                        }
                    if attr.get("pending"):
                        conn2 = get_db()
                        conn2.execute(
                            "UPDATE realtime_suggestions SET status = 'attribution_window' WHERE account_wxid = ? AND id = ?",
                            (account_wxid, suggestion_id),
                        )
                        conn2.commit()
                        return

                    attribution_type = attr.get("attribution_type")
                    if attribution_type not in {"accepted", "rewritten", "preface_then_reply"}:
                        conn2 = get_db()
                        conn2.execute(
                            "UPDATE realtime_suggestions SET status = 'feedback_collected' WHERE account_wxid = ? AND id = ?",
                            (account_wxid, suggestion_id),
                        )
                        conn2.commit()
                        return

                    feedback_analysis = extractor.analyze_feedback(
                        ai_speeches=speeches,
                        user_actual_message=attr.get("final_message") or captured_user_message,
                        display_name=captured_display_name,
                        suggestion_id=suggestion_id,
                        user_message_type=user_message_type,
                        account_wxid=str(session_state.get('account_wxid') or self.current_account_wxid or ''),
                    )
                    try:
                        from .suggestion_observer import (
                            EVENT_ADOPTED,
                            EVENT_REWRITTEN,
                            record_observation,
                        )

                        outcome = feedback_analysis.get('outcome')
                        if attribution_type in {'accepted', 'preface_then_reply'}:
                            outcome = 'adopted'
                        elif attribution_type == 'rewritten':
                            outcome = 'rewritten'
                        if outcome in {'adopted', 'rewritten'}:
                            record_observation(
                                conn2 := get_db(),
                                suggestion_id=suggestion_id,
                                account_wxid=account_wxid,
                                event_type=EVENT_ADOPTED if outcome == 'adopted' else EVENT_REWRITTEN,
                                similarity=feedback_analysis.get('max_similarity'),
                                selected_speech=attr.get('selected_speech') or feedback_analysis.get('selected_speech'),
                                actual_message=attr.get("final_message") or captured_user_message,
                                actual_message_type=user_message_type,
                                metadata={
                                    'attribution_type': attribution_type,
                                    'attribution_confidence': attr.get('confidence'),
                                    'rule_source': feedback_analysis.get('rule_source'),
                                    'rule_count': len(feedback_analysis.get('rules') or []),
                                },
                            )
                            conn2.commit()
                    except Exception as obs_e:
                        _print(f"⚠️ [隐式反馈] 记录观察事件失败: {obs_e}")

                    extracted_rules = feedback_analysis.get('rules') or []
                    if extracted_rules:
                        _print(
                            "\ud83d\udcdd [隐式反馈] 提取到新规则: "
                            + " / ".join(
                                str(item.get('rule', '')).strip()
                                for item in extracted_rules
                                if str(item.get('rule', '')).strip()
                            )
                        )

                    # 标记建议为已反馈。即使这次没有提取到新规则，也不能卡在 feedback_processing。
                    conn2 = get_db()
                    conn2.execute(
                        "UPDATE realtime_suggestions SET status = 'feedback_collected' WHERE account_wxid = ? AND id = ?",
                        (account_wxid, suggestion_id)
                    )
                    conn2.commit()
                except Exception as e:
                    try:
                        conn2 = get_db()
                        conn2.execute(
                            "UPDATE realtime_suggestions SET status = 'feedback_failed' WHERE account_wxid = ? AND id = ?",
                            (account_wxid, suggestion_id)
                        )
                        conn2.commit()
                    except Exception:
                        pass
                    _print(f"⚠️ [隐式反馈] 提取失败: {e}")

            t = threading.Thread(target=do_extract, daemon=True)
            t.start()

        except Exception as e:
            _print(f"⚠️ [隐式反馈] 检查失败: {e}")

    def shutdown(self):
        """
        关闭服务,清理资源
        """
        try:
            if self.is_monitoring:
                self.stop_monitoring()
            
            if self.wx:
                try:
                    self.wx.StopListening()
                except:
                    pass
            
            logger.debug("[RealtimeMonitorService] 服务已关闭")
            
        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 关闭服务异常: {e}")
