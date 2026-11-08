"""年度报告 / 纪念册数据服务（docs/product-redesign-2026-11.md §6.2）。

「我们的 2026」与任意区间纪念册共用一个窗口 payload：页面序列
封面（温度+天数）→ 总量 → 词云 → 专属梗 → 表情 → 里程碑 → 签名，
数据全部来自现有引擎聚合——统计/默契/top 词/里程碑复用 deep 海报
聚合器，表情页走 emoji_stats 窗口扫描，节奏（早安晚安）走
pulse_metrics.greeting_rhythm，温度读好感度缓存（未分析降级 None）。

敏感边界与海报同构：display_name/avatar 集中在 contact（sensitive
标注），前端公开版经 sanitizeReportForPublic 白名单投影，类型层
拿不到敏感字段。

专属梗挖掘（两段式，确定性）：
1. 按时间序等距抽样（同海报 top 词口径，约 2000 条上限）jieba 分词，
   相邻实词组成 2-3 词短语（拼接后 2~8 字）为候选，样本内出现 ≥5 次；
2. 候选短语回窗 SQL LIKE 精确计数（分侧 + 出现在多少条消息），
   总命中 ≥8 次入榜，按次数取 Top 10。抽样只用于圈候选，入榜数字
   是全窗精确值——报告里印的「说了 N 次」不掺水分。
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REPORT_VERSION = 1

# 专属梗挖掘参数
REPORT_MEME_SAMPLE = 2000  # 候选挖掘的等距抽样上限（与海报 top 词同量级）
REPORT_MEME_MIN_SAMPLE_HITS = 5  # 样本内出现次数门槛（圈候选）
REPORT_MEME_MIN_TOTAL = 8  # 全窗精确计数门槛（入榜 + 公开版安全冗余）
REPORT_MEME_TOP = 10
REPORT_MEME_CANDIDATES = 24  # 送精确计数的候选数上限

REPORT_EMOJI_TOP = 8  # 表情页每侧 Top 榜长度（unicode+内置合并）


def _like_escape(text: str) -> str:
    """LIKE 通配符转义（配 ESCAPE '\\' 子句）。"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ReportService:
    """组装年度报告 / 纪念册 payload（窗口口径，无缓存按需现算）。"""

    def build_report_payload(
        self, conversation_id: int, from_ts: int, to_ts: int, account_wxid: str = ""
    ) -> Dict[str, Any]:
        from .deep_analysis_service import DeepAnalysisService

        deep = DeepAnalysisService()
        stats = deep._poster_stats(conversation_id, from_ts, to_ts)
        if not stats["total"]:
            return {"ok": False, "error": "所选区间没有可统计的聊天消息"}

        contact = deep._poster_contact(conversation_id)
        story = {
            "milestones": deep._build_milestones(conversation_id, from_ts, to_ts),
            "chemistry": deep._poster_chemistry(conversation_id, from_ts, to_ts),
        }
        report = {
            "chars": self._window_chars(conversation_id, from_ts, to_ts),
            "temperature": self._temperature(conversation_id),
            "memes": self._mine_memes(conversation_id, from_ts, to_ts),
            "emoji": self._window_emoji(conversation_id, from_ts, to_ts),
            "rhythm": self._rhythm(conversation_id, from_ts, to_ts),
            "streak_days": deep._longest_active_streak(conversation_id, from_ts, to_ts, None),
        }
        return {
            "ok": True,
            "kind": "report",
            "version": REPORT_VERSION,
            "conversation_id": int(conversation_id),
            "from_ts": int(from_ts),
            "to_ts": int(to_ts),
            "contact": {
                "display_name": contact["display_name"],
                "avatar": DeepAnalysisService._avatar_data_url(contact["avatar_path"]),
                "sensitive": True,
            },
            "stats": stats,
            "top_words": deep._poster_top_words(conversation_id, from_ts, to_ts),
            "story": story,
            "report": report,
            "generated_at": int(time.time()),
        }

    # ------------------------------------------------------------------
    # 总量页素材
    # ------------------------------------------------------------------

    @staticmethod
    def _window_chars(conversation_id: int, from_ts: int, to_ts: int) -> int:
        """窗内字数（文本消息 content 字符数总和，自然日窗口口径同 stats）。"""
        from ...db.connection import get_db

        row = get_db().execute(
            """
            SELECT SUM(LENGTH(content))
            FROM messages
            WHERE conversation_id = ? AND message_type = 1
                AND timestamp BETWEEN ? AND ?
                AND content IS NOT NULL AND TRIM(content) != ''
            """,
            (conversation_id, from_ts, to_ts),
        ).fetchone()
        return int(row[0] or 0)

    @staticmethod
    def _temperature(conversation_id: int) -> Optional[Dict[str, Any]]:
        """封面关系温度：好感度历史表最新总分 + 分段话术（与脉搏折线同源
        的轻量读法；未分析降级 None，封面只讲天数——报告不应因没跑过
        分析而拒发）。"""
        from ...db.connection import get_db
        from .pulse_metrics import temperature_label

        try:
            row = get_db().execute(
                """
                SELECT overall_score FROM affinity_scores
                WHERE conversation_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        except Exception as exc:
            logger.debug("[报告] 好感度读取失败，封面温度降级: %s", exc)
            return None
        if not row or row[0] is None:
            return None
        score = float(row[0])
        return {"score": round(score), "label": temperature_label(score)}

    # ------------------------------------------------------------------
    # 专属梗挖掘
    # ------------------------------------------------------------------

    def _mine_memes(
        self, conversation_id: int, from_ts: int, to_ts: int
    ) -> List[Dict[str, Any]]:
        candidates = self._meme_candidates(conversation_id, from_ts, to_ts)
        verified: List[Dict[str, Any]] = []
        for phrase, _sample_hits in candidates:
            # 高频候选已入榜的子串/母串不再入榜（「笑死」与「笑死我了」取其一）
            if any(phrase in v["text"] or v["text"] in phrase for v in verified):
                continue
            count, me = self._count_phrase(conversation_id, from_ts, to_ts, phrase)
            if count >= REPORT_MEME_MIN_TOTAL:
                verified.append({"text": phrase, "count": count, "me": me, "ta": count - me})
            if len(verified) >= REPORT_MEME_TOP:
                break
        return verified

    @staticmethod
    def _sample_window_texts(
        conversation_id: int, from_ts: int, to_ts: int, limit: int
    ) -> List[str]:
        """按时间序等距抽样窗内文本（同海报 top 词口径：无近期偏倚、确定性）。"""
        from ...db.connection import get_db

        rows = get_db().execute(
            """
            WITH ranked AS (
                SELECT content,
                       ROW_NUMBER() OVER (ORDER BY timestamp, id) AS rn,
                       COUNT(*) OVER () AS total
                FROM messages
                WHERE conversation_id = ? AND message_type = 1
                  AND timestamp BETWEEN ? AND ?
                  AND content IS NOT NULL AND TRIM(content) != ''
            )
            SELECT content FROM ranked
            WHERE (rn - 1) % ((total + ? - 1) / ?) = 0
            """,
            (conversation_id, from_ts, to_ts, limit, limit),
        ).fetchall()
        return [r[0] if isinstance(r[0], str) else str(r[0] or "") for r in rows]

    def _meme_candidates(
        self, conversation_id: int, from_ts: int, to_ts: int
    ) -> List[Tuple[str, int]]:
        """抽样分词挖候选短语：相邻实词 2-3 词组合（拼接后 2~8 字），
        样本内 ≥5 次。只圈候选不报数——数字留给全窗精确计数。

        过滤复用词云的单一来源（停用词/标点/纯数字/重复字符），但不套
        词性白名单——内梗常被通用标注判成惯用语/叹词（「小笨蛋」标 l），
        白名单会把要挖的梗整词滤掉。
        """
        try:
            import jieba.posseg as pseg
        except ImportError:
            logger.warning("[报告] jieba 未安装，专属梗页跳过")
            return []

        from .wordcloud_generator import WordCloudGenerator

        gen = WordCloudGenerator()
        texts = self._sample_window_texts(
            conversation_id, from_ts, to_ts, REPORT_MEME_SAMPLE
        )
        counter: Counter = Counter()

        def _accept(word: str) -> bool:
            w = word.strip()
            return (
                2 <= len(w) <= 8
                and w not in gen.stopwords
                and not w.isdigit()
                and not gen._is_punctuation(w)
                and not gen._is_repeated_char(w)
            )

        def _emit(run: List[str]) -> None:
            for n in (2, 3):
                for i in range(len(run) - n + 1):
                    phrase = "".join(run[i : i + n])
                    if 2 <= len(phrase) <= 8:
                        counter[phrase] += 1

        for raw in texts:
            run: List[str] = []
            for pair in pseg.cut(gen._prepare_text(raw)):
                if _accept(pair.word):
                    run.append(pair.word.strip())
                else:
                    # 过滤词是边界：两边的词不相邻，不拼短语
                    if len(run) > 1:
                        _emit(run)
                    run = []
            if len(run) > 1:
                _emit(run)

        return [
            (phrase, hits)
            for phrase, hits in counter.most_common(REPORT_MEME_CANDIDATES)
            if hits >= REPORT_MEME_MIN_SAMPLE_HITS
        ]

    @staticmethod
    def _count_phrase(
        conversation_id: int, from_ts: int, to_ts: int, phrase: str
    ) -> Tuple[int, int]:
        """短语全窗精确计数：出现在多少条文本消息里（含该短语的消息数），
        附我方条数。LIKE 通配符已转义。"""
        from ...db.connection import get_db

        row = get_db().execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN is_sender = 1 THEN 1 ELSE 0 END)
            FROM messages
            WHERE conversation_id = ? AND message_type = 1
                AND timestamp BETWEEN ? AND ?
                AND content LIKE ? ESCAPE '\\'
            """,
            (conversation_id, from_ts, to_ts, f"%{_like_escape(phrase)}%"),
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    # ------------------------------------------------------------------
    # 表情页 / 节奏
    # ------------------------------------------------------------------

    @staticmethod
    def _window_emoji(conversation_id: int, from_ts: int, to_ts: int) -> Optional[Dict[str, Any]]:
        """表情页素材：emoji_stats 窗口扫描（不落缓存），每侧 unicode+内置
        合并 Top 榜 + 自定义表情总次 + 高峰时辰话术。窗口无表情返回 None。"""
        from .emoji_stats_service import collect_emoji_stats

        try:
            snap = collect_emoji_stats(conversation_id, from_ts, to_ts)
        except Exception as exc:
            logger.warning("[报告] 表情窗口统计失败: %s", exc)
            return None

        def _merged(side: str) -> List[Dict[str, Any]]:
            items = [
                {"key": item["key"], "kind": kind, "count": item["count"]}
                for kind in ("unicode", "builtin")
                for item in snap[f"top_{side}"].get(kind, [])
            ]
            items.sort(key=lambda x: -x["count"])
            return items[:REPORT_EMOJI_TOP]

        top_me, top_ta = _merged("me"), _merged("ta")
        if not top_me and not top_ta and not snap["custom_wall"]:
            return None
        anonymous = snap["custom_anonymous"]
        custom_count = (
            sum(item["count"] for item in snap["custom_wall"])
            + anonymous.get("me", 0)
            + anonymous.get("ta", 0)
        )
        return {
            "top_me": top_me,
            "top_ta": top_ta,
            "custom_count": custom_count,
            "peak_label": snap.get("rhythm_label") or "",
        }

    @staticmethod
    def _rhythm(conversation_id: int, from_ts: int, to_ts: int) -> Dict[str, int]:
        """节奏页素材：早安晚安天数（§6.5，与本月速览同口径单一来源）。"""
        from .pulse_metrics import greeting_rhythm

        return greeting_rhythm(conversation_id, from_ts, to_ts)
