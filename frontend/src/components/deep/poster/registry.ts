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

export type PosterBig5Scores = Record<string, { score: number | null; label?: string }> | null

/** 里程碑事件（story.milestones 元素）：口径同时光深度页签，纯统计无身份 */
export type PosterMilestone = {
  kind: 'first_message' | 'count_mark' | 'longest_silence'
  ts: number
  scope?: 'global' | 'window' // first_message 专有
  mark?: number // count_mark 专有：第 N 条关口
  days?: number // longest_silence 专有：沉默天数
  from_ts?: number
  to_ts?: number
}

/** 默契统计（story.chemistry）：逐字段独立降级 null，模板 v-if 跳分镜 */
export type PosterChemistry = {
  late_night: { count: number; self_count: number; other_count: number } | null
  peak_day: { date: string; count: number; self_count: number; other_count: number } | null
  reply_stats: {
    count: number
    avg: number
    median: number | null
    self_avg: number | null
    other_avg: number | null
  } | null
  initiator: {
    user_sessions: number
    other_sessions: number
    user_ratio: number | null
  } | null
}

/** 故事化分镜数据：纯聚合统计（无姓名/头像/原文），核心分镜零依赖分析产物 */
export type PosterStory = {
  milestones: PosterMilestone[]
  chemistry: PosterChemistry
}

/** activity 分镜（完整档）：7×24 作息格（all/me 分侧）、最活跃年年历、衍生判据 */
export type PosterActivity = {
  grid: { all: number[][]; me: number[][]; max_all: number; max_me: number }
  /** 窗内最活跃年的逐日计数（绝对日期——公开版投影剥离，自我版只取我的列） */
  calendar: {
    year: number
    days: Array<{ date: string; count: number; self_count: number }>
    max: number
  } | null
  insights: {
    streak_days: number | null
    self_streak_days: number | null
    question: { total: number; questions: number } | null
    self_question: { total: number; questions: number } | null
  }
}

/** 公开版 activity：合并作息格（无绝对日期）+ 联合判据；年历/单侧格类型上拿不到 */
export type PublicPosterActivity = {
  grid: { counts: number[][]; max: number }
  insights: { streak_days: number | null; question: { total: number; questions: number } | null }
}

/** 自我版 activity：我的作息格 + 我的年历（日期属我本人数据，可带）+ 单侧判据 */
export type SelfPosterActivity = {
  grid: { counts: number[][]; max: number }
  calendar: { year: number; days: Array<{ date: string; count: number }>; max: number } | null
  insights: { streak_days: number | null; question: { total: number; questions: number } | null }
}

/** 公开版里程碑：不带绝对日期——首条消息/关口/沉默期是全会话口径，日期
 *  会突破用户所选导出窗，公开域组合（首条日期+沉默叙事+峰值日）具强识别性 */
export type PublicPosterMilestone = Omit<PosterMilestone, 'ts' | 'from_ts' | 'to_ts'>

/** 公开版默契统计：峰值日只留条数不带日历日期（深夜/回复/主动比本就无日期） */
export type PublicPosterChemistry = {
  late_night: PosterChemistry['late_night']
  peak_day: { count: number; self_count: number; other_count: number } | null
  reply_stats: PosterChemistry['reply_stats']
  initiator: PosterChemistry['initiator']
}

/** 公开版故事：时间线只讲事件不讲哪天（定向/自我版保留日期） */
export type PublicPosterStory = {
  milestones: PublicPosterMilestone[]
  chemistry: PublicPosterChemistry
}

/** 自我版故事切片：仅我的单侧指标——联合事件（主动比/双方中位回复）不进 my 切片 */
export type MyPosterStory = {
  late_night_self: number | null
  reply_self_avg_seconds: number | null
}

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
  quotes: { items: Array<{ text: string; is_sender: boolean; ts: number }>; sensitive: true }
  big5: { me: { source: string; scores: PosterBig5Scores } | null; other: { source: string; scores: PosterBig5Scores } | null }
  story?: PosterStory
  activity?: PosterActivity
  generated_at: number
}

/** 公开/自我版 payload：白名单投影，无对方姓名、头像、原文引用 */
export type PublicPosterPayload = {
  version: number
  stats: PosterStats
  emotion_curve: { bucket: string; points: PosterCurvePoint[] }
  top_words: { all: PosterWord[]; me: PosterWord[]; other: PosterWord[] }
  big5: { me: { scores: PosterBig5Scores } | null; other: { scores: PosterBig5Scores } | null }
  /** story 聚合字段进公开版但剥绝对日期（类型上拿不到日期字段） */
  story?: PublicPosterStory
  /** activity 只进合并作息格与联合判据（无绝对日期）；年历/单侧格剥离 */
  activity?: PublicPosterActivity
  generated_at: number
}

/** 自我版曲线点：仅我的分数——类型上不存在 otherScore/合并 score，模板无法引用对方序列 */
export type SelfCurvePoint = { ts: string; userScore: number | null }

