"""实时消息查询服务

提供消息列表查询功能,联合查询消息和情感分析结果
"""
import json
from ...db.connection import get_db


def get_messages_with_sentiment(batch_id: str, limit: int = 50):
    """获取消息及其情感分析结果
    
    Args:
        batch_id: 批次ID
        limit: 返回消息数量限制
    
    Returns:
        消息列表,每条消息包含情感分析结果
    """
    db = get_db()
    cursor = db.execute("""
        SELECT 
            m.id,
            m.message_hash,
            m.sender_attr,
            m.content,
            m.message_type,
            m.timestamp,
            s.polarity,
            s.intensity,
            s.confidence,
            s.rules_applied
        FROM realtime_message_buffer m
        LEFT JOIN realtime_sentiment_cache s ON m.message_hash = s.message_id
        WHERE m.batch_id = ? AND m.sender_attr != 'system'
        ORDER BY m.timestamp DESC
        LIMIT ?
    """, (batch_id, limit))
    
    messages = []
    for row in cursor.fetchall():
        message = {
            'id': row[0],
            'message_hash': row[1],
            'sender': row[2],  # 'self', 'friend', 'system'
            'content': row[3],
            'type': row[4],
            'timestamp': row[5],
        }
        
        # 如果有情感分析结果,添加到消息中
        if row[6] is not None:
            message['sentiment'] = {
                'polarity': row[6],  # -1/0/1
                'intensity': row[7],  # -1.0 to 1.0
                'confidence': row[8],  # 0.0 to 1.0
                'rules': json.loads(row[9]) if row[9] else []
            }
        else:
            message['sentiment'] = None
        
        messages.append(message)
    
    return messages
