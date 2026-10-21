<template>
  <div class="persona-gallery">
    <!-- 画廊头部：生成入口从外层裸按钮行移入（空态/有档两种状态都能直达） -->
    <div class="gallery-head">
      <div>
        <div class="gallery-title">画像档案</div>
        <div class="gallery-sub">AI 从聊天记录提炼的长期印象{{ hasProfile ? '，支持历史快照回看' : '' }}</div>
      </div>
      <button class="btn primary gallery-generate" :disabled="loading" @click="emit('generate')">
        {{ hasProfile ? '更新画像' : '生成画像' }}
      </button>
    </div>

    <div v-if="loading" class="persona-gallery-empty">
      <div class="persona-gallery-icon"><Clock :size="40" class="persona-loading-spin" /></div>
      <p>正在读取这位联系人的画像档案...</p>
    </div>

    <div v-else-if="!hasProfile" class="persona-gallery-empty">
      <div class="persona-gallery-icon"><Images :size="40" :stroke-width="1.5" /></div>
      <p>这位联系人还没有可展示的 AI 画像。</p>
      <span>点右上「生成画像」，按当前时间窗从聊天记录里提炼第一份画像。</span>
    </div>

    <template v-else>
      <div class="hero-with-snapshots">
        <PersonaTagsCard
          :title="heroTitle"
          :summary="heroSummary"
          :note="heroNote"
          :tags="heroTags"
          :meta-items="heroMeta"
        />

        <div class="snapshot-row">
          <button class="snapshot-toggle" :disabled="snapshotsLoading" @click="toggleSnapshots">
            {{ snapshotsOpen ? '收起快照' : `历史快照${snapshots.length ? `（${snapshots.length} 份）` : ''}` }}
          </button>
          <span v-if="viewingSnapshot" class="snapshot-viewing">
            正在回看{{ snapshotLabel(viewingSnapshot) }}的画像
            <button class="snapshot-back" @click="viewingSnapshot = null">回到当前</button>
          </span>
        </div>

        <div v-if="snapshotsOpen" class="snapshot-list">
          <div v-if="snapshotsLoading" class="snapshot-empty">正在读取快照列表…</div>
          <div v-else-if="!snapshots.length" class="snapshot-empty">还没有历史快照（每次不同时间窗的生成都会各自存档）</div>
          <button
            v-for="snap in snapshots"
            :key="snap.id"
            class="snapshot-item"
            :class="{ active: viewingSnapshot?.id === snap.id }"
            @click="viewingSnapshot = snap"
          >
            <span class="snapshot-window">{{ snapshotLabel(snap) }}</span>
            <span class="snapshot-kind">{{ snap.window_kind === 'custom' ? '指定窗' : '滚动窗' }}</span>
            <span class="snapshot-date">生成于 {{ formatUnixDate(snap.created_at) }}</span>
          </button>
        </div>
      </div>

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
            :clickable="Boolean(milestone.anchor && conversationId)"
            @open="openRecall(milestone)"
          />
        </div>
        <div v-else class="persona-empty-mini">当前还不足以拼出关键互动瞬间</div>
      </CtCard>
    </template>

    <!-- 记忆相框回顾弹窗：展示锚点时刻的原始对话 -->
    <div v-if="recall.visible" class="recall-overlay" @click.self="closeRecall">
      <div class="recall-panel">
        <div class="recall-head">
          <div class="recall-head-text">
            <h3>{{ recall.title }}</h3>
            <span class="recall-date-pill">{{ recall.dateLabel }}</span>
          </div>
          <button class="recall-close" aria-label="关闭" @click="closeRecall">✕</button>
        </div>

        <div class="recall-body">
          <div v-if="recall.loading" class="recall-status">
            <Clock :size="22" class="persona-loading-spin" />
            <p>正在取回当时的对话...</p>
          </div>
          <div v-else-if="recall.error" class="recall-status">
            <p>{{ recall.error }}</p>
          </div>
          <template v-else>
            <div
              v-for="msg in recall.messages"
              :key="msg.id"
              class="recall-msg"
              :class="{ 'is-me': msg.is_me }"
            >
              <div class="recall-bubble">
                <div class="recall-meta">
                  <span class="recall-sender">{{ msg.sender_name }}</span>
                  <span class="recall-time">{{ formatClock(msg.create_time) }}</span>
                </div>
                <div class="recall-content">{{ msg.content?.trim() || '（图片/语音等非文字内容）' }}</div>
              </div>
            </div>
          </template>
        </div>

        <div v-if="!recall.loading && !recall.error && recall.messages.length" class="recall-foot">
          <template v-if="recall.truncated">已显示前 {{ recall.messages.length }} 条，共 {{ recall.total }} 条</template>
          <template v-else>共 {{ recall.total }} 条消息</template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PropType } from 'vue'
