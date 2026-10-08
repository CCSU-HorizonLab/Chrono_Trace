"""回溯落库与消息迁移。

自 monitor_service.py 拆出（步骤 4C）。仅数据库操作：
断点回溯存储、缓冲区消息迁移、去重。
"""
from __future__ import annotations

import logging
import time

from .providers.models import build_message_hash
from .safe_print import safe_print as _print

logger = logging.getLogger(__name__)


class BackfillStoreMixin:
    """回溯相关数据库操作。"""

    def _map_message_type(self, message_type: str) -> int:
        """Map normalized listener message types to the app's integer message types."""
        type_map = {
            'text': 1,
            'image': 3,
            'voice': 34,
            'video': 43,
            'emoji': 47,
            'file': 49,
            'link': 1,
            'system': 1,
        }
        return type_map.get(str(message_type or 'text').lower(), 1)

    def _get_or_create_conversation_id(self, talker_username: str, talker_display_name: str) -> int:
        """Return the conversation id for a talker, creating it when missing."""
        from ...db.connection import get_db

        conn = get_db()
        talker_key = self._get_talker_key(talker_username, talker_display_name)
        account_wxid = self._resolve_account_wxid()
        row = conn.execute(
            'SELECT id FROM conversations WHERE account_wxid = ? AND username = ? AND platform = ?',
            (account_wxid, talker_key, 'wechat')
        ).fetchone()
        if row:
            return row[0]

        now_ts = int(time.time())
        cursor = conn.execute(
            '''
            INSERT INTO conversations (account_wxid, username, display_name, platform, created_at, updated_at, message_count)
            VALUES (?, ?, ?, 'wechat', ?, ?, 0)
            ''',
            (account_wxid, talker_key, talker_display_name or talker_key, now_ts, now_ts)
        )
        conn.commit()
        return cursor.lastrowid

    def _message_exists_in_history(
        self,
        conversation_id: int,
        message_data: dict,
        occurrence_index: int = 1,
    ) -> bool:
        """Check whether a buffered realtime message has already been migrated.

        occurrence_index 为该消息在缓冲区同签名（发送方+类型+时间戳+内容）消息中的
        序号（从 1 开始）：历史表中同签名消息数达到该序号才判为已存在。
        """
        from ...db.connection import get_db

        conn = get_db()
        # 注意：不按 runtime_id 查 local_id —— 实时 runtime_id 与微信库 local_id 属于
        # 两个无关 ID 空间，数值撞车会把真实新消息误判为已存在而静默丢弃（W1）。
        # UIA 时间标签只有分钟精度、实时侧时间戳按分钟截断，同分钟消息落库后时间戳
        # 可能有秒级偏差，精确等值判重会把同分钟连发的相同内容消息静默丢掉；这里放宽
        # 为 ±59 秒窗口并按签名计数，仅当历史同签名数 >= 缓冲内序号时才判已存在（R4）。
        try:
            occurrence_index = max(1, int(occurrence_index))
        except (TypeError, ValueError):
            occurrence_index = 1
        timestamp = int(message_data.get('timestamp') or 0)
        count = conn.execute(
            '''
            SELECT COUNT(*)
            FROM messages
            WHERE conversation_id = ?
              AND is_sender = ?
              AND message_type = ?
              AND timestamp BETWEEN ? - 59 AND ? + 59
              AND COALESCE(content, '') = ?
            ''',
            (
                conversation_id,
                1 if message_data.get('sender_attr') == 'self' else 0,
                self._map_message_type(message_data.get('message_type')),
                timestamp,
                timestamp,
                message_data.get('content') or '',
            )
        ).fetchone()[0]
        return int(count or 0) >= occurrence_index

    def _store_backfill_messages(
        self,
        talker_username: str,
        talker_display_name: str,
        messages: list[dict],
    ) -> dict:
        """Persist recovered history directly into messages with a backfill source tag."""
        from ...db.connection import get_db

        talker_key = self._get_talker_key(talker_username, talker_display_name)
        if not talker_key or not messages:
            return {
                'inserted_count': 0,
                'existing_count': 0,
            }

        conn = get_db()
        conversation_id = self._get_or_create_conversation_id(talker_key, talker_display_name or talker_key)
        inserted = 0
        existing = 0
        latest_ts = 0
        inserted_samples: list[str] = []
        existing_samples: list[str] = []

        # 遍历时累计同签名（发送方+类型+时间戳+内容）出现次数作为判重序号，
        # 配合 ±59 秒窗口计数判重，避免同分钟连发的相同内容消息被静默丢掉（R4）
        occurrence_counts: dict[tuple, int] = {}
        for message_data in messages:
            latest_ts = max(latest_ts, int(message_data.get('timestamp') or 0))
            signature = (
                1 if message_data.get('sender_attr') == 'self' else 0,
                self._map_message_type(message_data.get('message_type')),
                int(message_data.get('timestamp') or 0),
                message_data.get('content') or '',
            )
            occurrence_counts[signature] = occurrence_counts.get(signature, 0) + 1
            if self._message_exists_in_history(
                conversation_id,
                message_data,
                occurrence_index=occurrence_counts[signature],
            ):
                existing += 1
                if len(existing_samples) < 12:
                    existing_samples.append(
                        f"{message_data.get('sender_attr')}|{int(message_data.get('timestamp') or 0)}|{(message_data.get('content') or '')!r}"
                    )
                continue

            # runtime_id 与微信库 local_id 属不同 ID 空间，实时消息不占用 local_id（W1）
            local_id = None
            cursor = conn.execute(
                '''
                INSERT OR IGNORE INTO messages
                (conversation_id, local_id, talker, sender, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'realtime_backfill', ?)
                ''',
                (
                    conversation_id,
                    local_id,
                    talker_key,
                    None if message_data.get('sender_attr') == 'self' else talker_key,
                    1 if message_data.get('sender_attr') == 'self' else 0,
                    self._map_message_type(message_data.get('message_type')),
                    message_data.get('content') or '',
                    int(message_data.get('timestamp') or int(time.time())),
                    int(time.time()),
                )
            )
            if cursor.rowcount == 1:
                inserted += 1
                if len(inserted_samples) < 12:
                    inserted_samples.append(
                        f"{message_data.get('sender_attr')}|{int(message_data.get('timestamp') or 0)}|{(message_data.get('content') or '')!r}"
                    )
            else:
                existing += 1

        if inserted:
            total_count = conn.execute(
                'SELECT COUNT(*) FROM messages WHERE conversation_id = ?',
                (conversation_id,)
            ).fetchone()[0]
            conn.execute(
                '''
                UPDATE conversations
                SET display_name = ?, updated_at = ?, message_count = ?
                WHERE id = ?
                ''',
                (
                    talker_display_name or talker_key,
                    latest_ts or int(time.time()),
                    total_count,
                    conversation_id,
                )
            )
            conn.commit()
            # 回溯写入也是消息集变化：分析结果打脏（失败仅丢提示）
            try:
                from ..analysis.analysis_state import mark_conversations_stale

                mark_conversations_stale([conversation_id])
            except Exception as stale_e:
                logger.debug("[分析状态] backfill stale mark skipped: %s", stale_e)
            # RAG 索引同样要感知：不标脏则回溯历史永不进记忆
            # （id 游标只认 messages.id，插入即推进，等下次重建被拾起）
            try:
                from .rag.indexer import RagIndexQueue

                RagIndexQueue.mark_dirty(self._resolve_account_wxid(self.current_account_wxid), int(conversation_id))
            except Exception as rag_e:
                logger.debug("[RAG] backfill dirty mark skipped: %s", rag_e)

        if messages:
            _print(f"[Backfill] 已存在样本({existing}/{len(messages)}): {existing_samples}")
            _print(f"[Backfill] 实际插入样本({inserted}/{len(messages)}): {inserted_samples}")

        return {
            'inserted_count': inserted,
            'existing_count': existing,
        }

    def _merge_backfill_into_current_batch(
        self,
        talker_username: str,
        talker_display_name: str,
        messages: list[dict],
    ) -> int:
        """Append recovered messages into the active realtime batch for polling and archive."""
        if not self.current_batch_id or not messages:
            return 0

        merged = 0
        for message_data in messages:
            message_hash = message_data.get('message_hash')
            if message_hash and self.message_buffer.message_exists(message_hash, self.current_account_wxid):
                self.seen_hashes.add(message_hash)
                continue

            success = self.message_buffer.save_message(
                self.current_batch_id,
                self.current_account_wxid,
                talker_username,
                talker_display_name,
                message_data,
            )
            if not success:
                continue

            merged += 1
            if message_hash:
                self.seen_hashes.add(message_hash)
                content = str(message_data.get('content') or '').strip()
                if message_data.get('sender_attr') != 'system' and content:
                    try:
                        self.sentiment_service.analyze_and_cache(
                            message_id=message_hash,
                            text=content,
                        )
                    except Exception as e:
                        _print(f"[Backfill] 情感缓存失败: {e}")

        return merged

    def _run_backfill_in_current_chat_context(
        self,
        probe: dict,
        talker_username: str,
        talker_display_name: str,
        max_scroll_rounds: int = 80,
        wheel_times: int = 3,
    ) -> dict:
        """Run backfill using the current wx/chat context without re-running ChatWith."""
        collected: dict[str, dict] = {}
        seen_top_signature = None
        stagnant_rounds = 0
        checkpoint_found = False
        latest_step = min(8, max(int(wheel_times or 1) + 3, 6))

        _print(f"[Backfill] 预定位到最新消息区域，scroll_step={latest_step}")
        self._scroll_chat_to_latest(
            max_rounds=18,
            wheel_times=latest_step,
            stagnant_threshold=3,
        )

        for round_index in range(1, max_scroll_rounds + 1):
            visible_messages = self.wx.GetAllMessage() if self.wx else []
            if not visible_messages:
                _print(f"[Backfill] 第 {round_index} 轮未读取到可见消息，停止回溯")
                break

            _print(f"[Backfill] 第 {round_index}/{max_scroll_rounds} 轮，可见消息 {len(visible_messages)} 条")

            visible_top_signature = self._visible_message_signature(visible_messages, from_tail=False)
            if visible_top_signature == seen_top_signature:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
                seen_top_signature = visible_top_signature

            self._last_known_ts = 0
            checkpoint_index = -1
            round_messages: list[dict] = []
            round_identity_counts: dict[str, int] = {}

            for idx, msg in enumerate(visible_messages):
                sender_attr = 'self' if getattr(msg, 'is_self', False) else 'friend'
                if getattr(msg, 'is_system', False):
                    sender_attr = 'system'
                content = str(getattr(msg, 'content', '') or '')
                resolved_timestamp = self._resolve_message_timestamp(msg, sender_attr, content)

                if sender_attr == 'system':
                    continue

                match_reason = self._checkpoint_match_reason(
                    probe,
                    msg,
                    resolved_timestamp,
                    visible_messages=visible_messages,
                    visible_index=idx,
                )
                if match_reason:
                    _print(
                        "[Backfill] 命中 checkpoint: "
                        f"reason={match_reason}, "
                        f"content={content!r}, "
                        f"runtime_id={getattr(msg, 'id', None)!r}, "
                        f"hash={getattr(msg, 'hash', None)!r}, "
                        f"timestamp={resolved_timestamp}"
                    )
                    checkpoint_index = idx
                    checkpoint_found = True
                    continue

                base_identity = self._message_identity(msg)
                round_identity_counts[base_identity] = round_identity_counts.get(base_identity, 0) + 1
                identity = f"{base_identity}#occ{round_identity_counts[base_identity]}"
                runtime_id = str(getattr(msg, 'id', '') or '')
                round_messages.append({
                    'identity': identity,
                    'message_hash': build_message_hash(
                        self._listener_profile or getattr(self.wx, 'listener_profile', '') or 'unknown',
                        sender_attr,
                        getattr(msg, 'type', 'text'),
                        content,
                        int(resolved_timestamp or 0),
                        runtime_id or f"{idx}:{round_index}:{round_identity_counts[base_identity]}",
                    ),
                    'runtime_id': runtime_id,
                    'sender_attr': sender_attr,
                    'content': content,
                    'message_type': getattr(msg, 'type', 'text'),
                    'timestamp': resolved_timestamp,
                    'visible_index': idx,
                    'round_index': round_index,
                })

            if checkpoint_found:
                round_messages = [
                    item for item in round_messages
                    if int(item.get('visible_index', -1)) > checkpoint_index
                ]
                _print(
                    f"[Backfill] 第 {round_index} 轮命中 checkpoint，位置 idx={checkpoint_index}，"
                    f"本轮保留 {len(round_messages)} 条较新消息"
                )
            else:
                _print(f"[Backfill] 第 {round_index} 轮未命中 checkpoint，暂存 {len(round_messages)} 条消息")

            for item in round_messages:
                identity = str(item.pop('identity'))
                collected[identity] = item

            if checkpoint_found:
                break

            if stagnant_rounds >= 6:
                _print("[Backfill] 可见顶部消息连续未变化，停止继续上翻")
                break

            proximity = self._estimate_backfill_checkpoint_proximity(probe, visible_messages)
            time_gap_seconds = self._estimate_backfill_time_gap_seconds(probe, visible_messages)
            scroll_direction = self._choose_backfill_scroll_direction(
                proximity=proximity,
                time_gap_seconds=time_gap_seconds,
            )
            scroll_step = self._choose_backfill_scroll_step(
                checkpoint=probe,
                visible_messages=visible_messages,
                round_index=round_index,
                default_wheel_times=wheel_times,
                proximity=proximity,
                time_gap_seconds=time_gap_seconds,
            )
            scroll_repeats = self._choose_backfill_scroll_repeats(
                proximity=proximity,
                time_gap_seconds=time_gap_seconds,
            )
            _print(
                f"[Backfill] 第 {round_index} 轮继续滚动，direction={scroll_direction}, "
                f"scroll_step={scroll_step}, repeats={scroll_repeats}, "
                f"time_gap_seconds={time_gap_seconds}"
            )
            moved = False
            for _ in range(max(1, int(scroll_repeats or 1))):
                if scroll_direction == 'down':
                    moved = self._scroll_chat_history_down(wheel_times=scroll_step)
                else:
                    moved = self._scroll_chat_history_up(wheel_times=scroll_step)
                if not moved:
                    break
            if not moved:
                break

        if not checkpoint_found:
            return {
                'success': False,
                'inserted_count': 0,
                'message': '回溯达到阈值仍未找到断点，建议重新导入数据库',
                'need_reimport': True,
                'scanned_count': len(collected),
            }

        ordered_messages = sorted(
            collected.values(),
            key=lambda item: (
                int(item.get('timestamp') or 0),
                int(item.get('round_index') or 0),
                int(item.get('visible_index') or 0),
                str(item.get('runtime_id') or ''),
                item.get('content') or '',
            )
        )
        candidate_samples = [
            f"{item.get('sender_attr')}|{int(item.get('timestamp') or 0)}|{(item.get('content') or '')!r}"
            for item in ordered_messages[:12]
        ]
        _print(f"[Backfill] 候选样本({len(ordered_messages)}): {candidate_samples}")
        store_result = self._store_backfill_messages(
            talker_username=talker_username,
            talker_display_name=talker_display_name,
            messages=ordered_messages,
        )
        merged_batch_count = self._merge_backfill_into_current_batch(
            talker_username=talker_username,
            talker_display_name=talker_display_name,
            messages=ordered_messages,
        )
        inserted_count = int(store_result.get('inserted_count') or 0)
        existing_count = int(store_result.get('existing_count') or 0)
        _print(
            "[Backfill] 汇总: "
            f"当前命中轮保留={len(round_messages) if checkpoint_found else 0}, "
            f"最终候选={len(ordered_messages)}, "
            f"已存在跳过={existing_count}, "
            f"实际插入={inserted_count}, "
            f"当前batch并入={merged_batch_count}"
        )
        return {
            'success': True,
            'inserted_count': inserted_count,
            'existing_count': existing_count,
            'merged_batch_count': merged_batch_count,
            'scanned_count': len(ordered_messages),
            'message': f'回溯完成，补入 {inserted_count} 条消息',
            'need_reimport': False,
        }

    def run_backfill(
        self,
        talker_display_name: str,
        talker_username: str = '',
        threshold_seconds: int = 300,
        max_scroll_rounds: int = 80,
        wheel_times: int = 3,
    ) -> dict:
        """Backfill missing history between the last checkpoint and now."""
        if self.is_monitoring:
            return {
                'success': False,
                'message': '当前存在进行中的监听任务',
                'need_reimport': False,
            }

        probe = self.get_resume_probe(
            talker_display_name=talker_display_name,
            talker_username=talker_username,
            threshold_seconds=threshold_seconds,
        )
        if not probe.get('has_checkpoint'):
            return {
                'success': True,
                'inserted_count': 0,
                'message': '未找到可用断点，无需回溯',
                'need_reimport': False,
            }
        if not probe.get('should_offer_resume'):
            return {
                'success': True,
                'inserted_count': 0,
                'message': '断点时间间隔未达到回溯阈值',
                'need_reimport': False,
                'gap_seconds': probe.get('gap_seconds', 0),
            }

        self._session_generation += 1  # 回溯接管单例（R2）
        backfill_generation = self._session_generation
        self.current_display_name = talker_display_name
        self.current_talker = talker_username
        self._last_known_ts = 0

        try:
            self._create_wechat_instance_with_recovery(phase="backfill")
            self._bring_wechat_to_front()
            time.sleep(1.0)

            switched = False
            for target_name in self._build_chatwith_candidates():
                if self._try_chat_with(target_name):
                    switched = True
                    break
            if not switched:
                return {
                    'success': False,
                    'message': f"回溯前切换聊天失败: {self._chat_error}",
                    'need_reimport': False,
                }

            return self._run_backfill_in_current_chat_context(
                probe=probe,
                talker_username=talker_username,
                talker_display_name=talker_display_name,
                max_scroll_rounds=max_scroll_rounds,
                wheel_times=wheel_times,
            )
        finally:
            if self._session_generation != backfill_generation:
                # 回溯期间已有新监听会话启动并接管单例状态：
                # 不得清空新会话字段、不得销毁新会话的 wx 实例（R2）
                _print("⏭️ 回溯结束：检测到新监听会话已启动，跳过单例状态清理")
            else:
                self.current_display_name = None
                self.current_talker = None
                self._last_known_ts = 0
                self._reset_wechat_instance()

    def _migrate_buffer_to_messages(self, batch_id: str, talker_username: str, talker_display_name: str) -> int:
        """Move realtime buffered messages into the historical messages table."""
        from ...db.connection import get_db

        talker_key = self._get_talker_key(talker_username, talker_display_name)
        if not batch_id or not talker_key:
            return 0

        buffer_messages = self.message_buffer.get_batch_messages(batch_id, account_wxid=self.current_account_wxid)
        if not buffer_messages:
            return 0

        conn = get_db()
        conversation_id = self._get_or_create_conversation_id(
            talker_key,
            talker_display_name or talker_key
        )
        migrated = 0
        latest_ts = 0

        # 遍历时累计同签名（发送方+类型+时间戳+内容）出现次数作为判重序号，
        # 配合 ±59 秒窗口计数判重，避免同分钟连发的相同内容消息被静默丢掉（R4）
        occurrence_counts: dict[tuple, int] = {}
        for msg in buffer_messages:
            if msg.get('sender_attr') == 'system':
                continue
            signature = (
                1 if msg.get('sender_attr') == 'self' else 0,
                self._map_message_type(msg.get('message_type')),
                int(msg.get('timestamp') or 0),
                msg.get('content') or '',
            )
            occurrence_counts[signature] = occurrence_counts.get(signature, 0) + 1
            if self._message_exists_in_history(
                conversation_id,
                msg,
                occurrence_index=occurrence_counts[signature],
            ):
                continue

            # runtime_id 与微信库 local_id 属不同 ID 空间，实时消息不占用 local_id（W1）
            local_id = None
            timestamp = int(msg.get('timestamp') or int(time.time()))
            latest_ts = max(latest_ts, timestamp)

            cursor = conn.execute(
                '''
                INSERT OR IGNORE INTO messages
                (conversation_id, local_id, talker, sender, is_sender, message_type,
                 content, timestamp, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'realtime', ?)
                ''',
                (
                    conversation_id,
                    local_id,
                    talker_key,
                    None if msg.get('sender_attr') == 'self' else talker_key,
                    1 if msg.get('sender_attr') == 'self' else 0,
                    self._map_message_type(msg.get('message_type')),
                    msg.get('content') or '',
                    timestamp,
                    int(time.time()),
                )
            )
            if cursor.rowcount == 1:
                migrated += 1

        if migrated:
            total_count = conn.execute(
                'SELECT COUNT(*) FROM messages WHERE conversation_id = ?',
                (conversation_id,)
            ).fetchone()[0]
            conn.execute(
                '''
                UPDATE conversations
                SET display_name = ?, updated_at = ?, message_count = ?
                WHERE id = ?
                ''',
                (
                    talker_display_name or talker_key,
                    latest_ts or int(time.time()),
                    total_count,
                    conversation_id,
                )
            )
            conn.commit()
            # 监听期间的消息并入历史：分析结果打脏（失败仅丢提示）
            try:
                from ..analysis.analysis_state import mark_conversations_stale

                mark_conversations_stale([conversation_id])
            except Exception as stale_e:
                logger.debug("[分析状态] migrate stale mark skipped: %s", stale_e)
        else:
            conn.commit()

        self.message_buffer.mark_as_processed(batch_id, self.current_account_wxid)

        return migrated

