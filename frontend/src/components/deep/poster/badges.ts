/**
 * 海报称号规则（纯前端函数）：文案随受众变，后端下发等于把展示细节塞进
 * payload。规则按序首中（先命中先得），全部未中兜底「时光收藏家」。
 *
 * 自我版只喂 my 切片（无对方数据）：依赖联合数据的规则（势均力敌/先声
 * 夺人/同频共振/秒回拍档的条数门槛）自然不生效，无需特判。
 *
 * 称号体系两档：pickPosterBadge 主称号（首中一条）+ posterSubBadges 副称号
 * 成就清单（极值触发、★分级）；posterRarityLines 是会话内稀有度话术——
 * 本地单机无跨用户基准，全部锚定这段对话自身的相对事实，不编造百分位。
 */
import type {
  IntimatePosterPayload,
  PosterAudience,
  PublicPosterPayload,
  SelfPosterPayload,
} from './registry'
import { formatCount } from './activityShared'

/** 三种 payload 归一后的称号判定输入（缺席指标为 null，对应规则跳过） */
export type BadgeInput = {
  total: number
  selfCount: number
  otherCount: number
  activeDays: number
  spanDays: number
  lateNightCount: number | null
  /** 秒回判据用时（秒）：定向/公开=中位回复；自我版无中位切片以均值近似 */
  replyQuickSeconds: number | null
  replyCount: number | null
  userRatio: number | null
  topAll: string[]
  topMine: string[]
  topOther: string[]
  /** 最长连续活跃天数（自我版=我单侧的连续天数） */
  streakDays: number | null
  /** 窗内最长沉默期天数（联合事件，自我版恒 null） */
  silenceDays: number | null
}

export type PosterBadge = { id: string; title: string; caption: string }

/** 副称号：极值触发的成就徽标，grade=★档（会话内相对口径） */
export type SubBadge = { id: string; title: string; grade: 1 | 2 | 3; note: string }

/** 里程碑里的最长沉默天数（公开版投影保留 days 剥日期） */
function silenceDaysFrom(
  milestones: Array<{ kind: string; days?: number }>,
): number | null {
  const hit = milestones.find((m) => m.kind === 'longest_silence')
  return typeof hit?.days === 'number' ? hit.days : null
}

export function badgeInputFromIntimate(p: IntimatePosterPayload): BadgeInput {
  return {
    total: p.stats.total,
    selfCount: p.stats.self_count,
    otherCount: p.stats.other_count,
    activeDays: p.stats.active_days,
    spanDays: p.stats.span_days,
    lateNightCount: p.story?.chemistry.late_night?.count ?? null,
    replyQuickSeconds: p.story?.chemistry.reply_stats?.median ?? null,
    replyCount: p.story?.chemistry.reply_stats?.count ?? null,
    userRatio: p.story?.chemistry.initiator?.user_ratio ?? null,
    topAll: p.top_words.all.map((w) => w.word),
    topMine: p.top_words.me.map((w) => w.word),
    topOther: p.top_words.other.map((w) => w.word),
    streakDays: p.activity?.insights.streak_days ?? null,
    silenceDays: silenceDaysFrom(p.story?.milestones || []),
  }
}

export function badgeInputFromPublic(p: PublicPosterPayload): BadgeInput {
  return {
    total: p.stats.total,
    selfCount: p.stats.self_count,
    otherCount: p.stats.other_count,
    activeDays: p.stats.active_days,
    spanDays: p.stats.span_days,
    lateNightCount: p.story?.chemistry.late_night?.count ?? null,
    replyQuickSeconds: p.story?.chemistry.reply_stats?.median ?? null,
    replyCount: p.story?.chemistry.reply_stats?.count ?? null,
    userRatio: p.story?.chemistry.initiator?.user_ratio ?? null,
    topAll: p.top_words.all.map((w) => w.word),
    topMine: p.top_words.me.map((w) => w.word),
    topOther: p.top_words.other.map((w) => w.word),
    streakDays: p.activity?.insights.streak_days ?? null,
    silenceDays: silenceDaysFrom(p.story?.milestones || []),
  }
}

