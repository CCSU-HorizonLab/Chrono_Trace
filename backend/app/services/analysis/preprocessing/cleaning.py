"""消息清洗：内容去噪/表情XML去除/消息统计入口（PreprocessingService）。（拆分自原 preprocessing_service.py）"""
import re
import json
import logging
import string
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ....db.connection import get_db, write_transaction

logger = logging.getLogger(__name__)

# 清洗口径版本：变化时 message_preprocessed（可再生缓存）整表重建
CLEANING_VERSION = 2

# 微信方括号占位白名单——只删这些与文本表情。此前 \[.*?\] 吞掉一切
# 方括号内容（普通文本 "[1]"、"[链接说明]" 同删），词云/字数统计失真；
# 白名单外的方括号文本保留，漏判的表情留在文本里只是多一个词，无害。
_WECHAT_PLACEHOLDER_WORDS = (
    "图片 视频 语音 文件 动画表情 表情 链接 名片 位置 音乐 小程序"
    " 转账 红包 视频号 拍一拍 聊天记录 引用 收藏 系统消息 系统提示"
    " 游戏 分享 猜拳 骰子 链接标题 小程序分享 视频通话 语音通话"
).split()
_WECHAT_EMOJI_WORDS = (
    "微笑 呲牙 偷笑 发怒 大哭 色 得意 害羞 闭嘴 睡 尴尬 发呆 思考"
    " 惊讶 难过 抓狂 吐 愉快 白眼 傲慢 困 惊恐 憨笑 悠闲 咒骂 疑问"
    " 嘘 晕 敲打 再见 擦汗 抠鼻 鼓掌 坏笑 鄙视 委屈 快哭了 阴险 亲亲"
    " 可怜 笑脸 生病 脸红 破涕为笑 恐惧 失望 无语 嘿哈 捂脸 奸笑"
    " 机智 皱眉 耶 吃瓜 加油 汗 天啊 Emm emm 社会 旺柴 好的 打脸"
    " 哇 翻白眼 666 让我看看 叹气 苦涩 裂开 嘴唇 爱心 心碎 拥抱 强"
    " 弱 握手 胜利 抱拳 勾引 拳头 OK ok 合十 啤酒 咖啡 蛋糕 玫瑰"
    " 凋谢 菜刀 炸弹 便便 月亮 太阳 庆祝 发 福 猪头 跳出 跳绳 太极"
    " 拒绝 敬礼 流泪 翻滚 哈欠 骂 醒了 裂开 笑哭 笑眼 星星 闪电"
).split()


