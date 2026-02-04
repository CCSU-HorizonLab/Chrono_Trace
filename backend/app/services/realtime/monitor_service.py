"""
实时消息监听服务
基于 wxauto4 实现单对象消息监听
"""
import sys
import time
import uuid
import threading
from .message_buffer import MessageBuffer
from .realtime_sentiment_service import RealtimeSentimentService

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
            # 新增:实时情感分析服务
            self.sentiment_service = RealtimeSentimentService()
            self._initialized = True
            _print("[RealtimeMonitorService] 服务已初始化")
    
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
            
            _print(f"[RealtimeMonitorService] 开始监听: {talker_display_name} (batch_id: {self.current_batch_id})")
            
            # 4. 不再使用 AddListenChat，改用轮询模式主动获取消息
            _print(f"\n👂 启动轮询监听（不使用回调），目标: {talker_display_name}")
            _print(f"💡 提示：请确保在微信主窗口（不是独立聊天窗口）中可以看到该联系人")
            
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
                
                # 新增:自动进行实时情感分析(排除系统消息)
                if sender_attr != 'system' and message_data['content'] and str(message_data['content']).strip():
                    try:
                        # 获取保存的message_id(需要从message_buffer获取)
                        # 这里简化处理,实际应该从save_message返回message_id
                        self.sentiment_service.analyze_and_cache(
                            message_id=message_hash,  # 临时使用hash作为id
                            text=str(message_data['content'])
                        )
                        _print(f"💭 情感分析完成")
                    except Exception as e:
                        _print(f"⚠️ 情感分析失败: {e}")
                        import traceback
                        traceback.print_exc()
                
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
                'message_count': message_count
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
