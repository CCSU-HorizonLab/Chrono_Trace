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
from .providers.models import build_message_hash, normalize_text
from .safe_print import safe_print as _print
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file

logger = logging.getLogger(__name__)


from .backfill_matcher import BackfillMatcherMixin
from .backfill_store import BackfillStoreMixin
from .suggestion_pipeline import SuggestionPipelineMixin


# 建议配置内置默认（按联系人存储的缺省回落值；旧全局键已废弃不读）
SUGGESTION_CONFIG_DEFAULTS = {
    'trigger_mode': 'semi_auto',    # full_auto / semi_auto / manual
    'intent': 'maintain',           # intimate / maintain / distance
    'auto_rate_limit': 10,          # 全自动模式更新频率上限（秒）
    'engine_type': 'llm',
}


def suggestion_config_settings_key(conversation_id: int) -> str:
    """按联系人的建议配置 settings 键"""
    return f"suggestion_config:{int(conversation_id or 0)}"


def load_suggestion_config_for_contact(conversation_id: int) -> dict:
    """按联系人读取建议配置（settings 键 suggestion_config:{id}，无键/无联系人回落内置默认）"""
    config = dict(SUGGESTION_CONFIG_DEFAULTS)
    if not conversation_id:
        return config
    try:
        stored = load_settings_from_file().get(suggestion_config_settings_key(conversation_id)) or {}
        for key in SUGGESTION_CONFIG_DEFAULTS:
            if key in stored:
                config[key] = stored[key]
        config['auto_rate_limit'] = int(config.get('auto_rate_limit') or 10)
    except Exception as e:
        _print(f"[RealtimeMonitorService] 读取按联系人建议配置失败（回落默认）: {e}")
    return config


