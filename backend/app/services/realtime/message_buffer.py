"""
实时消息暂存表数据访问层
负责消息的增删改查操作
"""
import sys
import logging
import time
import threading
from typing import List, Dict, Optional
from ...db.connection import get_db

logger = logging.getLogger(__name__)
def _print(*args, **kwargs):
    """强制刷新的打印函数"""
    logger.debug(*args, **kwargs)


class MessageBuffer:
    """消息暂存表操作类"""
    
    def __init__(self):
        """初始化,确保线程安全"""
        self._lock = threading.Lock()
    
    def save_message(
        self,
        batch_id: str,
        talker_username: str,
        talker_display_name: str,
        message_data: dict
    ) -> bool:
        """
        保存单条消息到暂存表
        
        Args:
            batch_id: 批次ID
            talker_username: 对话对象username
            talker_display_name: 对话对象显示名
            message_data: 消息数据字典
                {
                    'message_hash': str,
                    'runtime_id': str,
                    'sender_attr': str,  # self/friend/system
                    'content': str,
                    'message_type': str,
                    'timestamp': int
                }
        
        Returns:
            bool: 是否保存成功
        """
        with self._lock:
            try:
                conn = get_db()
                cursor = conn.cursor()
                
                now = int(time.time())
                
                cursor.execute('''
                    INSERT INTO realtime_message_buffer (
                        talker_username,
                        talker_display_name,
                        message_hash,
                        runtime_id,
                        sender_attr,
                        content,
                        message_type,
                        timestamp,
                        captured_at,
                        batch_id,
                        is_processed,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ''', (
                    talker_username,
                    talker_display_name,
                    message_data.get('message_hash'),
                    message_data.get('runtime_id'),
                    message_data.get('sender_attr'),
                    message_data.get('content'),
                    message_data.get('message_type', 'text'),
                    message_data.get('timestamp', now),
                    now,
                    batch_id,
                    now
                ))
                
                conn.commit()
                return True
                
            except Exception as e:
                _print(f"❌ 数据库保存失败: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    def get_batch_messages(
        self, 
        batch_id: str, 
        processed: Optional[bool] = None
    ) -> List[Dict]:
        """
        获取指定批次的消息
        
        Args:
            batch_id: 批次ID
            processed: 是否只查询已处理/未处理(None=全部)
        
        Returns:
            List[Dict]: 消息列表
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            if processed is None:
                cursor.execute('''
                    SELECT 
                        id, talker_username, talker_display_name,
                        message_hash, runtime_id, sender_attr,
                        content, message_type, timestamp,
                        captured_at, is_processed, batch_id, created_at
                    FROM realtime_message_buffer
                    WHERE batch_id = ?
                    ORDER BY timestamp ASC
                ''', (batch_id,))
            else:
                cursor.execute('''
                    SELECT 
                        id, talker_username, talker_display_name,
                        message_hash, runtime_id, sender_attr,
                        content, message_type, timestamp,
                        captured_at, is_processed, batch_id, created_at
                    FROM realtime_message_buffer
                    WHERE batch_id = ? AND is_processed = ?
                    ORDER BY timestamp ASC
                ''', (batch_id, 1 if processed else 0))
            
            rows = cursor.fetchall()
            
            messages = []
            for row in rows:
                messages.append({
                    'id': row[0],
                    'talker_username': row[1],
                    'talker_display_name': row[2],
                    'message_hash': row[3],
                    'runtime_id': row[4],
                    'sender_attr': row[5],
                    'content': row[6],
                    'message_type': row[7],
                    'timestamp': row[8],
                    'captured_at': row[9],
                    'is_processed': row[10],
                    'batch_id': row[11],
                    'created_at': row[12]
                })
            
            return messages
            
        except Exception as e:
            logger.error(f"[MessageBuffer] 获取批次消息失败: {e}")
            return []
    
    def get_batch_count(self, batch_id: str) -> int:
        """
        获取批次消息数量
        
        Args:
            batch_id: 批次ID
        
        Returns:
            int: 消息数量
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT COUNT(*) FROM realtime_message_buffer
                WHERE batch_id = ?
            ''', (batch_id,))
            
            result = cursor.fetchone()
            count = result[0] if result else 0
            return count
            
        except Exception as e:
            logger.error(f"[MessageBuffer] 获取批次消息数量失败: {e}")
            return 0
    
    def mark_as_processed(self, batch_id: str) -> int:
        """
        标记批次消息为已处理
        
        Args:
            batch_id: 批次ID
        
        Returns:
            int: 影响行数
        """
        with self._lock:
            try:
                conn = get_db()
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE realtime_message_buffer
                    SET is_processed = 1
                    WHERE batch_id = ?
                ''', (batch_id,))
                
                conn.commit()
                return cursor.rowcount
                
            except Exception as e:
                logger.error(f"[MessageBuffer] 标记批次为已处理失败: {e}")
                return 0
    
    def delete_batch(self, batch_id: str) -> int:
        """
        删除批次消息
        
        Args:
            batch_id: 批次ID
        
        Returns:
            int: 删除行数
        """
        with self._lock:
            try:
                conn = get_db()
                cursor = conn.cursor()
                
                cursor.execute('''
                    DELETE FROM realtime_message_buffer
                    WHERE batch_id = ?
                ''', (batch_id,))
                
                conn.commit()
                return cursor.rowcount
                
            except Exception as e:
                logger.error(f"[MessageBuffer] 删除批次消息失败: {e}")
                return 0
    
    def get_recent_batches(self, limit: int = 10) -> List[Dict]:
        """
        获取最近的监听批次列表
        
        Args:
            limit: 返回数量限制
        
        Returns:
            List[Dict]: 批次列表
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    batch_id,
                    talker_username,
                    talker_display_name,
                    COUNT(*) as message_count,
                    MIN(timestamp) as first_message_time,
                    MAX(timestamp) as last_message_time,
                    SUM(CASE WHEN is_processed = 1 THEN 1 ELSE 0 END) as processed_count
                FROM realtime_message_buffer
                GROUP BY batch_id
                ORDER BY MAX(created_at) DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            
            batches = []
            for row in rows:
                batches.append({
                    'batch_id': row[0],
                    'talker_username': row[1],
                    'talker_display_name': row[2],
                    'message_count': row[3],
                    'first_message_time': row[4],
                    'last_message_time': row[5],
                    'processed_count': row[6],
                    'is_fully_processed': row[6] == row[3]
                })
            
            return batches
            
        except Exception as e:
            logger.error(f"[MessageBuffer] 获取批次列表失败: {e}")
            return []
    
    def message_exists(self, message_hash: str) -> bool:
        """
        检查消息是否已存在(去重)
        
        Args:
            message_hash: 消息哈希值
        
        Returns:
            bool: 是否存在
        """
        try:
            if not message_hash:
                return False
            
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT COUNT(*) FROM realtime_message_buffer
                WHERE message_hash = ?
            ''', (message_hash,))
            
            result = cursor.fetchone()
            return result[0] > 0 if result else False
            
        except Exception as e:
            logger.error(f"[MessageBuffer] 检查消息是否存在失败: {e}")
            return False
    
    def clear_old_batches(self, days: int = 30) -> int:
        """
        清理超过指定天数的已处理批次
        
        Args:
            days: 天数阈值
        
        Returns:
            int: 删除的消息数
        """
        with self._lock:
            try:
                conn = get_db()
                cursor = conn.cursor()
                
                threshold = int(time.time()) - (days * 24 * 3600)
                
                cursor.execute('''
                    DELETE FROM realtime_message_buffer
                    WHERE is_processed = 1 AND created_at < ?
                ''', (threshold,))
                
                conn.commit()
                return cursor.rowcount
                
            except Exception as e:
                logger.error(f"[MessageBuffer] 清理旧批次失败: {e}")
                return 0
