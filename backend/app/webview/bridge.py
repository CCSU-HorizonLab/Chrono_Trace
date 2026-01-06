from typing import Any
import json
import os
from pathlib import Path
from ..services.wechat.ingest_service import WeChatIngestService

class Bridge:
    """PyWebView JS API Bridge: 暴露给前端调用的方法。"""

    def __init__(self):
        self.wechat_service = WeChatIngestService()
        self.settings_file = Path(__file__).parent.parent.parent / "data" / "settings.json"
        self._load_settings()

        # 延迟加载特征提取服务（避免循环导入）
        self._feature_service = None

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
            print(f"保存设置失败: {e}")

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
                print("[WARN] 自定义路径配置不完整，尝试自动检测")
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
            print(f"[DEBUG Bridge] 使用自定义路径: {custom_paths}")
        else:
            print(f"[DEBUG Bridge] 未配置自定义路径,将使用自动检测")
        
        return self.wechat_service.import_wechat_data(db_key, options or {}, custom_paths)

    # ==================== 原有接口（保留） ====================

    def ingest_data(self, file_path: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": True, "file_path": file_path, "options": options or {}}

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
        return {
            "intent": intent,
            "summary": "示例建议：保持耐心与共情表达。",
            "speech": ["我理解你的感受，我们一起看怎么改善。"],
        }

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
            
            print(f"[DEBUG] 打开文件选择对话框: title={title}, file_types={file_types}")
            
            # 获取当前窗口
            if not webview.windows or len(webview.windows) == 0:
                print("[ERROR] 没有可用的 webview 窗口")
                return {"path": None, "error": "No webview window available"}
            
            window = webview.windows[0]
            
            # 解析文件类型
            if file_types and file_types != "*.*":
                filter_name = f"数据库文件 ({file_types})"
                file_filter = (filter_name, file_types)
            else:
                file_filter = ("所有文件 (*.*)", "*.*")
            
            print(f"[DEBUG] 调用 create_file_dialog, filter={file_filter}")
            
            # 调用文件选择对话框
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory="",
                file_types=(file_filter,)
            )
            
            print(f"[DEBUG] 文件选择结果: {result}")
            
            if result and len(result) > 0:
                selected_path = result[0]
                print(f"[DEBUG] 已选择文件: {selected_path}")
                return {"path": selected_path}
            
            print("[DEBUG] 用户取消选择")
            return {"path": None}
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[ERROR] 文件选择失败: {e}")
            print("[ERROR] 详细错误:")
            print(error_detail)
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
            
            print(f"[DEBUG] 打开目录选择对话框: title={title}")
            
            # 获取当前窗口
            if not webview.windows or len(webview.windows) == 0:
                print("[ERROR] 没有可用的 webview 窗口")
                return {"path": None, "error": "No webview window available"}
            
            window = webview.windows[0]
            
            print("[DEBUG] 调用 create_file_dialog (FOLDER_DIALOG)")
            
            # 调用目录选择对话框
            result = window.create_file_dialog(
                webview.FOLDER_DIALOG
            )
            
            print(f"[DEBUG] 目录选择结果: {result}")
            
            if result and len(result) > 0:
                selected_path = result[0]
                print(f"[DEBUG] 已选择目录: {selected_path}")
                return {"path": selected_path}
            
            print("[DEBUG] 用户取消选择")
            return {"path": None}
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[ERROR] 目录选择失败: {e}")
            print("[ERROR] 详细错误:")
            print(error_detail)
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
            
            print(f"[DEBUG] 开始扫描目录: {wechat_dir}")
            
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
            print(f"[DEBUG] 列举目录内容...")
            entries = os.listdir(wechat_dir)
            print(f"[DEBUG] 找到 {len(entries)} 个条目")
            
            for entry in entries:
                # 只处理 wxid_ 开头的目录名
                if not entry.startswith("wxid_"):
                    continue
                
                entry_path = os.path.join(wechat_dir, entry)
                
                # 跳过非目录
                if not os.path.isdir(entry_path):
                    print(f"[DEBUG] 跳过非目录: {entry}")
                    continue
                
                wxid = entry
                print(f"[DEBUG] 找到wxid: {wxid}")
                result["wxids"].append(wxid)
                
                # 查找该用户的数据库文件
                user_data = {
                    "msg_dbs": [],
                    "contact_db": None
                }
                
                # 查找消息数据库 (Msg/Multi/MSG*.db)
                msg_dir = os.path.join(entry_path, "Msg")
                if os.path.isdir(msg_dir):
                    print(f"[DEBUG] 扫描消息目录: {msg_dir}")
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
                                print(f"[DEBUG] 找到消息数据库: {file}")
                
                # 查找联系人数据库 (Msg/MicroMsg.db)
                micromsg_path = os.path.join(entry_path, "Msg", "MicroMsg.db")
                if os.path.exists(micromsg_path):
                    user_data["contact_db"] = micromsg_path
                    print(f"[DEBUG] 找到联系人数据库: MicroMsg.db")
                
                result["databases"][wxid] = user_data
            
            print(f"[DEBUG] 扫描完成，找到 {len(result['wxids'])} 个wxid")
            return result
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[ERROR] 扫描微信目录失败: {e}")
            print(error_detail)
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
            
            print(f"[Bridge] 启动实时监听: {talker_display_name}")
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
            print(f"[Bridge] 启动实时监听异常: {e}")
            traceback.print_exc()
            return {
                "ok": False,
                "success": False,
                "error": str(e)
            }
    
    def stop_realtime_monitor(self) -> dict[str, Any]:
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
            
            print("[Bridge] 停止实时监听")
            monitor_service = RealtimeMonitorService()
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
            print(f"[Bridge] 停止实时监听异常: {e}")
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
                "message_count": status.get('message_count', 0)
            }
        except Exception as e:
            print(f"[Bridge] 获取实时监听状态异常: {e}")
            return {
                "ok": False,
                "error": str(e),
                "is_monitoring": False,
                "message_count": 0
            }
    
    def get_realtime_messages(self, batch_id: str) -> dict[str, Any]:
        """
        获取批次消息列表
        
        Args:
            batch_id: 批次ID
            
        Returns:
            {
                "ok": True,
                "messages": [...]
            }
        """
        try:
            from ..services.realtime.monitor_service import RealtimeMonitorService
            
            monitor_service = RealtimeMonitorService()
            messages = monitor_service.message_buffer.get_batch_messages(batch_id)
            
            return {
                "ok": True,
                "messages": messages
            }
        except Exception as e:
            print(f"[Bridge] 获取批次消息异常: {e}")
            return {
                "ok": False,
                "error": str(e),
                "messages": []
            }

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
            print(f"[Bridge] 开始特征提取: conversation_id={conversation_id}")

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
            print(f"[Bridge] 特征提取失败: {e}")
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
            print(f"[Bridge] 查询任务进度失败: {e}")
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
            print(f"[Bridge] 获取会话列表失败: {e}")
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
            print(f"[Bridge] 获取响应时间统计失败: {e}")
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
            print(f"[Bridge] 获取主动性统计失败: {e}")
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
            print(f"[Bridge] 获取字数统计失败: {e}")
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
            print(f"[Bridge] 重新分析: conversation_id={conversation_id}")

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
            print(f"[Bridge] 重新分析失败: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

