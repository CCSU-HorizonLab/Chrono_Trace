"""虚构演示库生成器（脱敏 demo 库）——论文截图 / 复现包 / 对外 demo 用。

背景（论文规划 P0 ②、素材 §8）：真实库界面含真实姓名与原始消息，
任何对外截图/共享统计前必须先用虚构演示库重做。本脚本从零生成
**纯虚构**语料（不读真实库、不做真实数据脱敏复制——生成即脱敏），
并用应用自己的 schema.sql 建库，保证 demo 库可被应用直接消费。

产物（默认 backend/data/demo_home/，配合 CHRONO_TRACE_DATA_DIR 使用）：
- chrono_trace.db   虚构库（8 会话：6 单聊 + 2 群聊，约 3 万条消息）
- settings.json     最小演示设置（独立于真实 settings——绝不携带真实
                    账号/密钥/网关配置，实时监听与 RAG 默认关闭）
- models -> 符号链接 指向仓库内模型目录（本地分析可跑；失败则提示）

运行：
    python backend/scripts/make_demo_db.py [--seed N] [--anchor "2026-11-14 20:00"]
                                           [--out backend/data/demo_home]

截图会话（真实数据完全隔离，双向不串）：
    CHRONO_TRACE_DATA_DIR=<绝对路径>/demo_home python app_dev.py

可复现性：同 seed + 同 anchor 产出逐字节等价的消息序列（复现包记录
这两个参数即可重造 demo 库）；anchor 默认取当前时间——demo 看起来
「新鲜」，复现时显式传 anchor。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

DEMO_ACCOUNT_WXID = "wxid_demo_self"
DEMO_SELF_LABEL = "演示账号"

# ---------------------------------------------------------------------------
# 语料模板库（全部虚构；{kw} 由 persona 关键词填充）
# ---------------------------------------------------------------------------

# 通用寒暄/回复池：me 与 other 共用底池，persona 再叠加个性话题
OPENERS = [
    "在吗", "忙不忙", "有个事想问问你", "哈哈跟你分享个事", "早呀",
    "晚上好", "喂，看到回我一下", "刚看到个东西想到你",
]
REPLIES_NEUTRAL = [
    "嗯嗯", "好嘞", "收到收到", "行，那就这么定", "我先看看",
    "等我想想再回你", "好，晚点聊", "在忙，稍后回你", "明白", "可以的",
]
REPLIES_POS = [
    "太好了哈哈", "牛！", "这个真的可以", "开心！", "哈哈哈笑死",
    "稳的", "太赞了吧", "好耶",
]
REPLIES_NEG = [
    "唉，最近有点烦", "不太行啊", "有点 emo", "头疼", "烦死了",
    "算了不说这个了", "唉",
]
# 决策语言（喂决策风格通道 B：求助问句/决策列举/拖延话术——双侧都要有）
DECISIONS_SEEK = [
    "你觉得呢，帮我看看", "怎么办，帮我拿个主意", "帮我参谋一下这个",
    "你说哪个好", "给点建议呗，怎么选啊",
]
DECISIONS_DELIB = [
    "我查了下，对比了两家的参数", "我列了一下几个选项", "我做了点功课，看了测评",
    "我调研了三个方案", "权衡了下利弊，各有各的好", "研究了下，基本想清楚了",
]
DECISIONS_DELAY = [
    "再看看吧，不急", "以后再说", "回头再说", "先放放，想想再说", "到时候再说吧",
]
EMOTE_SHORT = [
    "哈哈哈哈哈哈", "……", "？？？", "！？", "orz", "阿这", "绷不住了",
    "无语住了", "真的会谢", "好家伙",
]

# 长消息（段落级，偶发；让 LLM 评估/画像页有「有内容」的质感）
LONG_TEMPLATES = [
    ("跟你说个大喜事：今天终面过了！三轮面下来其实没底，出门的时候手都在抖，"
     "结果晚上就来了 offer 电话。第一时间想到跟你讲，这几个月听我倒垃圾真是太谢谢了，"
     "回头请你吃饭，你选地方。", 1),
    ("最近状态有点差，项目连着两周赶进度，每天到家都是十一点多，周末也在补觉。"
     "有点怀疑这么卷值不值得，但又不敢停下来。你之前说的那个说法我一直在想，"
     "「先把这一段熬过去再看」，先这样吧。", -1),
    ("这周末去了趟郊区，本来只是随便走走，结果那边的山道意外地好骑，"
     "一路都是树荫，风穿过来的时候整个人都松了。拍了些照片，回头发你。"
     "下次组一局？就当散心。", 1),
    ("整理房间翻出一堆老物件，包括咱们以前出去玩拍的那卷胶片，居然还没冲。"
     "拿去店里冲出来那一刻真的很感动，好多画面都想不起来了，照片替我记着。"
     "改天把扫描件发你。", 0),
    ("家里老人住院了一周，没什么大事，就是年纪到了总要检查。在医院陪床的时候"
     "想了很多，觉得能常常联系的朋友要好好珍惜。谢谢你一直都在。", 0),
]


def _hours_allday() -> List[float]:
    w = [0.2] * 24
    for h in (10, 11, 12, 14, 15, 20, 21, 22, 23):
        w[h] = 1.2
    w[0] = 0.4
    return w


def _hours_work() -> List[float]:
    w = [0.0] * 24
    for h in range(9, 19):
        w[h] = 1.5 if h in (10, 11, 14, 15, 16) else 0.8
    w[20] = 0.3
    return w


def _hours_evening() -> List[float]:
    w = [0.0] * 24
    for h in range(19, 24):
        w[h] = 1.4
    w[13] = 0.5
    w[14] = 0.5
    w[0] = 0.2
    return w


def _hours_elder() -> List[float]:
    w = [0.0] * 24
    for h in (7, 8, 9):
        w[h] = 1.6
    for h in (20, 21, 22):
        w[h] = 1.2
    return w


def _hours_weekend_play() -> List[float]:
    w = [0.0] * 24
    for h in range(9, 21):
        w[h] = 1.0
    w[10] = w[15] = 1.6
    return w


@dataclass
class Persona:
    """单聊/群聊 persona：节奏、话题、决策语言密度全部由这里定义。"""

    key: str
    name: str
    wxid: str
    conv_type: str = "private"
    remark: Optional[str] = None
    months: int = 24
    sessions_week_start: float = 3.0
    sessions_week_end: float = 3.0          # 起→末线性阶段曲线（升/降温）
    hour_weights: List[float] = field(default_factory=_hours_allday)
    weekend_factor: float = 1.0             # 周末会话密度倍数
    me_initiate: float = 0.5
    reply_prob: float = 0.82
    burst: Tuple[int, int] = (1, 3)
    nontext_rate: float = 0.06
    emoji_rate: float = 0.18
    long_rate: float = 0.02
    decision_rate: float = 0.10             # 决策语言占比（陈叙白拉满）
    # 话题 bank：(模板, 极性 1/0/-1)；{kw} 占位由 keywords 填充
    topics: List[Tuple[str, int]] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    memes: List[str] = field(default_factory=list)  # 高频专属短语（梗词典）
    me_extras: List[Tuple[str, int]] = field(default_factory=list)  # 我方个性话题
    # 群聊专属
    members: List[Tuple[str, float]] = field(default_factory=list)  # (短名, 发言权重)
    group_topics: List[Tuple[str, int]] = field(default_factory=list)


PERSONAS: List[Persona] = [
    Persona(
        key="linwz", name="林晚照", wxid="wxid_demo_linwz",
        months=30, sessions_week_start=6.0, sessions_week_end=5.2,
        hour_weights=_hours_allday(), weekend_factor=1.3,
        me_initiate=0.55, reply_prob=0.9, burst=(1, 4),
        nontext_rate=0.12, emoji_rate=0.34, long_rate=0.03, decision_rate=0.06,
        topics=[
            ("今天路上看到一只{kw}，走不动道", 1), ("那家{kw}居然没翻车，意外的好吃", 1),
            ("新开的{kw}周末去不去？", 1), ("这个{kw}我真的能看一百遍", 1),
            ("被{kw}气到了，无语", -1), ("今天有点丧，什么都不想干", -1),
            ("又开始下雨了，烦", -1), ("周三的{kw}记得吗，别放我鸽子", 0),
            ("你说我们是不是该攒钱出去一趟", 0), ("晚上吃{kw}怎么样", 0),
            ("刚吵完一架，心情很差", -1), ("收到{kw}的快递了！开心", 1),
        ],
        keywords=["小鳄鱼玩偶", "咖啡馆", "日料店", "画展", "老地方面馆", "新番", "落日飞车"],
        memes=["小鳄鱼", "周四见", "不许放鸽子"],
        me_extras=[
            ("给你看个东西，笑死我了哈哈哈", 1), ("今天被老板夸了，飘了", 1),
            ("累瘫了，只想躺着", -1), ("想你了，什么时候有空", 1),
        ],
    ),
    Persona(
        key="chenxb", name="陈叙白", wxid="wxid_demo_chenxb", remark="陈工-山南",
        months=26, sessions_week_start=4.0, sessions_week_end=3.4,
        hour_weights=_hours_work(), weekend_factor=0.25,
        me_initiate=0.45, reply_prob=0.85, burst=(1, 2),
        nontext_rate=0.08, emoji_rate=0.08, long_rate=0.02, decision_rate=0.26,
        topics=[
            ("{kw}的进度同步一下，今天卡在联调", 0), ("接口文档我更新了，{kw}那部分你再看下", 0),
            ("这周的{kw}你来主导，我配合", 0), ("需求又变了，{kw}得重排", -1),
            ("灰度数据不错，{kw}可以全量了", 1), ("复盘写完了，{kw}那段你补充下", 0),
            ("服务器昨晚告警，{kw}排查了一小时", -1), ("客户那边对{kw}很满意，稳了", 1),
        ],
        keywords=["山南项目", "网关迁移", "对账模块", "压测", "灰度发布", "周报"],
        memes=["对齐一下", "拉齐", "闭环"],
        me_extras=[
            ("方案我发你了，有空帮我看看", 0), ("评审过了！这版稳", 1),
            ("加班到现在，头疼", -1), ("周五上线，这周都在补文档", 0),
        ],
    ),
    Persona(
        key="suche", name="苏澈", wxid="wxid_demo_suche",
        months=22, sessions_week_start=2.5, sessions_week_end=2.8,
        hour_weights=_hours_evening(), weekend_factor=2.2,
        me_initiate=0.5, reply_prob=0.75, burst=(1, 2),
        nontext_rate=0.10, emoji_rate=0.2, long_rate=0.025, decision_rate=0.08,
        topics=[
            ("这卷{kw}出片了！色调绝了", 1), ("入了个{kw}，钱包空了但快乐", 1),
            ("周末{kw}走不走，天气不错", 1), ("冲扫店涨价了，唉", -1),
            ("{kw}太堵了，体验一般", -1), ("那个展的{kw}值得二刷", 1),
            ("暗房约到了，第一次自己放照片", 1), ("装备党的钱包保不住了", -1),
        ],
        keywords=["柯尼卡", "反转片", "环湖骑行", "中古相机", "版画展", "定妆照"],
        memes=["出片了", "毒德大学"],
        me_extras=[
            ("刚扫出来，发你了", 1), ("这周没空，下下周？", 0),
            ("膝盖不行了，得歇歇", -1),
        ],
    ),
    Persona(
        key="zhouyq", name="周砚秋", wxid="wxid_demo_zhouyq", remark="周老师",
        months=34, sessions_week_start=3.2, sessions_week_end=2.6,
        hour_weights=_hours_elder(), weekend_factor=0.8,
        me_initiate=0.3, reply_prob=0.92, burst=(1, 2),
        nontext_rate=0.20, emoji_rate=0.24, long_rate=0.015, decision_rate=0.04,
        topics=[
            ("早上好！今天去早市买了{kw}", 1), ("{kw}记得按时吃，别不当回事", 0),
            ("外孙这次考得不错，奖励了他一套{kw}", 1), ("晚上降温了，早点休息", 0),
            ("血压又高了点，医生说少盐", -1), ("腌笃鲜的做法我发你，{kw}别省", 0),
            ("公园的桂花开好了，香得很", 1),
        ],
        keywords=["时令菜", "降压药", "这套书", "太极剑", "荠菜馄饨"],
        memes=["早上好", "晚安", "好好吃饭"],
        me_extras=[
            ("周老师早！", 1), ("收到，我会注意的", 0), ("改天去看您", 1),
        ],
    ),
    Persona(
        key="guyf", name="顾一帆", wxid="wxid_demo_guyf",
        months=30, sessions_week_start=5.0, sessions_week_end=0.35,
        hour_weights=_hours_allday(), weekend_factor=1.1,
        me_initiate=0.35, reply_prob=0.7, burst=(1, 2),
        nontext_rate=0.06, emoji_rate=0.12, long_rate=0.02, decision_rate=0.05,
        topics=[
            ("今天去{kw}练了两小时，爽", 1), ("老同学聚会上聊起你，都说好久没见", 0),
            ("搬来这边之后通勤累多了", -1), ("新公司节奏快，周末只想补觉", -1),
            ("改天约饭，老地方", 1), ("最近有点迷茫，不知道要不要换个方向", -1),
        ],
        keywords=["新健身房", "老城区", "公司班车"],
        memes=["改天约", "老地方"],
        me_extras=[
            ("最近怎么样？好久没聊", 0), ("看到你朋友圈了，状态不错啊", 1),
        ],
    ),
    Persona(
        key="hezw", name="何知微", wxid="wxid_demo_hezw",
        months=5, sessions_week_start=0.5, sessions_week_end=4.6,
        hour_weights=_hours_evening(), weekend_factor=1.6,
        me_initiate=0.6, reply_prob=0.8, burst=(1, 3),
        nontext_rate=0.08, emoji_rate=0.26, long_rate=0.02, decision_rate=0.07,
        topics=[
            ("今天第一次试了{kw}，手臂还在抖", 1), ("公司附近新开了家{kw}，环境很好", 1),
            ("那家{kw}的猫太亲人了", 1), ("即兴喜剧的开放麦笑死我了", 1),
            ("这本书在{kw}看到的，借你了", 0), ("下周团建要爬山，救命", -1),
        ],
        keywords=["攀岩", "猫咖", "独立书店", "开放麦"],
        memes=["社恐发作", "下次一定"],
        me_extras=[
            ("带你去那家店，绝对合你口味", 1), ("这周忙完约你", 1),
        ],
    ),
    Persona(
        key="g_shannan", name="山南项目组", wxid="wxid_demo_group_shannan",
        conv_type="group",
        months=20, sessions_week_start=7.0, sessions_week_end=5.5,
        hour_weights=_hours_work(), weekend_factor=0.15,
        me_initiate=0.3, reply_prob=0.88, burst=(1, 2),
        nontext_rate=0.06, emoji_rate=0.1, long_rate=0.01, decision_rate=0.12,
        keywords=["山南项目", "联调", "需求"],
        members=[("我", 1.0), ("陈工", 2.4), ("小陆", 1.6), ("老猫", 1.2), ("实习生小周", 0.7)],
        group_topics=[
            ("明早十点{kw}评审，别忘了", 0), ("{kw}第三轮联调的排期发群里了", 0),
            ("这个 bug 我这边修完了，帮忙验一下", 0), ("客户刚确认了{kw}的验收标准", 1),
            ("测试环境又挂了，谁在看", -1), ("周报我汇总好了，大家补充", 0),
            ("辛苦各位，这周里程碑保住了", 1), ("需求文档 v3 更新，重点看第 4 节", 0),
            ("下午茶到楼下了，自取", 1), ("上线窗口定在周五 22 点", 0),
        ],
    ),
    Persona(
        key="g_cycling", name="周末骑行小队", wxid="wxid_demo_group_cycling",
        conv_type="group",
        months=16, sessions_week_start=3.0, sessions_week_end=3.4,
        hour_weights=_hours_weekend_play(), weekend_factor=2.6,
        me_initiate=0.5, reply_prob=0.85, burst=(1, 3),
        nontext_rate=0.10, emoji_rate=0.3, long_rate=0.01, decision_rate=0.06,
        keywords=["环湖", "刷街"],
        members=[("我", 1.2), ("阿澈", 2.0), ("板凳", 1.5), ("二饼", 1.3), ("阿凯", 1.0), ("娜娜", 0.9)],
        group_topics=[
            ("周六早上六点半{kw}集合，迟到请全队奶茶", 1), ("这条路线的红叶出了，快冲", 1),
            ("我爆胎了，在路边等救援", -1), ("{kw}之后那家羊肉汤，懂的都懂", 1),
            ("周末有雨，活动顺延一天", -1), ("新买的车到了，周末验收", 1),
            ("夜骑走不走，带了前后灯", 1), ("这周量太大，我歇一周", 0),
        ],
    ),
]

EMOJIS = ["😄", "🥲", "😂", "👍", "🐢", "🐊", "🚴", "📷", "🍜", "🌙", "💪", "🙏", "😹"]


# ---------------------------------------------------------------------------
# 生成逻辑
# ---------------------------------------------------------------------------

def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth 小 λ 泊松采样（λ < 10 足够，确定性由 rng 保证）。"""
    lam = max(0.0, min(lam, 12.0))
    l_exp = pow(2.718281828459045, -lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l_exp:
            return k - 1


def _pick_hour(rng: random.Random, weights: List[float]) -> int:
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for hour, w in enumerate(weights):
        acc += w
        if r <= acc:
            return hour
    return 23


def _fill(rng: random.Random, template: str, keywords: List[str]) -> str:
    if "{kw}" in template and keywords:
        return template.replace("{kw}", rng.choice(keywords))
    return template


def _pick_topic(rng: random.Random, persona: Persona, side: int) -> Tuple[str, int]:
    """side: 1=我方 0=对方。我方=通用池+个性 me_extras，对方=persona.topics。"""
    if side == 1 and persona.me_extras and rng.random() < 0.35:
        return rng.choice(persona.me_extras)
    if persona.conv_type == "group" and persona.group_topics and rng.random() < 0.7:
        return rng.choice(persona.group_topics)
    if persona.topics and rng.random() < 0.75:
        return rng.choice(persona.topics)
    polarity = rng.choices([1, 0, -1], weights=[45, 40, 15])[0]
    bank = {1: REPLIES_POS, 0: REPLIES_NEUTRAL, -1: REPLIES_NEG}[polarity]
    return rng.choice(bank), polarity


def _one_text(rng: random.Random, persona: Persona, side: int, *,
              is_opener: bool) -> Tuple[str, int]:
    """生成一条文本：opener/话题/决策语言/梗/语气短句 按类别概率选择。"""
    r = rng.random()
    if is_opener:
        return rng.choice(OPENERS), 0
    if r < persona.decision_rate:
        pool = DECISIONS_SEEK if rng.random() < 0.4 else (
            DECISIONS_DELIB if rng.random() < 0.7 else DECISIONS_DELAY)
        return rng.choice(pool), 0
    if r < persona.decision_rate + 0.06 and persona.memes:
        return rng.choice(persona.memes), 1
    if r < persona.decision_rate + 0.06 + 0.12:
        return rng.choice(EMOTE_SHORT), 0
    text, polarity = _pick_topic(rng, persona, side)
    return _fill(rng, text, persona.keywords), polarity


def _emit_message(rng: random.Random, persona: Persona, side: int, ts: int, *,
                  is_opener: bool = False, force_long: bool = False) -> dict:
    """组装单条消息 dict；时间戳冲突由调用方保证严格递增。"""
    if rng.random() < persona.nontext_rate and not force_long and not is_opener:
        mtype = rng.choices([3, 34, 49], weights=[55, 35, 10])[0]
        content = None
    elif force_long:
        text, polarity = rng.choice(LONG_TEMPLATES)
        mtype, content = 1, text
    else:
        text, _ = _one_text(rng, persona, side, is_opener=is_opener)
        if rng.random() < persona.emoji_rate:
            text = f"{text} {rng.choice(EMOJIS)}"
        mtype, content = 1, text
    return {
        "is_sender": 1 if side == 1 else 0,
        "sender": ("我" if side == 1 else None) if persona.conv_type == "group" else None,
        "message_type": mtype,
        "content": content,
        "timestamp": ts,
    }


def _pick_member(rng: random.Random, persona: Persona) -> int:
    """群聊成员抽样：返回 side（1=我）按发言权重——普通人是 zipf 分布。"""
    weights = [w for _, w in persona.members]
    names = [n for n, _ in persona.members]
    idx = rng.choices(range(len(names)), weights=weights)[0]
    return 1 if names[idx] == "我" else 0


def generate_messages(rng: random.Random, persona: Persona, start_ts: int,
                      end_ts: int) -> List[dict]:
    """按天走表生成一个会话的全部消息（时间严格递增）。"""
    messages: List[dict] = []
    total_days = max(1, (end_ts - start_ts) // 86400)
    long_quota_every = max(1, int(1.0 / max(persona.long_rate, 1e-4)))
    msg_index = 0
    for day in range(total_days):
        ts_day = start_ts + day * 86400
        dt = datetime.fromtimestamp(ts_day)
        frac = day / total_days
        rate = persona.sessions_week_start + (
            persona.sessions_week_end - persona.sessions_week_start) * frac
        weekend = dt.weekday() >= 5
        lam = rate / 7.0 * (persona.weekend_factor if weekend else 1.0)
        for _ in range(_poisson(rng, lam)):
            hour = _pick_hour(rng, persona.hour_weights)
            ts = ts_day + hour * 3600 + rng.randint(0, 59) * 60 + rng.randint(0, 59)
            if ts >= end_ts:
                continue
            side = 1 if rng.random() < persona.me_initiate else 0
            first_of_session = True
            used_long = False
            while True:
                burst = rng.randint(*persona.burst)
                for _ in range(burst):
                    msg_index += 1
                    force_long = (not used_long and msg_index % long_quota_every == 0)
                    if force_long:
                        used_long = True
                    msg = _emit_message(rng, persona, side, ts,
                                        is_opener=first_of_session,
                                        force_long=force_long)
                    first_of_session = False
                    if persona.conv_type == "group":
                        msg["sender"] = ("我" if side == 1 else _group_sender(rng, persona))
                    # 时间严格递增保护（同秒连发按 +1 秒错开）
                    if messages and msg["timestamp"] <= messages[-1]["timestamp"]:
                        msg["timestamp"] = messages[-1]["timestamp"] + 1
                        ts = msg["timestamp"]
                    messages.append(msg)
                    ts += rng.randint(20, 200)
                if rng.random() > persona.reply_prob:
                    break
                if persona.conv_type == "group":
                    side = _pick_member(rng, persona)
                else:
                    side = 1 - side
    return messages


def _group_sender(rng: random.Random, persona: Persona) -> str:
    names = [n for n, _ in persona.members if n != "我"]
    weights = [w for n, w in persona.members if n != "我"]
    return rng.choices(names, weights=weights)[0]


# ---------------------------------------------------------------------------
# 建库
# ---------------------------------------------------------------------------

def build_demo_db(db_path: Path, seed: int, anchor_ts: int) -> dict:
    """生成 demo 库主流程：schema → 8 会话 → 消息 → 校验。返回统计。"""
    rng = random.Random(seed)
    schema_sql = (BACKEND_DIR / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)

    start_ts = anchor_ts - int(34 * 30.4 * 86400)  # 最长 persona 34 个月
    end_ts = anchor_ts - 2 * 86400                  # 停在「两天前」
    stats = []
    for persona in PERSONAS:
        conv_start = max(start_ts, end_ts - int(persona.months * 30.4 * 86400))
        msgs = generate_messages(rng, persona, conv_start, end_ts)
        if not msgs:
            continue
        cur = conn.execute(
            "INSERT INTO conversations (account_wxid, username, display_name, remark,"
            " nickname, conversation_type, platform, created_at, updated_at,"
            " message_count, is_deleted, analysis_stale)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,0,1)",
            (DEMO_ACCOUNT_WXID, persona.wxid, persona.name, persona.remark,
             persona.name, persona.conv_type, "wechat",
             msgs[0]["timestamp"], msgs[-1]["timestamp"], len(msgs)),
        )
        conv_id = cur.lastrowid
        rows = [
            (conv_id, i + 1, persona.wxid if persona.conv_type == "private" else persona.wxid,
             m["sender"], m["is_sender"], m["message_type"], m["content"],
             m["timestamp"], "long", anchor_ts)
            for i, m in enumerate(msgs)
        ]
        conn.executemany(
            "INSERT INTO messages (conversation_id, local_id, talker, sender, is_sender,"
            " message_type, content, timestamp, source, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        if persona.conv_type == "private":
            conn.execute(
                "INSERT INTO contacts (account_wxid, username, nickname, remark,"
                " contact_type, is_friend, created_at, updated_at)"
                " VALUES (?,?,?,?, 'friend', 1, ?, ?)",
                (DEMO_ACCOUNT_WXID, persona.wxid, persona.name, persona.remark,
                 conv_start, anchor_ts),
            )
        stats.append({"key": persona.key, "name": persona.name, "type": persona.conv_type,
                      "messages": len(msgs), "span_days": (msgs[-1]["timestamp"] - msgs[0]["timestamp"]) // 86400})
    conn.commit()
    verify_demo_db(conn)
    conn.close()
    return {"conversations": len(stats), "messages": sum(s["messages"] for s in stats),
            "detail": stats}


def verify_demo_db(conn: sqlite3.Connection) -> None:
    """落库后自检：计数一致、时间单调、无空文本、wxid 全部带 demo 前缀。"""
    for conv_id, count, created, updated in conn.execute(
            "SELECT id, message_count, created_at, updated_at FROM conversations"):
        real, mn, mx = conn.execute(
            "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM messages"
            " WHERE conversation_id=?", (conv_id,)).fetchone()
        assert real == count, f"conv {conv_id}: message_count {count} != 实际 {real}"
        assert (mn, mx) == (created, updated), f"conv {conv_id}: 时间边界不一致"
    bad_empty = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE message_type=1"
        " AND (content IS NULL OR TRIM(content)='')").fetchone()[0]
    assert bad_empty == 0, f"{bad_empty} 条文本消息内容为空"
    bad_wxid = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE username NOT LIKE 'wxid_demo_%'").fetchone()[0]
    assert bad_wxid == 0, "存在非 demo 前缀的 username"
    # 决策语言在场（陈叙白双侧都要有——决策风格卡的信号源）
    seek = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id=("
        " SELECT id FROM conversations WHERE username='wxid_demo_chenxb')"
        " AND (content LIKE '%帮我看看%' OR content LIKE '%帮我参谋%'"
        " OR content LIKE '%对比了%' OR content LIKE '%调研%')").fetchone()[0]
    assert seek >= 20, f"决策语言样本不足: {seek}"


# ---------------------------------------------------------------------------
# demo_home 组装
# ---------------------------------------------------------------------------

def write_demo_settings(path: Path, anchor_ts: int) -> None:
    """最小演示 settings：独立账号、无密钥、监听/RAG 关闭（不碰真实配置）。"""
    settings = {
        "wechat_accounts": [{
            "wxid": DEMO_ACCOUNT_WXID,
            "label": DEMO_SELF_LABEL,
            "avatar": "",
            "wechat_dir": "",
            "source": "demo",
            "db_key": "",
            "raw_keys": {},
            "import_completed": True,
            "last_import_at": anchor_ts,
        }],
    }
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def link_models(home_dir: Path) -> bool:
    """符号链接仓库模型目录到 demo home（本地情感分析可跑；失败仅提示）。"""
    src = BACKEND_DIR / "data" / "models"
    dst = home_dir / "models"
    if dst.exists() or dst.is_symlink():
        return True
    if not src.exists():
        return False
    try:
        os.symlink(src.resolve(), dst)
        return True
    except OSError:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成虚构演示库（脱敏 demo）")
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--anchor", type=str, default="",
                        help='语料截止锚点，如 "2026-11-14 20:00"（复现时显式传入）')
    parser.add_argument("--out", type=str,
                        default=str(BACKEND_DIR / "data" / "demo_home"))
    args = parser.parse_args(argv)

    if args.anchor:
        anchor_dt = datetime.strptime(args.anchor, "%Y-%m-%d %H:%M")
    else:
        anchor_dt = datetime.now().replace(microsecond=0)
    anchor_ts = int(anchor_dt.timestamp())

    home = Path(args.out).expanduser().resolve()
    db_path = home / "chrono_trace.db"
    result = build_demo_db(db_path, args.seed, anchor_ts)
    write_demo_settings(home / "settings.json", anchor_ts)
    models_ok = link_models(home)

    print(f"[demo] 库: {db_path}")
    print(f"[demo] seed={args.seed} anchor={anchor_dt.strftime('%Y-%m-%d %H:%M')}"
          f"（复现请原样记录这两个参数）")
    for s in result["detail"]:
        print(f"[demo]   {s['type']:8s} {s['name']:8s} {s['messages']:6d} 条 / 跨度 {s['span_days']} 天")
    print(f"[demo] 合计 {result['conversations']} 会话 {result['messages']} 消息；自检通过")
    if not models_ok:
        print("[demo] 注意：模型目录符号链接失败，demo 会话内情感分析不可用"
              "（可将 backend/data/models 复制到 demo_home/models）")
    print("[demo] 截图会话启动方式（真实数据完全隔离）：")
    print(f"[demo]   CHRONO_TRACE_DATA_DIR={home} python app_dev.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
