"""
实时消息监听服务
基于监听 provider 实现单对象消息监听
"""
import logging
import time
import uuid
import json
import threading
import re
from .message_buffer import MessageBuffer
from .realtime_sentiment_service import RealtimeSentimentService
from .emotion_state_tracker import EmotionStateTracker
from .providers.base import UINotAccessibleError
from .providers.models import build_message_hash, normalize_text
from .providers.native_uia import TIME_LABEL_RE
from .providers.factory import normalize_listener_backend
from .safe_print import safe_print as _print
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file

logger = logging.getLogger(__name__)


from .uia_recovery import UiaRecoveryMixin
from .backfill_matcher import BackfillMatcherMixin
from .backfill_store import BackfillStoreMixin
from .suggestion_pipeline import SuggestionPipelineMixin


class RealtimeMonitorService(SuggestionPipelineMixin, BackfillStoreMixin, UiaRecoveryMixin, BackfillMatcherMixin):
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
            # db_watch 后端用 return False（不抛异常）表示切换失败：
            # 返回值必须检查，否则失败被当成功，监听「正常」启动但永远
            # 抓不到消息且无任何报错
            chat_ok = self.wx.ChatWith(target_name, expected_display_name=expected_name)
            if chat_ok is False:
                self._chat_error = (
                    f"切换聊天窗口失败（open_chat 返回 False）"
                    f"，target='{target_name}'，expected='{expected_name}'"
                    f"（常见原因：本地库解析不到该联系人或消息表不在任何分片）"
                )
                _print(f"[OpenChat] open_chat 返回 False: {self._chat_error}")
                return False
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
        resolved_account_wxid = self._resolve_account_wxid(account_wxid)
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
