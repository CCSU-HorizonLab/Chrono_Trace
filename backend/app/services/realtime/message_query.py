"""实时消息查询服务

提供消息列表查询功能,联合查询消息和情感分析结果
"""
import json
from ...db.connection import get_db
def get_messages_with_sentiment(batch_id: str, limit: int = 50, exclude_system: bool = True, order_desc: bool = True):
    """获取消息及其情感分析结果

    Args:
        batch_id: 批次ID
        limit: 返回消息数量限制
        exclude_system: 是否排除系统消息 (默认: True)
        order_desc: 是否按时间降序排列 (默认: True)

    Returns:
        消息列表,每条消息包含情感分析结果
    """
    db = get_db()

    # 构建查询条件
    where_clause = "WHERE m.batch_id = ?"
    params = [batch_id]

    if exclude_system:
        where_clause += " AND m.sender_attr != 'system'"

    order_clause = "ORDER BY m.timestamp DESC" if order_desc else "ORDER BY m.timestamp ASC"

    cursor = db.execute(f"""
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
        {where_clause}
        {order_clause}
        LIMIT ?
    """, params + [limit])
    
    messages = []
    for row in cursor.fetchall():
        message = {
            'id': row[0],
            'message_hash': row[1],
            'sender': row[2],  # 'self', 'friend', 'system'
            'sender_attr': row[2],  # LLM 引擎使用此字段名
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
