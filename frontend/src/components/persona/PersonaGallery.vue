<template>
  <div class="persona-gallery">
    <div v-if="loading" class="persona-gallery-empty">
      <div class="persona-gallery-icon">⏳</div>
      <p>正在读取这位联系人的画像档案...</p>
    </div>

    <div v-else-if="!hasProfile" class="persona-gallery-empty">
      <div class="persona-gallery-icon">🖼️</div>
      <p>这位联系人还没有可展示的 AI 画像。</p>
      <span>先在 AI 建议页生成联系人画像，回廊就会自动点亮。</span>
    </div>

    <template v-else>
      <PersonaTagsCard
        :title="heroTitle"
        :summary="heroSummary"
        :note="heroNote"
        :tags="heroTags"
        :meta-items="heroMeta"
      />

      <div class="persona-grid">
        <TopicUniverse :topics="topicBubbles" />
        <EmotionSpectrum :items="emotionBands" />
      </div>

      <CtCard class="persona-panel milestone-panel">
        <template #header>
          <span>记忆相框</span>
        </template>

        <div v-if="milestones.length" class="milestone-grid">
          <MilestoneFrame
            v-for="milestone in milestones"
            :key="`${milestone.title}-${milestone.dateLabel}`"
            :title="milestone.title"
            :date-label="milestone.dateLabel"
            :body="milestone.body"
            :accent="milestone.accent"
          />
        </div>
        <div v-else class="persona-empty-mini">当前还不足以拼出关键互动瞬间</div>
      </CtCard>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PropType } from 'vue'
import CtCard from '@/components/base/CtCard.vue'
import PersonaTagsCard from './PersonaTagsCard.vue'
import TopicUniverse from './TopicUniverse.vue'
import EmotionSpectrum from './EmotionSpectrum.vue'
import MilestoneFrame from './MilestoneFrame.vue'

type PersonaProfile = {
  personality_tags?: string[]
  chat_style?: string
  interests?: string[]
  relationship_note?: string
  communication_tips?: string
}

type PersonaMeta = {
  createdAt: number | null
  expiresAt: number | null
  expired: boolean
  estimatedTokens: number
}

type TimeseriesPoint = {
  ts: string
  score: number
  positive?: number
  neutral?: number
  negative?: number
}

type WordCloudPoint = {
  word: string
  weight: number
}

type SessionPoint = {
  start_time: number
  message_count: number
}

type AffinityResult = {
  overall_score?: number
  emotional_resonance?: { score: number }
  chat_positivity?: { score: number }
}

type FeatureStats = {
  avgResponseTime: number
  medianResponseTime: number
  initiativeRate: number
  wordRatio: number
}

type MilestoneItem = {
  title: string
  dateLabel: string
  body: string
  accent: string
}

const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  },
  contactName: {
    type: String,
    required: true
  },
  profile: {
    type: Object as PropType<PersonaProfile | null>,
    default: null
  },
  profileMeta: {
    type: Object as PropType<PersonaMeta>,
    required: true
  },
  analysis: {
    type: Object as PropType<{ timeseries: TimeseriesPoint[]; wordcloud: WordCloudPoint[] }>,
    required: true
  },
  analysisResult: {
    type: Object as PropType<AffinityResult | null>,
    default: null
  },
  featureStats: {
    type: Object as PropType<FeatureStats>,
    required: true
  },
  sessions: {
    type: Array as PropType<SessionPoint[]>,
    default: () => []
  },
  activityCalendarSummary: {
    type: Object as PropType<any>,
    default: null
  },
  currentRangeLabel: {
    type: String,
    default: ''
  }
})

const palette = ['#f97316', '#fb7185', '#f59e0b', '#14b8a6', '#0ea5e9', '#8b5cf6']

const hasProfile = computed(() => Boolean(props.profile))

const heroTags = computed(() => props.profile?.personality_tags?.slice(0, 6) || [])

const heroTitle = computed(() => {
  if (heroTags.value.length > 0) return heroTags.value.join(' · ')
  return `${props.contactName} 的画像档案`
})

const heroSummary = computed(() => {
  return props.profile?.chat_style || props.profile?.relationship_note || '画像已生成，但暂时没有更多摘要信息。'
})

const heroNote = computed(() => props.profile?.communication_tips || '')

const heroMeta = computed(() => {
  const items: string[] = []
  if (props.profile?.relationship_note) items.push(props.profile.relationship_note)
  if (props.analysisResult?.overall_score !== undefined) items.push(`关系评分 ${Math.round(props.analysisResult.overall_score)}%`)
  if (props.currentRangeLabel) items.push(props.currentRangeLabel)
  if (props.profileMeta.createdAt) items.push(`画像生成于 ${formatUnixDate(props.profileMeta.createdAt)}`)
  return items
})

const topicBubbles = computed(() => {
  const interests = props.profile?.interests || []
  if (interests.length) {
    return interests.slice(0, 6).map((label, index) => ({
      label,
      hint: '画像兴趣标签',
      size: 112 - index * 8,
      hue: palette[index % palette.length]
    }))
  }

  return (props.analysis.wordcloud || []).slice(0, 6).map((item, index) => ({
    label: item.word,
    hint: `关键词热度 ${Math.round(item.weight)}`,
    size: 112 - index * 8,
    hue: palette[index % palette.length]
  }))
})

