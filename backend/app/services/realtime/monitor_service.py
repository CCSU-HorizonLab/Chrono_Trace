"""
实时消息监听服务
基于 wxauto4 实现单对象消息监听
"""
import sys
import time
import uuid
import json
import threading
from .message_buffer import MessageBuffer
from .realtime_sentiment_service import RealtimeSentimentService
from .emotion_state_tracker import EmotionStateTracker

def _print(*args, **kwargs):
    """强制刷新的打印函数"""
    print(*args, **kwargs)
    sys.stdout.flush()


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
            self.message_buffer = MessageBuffer()
            self.seen_hashes = set()            # 消息去重集合
            self.polling_thread = None          # 轮询线程
            self.stop_polling = False           # 停止轮询标志
            # 实时情感分析服务
            self.sentiment_service = RealtimeSentimentService()
            # 情绪状态追踪器（每次 start_monitoring 时重建）
            self.emotion_tracker = None
            # AI 建议配置
            self._suggestion_config = {
                'trigger_mode': 'semi_auto',    # full_auto / semi_auto / manual
                'intent': 'maintain',           # intimate / maintain / distance
                'auto_rate_limit': 10,          # 全自动模式更新频率上限（秒）
                'engine_type': 'template',      # template / llm
            }
            # 检查数据库是否有已激活的 LLM 模型，自动切换引擎类型
            try:
                from ...db.connection import get_db
                conn = get_db()
                row = conn.execute(
                    'SELECT id FROM llm_models WHERE is_active = 1 LIMIT 1'
                ).fetchone()
                if row:
                    self._suggestion_config['engine_type'] = 'llm'
                    _print("[RealtimeMonitorService] 检测到已激活 LLM 模型，引擎类型设为 llm")
            except Exception:
                pass  # 表不存在或数据库未就绪，保持默认 template
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
            if self.wx is None:
                _print("[RealtimeMonitorService] 初始化 wxauto4...")
                try:
                    from wxauto4 import WeChat
                    self.wx = WeChat(start_listener=True)
                    _print(f"[RealtimeMonitorService] wxauto4 初始化成功, 当前账号: {self.wx.nickname}")
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
            
            # 创建情绪追踪器
            self.emotion_tracker = EmotionStateTracker()
            _print(f"[RealtimeMonitorService] 情绪追踪器已创建")
            
            # 自动将微信窗口置顶到前台
            self._bring_wechat_to_front()
            
            _print(f"[RealtimeMonitorService] 开始监听: {talker_display_name} (batch_id: {self.current_batch_id})")
            
            # 4. 不再使用 AddListenChat，改用轮询模式主动获取消息
            _print(f"\n👂 启动轮询监听（不使用回调），目标: {talker_display_name}")
            _print(f"💡 微信窗口已自动激活到前台")
            
            # 5. 更新状态
            self.is_monitoring = True
            _print(f"✅ 监听已启动！批次ID: {self.current_batch_id[:8]}...")
            
            # 7. 启动轮询线程（因为 wxauto4 的回调在 webview 环境下可能不工作）
            _print(f"🔄 启动消息轮询线程（每1秒检查一次新消息）...")
            self.stop_polling = False
            self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
            self.polling_thread.start()
            
            _print(f"💡 使用轮询模式获取消息（替代回调函数）")
            _print(f"💡 请在微信主窗口中发送消息（单击联系人显示的聊天区域，不要双击弹窗）")
            
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
            print(f"[RealtimeMonitorService] 启动监听异常: {e}")
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

            _print("✅ 微信窗口已强制置顶到最前方")
            return True

        except Exception as e:
            _print(f"⚠️ 自动置顶微信窗口失败: {e}，请手动切换")
            return False

    def _polling_loop(self):
        """轮询线程：定期检查新消息"""
        _print(f"🔄 轮询线程已启动")
        
        # 在循环外切换一次聊天窗口
        try:
            self.wx.ChatWith(self.current_display_name)
            _print(f"✅ 已切换到聊天窗口: {self.current_display_name}")
        except Exception as e:
            _print(f"❌ 切换聊天窗口失败: {e}")
            return
        
        # 预加载情感分析模型(在切换窗口后,开始抓取前)
        _print(f"\n🤖 正在预加载情感分析模型...")
        try:
            self.sentiment_service.analyze("测试")
            _print(f"✅ 情感分析模型加载完成\n")
        except Exception as e:
            _print(f"⚠️ 情感分析模型加载失败: {e}")
            _print(f"💡 将继续监听,但情感分析功能可能不可用\n")
        
        while not self.stop_polling and self.is_monitoring:
            try:
                if not self.wx or not self.current_display_name:
                    break
                
                # 获取当前窗口的所有消息（通过去重逻辑只处理新消息）
                new_messages = self.wx.GetAllMessage()
                
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
                'timestamp': int(time.time())
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
                
                # 显示统计
                _print(f"✅ 已保存！累计: {len(self.seen_hashes)} 条\n")
            else:
                _print(f"❌ 保存失败！\n")
            
        except Exception as e:
            _print(f"❌ 消息处理出错: {e}")
            import traceback
            traceback.print_exc()
    
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
            talker_display_name = self.current_display_name
            
            # 5. 记录事件
            self._log_runtime_event('realtime_monitor_stop', {
                'batch_id': batch_id,
                'talker_username': self.current_talker,
                'talker_display_name': talker_display_name,
                'message_count': message_count
            })
            
            # 6. 清理状态
            self.current_batch_id = None
            self.current_talker = None
            self.current_display_name = None
            self.seen_hashes.clear()
            
            # 7. 重置情绪追踪器
            if self.emotion_tracker:
                self.emotion_tracker.reset()
                self.emotion_tracker = None
            self._last_auto_suggestion_time = 0
            
            _print(f"✅ 监听已完全停止！累计抓取: {message_count} 条\n")
            
            return {
                'success': True,
                'batch_id': batch_id,
                'message_count': message_count,
                'message': f'监听已停止,共抓取 {message_count} 条消息'
            }
            
        except Exception as e:
            print(f"[RealtimeMonitorService] 停止监听异常: {e}")
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
            
            return {
                'is_monitoring': self.is_monitoring,
                'talker_username': self.current_talker,
                'talker_display_name': self.current_display_name,
                'batch_id': self.current_batch_id,
                'message_count': message_count,
                'model_ready': self.sentiment_service.is_ready()
            }
            
        except Exception as e:
            print(f"[RealtimeMonitorService] 获取状态失败: {e}")
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
            print(f"[RealtimeMonitorService] 记录运行时事件失败: {e}")
    
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
                
                # 生成建议
                from .suggestion_engine import SuggestionEngineFactory
                engine_type = self._suggestion_config.get('engine_type', 'template')
                engine = SuggestionEngineFactory.create(engine_type)
                result = engine.generate(
                    trigger.trigger_type, intent, trigger.context
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
                self._suggestion_config.get('engine_type', 'template')
            )
            result = engine.generate(trigger_type, intent)
            
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
                    engine_type TEXT DEFAULT 'template',
                    trigger_context TEXT,
                    created_at INTEGER NOT NULL,
                    read_at INTEGER,
                    dismissed_at INTEGER
                )
            ''')
            
            conn.execute('''
                INSERT INTO realtime_suggestions
                (batch_id, trigger_type, intent, severity, summary, speeches,
                 confidence, engine_type, trigger_context, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.current_batch_id,
                result.trigger_type,
                result.intent,
                result.severity,
                result.summary,
                json.dumps(result.speeches, ensure_ascii=False),
                result.confidence,
                self._suggestion_config.get('engine_type', 'template'),
                json.dumps(trigger.context, ensure_ascii=False) if trigger.context else None,
                int(time.time()),
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
            
            print("[RealtimeMonitorService] 服务已关闭")
            
        except Exception as e:
            print(f"[RealtimeMonitorService] 关闭服务异常: {e}")
