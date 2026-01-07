"""数据预处理服务 - 消息清洗与基础统计"""
import re
from typing import Dict, Any, List, Optional
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
