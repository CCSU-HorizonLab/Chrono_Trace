"""数据预处理服务 - 消息清洗与基础统计

包含三个服务类:
1. BasicPreprocessingService - 基础统计收集
2. PairPreprocessingService - 交互对构建
3. SessionManager - 会话切分和管理
"""
import re
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ...db.connection import get_db


class PreprocessingService:
    """消息预处理服务"""
    
    def __init__(self):
        self.db = get_db()
        self._compile_patterns()
    
    def _compile_patterns(self):
        """编译正则表达式模式（提升性能）"""
        # XML系统消息: <msg>...</msg>
        self.xml_pattern = re.compile(r'<msg>.*?</msg>', re.DOTALL | re.IGNORECASE)
        
        # 表情和媒体标签: [表情]、[图片]、[语音]等
        self.media_pattern = re.compile(r'\[.*?\]')
        
        # 多个连续空白字符
        self.whitespace_pattern = re.compile(r'\s+')
    
    def clean_content(self, content: str) -> Dict[str, Any]:
        """
        清洗单条消息内容
        
        Args:
            content: 原始消息内容
            
        Returns:
            {
                "original": "原始内容",
                "cleaned": "清洗后内容",
                "original_length": 15,
                "cleaned_length": 10,
                "has_xml": bool,
                "has_media": bool,
                "is_valid": bool
            }
        """
        if not content or not isinstance(content, str):
            return {
                "original": content or "",
                "cleaned": "",
                "original_length": 0,
                "cleaned_length": 0,
                "has_xml": False,
                "has_media": False,
                "is_valid": False
            }
        
        original = content
        original_length = len(content)
        
        # 检测是否包含XML标签
        has_xml = bool(self.xml_pattern.search(content))
        
        # 移除XML系统消息
        content = self.xml_pattern.sub('', content)
        
        # 检测是否包含媒体标签
        has_media = bool(self.media_pattern.search(content))
        
        # 移除表情和媒体标签
        content = self.media_pattern.sub('', content)
        
        # 规范化空白字符
        content = self.whitespace_pattern.sub(' ', content)
        
        # 去除首尾空格
        content = content.strip()
        
        cleaned_length = len(content)
        
        # 判断是否为有效消息（至少2个字符）
        is_valid = cleaned_length >= 2
        
        return {
            "original": original,
            "cleaned": content,
            "original_length": original_length,
            "cleaned_length": cleaned_length,
            "has_xml": has_xml,
            "has_media": has_media,
            "is_valid": is_valid
        }
    
    def calculate_message_stats(self, content: str) -> Dict[str, Any]:
        """
        计算消息的统计信息
        
        Args:
            content: 清洗后的消息内容
            
        Returns:
            {
                "char_count": 15,
                "word_count": 8,
                "has_punctuation": bool
            }
        """
        if not content:
            return {
                "char_count": 0,
                "word_count": 0,
                "has_punctuation": False
            }
        
        # 字符数（不含空格）
        char_count = len(content.replace(' ', ''))
        
        # 词数（使用jieba分词）
        word_count = 0
        try:
            import jieba
            words = list(jieba.cut(content))
            # 过滤空字符串和纯空格
            word_count = len([w for w in words if w.strip()])
        except ImportError:
            # 如果jieba未安装，使用简单的空格分割
            word_count = len(content.split())
        
        # 是否包含标点符号
        import string
        cn_punctuation = '，。！？、；：""''（）【】《》…—·'
        all_punctuation = string.punctuation + cn_punctuation
        has_punctuation = any(c in all_punctuation for c in content)
        
        return {
            "char_count": char_count,
            "word_count": word_count,
            "has_punctuation": has_punctuation
        }
    
    def preprocess_conversation(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 10000,
        use_cache: bool = True,
        force_reprocess: bool = False
    ) -> Dict[str, Any]:
        """
        预处理某个对话的所有消息（支持缓存）
        
        Args:
            conversation_id: 会话ID
            from_ts: 开始时间戳（可选）
            to_ts: 结束时间戳（可选）
            limit: 最大消息数量
            use_cache: 是否使用缓存（默认True）
            force_reprocess: 是否强制重新处理（默认False）
            
        Returns:
            {
                "conversation_id": 1,
                "total_messages": 1234,
                "valid_messages": 1150,
                "cleaned_messages": [...],
                "stats": {
                    "xml_count": 20,
                    "media_count": 84,
                    "avg_char_count": 12.5,
                    "avg_word_count": 8.3,
                    "cache_hit_rate": 0.95
                }
            }
        """
        print(f"\n[预处理] 开始处理会话 {conversation_id} (use_cache={use_cache}, force={force_reprocess})")
        
        # 构建查询SQL
        sql = """
            SELECT id, content, is_sender, timestamp, message_type
            FROM messages
            WHERE conversation_id = ?
                AND message_type = 1
        """
        params = [conversation_id]
        
        # 添加时间范围条件
        if from_ts is not None:
            sql += " AND timestamp >= ?"
            params.append(from_ts)
        
        if to_ts is not None:
            sql += " AND timestamp <= ?"
            params.append(to_ts)
        
        sql += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)
        
        # 查询消息
        cursor = self.db.execute(sql, tuple(params))
        messages = cursor.fetchall()
        
        print(f"[预处理] 查询到 {len(messages)} 条文本消息")
        
        # 初始化统计
        total_messages = len(messages)
        valid_messages = 0
        xml_count = 0
        media_count = 0
        total_char_count = 0
        total_word_count = 0
        cache_hits = 0
        
        cleaned_messages = []
        messages_to_cache = []  # 需要写入缓存的消息
        
        # 逐条处理
        for row in messages:
            msg_id = row[0]
            content = row[1]
            is_sender = row[2]
            timestamp = row[3]
            
            # 尝试从缓存读取
            cached = None
            if use_cache and not force_reprocess:
                cached = self._get_cached_message(msg_id)
            
            if cached:
                # 使用缓存数据
                cache_hits += 1
                if cached["is_valid"]:
                    valid_messages += 1
                    total_char_count += cached["char_count"]
                    total_word_count += cached["word_count"]
                    
                    cleaned_messages.append({
                        "id": msg_id,
                        "original_content": content,
                        "cleaned_content": cached["cleaned_content"],
                        "char_count": cached["char_count"],
                        "word_count": cached["word_count"],
                        "is_sender": is_sender,
                        "timestamp": timestamp
                    })
                
                if cached["has_xml"]:
                    xml_count += 1
                if cached["has_media"]:
                    media_count += 1
            else:
                # 实时清洗内容
                clean_result = self.clean_content(content)
                
                # 统计
                if clean_result["has_xml"]:
                    xml_count += 1
                if clean_result["has_media"]:
                    media_count += 1
                
                if clean_result["is_valid"]:
                    valid_messages += 1
                    
                    # 计算词数和字符数
                    stats = self.calculate_message_stats(clean_result["cleaned"])
                    total_char_count += stats["char_count"]
                    total_word_count += stats["word_count"]
                    
                    # 保存清洗后的消息
                    cleaned_messages.append({
                        "id": msg_id,
                        "original_content": clean_result["original"],
                        "cleaned_content": clean_result["cleaned"],
                        "char_count": stats["char_count"],
                        "word_count": stats["word_count"],
                        "is_sender": is_sender,
                        "timestamp": timestamp
                    })
                    
                    # 准备写入缓存
                    messages_to_cache.append({
                        "message_id": msg_id,
                        "conversation_id": conversation_id,
                        "cleaned_content": clean_result["cleaned"],
                        "char_count": stats["char_count"],
                        "word_count": stats["word_count"],
                        "is_valid": 1,
                        "has_xml": 1 if clean_result["has_xml"] else 0,
                        "has_media": 1 if clean_result["has_media"] else 0
                    })
                else:
                    # 无效消息也缓存，避免重复处理
                    messages_to_cache.append({
                        "message_id": msg_id,
                        "conversation_id": conversation_id,
                        "cleaned_content": "",
                        "char_count": 0,
                        "word_count": 0,
                        "is_valid": 0,
                        "has_xml": 1 if clean_result["has_xml"] else 0,
                        "has_media": 1 if clean_result["has_media"] else 0
                    })
        
        # 批量写入缓存
        if messages_to_cache and use_cache:
            self._batch_cache_messages(messages_to_cache)
        
        # 计算平均值
        avg_char_count = round(total_char_count / valid_messages, 2) if valid_messages > 0 else 0
        avg_word_count = round(total_word_count / valid_messages, 2) if valid_messages > 0 else 0
        cache_hit_rate = round(cache_hits / total_messages, 2) if total_messages > 0 else 0
        
        print(f"[预处理] 有效消息: {valid_messages}/{total_messages}")
        print(f"[预处理] XML消息: {xml_count}, 媒体消息: {media_count}")
        print(f"[预处理] 平均字符数: {avg_char_count}, 平均词数: {avg_word_count}")
        print(f"[预处理] 缓存命中率: {cache_hit_rate * 100}% ({cache_hits}/{total_messages})")
        
        return {
            "conversation_id": conversation_id,
            "total_messages": total_messages,
            "valid_messages": valid_messages,
            "cleaned_messages": cleaned_messages,
            "stats": {
                "xml_count": xml_count,
                "media_count": media_count,
                "avg_char_count": avg_char_count,
                "avg_word_count": avg_word_count,
                "invalid_messages": total_messages - valid_messages,
                "cache_hit_rate": cache_hit_rate
            }
        }
    
    def _get_cached_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        """从缓存读取预处理结果"""
        cursor = self.db.execute("""
            SELECT cleaned_content, char_count, word_count, is_valid, has_xml, has_media
            FROM message_preprocessed
            WHERE message_id = ?
        """, (message_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            "cleaned_content": row[0],
            "char_count": row[1],
            "word_count": row[2],
            "is_valid": row[3],
            "has_xml": row[4],
            "has_media": row[5]
        }
    
    def _batch_cache_messages(self, messages: List[Dict[str, Any]]):
        """批量写入缓存"""
        import time
        
        for msg in messages:
            try:
                self.db.execute("""
                    INSERT OR REPLACE INTO message_preprocessed
                    (message_id, conversation_id, cleaned_content, char_count, word_count, 
                     is_valid, has_xml, has_media, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    msg["message_id"],
                    msg["conversation_id"],
                    msg["cleaned_content"],
                    msg["char_count"],
                    msg["word_count"],
                    msg["is_valid"],
                    msg["has_xml"],
                    msg["has_media"],
                    int(time.time())
                ))
            except Exception as e:
                print(f"[预处理] 缓存消息 {msg['message_id']} 失败: {e}")
        
        self.db.commit()
       # print(f"[预处理] 已缓存 {len(messages)} 条消息")
    
    def preprocess_message_batch(
        self,
        conversation_id: int,
        message_ids: List[int]
    ) -> int:
        """
        批量预处理指定的消息（用于导入后自动预处理）
        
        Args:
            conversation_id: 会话ID
            message_ids: 消息ID列表
            
        Returns:
            成功处理的消息数量
        """
        if not message_ids:
            return 0
        
        # print(f"\n[预处理] 批量预处理 {len(message_ids)} 条消息 (conversation_id={conversation_id})")
        
        # 查询消息内容
        placeholders = ','.join('?' * len(message_ids))
        cursor = self.db.execute(f"""
            SELECT id, content
            FROM messages
            WHERE id IN ({placeholders})
                AND message_type = 1
        """, tuple(message_ids))
        
        messages = cursor.fetchall()
        messages_to_cache = []
        
        for row in messages:
            msg_id = row[0]
            content = row[1]
            
            # 清洗内容
            clean_result = self.clean_content(content)
            
            if clean_result["is_valid"]:
                stats = self.calculate_message_stats(clean_result["cleaned"])
                messages_to_cache.append({
                    "message_id": msg_id,
                    "conversation_id": conversation_id,
                    "cleaned_content": clean_result["cleaned"],
                    "char_count": stats["char_count"],
                    "word_count": stats["word_count"],
                    "is_valid": 1,
                    "has_xml": 1 if clean_result["has_xml"] else 0,
                    "has_media": 1 if clean_result["has_media"] else 0
                })
            else:
                messages_to_cache.append({
                    "message_id": msg_id,
                    "conversation_id": conversation_id,
                    "cleaned_content": "",
                    "char_count": 0,
                    "word_count": 0,
                    "is_valid": 0,
                    "has_xml": 1 if clean_result["has_xml"] else 0,
                    "has_media": 1 if clean_result["has_media"] else 0
                })
        
        # 批量写入缓存
        self._batch_cache_messages(messages_to_cache)
        
        return len(messages_to_cache)
    
    def get_cleaned_texts(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 10000
    ) -> List[str]:
        """
        获取清洗后的纯文本列表（用于词云等分析）
        
        Args:
            conversation_id: 会话ID
            from_ts: 开始时间戳（可选）
            to_ts: 结束时间戳（可选）
            limit: 最大消息数量
            
        Returns:
            ["清洗后的文本1", "清洗后的文本2", ...]
        """
        preprocessed = self.preprocess_conversation(
            conversation_id, from_ts, to_ts, limit
        )
        
        return [
            msg["cleaned_content"]
            for msg in preprocessed["cleaned_messages"]
            if msg["cleaned_content"]
        ]


# ============================================================
# 基础预处理服务 - 收集消息和时间统计
# ============================================================

class BasicPreprocessingService:
    """基础预处理服务 - 收集消息和时间统计"""

    def __init__(self):
        self.db = get_db()

    def collect_message_statistics(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        收集消息统计信息

        Args:
            conversation_id: 会话ID
            from_ts: 开始时间戳（可选）
            to_ts: 结束时间戳（可选）

        Returns:
            {
                "total_message_count": 1234,
                "total_positive_count": 800,
                "total_negative_count": 200,
                "total_neutral_count": 234
            }
        """
        # 构建查询条件
        sql = "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND message_type = 1"
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND timestamp <= ?"
            params.append(to_ts)

        # 总消息数
        cursor = self.db.execute(sql, tuple(params))
        total_message_count = cursor.fetchone()[0]

        # 从情感缓存获取统计
        sql = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN polarity = 1 THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN polarity = -1 THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN polarity = 0 THEN 1 ELSE 0 END) as neutral
            FROM sentiment_cache sc
            JOIN messages m ON sc.message_id = m.id
            WHERE m.conversation_id = ?
        """
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND m.timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND m.timestamp <= ?"
            params.append(to_ts)

        cursor = self.db.execute(sql, tuple(params))
        row = cursor.fetchone()

        return {
            "total_message_count": total_message_count,
            "total_positive_count": row[1] or 0,
            "total_negative_count": row[2] or 0,
            "total_neutral_count": row[3] or 0
        }

    def collect_time_statistics(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        收集时间统计信息

        Returns:
            {
                "conversation_start_timestamp": 1234567890,
                "conversation_end_timestamp": 1234567890,
                "conversation_duration_days": 123.5,
                "chat_days_count": 100
            }
        """
        # 构建查询
        sql = """
            SELECT
                MIN(timestamp) as start_ts,
                MAX(timestamp) as end_ts,
                COUNT(DISTINCT DATE(timestamp, 'unixepoch')) as chat_days
            FROM messages
            WHERE conversation_id = ? AND message_type = 1
        """
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND timestamp <= ?"
            params.append(to_ts)

        cursor = self.db.execute(sql, tuple(params))
        row = cursor.fetchone()

        start_ts = row[0]
        end_ts = row[1]
        chat_days = row[2]

        # 计算持续时间（天）
        duration_days = 0
        if start_ts and end_ts:
            duration_days = (end_ts - start_ts) / (24 * 3600)

        return {
            "conversation_start_timestamp": start_ts or 0,
            "conversation_end_timestamp": end_ts or 0,
            "conversation_duration_days": round(duration_days, 2),
            "chat_days_count": chat_days or 0
        }

    def collect_length_statistics(
        self,
        conversation_id: int,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        收集消息长度统计信息

        Returns:
            {
                "total_characters": 12345,
                "average_message_length": 12.5
            }
        """
        # 从预处理缓存获取统计
        sql = """
            SELECT
                SUM(char_count) as total_chars,
                AVG(char_count) as avg_chars,
                COUNT(*) as count
            FROM message_preprocessed mp
            JOIN messages m ON mp.message_id = m.id
            WHERE m.conversation_id = ? AND mp.is_valid = 1
        """
        params = [conversation_id]

        if from_ts is not None:
            sql += " AND m.timestamp >= ?"
            params.append(from_ts)

        if to_ts is not None:
            sql += " AND m.timestamp <= ?"
            params.append(to_ts)

        cursor = self.db.execute(sql, tuple(params))
        row = cursor.fetchone()

        total_chars = row[0] or 0
        avg_chars = row[1] or 0

        return {
            "total_characters": total_chars,
            "average_message_length": round(avg_chars, 2)
        }


# ============================================================
# 交互对预处理服务 - 构建发言单元和交互对
# ============================================================

class PairPreprocessingService:
    """交互对预处理服务 - 构建发言单元和交互对"""

    # 合并同一发送者连续消息的时间阈值（秒）
    MERGE_TIME_THRESHOLD = 300  # 5分钟

    def __init__(self):
        self.db = get_db()

    def _get_sentiment_for_unit(self, message_ids: List[int]) -> Dict[str, Any]:
        """
        获取发言单元的平均情感数据
        
        Args:
            message_ids: 消息ID列表
        
        Returns:
            {
                "polarity": 平均极性（-1, 0, 1），
                "intensity": 平均强度（-1.0 到 1.0）
            }
        """
        if not message_ids:
            return {"polarity": 0, "intensity": 0.0}
        
        try:
            # 将消息ID列表转换为逗号分隔的字符串
            if isinstance(message_ids, str):
                import json
                message_ids = json.loads(message_ids)
            
            # 查询这些消息的情感数据
            placeholders = ','.join('?' * len(message_ids))
            cursor = self.db.execute(f"""
                SELECT polarity, intensity
                FROM sentiment_cache
                WHERE message_id IN ({placeholders})
            """, message_ids)
            
            sentiments = cursor.fetchall()
            
            if not sentiments:
                return {"polarity": 0, "intensity": 0.0}
            
            # 计算平均值
            avg_polarity = sum(s[0] for s in sentiments) / len(sentiments)
            avg_intensity = sum(s[1] for s in sentiments) / len(sentiments)
            
            # 极性取四舍五入
            polarity = round(avg_polarity)
            # 确保极性在 -1, 0, 1 范围内
            polarity = max(-1, min(1, polarity))
            
            return {
                "polarity": polarity,
                "intensity": round(avg_intensity, 2)
            }
        
        except Exception as e:
            print(f"[交互对预处理] 获取情感数据失败: {e}")
            return {"polarity": 0, "intensity": 0.0}
    
    def build_speech_units(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        合并同一发送者的连续消息 (< 5分钟间隔) 为发言单元

        Args:
            messages: 消息列表,格式:
                [
                    {"id": 1, "content": "你好", "is_sender": 1, "timestamp": 1234567890},
                    ...
                ]

        Returns:
            发言单元列表:
            [
                {
                    "id": None,  # 稍后分配
                    "conversation_id": None,
                    "is_sender": 1,
                    "content": "你好 在吗",
                    "start_timestamp": 1234567890,
                    "end_timestamp": 1234567950,
                    "message_count": 2,
                    "message_ids": [1, 2]
                },
                ...
            ]
        """
        if not messages:
            return []

        # 按时间戳排序
        sorted_messages = sorted(messages, key=lambda m: m["timestamp"])

        speech_units = []
        current_unit = None

        for msg in sorted_messages:
            msg_id = msg["id"]
            is_sender = msg["is_sender"]
            timestamp = msg["timestamp"]
            content = msg.get("cleaned_content") or msg.get("content", "")
            # 确保 content 是字符串（数据库可能返回 bytes）
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")

            # 检查是否应该合并到当前单元
            should_merge = False

            if current_unit is not None:
                time_gap = timestamp - current_unit["end_timestamp"]
                same_sender = current_unit["is_sender"] == is_sender

                # 同一发送者且时间间隔 < 5分钟
                if same_sender and time_gap < self.MERGE_TIME_THRESHOLD:
                    should_merge = True

            if should_merge:
                # 合并到当前单元
                current_unit["content"] += " " + content
                current_unit["end_timestamp"] = timestamp
                current_unit["message_count"] += 1
                current_unit["message_ids"].append(msg_id)
            else:
                # 保存当前单元（如果存在）
                if current_unit is not None:
                    speech_units.append(current_unit)

                # 创建新单元
                current_unit = {
                    "id": None,  # 稍后分配
                    "conversation_id": None,
                    "is_sender": is_sender,
                    "content": content,
                    "start_timestamp": timestamp,
                    "end_timestamp": timestamp,
                    "message_count": 1,
                    "message_ids": [msg_id]
                }

        # 添加最后一个单元
        if current_unit is not None:
            speech_units.append(current_unit)

        # 分配ID
        for i, unit in enumerate(speech_units, 1):
            unit["id"] = i

        return speech_units

    def build_interaction_pairs(
        self,
        speech_units: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        创建发言单元间的双向交替配对

        Args:
            speech_units: 发言单元列表

        Returns:
            交互对列表:
            [
                {
                    "id": None,
                    "conversation_id": None,
                    "first_unit_id": 1,
                    "second_unit_id": 2,
                    "is_bidirectional": 1,
                    "direction": "sender_to_contact",
                    "pair_index": 1,
                    "is_same_parity": 1,
                    "time_gap_seconds": 60,
                    "time_gap_minutes": 1.0,
                    "semantic_similarity": 0.75  # 可选,稍后计算
                },
                ...
            ]
        """
        if len(speech_units) < 2:
            return []

        interaction_pairs = []

        for i in range(len(speech_units) - 1):
            first_unit = speech_units[i]
            second_unit = speech_units[i + 1]

            # 只构建不同发送者之间的交互对
            if first_unit["is_sender"] == second_unit["is_sender"]:
                continue

            # 计算时间间隔
            time_gap = second_unit["start_timestamp"] - first_unit["end_timestamp"]
            
            # 获取情感数据
            first_sentiment = self._get_sentiment_for_unit(first_unit["message_ids"])
            second_sentiment = self._get_sentiment_for_unit(second_unit["message_ids"])

            pair = {
                "id": None,  # 稍后分配
                "conversation_id": None,
                "first_unit_id": first_unit["id"],
                "second_unit_id": second_unit["id"],
                "time_gap_seconds": time_gap,
                "semantic_similarity": None,  # 稍后计算
                # 情感数据
                "from_polarity": first_sentiment["polarity"],
                "to_polarity": second_sentiment["polarity"],
                "from_intensity": first_sentiment["intensity"],
                "to_intensity": second_sentiment["intensity"],
                # 负面情绪发起标记
                "is_negative_initiation": 1 if first_sentiment["polarity"] == -1 else 0,
                # 共情响应标记（简化版：负面发起+积极响应）
                "is_empathetic_response": 1 if (first_sentiment["polarity"] == -1 and second_sentiment["polarity"] == 1) else 0
            }

            interaction_pairs.append(pair)

        return interaction_pairs

    def collect_pair_statistics(
        self,
        interaction_pairs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        收集交互对统计信息

        Returns:
            {
                "total_interaction_pairs": 123,
                "bidirectional_pairs": 123,  # 保留以兼容现有代码，值等于 total
                "same_parity_pairs": 0,      # 保留以兼容现有代码，固定为0
                "avg_time_gap_seconds": 180.5,
                "avg_time_gap_minutes": 3.0
            }
        """
        if not interaction_pairs:
            return {
                "total_interaction_pairs": 0,
                "bidirectional_pairs": 0,
                "same_parity_pairs": 0,
                "avg_time_gap_seconds": 0,
                "avg_time_gap_minutes": 0
            }

        total_pairs = len(interaction_pairs)
        avg_time_gap = sum(p["time_gap_seconds"] for p in interaction_pairs) / total_pairs

        return {
            "total_interaction_pairs": total_pairs,
            "bidirectional_pairs": total_pairs,  # 所有交互对都是双向的
            "same_parity_pairs": 0,  # 已废弃，保留字段以兼容
            "avg_time_gap_seconds": round(avg_time_gap, 2),
            "avg_time_gap_minutes": round(avg_time_gap / 60.0, 2)
        }

    def save_speech_units(
        self,
        conversation_id: int,
        speech_units: List[Dict[str, Any]]
    ) -> int:
        """写入发言单元到数据库"""
        try:
            import time
            for unit in speech_units:
                self.db.execute("""
                    INSERT OR REPLACE INTO speech_units
                    (conversation_id, sender, first_message_timestamp,
                     last_message_timestamp, message_count, message_ids, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    'user' if unit["is_sender"] == 1 else 'other',  # 转换为 sender
                    int(unit["start_timestamp"]),  # 映射到 first_message_timestamp
                    int(unit["end_timestamp"]),    # 映射到 last_message_timestamp
                    unit["message_count"],
                    json.dumps(unit["message_ids"]),
                    int(time.time())
                ))

            self.db.commit()
            print(f"[交互对预处理] 已保存 {len(speech_units)} 个发言单元")
            return len(speech_units)

        except Exception as e:
            print(f"[交互对预处理] 保存发言单元失败: {e}")
            return 0

    def save_interaction_pairs(
        self,
        conversation_id: int,
        interaction_pairs: List[Dict[str, Any]]
    ) -> int:
        """写入交互对到数据库"""
        try:
            import time
            for pair in interaction_pairs:
                self.db.execute("""
                    INSERT OR REPLACE INTO interaction_pairs
                    (conversation_id, from_speech_unit_id, to_speech_unit_id, 
                     time_gap, semantic_similarity, from_polarity, to_polarity,
                     from_intensity, to_intensity, is_negative_initiation, 
                     is_empathetic_response, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    pair["first_unit_id"],  # 映射到 from_speech_unit_id
                    pair["second_unit_id"], # 映射到 to_speech_unit_id
                    pair["time_gap_seconds"],  # 映射到 time_gap
                    pair.get("semantic_similarity"),
                    pair.get("from_polarity", 0),
                    pair.get("to_polarity", 0),
                    pair.get("from_intensity", 0.0),
                    pair.get("to_intensity", 0.0),
                    pair.get("is_negative_initiation", 0),
                    pair.get("is_empathetic_response", 0),
                    int(time.time())
                ))

            self.db.commit()
            print(f"[交互对预处理] 已保存 {len(interaction_pairs)} 个交互对")
            return len(interaction_pairs)

        except Exception as e:
            print(f"[交互对预处理] 保存交互对失败: {e}")
            return 0

    def load_cached_pairs(
        self,
        conversation_id: int
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        从缓存读取发言单元和交互对

        Returns:
            (speech_units, interaction_pairs)
        """
        try:
            # 读取发言单元（使用数据库实际的列名）
            cursor = self.db.execute("""
                SELECT id, sender, first_message_timestamp, last_message_timestamp,
                       message_count, message_ids
                FROM speech_units
                WHERE conversation_id = ?
                ORDER BY first_message_timestamp ASC
            """, (conversation_id,))

            speech_units = []
            for row in cursor.fetchall():
                speech_units.append({
                    "id": row[0],
                    "is_sender": 1 if row[1] == 'user' else 0,  # 转换 sender 为 is_sender
                    "start_timestamp": row[2],  # 从 first_message_timestamp 读取
                    "end_timestamp": row[3],    # 从 last_message_timestamp 读取
                    "message_count": row[4],
                    "message_ids": json.loads(row[5])
                    # 注意：不包含 content 字段，需要时从 messages 表查询
                })

            # 读取交互对
            cursor = self.db.execute("""
                SELECT id, from_speech_unit_id, to_speech_unit_id, time_gap,
                       semantic_similarity, from_polarity, to_polarity,
                       from_intensity, to_intensity
                FROM interaction_pairs
                WHERE conversation_id = ?
                ORDER BY id ASC
            """, (conversation_id,))

            interaction_pairs = []
            for row in cursor.fetchall():
                interaction_pairs.append({
                    "id": row[0],
                    "first_unit_id": row[1],  # 从 from_speech_unit_id 读取
                    "second_unit_id": row[2], # 从 to_speech_unit_id 读取
                    "time_gap_seconds": row[3],  # 从 time_gap 读取
                    "semantic_similarity": row[4],
                    "from_polarity": row[5],
                    "to_polarity": row[6],
                    "from_intensity": row[7],
                    "to_intensity": row[8]
                })

            print(f"[交互对预处理] 从缓存读取: {len(speech_units)} 个发言单元, {len(interaction_pairs)} 个交互对")
            return speech_units, interaction_pairs

        except Exception as e:
            print(f"[交互对预处理] 读取缓存失败: {e}")
            return [], []


# ============================================================
# 会话管理器 - 切分和管理会话
# ============================================================

class SessionManager:
    """会话管理器 - 通过时间间隔+睡眠时间+语义相似度切分会话"""

    # 滑动窗口大小（交互对数量）
    WINDOW_SIZE = 10

    # 相似度阈值（用于检测谷值）
    SIMILARITY_THRESHOLD = 0.3
    
    # 最小会话长度（发言单元数量）- 防止会话过于碎片化
    MIN_SESSION_UNITS = 3

    # 时间间隔阈值（30分钟 = 1800秒）
    TIME_GAP_THRESHOLD = 1800

    # 睡眠时间配置（小时）
    SLEEP_END_HOUR = 7  # 早上7点结束睡眠

    def __init__(self):
        self.db = get_db()
        self._sentiment_service = None  # 缓存 SentimentService 实例

    def calculate_semantic_similarity(
        self,
        text1: str,
        text2: str
    ) -> float:
        """
        计算两个文本的语义相似度（余弦相似度）

        Args:
            text1: 文本1
            text2: 文本2

        Returns:
            相似度 (0.0 到 1.0)
        """
        try:
            from .sentiment_service import SentimentService

            # 使用缓存的实例（避免重复加载模型）
            if self._sentiment_service is None:
                self._sentiment_service = SentimentService()

            # 获取向量
            emb1 = self._sentiment_service._get_embedding(text1)
            emb2 = self._sentiment_service._get_embedding(text2)

            # 计算余弦相似度
            import numpy as np
            vec1 = np.array(emb1)
            vec2 = np.array(emb2)

            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = dot_product / (norm1 * norm2)

            return float(similarity)

        except Exception as e:
            print(f"[会话管理器] 计算相似度失败: {e}")
            return 0.0

    def _check_crosses_sleep_time(
        self,
        start_ts: int,
        end_ts: int
    ) -> bool:
        """
        检查时间间隔是否跨越睡眠时间（00:00-07:00）

        Args:
            start_ts: 开始时间戳（秒）
            end_ts: 结束时间戳（秒）

        Returns:
            是否跨越睡眠时间
        """
        try:
            from datetime import datetime
            # 使用本地时区而不是UTC
            start_dt = datetime.fromtimestamp(start_ts)
            end_dt = datetime.fromtimestamp(end_ts)

            # 检查是否跨越午夜（日期不同）
            if start_dt.date() != end_dt.date():
                return True

            # 检查是否在睡眠时段内（00:00-07:00）
            hour = start_dt.hour
            if hour >= 0 and hour < self.SLEEP_END_HOUR:
                # 如果在00:00-07:00之间，检查是否跨越结束时间
                return end_dt.hour >= self.SLEEP_END_HOUR

            return False

        except Exception as e:
            print(f"[会话管理器] 检查睡眠时间失败: {e}")
            return False

    def split_sessions(
        self,
        speech_units: List[Dict[str, Any]],
        conversation_id: int = None  # 添加可选参数，保持向后兼容
    ) -> List[Dict[str, Any]]:
        """
        通过时间间隔+睡眠时间+语义相似度切分会话

        切分规则（按优先级排序）:
        1. 睡眠时间切分：跨越午夜或00:00-07:00时段
        2. 时间间隔切分：时间间隔 > 30分钟
        3. 语义相似度切分：相似度 < 0.5 且为局部谷值

        Args:
            speech_units: 发言单元列表

        Returns:
            会话列表:
            [
                {
                    "id": None,
                    "conversation_id": None,
                    "start_unit_id": 1,
                    "end_unit_id": 10,
                    "start_timestamp": 1234567890,
                    "end_timestamp": 1234567990,
                    "unit_count": 10,
                    "initiator_is_sender": 1
                },
                ...
            ]
        """
        if len(speech_units) < 1:
            return []

        # 如果只有1个发言单元，直接作为一个会话返回
        if len(speech_units) == 1:
            unit = speech_units[0]
            return [{
                "id": None,
                "conversation_id": None,
                "start_unit_id": 1,
                "end_unit_id": 1,
                "start_timestamp": unit["start_timestamp"],
                "end_timestamp": unit["end_timestamp"],
                "unit_count": 1,
                "initiator_is_sender": unit["is_sender"]
            }]

        # ================================================================
        # 第一步：强制执行时间间隔和睡眠时间切分（保底机制）
        # 这些切分点是必须的，不依赖于语义相似度计算
        # ================================================================
        mandatory_split_points = set()
        
        for i in range(len(speech_units) - 1):
            time_gap = speech_units[i + 1]["start_timestamp"] - speech_units[i]["end_timestamp"]
            
            # 优先级1: 睡眠时间切分 - 跨越午夜或00:00-07:00时段
            if self._check_crosses_sleep_time(
                speech_units[i]["end_timestamp"],
                speech_units[i + 1]["start_timestamp"]
            ):
                mandatory_split_points.add(i + 1)
                continue
            
            # 优先级2: 时间间隔切分 - 如果时间间隔 > 30分钟,强制切分
            if time_gap > self.TIME_GAP_THRESHOLD:
                mandatory_split_points.add(i + 1)
                continue
        
        print(f"[会话管理器] 强制切分点（时间/睡眠）: {len(mandatory_split_points)} 个")

        # ================================================================
        # 第二步：尝试计算语义相似度进行更细粒度的切分（可选增强）
        # ================================================================
        semantic_split_points = set()
        
        # 计算相邻发言单元的语义相似度（批量计算，性能优化）
        # 对于超大对话（>1000个单元），使用间隔采样+回溯策略
        LARGE_CONVERSATION_THRESHOLD = 1000
        SAMPLE_INTERVAL = 5  # 每5个单元采样一次
        
        use_sampling = len(speech_units) > LARGE_CONVERSATION_THRESHOLD
        
        if use_sampling:
            print(f"[会话管理器] 超大对话 ({len(speech_units)} 个单元)，启用间隔采样策略")
        else:
            print(f"[会话管理器] 开始计算 {len(speech_units)} 个发言单元的语义相似度...")

        try:
            from .sentiment_service import SentimentService

            # 使用缓存的实例（避免重复加载模型）
            if self._sentiment_service is None:
                self._sentiment_service = SentimentService()

            # 确保模型已加载
            if self._sentiment_service._embedding_model is None:
                self._sentiment_service._load_embedding_model()

            if use_sampling:
                # === 间隔采样策略 ===
                # 第一阶段：粗采样，找出候选切分区域
                sample_indices = list(range(0, len(speech_units), SAMPLE_INTERVAL))
                if sample_indices[-1] != len(speech_units) - 1:
                    sample_indices.append(len(speech_units) - 1)
                
                sample_texts = [speech_units[i]["content"] for i in sample_indices]
                print(f"[会话管理器] 第一阶段：粗采样 {len(sample_texts)} 个文本...")
                
                sample_embeddings = self._sentiment_service._embedding_model.encode(
                    sample_texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=64  # 采样时可用更大批次
                )
                
                # 找出候选切分区域（相似度较低的区域）
                import numpy as np
                candidate_regions = []
                for i in range(len(sample_indices) - 1):
                    vec1 = sample_embeddings[i]
                    vec2 = sample_embeddings[i + 1]
                    similarity = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
                    
                    if similarity < self.SIMILARITY_THRESHOLD + 0.2:  # 粗筛阈值稍高
                        # 记录需要精细检测的区域
                        start = sample_indices[i]
                        end = sample_indices[i + 1]
                        candidate_regions.append((start, end))
                
                print(f"[会话管理器] 发现 {len(candidate_regions)} 个候选切分区域")
                
                # 第二阶段：对候选区域进行精细检测
                # 初始化 similarities 数组（默认高相似度，不切分）
                similarities = [0.8] * (len(speech_units) - 1)
                
                for start, end in candidate_regions:
                    region_texts = [speech_units[i]["content"] for i in range(start, end + 1)]
                    region_embeddings = self._sentiment_service._embedding_model.encode(
                        region_texts,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                        batch_size=32
                    )
                    
                    for i in range(len(region_embeddings) - 1):
                        vec1 = region_embeddings[i]
                        vec2 = region_embeddings[i + 1]
                        similarity = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
                        similarities[start + i] = similarity
                
                print(f"[会话管理器] 精细检测完成")
                
            else:
                # === 常规全量计算 ===
                texts = [unit["content"] for unit in speech_units]
                embeddings = self._sentiment_service._embedding_model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    batch_size=32  # 批量处理
                )

                # 批量计算所有相邻相似度
                import numpy as np
                similarities = []
                for i in range(len(speech_units) - 1):
                    vec1 = embeddings[i]
                    vec2 = embeddings[i + 1]

                    # 计算余弦相似度
                    dot_product = np.dot(vec1, vec2)
                    norm1 = np.linalg.norm(vec1)
                    norm2 = np.linalg.norm(vec2)

                    if norm1 == 0 or norm2 == 0:
                        similarity = 0.0
                    else:
                        similarity = float(dot_product / (norm1 * norm2))

                    similarities.append(similarity)

            print(f"[会话管理器] 语义相似度计算完成 ({len(similarities)} 个相似度)")

        except Exception as e:
            print(f"[会话管理器] 批量计算语义相似度失败，回退到逐个计算: {e}")
            # 回退到逐个计算
            similarities = []
            for i in range(len(speech_units) - 1):
                sim = self.calculate_semantic_similarity(
                    speech_units[i]["content"],
                    speech_units[i + 1]["content"]
                )
                similarities.append(sim)

        # 使用滑动窗口检测谷值（相似度骤降点）- 仅用于语义切分
        # 时间间隔和睡眠时间切分已在上面的 mandatory_split_points 中处理

        for i in range(len(similarities)):
            # 跳过已经在强制切分点中的位置
            if (i + 1) in mandatory_split_points:
                continue

            # 优先级3: 语义相似度切分 - 检查是否为谷值（局部最小值）
            window_start = max(0, i - self.WINDOW_SIZE // 2)
            window_end = min(len(similarities), i + self.WINDOW_SIZE // 2 + 1)

            window = similarities[window_start:window_end]

            if len(window) < 3:
                continue

            # 检查是否为窗口内的最小值
            if similarities[i] == min(window):
                # 检查是否低于阈值
                if similarities[i] < self.SIMILARITY_THRESHOLD:
                    semantic_split_points.add(i + 1)  # 在这个位置切分

        print(f"[会话管理器] 语义切分点: {len(semantic_split_points)} 个")

        # 合并所有切分点
        all_split_points = sorted(mandatory_split_points | semantic_split_points)
        
        print(f"[会话管理器] 总切分点: {len(all_split_points)} 个")

        # 如果没有检测到切分点,整个对话作为一个会话
        if not all_split_points:
            return [{
                "id": None,
                "conversation_id": None,
                "start_unit_id": speech_units[0]["id"],
                "end_unit_id": speech_units[-1]["id"],
                "start_timestamp": speech_units[0]["start_timestamp"],
                "end_timestamp": speech_units[-1]["end_timestamp"],
                "unit_count": len(speech_units),
                "initiator_is_sender": speech_units[0]["is_sender"]
            }]

        # 构建会话
        sessions = []
        start_idx = 0

        for split_idx in all_split_points:
            end_idx = split_idx - 1

            session_units = speech_units[start_idx:end_idx + 1]

            sessions.append({
                "id": None,
                "conversation_id": None,
                "start_unit_id": session_units[0]["id"],
                "end_unit_id": session_units[-1]["id"],
                "start_timestamp": session_units[0]["start_timestamp"],
                "end_timestamp": session_units[-1]["end_timestamp"],
                "unit_count": len(session_units),
                "initiator_is_sender": session_units[0]["is_sender"]
            })

            start_idx = end_idx + 1

        # 添加最后一个会话
        last_session_units = speech_units[start_idx:]
        if last_session_units:
            sessions.append({
                "id": None,
                "conversation_id": None,
                "start_unit_id": last_session_units[0]["id"],
                "end_unit_id": last_session_units[-1]["id"],
                "start_timestamp": last_session_units[0]["start_timestamp"],
                "end_timestamp": last_session_units[-1]["end_timestamp"],
                "unit_count": len(last_session_units),
                "initiator_is_sender": last_session_units[0]["is_sender"]
            })

        # 合并过于碎片化的会话（小于 MIN_SESSION_UNITS 个单元的会话与相邻会话合并）
        # 重要：只有当两个会话之间的时间间隔小于阈值时才合并，防止跨越大间隙
        if len(sessions) > 1:
            merged_sessions = []
            i = 0
            while i < len(sessions):
                current = sessions[i]
                
                # 检查是否需要合并（会话太小）
                if current["unit_count"] < self.MIN_SESSION_UNITS:
                    # 尝试与下一个会话合并
                    if i + 1 < len(sessions):
                        next_session = sessions[i + 1]
                        
                        # 计算两个会话之间的时间间隔
                        time_gap = next_session["start_timestamp"] - current["end_timestamp"]
                        
                        # 只有时间间隔小于阈值时才合并，否则保留小会话
                        if time_gap <= self.TIME_GAP_THRESHOLD:
                            # 合并两个会话
                            merged = {
                                "id": None,
                                "conversation_id": None,
                                "start_unit_id": current["start_unit_id"],
                                "end_unit_id": next_session["end_unit_id"],
                                "start_timestamp": current["start_timestamp"],
                                "end_timestamp": next_session["end_timestamp"],
                                "unit_count": current["unit_count"] + next_session["unit_count"],
                                "initiator_is_sender": current["initiator_is_sender"]
                            }
                            merged_sessions.append(merged)
                            i += 2  # 跳过已合并的两个会话
                        else:
                            # 时间间隔太大，保留小会话
                            merged_sessions.append(current)
                            i += 1
                    elif merged_sessions:
                        # 如果没有下一个会话，检查能否与上一个合并
                        prev = merged_sessions[-1]
                        time_gap = current["start_timestamp"] - prev["end_timestamp"]
                        
                        if time_gap <= self.TIME_GAP_THRESHOLD:
                            prev["end_unit_id"] = current["end_unit_id"]
                            prev["end_timestamp"] = current["end_timestamp"]
                            prev["unit_count"] += current["unit_count"]
                        else:
                            # 时间间隔太大，保留小会话
                            merged_sessions.append(current)
                        i += 1
                    else:
                        # 只有一个小会话，保留
                        merged_sessions.append(current)
                        i += 1
                else:
                    merged_sessions.append(current)
                    i += 1
            
            sessions = merged_sessions
            print(f"[会话管理器] 合并碎片化会话后: {len(sessions)} 个会话")

        print(f"[会话管理器] 检测到 {len(sessions)} 个会话 (睡眠时间+时间间隔+语义相似度), 切分点: {all_split_points}")
        return sessions

    def collect_session_statistics(
        self,
        sessions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        收集会话统计信息

        Returns:
            {
                "total_sessions": 10,
                "average_session_length": 5.5,
                "average_session_gap": 3600.0
            }
        """
        if not sessions:
            return {
                "total_sessions": 0,
                "average_session_length": 0,
                "average_session_gap": 0
            }

        total_sessions = len(sessions)
        avg_length = sum(s["unit_count"] for s in sessions) / total_sessions

        # 计算会话间隔
        gaps = []
        for i in range(len(sessions) - 1):
            gap = sessions[i + 1]["start_timestamp"] - sessions[i]["end_timestamp"]
            gaps.append(gap)

        avg_gap = sum(gaps) / len(gaps) if gaps else 0

        return {
            "total_sessions": total_sessions,
            "average_session_length": round(avg_length, 2),
            "average_session_gap": round(avg_gap, 2)
        }

    def identify_session_initiators(
        self,
        sessions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        标记会话发起者

        Returns:
            {
                "sender_initiated_count": 6,
                "contact_initiated_count": 4,
                "sender_initiation_rate": 0.6
            }
        """
        if not sessions:
            return {
                "sender_initiated_count": 0,
                "contact_initiated_count": 0,
                "sender_initiation_rate": 0
            }

        sender_count = sum(1 for s in sessions if s["initiator_is_sender"] == 1)
        contact_count = len(sessions) - sender_count

        return {
            "sender_initiated_count": sender_count,
            "contact_initiated_count": contact_count,
            "sender_initiation_rate": round(sender_count / len(sessions), 2)
        }

    def save_sessions(
        self,
        conversation_id: int,
        sessions: List[Dict[str, Any]]
    ) -> int:
        """写入会话到数据库"""
        try:
            import time
            for session in sessions:
                self.db.execute("""
                    INSERT OR REPLACE INTO sessions
                    (conversation_id, start_time, end_time, message_count,
                     initiator, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    session["start_timestamp"],  # 映射到 start_time
                    session["end_timestamp"],    # 映射到 end_time
                    session["unit_count"],       # 映射到 message_count
                    'user' if session["initiator_is_sender"] == 1 else 'other',  # 转换为 initiator
                    'long',
                    int(time.time())
                ))

            self.db.commit()
            print(f"[会话管理器] 已保存 {len(sessions)} 个会话")
            return len(sessions)

        except Exception as e:
            print(f"[会话管理器] 保存会话失败: {e}")
            return 0

    def load_cached_sessions(
        self,
        conversation_id: int
    ) -> List[Dict[str, Any]]:
        """从缓存读取会话"""
        try:
            cursor = self.db.execute("""
                SELECT id, start_unit_id, end_unit_id, start_timestamp,
                       end_timestamp, unit_count, initiator_is_sender
                FROM sessions
                WHERE conversation_id = ?
                ORDER BY start_timestamp ASC
            """, (conversation_id,))

            sessions = []
            for row in cursor.fetchall():
                sessions.append({
                    "id": row[0],
                    "start_unit_id": row[1],
                    "end_unit_id": row[2],
                    "start_timestamp": row[3],
                    "end_timestamp": row[4],
                    "unit_count": row[5],
                    "initiator_is_sender": row[6]
                })

            print(f"[会话管理器] 从缓存读取 {len(sessions)} 个会话")
            return sessions

        except Exception as e:
            print(f"[会话管理器] 读取缓存失败: {e}")
            return []


# ============================================================
# 态度预处理服务 - 收集态度倾向统计
# ============================================================

from dataclasses import dataclass


@dataclass
class AttitudeStatistics:
    """态度统计数据结构"""
    emoji_message_count: int = 0          # 表情包消息数
    voice_message_count: int = 0          # 语音消息数
    video_message_count: int = 0          # 视频通话消息数
    nickname_message_count: int = 0       # 专属称呼消息数
    privacy_message_count: int = 0        # 隐私分享消息数
    holiday_message_count: int = 0        # 节日祝福消息数
    holidays_sent_count: int = 0          # 独立节日日期数(去重)


class AttitudePreprocessingService:
    """态度预处理服务 - 单次遍历统计 O(N)"""

    # 微信消息类型常量
    MESSAGE_TYPE_TEXT = 1
    MESSAGE_TYPE_IMAGE = 3
    MESSAGE_TYPE_VOICE = 34
    MESSAGE_TYPE_VIDEO = 43
    MESSAGE_TYPE_EMOJI = 47
    
    # 消息类型到统计字段的映射(优化:减少if-elif链)
    TYPE_TO_FIELD = {
        47: 'emoji_message_count',   # MESSAGE_TYPE_EMOJI
        34: 'voice_message_count',   # MESSAGE_TYPE_VOICE
        43: 'video_message_count',   # MESSAGE_TYPE_VIDEO
    }

    def __init__(self, keyword_lib=None):
        """
        初始化服务

        Args:
            keyword_lib: 关键词库实例(可选,默认创建新实例)
        """
        from .keyword_libraries import KeywordLibraries
        from .holiday_library import HolidayLibrary
        
        self.keyword_lib = keyword_lib or KeywordLibraries()
        self.holiday_lib = HolidayLibrary()
        self._keywords_cache = None

    def collect_attitude_statistics(self, messages):
        """
        单次遍历收集态度统计数据 (O(N))

        Args:
            messages: 消息列表,每条消息格式:
                {
                    'content': str,        # 消息内容
                    'message_type': int,   # 消息类型
                    'timestamp': int,      # 时间戳
                    'is_sender': int       # 0=对方,1=用户
                }

        Returns:
            AttitudeStatistics: 态度统计结果
        """
        # 验证输入
        if not messages:
            return AttitudeStatistics()
        
        # 延迟加载关键词(只在第一次调用时加载)
        if self._keywords_cache is None:
            self._keywords_cache = self.keyword_lib.get_all_keywords()

        stats = AttitudeStatistics()
        holidays_seen = set()  # 用于去重节日(格式: "节日名-年份")

        for i, msg in enumerate(messages):
            try:
                # 验证消息格式
                if not isinstance(msg, dict):
                    print(f"[警告] 消息 #{i} 格式无效,跳过")
                    continue
                
                content = msg.get('content', '')
                msg_type = msg.get('message_type', self.MESSAGE_TYPE_TEXT)
                timestamp = msg.get('timestamp', 0)

                # 优化1: 使用字典映射处理消息类型统计
                if msg_type in self.TYPE_TO_FIELD:
                    field = self.TYPE_TO_FIELD[msg_type]
                    setattr(stats, field, getattr(stats, field) + 1)

                # 只对文本消息进行关键词匹配
                if msg_type == self.MESSAGE_TYPE_TEXT and content:
                    # 优化2: 一次性检查所有关键词类别
                    keyword_matches = self._check_all_keywords(content)
                    
                    # 统计专属称呼
                    if keyword_matches.get('nickname'):
                        stats.nickname_message_count += 1

                    # 统计隐私分享
                    if keyword_matches.get('privacy'):
                        stats.privacy_message_count += 1

                    # 优化3: 改进节日祝福统计 - 基于节日名称+日期匹配
                    if keyword_matches.get('holiday'):
                        stats.holiday_message_count += 1
                        
                        # 提取节日名称并验证日期
                        holiday_name = self._extract_holiday_name(content)
                        if holiday_name and timestamp:
                            msg_date = self._extract_date_from_timestamp(timestamp)
                            if msg_date:
                                # 检查消息日期是否在节日当天(容错±1天)
                                if self.holiday_lib.is_holiday_date(msg_date, holiday_name, tolerance_days=1):
                                    # 使用"节日名-年份"作为唯一标识
                                    year = datetime.fromtimestamp(timestamp).year
                                    holiday_key = f"{holiday_name}-{year}"
                                    holidays_seen.add(holiday_key)
                                else:
                                    # 如果日期不匹配,仍然记录(可能是提前祝福)
                                    # 但使用消息日期作为标识
                                    holidays_seen.add(msg_date)
            
            except Exception as e:
                # 优化4: 添加异常处理,确保单条消息异常不影响整体统计
                print(f"[错误] 处理消息 #{i} 时出错: {e}")
                continue

        # 计算独立节日数
        stats.holidays_sent_count = len(holidays_seen)

        return stats

    def _check_all_keywords(self, text):
        """
        一次性检查文本中的所有关键词类别(优化:减少重复遍历)

        Args:
            text: 文本内容

        Returns:
            dict: {category: bool} 各类别是否匹配
        """
        results = {
            'nickname': False,
            'privacy': False,
            'holiday': False
        }
        
        if not text:
            return results
        
        # 使用优化后的正则预编译方法
        for category in results.keys():
            results[category] = self.keyword_lib.check_keywords_in_text_by_category(text, category)
        
        return results
    
    def _extract_holiday_name(self, text):
        """
        从文本中提取节日名称

        Args:
            text: 文本内容

        Returns:
            str: 节日名称,如果没有匹配则返回None
        """
        # 确保关键词缓存已初始化
        if self._keywords_cache is None:
            self._keywords_cache = self.keyword_lib.get_all_keywords()

        holiday_keywords = self._keywords_cache.get('holiday', [])
        return self.holiday_lib.extract_holiday_from_keywords(text, holiday_keywords)

    def _extract_date_from_timestamp(self, timestamp):
        """
        从时间戳提取日期字符串

        Args:
            timestamp: Unix时间戳

        Returns:
            str: 日期字符串 "YYYY-MM-DD"
        """
        if not timestamp:
            return ""

        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return ""
