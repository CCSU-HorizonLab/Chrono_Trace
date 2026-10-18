"""时光深度：时间窗长期演变聚合（分桶情绪序列 / 词云演变 / 里程碑 / 情绪拐点）。

口径说明：
- 情绪桶聚合只读 sentiment_cache（与全面分析同一 ONNX 模型产物，天然同口径）。
  INNER JOIN 会丢掉没有情感数据的桶——这里用「全量文本桶计数 + 情感聚合桶」
  双查询合并补出 coverage：未覆盖桶 score=None 且 lowConfidence=True，
  msgCount 仍按全量文本消息计，前端可如实画出「有聊天但缺情感」的时段。
- 词云演变不走 preprocess_conversation（其 ANALYSIS_MESSAGE_LIMIT=50000 按
  时间升序截断，大会话后半窗会被整体截空），改按半窗直查并独立上限+等距抽样。
  整个模块按 message_preprocessed 覆盖率二选一口径（≥90% 用清洗缓存文本，
  否则统一用原始 content），绝不前后半窗混用。
- 好感度历史点只取当前口径（CALIBER_VERSION）行：历史只在全面分析完成时
  落点，是稀疏的「分析落点」而非每日快照，前端叠加时须注明。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db
from .analysis_service import AnalysisService, sentiment_bucket_expr
from .wordcloud_generator import WordCloudGenerator

import logging

logger = logging.getLogger(__name__)

# 桶口径/序列结构版本：分桶表达式或点位结构变化时 +1（payload 携带，
# 序列实时计算无缓存，版本主要用于前端兼容判断与文档口径记录）
DEEP_ANALYSIS_VERSION = 1

DEEP_BUCKET_GRANULARITIES = ("day", "week", "month", "year")

# 词云演变每半窗消息上限（超出等距抽样并标记 truncated）
DEEP_WORDCLOUD_HALF_LIMIT = 15000

# 判断「整个窗已有足够清洗缓存」可用清洗口径的覆盖率线
DEEP_PREPROCESSED_COVERAGE = 0.9

# 拐点参与门槛：样本过少/覆盖不足的桶不参与涨跌幅判定
DEEP_MIN_TURNING_BUCKET_MSGS = 30
DEEP_MIN_TURNING_COVERAGE = 0.8

# 桶低置信标记线（coverage 低于此值时 lowConfidence=True）
DEEP_LOW_COVERAGE_THRESHOLD = 0.6

# 默认消息量关口（可被调用方注入覆盖，便于测试）
DEEP_DEFAULT_MARKS = (1000, 5000, 10000, 50000, 100000)

# 海报 payload 常量
POSTER_TOP_WORDS = 12            # 每侧词条数
POSTER_QUOTE_COUNT = 3           # 金句条数（仅定向版消费）
POSTER_QUOTE_MIN_CHARS = 10      # 金句长度下限
POSTER_QUOTE_MAX_CHARS = 50      # 金句长度上限
POSTER_AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 头像转 base64 上限
POSTER_WORDCLOUD_SAMPLE = 2000   # top 词计算的消息抽样上限


class DeepAnalysisService:
    """时光深度聚合服务（无状态，实时计算不落缓存）"""

    def __init__(self):
        self._analysis_service: Optional[AnalysisService] = None
        self._wordcloud_gen: Optional[WordCloudGenerator] = None

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def get_deep_analysis(
        self,
        conversation_id: int,
        from_ts: int,
        to_ts: int,
        bucket: str = "week",
        marks: Tuple[int, ...] = DEEP_DEFAULT_MARKS,
    ) -> Dict[str, Any]:
        """组装时光深度 payload：分桶情绪序列 + 拐点 + 词云演变 + 里程碑 + 好感度落点"""
        if bucket not in DEEP_BUCKET_GRANULARITIES:
            return {"ok": False, "error": f"未知分桶粒度: {bucket}"}

        merged = self._merged_bucket_series(conversation_id, from_ts, to_ts, bucket)
        turning = self._sentiment_turning_points(merged)
        wordcloud = self._wordcloud_evolution(conversation_id, from_ts, to_ts)
        milestones = self._build_milestones(conversation_id, from_ts, to_ts, marks)
        affinity = self._affinity_history_points(conversation_id, from_ts, to_ts)

        return {
            "ok": True,
            "version": DEEP_ANALYSIS_VERSION,
            "bucket": bucket,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "buckets": merged,
            "turning_points": turning,
            "wordcloud_evolution": wordcloud,
            "milestones": milestones,
            "affinity_history": affinity,
        }

    # ------------------------------------------------------------------
    # 分桶情绪序列（全量计数 × 情感聚合 合并补覆盖率）
    # ------------------------------------------------------------------

    def _bucketed_message_counts(
        self, conversation_id: int, from_ts: int, to_ts: int, bucket: str
    ) -> Dict[str, int]:
        """按桶统计全量文本消息数（覆盖率的分母，与情感聚合的消息过滤同口径）"""
        expr = sentiment_bucket_expr(bucket)
        rows = get_db().execute(f"""
            SELECT {expr} AS b, COUNT(*) AS cnt
            FROM messages m
            WHERE m.conversation_id = ?
                AND m.message_type = 1
                AND m.timestamp BETWEEN ? AND ?
                AND m.content IS NOT NULL
                AND TRIM(m.content) != ''
            GROUP BY b ORDER BY b ASC
        """, (conversation_id, from_ts, to_ts)).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def _merged_bucket_series(
        self, conversation_id: int, from_ts: int, to_ts: int, bucket: str
    ) -> List[Dict[str, Any]]:
        """合并全量桶计数与情感聚合桶，产出带 coverage 的序列点。

        点位键沿用既有 timeseries 的驼峰命名（ts/score/userScore/otherScore/
        msgCount...），EmotionLineChart 可直接消费。
        """
        counts = self._bucketed_message_counts(conversation_id, from_ts, to_ts, bucket)
        if not counts:
            return []

        if self._analysis_service is None:
            self._analysis_service = AnalysisService()
        summary = self._analysis_service._build_sentiment_timeseries(
            conversation_id, from_ts, to_ts, bucket=bucket
        )
        sent_by_ts = {point["ts"]: point for point in summary["timeseries"]}

        merged: List[Dict[str, Any]] = []
        for label, total in counts.items():
            point = sent_by_ts.get(label)
            cached = int(point["msgCount"]) if point else 0
            coverage = round(cached / total, 3) if total else None
            merged.append({
                "ts": label,
                "score": point["score"] if point else None,
                "userScore": (point or {}).get("userScore"),
                "otherScore": (point or {}).get("otherScore"),
                "positive": int(point["positive"]) if point else 0,
                "neutral": int(point["neutral"]) if point else 0,
                "negative": int(point["negative"]) if point else 0,
                "msgCount": total,
                "cachedCount": cached,
                "coverage": coverage,
                "lowConfidence": (coverage is None or coverage < DEEP_LOW_COVERAGE_THRESHOLD),
            })
        return merged

    @staticmethod
    def _sentiment_turning_points(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """相邻桶最大涨/跌幅（情绪拐点）。样本过少或覆盖不足的桶不参与。"""
        eligible = [
            item for item in series
            if item.get("score") is not None
            and item.get("msgCount", 0) >= DEEP_MIN_TURNING_BUCKET_MSGS
            and (item.get("coverage") or 0) >= DEEP_MIN_TURNING_COVERAGE
        ]
        best = {"drop": None, "rise": None}
        for prev, curr in zip(eligible, eligible[1:]):
            delta = round(curr["score"] - prev["score"], 3)
            if delta == 0:
                continue
            direction = "drop" if delta < 0 else "rise"
            record = {
                "direction": direction,
                "from_ts": prev["ts"],
                "to_ts": curr["ts"],
                "from_score": prev["score"],
                "to_score": curr["score"],
                "delta": delta,
            }
            if best[direction] is None or abs(delta) > abs(best[direction]["delta"]):
                best[direction] = record
        # 先跌后涨的叙事顺序输出
        return [item for item in (best["drop"], best["rise"]) if item]

    # ------------------------------------------------------------------
    # 词云演变（前后半窗 × 双方/我/TA）
    # ------------------------------------------------------------------

    def _wordcloud_evolution(self, conversation_id: int, from_ts: int, to_ts: int) -> Dict[str, Any]:
        """前后半窗词云对比。整个模块按清洗覆盖率二选一口径，绝不混合。"""
        total = self._count_text_messages(conversation_id, from_ts, to_ts)
        if not total:
            return {
                "caliber": "none",
                "coverage_ratio": 0.0,
                "halves": [],
            }

        preprocessed_count = self._count_preprocessed_messages(conversation_id, from_ts, to_ts)
        coverage_ratio = preprocessed_count / total
        use_cleaned = coverage_ratio >= DEEP_PREPROCESSED_COVERAGE
        caliber = "cleaned" if use_cleaned else "raw"

        if self._wordcloud_gen is None:
            self._wordcloud_gen = WordCloudGenerator()

        mid_ts = (from_ts + to_ts) // 2
        halves = []
        for half_from, half_to in ((from_ts, mid_ts - 1), (mid_ts, to_ts)):
            rows = self._load_half_texts(conversation_id, half_from, half_to, use_cleaned)
            sampled_total = len(rows)
            truncated = sampled_total > DEEP_WORDCLOUD_HALF_LIMIT
            if truncated:
                step = (sampled_total - 1) / (DEEP_WORDCLOUD_HALF_LIMIT - 1)
                rows = [rows[round(i * step)] for i in range(DEEP_WORDCLOUD_HALF_LIMIT)]

            texts = {"all": [], "me": [], "other": []}
            for is_sender, content in rows:
                texts["all"].append(content)
                texts["me" if is_sender == 1 else "other"].append(content)

            halves.append({
                "from_ts": half_from,
                "to_ts": half_to,
                "truncated": truncated,
                "sampled": len(rows),
                "total": sampled_total,
                "words": {
                    key: self._wordcloud_gen.generate(values, top_n=30)
                    for key, values in texts.items()
                },
            })

        return {
            "caliber": caliber,
            "coverage_ratio": round(coverage_ratio, 3),
            "halves": halves,
        }

    @staticmethod
    def _count_text_messages(conversation_id: int, from_ts: int, to_ts: int) -> int:
        row = get_db().execute("""
            SELECT COUNT(*)
            FROM messages
            WHERE conversation_id = ?
                AND message_type = 1
                AND timestamp BETWEEN ? AND ?
                AND content IS NOT NULL
                AND TRIM(content) != ''
        """, (conversation_id, from_ts, to_ts)).fetchone()
        return int(row[0] or 0)

    @staticmethod
    def _count_preprocessed_messages(conversation_id: int, from_ts: int, to_ts: int) -> int:
        row = get_db().execute("""
            SELECT COUNT(*)
            FROM messages m
            INNER JOIN message_preprocessed mp ON mp.message_id = m.id
            WHERE m.conversation_id = ?
                AND m.message_type = 1
                AND m.timestamp BETWEEN ? AND ?
                AND m.content IS NOT NULL
                AND TRIM(m.content) != ''
                AND mp.cleaned_content IS NOT NULL
                AND TRIM(mp.cleaned_content) != ''
        """, (conversation_id, from_ts, to_ts)).fetchone()
        return int(row[0] or 0)

    @staticmethod
    def _load_half_texts(
        conversation_id: int, from_ts: int, to_ts: int, use_cleaned: bool
    ) -> List[Tuple[int, str]]:
        """取半窗 (is_sender, 文本) 有序对。清洗口径回表 message_preprocessed。"""
        if use_cleaned:
            rows = get_db().execute("""
                SELECT m.is_sender, mp.cleaned_content AS text
                FROM messages m
                INNER JOIN message_preprocessed mp ON mp.message_id = m.id
                WHERE m.conversation_id = ?
                    AND m.message_type = 1
                    AND m.timestamp BETWEEN ? AND ?
                    AND mp.cleaned_content IS NOT NULL
                    AND TRIM(mp.cleaned_content) != ''
                ORDER BY m.timestamp ASC, m.id ASC
            """, (conversation_id, from_ts, to_ts)).fetchall()
        else:
            rows = get_db().execute("""
                SELECT m.is_sender, m.content AS text
                FROM messages m
                WHERE m.conversation_id = ?
                    AND m.message_type = 1
                    AND m.timestamp BETWEEN ? AND ?
                    AND m.content IS NOT NULL
                    AND TRIM(m.content) != ''
                ORDER BY m.timestamp ASC, m.id ASC
            """, (conversation_id, from_ts, to_ts)).fetchall()
        return [(int(row[0]), row[1]) for row in rows]

    # ------------------------------------------------------------------
    # 里程碑（纯统计）
    # ------------------------------------------------------------------

    def _build_milestones(
        self,
        conversation_id: int,
        from_ts: int,
        to_ts: int,
        marks: Tuple[int, ...] = DEEP_DEFAULT_MARKS,
    ) -> List[Dict[str, Any]]:
        """关系里程碑：首条消息（全局/窗内）、消息量关口、窗内最长沉默期。"""
        events: List[Dict[str, Any]] = []

        row = get_db().execute(
            "SELECT MIN(timestamp) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        global_first = row[0] if row else None
        if global_first is not None:
            events.append({"kind": "first_message", "scope": "global", "ts": int(global_first)})
            if not (from_ts <= global_first <= to_ts):
                window_row = get_db().execute("""
                    SELECT MIN(timestamp) FROM messages
                    WHERE conversation_id = ? AND timestamp BETWEEN ? AND ?
                """, (conversation_id, from_ts, to_ts)).fetchone()
                if window_row and window_row[0] is not None:
                    events.append({
                        "kind": "first_message", "scope": "window", "ts": int(window_row[0]),
                    })

        # 消息量关口：全会话第 N 条消息落在窗内才报告
        for mark in marks:
            mark_row = get_db().execute("""
                SELECT timestamp FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp ASC, id ASC
                LIMIT 1 OFFSET ?
            """, (conversation_id, mark - 1)).fetchone()
            if mark_row and mark_row[0] is not None and from_ts <= mark_row[0] <= to_ts:
                events.append({"kind": "count_mark", "mark": int(mark), "ts": int(mark_row[0])})

        silence = self._longest_silence(conversation_id, from_ts, to_ts)
        if silence:
            events.append({
                "kind": "longest_silence",
                "ts": silence[0],
                "days": silence[2],
                "from_ts": silence[0],
                "to_ts": silence[1],
            })

        events.sort(key=lambda item: item["ts"])
        return events

    @staticmethod
    def _longest_silence(conversation_id: int, from_ts: int, to_ts: int):
        """窗内相邻消息最大间隔；不足 1 天不构成「沉默期」。返回 (起, 止, 天数)。"""
        rows = get_db().execute("""
            SELECT timestamp FROM messages
            WHERE conversation_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (conversation_id, from_ts, to_ts)).fetchall()
        timestamps = [int(row[0]) for row in rows]
        best_gap = 0
        best = None
        for prev, curr in zip(timestamps, timestamps[1:]):
            gap = curr - prev
            if gap > best_gap:
                best_gap = gap
                best = (prev, curr)
        if best is None or best_gap < 86400:
            return None
        return (best[0], best[1], round(best_gap / 86400, 1))

    # ------------------------------------------------------------------
    # 好感度历史落点
    # ------------------------------------------------------------------

    @staticmethod
    def _affinity_history_points(
        conversation_id: int, from_ts: int, to_ts: int
    ) -> Dict[str, Any]:
        """好感度历史点（只取当前口径行；秒级时间戳，前端展示时 ×1000）。"""
        from .affinity_analysis_service import AffinityAnalysisService

        caliber = AffinityAnalysisService.CALIBER_VERSION

        rows = get_db().execute("""
            SELECT overall_score, created_at
            FROM affinity_scores
            WHERE conversation_id = ? AND analysis_version = ?
                AND created_at BETWEEN ? AND ?
            ORDER BY created_at ASC
        """, (conversation_id, caliber, from_ts, to_ts)).fetchall()
        return {
            "caliber_version": caliber,
            "note": "好感度为全面分析完成时的落点，非每日快照",
            "points": [
                {"ts": int(row[1]), "score": round(float(row[0]), 1)} for row in rows
            ],
        }

    # ------------------------------------------------------------------
    # 分享海报 payload（前端 html2canvas 合成用）
    # ------------------------------------------------------------------

    def build_poster_payload(
        self, conversation_id: int, from_ts: int, to_ts: int, account_wxid: str = ""
    ) -> Dict[str, Any]:
        """组装海报数据。敏感字段（display_name/avatar/quotes）集中标注
        sensitive: True，前端公开/自我模板经投影函数消费，拿不到敏感字段。"""
        contact = self._poster_contact(conversation_id)
        stats = self._poster_stats(conversation_id, from_ts, to_ts)
        curve = self._merged_bucket_series(conversation_id, from_ts, to_ts, "week")
        top_words = self._poster_top_words(conversation_id, from_ts, to_ts)
        milestones = self._build_milestones(conversation_id, from_ts, to_ts)[:5]
        quotes = self._poster_quotes(conversation_id, from_ts, to_ts)
        big5 = self._poster_big5(conversation_id, account_wxid)

        return {
            "ok": True,
            "version": DEEP_ANALYSIS_VERSION,
            "conversation_id": int(conversation_id),
            "from_ts": int(from_ts),
            "to_ts": int(to_ts),
            "contact": {
                "display_name": contact["display_name"],
                "avatar": self._avatar_data_url(contact["avatar_path"]),
                "sensitive": True,
            },
            "stats": stats,
            "emotion_curve": {"bucket": "week", "points": curve},
            "top_words": top_words,
            "milestones": milestones,
            "quotes": {"items": quotes, "sensitive": True},
            "big5": big5,
            "generated_at": int(datetime.now().timestamp()),
        }

    @staticmethod
    def _poster_contact(conversation_id: int) -> Dict[str, Any]:
        """联系人显示名与头像路径（备注名 > 昵称 > username）。"""
        row = get_db().execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(c.display_name), ''), NULLIF(TRIM(ct.nickname), ''),
                         NULLIF(TRIM(ct.display_name), ''), '联系人'),
                COALESCE(NULLIF(TRIM(c.avatar_path), ''), NULLIF(TRIM(ct.avatar_path), ''))
            FROM conversations c
            LEFT JOIN contacts ct
                ON c.account_wxid = ct.account_wxid
               AND c.username = ct.username
            WHERE c.id = ?
            """,
            (conversation_id,),
        ).fetchone()
        if not row:
            return {"display_name": "联系人", "avatar_path": None}
        return {"display_name": str(row[0] or "联系人"), "avatar_path": (row[1] or None) and str(row[1])}

    @staticmethod
    def _avatar_data_url(path: Optional[str]) -> Optional[str]:
        """头像文件 → base64 data URL（html2canvas 要求，file:// 会污染画布）。
        超过 2MB 或读取失败返回 None（前端首字母占位）。"""
        if not path:
            return None
        try:
            from pathlib import Path

            file = Path(path)
            if not file.is_file() or file.stat().st_size > POSTER_AVATAR_MAX_BYTES:
                return None
            data = file.read_bytes()
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif data[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            else:
                return None
            import base64

            return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        except Exception as exc:
            logger.warning("[海报] 头像读取失败，使用占位: %s", exc)
            return None

    @staticmethod
    def _poster_stats(conversation_id: int, from_ts: int, to_ts: int) -> Dict[str, Any]:
        """窗内统计：双方消息数、活跃天数、跨度天数。"""
        row = get_db().execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN is_sender = 1 THEN 1 ELSE 0 END),
                   COUNT(DISTINCT DATE(timestamp, 'unixepoch', 'localtime'))
            FROM messages
            WHERE conversation_id = ? AND message_type = 1
                AND timestamp BETWEEN ? AND ?
                AND content IS NOT NULL AND TRIM(content) != ''
            """,
            (conversation_id, from_ts, to_ts),
        ).fetchone()
        total = int(row[0] or 0)
        self_count = int(row[1] or 0)
        active_days = int(row[2] or 0)
        span_days = max((to_ts - from_ts) // 86400, 1)
        return {
            "total": total,
            "self_count": self_count,
            "other_count": total - self_count,
            "active_days": active_days,
            "span_days": span_days,
        }

    def _poster_top_words(
        self, conversation_id: int, from_ts: int, to_ts: int
    ) -> Dict[str, Any]:
        """海报 top 词：双方/我/TA 各前 12（抽样 2000 条约束分词代价）。"""
        rows = get_db().execute(
            "SELECT is_sender, content FROM messages "
            "WHERE conversation_id = ? AND message_type = 1 "
            "AND timestamp BETWEEN ? AND ? AND content IS NOT NULL AND TRIM(content) != '' "
            "ORDER BY timestamp DESC LIMIT ?",
            (conversation_id, from_ts, to_ts, POSTER_WORDCLOUD_SAMPLE),
        ).fetchall()
        texts = {"all": [], "me": [], "other": []}

        def _decode(content) -> str:
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return str(content or "")

        for is_sender, content in rows:
            text = _decode(content)
            texts["all"].append(text)
            texts["me" if int(is_sender or 0) == 1 else "other"].append(text)

        if self._wordcloud_gen is None:
            self._wordcloud_gen = WordCloudGenerator()
        return {
            key: self._wordcloud_gen.generate(values, top_n=POSTER_TOP_WORDS)
            for key, values in texts.items()
        }

    @staticmethod
    def _poster_quotes(conversation_id: int, from_ts: int, to_ts: int) -> List[Dict[str, Any]]:
        """金句（仅定向版消费）：正向情感、10~50 字、时间分散取 3 条。"""
        rows = get_db().execute(
            """
            SELECT m.content, m.is_sender, m.timestamp
            FROM messages m
            JOIN sentiment_cache sc ON sc.message_id = m.id
            WHERE m.conversation_id = ? AND m.message_type = 1
                AND m.timestamp BETWEEN ? AND ?
                AND sc.polarity = 1
                AND LENGTH(m.content) BETWEEN ? AND ?
            ORDER BY m.timestamp ASC
            """,
            (conversation_id, from_ts, to_ts,
             POSTER_QUOTE_MIN_CHARS, POSTER_QUOTE_MAX_CHARS),
        ).fetchall()
        if not rows:
            return []
        picked: List[Any] = []
        step = max(len(rows) // POSTER_QUOTE_COUNT, 1)
        for index in range(0, len(rows), step):
            picked.append(rows[index])
            if len(picked) >= POSTER_QUOTE_COUNT:
                break

        def _decode(content) -> str:
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return str(content or "")

        return [
            {
                "text": _decode(row[0]).strip(),
                "is_sender": int(row[1] or 0) == 1,
                "ts": int(row[2] or 0),
            }
            for row in picked
        ]

    @staticmethod
    def _poster_big5(conversation_id: int, account_wxid: str) -> Dict[str, Any]:
        """读大五缓存（未生成返回 None 字段，不阻塞海报）。"""
        from .personality_impression_service import PersonalityImpressionService

        now = int(datetime.now().timestamp())
        service = PersonalityImpressionService()
        result: Dict[str, Any] = {}
        for subject in ("me", "other"):
            cached = None
            try:
                cached = service._load_cached(conversation_id, account_wxid, subject, now)
            except Exception as exc:
                logger.debug("[海报] 大五缓存读取失败: %s", exc)
            if cached:
                # 只带分数与标签，不带证据原文（公开版投影再兜一层）
                result[subject] = {
                    "source": cached.get("source"),
                    "scores": {
                        dim: {"score": item.get("score"), "label": item.get("label")}
                        for dim, item in (cached.get("scores") or {}).items()
                    },
                }
            else:
                result[subject] = None
        return result
