"""断点上下文匹配与回溯滚动策略（纯函数）。

自 monitor_service.py 拆出（步骤 4B）。仅确定性算法。
"""
from __future__ import annotations

import logging
import re
import sys

logger = logging.getLogger(__name__)


import sys

def _print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(arg) for arg in args) + end
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe_text)
        if kwargs.get("flush", False):
            sys.stdout.flush()
from datetime import datetime, timedelta
import json
from .providers.models import normalize_text

class BackfillMatcherMixin:
    """Checkpoint matching + scroll strategy."""

    def _normalize_checkpoint_context_value(self, token: str) -> str:
        """Normalize checkpoint context tokens so relative time labels stay stable across days."""
        text = normalize_text(token)
        if not text:
            return ""
        if text.startswith('system_hm:'):
            return text
        if text.startswith('system_ts:'):
            return text
        if text.startswith('system:'):
            label = text.split(':', 1)[1].strip()
            matched = re.search(r'(\d{1,2}):(\d{2})$', label)
            if matched:
                return f"system_hm:{int(matched.group(1)):02d}:{matched.group(2)}"
            resolved = self._resolve_time_label(label, 0)
            if resolved:
                return f"system_ts:{int(resolved // 60)}"
            return f"system:{normalize_text(label)}"
        return text

    def _checkpoint_context_token(self, sender_attr: str, content: str) -> str:
        """Build a tolerant checkpoint context token."""
        text = normalize_text(content)
        if not text:
            return ""
        if normalize_text(sender_attr) == 'system':
            return self._normalize_checkpoint_context_value(f"system:{text}")
        return self._normalize_checkpoint_context_value(text)

    def _extract_visible_checkpoint_context(
        self,
        visible_messages: list,
        anchor_index: int,
        max_neighbors: int = 6,
    ) -> dict:
        """Extract a compact context window around a visible message."""
        if not visible_messages or anchor_index < 0 or anchor_index >= len(visible_messages):
            return {}

        anchor_msg = visible_messages[anchor_index]
        anchor_sender_attr = self._resolve_visible_sender_attr(anchor_msg)
        anchor_content = str(getattr(anchor_msg, 'content', '') or '')
        before: list[str] = []
        after: list[str] = []

        for msg in visible_messages[:anchor_index]:
            token = self._checkpoint_context_token(
                self._resolve_visible_sender_attr(msg),
                str(getattr(msg, 'content', '') or ''),
            )
            if token:
                before.append(token)
        for msg in visible_messages[anchor_index + 1:]:
            token = self._checkpoint_context_token(
                self._resolve_visible_sender_attr(msg),
                str(getattr(msg, 'content', '') or ''),
            )
            if token:
                after.append(token)

        return {
            'sender_attr': anchor_sender_attr,
            'message_type': str(getattr(anchor_msg, 'type', 'text') or 'text'),
            'anchor': self._checkpoint_context_token(anchor_sender_attr, anchor_content),
            'before': before[-max(0, int(max_neighbors or 0)):],
            'after': after[:max(0, int(max_neighbors or 0))],
        }

    def _extract_record_checkpoint_context(
        self,
        messages: list[dict],
        anchor_index: int,
        max_neighbors: int = 6,
    ) -> dict:
        """Extract a compact context window from buffered record dicts."""
        if not messages or anchor_index < 0 or anchor_index >= len(messages):
            return {}

        anchor_message = messages[anchor_index]
        before: list[str] = []
        after: list[str] = []
        for item in messages[:anchor_index]:
            token = self._checkpoint_context_token(
                str(item.get('sender_attr') or ''),
                str(item.get('content') or ''),
            )
            if token:
                before.append(token)
        for item in messages[anchor_index + 1:]:
            token = self._checkpoint_context_token(
                str(item.get('sender_attr') or ''),
                str(item.get('content') or ''),
            )
            if token:
                after.append(token)

        return {
            'sender_attr': str(anchor_message.get('sender_attr') or ''),
            'message_type': str(anchor_message.get('message_type') or 'text'),
            'anchor': self._checkpoint_context_token(
                str(anchor_message.get('sender_attr') or ''),
                str(anchor_message.get('content') or ''),
            ),
            'before': before[-max(0, int(max_neighbors or 0)):],
            'after': after[:max(0, int(max_neighbors or 0))],
        }

    def _select_checkpoint_visible_index(self, last_message: dict, visible_messages: list) -> int:
        """Find the most plausible visible occurrence for the checkpoint anchor."""
        target_content = normalize_text(str(last_message.get('content') or ''))
        target_runtime_id = normalize_text(str(last_message.get('runtime_id') or ''))
        target_sender_attr = normalize_text(str(last_message.get('sender_attr') or ''))
        target_message_type = normalize_text(str(last_message.get('message_type') or 'text')).lower()
        if not target_content or not visible_messages:
            return -1

        best_index = -1
        best_score = None
        for index, msg in enumerate(visible_messages):
            content = normalize_text(str(getattr(msg, 'content', '') or ''))
            if content != target_content:
                continue

            score = index
            runtime_id = normalize_text(str(getattr(msg, 'id', '') or ''))
            if target_runtime_id and runtime_id == target_runtime_id:
                score += 1000

            sender_attr = self._resolve_visible_sender_attr(msg)
            if target_sender_attr and normalize_text(sender_attr) == target_sender_attr:
                score += 100

            message_type = normalize_text(str(getattr(msg, 'type', 'text') or 'text')).lower()
            if target_message_type and message_type == target_message_type:
                score += 50

            if best_score is None or score > best_score:
                best_score = score
                best_index = index

        return best_index

    def _select_checkpoint_record_index(self, last_message: dict, messages: list[dict]) -> int:
        """Find the buffered record index for the checkpoint anchor."""
        target_content = normalize_text(str(last_message.get('content') or ''))
        target_runtime_id = normalize_text(str(last_message.get('runtime_id') or ''))
        target_sender_attr = normalize_text(str(last_message.get('sender_attr') or ''))
        target_message_type = normalize_text(str(last_message.get('message_type') or 'text')).lower()
        if not target_content or not messages:
            return -1

        best_index = -1
        best_score = None
        for index, item in enumerate(messages):
            content = normalize_text(str(item.get('content') or ''))
            if content != target_content:
                continue

            score = index
            runtime_id = normalize_text(str(item.get('runtime_id') or ''))
            if target_runtime_id and runtime_id == target_runtime_id:
                score += 1000
            if target_sender_attr and normalize_text(str(item.get('sender_attr') or '')) == target_sender_attr:
                score += 100
            if target_message_type and normalize_text(str(item.get('message_type') or 'text')).lower() == target_message_type:
                score += 50

            if best_score is None or score > best_score:
                best_score = score
                best_index = index

        return best_index

    def _build_checkpoint_context(self, last_message: dict, batch_messages: list[dict]) -> dict:
        """Build a context window for checkpoint matching."""
        try:
            visible_messages = self.wx.GetAllMessage() if self.wx else []
        except Exception as e:
            _print(f"[Checkpoint] 读取当前可见消息失败，回退 batch context: {e}")
            visible_messages = []

        visible_index = self._select_checkpoint_visible_index(last_message, visible_messages)
        if visible_index >= 0:
            context = self._extract_visible_checkpoint_context(visible_messages, visible_index)
            if context:
                return context

        batch_index = self._select_checkpoint_record_index(last_message, batch_messages)
        if batch_index >= 0:
            return self._extract_record_checkpoint_context(batch_messages, batch_index)
        return {}

    def _normalize_checkpoint_context(self, raw_context) -> dict:
        """Normalize checkpoint context payloads from DB/tests into a dict."""
        if isinstance(raw_context, dict):
            return raw_context
        if not raw_context:
            return {}
        try:
            payload = json.loads(str(raw_context))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _score_context_window(
        self,
        expected: list[str],
        actual: list[str],
        reverse: bool = False,
    ) -> dict:
        """Score the best contiguous overlap between two context windows with sliding alignment."""
        expected_tokens = [
            self._normalize_checkpoint_context_value(token)
            for token in (expected or [])
        ]
        expected_tokens = [token for token in expected_tokens if token]
        actual_tokens = [
            self._normalize_checkpoint_context_value(token)
            for token in (actual or [])
        ]
        actual_tokens = [token for token in actual_tokens if token]

        if reverse:
            expected_tokens = list(reversed(expected_tokens))
            actual_tokens = list(reversed(actual_tokens))

        weights = [len(expected_tokens) - idx for idx in range(len(expected_tokens))]
        total_weight = sum(weights)
        best = {
            'count': 0,
            'weight': 0,
            'expected_start': -1,
            'actual_start': -1,
            'expected_count': len(expected_tokens),
            'actual_count': len(actual_tokens),
            'expected_weight': total_weight,
            'coverage': 0.0,
            'weight_ratio': 0.0,
        }
        if not expected_tokens or not actual_tokens:
            return best

        for expected_start in range(len(expected_tokens)):
            for actual_start in range(len(actual_tokens)):
                matched = 0
                matched_weight = 0
                while (
                    expected_start + matched < len(expected_tokens)
                    and actual_start + matched < len(actual_tokens)
                ):
                    expected_token = expected_tokens[expected_start + matched]
                    actual_token = actual_tokens[actual_start + matched]
                    if expected_token != actual_token:
                        break
                    matched_weight += weights[expected_start + matched]
                    matched += 1

                if matched > best['count'] or (
                    matched == best['count'] and matched_weight > best['weight']
                ):
                    best.update({
                        'count': matched,
                        'weight': matched_weight,
                        'expected_start': expected_start,
                        'actual_start': actual_start,
                    })

        if best['expected_count']:
            best['coverage'] = best['count'] / best['expected_count']
        if best['expected_weight']:
            best['weight_ratio'] = best['weight'] / best['expected_weight']
        return best

    def _context_window_match_reason(self, checkpoint_context: dict, visible_context: dict) -> str | None:
        """Decide whether the visible anchor matches the saved checkpoint context."""
        expected_before = list(checkpoint_context.get('before') or [])
        expected_after = list(checkpoint_context.get('after') or [])
        actual_before = list(visible_context.get('before') or [])
        actual_after = list(visible_context.get('after') or [])

        before_score = self._score_context_window(expected_before, actual_before, reverse=True)
        after_score = self._score_context_window(expected_after, actual_after, reverse=False)
        total_expected_weight = int(before_score.get('expected_weight') or 0) + int(after_score.get('expected_weight') or 0)
        matched_weight = int(before_score.get('weight') or 0) + int(after_score.get('weight') or 0)
        total_weight_ratio = (matched_weight / total_expected_weight) if total_expected_weight else 0.0

        sender_expected = normalize_text(str(checkpoint_context.get('sender_attr') or ''))
        sender_actual = normalize_text(str(visible_context.get('sender_attr') or ''))
        type_expected = normalize_text(str(checkpoint_context.get('message_type') or '')).lower()
        type_actual = normalize_text(str(visible_context.get('message_type') or '')).lower()
        if sender_expected and sender_actual and sender_expected == sender_actual:
            total_weight_ratio = min(1.0, total_weight_ratio + 0.05)
        if type_expected and type_actual and type_expected == type_actual:
            total_weight_ratio = min(1.0, total_weight_ratio + 0.05)

        expected_before_count = int(before_score.get('expected_count') or 0)
        expected_after_count = int(after_score.get('expected_count') or 0)
        before_count = int(before_score.get('count') or 0)
        after_count = int(after_score.get('count') or 0)
        strong_before = expected_before_count > 0 and (
            before_count >= min(3, expected_before_count)
            or float(before_score.get('weight_ratio') or 0.0) >= 0.75
        )
        solid_before = expected_before_count > 0 and (
            before_count >= min(2, expected_before_count)
            or float(before_score.get('weight_ratio') or 0.0) >= 0.55
        )
        any_after = expected_after_count > 0 and after_count >= 1
        strong_after = expected_after_count > 0 and (
            after_count >= min(2, expected_after_count)
            or float(after_score.get('weight_ratio') or 0.0) >= 0.65
        )

        if expected_after_count:
            if any_after and (solid_before or strong_after or total_weight_ratio >= 0.7):
                return 'context_window'
            return None

        if strong_before and total_weight_ratio >= 0.65:
            return 'context_before_window'

        return None

    def _estimate_backfill_checkpoint_proximity(self, checkpoint: dict, visible_messages: list) -> dict:
        """Estimate how close the current viewport is to the saved checkpoint anchor."""
        checkpoint_preview = re.sub(r'\s+', ' ', str(checkpoint.get('last_message_preview') or '')).strip()
        checkpoint_context = self._normalize_checkpoint_context(
            checkpoint.get('last_message_context')
        )
        visible_tokens: list[str] = []
        preview_visible = False
        preview_candidates = 0
        strongest_candidate = {
            'reason': None,
            'before_count': 0,
            'after_count': 0,
            'before_ratio': 0.0,
            'after_ratio': 0.0,
            'total_ratio': 0.0,
        }

        for idx, msg in enumerate(visible_messages or []):
            sender_attr = self._resolve_visible_sender_attr(msg)
            content = str(getattr(msg, 'content', '') or '')
            token = self._checkpoint_context_token(sender_attr, content)
            if token:
                visible_tokens.append(token)

            normalized_content = re.sub(r'\s+', ' ', content).strip()
            if not checkpoint_preview or normalized_content != checkpoint_preview:
                continue

            preview_visible = True
            preview_candidates += 1
            if not checkpoint_context:
                continue

            visible_context = self._extract_visible_checkpoint_context(
                visible_messages,
                idx,
            )
            before_score = self._score_context_window(
                list(checkpoint_context.get('before') or []),
                list(visible_context.get('before') or []),
                reverse=True,
            )
            after_score = self._score_context_window(
                list(checkpoint_context.get('after') or []),
                list(visible_context.get('after') or []),
                reverse=False,
            )
            total_expected_weight = int(before_score.get('expected_weight') or 0) + int(after_score.get('expected_weight') or 0)
            matched_weight = int(before_score.get('weight') or 0) + int(after_score.get('weight') or 0)
            total_ratio = (matched_weight / total_expected_weight) if total_expected_weight else 0.0
            context_reason = self._context_window_match_reason(
                checkpoint_context,
                visible_context,
            )
            candidate = {
                'reason': context_reason,
                'before_count': int(before_score.get('count') or 0),
                'after_count': int(after_score.get('count') or 0),
                'before_ratio': float(before_score.get('weight_ratio') or 0.0),
                'after_ratio': float(after_score.get('weight_ratio') or 0.0),
                'total_ratio': float(total_ratio),
            }
            if (
                candidate['total_ratio'] > strongest_candidate['total_ratio']
                or (
                    candidate['total_ratio'] == strongest_candidate['total_ratio']
                    and (candidate['before_count'] + candidate['after_count'])
                    > (strongest_candidate['before_count'] + strongest_candidate['after_count'])
                )
            ):
                strongest_candidate = candidate

        focus_tokens: list[str] = []
        if checkpoint_context:
            expected_before = [
                self._normalize_checkpoint_context_value(token)
                for token in list(checkpoint_context.get('before') or [])[-3:]
            ]
            expected_after = [
                self._normalize_checkpoint_context_value(token)
                for token in list(checkpoint_context.get('after') or [])[:2]
            ]
            focus_tokens = [token for token in (expected_before + expected_after) if token]

        visible_token_set = set(visible_tokens)
        focus_hits = sum(1 for token in focus_tokens if token in visible_token_set)
        strongest_candidate['preview_visible'] = preview_visible
        strongest_candidate['preview_candidates'] = preview_candidates
        strongest_candidate['focus_hits'] = focus_hits
        return strongest_candidate

    def _estimate_backfill_time_gap_seconds(self, checkpoint: dict, visible_messages: list) -> int:
        """Estimate whether the current viewport is still later than the checkpoint based on visible time markers."""
        checkpoint_ts = int(checkpoint.get('last_message_timestamp') or 0)
        if not checkpoint_ts:
            return 0

        visible_marker_timestamps: list[int] = []
        for msg in visible_messages or []:
            label = ''
            if getattr(msg, 'is_system', False):
                label = str(getattr(msg, 'content', '') or '')
            else:
                label = str(getattr(msg, 'time', None) or getattr(msg, 'CreateTime', '') or '')
            parsed = self._resolve_time_label(label, 0) if label else 0
            if parsed:
                visible_marker_timestamps.append(int(parsed))

        if not visible_marker_timestamps:
            return 0

        earliest_visible_ts = min(visible_marker_timestamps)
        latest_visible_ts = max(visible_marker_timestamps)
        if checkpoint_ts < earliest_visible_ts:
            return earliest_visible_ts - checkpoint_ts
        if checkpoint_ts > latest_visible_ts:
            return latest_visible_ts - checkpoint_ts
        return 0

    def _choose_backfill_scroll_step(
        self,
        checkpoint: dict,
        visible_messages: list,
        round_index: int,
        default_wheel_times: int = 3,
        proximity: dict | None = None,
        time_gap_seconds: int | None = None,
    ) -> int:
        """Choose a backfill scroll step: move faster when far away, slow down near the anchor."""
        base_step = max(1, int(default_wheel_times or 1))
        fast_step = min(8, max(base_step + 3, 6))
        medium_step = min(5, max(base_step + 1, 4))
        slow_step = max(1, base_step - 1)
        proximity = proximity or self._estimate_backfill_checkpoint_proximity(checkpoint, visible_messages)
        time_gap_seconds = (
            int(time_gap_seconds)
            if time_gap_seconds is not None
            else self._estimate_backfill_time_gap_seconds(checkpoint, visible_messages)
        )

        if proximity.get('reason') in {'context_window', 'context_before_window'}:
            return 1
        if proximity.get('preview_visible'):
            if (
                int(proximity.get('before_count') or 0) >= 2
                or int(proximity.get('after_count') or 0) >= 1
                or float(proximity.get('total_ratio') or 0.0) >= 0.45
            ):
                return 1
            return slow_step
        if int(proximity.get('focus_hits') or 0) >= 2:
            return slow_step
        if int(proximity.get('focus_hits') or 0) == 1:
            return min(base_step, 3)
        if time_gap_seconds >= 12 * 3600:
            return max(fast_step, 8)
        if time_gap_seconds >= 6 * 3600:
            return max(fast_step, 7)
        if time_gap_seconds >= 3600:
            return max(fast_step, 6)
        if time_gap_seconds >= 15 * 60:
            return fast_step
        if round_index <= 4:
            return fast_step
        if round_index <= 12:
            return medium_step
        return max(base_step, 3)

    def _choose_backfill_scroll_direction(
        self,
        proximity: dict | None = None,
        time_gap_seconds: int | None = None,
    ) -> str:
        """Pick the next scroll direction for backfill."""
        proximity = proximity or {}
        time_gap_seconds = int(time_gap_seconds or 0)
        if (
            time_gap_seconds <= -15 * 60
            and not proximity.get('preview_visible')
            and int(proximity.get('focus_hits') or 0) == 0
        ):
            return 'down'
        return 'up'

    def _choose_backfill_scroll_repeats(
        self,
        proximity: dict | None = None,
        time_gap_seconds: int | None = None,
    ) -> int:
        """Choose how many consecutive small-step scrolls to batch into one backfill round."""
        proximity = proximity or {}
        time_gap_seconds = int(time_gap_seconds or 0)
        if proximity.get('reason') in {'context_window', 'context_before_window'}:
            return 1
        if proximity.get('preview_visible') or int(proximity.get('focus_hits') or 0) > 0:
            return 1
        if time_gap_seconds >= 12 * 3600:
            return 3
        if time_gap_seconds >= 6 * 3600:
            return 2
        if time_gap_seconds >= 3600:
            return 2
        return 1

    def _visible_message_signature(self, visible_messages: list, from_tail: bool = False, size: int = 3) -> tuple[str, ...]:
        """Build a short edge signature so small-step scrolling doesn't look stagnant too early."""
        if not visible_messages:
            return tuple()
        window_size = max(1, int(size or 1))
        selected = visible_messages[-window_size:] if from_tail else visible_messages[:window_size]
        return tuple(self._message_identity(msg) for msg in selected)

    def _resolve_time_label(self, label, fallback: int) -> int:
        """Convert WeChat time labels like '昨天 14:30' into unix timestamps."""
        if not label:
            return fallback

        text = str(label).strip()
        if not text:
            return fallback

        now_dt = datetime.now()

        matched = re.match(r'^(\d{1,2}):(\d{2})$', text)
        if matched:
            parsed = int(datetime(
                now_dt.year, now_dt.month, now_dt.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())
            # 微信对今天消息只显示 HH:MM；若解析值落在未来（超出 60 秒容差），
            # 说明标签属于昨天（如刚跨零点时仍显示昨日时刻），回退为昨天同一时刻（R5）
            if parsed > int(now_dt.timestamp()) + 60:
                parsed -= 86400
            return parsed

        matched = re.match(r'^昨天\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            day = now_dt - timedelta(days=1)
            return int(datetime(
                day.year, day.month, day.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        matched = re.match(r'^前天\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            day = now_dt - timedelta(days=2)
            return int(datetime(
                day.year, day.month, day.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        matched = re.match(
            r'^(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s+(?:(?:星期|周)[一二三四五六日天]\s+)?(?:(?:凌晨|早上|上午|中午|下午|傍晚|晚上|夜间)\s*)?(\d{1,2}):(\d{2})$',
            text,
        )
        if matched:
            explicit_year = int(matched.group(1)) if matched.group(1) else None
            month = int(matched.group(2))
            day = int(matched.group(3))
            hour = int(matched.group(4))
            minute = int(matched.group(5))
            year = explicit_year or now_dt.year
            candidate = datetime(year, month, day, hour, minute)
            if explicit_year is None and candidate > now_dt + timedelta(days=1):
                candidate = datetime(year - 1, month, day, hour, minute)
            return int(candidate.timestamp())

        matched = re.match(r'^(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})$', text)
        if matched:
            month = int(matched.group(1))
            day = int(matched.group(2))
            hour = int(matched.group(3))
            minute = int(matched.group(4))
            year = now_dt.year
            candidate = datetime(year, month, day, hour, minute)
            if candidate > now_dt + timedelta(days=1):
                candidate = datetime(year - 1, month, day, hour, minute)
            return int(candidate.timestamp())

        weekday_map = {
            '周一': 0, '星期一': 0,
            '周二': 1, '星期二': 1,
            '周三': 2, '星期三': 2,
            '周四': 3, '星期四': 3,
            '周五': 4, '星期五': 4,
            '周六': 5, '星期六': 5,
            '周日': 6, '星期日': 6, '星期天': 6,
        }
        for prefix, weekday in weekday_map.items():
            matched = re.match(rf'^{re.escape(prefix)}\s+(\d{{1,2}}):(\d{{2}})$', text)
            if not matched:
                continue
            # 微信对今天消息只显示 HH:MM，带星期的标签必属过去 7 天；差值为 0 时
            # 应取上周同一天而不是今天，故统一映射到 [1, 7] 天前（R5）
            day = now_dt - timedelta(days=((now_dt.weekday() - weekday - 1) % 7) + 1)
            return int(datetime(
                day.year, day.month, day.day,
                int(matched.group(1)), int(matched.group(2))
            ).timestamp())

        return fallback

