"""Preprocessing orchestrator for historical analysis."""

import json
import logging
import time
import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ...db.connection import get_db
from .feature_extraction_config import FeatureExtractionConfig
from .keyword_libraries import KeywordLibraries
from .preprocessing_service import (
    AttitudePreprocessingService,
    BasicPreprocessingService,
    PairPreprocessingService,
    SessionManager,
)
from .sentiment_service import SentimentService


logger = logging.getLogger(__name__)


def _step_elapsed(start_time: float) -> str:
    return f"{time.time() - start_time:.1f}s"


@dataclass
class PreprocessedStatistics:
    total_message_count: int = 0
    total_positive_count: int = 0
    total_negative_count: int = 0
    total_neutral_count: int = 0
    conversation_start_timestamp: int = 0
    conversation_end_timestamp: int = 0
    conversation_duration_days: float = 0.0
    chat_days_count: int = 0
    total_characters: int = 0
    average_message_length: float = 0.0
    total_interaction_pairs: int = 0
    bidirectional_pairs: int = 0
    same_parity_pairs: int = 0
    total_sessions: int = 0
    average_session_length: float = 0.0
    average_session_gap: float = 0.0
    sender_initiated_count: int = 0
    contact_initiated_count: int = 0
    emoji_message_count: int = 0
    voice_message_count: int = 0
    video_message_count: int = 0
    nickname_message_count: int = 0
    privacy_message_count: int = 0
    holiday_message_count: int = 0
    holidays_sent_count: int = 0
    conversation_id: int = 0
    preprocessing_timestamp: int = 0
    preprocessing_duration_ms: int = 0


