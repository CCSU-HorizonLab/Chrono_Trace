"""关系章节——会话时间轴自动分段与周级大五分布（纯统计层，零 LLM）。

设计（docs/goals/persona-chapters-goal.md）：
- 章节检测：周粒度多变量特征（文本量/对方占比/正向率/回复时延）z 归一后
  最优分段（DP 精确解 + BIC 式惩罚选段数），边界吸附 ±7 天内的里程碑。
  均分切窗会把真转折劈成两半、把两段平静黏成一段——按行为变点切「自然章节」。
- 周级大五：复用 big5_proxies 锚点插值与缺席重归一，逐周算单侧代理分组成
  五维分布序列。人格是状态的密度分布（Fleeson WTT 2015），逐段点分读不出
  演变——分布带才是演变本体；分布带只做相对演变叙事，不做绝对测评解读。
- 周内单侧文本 < WEEKLY_MIN_SIDE_TEXTS 该侧该周记 None（诚实留白）。
- 纯统计无 LLM 无缓存：单次请求一次行扫描可承受；C2 摘要层再引入落库。
"""
from __future__ import annotations

import logging
import json
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db

logger = logging.getLogger(__name__)

CHAPTERS_VERSION = 1
WEEK_SECONDS = 7 * 86400
WEEKLY_MIN_SIDE_TEXTS = 10     # 周内单侧文本不足该数 → 该侧该周大五记 None
WEEKLY_LEX_SAMPLE = 200        # 每周每侧分词抽样上限（jieba 代价约束）
MIN_CHAPTER_WEEKS = 2          # 章节最短跨度（周）
MAX_CHAPTERS = 8
CHANGE_SNAP_DAYS = 7           # 章节边界吸附里程碑半径（天）
PENALTY_FACTOR = 2.0           # 每条边界惩罚 = factor × d × ln(n)，合成序列校准
CHANGE_Z_THRESHOLD = 0.5       # 相邻章节均值差（z 单位）超过该值才报变化
MIN_TOTAL_TEXTS = 40           # 会话文本总量低于此不出章节
LATENCY_CAP_SECONDS = 86400    # 回复时延超一天视为异常不进周特征

# 章节特征键（检测用四路信号；label 供前端变化归因展示）
FEATURE_LABELS = {
    "volume": "消息密度",
    "other_share": "TA 占比",
    "pos_ratio": "正向情绪",
    "latency": "回复时延",
}


def _week_start(ts: int) -> int:
    """消息时间戳所在周的周一 00:00（本地时区）。"""
    lt = time.localtime(ts)
    day_start = ts - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
    return day_start - lt.tm_wday * 86400


