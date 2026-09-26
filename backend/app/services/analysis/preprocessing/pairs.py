"""交互对构建：发言单元/你来我往配对/响应时长（PairPreprocessingService）。（拆分自原 preprocessing_service.py）"""
import re
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ....db.connection import get_db

logger = logging.getLogger(__name__)


class PairPreprocessingService:
    """交互对预处理服务 - 构建发言单元和交互对"""

    # 合并同一发送者连续消息的时间阈值（秒）
    MERGE_TIME_THRESHOLD = 300  # 5分钟

    def __init__(self):
        pass  # get_db() removed for thread safety

    def _calculate_unit_similarities(
        self,
        speech_units: List[Dict[str, Any]]
    ) -> Dict[int, float]:
        """批量计算相邻发言单元的语义相似度."""
        if len(speech_units) < 2:
            return {}

        try:
            from ..sentiment_service import SentimentService
            import numpy as np

            sentiment_service = SentimentService()
            sentiment_service._load_embedding_model()
            if sentiment_service._embedding_model is None:
                return {}

            texts = [(unit.get("content") or "").strip() for unit in speech_units]
            embeddings = sentiment_service._embedding_model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=32
            )

            similarities: Dict[int, float] = {}
            for idx in range(len(speech_units) - 1):
                similarity = float(np.dot(embeddings[idx], embeddings[idx + 1]))
                similarities[idx] = max(0.0, min(1.0, similarity))

            return similarities

        except Exception as e:
            logger.warning(f"[交互对预处理] 计算语义相似度失败，将保留为空值: {e}")
            return {}

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
            # 如果 message_ids 内部变成了 dict 列表，提取 ID
            if message_ids and isinstance(message_ids[0], dict):
                try:
                    message_ids = [m.get('id', m) for m in message_ids]
                except Exception:
                    pass
            # 查询这些消息的情感数据
            placeholders = ','.join('?' * len(message_ids))
            cursor = get_db().execute(f"""
                SELECT polarity, intensity
                FROM sentiment_cache
                WHERE message_id IN ({placeholders})
            """, message_ids)
            
            sentiments = cursor.fetchall()
            
            if not sentiments:
                return {"polarity": 0, "intensity": 0.0}
            
            # 过滤掉为 None 的情况
            valid_polarities = [s[0] for s in sentiments if s[0] is not None]
            valid_intensities = [s[1] for s in sentiments if s[1] is not None]
            
            if not valid_polarities or not valid_intensities:
                return {"polarity": 0, "intensity": 0.0}
            
            # 计算平均值
            avg_polarity = sum(valid_polarities) / len(valid_polarities)
            avg_intensity = sum(valid_intensities) / len(valid_intensities)
            
            # 极性取四舍五入
            polarity = round(avg_polarity)
            # 确保极性在 -1, 0, 1 范围内
            polarity = max(-1, min(1, polarity))
            
            return {
                "polarity": polarity,
                "intensity": round(avg_intensity, 2)
            }
        
        except Exception as e:
            logger.error(f"[交互对预处理] 获取情感数据失败: {e}")
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
        adjacent_similarities = self._calculate_unit_similarities(speech_units)

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
                "semantic_similarity": adjacent_similarities.get(i),
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
                get_db().execute("""
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

            get_db().commit()
            logger.debug(f"[交互对预处理] 已保存 {len(speech_units)} 个发言单元")
            return len(speech_units)

        except Exception as e:
            logger.error(f"[交互对预处理] 保存发言单元失败: {e}")
            return 0

    def clear_cached_pairs(self, conversation_id: int):
        """清理某个会话已有的发言单元和交互对。"""
        db = get_db()
        db.execute(
            "DELETE FROM interaction_pairs WHERE conversation_id = ?",
            (conversation_id,)
        )
        db.execute(
            "DELETE FROM speech_units WHERE conversation_id = ?",
            (conversation_id,)
        )
        db.commit()

    def save_speech_units_with_mapping(
        self,
        conversation_id: int,
        speech_units: List[Dict[str, Any]]
    ) -> Dict[int, int]:
        """写入发言单元，并返回内存单元 ID 到数据库 ID 的映射。"""
        try:
            import time

            db = get_db()
            unit_id_map: Dict[int, int] = {}
            created_at = int(time.time())

            for unit in speech_units:
                cursor = db.execute("""
                    INSERT INTO speech_units
                    (conversation_id, sender, first_message_timestamp,
                     last_message_timestamp, message_count, message_ids, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    'user' if unit["is_sender"] == 1 else 'other',
                    int(unit["start_timestamp"]),
                    int(unit["end_timestamp"]),
                    unit["message_count"],
                    json.dumps(unit["message_ids"]),
                    created_at
                ))
                unit_id_map[unit["id"]] = cursor.lastrowid

            db.commit()
            logger.debug(f"[交互对预处理] 已保存 {len(speech_units)} 个发言单元并建立 ID 映射")
            return unit_id_map

        except Exception as e:
            logger.error(f"[交互对预处理] 保存发言单元并映射 ID 失败: {e}")
            return {}

    def save_interaction_pairs(
        self,
        conversation_id: int,
        interaction_pairs: List[Dict[str, Any]]
    ) -> int:
        """写入交互对到数据库"""
        try:
            import time
            for pair in interaction_pairs:
                get_db().execute("""
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

            get_db().commit()
            logger.debug(f"[交互对预处理] 已保存 {len(interaction_pairs)} 个交互对")
            return len(interaction_pairs)

        except Exception as e:
            logger.error(f"[交互对预处理] 保存交互对失败: {e}")
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
            cursor = get_db().execute("""
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
            cursor = get_db().execute("""
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

            logger.debug(f"[交互对预处理] 从缓存读取: {len(speech_units)} 个发言单元, {len(interaction_pairs)} 个交互对")
            return speech_units, interaction_pairs

        except Exception as e:
            logger.error(f"[交互对预处理] 读取缓存失败: {e}")
            return [], []


# ============================================================
# 会话管理器 - 切分和管理会话
# ============================================================
