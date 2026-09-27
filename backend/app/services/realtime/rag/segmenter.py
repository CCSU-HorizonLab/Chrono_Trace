"""Independent message segmentation for RAG v2 indexing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any


@dataclass
class RagSegment:
    segment_id: str
    start_ts: int
    end_ts: int
    messages: list[dict[str, Any]]
    message_ids: list[int]
    topics: list[str]
    entities: list[str]
    time_label: str
    session_id: int | None = None


class RagSegmenter:
    """Build RAG-oriented topic segments directly from the message stream."""

    HARD_GAP_SECONDS = 7200
    SOFT_GAP_SECONDS = 1800
    TOPIC_SHIFT_MIN_GAP_SECONDS = 300
    TOPIC_SHIFT_MIN_MESSAGES = 10
    SHORT_MERGE_GAP_SECONDS = 1800
    MAX_SEGMENT_MESSAGES = 40
    MAX_SEGMENT_CHARS = 3000
    WINDOW_SIZE = 32
    WINDOW_STEP = 28
    MIN_SEGMENT_MESSAGES = 3
    SLEEP_END_HOUR = 7

    STOPWORDS = {
        "这个",
        "那个",
        "就是",
        "然后",
        "但是",
        "因为",
        "所以",
        "一下",
        "什么",
        "怎么",
        "我们",
        "你们",
        "他们",
        "她们",
        "哈哈",
        "嘿嘿",
        "宝宝",
        "宝贝",
    }

    FACT_MARKERS = (
        "贵",
        "便宜",
        "喜欢",
        "不喜欢",
        "想买",
        "买",
        "吃",
        "喝",
        "约",
        "答应",
        "说好",
        "记得",
        "上次",
        "之前",
        "那次",
        "一起",
        "玩",
        "流派",
        "卡组",
    )

    def segment(
        self,
        messages: list[dict[str, Any]],
        *,
        conversation_id: int,
        sessions: list[dict[str, Any]] | None = None,
    ) -> list[RagSegment]:
        normalized = self._normalize_messages(messages)
        if not normalized:
            return []

        raw_segments = self._split_by_boundaries(normalized)
        merged = self._merge_short_segments(raw_segments)
        windowed = self._split_oversized_segments(merged)

        return [
            self._build_segment(
                segment_messages,
                conversation_id=conversation_id,
                sessions=sessions or [],
            )
            for segment_messages in windowed
            if segment_messages
        ]

    def build_fact_memories(self, segment: RagSegment) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for msg in segment.messages:
            content = self._compact_content(msg.get("content"))
            if not content or not any(marker in content for marker in self.FACT_MARKERS):
                continue
            sender = "我" if int(msg.get("is_sender") or 0) else "对方"
            facts.append(
                {
                    "content": f"{sender}提到：{content}",
                    "source_id": msg.get("id"),
                    "source_ts": int(msg.get("timestamp") or segment.end_ts),
                    "subject": sender,
                    "topics": self.extract_topics(content),
                    "entities": self.extract_entities(content),
                }
            )
        return facts[:8]

    def render_segment(self, segment: RagSegment, *, max_messages: int = 20) -> str:
        lines = [f"时间：{segment.time_label}"]
        for msg in segment.messages[:max_messages]:
            sender = "我" if int(msg.get("is_sender") or 0) else "对方"
            content = self._compact_content(msg.get("content"))
            if content:
                lines.append(f"{sender}: {content}")
        return "\n".join(lines)

    def render_excerpt(self, segment: RagSegment, *, max_messages: int = 12) -> str:
        selected = self._select_evidence_messages(segment.messages, max_messages=max_messages)
        lines = [f"时间：{segment.time_label}"]
        for msg in selected:
            sender = "我" if int(msg.get("is_sender") or 0) else "对方"
            content = self._compact_content(msg.get("content"))
            if content:
                lines.append(f"{sender}: {content}")
        return "\n".join(lines)

    def extract_topics(self, text: str) -> list[str]:
        tokens = self._tokens(text)
        topics: list[str] = []
        for token in tokens:
            if token in self.STOPWORDS:
                continue
            if token not in topics:
                topics.append(token)
            if len(topics) >= 8:
                break
        return topics

    def extract_entities(self, text: str) -> list[str]:
        candidates = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,}|[\u4e00-\u9fff]{2,8}", text or "")
        entities: list[str] = []
        for candidate in candidates:
            if candidate in self.STOPWORDS:
                continue
            if any(marker in candidate for marker in self.FACT_MARKERS) or len(candidate) >= 3:
                if candidate not in entities:
                    entities.append(candidate)
            if len(entities) >= 8:
                break
        return entities

    def time_label(self, start_ts: int, end_ts: int | None = None) -> str:
        dt = datetime.fromtimestamp(int(end_ts or start_ts or 0))
        period = "凌晨" if dt.hour < 6 else "上午" if dt.hour < 12 else "下午" if dt.hour < 18 else "晚上"
        return f"{dt:%Y-%m-%d} {period}"

    def _normalize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for msg in messages:
            content = self._compact_content(msg.get("content"))
            if not content:
                continue
            item = dict(msg)
            item["content"] = content
            try:
                item["timestamp"] = int(item.get("timestamp") or 0)
            except (TypeError, ValueError):
                item["timestamp"] = 0
            try:
                item["id"] = int(item.get("id") or 0)
            except (TypeError, ValueError):
                item["id"] = 0
            normalized.append(item)
        return sorted(normalized, key=lambda item: (item.get("timestamp") or 0, item.get("id") or 0))

    def _split_by_boundaries(self, messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        segments: list[list[dict[str, Any]]] = []
        current = [messages[0]]
        for previous, current_msg in zip(messages, messages[1:]):
            if self._should_split(previous, current_msg, current):
                segments.append(current)
                current = [current_msg]
            else:
                current.append(current_msg)
        if current:
            segments.append(current)
        return segments

    def _should_split(
        self,
        previous: dict[str, Any],
        current: dict[str, Any],
        current_segment: list[dict[str, Any]],
    ) -> bool:
        previous_ts = int(previous.get("timestamp") or 0)
        current_ts = int(current.get("timestamp") or 0)
        gap = current_ts - previous_ts
        if gap <= 0:
            return False
        if self._crosses_day_or_sleep(previous_ts, current_ts):
            return True
        if gap > self.HARD_GAP_SECONDS:
            return True
        if gap > self.SOFT_GAP_SECONDS and self._topic_overlap(current_segment[-6:], [current]) <= 0.1:
            return True
        if (
            gap >= self.TOPIC_SHIFT_MIN_GAP_SECONDS
            and len(current_segment) >= self.TOPIC_SHIFT_MIN_MESSAGES
        ):
            if self._topic_overlap(current_segment[-6:], [current]) == 0 and self._has_topic_shift(current_segment, current):
                return True
        return False

    def _merge_short_segments(self, segments: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
        merged: list[list[dict[str, Any]]] = []
        index = 0
        while index < len(segments):
            current = list(segments[index])
            if len(current) < self.MIN_SEGMENT_MESSAGES and index + 1 < len(segments):
                gap = int(segments[index + 1][0].get("timestamp") or 0) - int(current[-1].get("timestamp") or 0)
                if gap <= self.SHORT_MERGE_GAP_SECONDS:
                    merged.append(current + segments[index + 1])
                    index += 2
                    continue
            if len(current) < self.MIN_SEGMENT_MESSAGES and merged:
                gap = int(current[0].get("timestamp") or 0) - int(merged[-1][-1].get("timestamp") or 0)
                if gap <= self.SHORT_MERGE_GAP_SECONDS:
                    merged[-1].extend(current)
                    index += 1
                    continue
            merged.append(current)
            index += 1
        return merged

    def _split_oversized_segments(self, segments: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
        output: list[list[dict[str, Any]]] = []
        for segment in segments:
            total_chars = sum(len(str(msg.get("content") or "")) for msg in segment)
            if len(segment) <= self.MAX_SEGMENT_MESSAGES and total_chars <= self.MAX_SEGMENT_CHARS:
                output.append(segment)
                continue
            start = 0
            while start < len(segment):
                window = segment[start:start + self.WINDOW_SIZE]
                if window:
                    output.append(window)
                if start + self.WINDOW_SIZE >= len(segment):
                    break
                start += self.WINDOW_STEP
        return output

    def _build_segment(
        self,
        messages: list[dict[str, Any]],
        *,
        conversation_id: int,
        sessions: list[dict[str, Any]],
    ) -> RagSegment:
        start_ts = int(messages[0].get("timestamp") or 0)
        end_ts = int(messages[-1].get("timestamp") or start_ts)
        message_ids = [int(msg.get("id") or 0) for msg in messages if int(msg.get("id") or 0)]
        text = " ".join(str(msg.get("content") or "") for msg in messages)
        return RagSegment(
            segment_id=f"conversation:{conversation_id}:{start_ts}:{end_ts}:{message_ids[0] if message_ids else 0}",
            start_ts=start_ts,
            end_ts=end_ts,
            messages=messages,
            message_ids=message_ids,
            topics=self.extract_topics(text),
            entities=self.extract_entities(text),
            time_label=self.time_label(start_ts, end_ts),
            session_id=self._matching_session_id(start_ts, end_ts, sessions),
        )

    def _matching_session_id(self, start_ts: int, end_ts: int, sessions: list[dict[str, Any]]) -> int | None:
        for session in sessions:
            try:
                session_start = int(session.get("start_time") or session.get("start_timestamp") or 0)
                session_end = int(session.get("end_time") or session.get("end_timestamp") or 0)
            except (TypeError, ValueError):
                continue
            if session_start <= start_ts and end_ts <= session_end:
                try:
                    return int(session.get("id") or 0) or None
                except (TypeError, ValueError):
                    return None
        return None

    def _select_evidence_messages(self, messages: list[dict[str, Any]], *, max_messages: int) -> list[dict[str, Any]]:
        fact_like = [
            msg
            for msg in messages
            if any(marker in str(msg.get("content") or "") for marker in self.FACT_MARKERS)
        ]
        if fact_like:
            return fact_like[:max_messages]
        if len(messages) <= max_messages:
            return messages
        half = max_messages // 2
        return messages[:half] + messages[-(max_messages - half):]

    def _crosses_day_or_sleep(self, previous_ts: int, current_ts: int) -> bool:
        previous = datetime.fromtimestamp(previous_ts)
        current = datetime.fromtimestamp(current_ts)
        if previous.date() != current.date():
            return True
        return previous.hour < self.SLEEP_END_HOUR <= current.hour

    def _topic_overlap(self, left_messages: list[dict[str, Any]], right_messages: list[dict[str, Any]]) -> float:
        left = set(self.extract_topics(" ".join(str(msg.get("content") or "") for msg in left_messages)))
        right = set(self.extract_topics(" ".join(str(msg.get("content") or "") for msg in right_messages)))
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, min(len(left), len(right)))

    def _has_topic_shift(self, current_segment: list[dict[str, Any]], current_msg: dict[str, Any]) -> bool:
        previous_topics = set(self.extract_topics(" ".join(str(msg.get("content") or "") for msg in current_segment[-6:])))
        current_topics = set(self.extract_topics(str(current_msg.get("content") or "")))
        return bool(previous_topics and current_topics and not (previous_topics & current_topics))

    def _tokens(self, text: str) -> list[str]:
        compact = re.sub(r"\s+", "", str(text or ""))
        tokens = re.split(r"[\s,，。！？；：、/()（）\[\]\-~～]+", str(text or ""))
        words = [token for token in tokens if len(token) >= 2]
        for size in (2, 3, 4):
            words.extend(compact[index:index + size] for index in range(max(0, len(compact) - size + 1)))
        deduped: list[str] = []
        for word in words:
            if word and word not in deduped:
                deduped.append(word)
        return deduped[:80]

    def _compact_content(self, content: Any) -> str:
        return re.sub(r"\s+", " ", str(content or "")).strip()[:240]
