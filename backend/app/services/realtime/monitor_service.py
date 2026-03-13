"""
实时消息监听服务
基于 wxauto4 实现单对象消息监听
"""
import sys
import logging
import time
import uuid
import json
import threading
import multiprocessing
import queue
import re
from datetime import datetime, timedelta
from .message_buffer import MessageBuffer
from .realtime_sentiment_service import RealtimeSentimentService
from .emotion_state_tracker import EmotionStateTracker

logger = logging.getLogger(__name__)
def _print(*args, **kwargs):
    """强制刷新的打印函数"""
    print(*args, **kwargs, flush=True)


def _chatwith_worker(target_name: str, result_queue):
    """Run wxauto4.ChatWith in a separate process so it can be terminated on timeout."""
    started_at = time.time()
    try:
        from wxauto4 import WeChat

        wx = WeChat(start_listener=False)
        wx.ChatWith(target_name)
        result_queue.put({
            'ok': True,
            'error': '',
            'elapsed': time.time() - started_at,
        })
    except Exception as e:
        result_queue.put({
            'ok': False,
            'error': str(e),
            'elapsed': time.time() - started_at,
        })


class RealtimeMonitorService:
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
            self.is_monitoring = False          # 监听状态
            self._chat_ready = False            # ChatWith 是否完成
            self._chat_error = ''               # ChatWith 出错信息
            self._start_time = 0                # 开始监听时间戳
            self._last_known_ts = 0
            self._chat_timed_out = False
            self.message_buffer = MessageBuffer()
            self.seen_hashes = set()            # 消息去重集合
            self.polling_thread = None          # 轮询线程
            self.stop_polling = False           # 停止轮询标志
            # 实时情感分析服务
            self.sentiment_service = RealtimeSentimentService()
            # 情绪状态追踪器（每次 start_monitoring 时重建）
            # AI 建议配置: 从 global settings.json 中读取
            try:
                from pathlib import Path
                import json
                settings_file = Path(__file__).parent.parent.parent.parent / "data" / "settings.json"
                if settings_file.exists():
                    with open(settings_file, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                else:
                    settings = {}
                self._suggestion_config = {
                    'trigger_mode': settings.get('trigger_mode', 'semi_auto'),
                    'intent': settings.get('intent', 'maintain'),
                    'auto_rate_limit': int(settings.get('auto_rate_limit', 10)),
                    'engine_type': 'llm',           # llm
                }
            except Exception as e:
                _print(f"[RealtimeMonitorService] 获取全局设置失败: {e}")
                self._suggestion_config = {
                    'trigger_mode': 'semi_auto',    # full_auto / semi_auto / manual
                    'intent': 'maintain',           # intimate / maintain / distance
                    'auto_rate_limit': 10,          # 全自动模式更新频率上限（秒）
                    'engine_type': 'llm',           # llm
                }
            self._last_auto_suggestion_time = 0
            self._initialized = True
            _print(f"[RealtimeMonitorService] 服务已初始化，引擎类型: {self._suggestion_config['engine_type']}")
    
    def start_monitoring(
        self, 
        talker_username: str,
        talker_display_name: str
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
            # 2. 初始化 wxauto4
            self._reset_wechat_instance()
            if self.wx is None:
                _print("[RealtimeMonitorService] 初始化 wxauto4...")
                try:
                    from wxauto4 import WeChat  # noqa: F401
                    self._reset_wechat_instance()
                except Exception as e:
                    return {
                        'success': False,
                        'message': 'wxauto4 初始化失败',
                        'error': f'请确保微信 4.0.5 已启动并登录: {str(e)}'
                    }
            
            # 3. 生成批次ID
            self.current_batch_id = str(uuid.uuid4())
            self.current_talker = talker_username
            self.current_display_name = talker_display_name
            self.seen_hashes.clear()
            self._last_known_ts = 0
            
            # 创建情绪追踪器
            self.emotion_tracker = EmotionStateTracker()
            _print(f"[RealtimeMonitorService] 情绪追踪器已创建")
            
            _print(f"[RealtimeMonitorService] 开始监听: {talker_display_name} (batch_id: {self.current_batch_id})")
            
            # 4. 立即设置状态（让前端可以先进入悬浮模式）
            self.is_monitoring = True
            self._chat_ready = False
            self._chat_error = ''
            import time
            self._start_time = int(time.time())
            _print(f"✅ 监听已启动！批次ID: {self.current_batch_id[:8]}...")
            
            # 5. 启动轮询线程（ChatWith 和模型预加载在线程中异步执行）
            _print(f"🔄 启动消息轮询线程...")
            self.stop_polling = False
            self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
            self.polling_thread.start()
            
            # 8. 记录事件到运行时事件表
            self._log_runtime_event('realtime_monitor_start', {
                'batch_id': self.current_batch_id,
                'talker_username': talker_username,
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
    def _bring_wechat_to_front(self):
        """使用 Win32 API 将微信窗口强制置顶到所有窗口之上"""
        try:
            import ctypes
            import time as _time

            user32 = ctypes.windll.user32

            # 优先从 wxauto4 获取已有的窗口句柄（最可靠）
            hwnd = None
            if self.wx and hasattr(self.wx, '_api') and hasattr(self.wx._api, 'HWND'):
                hwnd = self.wx._api.HWND
                _print(f"[置顶] 从 wxauto4 获取到窗口句柄: {hwnd}")

            # fallback: 按类名搜索
            if not hwnd:
                for cls_name in ('WeChatMainWndForPC', 'WeChat', 'WeChatMainWndForPC_New'):
                    hwnd = user32.FindWindowW(cls_name, None)
                    if hwnd:
                        _print(f"[置顶] 通过类名 {cls_name} 找到窗口句柄: {hwnd}")
                        break
            
            if not hwnd:
                _print("⚠️ 未找到微信窗口句柄，请手动切换到微信")
                return False

            # 如果窗口最小化，先恢复
            SW_RESTORE = 9
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
                _time.sleep(0.3)

            # 使用 SetWindowPos + HWND_TOPMOST 强制置顶
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040

            # 步骤1: 临时设为 TOPMOST（强制到所有窗口之上）
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            _time.sleep(0.5)

            # 步骤2: 取消 TOPMOST（恢复正常，不永久置顶）
            user32.SetWindowPos(
                hwnd, HWND_NOTOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            user32.SetForegroundWindow(hwnd)
            for _ in range(15):
                if user32.GetForegroundWindow() == hwnd:
                    break
                _time.sleep(0.1)
            _time.sleep(0.3)

            _print("✅ 微信窗口已强制置顶到最前方")
            return True

        except Exception as e:
            _print(f"⚠️ 自动置顶微信窗口失败: {e}，请手动切换")
            return False

    def _reset_wechat_instance(self):
        """Reset the cached wxauto4 instance so the next retry starts clean."""
        if self.wx is not None:
            try:
                stop_listening = getattr(self.wx, 'StopListening', None)
                if callable(stop_listening):
                    stop_listening()
            except Exception:
                pass
        self.wx = None

    def _create_wechat_instance(self):
        """Create a fresh wxauto4 instance without starting the async listener."""
        from wxauto4 import WeChat

        self._reset_wechat_instance()
        self.wx = WeChat(start_listener=False)
        nickname = getattr(self.wx, 'nickname', '')
        if nickname:
            _print(f"[RealtimeMonitorService] wxauto4 初始化成功, 当前账号: {nickname}")
        return self.wx

    def _get_foreground_window_info(self) -> dict:
        """Return basic diagnostics for the current foreground window."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            title_buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            return {
                'hwnd': int(hwnd or 0),
                'title': title_buffer.value,
                'class_name': class_buffer.value,
            }
        except Exception as e:
            return {
                'hwnd': 0,
                'title': '',
                'class_name': '',
                'error': str(e),
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

    def _try_chat_with(self, target_name: str) -> bool:
        """尝试执行 ChatWith，带 15 秒超时。成功返回 True，失败设置 _chat_error 并返回 False"""
        self._chat_timed_out = False
        started_at = time.time()
        before_info = self._get_foreground_window_info()
        _print(
            f"[ChatWith] 调用前前台窗口: hwnd={before_info.get('hwnd')} "
            f"class={before_info.get('class_name')} title={before_info.get('title')}"
        )

        ctx = multiprocessing.get_context('spawn')
        result_queue = ctx.Queue()
        chat_process = ctx.Process(
            target=_chatwith_worker,
            args=(target_name, result_queue),
            daemon=True,
        )
        _print(f"[ChatWith] 开始调用 wx.ChatWith('{target_name}')")
        chat_process.start()
        chat_process.join(timeout=15)
        after_info = self._get_foreground_window_info()
        
        if chat_process.is_alive():
            self._chat_timed_out = True
            elapsed = time.time() - started_at
            chat_process.terminate()
            chat_process.join(timeout=2)
            self._chat_error = (
                f"切换聊天窗口超时（{elapsed:.1f}秒）"
                f"，target='{target_name}'，前台窗口={after_info.get('title') or after_info.get('class_name')}"
            )
            _print(
                f"[ChatWith] 超时: hwnd={after_info.get('hwnd')} "
                f"class={after_info.get('class_name')} title={after_info.get('title')}"
            )
            return False

        try:
            worker_result = result_queue.get_nowait()
        except queue.Empty:
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

        elapsed = float(worker_result.get('elapsed') or (time.time() - started_at))
        _print(
            f"[ChatWith] 成功: target='{target_name}', elapsed={elapsed:.2f}s, "
            f"前台窗口={after_info.get('title') or after_info.get('class_name')}"
        )
        self._chat_error = ''
        return True

    def _polling_loop(self):
        """轮询线程：先完成 ChatWith 和模型预加载，再开始抓取消息"""
        _print(f"🔄 轮询线程已启动")
        
        # -- 1. 将微信窗口置顶 --
        self._bring_wechat_to_front()
        time.sleep(1.0)
        
        # -- 2. 切换聊天窗口（带重试循环，最多 3 次） --
        _print(f"👂 切换到聊天窗口: {self.current_display_name}")
        MAX_CHAT_RETRIES = 3
        CHAT_RETRY_DELAY = 5  # 秒
        chat_connected = False
        chat_targets = self._build_chatwith_candidates()
        _print(f"[ChatWith] 候选搜索名: {chat_targets}")
        
        for attempt in range(1, MAX_CHAT_RETRIES + 1):
            if self.stop_polling or not self.is_monitoring:
                _print(f"🛑 收到停止信号，中止 ChatWith 重试")
                return
            
            _print(f"🔄 ChatWith 尝试 {attempt}/{MAX_CHAT_RETRIES}...")
            try:
                self._create_wechat_instance()
                self._bring_wechat_to_front()
                time.sleep(1.2)
                for target_name in chat_targets:
                    _print(f"[ChatWith] 本轮尝试搜索名: {target_name}")
                    if self._try_chat_with(target_name):
                        _print(f"✅ 已切换到聊天窗口: {target_name}")
                        chat_connected = True
                        break
                    _print(f"⚠️ 第 {attempt} 次 ChatWith 失败: {self._chat_error}")
                    if self._chat_timed_out:
                        _print("⚠️ 检测到 ChatWith 超时，停止本轮其余候选名和后续自动重试，避免堆积挂起线程")
                        break
                if chat_connected:
                    break
                if self._chat_timed_out:
                    break
            except Exception as e:
                self._chat_error = f'切换聊天窗口异常: {e}'
                _print(f"❌ 第 {attempt} 次 ChatWith 异常: {e}")
            
            if self._chat_timed_out:
                break

            if attempt < MAX_CHAT_RETRIES:
                _print(f"⏳ {CHAT_RETRY_DELAY} 秒后重试...")
                time.sleep(CHAT_RETRY_DELAY)
        
        # 重试 3 次仍失败 → 进入「等待恢复」模式，而不是终止线程
        if not chat_connected:
            _print(f"⚠️ ChatWith 初始连接 {MAX_CHAT_RETRIES} 次尝试均失败，进入等待恢复模式...")
            RECOVERY_INTERVAL = 10  # 每 10 秒重试一次
            while not self.stop_polling and self.is_monitoring:
                time.sleep(RECOVERY_INTERVAL)
                _print(f"🔄 [等待恢复] 重试 ChatWith...")
                try:
                    self._create_wechat_instance()
                    self._bring_wechat_to_front()
                    time.sleep(1.2)
                    for target_name in chat_targets:
                        _print(f"[ChatWith] [恢复模式] 尝试搜索名: {target_name}")
                        if self._try_chat_with(target_name):
                            _print(f"✅ [恢复成功] 已切换到聊天窗口: {target_name}")
                            chat_connected = True
                            break
                        if self._chat_timed_out:
                            _print("⚠️ [恢复模式] ChatWith 超时，停止本轮恢复尝试")
                            break
                    if chat_connected:
                        break
                    if self._chat_timed_out:
                        break
                except Exception as e:
                    _print(f"⚠️ [等待恢复] ChatWith 仍然失败: {e}")

                if self._chat_timed_out:
                    break
            
            if not chat_connected:
                _print(f"🛑 等待恢复被中断（收到停止信号），轮询线程退出")
                return
        
        # -- 3. 预加载情感分析模型 --
        _print(f"🤖 正在预加载情感分析模型...")
        try:
            self.sentiment_service.analyze("测试")
            _print(f"✅ 情感分析模型加载完成")
        except Exception as e:
            _print(f"⚠️ 情感分析模型加载失败: {e}")
            _print(f"💡 将继续监听,但情感分析功能可能不可用")
        
        # -- 4. 标记就绪 --
        self._chat_ready = True
        self._chat_error = ''
        _print(f"🟢 准备就绪，开始抓取消息...")
        
        gdi_fail_count = 0  # GDI 异常连续失败计数（Bug 3）
        GDI_MAX_CONSECUTIVE = 5  # 连续 GDI 失败上限
        
        while not self.stop_polling and self.is_monitoring:
            try:
                if not self.wx or not self.current_display_name:
                    break
                
                # 获取当前窗口的所有消息（通过去重逻辑只处理新消息）
                try:
                    new_messages = self.wx.GetAllMessage()
                    gdi_fail_count = 0  # 成功则重置计数
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
                    for msg in new_messages:
                        self._process_message(msg)
                
                # 周期性 silence 检测（即使没有新消息也需要检测）
                if self.emotion_tracker:
                    silence_event = self.emotion_tracker.check_silence()
                    if silence_event:
                        self._handle_trigger_events([silence_event])
                
                # 每1秒检查一次
                time.sleep(1)
                
            except Exception as e:
                _print(f"❌ 轮询出错: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)
        
        _print(f"🛑 轮询线程已停止")
    
    def _process_message(self, msg):
        """处理单条消息（从轮询或回调中调用）"""
        try:
            # 1. 提取消息数据
            message_hash = getattr(msg, 'hash', None)
            
            # 2. 去重检查 (内存快速去重)
            if message_hash and message_hash in self.seen_hashes:
                return  # 已处理过,跳过
            
            # 3. 数据库去重检查 (防止重启后重复)
            if message_hash and self.message_buffer.message_exists(message_hash):
                self.seen_hashes.add(message_hash)
                return
            
            # 4. 判断发送者
            is_self = getattr(msg, 'is_self', False)
            is_system = getattr(msg, 'is_system', False)
            
            sender_attr = 'self' if is_self else 'friend'
            if is_system:
                sender_attr = 'system'
            
            sender_name = "我" if is_self else "对方"
            if is_system:
                sender_name = "系统"
            
            # 5. 提取消息内容
            content = getattr(msg, 'content', '')
            message_type = getattr(msg, 'type', 'text')
            
            # 显示简洁的消息预览
            content_preview = str(content)[:30] + '...' if len(str(content)) > 30 else str(content)
            _print(f"📩 收到消息 [{sender_name}]: {content_preview}")
            
            # 6. 构建消息数据
            message_data = {
                'message_hash': message_hash,
                'runtime_id': str(getattr(msg, 'id', '')),
                'sender_attr': sender_attr,
                'content': str(content) if content else '',
                'message_type': message_type,
                'timestamp': self._resolve_message_timestamp(msg, sender_attr, content)
            }
            
            # 7. 保存到数据库
            success = self.message_buffer.save_message(
                self.current_batch_id,
                self.current_talker,
                self.current_display_name,
                message_data
            )
            
            if success:
                # 记录哈希
                if message_hash:
                    self.seen_hashes.add(message_hash)
                
                # 自动进行实时情感分析(排除系统消息)
                sentiment_result = None
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
                        if triggers:
                            self._handle_trigger_events(triggers)
                    except Exception as e:
                        _print(f"⚠️ 情绪追踪更新失败: {e}")
                
                # 全自动模式：每条消息都尝试生成建议
                if (self._suggestion_config.get('trigger_mode') == 'full_auto'
                        and sentiment_result
                        and sender_attr == 'friend'):
                    self._handle_full_auto_suggestion(sentiment_result)
                
                # 隐式反馈：用户自己发了消息 → 对比最近的 AI 建议
                if sender_attr == 'self' and message_data['content']:
                    self._check_feedback(message_data['content'])
                
                # 显示统计
                _print(f"✅ 已保存！累计: {len(self.seen_hashes)} 条\n")
            else:
                _print(f"❌ 保存失败！\n")
            
        except Exception as e:
            _print(f"❌ 消息处理出错: {e}")
            import traceback
            traceback.print_exc()
    
    def _resolve_message_timestamp(self, msg, sender_attr: str, content) -> int:
        """Resolve a best-effort message timestamp from wxauto4 metadata or system labels."""
        now_ts = int(time.time())
        direct_label = getattr(msg, 'time', None) or getattr(msg, 'CreateTime', None)
        parsed_direct = self._resolve_time_label(direct_label, 0) if direct_label else 0
        if parsed_direct:
            self._last_known_ts = parsed_direct

        if sender_attr == 'system':
            parsed_system = self._resolve_time_label(content, 0)
            if parsed_system:
                self._last_known_ts = parsed_system
                return parsed_system
            return parsed_direct or now_ts

        return parsed_direct or self._last_known_ts or now_ts

    def _resolve_time_label(self, label, fallback: int) -> int:
        """Convert WeChat time labels like '昨天 14:30' into unix timestamps."""
        if not label:
            return fallback

        text = str(label).strip()
        if not text:
            return fallback

        now_dt = datetime.now()

        matched = re.match(r'^(\d{1,2}):(\d{2})$', text)
        if matched:
            return int(datetime(
                now_dt.year, now_dt.month, now_dt.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        matched = re.match(r'^昨天\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            day = now_dt - timedelta(days=1)
            return int(datetime(
                day.year, day.month, day.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        matched = re.match(r'^前天\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            day = now_dt - timedelta(days=2)
            return int(datetime(
                day.year, day.month, day.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        matched = re.match(r'^(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            month = int(matched.group(1))
            day = int(matched.group(2))
            hour = int(matched.group(3))
            minute = int(matched.group(4))
            year = now_dt.year
            candidate = datetime(year, month, day, hour, minute)
            if candidate > now_dt + timedelta(days=1):
                candidate = datetime(year - 1, month, day, hour, minute)
            return int(candidate.timestamp())

        matched = re.match(r'^(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            month = int(matched.group(1))
            day = int(matched.group(2))
            hour = int(matched.group(3))
            minute = int(matched.group(4))
            year = now_dt.year
            candidate = datetime(year, month, day, hour, minute)
            if candidate > now_dt + timedelta(days=1):
                candidate = datetime(year - 1, month, day, hour, minute)
            return int(candidate.timestamp())

        weekday_map = {
            '周一': 0, '星期一': 0,
            '周二': 1, '星期二': 1,
            '周三': 2, '星期三': 2,
            '周四': 3, '星期四': 3,
            '周五': 4, '星期五': 4,
            '周六': 5, '星期六': 5,
            '周日': 6, '星期日': 6, '星期天': 6,
        }
        for prefix, weekday in weekday_map.items():
            matched = re.match(rf'^{re.escape(prefix)}\s+(\d{{1,2}}):(\d{{2}})$', text)
            if not matched:
                continue
            day = now_dt - timedelta(days=(now_dt.weekday() - weekday) % 7)
            return int(datetime(
                day.year, day.month, day.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        return fallback

    def _map_message_type(self, message_type: str) -> int:
        """Map wxauto4 string types to the app's integer message types."""
        type_map = {
            'text': 1,
            'image': 3,
            'voice': 34,
            'video': 43,
            'emoji': 47,
            'file': 49,
        }
        return type_map.get(str(message_type or 'text').lower(), 1)

    def _get_or_create_conversation_id(self, talker_username: str, talker_display_name: str) -> int:
        """Return the conversation id for a talker, creating it when missing."""
        from ...db.connection import get_db

        conn = get_db()
        row = conn.execute(
            'SELECT id FROM conversations WHERE username = ?',
            (talker_username,)
        ).fetchone()
        if row:
            return row[0]

        now_ts = int(time.time())
        cursor = conn.execute(
            '''
            INSERT INTO conversations (username, display_name, created_at, updated_at, message_count)
            VALUES (?, ?, ?, ?, 0)
            ''',
            (talker_username, talker_display_name or talker_username, now_ts, now_ts)
        )
        conn.commit()
        return cursor.lastrowid

    def _message_exists_in_history(self, conversation_id: int, message_data: dict) -> bool:
        """Check whether a buffered realtime message has already been migrated."""
        from ...db.connection import get_db

        conn = get_db()
        runtime_id = str(message_data.get('runtime_id') or '').strip()
        if runtime_id.isdigit():
            row = conn.execute(
                'SELECT id FROM messages WHERE conversation_id = ? AND local_id = ? LIMIT 1',
                (conversation_id, int(runtime_id))
            ).fetchone()
            if row:
                return True

        row = conn.execute(
            '''
            SELECT id
            FROM messages
            WHERE conversation_id = ?
              AND source = 'realtime'
              AND is_sender = ?
              AND message_type = ?
              AND timestamp = ?
              AND COALESCE(content, '') = ?
            LIMIT 1
            ''',
            (
                conversation_id,
                1 if message_data.get('sender_attr') == 'self' else 0,
                self._map_message_type(message_data.get('message_type')),
                int(message_data.get('timestamp') or 0),
                message_data.get('content') or '',
            )
        ).fetchone()
        return row is not None

    def _migrate_buffer_to_messages(self, batch_id: str, talker_username: str, talker_display_name: str) -> int:
        """Move realtime buffered messages into the historical messages table."""
        from ...db.connection import get_db

        if not batch_id or not talker_username:
            return 0

        buffer_messages = self.message_buffer.get_batch_messages(batch_id)
        if not buffer_messages:
            return 0

        conn = get_db()
        conversation_id = self._get_or_create_conversation_id(
            talker_username,
            talker_display_name or talker_username
        )
        migrated = 0
        latest_ts = 0

        for msg in buffer_messages:
            if msg.get('sender_attr') == 'system':
                continue
            if self._message_exists_in_history(conversation_id, msg):
                continue

            runtime_id = str(msg.get('runtime_id') or '').strip()
            local_id = int(runtime_id) if runtime_id.isdigit() else None
            timestamp = int(msg.get('timestamp') or int(time.time()))
            latest_ts = max(latest_ts, timestamp)

            conn.execute(
                '''
                INSERT INTO messages
                (conversation_id, local_id, talker, sender, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'realtime', ?)
                ''',
                (
                    conversation_id,
                    local_id,
                    talker_username,
                    None if msg.get('sender_attr') == 'self' else talker_username,
                    1 if msg.get('sender_attr') == 'self' else 0,
                    self._map_message_type(msg.get('message_type')),
                    msg.get('content') or '',
                    timestamp,
                    int(time.time()),
                )
            )
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
                    talker_display_name or talker_username,
                    latest_ts or int(time.time()),
                    total_count,
                    conversation_id,
                )
            )
            conn.commit()
            self.message_buffer.mark_as_processed(batch_id)

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
        _print(f"\n🛑 收到停止监听请求")
        _print(f"📊 当前监听状态: is_monitoring={self.is_monitoring}")
        
        if not self.is_monitoring:
            _print(f"⚠️  当前没有活跃的监听任务")
            return {
                'success': False,
                'message': '当前没有监听任务',
                'error': '未找到活跃的监听会话'
            }
        
        try:
            _print(f"⏹️  正在停止监听: {self.current_display_name}")
            
            # 1. 停止轮询线程
            self.stop_polling = True
            _print(f"🛑 已发送停止轮询信号")
            
            # 2. 清理状态标志（防止前端继续查询时认为还在监听）
            self.is_monitoring = False
            _print(f"✅ 监听状态已设为 False")
            
            # 3. 等待轮询线程结束（最多2秒）
            if self.polling_thread and self.polling_thread.is_alive():
                _print(f"⏳ 等待轮询线程结束...")
                self.polling_thread.join(timeout=2)
                if self.polling_thread.is_alive():
                    _print(f"⚠️  轮询线程未在2秒内结束，继续...")
                else:
                    _print(f"✅ 轮询线程已结束")
            
            # 4. 不调用 RemoveListenChat（避免卡顿）
            if self.wx and self.current_display_name:
                try:
                    _print(f"⚠️  跳过 RemoveListenChat 调用（避免卡顿）")
                except Exception as e:
                    _print(f"❌ 移除监听异常: {e}")
            
            # 3. 获取消息数量
            message_count = self.message_buffer.get_batch_count(self.current_batch_id)
            
            # 4. 保存批次ID用于返回
            batch_id = self.current_batch_id
            talker_username = self.current_talker
            talker_display_name = self.current_display_name

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
            self._last_known_ts = 0
            self._chat_timed_out = False
            
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
                message_count = self.message_buffer.get_batch_count(self.current_batch_id)
            
            # 检测轮询线程是否仍然存活
            polling_alive = (
                self.polling_thread is not None 
                and self.polling_thread.is_alive()
            )
            
            return {
                'is_monitoring': self.is_monitoring,
                'talker_username': self.current_talker,
                'talker_display_name': self.current_display_name,
                'batch_id': self.current_batch_id,
                'message_count': message_count,
                'model_ready': self.sentiment_service.is_ready(),
                'chat_ready': self._chat_ready,
                'chat_error': self._chat_error,
                'polling_alive': polling_alive,
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
    
    def _handle_trigger_events(self, triggers):
        """
        处理触发事件：根据触发模式决定是否生成建议并存入数据库
        
        Args:
            triggers: TriggerEvent 列表
        """
        mode = self._suggestion_config.get('trigger_mode', 'semi_auto')
        
        if mode == 'manual':
            # 纯手动模式不自动生成建议，只打印日志
            for trigger in triggers:
                _print(f"📊 [手动模式] 检测到触发: {trigger.trigger_type} (已忽略)")
            return
        
        intent = self._suggestion_config.get('intent', 'maintain')
        
        for trigger in triggers:
            try:
                _print(f"🔔 触发事件: {trigger.trigger_type} (severity={trigger.severity})")
                
                # 构建完整的 context (融合 trigger.context 和 画外特征)
                ctx = trigger.context.copy() if trigger.context else {}
                
                if self.current_display_name:
                    try:
                        from .contact_profiler import ContactProfiler
                        from .self_profiler import SelfProfiler
                        
                        # 对方画像
                        c_profiler = ContactProfiler()
                        c_cached = c_profiler.get_profile(self.current_display_name)
                        if c_cached and not c_cached['expired']:
                            ctx['contact_profile'] = c_cached['profile']
                            
                        # 我方本体画像
                        s_profiler = SelfProfiler()
                        s_cached = s_profiler.get_profile(self.current_display_name)
                        if s_cached and not s_cached['expired']:
                            ctx['self_profile'] = s_cached['profile']
                    except Exception as prof_e:
                        _print(f"⚠️ 提取画像失败: {prof_e}")

                # 传递联系人名称以便查询调教规则
                ctx['display_name'] = self.current_display_name

                # RAG：检索相关历史记忆
                try:
                    from .session_thread_service import SessionThreadService
                    thread_svc = SessionThreadService()
                    recent = ctx.get('recent_messages', [])
                    memories = thread_svc.retrieve_relevant_memories(
                        self.current_display_name, recent
                    )
                    if memories:
                        ctx['relevant_memories'] = memories
                except Exception as rag_e:
                    _print(f"⚠️ RAG 检索失败: {rag_e}")

                # 生成建议
                from .suggestion_engine import SuggestionEngineFactory
                engine_type = self._suggestion_config.get('engine_type', 'llm')
                engine = SuggestionEngineFactory.create(engine_type)
                result = engine.generate(
                    trigger.trigger_type, intent, ctx
                )
                
                # 存入数据库
                self._save_suggestion_to_db(trigger, result)
                _print(f"💡 建议已生成: {result.summary}")
                
            except Exception as e:
                _print(f"⚠️ 生成建议失败: {e}")
    
    def _handle_full_auto_suggestion(self, sentiment_result):
        """
        全自动模式：每条对方消息都生成建议（受频率限制）
        """
        now = time.time()
        rate_limit = self._suggestion_config.get('auto_rate_limit', 10)
        
        if now - self._last_auto_suggestion_time < rate_limit:
            return  # 频率限制内，跳过
        
        self._last_auto_suggestion_time = now
        
        try:
            intent = self._suggestion_config.get('intent', 'maintain')
            
            # 根据当前情绪推断触发类型
            if self.emotion_tracker:
                summary = self.emotion_tracker.get_emotion_summary()
                if summary['trend'] == 'negative':
                    trigger_type = 'negative_streak'
                elif summary['trend'] == 'positive':
                    trigger_type = 'positive_window'
                else:
                    trigger_type = 'topic_cooling'
            else:
                trigger_type = 'topic_cooling'
            
            from .suggestion_engine import SuggestionEngineFactory
            from .emotion_state_tracker import TriggerEvent
            engine = SuggestionEngineFactory.create(
                self._suggestion_config.get('engine_type', 'llm')
            )
            
            # 构建完整的 context (包含画像)
            ctx = {'mode': 'full_auto'}
            if self.current_display_name:
                try:
                    from .contact_profiler import ContactProfiler
                    from .self_profiler import SelfProfiler
                    
                    # 对方画像
                    c_profiler = ContactProfiler()
                    c_cached = c_profiler.get_profile(self.current_display_name)
                    if c_cached and not c_cached['expired']:
                        ctx['contact_profile'] = c_cached['profile']
                        
                    # 我方本体画像
                    s_profiler = SelfProfiler()
                    s_cached = s_profiler.get_profile(self.current_display_name)
                    if s_cached and not s_cached['expired']:
                        ctx['self_profile'] = s_cached['profile']
                except Exception as prof_e:
                    _print(f"⚠️ 提取画像失败: {prof_e}")

            # 传递联系人名称以便查询调教规则
            if self.current_display_name:
                ctx['display_name'] = self.current_display_name

            # RAG：检索相关历史记忆
            if self.current_display_name:
                try:
                    from .session_thread_service import SessionThreadService
                    thread_svc = SessionThreadService()
                    recent = ctx.get('recent_messages', [])
                    memories = thread_svc.retrieve_relevant_memories(
                        self.current_display_name, recent
                    )
                    if memories:
                        ctx['relevant_memories'] = memories
                except Exception as rag_e:
                    _print(f"⚠️ RAG 检索失败: {rag_e}")
                    
            result = engine.generate(trigger_type, intent, ctx)
            
            trigger = TriggerEvent(
                trigger_type=trigger_type,
                timestamp=now,
                severity='low',
                context={'mode': 'full_auto'}
            )
            self._save_suggestion_to_db(trigger, result)
            _print(f"💡 [全自动] 建议已生成: {result.summary}")
            
        except Exception as e:
            _print(f"⚠️ [全自动] 生成建议失败: {e}")
    
    def _save_suggestion_to_db(self, trigger, result):
        """
        将建议存入 realtime_suggestions 表
        """
        try:
            from ...db.connection import get_db
            
            conn = get_db()
            
            # 确保表存在
            conn.execute('''
                CREATE TABLE IF NOT EXISTS realtime_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    reply TEXT
                )
            ''')
            try:
                conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN reply TEXT")
            except:
                pass
            
            conn.execute('''
                INSERT INTO realtime_suggestions
                (batch_id, trigger_type, intent, severity, summary, speeches,
                 confidence, engine_type, trigger_context, created_at, reply)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.current_batch_id,
                result.trigger_type,
                result.intent,
                result.severity,
                result.summary,
                json.dumps(result.speeches, ensure_ascii=False),
                result.confidence,
                self._suggestion_config.get('engine_type', 'llm'),
                json.dumps(trigger.context, ensure_ascii=False) if trigger.context else None,
                int(time.time()),
                getattr(result, 'reply', None)
            ))
            conn.commit()
            
        except Exception as e:
            _print(f"⚠️ 保存建议到数据库失败: {e}")
    
    def get_suggestion_config(self) -> dict:
        """获取 AI 建议配置"""
        return dict(self._suggestion_config)
    
    def set_suggestion_config(self, config: dict):
        """更新 AI 建议配置"""
        for key in ('trigger_mode', 'intent', 'auto_rate_limit', 'engine_type'):
            if key in config:
                self._suggestion_config[key] = config[key]
        _print(f"[RealtimeMonitorService] 建议配置已更新: {self._suggestion_config}")

    def _check_feedback(self, user_message: str):
        """
        隐式反馈：将用户实际发送的消息与最近的 AI 建议进行对比，
        提取调教规则。
        """
        try:
            from ...db.connection import get_db
            conn = get_db()

            # 查询最近 5 分钟内尚未反馈的建议（pending=自动生成, displayed=手动生成）
            cutoff = int(time.time()) - 300
            cursor = conn.execute('''
                SELECT id, speeches FROM realtime_suggestions
                WHERE batch_id = ? AND status IN ('pending', 'displayed') AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
            ''', (self.current_batch_id, cutoff))

            row = cursor.fetchone()
            if not row:
                return  # 没有待处理建议，跳过

            suggestion_id = row['id']
            speeches = json.loads(row['speeches'])

            _print(f"\ud83d\udd0d [隐式反馈] 检测到用户发消息，开始对比 AI 建议 (id={suggestion_id})")

            # 调用规则提取器
            from .feedback_rule_extractor import FeedbackRuleExtractor
            extractor = FeedbackRuleExtractor()

            # 在后台线程中执行（避免阻塞消息轮询）
            import threading
            def do_extract():
                try:
                    result = extractor.compare_and_extract(
                        ai_speeches=speeches,
                        user_actual_message=user_message,
                        display_name=self.current_display_name or '',
                        suggestion_id=suggestion_id,
                    )
                    if result:
                        _print(f"\ud83d\udcdd [隐式反馈] 提取到新规则: {result.get('rule', '')}")
                    
                    # 标记建议为已反馈
                    conn2 = get_db()
                    conn2.execute(
                        "UPDATE realtime_suggestions SET status = 'feedback_collected' WHERE id = ?",
                        (suggestion_id,)
                    )
                    conn2.commit()
                except Exception as e:
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