const emotionBands = computed(() => {
  const points = props.analysis.timeseries || []
  const positiveAvg = average(points.map((point) => Number(point.positive || 0)))
  const neutralAvg = average(points.map((point) => Number(point.neutral || 0)))
  const negativeAvg = average(points.map((point) => Number(point.negative || 0)))
  const positivity = normalizeScore(props.analysisResult?.chat_positivity?.score)
  const resonance = normalizeScore(props.analysisResult?.emotional_resonance?.score)
  const initiative = clamp01(props.featureStats.initiativeRate || 0)

  const items = [
    {
      label: '温度感',
      value: positiveAvg || positivity,
      color: '#fb923c',
      description: positiveAvg ? '对话里的正向情绪更常作为底色出现。' : '基于聊天积极度推断，这段关系更偏暖色调。'
    },
    {
      label: '稳定感',
      value: clamp01(1 - negativeAvg),
      color: '#38bdf8',
      description: negativeAvg ? '低波动说明情绪起伏相对平稳。' : '暂时缺少明显负向样本，整体更像平缓流动。'
    },
    {
      label: '共鸣感',
      value: resonance,
      color: '#8b5cf6',
      description: '结合关系分析结果，反映彼此回应的共振强度。'
    },
    {
      label: '互动主动性',
      value: initiative,
      color: '#10b981',
      description: '从会话发起比例推断，对方主动打开话题的倾向。'
    }
  ]

  return items.filter((item) => item.value > 0)
})

const milestones = computed<MilestoneItem[]>(() => {
  const items: MilestoneItem[] = []
  const timeseries = [...(props.analysis.timeseries || [])]
  const sessions = [...(props.sessions || [])]

  if (props.profileMeta.createdAt) {
    items.push({
      title: '画像点亮时刻',
      dateLabel: formatUnixDate(props.profileMeta.createdAt),
      body: `AI 首次为 ${props.contactName} 留下这份关系侧写，之后的回廊会围绕它继续生长。`,
      accent: '#f97316'
    })
  }

  if (props.activityCalendarSummary && props.activityCalendarSummary.global_first_session_start_time) {
    items.push({
      title: '最早留痕',
      dateLabel: formatMsDate(props.activityCalendarSummary.global_first_session_start_time),
      body: '这是全纪录中能追溯到的最早一次完整互动切片。',
      accent: '#0ea5e9'
    })

    const peakSession = props.activityCalendarSummary.global_peak_session
    if (peakSession && peakSession.message_count > 0) {
      items.push({
        title: '高密度互动',
        dateLabel: formatMsDate(peakSession.start_time),
        body: `单场互动达到 ${peakSession.message_count} 条消息，是全部历史样本里互动最密集的一次。`,
        accent: '#8b5cf6'
      })
    }
  } else if (sessions.length) {
    const firstSession = sessions.reduce((min, session) => session.start_time < min.start_time ? session : min, sessions[0])
    const peakSession = sessions.reduce((max, session) => session.message_count > max.message_count ? session : max, sessions[0])

    items.push({
      title: '最早留痕',
      dateLabel: formatMsDate(firstSession.start_time),
      body: '这是当前采样样本中能追溯到的最早一次完整互动切片。',
      accent: '#0ea5e9'
    })

    if (peakSession.message_count > 0) {
      items.push({
        title: '高密度互动',
        dateLabel: formatMsDate(peakSession.start_time),
        body: `这场会话记录了 ${peakSession.message_count} 条消息，是当前最近样本里最饱满的一次交谈。`,
        accent: '#8b5cf6'
      })
    }
  }

  if (timeseries.length) {
    const highest = timeseries.reduce((max, point) => point.score > max.score ? point : max, timeseries[0])
    const lowest = timeseries.reduce((min, point) => point.score < min.score ? point : min, timeseries[0])

    items.push({
      title: '情绪高光',
      dateLabel: formatDayLabel(highest.ts),
      body: `这一天的情绪评分达到 ${highest.score.toFixed(2)}，是当前样本中的高光时刻。`,
      accent: '#10b981'
    })

    if (lowest.ts !== highest.ts) {
      items.push({
        title: '情绪转折',
        dateLabel: formatDayLabel(lowest.ts),
        body: `这一天的情绪评分降到 ${lowest.score.toFixed(2)}，可能是关系中的敏感节点。`,
        accent: '#fb7185'
      })
    }
  }

  return items.slice(0, 4)
})

function average(values: number[]) {
  const valid = values.filter((value) => Number.isFinite(value) && value > 0)
  if (!valid.length) return 0
  return clamp01(valid.reduce((sum, value) => sum + value, 0) / valid.length)
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value))
}

function normalizeScore(value?: number) {
  if (value === undefined || value === null) return 0
  return clamp01(value / 100)
}

function formatUnixDate(value: number) {
  return new Date(value * 1000).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

function formatMsDate(value: number) {
  return new Date(value).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

function formatDayLabel(value: string) {
  return new Date(value).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}
</script>

<style scoped>
.persona-gallery {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.persona-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.persona-panel {
  min-height: 320px;
}

.milestone-panel {
  overflow: hidden;
}

.milestone-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.persona-gallery-empty,
.persona-empty-mini {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 360px;
  border-radius: 28px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  background:
    radial-gradient(circle at top center, rgba(249, 115, 22, 0.08), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 252, 0.9));
  text-align: center;
}

.persona-gallery-empty p {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

.persona-gallery-empty span {
  font-size: 13px;
  color: var(--ct-text-tertiary);
}

.persona-gallery-icon {
  font-size: 42px;
}

@media (max-width: 1100px) {
  .milestone-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .persona-grid,
  .milestone-grid {
    grid-template-columns: 1fr;
  }
}
</style>