import { Images, Clock } from 'lucide-vue-next'
import { api } from '@/api/bridge'
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

type ProfileWindow = {
  kind: string
  from: number
  to: number
  days: number
  label: string
}

type ProfileSnapshot = {
  id: number
  window_kind: string
  window_from: number
  window_to: number
  budget_level?: string
  created_at: number
  expires_at?: number
  profile: PersonaProfile | null
  window?: ProfileWindow | null
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
  interaction_investment?: { score: number }
  emotional_resonance?: { score: number }
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
  anchor?: { startMs: number; endMs?: number }
}

type RecallMessage = {
  id: number
  sender_name: string
  content: string
  create_time: number
  is_me: boolean
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
  conversationId: {
    type: Number,
    default: null
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
  },
  /** 当前画像的窗口标注（get_contact_profile 的 window 字段） */
  windowInfo: {
    type: Object as PropType<ProfileWindow | null>,
    default: null
  },
  /** 查询历史快照用的账号（缺省走后端活跃账号） */
  accountWxid: {
    type: String,
    default: ''
  }
})

const emit = defineEmits<{
  (e: 'generate'): void
}>()

const palette = ['#E8656F', '#E0A458', '#2FA39A', '#5A4BC4', '#C455D0', '#8B93A7']

const hasProfile = computed(() => Boolean(props.profile))

// —— 历史快照回看：viewingSnapshot 非空时，画像区展示该快照内容 ——
const viewingSnapshot = ref<ProfileSnapshot | null>(null)
const snapshotsOpen = ref(false)
const snapshotsLoading = ref(false)
const snapshots = ref<ProfileSnapshot[]>([])

const activeProfile = computed<PersonaProfile | null>(
  () => viewingSnapshot.value?.profile ?? props.profile
)
const activeCreatedAt = computed<number | null>(
  () => viewingSnapshot.value?.created_at ?? props.profileMeta.createdAt
)
const activeWindowLabel = computed<string>(
  () => snapshotLabel(viewingSnapshot.value) || props.windowInfo?.label || ''
)

async function toggleSnapshots() {
  snapshotsOpen.value = !snapshotsOpen.value
  // 每次展开都重拉：面板打开期间新生成的快照（画像演变/生成对话框落档）也要出现
  if (snapshotsOpen.value) {
    snapshotsLoading.value = true
    try {
      const res = await api.list_profile_snapshots(
        props.contactName, props.accountWxid || undefined, 'contact'
      )
      snapshots.value = res?.ok ? (res.snapshots || []) : []
    } catch {
      snapshots.value = []
    } finally {
      snapshotsLoading.value = false
    }
  }
}

/** 快照的窗口描述：优先后端格式化 label，缺省用起止日期拼 */
function snapshotLabel(snap: ProfileSnapshot | null): string {
  if (!snap) return ''
  if (snap.window?.label) return snap.window.label
  if (snap.window_from && snap.window_to) {
    return `${formatUnixDate(snap.window_from)} ~ ${formatUnixDate(snap.window_to)}`
  }
  return '滚动窗'
}

const heroTags = computed(() => activeProfile.value?.personality_tags?.slice(0, 6) || [])

const heroTitle = computed(() => {
  if (heroTags.value.length > 0) return heroTags.value.join(' · ')
  return `${props.contactName} 的画像档案`
})

const heroSummary = computed(() => {
  return activeProfile.value?.chat_style || activeProfile.value?.relationship_note || '画像已生成，但暂时没有更多摘要信息。'
})

const heroNote = computed(() => activeProfile.value?.communication_tips || '')

const heroMeta = computed(() => {
  const items: string[] = []
  if (activeProfile.value?.relationship_note) items.push(activeProfile.value.relationship_note)
  if (props.analysisResult?.overall_score !== undefined) items.push(`关系评分 ${Math.round(props.analysisResult.overall_score)}%`)
  if (props.currentRangeLabel) items.push(props.currentRangeLabel)
  if (activeWindowLabel.value && activeCreatedAt.value) {
    items.push(`基于${activeWindowLabel.value} · 生成于 ${formatUnixDate(activeCreatedAt.value)}`)
  } else if (activeCreatedAt.value) {
    items.push(`画像生成于 ${formatUnixDate(activeCreatedAt.value)}`)
  }
  return items
})

