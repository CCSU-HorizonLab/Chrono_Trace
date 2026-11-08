/**
 * 海报 SSR 渲染探针（由 poster.render.test.mjs 经 vite ssrLoadModule 执行）：
 * 以全量 fixture（每个 v-if 分支都有数据）+ 稀疏 fixture（可选分镜全缺）
 * 服务端渲染三模板与三方卡，返回 HTML 供锚点/脱敏断言。
 *
 * 背景：模板渲染抛错时 Vue 会静默卸载子树，build 与令牌冒烟都抓不住
 * （SquareCard 'accent'、intimate 'counts.length' 两起线上空白事故）——
 * 此处在 node 里真跑一遍 renderToString，渲染即验证。
 */
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import {
  sanitizeForPublic,
  sanitizeForSelf,
  type IntimatePosterPayload,
  type IntimateReportPayload,
} from '../src/components/deep/poster/registry'
import PosterPublicMinimal from '../src/components/deep/poster/templates/PosterPublicMinimal.vue'
import PosterSelfPortrait from '../src/components/deep/poster/templates/PosterSelfPortrait.vue'
import PosterIntimateDuo from '../src/components/deep/poster/templates/PosterIntimateDuo.vue'
import ReportPublicLong from '../src/components/deep/poster/templates/ReportPublicLong.vue'
import ReportIntimateLong from '../src/components/deep/poster/templates/ReportIntimateLong.vue'
import SquareCard from '../src/components/deep/poster/SquareCard.vue'
import { POSTER_THEMES } from '../src/components/deep/poster/theme'
import { formatCount } from '../src/components/deep/poster/activityShared'
import {
  badgeInputFromIntimate,
  badgeInputFromPublic,
  badgeInputFromSelf,
  pickPosterBadge,
  posterSubBadges,
} from '../src/components/deep/poster/badges'

const CONTACT_NAME = '测试联系人'
const QUOTE_TEXT = '这是一句只属于我们的暗号'

/** 全量 fixture：story/activity/big5/quotes 全在场，grid 7×24 且峰值在深夜 */
function fullPayload(): IntimatePosterPayload {
  const grid = Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, (_, h) => (h >= 22 || h < 2 ? 9 : h >= 19 ? 4 : 1)),
  )
  return {
    ok: true,
    version: 1,
    conversation_id: 1,
    from_ts: 1579000000,
    to_ts: 1700000000,
    contact: { display_name: CONTACT_NAME, avatar: null, sensitive: true },
    stats: { total: 40530, self_count: 21010, other_count: 19520, active_days: 684, span_days: 2806 },
    emotion_curve: {
      bucket: 'month',
      points: Array.from({ length: 12 }, (_, i) => ({
        ts: `2024-${String(i + 1).padStart(2, '0')}`,
        score: 0.3 + i * 0.05,
        userScore: 0.2 + i * 0.06,
        otherScore: 0.4 + i * 0.04,
        msgCount: 100 + i * 10,
      })),
    },
    top_words: {
      all: [
        { word: '哈哈哈哈', weight: 99 },
        { word: '好的', weight: 80 },
        { word: '嗯嗯', weight: 60 },
      ],
      me: [{ word: '收到', weight: 90 }, { word: '走呀', weight: 70 }],
      other: [{ word: '晚安', weight: 95 }, { word: '无聊', weight: 65 }],
    },
    quotes: {
      items: [
        { text: QUOTE_TEXT, is_sender: false, ts: 1590000000 },
        { text: '明天见', is_sender: true, ts: 1590003600 },
      ],
      sensitive: true,
    },
    big5: {
      me: {
        source: 'local',
        scores: {
          openness: { score: 0.72 },
          conscientiousness: { score: 0.55 },
          extraversion: { score: 0.4 },
          agreeableness: { score: 0.66 },
          neuroticism: { score: 0.3 },
        },
      },
      other: {
        source: 'local',
        scores: {
          openness: { score: 0.5 },
          conscientiousness: { score: 0.62 },
          extraversion: { score: 0.58 },
          agreeableness: { score: 0.44 },
          neuroticism: { score: 0.48 },
        },
      },
    },
    story: {
      milestones: [
        { kind: 'first_message', ts: 1579000000, scope: 'global' },
        { kind: 'count_mark', ts: 1600000000, mark: 10000 },
        { kind: 'longest_silence', ts: 1610000000, days: 30, from_ts: 1609000000, to_ts: 1611596400 },
      ],
      chemistry: {
        late_night: { count: 321, self_count: 180, other_count: 141 },
        peak_day: { date: '2020-05-20', count: 512, self_count: 300, other_count: 212 },
        reply_stats: { count: 1387, avg: 1438.2, median: 44, self_avg: 61.5, other_avg: 1438.2 },
        initiator: { user_sessions: 80, other_sessions: 120, user_ratio: 0.4 },
      },
    },
    activity: {
      grid: { all: grid, me: grid, max_all: 9, max_me: 9 },
      calendar: {
        year: 2024,
        days: Array.from({ length: 366 }, (_, i) => ({
          date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
          count: (i % 60) + 1,
          self_count: (i % 30) + 1,
        })),
        max: 60,
      },
      insights: {
        streak_days: 21,
        self_streak_days: 12,
        question: { total: 40530, questions: 4000 },
        self_question: { total: 21010, questions: 2100 },
      },
    },
    generated_at: 1730000000,
  }
}