def detect_chapters(
    features: List[List[float]],
    min_seg_weeks: int = MIN_CHAPTER_WEEKS,
    max_chapters: int = MAX_CHAPTERS,
    penalty_factor: float = PENALTY_FACTOR,
) -> List[int]:
    """多变量周特征序列的最优分段（纯函数，确定性）。

    每列 z 归一（零方差列剔除）；DP 精确最小化段内平方和，段数由
    「SSE + penalty×(段数-1)」择优（penalty = factor·d·ln n，d 为在场特征
    维数——BIC 式且宁缺毋滥：单特征约 1.5σ 以上的均值漂移才值得切一刀）。
    返回每段起始周下标（首段恒为 0）；样本过少/全零方差返回 [0]。
    """
    n = len(features)
    if n < min_seg_weeks * 2:
        return [0]

    # 逐列 z 归一；方差为零的列剔除（恒定特征无判别力）
    cols: List[List[float]] = []
    for j in range(len(features[0])):
        column = [float(row[j]) for row in features]
        mean = sum(column) / n
        var = sum((v - mean) ** 2 for v in column) / n
        if var <= 1e-12:
            continue
        std = math.sqrt(var)
        cols.append([(v - mean) / std for v in column])
    if not cols:
        return [0]

    d = len(cols)
    # 前缀和：单位方差列的段内 SSE = Σ_f [k - (段和)²/k]，O(1) 每对端点
    prefix = [[0.0] * (n + 1) for _ in range(d)]
    for f, col in enumerate(cols):
        acc = 0.0
        for i, v in enumerate(col):
            acc += v
            prefix[f][i + 1] = acc

    def cost(i: int, j: int) -> float:
        k = j - i
        total = 0.0
        for f in range(d):
            s = prefix[f][j] - prefix[f][i]
            total += k - s * s / k
        return total

    penalty = penalty_factor * d * math.log(n)

    INF = float("inf")
    max_s = min(max_chapters, n // min_seg_weeks)
    dp = [[INF] * (n + 1) for _ in range(max_s + 1)]
    cut = [[-1] * (n + 1) for _ in range(max_s + 1)]
    dp[0][0] = 0.0
    for s in range(1, max_s + 1):
        for j in range(s * min_seg_weeks, n + 1):
            best, best_i = INF, -1
            for i in range((s - 1) * min_seg_weeks, j - min_seg_weeks + 1):
                prev = dp[s - 1][i]
                if prev == INF:
                    continue
                cand = prev + cost(i, j)
                if cand < best:
                    best, best_i = cand, i
            dp[s][j] = best
            cut[s][j] = best_i

    best_s, best_score = 1, dp[1][n]
    for s in range(2, max_s + 1):
        score = dp[s][n] + penalty * (s - 1)
        if score < best_score:
            best_s, best_score = s, score

    # 回溯各段起始周下标
    starts = [0] * best_s
    j = n
    for s in range(best_s, 0, -1):
        j = cut[s][j] if s > 1 else 0
        starts[s - 1] = j
    if starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])):
        return [0]
    return starts


def _new_week(start: int) -> Dict[str, Any]:
    def _side() -> Dict[str, Any]:
        return {
            "texts": [], "late": 0, "pos": 0, "neg": 0, "sentiment_n": 0,
            "intensities": [], "day_counts": [0] * 7, "shares": 0,
            "reply_chances": 0, "reply_hits": 0,
        }

    return {
        "start": start, "first_ts": None, "last_ts": None,
        "sides": {1: _side(), 0: _side()},
        "sessions": {1: 0, 0: 0}, "session_total": 0,
        "latency_secs": [],
    }


