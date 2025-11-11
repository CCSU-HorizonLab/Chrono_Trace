from typing import Any
from ..services.wechat.ingest_service import WeChatIngestService

class Bridge:
    """PyWebView JS API Bridge: 暴露给前端调用的方法。"""

    def __init__(self):
        self.wechat_service = WeChatIngestService()

    def ping(self) -> str:
        return "pong"

    # ==================== 微信数据导入相关 ====================
    
    def get_wechat_paths(self) -> dict[str, Any]:
        """
        获取微信数据库路径信息（用于前端展示）
        
        Returns:
            {"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
        """
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
        return self.wechat_service.import_wechat_data(db_key, options or {})

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
        return {
            "model": "local",
            "interval_minutes": 30,
            "range_days": 7,
        }

    def set_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"saved": True, "payload": payload}