class RealtimeMonitorService(SuggestionPipelineMixin, BackfillStoreMixin, BackfillMatcherMixin):
    """
    实时监听服务
    单例模式,同一时间只监听一个对象
    """

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
            self._current_conversation_id = 0   # 当前监听会话号（按联系人建议配置的键）
            self.is_monitoring = False          # 监听状态
            self._session_generation = 0        # 会话代数：start_monitoring/run_backfill 接管单例时递增（R2）
            self._chat_ready = False            # 聊天定位是否完成
            self._chat_error = ''               # 聊天定位出错信息
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
            # 消息保存成功回调（webview 推送通道注入，见 gui_backend.attach_realtime_push）：
            # fn(batch_id, account_wxid, message_data)——仅入队不阻塞，异常不影响落库链路
            self.on_message_saved = None
            # 实时情感分析服务
            self.sentiment_service = RealtimeSentimentService()
            # 情绪状态追踪器（每次 start_monitoring 时重建）
            # 建议配置按联系人在 start_monitoring 时读取；这里只落内置默认
            # （旧全局键 trigger_mode/intent 已废弃，不再读取）
            self._suggestion_config = dict(SUGGESTION_CONFIG_DEFAULTS)
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

    def _resolve_current_conversation_id(self) -> int:
        """解析当前监听对象对应的会话号（建议配置按联系人存储的键）"""
        display_name = str(self.current_display_name or '').strip()
        if not display_name:
            return 0
        try:
            from ...db.connection import get_db

            row = get_db().execute(
                "SELECT id FROM conversations WHERE account_wxid = ? "
                "AND (display_name = ? OR username = ?) AND is_deleted = 0 "
                "ORDER BY message_count DESC LIMIT 1",
                (self._resolve_account_wxid(), display_name, display_name),
            ).fetchone()
            return int(row['id']) if row and row['id'] else 0
        except Exception as e:
            _print(f"[RealtimeMonitorService] 解析监听会话号失败: {e}")
            return 0

    def _reset_wechat_instance(self):
        """重置缓存的微信实例，让下一次重试从干净状态开始。"""
        if self.wx is not None:
            try:
                stop_listening = getattr(self.wx, 'StopListening', None)
                if callable(stop_listening):
                    stop_listening()
            except Exception:
                pass
        self.provider = None
        self.wx = None
        self._provider_name = ''
        self._listener_profile = ''
        self._wechat_version = ''

    def _create_wechat_instance(self):
        """新建一个实时监听 provider 实例。"""
        try:
            from backend.wxauto4 import WeChat
        except ModuleNotFoundError:
            from wxauto4 import WeChat

        self._reset_wechat_instance()
        self.wx = WeChat(start_listener=False)
        self.provider = getattr(self.wx, '_provider', None)
        self._provider_name = getattr(self.wx, 'backend_name', '')
        self._listener_profile = getattr(self.wx, 'listener_profile', '')
        self._wechat_version = getattr(self.wx, 'wechat_version', '')
        nickname = getattr(self.wx, 'nickname', '')
        if nickname:
            _print(
                "[RealtimeMonitorService] 监听后端初始化成功, "
                f"backend={self._provider_name or 'unknown'}, "
                f"当前账号: {nickname}"
            )
        return self.wx

    @staticmethod
    def _format_listener_init_error(exc: Exception) -> str:
        return f'监听后端初始化失败，请确认微信已登录且密钥有效: {exc}'

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
            if self.wx is None:
                _print("[RealtimeMonitorService] 初始化监听后端...")
                try:
                    self._create_wechat_instance()
                except Exception as e:
                    return {
                        'success': False,
                        'message': '监听后端初始化失败',
                        'error': self._format_listener_init_error(e),
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
            # 建议配置按联系人装载（无会话号/无键回落内置默认）
            self._current_conversation_id = self._resolve_current_conversation_id()
            self._suggestion_config = load_suggestion_config_for_contact(self._current_conversation_id)
            _print(
                f"[RealtimeMonitorService] 按联系人建议配置已装载: conversation={self._current_conversation_id}"
                f" trigger_mode={self._suggestion_config.get('trigger_mode')}"
                f" intent={self._suggestion_config.get('intent')}"
            )
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
        from ..wechat.chatroom import is_chatroom_username, parse_chatroom_message

        # 监听群聊时剥离 wxid 前缀：与导入侧同口径——否则实时行与导入行
        # 内容不相等，对账永不命中、实时行成为永久重复，且前缀继续
        # 污染情绪/词频/事实抽取与出网 prompt
        monitoring_chatroom = is_chatroom_username(
            getattr(self, 'current_talker', '') or ''
        ) or is_chatroom_username(getattr(self, 'current_display_name', '') or '')
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
            if monitoring_chatroom and not is_system and content:
                _member_wxid, content = parse_chatroom_message(content)
            message_type = str(getattr(msg, 'type', 'text') or 'text')
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
        """定位目标联系人的聊天数据（db_watch：解析联系人并定位消息表）。"""
        if not self.wx:
            self._chat_error = '监听后端未初始化'
            return False
        expected_name = (self.current_display_name or target_name or "").strip()
        # db_watch 后端用 return False（不抛异常）表示定位失败：
        # 返回值必须检查，否则失败被当成功，监听「正常」启动但永远
        # 抓不到消息且无任何报错
        started_at = time.time()
        try:
            chat_ok = self.wx.ChatWith(target_name, expected_display_name=expected_name)
        except Exception as e:
            error_text = str(e)
            self._chat_timed_out = ('timeout' in error_text.lower()) or ('超时' in error_text)
            error_prefix = '定位聊天数据超时' if self._chat_timed_out else '定位聊天数据失败'
            self._chat_error = (
                f"{error_prefix}（{time.time() - started_at:.1f}秒）"
                f"，target='{target_name}'，原因={error_text}"
            )
            _print(f"[OpenChat] 失败: {self._chat_error}")
            return False
        if chat_ok is False:
            self._chat_error = (
                f"未找到『{expected_name or target_name}』的聊天数据"
                f"（常见原因：本地库解析不到该联系人或消息表不在任何分片，"
                f"请核对联系人名或先完成一次历史导入）"
            )
            _print(f"[OpenChat] open_chat 返回 False: {self._chat_error}")
            return False
        _print(f"[OpenChat] 成功: target='{target_name}', elapsed={time.time() - started_at:.2f}s")
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
        """轮询线程：先完成聊天定位和模型预加载，再开始抓取消息"""
        session_state = self._build_session_state(session_token)
        _print("🔄 轮询线程已启动")

        # -- 1. 定位目标联系人的聊天数据（db_watch：候选名逐一解析） --
        if not self._session_should_continue(session_state, stop_event):
            _print("🛑 收到停止信号，轮询线程退出")
            return
        _print(f"👂 定位聊天数据: {session_state.get('display_name')}")
        chat_connected = False
        chat_targets = self._build_chatwith_candidates()
        _print(f"[OpenChat] 候选搜索名: {chat_targets}")
        try:
            for target_name in chat_targets:
                _print(f"[OpenChat] 本轮尝试搜索名: {target_name}")
                if self._try_chat_with(target_name):
                    _print(f"✅ 已定位聊天数据: {target_name}")
                    chat_connected = True
                    break
                _print(f"⚠️ 聊天定位失败: {self._chat_error}")
                if self._chat_timed_out:
                    _print("⚠️ 定位超时，停止其余候选名，避免堆积挂起")
                    break
        except Exception as e:
            self._chat_error = f'定位聊天数据异常: {e}'
            _print(f"❌ 聊天定位异常: {e}")

        # 定位失败即停止（db_watch 的失败=联系人解析不到，等待无意义）
        if not chat_connected:
            self.is_monitoring = False
            _print(f"🛑 {self._chat_error or '聊天数据定位失败'}")
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
        
        poll_fail_count = 0  # 异常连续失败计数（R1）
        POLL_MAX_CONSECUTIVE = 10  # 连续失败上限：超过视为监听通道失效（如微信已关闭）

        while self._session_should_continue(session_state, stop_event):
            try:
                if not self.wx or not session_state.get('display_name'):
                    break

                # 获取当前聊天的可见消息（通过去重逻辑只处理新消息）
                new_messages = self.wx.GetAllMessage()
                poll_fail_count = 0
                
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
                
                # 轮询节奏：无变化轮在 provider 内短路（inotify 缓存/stat 短路，
                # µs 级），50ms 对齐延迟即可压到最低；stat 降级模式下 20Hz×19
                # 分片×2 文件 fstat 同样可忽略
                time.sleep(0.05)
                
            except Exception as e:
                poll_fail_count += 1
                _print(f"❌ 轮询出错 ({poll_fail_count}/{POLL_MAX_CONSECUTIVE}): {e}")
                import traceback
                traceback.print_exc()
                if poll_fail_count >= POLL_MAX_CONSECUTIVE:
                    # 连续失败视为监听通道失效（如微信已退出、数据文件不可读）：
                    # 置错误状态并停止轮询，前端经 get_status 的 chat_error 可见，
                    # 不再无限自旋刷日志（R1）
                    self._chat_error = f'消息轮询连续失败 {poll_fail_count} 次，监听已停止：{e}'
                    # 先收尾再停：迁移缓冲 + checkpoint。此前裸退后
                    # is_monitoring=False，用户再按停止会被「没有监听任务」
                    # 拒绝——本批消息永久滞留缓冲表无人消费
                    try:
                        self._finalize_session_in_thread(session_state)
                    except Exception as fin_e:
                        _print(f"⚠️  轮询失效收尾异常: {fin_e}")
                    self.is_monitoring = False
                    break
                time.sleep(1)

        _print("🛑 轮询线程已停止")

    def _finalize_session_in_thread(self, session_state: dict) -> None:
        """轮询线程侧失效收尾：checkpoint + 迁移缓冲 + 清状态（无 join）。

        与 stop_monitoring 收尾同语义，但在轮询线程自身执行——不能等
        自己结束，也不做状态拒绝检查（调用点即终局）。
        """
        batch_id = self.current_batch_id
        talker_username = self.current_talker
        talker_display_name = self.current_display_name
        if not batch_id:
            return
        message_count = self.message_buffer.get_batch_count(batch_id, self.current_account_wxid)
        self._save_monitor_checkpoint(
            batch_id, talker_username, talker_display_name, message_count
        )
        migrated_count = self._migrate_buffer_to_messages(
            batch_id, talker_username, talker_display_name
        )
        if migrated_count:
            _print(f"✅ 失效收尾已迁移 {migrated_count} 条消息到历史数据表")
        self._log_runtime_event('realtime_monitor_abort_finalize', {
            'batch_id': batch_id,
            'talker_username': talker_username,
            'talker_display_name': talker_display_name,
            'message_count': message_count,
            'migrated_count': migrated_count,
        })
        self.current_batch_id = None
        self.current_talker = None
        self.current_display_name = None
    
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
            
            # 7. 保存到数据库（返回新行 rowid：0=失败，真值语义同 bool）
            message_row_id = self.message_buffer.save_message(
                batch_id,
                self.current_account_wxid,
                talker_username,
                display_name,
                message_data
            )

            if message_row_id:
                message_data['id'] = message_row_id
                self.seen_message_keys.add(message_key)
                # 记录哈希
                if message_hash:
                    self.seen_hashes.add(message_hash)

                # 推送通道回调（evaluate_js，消息落库即上屏；情感分析等重活
                # 都在其后）——只入队不阻塞，异常不影响本条消息处理
                if self.on_message_saved:
                    try:
                        self.on_message_saved(
                            batch_id, self.current_account_wxid, message_data
                        )
                    except Exception as push_e:
                        _print(f"⚠️ 实时推送失败: {push_e}")
                
                # 自动进行实时情感分析(排除系统消息)
                sentiment_result = None
                triggers = []
                if sender_attr != 'system' and message_data['content'] and str(message_data['content']).strip():
                    try:
                        sentiment_result = self.sentiment_service.analyze(
                            str(message_data['content'])
                        )
                        # 同时缓存到数据库（传入已算好的结果，不再二次推理）
                        self.sentiment_service.analyze_and_cache(
                            message_id=message_hash,
                            text=str(message_data['content']),
                            result=sentiment_result,
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
        # 每次进监听都被打扰（实测：某高频会话每次必弹）。
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
            
            # 3. 等待轮询线程结束（软等 5s 给当前轮收尾；仍未结束再硬等 10s——
            # 回溯/抓取可能拖长。线程未死时数据所有权仍在线程：继续迁移会把
            # 竞态写入的新消息整批标已处理而无人迁移（静默丢），必须放弃迁移
            # 让消息留在缓冲表待下轮补全，方向安全）
            if self.polling_thread and self.polling_thread.is_alive():
                _print("⏳ 等待轮询线程结束...")
                waited = 0.0
                while self.polling_thread.is_alive() and waited < 15.0:
                    self.polling_thread.join(timeout=0.5)
                    waited += 0.5
                if self.polling_thread.is_alive():
                    _print(
                        f"⚠️  轮询线程 {waited:.1f}s 未结束，跳过本次缓冲迁移"
                        "（消息已留在暂存表，未被标已处理，不丢数据）"
                    )
                    deferred_batch_id = self.current_batch_id
                    deferred_talker = self.current_talker
                    deferred_name = self.current_display_name
                    # 保存 checkpoint：下次开启监听经回溯补全从微信侧重抓窗口消息
                    try:
                        deferred_count = self.message_buffer.get_batch_count(
                            deferred_batch_id, self.current_account_wxid
                        )
                        self._save_monitor_checkpoint(
                            deferred_batch_id, deferred_talker, deferred_name, deferred_count
                        )
                    except Exception as cp_e:
                        _print(f"⚠️  延迟收尾 checkpoint 保存失败: {cp_e}")
                    self._log_runtime_event('realtime_monitor_stop_deferred', {
                        'batch_id': deferred_batch_id,
                        'waited_seconds': waited,
                    })
                    self.is_monitoring = False
                    self.current_batch_id = None
                    self.current_talker = None
                    self.current_display_name = None
                    return {
                        'success': True,
                        'batch_id': deferred_batch_id,
                        'message_count': 0,
                        'message': f'监听已停止，但轮询线程仍在收尾（等待 {waited:.0f}s），'
                                   '本批消息未被迁移；已保存回溯点，下次开启监听可自动补全'
                    }
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
            self._current_conversation_id = 0  # 会话号随监听会话一起清（停止后状态不再回报旧会话）
            self.seen_hashes.clear()
            self.seen_message_keys.clear()
            self._last_known_ts = 0
            self._chat_timed_out = False
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
                'conversation_id': self._current_conversation_id,
                'batch_id': self.current_batch_id,
                'message_count': message_count,
                'model_ready': self.sentiment_service.is_ready(),
                'chat_ready': self._chat_ready,
                'chat_error': self._chat_error,
                'polling_alive': polling_alive,
                'provider': self._provider_name or getattr(self.wx, 'backend_name', ''),
                'listener_profile': self._listener_profile or getattr(self.wx, 'listener_profile', ''),
                'wechat_version': self._wechat_version or getattr(self.wx, 'wechat_version', ''),
            }

        except Exception as e:
            logger.error(f"[RealtimeMonitorService] 获取状态失败: {e}")
            return {
                'is_monitoring': False,
                'error': str(e)
            }


    def get_suggestion_config(self) -> dict:
        """获取 AI 建议配置"""
        return dict(self._suggestion_config)

    def set_suggestion_config(self, config: dict):
        """更新 AI 建议配置"""
        for key in ('trigger_mode', 'intent', 'auto_rate_limit', 'engine_type'):
            if key in config:
                self._suggestion_config[key] = config[key]
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