/** 自我版 payload：只含 me 切片，零对方元素 */
export type SelfPosterPayload = {
  version: number
  stats: { self_count: number; active_days: number; span_days: number }
  my_curve: SelfCurvePoint[]
  my_words: PosterWord[]
  my_big5: PosterBig5Scores
  my_story: MyPosterStory
  /** activity 只进我的作息格/我的年历/单侧判据（联合口径不进自我版红线） */
  my_activity?: SelfPosterActivity
  generated_at: number
}

/** 唯一的公开版构造入口：白名单投影（丢弃 contact/quotes，big5 只留分数） */
export function sanitizeForPublic(payload: IntimatePosterPayload): PublicPosterPayload {
  return {
    version: payload.version,
    stats: payload.stats,
    emotion_curve: payload.emotion_curve,
    top_words: payload.top_words,
    big5: {
      me: payload.big5?.me ? { scores: payload.big5.me.scores } : null,
      other: payload.big5?.other ? { scores: payload.big5.other.scores } : null,
    },
    // story 聚合字段进公开版，但逐项剥绝对日期：里程碑去 ts/from_ts/to_ts、
    // 峰值日去 date——公开版零具体日历日期（时间线只讲事件不讲哪天）
    story: payload.story
      ? {
          milestones: payload.story.milestones.map(
            ({ ts: _ts, from_ts: _fromTs, to_ts: _toTs, ...rest }) => rest,
          ),
          chemistry: {
            late_night: payload.story.chemistry.late_night,
            peak_day: payload.story.chemistry.peak_day
              ? {
                  count: payload.story.chemistry.peak_day.count,
                  self_count: payload.story.chemistry.peak_day.self_count,
                  other_count: payload.story.chemistry.peak_day.other_count,
                }
              : null,
            reply_stats: payload.story.chemistry.reply_stats,
            initiator: payload.story.chemistry.initiator,
          },
        }
      : undefined,
    // activity 投影：合并作息格（周几×时辰，无绝对日期）+ 联合判据；
    // 年历带日历日期、me 格带单侧数据——均在类型层剥离
    activity: payload.activity
      ? {
          grid: { counts: payload.activity.grid.all, max: payload.activity.grid.max_all },
          insights: {
            streak_days: payload.activity.insights.streak_days,
            question: payload.activity.insights.question,
          },
        }
      : undefined,
    generated_at: payload.generated_at,
  }
}

/** 唯一的自我版构造入口：me 切片投影（我的曲线点、me 词、big5.me） */
export function sanitizeForSelf(payload: IntimatePosterPayload): SelfPosterPayload {
  return {
    version: payload.version,
    stats: {
      self_count: payload.stats.self_count,
      active_days: payload.stats.active_days,
      span_days: payload.stats.span_days,
    },
    // 逐点投影只留 userScore——直接传整个 point 会把 otherScore 与合并
    // score 带进自我版类型，违背"类型上拿不到对方数据"的红线
    my_curve: payload.emotion_curve.points.map((p) => ({ ts: p.ts, userScore: p.userScore ?? null })),
    my_words: payload.top_words.me,
    my_big5: payload.big5?.me?.scores || null,
    // 单侧派生切片：深夜句数取 self_count、回复速度取 self_avg——联合
    // 口径（主动比/双方中位）不进自我版红线
    my_story: {
      late_night_self: payload.story?.chemistry.late_night?.self_count ?? null,
      reply_self_avg_seconds: payload.story?.chemistry.reply_stats?.self_avg ?? null,
    },
    // activity 单侧切片：作息格/年历/判据全部换成我的口径（年历日期属
    // 我本人数据可保留，count 已映射为 self_count）
    my_activity: payload.activity
      ? {
          grid: { counts: payload.activity.grid.me, max: payload.activity.grid.max_me },
          calendar: payload.activity.calendar
            ? {
                year: payload.activity.calendar.year,
                days: payload.activity.calendar.days.map((d) => ({
                  date: d.date,
                  count: d.self_count,
                })),
                max: Math.max(0, ...payload.activity.calendar.days.map((d) => d.self_count)),
              }
            : null,
          insights: {
            streak_days: payload.activity.insights.self_streak_days,
            question: payload.activity.insights.self_question,
          },
        }
      : undefined,
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
    description: '聚合数字串成的故事长图，无姓名头像与原文，适合朋友圈',
    audience: 'public',
    sensitive: false,
    component: PosterPublicMinimal,
  },
  {
    id: 'self-portrait',
    label: '自我画像',
    description: '只关于你的故事：你的数字、你的词、你的语气曲线',
    audience: 'self',
    sensitive: false,
    component: PosterSelfPortrait,
  },
  {
    id: 'intimate-duo',
    label: '定向发送',
    description: '星夜叙事长图：双方姓名、头像与聊天摘录，仅适合发给对方',
    audience: 'intimate',
    sensitive: true,
    component: PosterIntimateDuo,
  },
]