class RelationshipChapterService:
    """关系章节：章节检测 + 周级大五分布（读侧纯函数式编排）。

    实例内缓存：真实库 13 万条整算 ~7s，切页签回来不该重付——按
    「消息数 + 最新时间戳 + 口径版本」指纹缓存 payload，新消息落库
    或升版自动失效（纯统计可再生，不落库缓存表，KISS）。
    """

    def __init__(self):
        self._cache: Dict[int, Tuple[Tuple[int, int], dict]] = {}

    @staticmethod
    def _conv_fingerprint(conversation_id: int) -> Optional[Tuple[int, int]]:
        row = get_db().execute(
            "SELECT COUNT(*), MAX(timestamp) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if not row or not row[0]:
            return None
        return (int(row[0]), int(row[1] or 0))

    def get_chapters(self, conversation_id: int) -> dict:
        try:
            fingerprint = self._conv_fingerprint(conversation_id)
            cached = self._cache.get(int(conversation_id))
            if cached and cached[0] == fingerprint and fingerprint is not None:
                payload = cached[1]
            else:
                rows = self._fetch_text_rows(conversation_id)
                if len(rows) < MIN_TOTAL_TEXTS:
                    return {"ok": False, "reason": "insufficient_data",
                            "message": "文本消息不足，暂无法划分章节（需数周以上的对话积累）"}

                weeks = self._aggregate_weeks(rows)
                self._attach_aux(weeks, conversation_id)
                weekly_arrays = self._weekly_arrays(weeks)
                weekly_big5 = self._weekly_big5(weeks)
                features = self._chapter_features(weeks)
                starts = detect_chapters(features)
                chapters = self._build_chapters(
                    conversation_id, weeks, starts, features
                )

                from .big5_proxies import DIMENSION_LABELS

                payload = {
                    "ok": True,
                    "version": CHAPTERS_VERSION,
                    "span": {
                        "from_ts": weeks[0]["first_ts"], "to_ts": weeks[-1]["last_ts"],
                        "week_count": len(weeks), "week_seconds": WEEK_SECONDS,
                    },
                    "week_starts": [w["start"] for w in weeks],
                    "feature_labels": FEATURE_LABELS,
                    "weekly": {**weekly_arrays, "big5": weekly_big5},
                    "big5_labels": dict(DIMENSION_LABELS),
                    "chapters": chapters,
                }
                if fingerprint is not None:
                    self._cache[int(conversation_id)] = (fingerprint, payload)

            # 摘要状态每次现查（表轻，缓存外附加：摘要任务跑完无需失效章节缓存）；
            # chapters 逐章浅拷贝——摘要字段写副本，缓存对象不被调用方突变污染
            payload = dict(payload)
            payload["chapters"] = [dict(ch) for ch in payload["chapters"]]
            payload["summary"] = self._summary_status(int(conversation_id), payload["chapters"])
            return payload
        except Exception as exc:  # pragma: no cover - 桥层兜底日志
            logger.error("[关系章节] 计算失败: %s", exc, exc_info=True)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _summary_status(conversation_id: int, chapters: List[Dict[str, Any]]) -> dict:
        """章摘要就绪度 + 各章摘要文本（chapter_summaries 任务产物，纯读）。

        表缺失（未跑过摘要任务/旧库）静默降级为全 0。"""
        try:
            from .chapter_summaries import SUMMARY_VERSION, _summary_fp

            conn = get_db()
            month_row = conn.execute(
                "SELECT COUNT(*) FROM chapter_month_summaries"
                " WHERE conversation_id = ? AND version = ?",
                (conversation_id, SUMMARY_VERSION),
            ).fetchone()
            total_row = conn.execute(
                "SELECT COUNT(DISTINCT strftime('%Y-%m', m.timestamp, 'unixepoch',"
                " 'localtime')) FROM messages m"
                " WHERE m.conversation_id = ? AND m.message_type = 1"
                " AND m.content IS NOT NULL AND TRIM(m.content) != ''",
                (conversation_id,),
            ).fetchone()
            by_fp: Dict[str, dict] = {}
            for row in conn.execute(
                "SELECT fingerprint, summary_json FROM chapter_summaries"
                " WHERE conversation_id = ? AND version = ?",
                (conversation_id, SUMMARY_VERSION),
            ).fetchall():
                try:
                    parsed = json.loads(row[1])
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    by_fp[str(row[0])] = parsed
            for chapter in chapters:
                fp = _summary_fp(int(chapter["from_ts"]), int(chapter["to_ts"]))
                summary = by_fp.get(fp)
                if summary:
                    chapter["summary"] = str(summary.get("summary") or "")
                    chapter["phase"] = str(summary.get("phase") or "")
            return {
                "months_total": int(total_row[0] or 0),
                "months_ready": int(month_row[0] or 0),
                "chapters_ready": sum(1 for ch in chapters if ch.get("summary")),
            }
        except Exception as exc:
            logger.debug("[关系章节] 摘要状态降级: %s", exc)
            return {"months_total": 0, "months_ready": 0, "chapters_ready": 0}

    # ------------------------------------------------------------------
    # 周桶聚合
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_text_rows(conversation_id: int) -> List[Tuple]:
        """全会话文本消息 + 情感缓存联表，按时间升序一次拉齐。"""
        return get_db().execute(
            "SELECT m.is_sender, m.content, m.timestamp, sc.polarity, sc.intensity "
            "FROM messages m LEFT JOIN sentiment_cache sc ON sc.message_id = m.id "
            "WHERE m.conversation_id = ? AND m.message_type = 1 "
            "AND m.content IS NOT NULL AND TRIM(m.content) != '' "
            "ORDER BY m.timestamp ASC, m.id ASC",
            (conversation_id,),
        ).fetchall()

    @staticmethod
    def _aggregate_weeks(rows: List[Tuple]) -> List[Dict[str, Any]]:
        """行扫描进周桶；空周补零（冷却期本身是信号）；话题延续按周内
        「对方发言后本方 30 分钟内首条回应」口径（与大五基础层一致）。"""
        weeks: List[Dict[str, Any]] = []
        by_start: Dict[int, Dict[str, Any]] = {}
        last_peer_ts = {1: None, 0: None}  # 未被消费的对侧时间戳（按周重置）

        for raw in rows:
            is_sender = int(raw[0] or 0)
            content = raw[1]
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            text = (content or "").strip()
            ts = int(raw[2] or 0)
            if not text:
                continue
            start = _week_start(ts)
            week = by_start.get(start)
            if week is None:
                week = _new_week(start)
                by_start[start] = week
                weeks.append(week)
                last_peer_ts = {1: None, 0: None}
            week["first_ts"] = ts if week["first_ts"] is None else min(week["first_ts"], ts)
            week["last_ts"] = ts if week["last_ts"] is None else max(week["last_ts"], ts)

            lt = time.localtime(ts)
            side = week["sides"][is_sender]
            side["texts"].append(text)
            side["day_counts"][lt.tm_wday] += 1
            if 0 <= lt.tm_hour < 6:
                side["late"] += 1
            peer = last_peer_ts[1 - is_sender]
            if peer is not None:
                side["reply_chances"] += 1
                if ts - peer <= 1800:
                    side["reply_hits"] += 1
            last_peer_ts[is_sender] = ts
            last_peer_ts[1 - is_sender] = None

            polarity = raw[3]
            if polarity is not None:
                side["sentiment_n"] += 1
                if int(polarity) == 1:
                    side["pos"] += 1
                elif int(polarity) == -1:
                    side["neg"] += 1
                side["intensities"].append(float(raw[4] or 0))

        if not weeks:
            return []
        # 补空周（首末之间的静默周保留为 0 消息周）
        filled, cursor = [], weeks[0]["start"]
        for week in weeks:
            while cursor < week["start"]:
                filled.append(_new_week(cursor))
                cursor += WEEK_SECONDS
            filled.append(week)
            cursor = week["start"] + WEEK_SECONDS
        return filled

    @staticmethod
    def _attach_aux(weeks: List[Dict[str, Any]], conversation_id: int) -> None:
        """分享密度（图片/视频/链接）、破冰会话、回复时延三个辅助源进周桶。"""
        by_start = {w["start"]: w for w in weeks}

        for is_sender, ts in get_db().execute(
            "SELECT is_sender, timestamp FROM messages "
            "WHERE conversation_id = ? AND (message_type IN (3, 43) "
            "OR (message_type = 1 AND content LIKE '%http%'))",
            (conversation_id,),
        ).fetchall():
            week = by_start.get(_week_start(int(ts or 0)))
            if week is not None:
                week["sides"][int(is_sender or 0)]["shares"] += 1

        for initiator, start_time in get_db().execute(
            "SELECT initiator, start_time FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall():
            week = by_start.get(_week_start(int(start_time or 0)))
            if week is None:
                continue
            side = 1 if str(initiator) == "user" else 0
            week["sessions"][side] += 1
            week["session_total"] += 1

        for reply_ts, latency in get_db().execute(
            "SELECT rm.timestamp, rt.response_time_seconds "
            "FROM response_times rt JOIN messages rm ON rm.id = rt.reply_message_id "
            "WHERE rt.conversation_id = ? AND rt.is_abnormal = 0 "
            "AND rt.response_time_seconds IS NOT NULL "
            "AND rt.response_time_seconds < ?",
            (conversation_id, LATENCY_CAP_SECONDS),
        ).fetchall():
            week = by_start.get(_week_start(int(reply_ts or 0)))
            if week is not None:
                week["latency_secs"].append(float(latency))

    # ------------------------------------------------------------------
    # 周级序列
    # ------------------------------------------------------------------

    @staticmethod
    def _weekly_arrays(weeks: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
        """章节特征与体量序列（供前端图表与章节统计直接消费）。"""
        texts_me, texts_other, pos_ratio, latency_hours = [], [], [], []
        for w in weeks:
            me, other = w["sides"][1], w["sides"][0]
            texts_me.append(len(me["texts"]))
            texts_other.append(len(other["texts"]))
            pos = me["pos"] + other["pos"]
            neg = me["neg"] + other["neg"]
            pos_ratio.append(round(pos / (pos + neg), 4) if (pos + neg) else None)
            secs = w["latency_secs"]
            latency_hours.append(
                round(sum(secs) / len(secs) / 3600, 2) if secs else None
            )
        return {
            "texts_me": texts_me,
            "texts_other": texts_other,
            "pos_ratio": pos_ratio,
            "latency_hours": latency_hours,
        }

    @staticmethod
    def _chapter_features(weeks: List[Dict[str, Any]]) -> List[List[float]]:
        """章节检测特征矩阵（与 FEATURE_LABELS 键序一致；缺失位以列均值中性填）。"""
        raw: Dict[str, List[Optional[float]]] = {}
        for key, _label in FEATURE_LABELS.items():
            raw[key] = []
        for w in weeks:
            me, other = w["sides"][1], w["sides"][0]
            total = len(me["texts"]) + len(other["texts"])
            pos = me["pos"] + other["pos"]
            neg = me["neg"] + other["neg"]
            raw["volume"].append(math.log1p(total))
            raw["other_share"].append(
                len(other["texts"]) / total if total else 0.5
            )
            raw["pos_ratio"].append(
                pos / (pos + neg) if (pos + neg) else None
            )
            secs = w["latency_secs"]
            raw["latency"].append(
                math.log1p(sum(secs) / len(secs) / 60) if secs else None
            )

        features: List[List[float]] = []
        means = {}
        for key, series in raw.items():
            present = [v for v in series if v is not None]
            means[key] = sum(present) / len(present) if present else 0.0
        for i in range(len(weeks)):
            features.append([
                raw[key][i] if raw[key][i] is not None else means[key]
                for key in FEATURE_LABELS
            ])
        return features

    def _weekly_big5(self, weeks: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[Any]]]:
        """逐周逐侧大五代理分（锚点插值 + 缺席重归一）；样本薄记 None。"""
        from .big5_proxies import DIMENSIONS

        keywords = self._empathy_keywords()
        out: Dict[str, Dict[str, List[Any]]] = {
            "me": {dim: [] for dim in DIMENSIONS},
            "other": {dim: [] for dim in DIMENSIONS},
        }
        for w in weeks:
            for side_key, side_flag in (("me", 1), ("other", 0)):
                scores = self._week_side_scores(w, side_flag, keywords)
                if scores is None:
                    for dim in DIMENSIONS:
                        out[side_key][dim].append(None)
                    continue
                for dim in DIMENSIONS:
                    item = scores.get(dim) or {}
                    out[side_key][dim].append(item.get("score"))
        return out

    @staticmethod
    def _empathy_keywords() -> List[str]:
        from .keyword_libraries import KeywordLibraries

        try:
            lib = KeywordLibraries()
            return lib.get_keywords(KeywordLibraries.EMPATHY) + lib.get_keywords(
                KeywordLibraries.SOOTHING
            )
        except Exception as exc:
            logger.warning("[关系章节] 词表加载失败，宜人性密度缺席: %s", exc)
            return []

    @staticmethod
    def _week_side_scores(
        week: Dict[str, Any], side_flag: int, keywords: List[str]
    ) -> Optional[Dict[str, Any]]:
        """单周单侧指标 → big5_proxies 合成；样本不足返回 None。"""
        from .big5_proxies import compute_big5_base
        from .personality_impression_service import (
            PersonalityImpressionService,
            _EMOJI_EXCLAIM_PATTERN,
        )

        side = week["sides"][side_flag]
        texts = side["texts"]
        if len(texts) < WEEKLY_MIN_SIDE_TEXTS:
            return None
        count = len(texts)

        day_counts = [c for c in side["day_counts"] if c > 0]
        if day_counts:
            day_mean = sum(day_counts) / len(day_counts)
            var = sum((c - day_mean) ** 2 for c in day_counts) / len(day_counts)
            daily_cv = math.sqrt(var) / day_mean if day_mean > 0 else None
        else:
            daily_cv = None

        intensities = side["intensities"]
        if intensities:
            imean = sum(intensities) / len(intensities)
            ivar = sum((v - imean) ** 2 for v in intensities) / len(intensities)
        else:
            ivar = None

        session_total = week["session_total"]
        emoji_hits = sum(
            1 for t in texts if _EMOJI_EXCLAIM_PATTERN.search(t)
        )
        empathy_hits = (
            sum(1 for t in texts if any(k in t for k in keywords))
            if keywords else 0
        )
        ttr, entropy = PersonalityImpressionService._lexical_indicators(
            texts[:WEEKLY_LEX_SAMPLE]
        )

        pos, neg = side["pos"], side["neg"]
        indicators = {
            "daily_avg": round(count / 7, 3),
            "icebreak_ratio": (
                round(week["sessions"][side_flag] / session_total, 4)
                if session_total else None
            ),
            "emoji_exclaim_density": round(emoji_hits / count, 4),
            "unanswered_rate": None,
            "daily_cv": round(daily_cv, 4) if daily_cv is not None else None,
            "topic_continuation": (
                round(side["reply_hits"] / side["reply_chances"], 4)
                if side["reply_chances"] else None
            ),
            "intensity_variance": round(ivar, 5) if ivar is not None else None,
            "negative_ratio": (
                round(neg / side["sentiment_n"], 4) if side["sentiment_n"] else None
            ),
            "late_night_ratio": round(side["late"] / count, 4),
            "revoke_rate": None,
            "pos_neg_ratio": (
                round(pos / (pos + neg), 4) if (pos + neg) else None
            ),
            "positive_response_rate": None,
            "empathy_density": (
                round(empathy_hits / count, 4) if keywords else None
            ),
            "ttr": ttr,
            "topic_entropy": entropy,
            "share_density": round(side["shares"] / count, 4),
        }
        return compute_big5_base(indicators)

    # ------------------------------------------------------------------
    # 章节组装
    # ------------------------------------------------------------------

    def _build_chapters(
        self,
        conversation_id: int,
        weeks: List[Dict[str, Any]],
        starts: List[int],
        features: List[List[float]],
    ) -> List[Dict[str, Any]]:
        """段统计 + 变化归因（相邻段特征均值差按全局 z 折算）+ 里程碑吸附。"""
        milestones = self._fetch_milestones(
            conversation_id, weeks[0]["first_ts"], weeks[-1]["last_ts"]
        )
        feature_std = {}
        for idx, key in enumerate(FEATURE_LABELS):
            col = [row[idx] for row in features]
            mean = sum(col) / len(col)
            var = sum((v - mean) ** 2 for v in col) / len(col)
            feature_std[key] = math.sqrt(var) if var > 1e-12 else 0.0

        chapters: List[Dict[str, Any]] = []
        for seg, (i0, i1) in enumerate(zip(starts, list(starts[1:]) + [len(weeks)])):
            seg_weeks = weeks[i0:i1]
            stats = self._segment_stats(seg_weeks)
            # 段首/尾可能是沉默期空周（first_ts=None）：跳过空周取首个非空锚点，
            # 全空段兜底周界——沉默章也必须有可显示的时间范围
            first_ts = next(
                (w["first_ts"] for w in seg_weeks if w["first_ts"] is not None),
                seg_weeks[0]["start"],
            )
            last_ts = next(
                (w["last_ts"] for w in reversed(seg_weeks) if w["last_ts"] is not None),
                seg_weeks[-1]["start"] + WEEK_SECONDS - 1,
            )
            chapter = {
                "index": seg,
                "week_index": i0,
                "week_end": i1,
                "from_ts": first_ts,
                "to_ts": last_ts,
                "stats": stats,
                "changes": [],
            }
            if seg > 0:
                changes = []
                for idx, key in enumerate(FEATURE_LABELS):
                    std = feature_std[key]
                    if not std:
                        continue
                    cur_mean = sum(row[idx] for row in features[i0:i1]) / (i1 - i0)
                    prev_mean = sum(row[idx] for row in features[starts[seg - 1]:i0]) / (i0 - starts[seg - 1])
                    delta = (cur_mean - prev_mean) / std
                    if abs(delta) >= CHANGE_Z_THRESHOLD:
                        changes.append({
                            "key": key,
                            "label": FEATURE_LABELS[key],
                            "direction": "up" if delta > 0 else "down",
                            "delta": round(delta, 2),
                        })
                chapter["changes"] = changes
            chapters.append(chapter)

        # 边界吸附里程碑（仅展示时间戳，周统计不动）
        for prev, cur in zip(chapters, chapters[1:]):
            boundary = weeks[cur["week_index"]]["start"]
            snapped = self._snap_to_milestone(milestones, boundary)
            if snapped is not None:
                prev["to_ts"] = snapped
                cur["from_ts"] = snapped
        return chapters

    @staticmethod
    def _segment_stats(seg_weeks: List[Dict[str, Any]]) -> Dict[str, Any]:
        texts = me = other = pos = neg = sentiment_n = 0
        latency: List[float] = []
        for w in seg_weeks:
            for flag, store in ((1, "me"), (0, "other")):
                side = w["sides"][flag]
                n = len(side["texts"])
                texts += n
                if flag == 1:
                    me += n
                else:
                    other += n
                pos += side["pos"]
                neg += side["neg"]
                sentiment_n += side["sentiment_n"]
            latency.extend(w["latency_secs"])
        return {
            "texts": texts,
            "me_texts": me,
            "other_texts": other,
            "other_share": round(other / texts, 4) if texts else None,
            "pos_ratio": round(pos / (pos + neg), 4) if (pos + neg) else None,
            "latency_hours": (
                round(sum(latency) / len(latency) / 3600, 2) if latency else None
            ),
            "weeks": len(seg_weeks),
        }

    @staticmethod
    def _fetch_milestones(
        conversation_id: int, from_ts: int, to_ts: int
    ) -> List[int]:
        """复用深分析的里程碑口径（首条/消息量关口/最长沉默），取时间戳列表。"""
        try:
            from .deep_analysis_service import DeepAnalysisService

            events = DeepAnalysisService()._build_milestones(
                conversation_id, from_ts, to_ts
            )
            return sorted(int(e["ts"]) for e in events if e.get("ts"))
        except Exception as exc:
            logger.warning("[关系章节] 里程碑读取失败，边界不做吸附: %s", exc)
            return []

    @staticmethod
    def _snap_to_milestone(
        milestones: List[int], boundary_ts: int
    ) -> Optional[int]:
        """±CHANGE_SNAP_DAYS 内最近的里程碑时间戳；无则不吸附。"""
        radius = CHANGE_SNAP_DAYS * 86400
        best, best_gap = None, radius + 1
        for ts in milestones:
            gap = abs(ts - boundary_ts)
            if gap < best_gap:
                best, best_gap = ts, gap
        return best if best_gap <= radius else None
