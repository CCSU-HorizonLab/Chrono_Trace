/**
 * 分享海报类型与模板注册表。
 *
 * 脱敏责任边界（硬约束，不靠用户自觉）：
 * - IntimatePosterPayload：完整 payload（含对方姓名/头像/金句），仅定向版模板可消费；
 * - PublicPosterPayload：sanitizeForPublic() 白名单投影是唯一构造入口——
 *   类型上不存在 display_name(对方)/avatar(对方)/quotes 字段，公开版与
 *   自我版模板在类型层面就拿不到敏感字段。
 */
import type { Component } from 'vue'
import PosterPublicMinimal from './templates/PosterPublicMinimal.vue'
import PosterIntimateDuo from './templates/PosterIntimateDuo.vue'
import PosterSelfPortrait from './templates/PosterSelfPortrait.vue'

export type PosterWord = { word: string; weight: number }

export type PosterStats = {
  total: number
  self_count: number
  other_count: number
  active_days: number
  span_days: number
}

export type PosterCurvePoint = {
  ts: string
  score: number | null
  userScore?: number | null
  otherScore?: number | null
  msgCount?: number
}

export type PosterMilestone = {
  kind: string
  ts: number
  scope?: string
  mark?: number
  days?: number
}

export type PosterBig5Scores = Record<string, { score: number | null; label?: string }> | null

/** 完整 payload（定向版专属；敏感字段集中在 contact 与 quotes） */
export type IntimatePosterPayload = {
  ok: boolean
  version: number
  conversation_id: number
  from_ts: number
  to_ts: number
  contact: { display_name: string; avatar: string | null; sensitive: true }
  stats: PosterStats
  emotion_curve: { bucket: string; points: PosterCurvePoint[] }
  top_words: { all: PosterWord[]; me: PosterWord[]; other: PosterWord[] }
  milestones: PosterMilestone[]
  quotes: { items: Array<{ text: string; is_sender: boolean; ts: number }>; sensitive: true }
  big5: { me: { source: string; scores: PosterBig5Scores } | null; other: { source: string; scores: PosterBig5Scores } | null }
  generated_at: number
}

/** 公开/自我版 payload：白名单投影，无对方姓名、头像、原文引用 */
export type PublicPosterPayload = {
  version: number
  stats: PosterStats
  emotion_curve: { bucket: string; points: PosterCurvePoint[] }
  top_words: { all: PosterWord[]; me: PosterWord[]; other: PosterWord[] }
  milestones: PosterMilestone[]
  big5: { me: { scores: PosterBig5Scores } | null; other: { scores: PosterBig5Scores } | null }
  generated_at: number
}

/** 自我版 payload：只含 me 切片，零对方元素 */
export type SelfPosterPayload = {
  version: number
  stats: { self_count: number; active_days: number; span_days: number }
  my_curve: PosterCurvePoint[]
  my_words: PosterWord[]
  my_big5: PosterBig5Scores
  milestones: PosterMilestone[]
  generated_at: number
}

/** 唯一的公开版构造入口：白名单投影（丢弃 contact/quotes，big5 只留分数） */
export function sanitizeForPublic(payload: IntimatePosterPayload): PublicPosterPayload {
  return {
    version: payload.version,
    stats: payload.stats,
    emotion_curve: payload.emotion_curve,
    top_words: payload.top_words,
    milestones: payload.milestones,
    big5: {
      me: payload.big5?.me ? { scores: payload.big5.me.scores } : null,
      other: payload.big5?.other ? { scores: payload.big5.other.scores } : null,
    },
    generated_at: payload.generated_at,
  }
}

/** 唯一的自我版构造入口：me 切片投影（userScore 序列、me 词、big5.me、里程碑） */
export function sanitizeForSelf(payload: IntimatePosterPayload): SelfPosterPayload {
  return {
    version: payload.version,
    stats: {
      self_count: payload.stats.self_count,
      active_days: payload.stats.active_days,
      span_days: payload.stats.span_days,
    },
    my_curve: payload.emotion_curve.points,
    my_words: payload.top_words.me,
    my_big5: payload.big5?.me?.scores || null,
    milestones: payload.milestones,
    generated_at: payload.generated_at,
  }
}

export type PosterAudience = 'public' | 'intimate' | 'self'

export type PosterTemplate = {
  id: string
  label: string
  description: string
  audience: PosterAudience
  /** 含对方姓名/头像/原文的模板：导出前需确认 */
  sensitive: boolean
  component: Component
}

export const POSTER_TEMPLATES: PosterTemplate[] = [
  {
    id: 'public-minimal',
    label: '公开分享',
    description: '只含聚合数字与氛围，无姓名头像与原文，适合朋友圈',
    audience: 'public',
    sensitive: false,
    component: PosterPublicMinimal,
  },
  {
    id: 'self-portrait',
    label: '自我画像',
    description: '只关于你的年度语言画像，想了解自己也能分享',
    audience: 'self',
    sensitive: false,
    component: PosterSelfPortrait,
  },
  {
    id: 'intimate-duo',
    label: '定向发送',
    description: '含双方姓名、头像与聊天摘录，仅适合发给对方',
    audience: 'intimate',
    sensitive: true,
    component: PosterIntimateDuo,
  },
]