/** 自我版：total 以我的条数计，联合指标（对方侧/主动比/双方中位/沉默期）全 null */
export function badgeInputFromSelf(p: SelfPosterPayload): BadgeInput {
  const words = p.my_words.map((w) => w.word)
  return {
    total: p.stats.self_count,
    selfCount: p.stats.self_count,
    otherCount: 0,
    activeDays: p.stats.active_days,
    spanDays: p.stats.span_days,
    lateNightCount: p.my_story.late_night_self,
    // 自我版无中位切片：以均值近似秒回判据（阈值同 120s，非冒充中位）
    replyQuickSeconds: p.my_story.reply_self_avg_seconds,
    replyCount: null,
    userRatio: null,
    topAll: words,
    topMine: words,
    topOther: [],
    streakDays: p.my_activity?.insights.streak_days ?? null,
    silenceDays: null,
  }
}

function pct(value: number): number {
  return Math.round(value * 100)
}

export function pickPosterBadge(input: BadgeInput, audience: PosterAudience): PosterBadge {
  const { total, selfCount, otherCount, activeDays, spanDays } = input

  // 1 深夜守望者：深夜占比 ≥8% 或 ≥300 句
  const late = input.lateNightCount
  if (late != null && ((total > 0 && late / total >= 0.08) || late >= 300)) {
    if (audience === 'self') {
      return { id: 'night-owl', title: '深夜守望者', caption: `凌晨 0-5 点，你说过 ${late} 句话` }
    }
    const ratioText = total > 0 ? `，占全部对话的 ${pct(late / total)}%` : ''
    return {
      id: 'night-owl',
      title: '深夜守望者',
      caption: audience === 'intimate'
        ? `凌晨的对话框为你们亮着——深夜消息 ${late} 句${ratioText}`
        : `深夜的对话有 ${late} 句${ratioText}`,
    }
  }

  // 2 秒回拍档：回复用时 ≤2 分钟且样本 ≥30 条（定向/公开判中位，自我版均值近似）
  const quickSeconds = input.replyQuickSeconds
  if (quickSeconds != null && quickSeconds <= 120 && (input.replyCount ?? 0) >= 30) {
    return {
      id: 'quick-reply',
      title: '秒回拍档',
      caption: audience === 'intimate'
        ? `中位回复 ${Math.round(quickSeconds)} 秒，话题从不断档`
        : '回复常常不到两分钟，话题从不断档',
    }
  }

  // 3 势均力敌：双方条数比 ≥0.8 且总量 ≥1000
  const maxSide = Math.max(selfCount, otherCount)
  if (total >= 1000 && maxSide > 0 && Math.min(selfCount, otherCount) / maxSide >= 0.8) {
    return {
      id: 'evenly-matched',
      title: '势均力敌',
      caption: audience === 'intimate'
        ? `${pct(selfCount / total)}% 对 ${pct(otherCount / total)}%，谁也不让谁`
        : '双方消息量几乎对半，谁也不让谁',
    }
  }

  // 4 日日常驻：活跃率 ≥85% 且跨度 ≥30 天
  if (spanDays >= 30 && activeDays / spanDays >= 0.85) {
    return {
      id: 'daily-regular',
      title: '日日常驻',
      caption: `在 ${spanDays} 天的跨度里，${activeDays} 天都有消息`,
    }
  }

  // 5 先声夺人：一方发起比 ≥65% 或 ≤35%（公开版中性措辞）
  const ratio = input.userRatio
  if (ratio != null && (ratio >= 0.65 || ratio <= 0.35)) {
    if (audience === 'intimate') {
      return {
        id: 'conversation-opener',
        title: '先声夺人',
        caption: ratio >= 0.65 ? '多数话题由你先开口' : '多数话题由 TA 先开口',
      }
    }
    return { id: 'conversation-opener', title: '先声夺人', caption: '总有人先开口，把话题接住' }
  }

  // 6 长跑搭档：跨度 ≥365 天
  if (spanDays >= 365) {
    return {
      id: 'long-run',
      title: '长跑搭档',
      caption: `对话跨度 ${spanDays} 天，已满一年还在继续`,
    }
  }

  // 7 万语千言：总量 ≥10000
  if (total >= 10000) {
    return {
      id: 'ten-thousand',
      title: '万语千言',
      caption: audience === 'self' ? `你写下了 ${total} 条消息` : `${total} 条消息的对话`,
    }
  }

  // 8 同频共振：榜首词同现双方前 5
  const shared = input.topAll[0]
  if (
    shared
    && input.topMine.slice(0, 5).includes(shared)
    && input.topOther.slice(0, 5).includes(shared)
  ) {
    return {
      id: 'resonance',
      title: '同频共振',
      caption: `「${shared}」同时挂在你们嘴边`,
    }
  }

  return { id: 'collector', title: '时光收藏家', caption: '每一段对话，都值得被收藏' }
}

