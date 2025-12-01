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

    def get_analysis(self, date_range: dict[str, str]) -> dict[str, Any]:
        return {
            "emotion": {"labels": ["2025-01-01", "2025-01-02"], "values": [0.2, 0.6]},
            "frequency": {"labels": ["Mon", "Tue"], "values": [12, 8]},
            "wordcloud": [{"text": "聊天", "weight": 10}, {"text": "建议", "weight": 6}],
        }

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

