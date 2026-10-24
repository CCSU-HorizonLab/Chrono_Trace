"""时光深度：时间窗长期演变聚合（分桶情绪序列 / 词云演变 / 里程碑 / 情绪拐点）。

口径说明：
- 情绪桶聚合只读 sentiment_cache（与全面分析同一 ONNX 模型产物，天然同口径）。
  INNER JOIN 会丢掉没有情感数据的桶——这里用「全量文本桶计数 + 情感聚合桶」
  双查询合并补出 coverage：未覆盖桶 score=None 且 lowConfidence=True，
  msgCount 仍按全量文本消息计，前端可如实画出「有聊天但缺情感」的时段。
- 词云演变不走 preprocess_conversation（其 ANALYSIS_MESSAGE_LIMIT=50000 按
  时间升序截断，大会话后半段会被整体截空），改按分段直查并独立上限+等距抽样。
  整个模块按 message_preprocessed 覆盖率二选一口径（≥90% 用清洗缓存文本，
  否则统一用原始 content），绝不各段混用。
- 好感度历史点只取当前口径（CALIBER_VERSION）行：历史只在全面分析完成时
  落点，是稀疏的「分析落点」而非每日快照，前端叠加时须注明。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ...db.connection import get_db
from .analysis_service import AnalysisService, sentiment_bucket_expr
from .preprocessing.cleaning import CLEANING_VERSION
from .wordcloud_generator import WordCloudGenerator

import json
import logging

logger = logging.getLogger(__name__)

# 词云缓存版本：分词口径（单遍分词 all=me+other 精确和）或缓存结构变化时 +1
DEEP_WORDCLOUD_CACHE_VERSION = 2

# 桶口径/序列结构版本：分桶表达式或点位结构变化时 +1（payload 携带，
# 序列实时计算无缓存，版本主要用于前端兼容判断与文档口径记录）
# v2：词云演变 halves→segments（2~6 段可配，默认 4）
# v3：桶点补分侧全量计数 userMsgCount/otherMsgCount（互动量双柱数据源）
# v4：词面口径变更随行 bump——pos 白名单过滤（posseg 只留实词）+ 停用词
#     两轮扩表（词云/群摘要的词口径变了，v3 之后产生的词表不兼容）
# v5：分段语义换轨——词云/大五/里程碑从「窗口均分 N 段（word_segments 2~6）」
#     改为「全会话·章节边界分段」（chapter_spans，见 relationship_chapters）；
#     日期窗只剩情绪曲线一职，payload 增 chapter_spans
# 海报 story（milestones/chemistry）为纯加性字段，不触碰序列口径——不 +1
DEEP_ANALYSIS_VERSION = 5

DEEP_BUCKET_GRANULARITIES = ("day", "week", "month", "year")

# 词云演变每段消息上限（超出等距抽样并标记 truncated）
DEEP_WORDCLOUD_SEGMENT_LIMIT = 15000

# 判断「整个窗已有足够清洗缓存」可用清洗口径的覆盖率线
DEEP_PREPROCESSED_COVERAGE = 0.9

# 里程碑/沉默期与其他深度面板同口径：只数真实文本消息——图片/撤回/
# 系统消息不算「第 N 条」关口，也不该打断人际沉默期
_MILESTONE_TEXT_SQL = "message_type = 1 AND content IS NOT NULL AND TRIM(content) != ''"

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
        """组装时光深度 payload。

        C4 起分段语义统一为「全会话·章节边界」（chapter_spans）：词云/大五/
        里程碑不再受日期窗与 word_segments 影响；from/to/bucket 只服务情绪
        曲线（连续时间序列，窗口探索仍有意义）。
        """
        if bucket not in DEEP_BUCKET_GRANULARITIES:
            return {"ok": False, "error": f"未知分桶粒度: {bucket}"}

        from .relationship_chapters import chapter_spans

        chapter = chapter_spans(conversation_id)
        merged = self._merged_bucket_series(conversation_id, from_ts, to_ts, bucket)
        turning = self._sentiment_turning_points(merged)
        wordcloud = self._wordcloud_evolution(conversation_id, chapter["spans"])
        milestones = self._build_milestones(
            conversation_id, chapter["full_from"], chapter["full_to"], marks,
        )
        affinity = self._affinity_history_points(conversation_id, from_ts, to_ts)
        big5 = self._big5_evolution(conversation_id, chapter["spans"])

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
            "big5_evolution": big5,
            # 章节分段（全会话口径）：里程碑按章分组、面板标注「按章分段」用
            "chapter_spans": chapter["spans"],
            "chapters_ok": chapter["ok"],
        }

    # ------------------------------------------------------------------
    # 分桶情绪序列（全量计数 × 情感聚合 合并补覆盖率）
    # ------------------------------------------------------------------

    def _bucketed_message_counts(
        self, conversation_id: int, from_ts: int, to_ts: int, bucket: str
    ) -> Dict[str, Dict[str, int]]:
        """按桶统计全量文本消息数（覆盖率的分母，与情感聚合的消息过滤同口径）。

        计数按发送侧拆分（is_sender=1 我 / 0 对方），total 为桶内合计——
        互动量走势的分侧数据源，不依赖情感缓存。
        """
        expr = sentiment_bucket_expr(bucket)
        rows = get_db().execute(f"""
            SELECT {expr} AS b, m.is_sender AS side, COUNT(*) AS cnt
            FROM messages m
            WHERE m.conversation_id = ?
                AND m.message_type = 1
                AND m.timestamp BETWEEN ? AND ?
                AND m.content IS NOT NULL
                AND TRIM(m.content) != ''
            GROUP BY b, side ORDER BY b ASC
        """, (conversation_id, from_ts, to_ts)).fetchall()
        counts: Dict[str, Dict[str, int]] = {}
        for row in rows:
            entry = counts.setdefault(str(row[0]), {"total": 0, "user": 0, "other": 0})
            entry["total"] += int(row[2])
            if int(row[1]) == 1:
                entry["user"] += int(row[2])
            else:
                entry["other"] += int(row[2])
        return counts

    def _merged_bucket_series(
        self, conversation_id: int, from_ts: int, to_ts: int, bucket: str
    ) -> List[Dict[str, Any]]:
        """合并全量桶计数与情感聚合桶，产出带 coverage 的序列点。

        点位键沿用既有 timeseries 的驼峰命名（ts/score/userScore/otherScore/
        msgCount/userCount/otherCount...），EmotionLineChart 可直接消费。
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
        for label, entry in counts.items():
            total = entry["total"]
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
                # 分侧全量计数（互动量双柱数据源，不依赖情感缓存）
                "userMsgCount": entry["user"],
                "otherMsgCount": entry["other"],
                # 每侧已缓存计数（滚动平滑权重）；无缓存桶补 0
                "userCount": int((point or {}).get("userCount") or 0),
                "otherCount": int((point or {}).get("otherCount") or 0),
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
    # 词云演变（均分 N 段 × 双方/我/TA）
    # ------------------------------------------------------------------

    def _wordcloud_evolution(
        self,
        conversation_id: int,
        spans: List[Tuple[int, int]],
    ) -> Dict[str, Any]:
        """词云分段演变（章节边界分段，全会话口径）。

        整个会话按清洗覆盖率二选一口径，绝不各段混用。单段（章节检测
        不可用/单章会话）时 bump 对比无意义，前端按段数降级展示。
        """
        if not spans:
            return {"caliber": "none", "coverage_ratio": 0.0, "segments": []}
        full_from, full_to = spans[0][0], spans[-1][1]
        total = self._count_text_messages(conversation_id, full_from, full_to)
        if not total:
            return {
                "caliber": "none",
                "coverage_ratio": 0.0,
                "segments": [],
            }

        preprocessed_count = self._count_preprocessed_messages(conversation_id, full_from, full_to)
        coverage_ratio = preprocessed_count / total
        use_cleaned = coverage_ratio >= DEEP_PREPROCESSED_COVERAGE
        caliber = "cleaned" if use_cleaned else "raw"

        # 持久缓存：词云分词是深度页最重的一段（每段上限 15000 条 ×
        # posseg 全量切词），此前每次打开页面都重算。指纹 = 分段边界 +
        # 口径 + 消息总数 + 清洗口径版本，任一变化自然失效。
        cache_key = f"deep_wordcloud_v{DEEP_WORDCLOUD_CACHE_VERSION}_{conversation_id}"
        fingerprint = {
            "caliber": caliber,
            "total": total,
            "cleaning": CLEANING_VERSION,
            "spans": [list(span) for span in spans],
        }
        cached = self._load_wordcloud_cache(cache_key, fingerprint)
        if cached is not None:
            return cached

        if self._wordcloud_gen is None:
            self._wordcloud_gen = WordCloudGenerator()

        results = []
        for seg_from, seg_to in spans:
            rows, sampled_total = self._load_segment_texts(
                conversation_id, seg_from, seg_to, use_cleaned,
                limit=DEEP_WORDCLOUD_SEGMENT_LIMIT,
            )
            truncated = sampled_total > DEEP_WORDCLOUD_SEGMENT_LIMIT

            results.append({
                "from_ts": seg_from,
                "to_ts": seg_to,
                "truncated": truncated,
                "sampled": len(rows),
                "total": sampled_total,
                # 单遍分词三口径（all 恒等于 me+other 词频之和；此前
                # 三路各自拼接整段重切 3 遍）
                "words": self._wordcloud_gen.generate_by_side(
                    [(content, is_sender == 1) for is_sender, content in rows],
                    top_n=30,
                ),
            })

        payload = {
            "caliber": caliber,
            "coverage_ratio": round(coverage_ratio, 3),
            "segments": results,
        }
        self._save_wordcloud_cache(cache_key, payload, fingerprint)
        return payload

    @staticmethod
    def _load_wordcloud_cache(cache_key: str, fingerprint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            row = get_db().execute(
                "SELECT value FROM settings WHERE key = ?", (cache_key,)
            ).fetchone()
            if not row:
                return None
            cached = json.loads(row[0])
            if cached.get("fingerprint") != fingerprint:
                return None
            payload = cached.get("payload")
            return payload if isinstance(payload, dict) and payload.get("segments") else None
        except Exception as exc:
            logger.debug("[时光深度] 词云缓存读取失败(忽略): %s", exc)
            return None

    @staticmethod
    def _save_wordcloud_cache(cache_key: str, payload: Dict[str, Any], fingerprint: Dict[str, Any]) -> None:
        try:
            get_db().execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (cache_key, json.dumps({"fingerprint": fingerprint, "payload": payload}, ensure_ascii=False)),
            )
            get_db().commit()
        except Exception as exc:
            logger.debug("[时光深度] 词云缓存写入失败(忽略): %s", exc)

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
    def _load_segment_texts(
        conversation_id: int, from_ts: int, to_ts: int, use_cleaned: bool,
        limit: int = 0,
    ) -> Tuple[List[Tuple[int, str]], int]:
        """取一段 (is_sender, 文本) 有序对与真实总数。清洗口径回表 message_preprocessed。

        limit>0 且超出时在 SQL 侧等距抽样：大会话几十万行不再整体搬过
        进程边界，Python 只接收 ≤limit 行；truncated 由调用方按总数判定。
        """
        if use_cleaned:
            base_sql = """
                FROM messages m
                INNER JOIN message_preprocessed mp ON mp.message_id = m.id
                WHERE m.conversation_id = ?
                    AND m.message_type = 1
                    AND m.timestamp BETWEEN ? AND ?
                    AND mp.cleaned_content IS NOT NULL
                    AND TRIM(mp.cleaned_content) != ''
            """
            select_cols = "m.is_sender, mp.cleaned_content AS text"
        else:
            base_sql = """
                FROM messages m
                WHERE m.conversation_id = ?
                    AND m.message_type = 1
                    AND m.timestamp BETWEEN ? AND ?
                    AND m.content IS NOT NULL
                    AND TRIM(m.content) != ''
            """
            select_cols = "m.is_sender, m.content AS text"
        params: Tuple[Any, ...] = (conversation_id, from_ts, to_ts)

        total = int(get_db().execute(
            f"SELECT COUNT(*) {base_sql}", params
        ).fetchone()[0] or 0)
        if not total:
            return [], 0

        if limit and total > limit:
            # Bresenham 取模等距取「恰 limit 行」：rn*limit 对 total 取模
            # 落在 [0, limit) 的行恰为 limit 条且均匀分布。步长取模
            # （ceil(total/limit) 后 rn%%step）在 total/limit 略超整数时会
            # 明显欠采——1001/500 步长 3 只取到 333 行，浪费一半采样预算
            rows = get_db().execute(f"""
                SELECT is_sender, text FROM (
                    SELECT {select_cols},
                           ROW_NUMBER() OVER (ORDER BY m.timestamp ASC, m.id ASC) AS rn
                    {base_sql}
                ) WHERE (rn * ?) % ? < ?
                ORDER BY rn ASC
            """, params + (limit, total, limit)).fetchall()
            return [(int(row[0]), row[1]) for row in rows], total

        rows = get_db().execute(
            f"SELECT {select_cols} {base_sql} ORDER BY m.timestamp ASC, m.id ASC",
            params,
        ).fetchall()
        return [(int(row[0]), row[1]) for row in rows], total

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
            f"SELECT MIN(timestamp) FROM messages "
            f"WHERE conversation_id = ? AND {_MILESTONE_TEXT_SQL}",
            (conversation_id,),
        ).fetchone()
        global_first = row[0] if row else None
        if global_first is not None:
            events.append({"kind": "first_message", "scope": "global", "ts": int(global_first)})
            if not (from_ts <= global_first <= to_ts):
                window_row = get_db().execute(f"""
                    SELECT MIN(timestamp) FROM messages
                    WHERE conversation_id = ? AND timestamp BETWEEN ? AND ?
                      AND {_MILESTONE_TEXT_SQL}
                """, (conversation_id, from_ts, to_ts)).fetchone()
                if window_row and window_row[0] is not None:
                    events.append({
                        "kind": "first_message", "scope": "window", "ts": int(window_row[0]),
                    })

        # 消息量关口：全会话第 N 条文本消息落在窗内才报告
        for mark in marks:
            mark_row = get_db().execute(f"""
                SELECT timestamp FROM messages
                WHERE conversation_id = ? AND {_MILESTONE_TEXT_SQL}
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
        """窗内相邻消息最大间隔；不足 1 天不构成「沉默期」。返回 (起, 止, 天数)。

        LAG 窗口函数在库内求相邻间隔，只回最大一行——不把全窗时间戳
        搬进 Python（大会话数十万行的内存与反序列化热点）。并列最大取
        最早一对（curr 升序决胜），与逐对扫描语义一致。只数文本消息：
        系统消息（撤回提示等）不该打断真实的人际沉默。
        """
        row = get_db().execute(f"""
            SELECT prev, curr FROM (
                SELECT timestamp AS curr,
                       LAG(timestamp) OVER (ORDER BY timestamp ASC) AS prev
                FROM messages
                WHERE conversation_id = ? AND timestamp BETWEEN ? AND ?
                  AND {_MILESTONE_TEXT_SQL}
            ) WHERE prev IS NOT NULL
            ORDER BY curr - prev DESC, curr ASC
            LIMIT 1
        """, (conversation_id, from_ts, to_ts)).fetchone()
        if row is None:
            return None
        best_gap = int(row[1]) - int(row[0])
        if best_gap < 86400:
            return None
        return (int(row[0]), int(row[1]), round(best_gap / 86400, 1))

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
            "note": "好感度为全面分析完成时的落点，非每日快照；虚线只连落点示意方向",
            "points": [
                {"ts": int(row[1]), "score": round(float(row[0]), 1)} for row in rows
            ],
        }

    def _big5_evolution(
        self, conversation_id: int, spans: List[Tuple[int, int]]
    ) -> Dict[str, Any]:
        """双方大五随章节段演变（本地统计层，custom 窗缓存；AI 增强走 enhance 端点）。

        与词云演变共用章节分段；每段独立 get_impressions，样本过薄
        （<30 条/侧）该侧为 None；单段失败降级不炸整个 payload。
        """
        from .personality_impression_service import BIG5_MIN_MESSAGES, PersonalityImpressionService

        service = PersonalityImpressionService()
        series: List[Dict[str, Any]] = []
        for seg_from, seg_to in spans:
            entry: Dict[str, Any] = {"from_ts": seg_from, "to_ts": seg_to, "me": None, "other": None}
            if seg_to < seg_from:
                entry["error"] = "空段"
                series.append(entry)
                continue
            try:
                result = service.get_impressions(conversation_id, from_ts=seg_from, to_ts=seg_to)
                subjects = (result or {}).get("subjects") or {}
                entry["me"] = subjects.get("me")
                entry["other"] = subjects.get("other")
            except Exception as exc:
                logger.warning("[Big5演变] 段计算失败降级: %s", exc)
                entry["error"] = "本段计算失败"
            series.append(entry)
        return {
            "segments": len(spans),
            "min_messages": BIG5_MIN_MESSAGES,
            "series": series,
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
        quotes = self._poster_quotes(conversation_id, from_ts, to_ts)
        big5 = self._poster_big5(conversation_id, account_wxid, from_ts, to_ts)

        # 故事化分镜数据：里程碑复用深度页签口径；默契统计独立直查、逐字段
        # 降级 None（前端 v-if 跳分镜）。核心分镜零依赖分析产物——未跑分析
        # 的库也能出开场大数字/时间线/深夜/峰值日
        story = {
            "milestones": self._build_milestones(conversation_id, from_ts, to_ts),
            "chemistry": self._poster_chemistry(conversation_id, from_ts, to_ts),
        }

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
            "quotes": {"items": quotes, "sensitive": True},
            "big5": big5,
            "story": story,
            "generated_at": int(datetime.now().timestamp()),
        }

    @staticmethod
    def _poster_contact(conversation_id: int) -> Dict[str, Any]:
        """联系人显示名与头像路径（备注名 > 昵称 > 会话显示名；contacts 无 display_name 列）。"""
        row = get_db().execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(ct.remark), ''), NULLIF(TRIM(ct.nickname), ''),
                         NULLIF(TRIM(c.display_name), ''), '联系人'),
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

    @staticmethod
    def _poster_chemistry(conversation_id: int, from_ts: int, to_ts: int) -> Dict[str, Any]:
        """默契统计（故事分镜数据源）：深夜档/峰值日/回复速度/主动发起。

        每字段独立降级 None——reply_stats 与 initiator 依赖预处理产物，
        未分析的库常态缺席，前端 v-if 跳过对应分镜；消息口径与
        _poster_stats 同源（message_type=1 且非空文本、窗内、本地时区）。
        """
        chemistry: Dict[str, Any] = {}

        # 深夜档（本地 0~5 点）
        row = get_db().execute(
            f"""
            SELECT COUNT(*), SUM(CASE WHEN is_sender = 1 THEN 1 ELSE 0 END)
            FROM messages
            WHERE conversation_id = ? AND timestamp BETWEEN ? AND ?
                AND {_MILESTONE_TEXT_SQL}
                AND CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER)
                    BETWEEN 0 AND 5
            """,
            (conversation_id, from_ts, to_ts),
        ).fetchone()
        late_count = int(row[0] or 0)
        late_self = int(row[1] or 0)
        chemistry["late_night"] = (
            {"count": late_count, "self_count": late_self,
             "other_count": late_count - late_self}
            if late_count else None
        )

        # 峰值日：窗内消息最多的一天（并列取更早）
        row = get_db().execute(
            f"""
            SELECT DATE(timestamp, 'unixepoch', 'localtime'), COUNT(*),
                   SUM(CASE WHEN is_sender = 1 THEN 1 ELSE 0 END)
            FROM messages
            WHERE conversation_id = ? AND timestamp BETWEEN ? AND ?
                AND {_MILESTONE_TEXT_SQL}
            GROUP BY DATE(timestamp, 'unixepoch', 'localtime')
            ORDER BY COUNT(*) DESC, DATE(timestamp, 'unixepoch', 'localtime') ASC
            LIMIT 1
            """,
            (conversation_id, from_ts, to_ts),
        ).fetchone()
        chemistry["peak_day"] = (
            {"date": str(row[0]), "count": int(row[1] or 0),
             "self_count": int(row[2] or 0),
             "other_count": int(row[1] or 0) - int(row[2] or 0)}
            if row else None
        )

        # 回复速度 / 主动发起：依赖预处理产物，缺席为 None 是常态
        chemistry["reply_stats"] = DeepAnalysisService._poster_reply_stats(
            conversation_id, from_ts, to_ts
        )
        rows = get_db().execute(
            """
            SELECT initiator, COUNT(*)
            FROM sessions
            WHERE conversation_id = ? AND start_time BETWEEN ? AND ?
            GROUP BY initiator
            """,
            (conversation_id, from_ts, to_ts),
        ).fetchall()
        if rows:
            counts = {str(r[0]): int(r[1] or 0) for r in rows}
            user_sessions = counts.get("user", 0)
            total_sessions = sum(counts.values())
            chemistry["initiator"] = {
                "user_sessions": user_sessions,
                "other_sessions": total_sessions - user_sessions,
                "user_ratio": (
                    user_sessions / total_sessions if total_sessions else None
                ),
            }
        else:
            chemistry["initiator"] = None
        return chemistry

    @staticmethod
    def _poster_reply_stats(
        conversation_id: int, from_ts: int, to_ts: int
    ) -> Optional[Dict[str, Any]]:
        """回复速度（response_times 预处理产物）：回消息落窗、分侧按回消息
        归属，剔除异常值与 NULL。中位数 SQLite 无 MEDIAN，按序取中位段
        （偶数取两值均值）。无数据返回 None。"""
        row = get_db().execute(
            """
            SELECT COUNT(*), AVG(rt.response_time_seconds),
                   AVG(CASE WHEN m.is_sender = 1 THEN rt.response_time_seconds END),
                   AVG(CASE WHEN m.is_sender = 0 THEN rt.response_time_seconds END)
            FROM response_times rt
            JOIN messages m ON m.id = rt.reply_message_id
            WHERE rt.conversation_id = ? AND m.timestamp BETWEEN ? AND ?
                AND rt.is_abnormal = 0 AND rt.response_time_seconds IS NOT NULL
            """,
            (conversation_id, from_ts, to_ts),
        ).fetchone()
        count = int(row[0] or 0)
        if not count:
            return None
        mid_rows = get_db().execute(
            """
            SELECT rt.response_time_seconds
            FROM response_times rt
            JOIN messages m ON m.id = rt.reply_message_id
            WHERE rt.conversation_id = ? AND m.timestamp BETWEEN ? AND ?
                AND rt.is_abnormal = 0 AND rt.response_time_seconds IS NOT NULL
            ORDER BY rt.response_time_seconds
            LIMIT 2 OFFSET ?
            """,
            (conversation_id, from_ts, to_ts, (count - 1) // 2),
        ).fetchall()
        mid_values = [float(r[0]) for r in mid_rows if r[0] is not None]
        if len(mid_values) == 2 and count % 2 == 0:
            median = sum(mid_values) / 2
        elif mid_values:
            median = mid_values[0]
        else:
            median = None
        return {
            "count": count,
            "avg": round(float(row[1] or 0.0), 1),
            "median": round(median, 1) if median is not None else None,
            "self_avg": round(float(row[2]), 1) if row[2] is not None else None,
            "other_avg": round(float(row[3]), 1) if row[3] is not None else None,
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
    def _poster_big5(conversation_id: int, account_wxid: str, from_ts: int, to_ts: int) -> Dict[str, Any]:
        """读大五缓存（未生成返回 None 字段，不阻塞海报）。

        窗口与海报其余分镜同口径（from_ts/to_ts）：优先读该窗缓存，
        miss 时现算本地统计层（纯 SQL 零 LLM）——海报页头印的是窗口
        日期范围，大五不能再默默用全会话档冒充窗口结论。
        """
        from .personality_impression_service import (
            PersonalityImpressionService, _normalize_window,
        )

        now = int(datetime.now().timestamp())
        service = PersonalityImpressionService()
        window = _normalize_window(from_ts, to_ts)
        result: Dict[str, Any] = {}
        for subject in ("me", "other"):
            cached = None
            try:
                cached = service._load_cached(conversation_id, account_wxid, subject, now, window=window)
            except Exception as exc:
                logger.debug("[海报] 大五缓存读取失败: %s", exc)
            if cached is None and window[0] == "custom":
                try:
                    computed = service.get_impressions(
                        conversation_id, account_wxid, from_ts=from_ts, to_ts=to_ts
                    )
                    cached = (computed or {}).get("subjects", {}).get(subject)
                except Exception as exc:
                    logger.debug("[海报] 大五窗口现算失败: %s", exc)
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