class PreprocessingOrchestrator:
    """Coordinate preprocessing services and persist aggregated statistics."""

    def __init__(self):
        self.sentiment_service = SentimentService()
        self.basic_service = BasicPreprocessingService()
        self.pair_service = PairPreprocessingService()
        self.session_manager = SessionManager()
        self.keyword_lib = KeywordLibraries()
        self.attitude_service = AttitudePreprocessingService(keyword_lib=self.keyword_lib)

    def _cache_key(self, conversation_id: int) -> str:
        return f"preprocessing_stats_{conversation_id}"

    def _sync_analysis_device_mode(self) -> None:
        self.sentiment_service.configure_device_mode(
            FeatureExtractionConfig.from_settings().analysis_device_mode
        )

    def orchestrate_preprocessing(
        self,
        conversation_id: int,
        force_reprocess: bool = False,
        cancel_event: Optional[threading.Event] = None
    ) -> PreprocessedStatistics:
        start_time = time.time()
        self._sync_analysis_device_mode()
        logger.info(f"[预处理] 开始处理会话 {conversation_id} (force={force_reprocess})")

        if not force_reprocess:
            cached = self._load_cached_statistics(conversation_id)
            if cached:
                logger.info(f"[预处理] 命中缓存，会话 {conversation_id}")
                return cached

        stats = self._collect_all_statistics(conversation_id, cancel_event)
        stats.preprocessing_duration_ms = int((time.time() - start_time) * 1000)
        self._save_preprocessing_results(conversation_id, stats)
        logger.info(
            f"[预处理] 全部完成，会话 {conversation_id}，耗时 {stats.preprocessing_duration_ms}ms"
        )
        return stats

    def _collect_all_statistics(self, conversation_id: int, cancel_event: Optional[threading.Event] = None) -> PreprocessedStatistics:
        stats = PreprocessedStatistics(
            conversation_id=conversation_id,
            preprocessing_timestamp=int(time.time()),
        )

        step_start = time.time()
        messages = self._load_messages(conversation_id)
        logger.info(f"[预处理] 加载消息完成: {len(messages)} 条 ({_step_elapsed(step_start)})")
        if not messages:
            return stats

        step_start = time.time()
        self._ensure_sentiment_analysis(conversation_id, messages, cancel_event)
        logger.info(f"[预处理] 情感分析完成 ({_step_elapsed(step_start)})")

        basic_stats = self.basic_service.collect_message_statistics(conversation_id)
        stats.total_message_count = basic_stats.get("total_message_count", 0)
        stats.total_positive_count = basic_stats.get("total_positive_count", 0)
        stats.total_negative_count = basic_stats.get("total_negative_count", 0)
        stats.total_neutral_count = basic_stats.get("total_neutral_count", 0)

        time_stats = self.basic_service.collect_time_statistics(conversation_id)
        stats.conversation_start_timestamp = time_stats.get("conversation_start_timestamp", 0)
        stats.conversation_end_timestamp = time_stats.get("conversation_end_timestamp", 0)
        stats.conversation_duration_days = time_stats.get("conversation_duration_days", 0.0)
        stats.chat_days_count = time_stats.get("chat_days_count", 0)

        length_stats = self.basic_service.collect_length_statistics(conversation_id)
        stats.total_characters = length_stats.get("total_characters", 0)
        stats.average_message_length = length_stats.get("average_message_length", 0.0)

        speech_units = self.pair_service.build_speech_units(messages)
        interaction_pairs = self.pair_service.build_interaction_pairs(speech_units)
        self.pair_service.clear_cached_pairs(conversation_id)
        unit_id_map = self.pair_service.save_speech_units_with_mapping(conversation_id, speech_units)
        for pair in interaction_pairs:
            pair["first_unit_id"] = unit_id_map[pair["first_unit_id"]]
            pair["second_unit_id"] = unit_id_map[pair["second_unit_id"]]
        self.pair_service.save_interaction_pairs(conversation_id, interaction_pairs)

        pair_stats = self.pair_service.collect_pair_statistics(interaction_pairs)
        stats.total_interaction_pairs = pair_stats.get("total_interaction_pairs", 0)
        stats.bidirectional_pairs = pair_stats.get("bidirectional_pairs", 0)
        stats.same_parity_pairs = pair_stats.get("same_parity_pairs", 0)

        sessions = self.session_manager.split_sessions(speech_units)
        self.session_manager.save_sessions(conversation_id, sessions)
        session_stats = self.session_manager.collect_session_statistics(sessions)
        initiator_stats = self.session_manager.identify_session_initiators(sessions)
        stats.total_sessions = session_stats.get("total_sessions", 0)
        stats.average_session_length = session_stats.get("average_session_length", 0.0)
        stats.average_session_gap = session_stats.get("average_session_gap", 0.0)
        stats.sender_initiated_count = initiator_stats.get("sender_initiated_count", 0)
        stats.contact_initiated_count = initiator_stats.get("contact_initiated_count", 0)

        attitude_stats = self.attitude_service.collect_attitude_statistics(messages)
        stats.emoji_message_count = getattr(attitude_stats, "emoji_message_count", 0)
        stats.voice_message_count = getattr(attitude_stats, "voice_message_count", 0)
        stats.video_message_count = getattr(attitude_stats, "video_message_count", 0)
        stats.nickname_message_count = getattr(attitude_stats, "nickname_message_count", 0)
        stats.privacy_message_count = getattr(attitude_stats, "privacy_message_count", 0)
        stats.holiday_message_count = getattr(attitude_stats, "holiday_message_count", 0)
        stats.holidays_sent_count = getattr(attitude_stats, "holidays_sent_count", 0)

        return stats

    def _load_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        cursor = get_db().execute(
            """
            SELECT id, content, is_sender, timestamp, message_type
            FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _ensure_sentiment_analysis(
        self,
        conversation_id: int,
        messages: List[Dict[str, Any]],
        cancel_event: Optional[threading.Event] = None
    ):
        text_messages = [msg for msg in messages if msg["message_type"] == 1]
        all_ids = [msg["id"] for msg in text_messages]
        cached_results = self.sentiment_service.batch_get_sentiment_from_cache(all_ids)
        messages_to_analyze = [msg for msg in text_messages if msg["id"] not in cached_results]

        if not messages_to_analyze:
            logger.info("[预处理] 情感分析缓存命中，无需重新计算")
            return

        logger.info(
            f"[预处理] 需要分析 {len(messages_to_analyze)} 条消息 (缓存命中 {len(cached_results)}/{len(all_ids)})"
        )

        total_to_analyze = len(messages_to_analyze)
        batch_size = 500
        total_batches = (total_to_analyze + batch_size - 1) // batch_size
        sentiment_start = time.time()

        for start in range(0, total_to_analyze, batch_size):
            if cancel_event and cancel_event.is_set():
                logger.info(f"[预处理] 情感分析被用户取消 (已处理 {start}/{total_to_analyze})")
                raise Exception("分析已被用户取消")
                
            batch_index = start // batch_size + 1
            batch_msgs = messages_to_analyze[start:start + batch_size]
            texts = [msg["content"] or "" for msg in batch_msgs]
            batch_results = self.sentiment_service.analyze_batch(texts)

            cache_data = []
            for msg, result in zip(batch_msgs, batch_results):
                cache_data.append({
                    "message_id": msg["id"],
                    "polarity": result["polarity"],
                    "intensity": result["intensity"],
                    "embedding": result["embedding"],
                })

            self.sentiment_service.batch_cache_sentiments(cache_data)

            try:
                import gc
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            time.sleep(0.1)
            processed = min(start + batch_size, total_to_analyze)
            percentage = (processed / total_to_analyze) * 100 if total_to_analyze else 100
            logger.info(
                f"[预处理] 情感分析批次 {batch_index}/{total_batches}: "
                f"{processed}/{total_to_analyze} ({percentage:.1f}%), "
                f"累计耗时 {_step_elapsed(sentiment_start)}"
            )

    def _save_preprocessing_results(
        self,
        conversation_id: int,
        stats: PreprocessedStatistics,
    ):
        payload = json.dumps(asdict(stats), ensure_ascii=False)
        get_db().execute(
            """
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (self._cache_key(conversation_id), payload, int(time.time())),
        )
        get_db().commit()

    def _load_cached_statistics(self, conversation_id: int) -> Optional[PreprocessedStatistics]:
        cursor = get_db().execute(
            """
            SELECT value
            FROM settings
            WHERE key = ?
            """,
            (self._cache_key(conversation_id),),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None

        try:
            return PreprocessedStatistics(**json.loads(row[0]))
        except Exception as exc:
            logger.warning(f"[预处理] 缓存解析失败，将忽略旧缓存: {exc}")
            return None

    def invalidate_cache(self, conversation_id: int):
        get_db().execute(
            "DELETE FROM settings WHERE key = ?",
            (self._cache_key(conversation_id),),
        )
        get_db().commit()

    def get_preprocessed_statistics(
        self,
        conversation_id: int,
        force_reprocess: bool = False,
    ) -> PreprocessedStatistics:
        return self.orchestrate_preprocessing(conversation_id, force_reprocess)