const topicBubbles = computed(() => {
  const interests = activeProfile.value?.interests || []
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
  const positivity = normalizeScore(props.analysisResult?.interaction_investment?.score)
  const resonance = normalizeScore(props.analysisResult?.emotional_resonance?.score)
  const initiative = clamp01(props.featureStats.initiativeRate || 0)

  const items = [
    {
      label: '温度感',
      value: positiveAvg || positivity,
      color: '#E0A458',
      description: positiveAvg ? '对话里的正向情绪更常作为底色出现。' : '基于互动投入推断，这段关系更偏暖色调。'
    },
    {
      label: '稳定感',
      value: clamp01(1 - negativeAvg),
      color: '#8B93A7',
      description: negativeAvg ? '低波动说明情绪起伏相对平稳。' : '暂时缺少明显负向样本，整体更像平缓流动。'
    },
    {
      label: '共鸣感',
      value: resonance,
      color: '#5A4BC4',
      description: '结合关系分析结果，反映彼此回应的共振强度。'
    },
    {
      label: '互动主动性',
      value: initiative,
      color: '#2FA39A',
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
      accent: '#E8656F'
    })
  }

  if (props.activityCalendarSummary && props.activityCalendarSummary.global_first_session_start_time) {
    items.push({
      title: '最早留痕',
      dateLabel: formatMsDate(props.activityCalendarSummary.global_first_session_start_time),
      body: '这是全纪录中能追溯到的最早一次完整互动切片。',
      accent: '#8B93A7',
      anchor: { startMs: props.activityCalendarSummary.global_first_session_start_time }
    })

    const peakSession = props.activityCalendarSummary.global_peak_session
    if (peakSession && peakSession.message_count > 0) {
      items.push({
        title: '高密度互动',
        dateLabel: formatMsDate(peakSession.start_time),
        body: `单场互动达到 ${peakSession.message_count} 条消息，是全部历史样本里互动最密集的一次。`,
        accent: '#5A4BC4',
        anchor: { startMs: peakSession.start_time }
      })
    }
  } else if (sessions.length) {
    const firstSession = sessions.reduce((min, session) => session.start_time < min.start_time ? session : min, sessions[0])
    const peakSession = sessions.reduce((max, session) => session.message_count > max.message_count ? session : max, sessions[0])

    items.push({
      title: '最早留痕',
      dateLabel: formatMsDate(firstSession.start_time),
      body: '这是当前采样样本中能追溯到的最早一次完整互动切片。',
      accent: '#8B93A7',
      anchor: { startMs: firstSession.start_time }
    })

    if (peakSession.message_count > 0) {
      items.push({
        title: '高密度互动',
        dateLabel: formatMsDate(peakSession.start_time),
        body: `这场会话记录了 ${peakSession.message_count} 条消息，是当前最近样本里最饱满的一次交谈。`,
        accent: '#5A4BC4',
        anchor: { startMs: peakSession.start_time }
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
      accent: '#2FA39A',
      anchor: dayAnchor(highest.ts)
    })

    if (lowest.ts !== highest.ts) {
      items.push({
        title: '情绪转折',
        dateLabel: formatDayLabel(lowest.ts),
        body: `这一天的情绪评分降到 ${lowest.score.toFixed(2)}，可能是关系中的敏感节点。`,
        accent: '#E8656F',
        anchor: dayAnchor(lowest.ts)
      })
    }
  }

  return items.slice(0, 4)
})

// —— 记忆相框回顾：点击相框取回锚点时刻的原始对话 ——

// 切换联系人：回看状态与快照列表失效
watch(() => props.contactName, () => {
  viewingSnapshot.value = null
  snapshots.value = []
  snapshotsOpen.value = false
})

const recall = ref<{
  visible: boolean
  loading: boolean
  title: string
  dateLabel: string
  error: string
  messages: RecallMessage[]
  total: number
  truncated: boolean
}>({ visible: false, loading: false, title: '', dateLabel: '', error: '', messages: [], total: 0, truncated: false })

async function openRecall(milestone: MilestoneItem) {
  if (!milestone.anchor || !props.conversationId) return
  recall.value = {
    visible: true,
    loading: true,
    title: milestone.title,
    dateLabel: milestone.dateLabel,
    error: '',
    messages: [],
    total: 0,
    truncated: false
  }
  try {
    const res = await api.get_milestone_messages(
      props.conversationId,
      milestone.anchor.startMs,
      milestone.anchor.endMs ?? 0
    )
    if (!res?.ok) {
      recall.value.error = res?.error || '未能取回当时的消息'
      return
    }
    recall.value.messages = res.messages || []
    recall.value.total = res.total || 0
    recall.value.truncated = Boolean(res.truncated)
    if (!recall.value.messages.length) {
      recall.value.error = '该时间点附近没有留存的文字消息（可能是纯图片/语音片段）。'
    }
  } catch (e: any) {
    recall.value.error = e?.message || '读取失败，请稍后再试'
  } finally {
    recall.value.loading = false
  }
}

function closeRecall() {
  recall.value.visible = false
}