class PreprocessingService:
    """消息预处理服务"""

    def __init__(self):
        self._version_checked = False
        self._ensure_cleaning_cache_fresh()
        self._compile_patterns()

    def _ensure_cleaning_cache_fresh(self):
        """清洗口径与缓存版本不一致时整表重建缓存（可再生，不做迁移）。"""
        if self._version_checked:
            return
        self._version_checked = True
        try:
            db = get_db()
            row = db.execute(
                "SELECT value FROM settings WHERE key = 'cleaning_version'"
            ).fetchone()
            if row and str(row[0]) == str(CLEANING_VERSION):
                return
            db.execute("DELETE FROM message_preprocessed")
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) "
                "VALUES ('cleaning_version', ?, datetime('now'))",
                (str(CLEANING_VERSION),),
            )
            db.commit()
            logger.info("[预处理] 清洗口径 v%s，message_preprocessed 缓存已整表重建", CLEANING_VERSION)
        except Exception as exc:
            logger.warning("[预处理] 清洗版本校验失败(忽略): %s", exc)

    def _compile_patterns(self):
        """编译正则表达式模式（提升性能）"""
        # XML系统消息: <msg>...</msg>
        self.xml_pattern = re.compile(r'<msg>.*?</msg>', re.DOTALL | re.IGNORECASE)

        # 表情和媒体占位: [图片]、[表情]、[语音]等（白名单，长词在前防
        # 「动画表情」被「表情」抢先匹配）
        words = sorted(
            set(_WECHAT_PLACEHOLDER_WORDS) | set(_WECHAT_EMOJI_WORDS),
            key=len,
            reverse=True,
        )
        self.media_pattern = re.compile(rf'\[(?:{"|".join(words)})\]')

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
            import jieba  # noqa: F401
            words = list(jieba.cut(content))
            # 过滤空字符串和纯空格
            word_count = len([w for w in words if w.strip()])
        except ImportError:
            # 如果jieba未安装，使用简单的空格分割
            word_count = len(content.split())
        
        # 是否包含标点符号（集合成员测试：此前 115 字符字符串线性扫描，
        # 13 万条 × 平均字数的 O(115) 比较是纯浪费）
        cn_punctuation = '，。！？、；：""''（）【】《》…—·'
        all_punctuation = set(string.punctuation + cn_punctuation)
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
        logger.info(f"\n[预处理] 开始处理会话 {conversation_id} (use_cache={use_cache}, force={force_reprocess})")
        
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
        cursor = get_db().execute(sql, tuple(params))
        messages = cursor.fetchall()
        
        logger.debug(f"[预处理] 查询到 {len(messages)} 条文本消息")
        
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

        # 一次性批量预取缓存（此前循环内逐条点查，13 万条 = 13 万次语句往返）
        if use_cache and not force_reprocess:
            cached_map = self._batch_get_cached_messages([row[0] for row in messages])
        else:
            cached_map = {}

        # 逐条处理
        for row in messages:
            msg_id = row[0]
            content = row[1]
            is_sender = row[2]
            timestamp = row[3]

            # 尝试从缓存读取
            cached = cached_map.get(msg_id)
            
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
        
        logger.debug(f"[预处理] 有效消息: {valid_messages}/{total_messages}")
        logger.debug(f"[预处理] XML消息: {xml_count}, 媒体消息: {media_count}")
        logger.debug(f"[预处理] 平均字符数: {avg_char_count}, 平均词数: {avg_word_count}")
        logger.debug(f"[预处理] 缓存命中率: {cache_hit_rate * 100}% ({cache_hits}/{total_messages})")
        
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
    
    def _batch_get_cached_messages(self, message_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """批量读取预处理缓存（IN 分批 500），替代逐条点查。"""
        cached: Dict[int, Dict[str, Any]] = {}
        ids = list(message_ids)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ','.join('?' * len(chunk))
            cursor = get_db().execute(f"""
                SELECT message_id, cleaned_content, char_count, word_count,
                       is_valid, has_xml, has_media
                FROM message_preprocessed
                WHERE message_id IN ({placeholders})
            """, tuple(chunk))
            for row in cursor.fetchall():
                cached[int(row[0])] = {
                    "cleaned_content": row[1],
                    "char_count": row[2],
                    "word_count": row[3],
                    "is_valid": row[4],
                    "has_xml": row[5],
                    "has_media": row[6],
                }
        return cached

    def _batch_cache_messages(self, messages: List[Dict[str, Any]]):
        """批量写入缓存（executemany + 单事务；整批失败回退逐条）"""
        if not messages:
            return

        rows = [(
            msg["message_id"],
            msg["conversation_id"],
            msg["cleaned_content"],
            msg["char_count"],
            msg["word_count"],
            msg["is_valid"],
            msg["has_xml"],
            msg["has_media"],
            int(time.time()),
        ) for msg in messages]

        try:
            with write_transaction():
                get_db().executemany("""
                    INSERT OR REPLACE INTO message_preprocessed
                    (message_id, conversation_id, cleaned_content, char_count, word_count,
                     is_valid, has_xml, has_media, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)
            return
        except Exception as e:
            logger.error(f"[预处理] 批量缓存 {len(rows)} 条失败，回退逐条: {e}")

        for msg in messages:
            try:
                get_db().execute("""
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
                logger.error(f"[预处理] 缓存消息 {msg['message_id']} 失败: {e}")
    
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
        
        # logger.debug(f"\n[预处理] 批量预处理 {len(message_ids)} 条消息 (conversation_id={conversation_id})")
        
        # 查询消息内容
        placeholders = ','.join('?' * len(message_ids))
        cursor = get_db().execute(f"""
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