/** 稀疏 fixture：story/activity/quotes/big5 全缺——分镜逐项 v-if 降级不能抛错 */
function sparsePayload(): IntimatePosterPayload {
  const base = fullPayload()
  return {
    ...base,
    story: undefined,
    activity: undefined,
    quotes: { items: [], sensitive: true },
    big5: { me: null, other: null },
  }
}

function squareSpecFor(aud: 'public' | 'self' | 'intimate') {
  const p = fullPayload()
  const input =
    aud === 'intimate'
      ? badgeInputFromIntimate(p)
      : aud === 'self'
        ? badgeInputFromSelf(sanitizeForSelf(p))
        : badgeInputFromPublic(sanitizeForPublic(p))
  const theme = POSTER_THEMES[aud]
  return {
    bg: theme.bgGradient,
    palette: theme.palette,
    eyebrow: aud === 'intimate' ? '你们的称号' : aud === 'self' ? '你的称号' : '这段对话的称号',
    badge: pickPosterBadge(input, aud),
    subBadges: posterSubBadges(input, aud),
    heroNum: formatCount(aud === 'self' ? p.stats.self_count : p.stats.total),
    heroUnit: '条消息',
    heroCaption: `跨度 ${formatCount(p.stats.span_days)} 天`,
    miniStats: [
      { num: '2,806 天', label: '跨度' },
      { num: '684 天', label: '活跃' },
      { num: '44 秒', label: '中位回复' },
    ],
    wordChips: ['哈哈哈哈', '好的', '嗯嗯'],
    wordsLabel: '聊得最多的词',
    names: aud === 'intimate' ? { left: CONTACT_NAME, right: '我' } : aud === 'self' ? { left: '我' } : undefined,
    yearText: '2024',
    qr: aud === 'public',
  }
}

async function render(vnode: ReturnType<typeof h>): Promise<string> {
  const app = createSSRApp({ render: () => vnode })
  return renderToString(app)
}

/** 全量渲染：三模板 + 三方卡，键名即断言锚点 */
export async function renderFull(): Promise<Record<string, string>> {
  const p = fullPayload()
  const [intimate, publicLong, selfLong, sqPublic, sqSelf, sqIntimate] = await Promise.all([
    render(h(PosterIntimateDuo, { payload: p })),
    render(h(PosterPublicMinimal, { payload: sanitizeForPublic(p) })),
    render(h(PosterSelfPortrait, { payload: sanitizeForSelf(p) })),
    render(h(SquareCard, { spec: squareSpecFor('public') })),
    render(h(SquareCard, { spec: squareSpecFor('self') })),
    render(h(SquareCard, { spec: squareSpecFor('intimate') })),
  ])
  return { intimate, publicLong, selfLong, sqPublic, sqSelf, sqIntimate }
}

