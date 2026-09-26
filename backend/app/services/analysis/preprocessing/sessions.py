"""会话切分与管理：睡眠/时间间隔/语义相似度三段式（SessionManager）。（拆分自原 preprocessing_service.py）"""
import re
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ....db.connection import get_db

logger = logging.getLogger(__name__)


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
        self._cancel_event = None  # 可选取消信号（分析停止时置位，嵌入分块间检查）
        pass  # get_db() removed for thread safety
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
        self._raise_if_cancelled()
        try:
            from ..sentiment_service import SentimentService

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
            logger.error(f"[会话管理器] 计算相似度失败: {e}")
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
            logger.error(f"[会话管理器] 检查睡眠时间失败: {e}")
            return False

    def _raise_if_cancelled(self) -> None:
        """停止分析时中断预处理（相似度嵌入的分块/分区间检查点）。"""
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise Exception("分析已被用户取消")

    def split_sessions(
        self,
        speech_units: List[Dict[str, Any]],
        conversation_id: int = None,  # 添加可选参数，保持向后兼容
        progress_cb=None,  # Optional[Callable[[float], None]]：相似度嵌入进度 0~1
        cancel_event=None,  # Optional[threading.Event]：停止分析时置位，嵌入分块间生效
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
        # 取消信号接线（好感度路径经 orchestrator 传入；特征提取路径经属性注入）
        if cancel_event is not None:
            self._cancel_event = cancel_event

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
        
        logger.debug(f"[会话管理器] 强制切分点（时间/睡眠）: {len(mandatory_split_points)} 个")

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
            logger.debug(f"[会话管理器] 超大对话 ({len(speech_units)} 个单元)，启用间隔采样策略")
        else:
            logger.info(f"[会话管理器] 开始计算 {len(speech_units)} 个发言单元的语义相似度...")

        try:
            from ..sentiment_service import SentimentService

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

                self._raise_if_cancelled()
                sample_texts = [speech_units[i]["content"] for i in sample_indices]
                logger.debug(f"[会话管理器] 第一阶段：粗采样 {len(sample_texts)} 个文本...")

                # 分块编码采样文本：单次全量 encode 不可中断也无进度（82k 消息
                # 首跑实测采样集 ~1.6 万条，整段无回调致 UI 长时间冻结）
                sample_embeddings: List[Any] = []
                SAMPLE_CHUNK = 256
                for cs in range(0, len(sample_texts), SAMPLE_CHUNK):
                    self._raise_if_cancelled()
                    chunk = sample_texts[cs:cs + SAMPLE_CHUNK]
                    sample_embeddings.extend(self._sentiment_service._get_embeddings_batch(
                        chunk,
                        batch_size=64,  # 采样分块可用更大批次
                    ))
                    if progress_cb:
                        try:
                            # 采样阶段占整体 0→0.6
                            progress_cb(min(0.6, 0.6 * (cs + len(chunk)) / max(1, len(sample_texts))))
                        except Exception:
                            pass
                
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
                
                logger.debug(f"[会话管理器] 发现 {len(candidate_regions)} 个候选切分区域")
                
                # 第二阶段：对候选区域进行精细检测
                # 初始化 similarities 数组（默认高相似度，不切分）
                similarities = [0.8] * (len(speech_units) - 1)
                total_regions = len(candidate_regions)

                for region_idx, (start, end) in enumerate(candidate_regions):
                    self._raise_if_cancelled()
                    if progress_cb:
                        try:
                            # 精细检测占整体 0.6→1.0
                            progress_cb(min(1.0, 0.6 + 0.4 * (region_idx + 1) / max(1, total_regions)))
                        except Exception:
                            pass
                    region_texts = [speech_units[i]["content"] for i in range(start, end + 1)]
                    region_embeddings = self._sentiment_service._get_embeddings_batch(
                        region_texts,
                        batch_size=32,
                    )
                    
                    for i in range(len(region_embeddings) - 1):
                        vec1 = region_embeddings[i]
                        vec2 = region_embeddings[i + 1]
                        similarity = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
                        similarities[start + i] = similarity
                
                logger.info("[会话管理器] 精细检测完成")
                
            else:
                # === 常规全量计算 ===
                texts = [unit["content"] for unit in speech_units]
                # 分块编码：每块之间检查取消信号——单次全量 encode 不可中断
                # （实测 1400+ 条约 3 分钟），取消要等整块跑完才能生效
                # 走缓存版批量编码：特征提取与好感度两阶段的同文本
                # 发言单元直接命中缓存（此前直调模型导致双倍全量编码）
                embed_service = self._sentiment_service
                all_embeddings: List[Any] = []
                CHUNK = 128
                for chunk_start in range(0, len(texts), CHUNK):
                    self._raise_if_cancelled()
                    chunk = texts[chunk_start:chunk_start + CHUNK]
                    all_embeddings.extend(embed_service._get_embeddings_batch(chunk))
                    if progress_cb:
                        try:
                            progress_cb(min(1.0, (chunk_start + len(chunk)) / max(1, len(texts))))
                        except Exception:
                            pass
                embeddings = all_embeddings

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

            logger.info(f"[会话管理器] 语义相似度计算完成 ({len(similarities)} 个相似度)")

        except Exception as e:
            # 取消信号必须穿透：不能回退到逐对计算（那会继续全量编码且无检查点）
            if self._cancel_event is not None and self._cancel_event.is_set():
                raise
            logger.error(f"[会话管理器] 批量计算语义相似度失败，回退到逐个计算: {e}")
            # 回退到逐个计算
            similarities = []
            for i in range(len(speech_units) - 1):
                self._raise_if_cancelled()
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

        logger.debug(f"[会话管理器] 语义切分点: {len(semantic_split_points)} 个")

        # 合并所有切分点
        all_split_points = sorted(mandatory_split_points | semantic_split_points)
        
        logger.debug(f"[会话管理器] 总切分点: {len(all_split_points)} 个")

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
            logger.debug(f"[会话管理器] 合并碎片化会话后: {len(sessions)} 个会话")

        logger.debug(f"[会话管理器] 检测到 {len(sessions)} 个会话 (睡眠时间+时间间隔+语义相似度), 切分点: {all_split_points}")
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
            # 重跑预处理时先清掉本会话的历史来源会话行（A2）：表无唯一约束，
            # 否则每次好感度分析都会追加一整代重复行，污染基于 sessions 的统计。
            # 仅清 source='long'，不触碰可能存在的实时来源行。
            get_db().execute(
                "DELETE FROM sessions WHERE conversation_id = ? AND source = 'long'",
                (conversation_id,),
            )
            for session in sessions:
                get_db().execute("""
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

            get_db().commit()
            logger.debug(f"[会话管理器] 已保存 {len(sessions)} 个会话")
            return len(sessions)

        except Exception as e:
            logger.error(f"[会话管理器] 保存会话失败: {e}")
            return 0

    def load_cached_sessions(
        self,
        conversation_id: int
    ) -> List[Dict[str, Any]]:
        """从缓存读取会话"""
        try:
            cursor = get_db().execute("""
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

            logger.debug(f"[会话管理器] 从缓存读取 {len(sessions)} 个会话")
            return sessions

        except Exception as e:
            logger.error(f"[会话管理器] 读取缓存失败: {e}")
            return []
