"""表情包统计与博物馆（docs/product-redesign-2026-11.md §6.1）。

数据源是 messages.content 原文（decode_message_content 对可打印 str 原样
保留），三类提取：
- unicode：文本内 Unicode emoji（含 ZWJ 序列/肤色修饰/keycap，FE0F 归一合并）
- builtin：`[呲牙]` 式文本占位——词表复用 cleaning.EMOJI_PLACEHOLDER_WORDS
  （单一来源，清洗与统计同口径）
- custom：message_type=47 表情消息。content 含 32 位 hex（XML md5 属性或
  裸 hex）按 md5 聚合；已是 `[表情]` 占位（V4 库压缩通道解码不出原文）落
  匿名桶——至少保留「发了自定义表情」的次数与节奏。

缓存走 settings 快照（emoji_stats_v1_{id}，可再生），fingerprint =
版本 + 全会话消息数 + 最大时间戳，变了整算——与 deep_wordcloud_v2 同惯例，
不建低查询率新表。月份维度（演变 spark）与小时节奏随快照一并产出。
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

EMOJI_STATS_VERSION = 1

_DAY = 86400


def _get_db():
    # 函数内延迟导入：测试按 app.db.connection.get_db 打桩（模块级 from-import
    # 会固化真实库连接引用，patch 失效——weekly_report_service 同款约定）
    from ...db.connection import get_db

    return get_db()


# ----------------------------------------------------------------------
# Unicode emoji 提取（无第三方依赖：区间 + 簇合并）
# ----------------------------------------------------------------------

# 中文聊天高频文本符号（几何/杂项符号区段里的 text-presentation 默认项）：
# 落在 emoji 候选区间但实际是标点用途（实测 ●◎☆ 污染 Top 榜），定点剔除
_TEXT_SYMBOLS = {
    "●", "◎", "○", "◇", "◆", "□", "■", "△", "▲", "▽", "▼",
    "☆", "★", "※", "¤", "§", "‖", "℃", "‰", "→", "←", "↑", "↓",
}

# base 码点区间（独立成表情的起点）
_EMOJI_BASE_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x1F000, 0x1FAFF),  # 表情/手势/动物/食物/活动/符号/扩展（含 1F1E6-1F1FF 区域指示）
    (0x2600, 0x27BF),    # 杂项符号 + 装饰符号（☀ ✂ ✈ ✔）
    (0x2B00, 0x2BFF),    # ⭐ 等
    (0x203C, 0x203C), (0x2049, 0x2049),  # ‼ ⁉
    (0x2122, 0x2122), (0x2139, 0x2139),  # ™ ℹ
    (0x2194, 0x21AA),    # 箭头族（↔↕↖…➡）
    (0x231A, 0x231B),    # ⌚⌛
    (0x2328, 0x2328), (0x23CF, 0x23CF), (0x23E9, 0x23FA), (0x24C2, 0x24C2),
    (0x25AA, 0x25FE),    # 几何图形族 ▪▫▴…◾◽
    (0x2934, 0x2935), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3299),
    (0x00A9, 0x00A9), (0x00AE, 0x00AE),  # © ®
)
# 附着码点（不独立成表情，跟随前一个 base）
_EMOJI_EXTENSIONS = set(range(0x1F3FB, 0x1F3FF + 1))  # 肤色修饰
_EMOJI_EXTENSIONS |= {0xFE0F, 0x200D, 0x20E3, 0xFE0E}


def _is_emoji_base(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _EMOJI_BASE_RANGES)


def _cluster_key(cluster: str) -> str:
    """簇 → 统计键：去 FE0F/FE0E（😂 与 😂️ 变体合并）。"""
    return cluster.replace("\ufe0f", "").replace("\ufe0e", "")


_KEYCAP_RE = re.compile("[0-9#*]\\uFE0F?\\u20E3")


def extract_unicode_emojis(text: str) -> List[str]:
    """提取 Unicode emoji 簇（原样串，含修饰符；keycap 序列优先匹配）。"""
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        m = _KEYCAP_RE.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        cp = ord(text[i])
        if _is_emoji_base(cp) and text[i] not in _TEXT_SYMBOLS:
            j = i + 1
            # 簇吸收：肤色/变体选择符直接跟随；ZWJ 后跟 base 则连同吞下
            # （家庭/黑猫等组合表情）；区域指示符成对成旗（🇨🇳 两 base 相邻）
            regional = 0x1F1E6 <= cp <= 0x1F1FF
            while j < n:
                cp2 = ord(text[j])
                if cp2 in _EMOJI_EXTENSIONS and cp2 != 0x200D:
                    j += 1
                elif cp2 == 0x200D and j + 1 < n and _is_emoji_base(ord(text[j + 1])):
                    j += 2
                elif regional and 0x1F1E6 <= cp2 <= 0x1F1FF and j == i + 1:
                    j += 1
                else:
                    break
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


# ----------------------------------------------------------------------
# 占位与自定义表情提取
# ----------------------------------------------------------------------

_PLACEHOLDER_RE_CACHE: Optional[re.Pattern] = None


def _placeholder_re() -> re.Pattern:
    global _PLACEHOLDER_RE_CACHE
    if _PLACEHOLDER_RE_CACHE is None:
        from .preprocessing.cleaning import EMOJI_PLACEHOLDER_WORDS

        # 仅纯表情词；「表情/动画表情」是 47 类媒体占位（无表情语义，且
        # 47 类占位已由 custom 匿名通道接住），不进 builtin 词表
        words = sorted(set(EMOJI_PLACEHOLDER_WORDS), key=len, reverse=True)
        _PLACEHOLDER_RE_CACHE = re.compile(r"\[(" + "|".join(map(re.escape, words)) + r")\]")
    return _PLACEHOLDER_RE_CACHE


# XML md5 属性（V4 表情消息原文形态待真实解密通道验证，宽容两种：属性与裸 hex）
_MD5_ATTR_RE = re.compile(r'md5=["\']([0-9a-fA-F]{32})["\']')
_BARE_MD5_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])")

ANONYMOUS_CUSTOM_KEY = "anonymous"


def extract_custom_emoji(content: str, message_type: int) -> Optional[str]:
    """type=47 表情消息 → md5（小写）；解不出原文（`[表情]` 占位）→ 匿名桶；非 47 → None。"""
    if message_type != 47 or not content:
        return None
    m = _MD5_ATTR_RE.search(content) or _BARE_MD5_RE.search(content)
    return m.group(1).lower() if m else ANONYMOUS_CUSTOM_KEY


def extract_builtin_placeholders(text: str) -> List[str]:
    """文本内 `[呲牙]` 式占位（词表口径与清洗一致）。"""
    return _placeholder_re().findall(text)


# ----------------------------------------------------------------------
# 聚合与快照
# ----------------------------------------------------------------------

def _conversation_fingerprint(conversation_id: int) -> Tuple[int, int, int]:
    """(消息数, id 总和, 最大时间戳)——全会话口径，任何导入/实时新消息
    都会变；id 总和兜「等量删插」（删一条旧消息再插一条同时间戳新消息，
    计数与 max 都不变，内容和分布却已换了）。"""
    row = _get_db().execute(
        "SELECT COUNT(*), COALESCE(SUM(id), 0), COALESCE(MAX(timestamp), 0)"
        " FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def _month_of(ts: int) -> str:
    return time.strftime("%Y-%m", time.localtime(ts))


def collect_emoji_stats(
    conversation_id: int, from_ts: int = 0, to_ts: int = 0
) -> Dict[str, Any]:
    """单次扫描聚合。默认全会话（快照缓存路径）；传 from_ts/to_ts 走窗口
    口径（年度报告/纪念册按年/区间取表情页，不落缓存按需现算）。
    行量级 = 扫描范围全部消息，emoji 命中只占少数。"""
    top: Dict[Tuple[int, str, str], int] = defaultdict(int)  # (is_sender, kind, key) -> n
    months: Dict[str, Dict[str, int]] = defaultdict(lambda: {"me": 0, "ta": 0})
    hourly: List[int] = [0] * 24
    custom_first: Dict[str, int] = {}
    custom_last: Dict[str, int] = {}
    total_messages = 0

    window_sql = ""
    params: List[Any] = [conversation_id]
    if from_ts:
        window_sql += " AND timestamp >= ?"
        params.append(int(from_ts))
    if to_ts:
        window_sql += " AND timestamp <= ?"
        params.append(int(to_ts))

    pre = _placeholder_re()
    cur = _get_db().execute(
        "SELECT is_sender, message_type, COALESCE(content, ''), timestamp"
        " FROM messages WHERE conversation_id = ? AND content != ''"
        f"{window_sql} ORDER BY timestamp",
        tuple(params),
    )
    for is_sender, mtype, content, ts in cur:
        total_messages += 1
        side = "me" if is_sender else "ta"
        hits = False
        custom = extract_custom_emoji(content, mtype)
        if custom is not None:
            top[(is_sender, "custom", custom)] += 1
            if custom != ANONYMOUS_CUSTOM_KEY:
                if custom not in custom_first or ts < custom_first[custom]:
                    custom_first[custom] = ts
                if custom not in custom_last or ts > custom_last[custom]:
                    custom_last[custom] = ts
            hits = True
        else:
            for cluster in extract_unicode_emojis(content):
                top[(is_sender, "unicode", _cluster_key(cluster))] += 1
                hits = True
            for word in pre.findall(content):
                top[(is_sender, "builtin", word)] += 1
                hits = True
        if hits:
            months[_month_of(ts)][side] += 1
            hourly[time.localtime(ts).tm_hour] += 1

    return _build_snapshot(conversation_id, top, months, hourly, custom_first, custom_last, total_messages)


def _build_snapshot(
    conversation_id: int,
    top: Dict[Tuple[int, str, str], int],
    months: Dict[str, Dict[str, int]],
    hourly: List[int],
    custom_first: Dict[str, int],
    custom_last: Dict[str, int],
    total_messages: int,
) -> Dict[str, Any]:
    def _top_list(side: int, kind: str, limit: int) -> List[Dict[str, Any]]:
        items = [
            {"key": k, "count": c}
            for (s, kd, k), c in top.items()
            if s == side and kd == kind
        ]
        items.sort(key=lambda x: -x["count"])
        return items[:limit]

    md5s = sorted(
        {key for (_, k, key) in top if k == "custom" and key != ANONYMOUS_CUSTOM_KEY},
        key=lambda m: -(top[(1, "custom", m)] + top[(0, "custom", m)]),
    )
    wall = [
        {
            "md5": md5,
            "count": top[(1, "custom", md5)] + top[(0, "custom", md5)],
            "count_me": top[(1, "custom", md5)],
            "count_ta": top[(0, "custom", md5)],
            "first_used": custom_first.get(md5),
            "last_used": custom_last.get(md5),
        }
        for md5 in md5s
    ]
    anonymous_me = top.get((1, "custom", ANONYMOUS_CUSTOM_KEY), 0)
    anonymous_ta = top.get((0, "custom", ANONYMOUS_CUSTOM_KEY), 0)

    peak_hour, peak_count = max(enumerate(hourly), key=lambda p: p[1]) if any(hourly) else (0, 0)
    return {
        "ok": True,
        "version": EMOJI_STATS_VERSION,
        "conversation_id": conversation_id,
        "scanned_messages": total_messages,
        "top_me": {
            "unicode": _top_list(1, "unicode", 10),
            "builtin": _top_list(1, "builtin", 10),
        },
        "top_ta": {
            "unicode": _top_list(0, "unicode", 10),
            "builtin": _top_list(0, "builtin", 10),
        },
        "months": [{"month": m, "me": v["me"], "ta": v["ta"]} for m, v in sorted(months.items())],
        "hourly": hourly,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "rhythm_label": hour_window_label(peak_hour) if peak_count else "",
        "custom_wall": wall[:24],
        "custom_anonymous": {"me": anonymous_me, "ta": anonymous_ta},
    }


# ----------------------------------------------------------------------
# 节奏翻译
# ----------------------------------------------------------------------

_HOUR_WINDOWS = (
    (0, 5, "凌晨"), (6, 8, "清晨"), (9, 11, "上午"), (12, 13, "午间"),
    (14, 17, "下午"), (18, 22, "晚上"), (23, 23, "深夜"),
)


def hour_window_label(hour: int) -> str:
    for lo, hi, label in _HOUR_WINDOWS:
        if lo <= hour <= hi:
            return f"{label} {hour} 点前后"
    return f"{hour} 点前后"


# ----------------------------------------------------------------------
# 快照缓存与读出口
# ----------------------------------------------------------------------

def _snapshot_key(conversation_id: int) -> str:
    return f"emoji_stats_v{EMOJI_STATS_VERSION}_{conversation_id}"


def get_emoji_stats(conversation_id: int, force_refresh: bool = False) -> Dict[str, Any]:
    """读表情统计快照；fingerprint 失效（或首次/强制）整算并落 settings。"""
    count, id_sum, max_ts = _conversation_fingerprint(conversation_id)
    if count == 0:
        return {"ok": False, "reason": "no_messages"}
    fp = f"{EMOJI_STATS_VERSION}:{count}:{id_sum}:{max_ts}"
    db = _get_db()
    if not force_refresh:
        row = db.execute(
            "SELECT value FROM settings WHERE key = ?", (_snapshot_key(conversation_id),)
        ).fetchone()
        if row:
            try:
                cached = json.loads(row[0])
                if cached.get("fingerprint") == fp:
                    return cached
            except Exception:
                pass
    snapshot = collect_emoji_stats(conversation_id)
    snapshot["fingerprint"] = fp
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (_snapshot_key(conversation_id), json.dumps(snapshot, ensure_ascii=False)),
    )
    db.commit()
    return snapshot