/** 副称号成就清单：极值触发全列出（非首中），门槛比主称号规则更苛刻——
 *  主称号是「这段对话是谁」，副称号是「它有多极端」 */
export function posterSubBadges(input: BadgeInput, audience: PosterAudience): SubBadge[] {
  const badges: SubBadge[] = []
  const isSelf = audience === 'self'

  const streak = input.streakDays
  if (streak != null && streak >= 21) {
    badges.push({
      id: 'never-absent',
      title: '不缺席者',
      grade: streak >= 180 ? 3 : streak >= 60 ? 2 : 1,
      note: isSelf ? `你连续 ${streak} 天都在说话` : `连续 ${streak} 天，每天都有对话`,
    })
  }

  const late = input.lateNightCount
  if (late != null && late >= 500) {
    badges.push({
      id: 'night-walker',
      title: '夜行者',
      grade: late >= 5000 ? 3 : late >= 2000 ? 2 : 1,
      note: `${formatCount(late)} 条消息发在凌晨 0-5 点`,
    })
  }

  const quick = input.replyQuickSeconds
  if (quick != null && quick <= 90 && (input.replyCount ?? 0) >= 30) {
    badges.push({
      id: 'flash-reply',
      title: '秒回选手',
      grade: quick <= 20 ? 3 : quick <= 45 ? 2 : 1,
      note: isSelf
        ? `平均 ${Math.round(quick)} 秒就回`
        : `中位 ${Math.round(quick)} 秒就回`,
    })
  }

  const ratio = input.userRatio
  if (!isSelf && ratio != null && (ratio >= 0.7 || ratio <= 0.3)) {
    const leadShare = Math.round(Math.max(ratio, 1 - ratio) * 100)
    badges.push({
      id: 'icebreaker',
      title: '破冰人',
      grade: leadShare >= 90 ? 3 : leadShare >= 80 ? 2 : 1,
      note: audience === 'intimate'
        ? ratio >= 0.7
          ? `${leadShare}% 的话题由你先开口`
          : `${leadShare}% 的话题由 TA 先开口`
        : `${leadShare}% 的话题由同一个人先开口`,
    })
  }

  if (input.spanDays >= 730) {
    badges.push({
      id: 'long-haul',
      title: '长跑搭档',
      grade: input.spanDays >= 3650 ? 3 : input.spanDays >= 1825 ? 2 : 1,
      note: `对话跨度 ${formatCount(input.spanDays)} 天`,
    })
  }

  const volume = isSelf ? input.selfCount : input.total
  if (volume >= 10000) {
    badges.push({
      id: 'prolific',
      title: '笔耕不辍',
      grade: volume >= 100000 ? 3 : volume >= 50000 ? 2 : 1,
      note: `${formatCount(volume)} 条消息`,
    })
  }

  return badges
}

/** 稀有度话术：锚定会话内相对事实（沉默后重开/体量换算/年头跨度），
 *  上限 3 条——多了稀释，称号幕要留白 */
export function posterRarityLines(input: BadgeInput, audience: PosterAudience): string[] {
  const lines: string[] = []

  const silence = input.silenceDays
  if (silence != null && silence >= 14) {
    lines.push(`沉默过 ${Math.round(silence)} 天，后来还有人先开了口`)
  }

  const volume = audience === 'self' ? input.selfCount : input.total
  if (volume >= 20000) {
    const hours = (volume * 2) / 3600
    const span = hours >= 48 ? `不眠不休 ${(hours / 24).toFixed(1)} 天` : `整整 ${Math.round(hours)} 小时`
    lines.push(
      audience === 'self'
        ? `你写下的 ${formatCount(volume)} 条，逐条读 2 秒要 ${span}`
        : `${formatCount(volume)} 条消息逐条读 2 秒，要 ${span}`,
    )
  }

  const years = Math.floor(input.spanDays / 365)
  if (years >= 2) {
    lines.push(`这段对话前后跨越了 ${years} 个年头`)
  }

  return lines.slice(0, 3)
}
