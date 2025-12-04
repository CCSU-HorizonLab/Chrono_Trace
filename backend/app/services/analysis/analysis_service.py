"""历史数据分析服务"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from ...db.connection import get_db
from .wordcloud_generator import WordCloudGenerator


class AnalysisService:
    """历史数据分析服务"""
    
    def __init__(self):
        self.db = get_db()
        self.wordcloud_gen = WordCloudGenerator()
    
    def get_conversation_list(self) -> Dict[str, Any]:
        """
        获取所有联系人列表（用于前端下拉选择）
        
        Returns:
            {
                "ok": True,
                "conversations": [
                    {
                        "id": 1,
                        "name": "张三",
                        "username": "wxid_xxx",
                        "message_count": 1234,
                        "last_message_time": "2025-01-07 15:30"
                    },
                    ...
                ]
            }
        """
        try:
            # 查询所有会话，关联联系人表获取备注名/昵称
            # 优先级: contacts.remark > contacts.nickname > conversations.display_name > conversations.username
            cursor = self.db.execute("""
                SELECT 
                    c.id,
                    c.username,
                    c.display_name,
                    COALESCE(
                        NULLIF(TRIM(ct.remark), ''),
                        NULLIF(TRIM(ct.nickname), ''),
                        NULLIF(TRIM(c.display_name), ''),
                        NULLIF(TRIM(c.username), ''),
                        '未知联系人'
                    ) as name,
                    c.message_count,
                    c.updated_at
                FROM conversations c
                LEFT JOIN contacts ct ON c.username = ct.username
                WHERE c.is_deleted = 0
                    AND c.message_count > 0
                ORDER BY c.updated_at DESC
            """)
            
            conversations = []
            for row in cursor.fetchall():
                conversations.append({
                    "id": row[0],
                    "username": row[1],
                    "name": row[3],  # 优先使用备注名
                    "message_count": row[4],
                    "last_message_time": datetime.fromtimestamp(row[5]).strftime("%Y-%m-%d %H:%M")
                })
            
            print(f"[DEBUG] 查询到 {len(conversations)} 个联系人")
            
            return {
                "ok": True,
                "conversations": conversations
            }
        except Exception as e:
            print(f"[ERROR] 获取联系人列表失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "ok": False,
                "error": str(e),
                "conversations": []
            }
    
    def get_analysis(
        self, 
        conversation_id: int,
        from_date: str,
        to_date: str
    ) -> Dict[str, Any]:
        """
        获取分析数据（词云 + 统计）
        
        Args:
            conversation_id: 会话ID（必填）
            from_date: 开始日期 "2025-01-01"
            to_date: 结束日期 "2025-01-07"
        
        Returns:
            {
                "subject": {...},
                "timeseries": [],
                "wordcloud": [...]
            }
        """
        try:
            print(f"[DEBUG] 开始分析: conversation_id={conversation_id}, from={from_date}, to={to_date}")
            
            # 1. 转换日期为时间戳
            from_ts = int(datetime.strptime(from_date, "%Y-%m-%d").timestamp())
            to_ts = int(datetime.strptime(to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp())
            
            print(f"[DEBUG] 时间戳范围: {from_ts} - {to_ts}")
            
            # 2. 获取会话详情
            subject_info = self._get_subject_info(conversation_id)
            if not subject_info:
                return {
                    "error": "会话不存在",
                    "subject": None,
                    "timeseries": [],
                    "wordcloud": []
                }
            
            print(f"[DEBUG] 会话详情: {subject_info}")
            
            # 3. 查询消息内容
            messages = self._get_messages(conversation_id, from_ts, to_ts)
            msg_count = len(messages)
            
            print(f"[DEBUG] 查询到 {msg_count} 条消息")
            
            # 4. 生成词云
            wordcloud = self.wordcloud_gen.generate(messages, top_n=50)
            
            print(f"[DEBUG] 生成词云: {len(wordcloud)} 个词")
            
            # 5. 组装返回数据
            return {
                "subject": {
                    "id": subject_info["id"],
                    "name": subject_info["name"],
                    "avatar": subject_info.get("avatar"),
                    "stats": {
                        "msgCount": msg_count,
                        "avgScore": 0.0,  # 暂不实现情绪分析
                        "maxDay": None,
                        "minDay": None
                    }
                },
                "timeseries": [],  # 暂不实现
                "wordcloud": wordcloud
            }
        
        except Exception as e:
            print(f"[ERROR] 分析失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "subject": None,
                "timeseries": [],
                "wordcloud": []
            }
    
    def _get_subject_info(self, conversation_id: int) -> Optional[Dict]:
        """获取会话详情"""
        cursor = self.db.execute("""
            SELECT 
                c.id,
                c.username,
                COALESCE(
                    NULLIF(TRIM(ct.remark), ''),
                    NULLIF(TRIM(ct.nickname), ''),
                    NULLIF(TRIM(c.display_name), ''),
                    NULLIF(TRIM(c.username), ''),
                    '未知联系人'
                ) as name,
                c.avatar_path
            FROM conversations c
            LEFT JOIN contacts ct ON c.username = ct.username
            WHERE c.id = ?
        """, (conversation_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            "id": row[0],
            "username": row[1],
            "name": row[2],
            "avatar": row[3]
        }
    
    def _get_messages(
        self, 
        conversation_id: int, 
        from_ts: int, 
        to_ts: int,
        limit: int = 10000
    ) -> List[str]:
        """获取消息内容列表"""
        cursor = self.db.execute("""
            SELECT content
            FROM messages
            WHERE conversation_id = ?
                AND timestamp BETWEEN ? AND ?
                AND message_type = 1
                AND content IS NOT NULL
                AND content != ''
            ORDER BY timestamp DESC
            LIMIT ?
        """, (conversation_id, from_ts, to_ts, limit))
        
        messages = [row[0] for row in cursor.fetchall()]
        return messages