/** 稀疏渲染：可选分镜全缺时三模板仍需成图（降级路径） */
export async function renderSparse(): Promise<Record<string, string>> {
  const p = sparsePayload()
  const [intimate, publicLong, selfLong] = await Promise.all([
    render(h(PosterIntimateDuo, { payload: p })),
    render(h(PosterPublicMinimal, { payload: sanitizeForPublic(p) })),
    render(h(PosterSelfPortrait, { payload: sanitizeForSelf(p) })),
  ])
  return { intimate, publicLong, selfLong }
}

/** fixture 内嵌的敏感串：公开/自我版 HTML 不得出现（脱敏红线断言用） */
export const SENSITIVE_MARKERS = [CONTACT_NAME, QUOTE_TEXT] as const

// ----------------------------------------------------------------------
// 年度报告 / 纪念册：定向版给完整 payload，公开版模板内部走
// sanitizeReportForPublic 投影（生产同路径——探针喂原始 payload 即测投影）
// ----------------------------------------------------------------------

const UNSAFE_MEME = '望京路88号' // 含实体形短语，后端会标 public_safe: false
const TEMP_LABEL = '炽热'

/** 自选跨年窗口（纪念册）：定向版封面印日期段「2021.06 - 2023.11」，
 *  公开版投影只剩「N 天」跨度与滤标后的梗 */
function reportPayload(): IntimateReportPayload {
  return {
    ok: true,
    kind: 'report',
    version: 1,
    conversation_id: 1,
    from_ts: 1622505600, // 2021-06-01
    to_ts: 1700448000, // 2023-11-20
    contact: { display_name: CONTACT_NAME, avatar: null, sensitive: true },
    stats: { total: 40530, self_count: 21010, other_count: 19520, active_days: 684, span_days: 902 },
    top_words: {
      all: [
        { word: '哈哈哈哈', weight: 99 },
        { word: '好的', weight: 80 },
        { word: '嗯嗯', weight: 60 },
      ],
      me: [{ word: '收到', weight: 90 }],
      other: [{ word: '晚安', weight: 95 }],
    },
    story: fullPayload().story,
    report: {
      chars: 512340,
      temperature: { score: 82, label: TEMP_LABEL },
      memes: [
        { text: '笑死我了', count: 87, me: 41, ta: 46, public_safe: true },
        { text: '小笨蛋', count: 64, me: 12, ta: 52, public_safe: true },
        { text: UNSAFE_MEME, count: 31, me: 20, ta: 11, public_safe: false },
      ],
      emoji: {
        top_me: [
          { key: '[呲牙]', kind: 'builtin', count: 812 },
          { key: '😂', kind: 'unicode', count: 233 },
        ],
        top_ta: [
          { key: '[捂脸]', kind: 'builtin', count: 745 },
          { key: '🥰', kind: 'unicode', count: 198 },
        ],
        custom_count: 1204,
        peak_label: '晚上十点后',
      },
      rhythm: { morning_days: 214, morning_by_me: 120, night_days: 189, night_by_me: 99 },
      streak_days: 45,
    },
    generated_at: 1730000000,
  }
}

/** 年度窗口（整 2025 年）：公开版封面大字允许留年份（年份即报告主题） */
function reportPayloadYear(): IntimateReportPayload {
  return {
    ...reportPayload(),
    from_ts: 1735689600, // 2025-01-01
    to_ts: 1766630400, // 2025-12-25
    stats: { ...reportPayload().stats, span_days: 358 },
  }
}

/** 年报渲染：定向版 + 公开版（自选窗口/年度窗口），键名即断言锚点 */
export async function renderReport(): Promise<Record<string, string>> {
  const [intimate, publicCustom, publicYear] = await Promise.all([
    render(h(ReportIntimateLong, { payload: reportPayload() })),
    render(h(ReportPublicLong, { payload: reportPayload() })),
    render(h(ReportPublicLong, { payload: reportPayloadYear() })),
  ])
  return { intimate, publicCustom, publicYear }
}

/** 年报 fixture 的敏感串：公开版 HTML 不得出现（姓名/温度标签/日期段/
 *  不安全梗/峰值日历日）；年份大字不在其列（报告主题） */
export const REPORT_SENSITIVE_MARKERS = [
  CONTACT_NAME,
  TEMP_LABEL,
  UNSAFE_MEME,
  '2021.06',
  '2023.11',
  '2020-05-20',
] as const
