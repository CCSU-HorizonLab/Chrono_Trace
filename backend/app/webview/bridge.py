from typing import Any, Optional
import json
import os
import logging
from pathlib import Path
from ..services.wechat.ingest_service import WeChatIngestService

logger = logging.getLogger(__name__)
class Bridge:
    """PyWebView JS API Bridge: 暴露给前端调用的方法。"""

    def __init__(self):
        self.wechat_service = WeChatIngestService()
        self.settings_file = Path(__file__).parent.parent.parent / "data" / "settings.json"
        self._load_settings()

        # 延迟加载特征提取服务（避免循环导入）
        self._feature_service = None

        # 悬浮窗管理服务
        from ..services.realtime.floating_window_service import FloatingWindowService
        self._floating_service = FloatingWindowService()
        self._webview_window = None  # 由 app_dev.py 注入

    def _load_settings(self):
        """加载设置"""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except Exception:
                self.settings = {}
        else:
            self.settings = {}

    def _save_settings(self):
        """保存设置"""
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存设置失败: {e}")

    def ping(self) -> str:
        return "pong"

    # ==================== 微信数据导入相关 ====================
    
    def get_wechat_paths(self) -> dict[str, Any]:
        """
        获取微信数据库路径信息（用于前端展示）
        
        Returns:
            {"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
        """
        # 优先使用自定义路径
        if self.settings.get("wechat_use_custom_path"):
            wechat_dir = self.settings.get("wechat_data_dir", "")
            wxid = self.settings.get("wechat_user_wxid", "")
            
            # 验证路径是否完整
            if not wechat_dir or not wxid:
                logger.warning("[WARN] 自定义路径配置不完整，尝试自动检测")
                return self.wechat_service.get_wechat_paths()
            
            custom_paths = {
                "wechat_dir": wechat_dir,
                "current_user": wxid,
                "databases": {},  # 数据库会在导入时自动查找
                "source": "custom"
            }
            return {"ok": True, "data": custom_paths}
        
        # 使用自动检测
        return self.wechat_service.get_wechat_paths()
    
    def verify_wechat_key(self, db_key: str) -> dict[str, Any]:
        """
        验证微信数据库密钥是否有效
        
        Args:
            db_key: 32位hex密钥字符串
            
        Returns:
            {"ok": True} 或 {"ok": False, "error": "..."}
        """
        return self.wechat_service.verify_key(db_key)
    
    def import_wechat_data(self, db_key: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
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
        # 如果有自定义路径配置,传递给服务(只需要wechat_dir和current_user,databases会自动查找)
        custom_paths = None
        wechat_dir = self.settings.get("wechat_data_dir")
        wxid = self.settings.get("wechat_user_wxid")
        
        if wechat_dir and wxid:
            custom_paths = {
                "wechat_dir": wechat_dir,
                "current_user": wxid
            }
            logger.debug(f"[DEBUG Bridge] 使用自定义路径: {custom_paths}")
        else:
            logger.debug(f"[DEBUG Bridge] 未配置自定义路径,将使用自动检测")
        
        return self.wechat_service.import_wechat_data(db_key, options or {}, custom_paths)

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
    
    def get_conversation_list(self) -> dict[str, Any]:
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
        return service.get_conversation_list()
    
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
            engine_type = monitor._suggestion_config.get('engine_type', 'template')
            engine = SuggestionEngineFactory.create(engine_type)

            logger.debug(f"[Bridge] generate_suggestion: engine_type={engine_type}, intent={intent}")

            # 自动补充上下文：情绪摘要
            if 'emotion_summary' not in context and monitor.emotion_tracker:
                context['emotion_summary'] = monitor.emotion_tracker.get_emotion_summary()

            # 自动补充上下文：最近消息
            if 'recent_messages' not in context and monitor.current_batch_id:
                try:
                    from ..services.realtime.message_query import get_messages_with_sentiment
                    recent = get_messages_with_sentiment(monitor.current_batch_id, 50)
                    context['recent_messages'] = recent
                except Exception as e:
                    logger.error(f"[Bridge] 获取最近消息失败: {e}")

            # 自动补充上下文：联系人画像与本体画像
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
                except Exception as e:
                    logger.error(f"[Bridge] 获取画像失败: {e}")

            # 传递联系人名称以便查询调教规则
            if monitor.current_display_name:
                context['display_name'] = monitor.current_display_name

            # 获取触发类型，默认通过 tracker 状态推断
            trigger_type = context.get("trigger_type")
            if not trigger_type:
                # 从 Tracker 获取当前情绪摘要来推断
                if hasattr(monitor, 'emotion_tracker') and monitor.emotion_tracker:
                    summary = monitor.emotion_tracker.get_emotion_summary()
                    if summary['trend'] == 'negative':
                        trigger_type = "negative_streak"
                    elif summary['trend'] == 'positive':
                        trigger_type = "positive_window"
                    else:
                        trigger_type = "topic_cooling"
                else:
                    trigger_type = "topic_cooling"

            result = engine.generate(trigger_type, intent, context)

            # 将手动生成的建议也写入 DB（供隐式反馈对比使用）
            try:
                import time as _time
                from ..db.connection import get_db
                conn = get_db()
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
                now_time = int(_time.time())
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO realtime_suggestions
                    (batch_id, trigger_type, intent, severity, summary, speeches,
                     confidence, status, engine_type, trigger_context, created_at, reply)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'displayed', ?, ?, ?, ?)
                ''', (
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
                    }, ensure_ascii=False),
                    now_time,
                    getattr(result, 'reply', None),
                ))
                inserted_id = cursor.lastrowid
                conn.commit()
                logger.debug(f"[Bridge] 手动建议已写入 realtime_suggestions 表, id={inserted_id}")
            except Exception as db_e:
                inserted_id = None
                now_time = int(_time.time())
                logger.error(f"[Bridge] 写入建议到DB失败: {db_e}")

            # 提取 AI 实际参考的聊天记录（最多 10 条）
            recent_used = context.get('recent_messages', [])
            recent_for_display = []
            for msg in recent_used[-10:]:
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
        return self.settings

    def set_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存设置"""
        self.settings.update(payload)
        self._save_settings()
        return {"saved": True, "payload": payload}
    
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
            import os
            
            logger.info(f"[DEBUG] 开始扫描目录: {wechat_dir}")
            
            if not os.path.exists(wechat_dir):
                return {
                    "ok": False,
                    "error": f"目录不存在: {wechat_dir}",
                    "wxids": [],
                    "databases": {}
                }
            
            result = {
                "ok": True,
                "wxids": [],
                "databases": {}
            }
            
            # 扫描所有子目录，查找 wxid_ 开头的文件夹
            logger.debug(f"[DEBUG] 列举目录内容...")
            entries = os.listdir(wechat_dir)
            logger.debug(f"[DEBUG] 找到 {len(entries)} 个条目")
            
            for entry in entries:
                # 只处理 wxid_ 开头的目录名
                if not entry.startswith("wxid_"):
                    continue
                
                entry_path = os.path.join(wechat_dir, entry)
                
                # 跳过非目录
                if not os.path.isdir(entry_path):
                    logger.debug(f"[DEBUG] 跳过非目录: {entry}")
                    continue
                
                wxid = entry
                logger.debug(f"[DEBUG] 找到wxid: {wxid}")
                result["wxids"].append(wxid)
                
                # 查找该用户的数据库文件
                user_data = {
                    "msg_dbs": [],
                    "contact_db": None
                }
                
                # 查找消息数据库 (Msg/Multi/MSG*.db)
                msg_dir = os.path.join(entry_path, "Msg")
                if os.path.isdir(msg_dir):
                    logger.debug(f"[DEBUG] 扫描消息目录: {msg_dir}")
                    # 限制扫描深度，避免过深的递归
                    for root, dirs, files in os.walk(msg_dir):
                        # 只扫描Msg和Msg/Multi两层
                        depth = root[len(msg_dir):].count(os.sep)
                        if depth > 1:
                            dirs[:] = []  # 不再深入
                            continue
                        
                        for file in files:
                            if file.startswith("MSG") and file.endswith(".db"):
                                db_path = os.path.join(root, file)
                                user_data["msg_dbs"].append(db_path)
                                logger.debug(f"[DEBUG] 找到消息数据库: {file}")
                
                # 查找联系人数据库 (Msg/MicroMsg.db)
                micromsg_path = os.path.join(entry_path, "Msg", "MicroMsg.db")
                if os.path.exists(micromsg_path):
                    user_data["contact_db"] = micromsg_path
                    logger.debug(f"[DEBUG] 找到联系人数据库: MicroMsg.db")
                
                result["databases"][wxid] = user_data
            
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
                "databases": {}
            }

    # ==================== 实时监听相关 ====================
    
    def start_realtime_monitor(self, talker_display_name: str) -> dict[str, Any]:
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
                talker_username="",  # wxauto4 自动处理
                talker_display_name=talker_display_name
            )
            
            return {
                "ok": result['success'],
                "success": result['success'],
                "batch_id": result.get('batch_id'),
                "message": result.get('message'),
                "error": result.get('error')
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
                "batch_id": status.get('batch_id'),
                "message_count": status.get('message_count', 0),
                "model_ready": status.get('model_ready', False),
                "chat_ready": status.get('chat_ready', False),
                "chat_error": status.get('chat_error', ''),
                "polling_alive": status.get('polling_alive', True),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取实时监听状态异常: {e}")
            return {
                "ok": False,
                "error": str(e),
                "is_monitoring": False,
                "message_count": 0
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
            
            messages = get_messages_with_sentiment(batch_id, limit)
            
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

    def get_pending_suggestions(self, batch_id: str) -> dict[str, Any]:
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
                    dismissed_at INTEGER,
                    reply TEXT
                )
            ''')
            try:
                conn.execute("ALTER TABLE realtime_suggestions ADD COLUMN reply TEXT")
            except:
                pass

            # 查询 pending 状态的建议
            cursor = conn.execute('''
                SELECT id, trigger_type, intent, severity, summary, speeches,
                       confidence, engine_type, trigger_context, status, created_at, reply
                FROM realtime_suggestions
                WHERE batch_id = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 20
            ''', (batch_id,))

            suggestions = []
            for row in cursor.fetchall():
                import json
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
                    'reply': row['reply']
                })

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

    def dismiss_suggestion(self, suggestion_id: int) -> dict[str, Any]:
        """
        标记建议为已关闭

        Args:
            suggestion_id: 建议记录 ID
        """
        try:
            import time as _time
            from ..db.connection import get_db

            conn = get_db()
            conn.execute('''
                UPDATE realtime_suggestions
                SET status = 'dismissed', dismissed_at = ?
                WHERE id = ?
            ''', (int(_time.time()), suggestion_id))
            conn.commit()

            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 关闭建议失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_suggestion_config(self) -> dict[str, Any]:
        """获取 AI 建议配置（从系统设置读取）"""
        try:
            return {
                "ok": True, 
                "config": {
                    "trigger_mode": self.settings.get("trigger_mode", "semi_auto"),
                    "intent": self.settings.get("intent", "maintain"),
                    "auto_rate_limit": int(self.settings.get("auto_rate_limit", 10)),
                    "engine_type": "llm",
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
            recent_messages = get_messages_with_sentiment(batch_id, 10)
            
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
            # 1. 更新通用设置文件
            for key in ('trigger_mode', 'intent', 'auto_rate_limit'):
                if key in config:
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

    def get_contact_profile(self, display_name: str) -> dict[str, Any]:
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

            cached = profiler.get_profile(display_name)
            estimate = profiler.estimate_tokens(display_name)

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
        custom_budget: int = 0
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
            result = profiler.generate_profile(display_name, budget_level, custom_budget)
            return result
        except Exception as e:
            logger.error(f"[Bridge] 生成联系人画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def get_self_profile(self, display_name: str) -> dict[str, Any]:
        """获取用户本人的专属克隆画像缓存"""
        try:
            from ..services.realtime.self_profiler import SelfProfiler
            profiler = SelfProfiler()

            cached = profiler.get_profile(display_name)
            estimate = profiler.estimate_tokens(display_name)

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
        custom_budget: int = 0
    ) -> dict[str, Any]:
        """生成用户本体的聊天克隆画像"""
        try:
            from ..services.realtime.self_profiler import SelfProfiler
            profiler = SelfProfiler()
            result = profiler.generate_profile(display_name, budget_level, custom_budget)
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

            # 如果提供了自定义配置，更新服务配置
            if config:
                from ..services.analysis.feature_extraction_config import FeatureExtractionConfig
                service_config = FeatureExtractionConfig(**config)
                service = FeatureExtractionService(service_config)
            else:
                service = self._get_feature_service()

            # 执行特征提取（异步任务）
            result = service.extract_features(conversation_id)

            return {
                "success": True,
                "data": {
                    "task_id": result["task_id"],
                    "status": "completed",
                    "message": "Feature extraction completed"
                }
            }
        except Exception as e:
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
            from ..db.connection import get_db

            db = get_db()

            # 查询统计
            cursor = db.execute("""
                SELECT
                    COUNT(*) as count,
                    AVG(response_time_seconds) as avg,
                    MIN(response_time_seconds) as min,
                    MAX(response_time_seconds) as max
                FROM response_times
                WHERE conversation_id = ? AND is_abnormal = 0
            """, (conversation_id,))

            row = cursor.fetchone()

            # 计算中位数
            cursor2 = db.execute("""
                SELECT response_time_seconds
                FROM response_times
                WHERE conversation_id = ? AND is_abnormal = 0
                ORDER BY response_time_seconds
            """, (conversation_id,))

            values = [r["response_time_seconds"] for r in cursor2.fetchall()]
            median = values[len(values) // 2] if values else None

            # 查询异常数量
            abnormal_cursor = db.execute("""
                SELECT COUNT(*) as abnormal_count
                FROM response_times
                WHERE conversation_id = ? AND is_abnormal = 1
            """, (conversation_id,))

            abnormal_row = abnormal_cursor.fetchone()

            return {
                "success": True,
                "data": {
                    "count": row["count"],
                    "avg": round(row["avg"], 1) if row["avg"] else None,
                    "median": median,
                    "min": row["min"],
                    "max": row["max"],
                    "stddev": 0,  # 简化处理
                    "abnormal_count": abnormal_row["abnormal_count"]
                }
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
            char_ratio = overall_row["char_ratio"]

            if char_ratio >= 1:
                interpretation = f"对方投入的字数是您的{char_ratio:.2f}倍"
            else:
                interpretation = f"您投入的字数是对方的{1/char_ratio:.2f}倍"

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
                            "char_ratio": round(row["char_ratio"], 2)
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

    # ==================== 好感度分析相关 ====================

    # -- 关系上下文 --

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

    def analyze_affinity(self, conversation_id: int, force_reanalyze: bool = False, config_overrides: dict = None) -> dict[str, Any]:
        """执行好感度分析（异步，立即返回 task_id 供轮询）"""
        try:
            import threading
            import time as _time
            from ..services.analysis.affinity_analysis_service import AffinityAnalysisService

            service = AffinityAnalysisService()
            # 保存服务实例引用，供 get_affinity_progress 查询进度
            self._affinity_service = service

            # 预生成 task_id，与 service.analyze 内部生成的保持一致
            task_id = f"affinity_{conversation_id}_{int(_time.time())}"

            def _run_analysis():
                try:
                    service.analyze(conversation_id, force_reanalyze, config_overrides)
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
            from ..services.analysis.affinity_analysis_service import AffinityAnalysisService
            from dataclasses import asdict
            
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
        messages = buffer.get_batch_messages(batch_id)

        # 读取建议
        suggestions = []
        try:
            from ..db.connection import get_db
            conn = get_db()
            rows = conn.execute(
                'SELECT * FROM realtime_suggestions WHERE batch_id = ? ORDER BY created_at',
                (batch_id,)
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
            args=(batch_id, display_name, messages, suggestions, None, user_chat_history),
            daemon=True
        )
        t.start()
        logger.debug(f"[Bridge] 会话归档已启动 (batch={batch_id[:8]}...)")

    def get_latest_thread(self, display_name: str) -> dict[str, Any]:
        """获取该联系人最近的会话线程（24 小时内）"""
        try:
            from ..services.realtime.session_thread_service import SessionThreadService
            svc = SessionThreadService()
            thread = svc.get_latest_thread(display_name)
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
            ctx = svc.load_thread_context(thread_id)
            return {
                "ok": True,
                "context": ctx
            }
        except Exception as e:
            logger.error(f"[Bridge] 加载线程上下文失败: {e}")
            return {"ok": False, "error": str(e)}