function formatClock(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// 'YYYY-MM-DD'（后端按 localtime 聚合）→ 当地时区整日毫秒窗口
function dayAnchor(ts: string): { startMs: number; endMs: number } | undefined {
  const parts = String(ts).split('-').map(Number)
  if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return undefined
  const start = new Date(parts[0], parts[1] - 1, parts[2]).getTime()
  if (!Number.isFinite(start)) return undefined
  return { startMs: start, endMs: start + 86400000 }
}

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

.gallery-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
}

.gallery-title {
  font-size: var(--ct-text-base);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
}

.gallery-sub {
  margin-top: 2px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.persona-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

/* —— 历史快照回看 —— */
.snapshot-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: -8px;
}

.snapshot-toggle {
  padding: 5px 14px;
  border-radius: 999px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.snapshot-toggle:hover { border-color: var(--ct-color-primary); color: var(--ct-color-primary); }
.snapshot-toggle:disabled { opacity: 0.5; cursor: not-allowed; }

.snapshot-viewing {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ct-text-secondary);
}

.snapshot-back {
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid rgba(249, 115, 22, 0.4);
  background: rgba(249, 115, 22, 0.08);
  color: #c2410c;
  font-size: 11px;
  cursor: pointer;
}

.snapshot-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 16px;
  border: 1px dashed rgba(148, 163, 184, 0.35);
  background: rgba(248, 250, 252, 0.75);
}

.snapshot-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--ct-radius-sm);
  background: rgba(255, 255, 255, 0.9);
  cursor: pointer;
  text-align: left;
  font-size: 12px;
  color: var(--ct-text-primary);
  transition: all 0.15s ease;
}

.snapshot-item:hover { border-color: rgba(249, 115, 22, 0.45); }
.snapshot-item.active { border-color: rgba(249, 115, 22, 0.6); background: rgba(249, 115, 22, 0.08); }

.snapshot-window { font-weight: 600; }
.snapshot-kind {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10.5px;
  color: var(--ct-text-tertiary);
}
.snapshot-date { margin-left: auto; color: var(--ct-text-tertiary); font-size: 11px; }
.snapshot-empty { font-size: 12px; color: var(--ct-text-tertiary); text-align: center; padding: 6px 0; }

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
  border: 1px dashed var(--ct-border-color);
  background: var(--ct-bg-paper-warm);
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
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ct-color-primary);
  opacity: 0.85;
}

.persona-loading-spin {
  animation: persona-spin 2s linear infinite;
}

@keyframes persona-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* —— 记忆相框回顾弹窗 —— */
.recall-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(69, 26, 3, 0.42);
  backdrop-filter: blur(3px);
}

.recall-panel {
  display: flex;
  flex-direction: column;
  width: min(640px, 100%);
  max-height: min(78vh, 720px);
  border-radius: 24px;
  overflow: hidden;
  background: var(--ct-bg-paper-warm);
  border: 1px solid rgba(251, 191, 36, 0.28);
  box-shadow: 0 28px 64px rgba(120, 53, 15, 0.28);
}

.recall-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid rgba(251, 191, 36, 0.18);
}

.recall-head-text h3 {
  margin: 0 0 6px;
  font-size: 17px;
  color: #7c2d12;
}

.recall-date-pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(249, 115, 22, 0.1);
  color: #9a3412;
  font-size: 11px;
  font-weight: 700;
}

.recall-close {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 50%;
  background: rgba(156, 63, 18, 0.08);
  color: #9a3412;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.recall-close:hover {
  background: rgba(156, 63, 18, 0.16);
}

.recall-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.recall-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 160px;
  color: #9a3412;
}

.recall-status p {
  margin: 0;
  font-size: 13.5px;
}

.recall-msg {
  display: flex;
}

.recall-msg.is-me {
  justify-content: flex-end;
}

.recall-bubble {
  max-width: 78%;
  padding: 8px 12px;
  border-radius: 16px;
  border-bottom-left-radius: 6px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(251, 191, 36, 0.2);
}

.recall-msg.is-me .recall-bubble {
  border-bottom-left-radius: 16px;
  border-bottom-right-radius: 6px;
  background: rgba(249, 115, 22, 0.1);
  border-color: rgba(249, 115, 22, 0.22);
}

.recall-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 3px;
}

.recall-sender {
  font-size: 11.5px;
  font-weight: 700;
  color: #b45309;
}

.recall-time {
  font-size: 10.5px;
  color: rgba(154, 52, 18, 0.55);
}

.recall-content {
  font-size: 13.5px;
  line-height: 1.65;
  color: #431407;
  white-space: pre-wrap;
  word-break: break-word;
}

.recall-foot {
  padding: 10px 20px 14px;
  border-top: 1px solid rgba(251, 191, 36, 0.18);
  font-size: 11.5px;
  color: rgba(154, 52, 18, 0.7);
  text-align: center;
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
