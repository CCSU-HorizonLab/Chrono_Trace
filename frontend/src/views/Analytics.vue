<template>
  <section class="analytics-page">
    <!-- 页面头部 - 编辑风格 -->
    <header class="page-header">
      <div class="header-content">
        <h1 class="page-title">{{ currentContactName }}</h1>
        <p class="page-meta">
          <span class="meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="16" y1="2" x2="16" y2="6"></line>
              <line x1="8" y1="2" x2="8" y2="6"></line>
              <line x1="3" y1="10" x2="21" y2="10"></line>
            </svg>
            {{ dates.from }} ~ {{ dates.to }}
          </span>
        </p>
      </div>
      <FiltersBar
        :conversations="conversations"
        :selected-conversation-id="selectedConversationId"
        :dates="dates"
        :loading="loading"
        @update:conversation-id="onConversationChange"
        @update:dates="onDatesChange"
        @refresh="loadAnalysis"
      />
    </header>

    <!-- 统计指标 - 精致的卡片网格 -->
    <div v-if="!loading && stats" class="stats-section">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon messages">💬</div>
          <div class="stat-content">
            <div class="stat-value">{{ formatNumber(stats.totalMessages) }}</div>
            <div class="stat-label">消息总数</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon sentiment">💝</div>
          <div class="stat-content">
            <div class="stat-value">{{ stats.avgSentiment }}</div>
            <div class="stat-label">平均情感值</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon days">📅</div>
          <div class="stat-content">
            <div class="stat-value">{{ stats.activeDays }}</div>
            <div class="stat-label">互动天数</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon sessions">⚡</div>
          <div class="stat-content">
            <div class="stat-value">{{ stats.sessionCount }}</div>
            <div class="stat-label">会话数量</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容区 - 图表与可视化 -->
    <div class="main-content">
      <!-- 情绪曲线图 -->
      <div class="chart-card primary">
        <header class="card-header">
          <div class="header-left">
            <h2>历史情绪曲线</h2>
            <p class="chart-subtitle">追踪情感变化的波动轨迹</p>
          </div>
          <div class="header-actions">
            <button class="icon-btn" @click="loadAnalysis" :disabled="loading" title="刷新">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
          </div>
        </header>
        <div class="card-body">
          <div v-if="loading" class="skeleton">
            <div class="skeleton-shimmer"></div>
          </div>
          <div v-else-if="error" class="error-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <span>{{ error }}</span>
            <button class="btn" @click="loadAnalysis">重试</button>
          </div>
          <div v-else class="chart-container">
            <EmotionLineChart :timeseries="analysis.timeseries" />
          </div>
        </div>
      </div>

      <!-- 词云图 -->
      <div class="chart-card secondary">
        <header class="card-header">
          <div class="header-left">
            <h2>聊天词云</h2>
            <p class="chart-subtitle">高频词汇的可视化呈现</p>
          </div>
        </header>
        <div class="card-body">
          <div v-if="loading" class="skeleton">
            <div class="skeleton-shimmer"></div>
          </div>
          <div v-else-if="error" class="error-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <span>{{ error }}</span>
            <button class="btn" @click="loadAnalysis">重试</button>
          </div>
          <div v-else class="wordcloud-container">
            <WordCloud :words="analysis.wordcloud" @select="onWordSelect" />
          </div>
        </div>
      </div>
    </div>

    <!-- 对象信息卡 - 精致侧边栏 -->
    <div v-if="selectedConversationId" class="subject-section">
      <SubjectCard :subject="subject" />
    </div>

    <!-- 时间线 - 对话历史流 -->
    <div v-if="selectedConversationId" class="timeline-section">
      <div class="section-header">
        <h3>对话时间线</h3>
        <p class="section-subtitle">按时间顺序展开的交流记录</p>
      </div>
      <ConversationTimeline :sessions="sessions" :loading="loadingSessions" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import SubjectCard from '@/components/analytics/SubjectCard.vue'
import EmotionLineChart from '@/components/charts/EmotionLineChart.vue'
import WordCloud from '@/components/charts/WordCloud.vue'
import ConversationTimeline from '@/components/timeline/ConversationTimeline.vue'

type Conversation = {
  id: number
  name: string
  username: string
  message_count: number
  last_message_time: string
}

type Session = {
  id: number
  start_time: string
  end_time: string
  duration: number
  message_count: number
  messages: any[]
}

type TimeseriesPoint = { ts: string; score: number; positive?: number; negative?: number }
type SubjectStats = { msgCount: number; avgScore: number; maxDay?: string; minDay?: string }
type Subject = { id?: string | number; name: string; avatar?: string; stats?: SubjectStats }
type Analysis = { subject?: Subject; timeseries: TimeseriesPoint[]; wordcloud: { word: string; weight: number }[] }

// 联系人列表
const conversations = ref<Conversation[]>([])
const selectedConversationId = ref<number | null>(null)

const dates = reactive({ from: '', to: '' })
const loading = ref(false)
const loadingSessions = ref(false)
const error = ref('')
const analysis = reactive<Analysis>({ timeseries: [], wordcloud: [] })
const subject = ref<Subject | undefined>(undefined)
const sessions = ref<Session[]>([])

// 统计数据
const stats = ref<{
  totalMessages: number
  avgSentiment: number
  activeDays: number
  sessionCount: number
} | null>(null)

// 当前联系人名称
const currentContactName = computed(() => {
  if (!selectedConversationId.value) return '选择联系人'
  const contact = conversations.value.find(c => c.id === selectedConversationId.value)
  return contact?.name || '选择联系人'
})

// 格式化数字
function formatNumber(num: number): string {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

function setDefaultDates(days = 7) {
  const to = new Date()
  const from = new Date()
  from.setDate(to.getDate() - (days - 1))
  dates.from = from.toISOString().slice(0, 10)
  dates.to = to.toISOString().slice(0, 10)
}

// 加载联系人列表
async function loadConversations() {
  try {
    await bridgeReady()
    const res = await api.get_conversation_list()
    if (res.ok) {
      conversations.value = res.conversations
    } else {
      console.error('加载联系人列表失败:', res.error)
    }
  } catch (e: any) {
    console.error('加载联系人列表异常:', e)
  }
}

// 联系人切换
function onConversationChange(conversationId: number) {
  selectedConversationId.value = conversationId
  loadAnalysis()
  loadSessions()
}

function onDatesChange(newDates: { from: string; to: string }) {
  dates.from = newDates.from
  dates.to = newDates.to
  loadAnalysis()
}

async function loadAnalysis() {
  if (!selectedConversationId.value) {
    error.value = '请先选择联系人'
    return
  }

  loading.value = true
  error.value = ''
  try {
    await bridgeReady()
    const res = await api.get_analysis({
      conversation_id: selectedConversationId.value,
      from: dates.from,
      to: dates.to
    })

    if (res.error) {
      error.value = res.error
      return
    }

    analysis.timeseries = res?.timeseries ?? []
    analysis.wordcloud = res?.wordcloud ?? []
    subject.value = res?.subject ?? subject.value

    // 计算统计数据
    if (analysis.timeseries.length > 0) {
      const totalSentiment = analysis.timeseries.reduce((sum: number, point: any) => sum + (point.score || 0), 0)
      stats.value = {
        totalMessages: subject.value?.stats?.msgCount || 0,
        avgSentiment: (totalSentiment / analysis.timeseries.length).toFixed(2),
        activeDays: analysis.timeseries.length,
        sessionCount: sessions.value.length
      }
    }
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// 加载会话数据
async function loadSessions() {
  if (!selectedConversationId.value) return

  loadingSessions.value = true
  try {
    await bridgeReady()
    const res = await api.get_sessions(selectedConversationId.value, 50, 0)

    if (res.ok && res.sessions) {
      sessions.value = res.sessions
    }
  } catch (e: any) {
    console.error('加载会话失败:', e)
  } finally {
    loadingSessions.value = false
  }
}

function onWordSelect(word: string) {
  console.debug('selected word:', word)
}

onMounted(async () => {
  if (!dates.from || !dates.to) setDefaultDates(7)
  await loadConversations()
})
</script>

<style scoped>
/* ========================================
   Analytics Page - Data Poetry Aesthetic
   ======================================== */

.analytics-page {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-3xl);
  max-width: 1400px;
  margin: 0 auto;
  padding: var(--ct-space-2xl) var(--ct-space-lg);
}

/* === Header === */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--ct-space-xl);
  flex-wrap: wrap;
}

.header-content {
  flex: 1;
  min-width: 280px;
}

.page-title {
  font-size: var(--ct-text-4xl);
  font-weight: 700;
  color: var(--ct-text-primary);
  margin-bottom: var(--ct-space-sm);
  letter-spacing: -0.02em;
}

.page-meta {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-xs) var(--ct-space-sm);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
}

.meta-item svg {
  color: var(--ct-color-primary);
  opacity: 0.8;
}

/* === Stats Section === */
.stats-section {
  animation: fadeInUp 0.6s ease-out;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--ct-space-lg);
}

.stat-card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-xl);
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  transition: all var(--ct-transition-normal);
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--ct-color-primary), var(--ct-color-accent));
  opacity: 0;
  transition: opacity var(--ct-transition-normal);
}

.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--ct-shadow-lg);
  border-color: var(--ct-border-color-hover);
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--ct-radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  flex-shrink: 0;
  position: relative;
}

.stat-icon.messages {
  background: linear-gradient(135deg, var(--ct-color-primary-light), var(--ct-color-accent-light));
}

.stat-icon.sentiment {
  background: linear-gradient(135deg, var(--ct-color-accent-light), rgba(245, 166, 35, 0.2));
}

.stat-icon.days {
  background: linear-gradient(135deg, var(--ct-color-success-light), rgba(16, 185, 129, 0.2));
}

.stat-icon.sessions {
  background: linear-gradient(135deg, var(--ct-color-info-light), rgba(59, 130, 246, 0.2));
}

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: var(--ct-text-3xl);
  font-weight: 700;
  color: var(--ct-text-primary);
  line-height: 1;
  margin-bottom: var(--ct-space-xs);
  font-family: var(--ct-font-display);
}

.stat-label {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* === Main Content === */
.main-content {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--ct-space-xl);
  animation: fadeInUp 0.6s ease-out 0.1s backwards;
}

.chart-card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-xl);
  box-shadow: var(--ct-shadow-sm);
  overflow: hidden;
  transition: all var(--ct-transition-normal);
}

.chart-card:hover {
  box-shadow: var(--ct-shadow-md);
}

.card-header {
  padding: var(--ct-space-lg) var(--ct-space-xl);
  border-bottom: 1px solid var(--ct-border-color);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-left h2 {
  font-size: var(--ct-text-xl);
  font-weight: 600;
  color: var(--ct-text-primary);
  margin-bottom: var(--ct-space-xs);
}

.chart-subtitle {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: var(--ct-space-sm);
}

.icon-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--ct-radius-md);
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
  color: var(--ct-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}

.icon-btn:hover:not(:disabled) {
  background: var(--ct-bg-tertiary);
  border-color: var(--ct-border-color-hover);
  color: var(--ct-text-primary);
}

.icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.card-body {
  padding: var(--ct-space-xl);
  min-height: 320px;
  position: relative;
}

.chart-container,
.wordcloud-container {
  width: 100%;
  height: 100%;
  min-height: 280px;
}

/* === Loading & Error States === */
.skeleton {
  width: 100%;
  height: 100%;
  min-height: 280px;
  background: linear-gradient(
    90deg,
    var(--ct-bg-secondary) 0%,
    var(--ct-bg-tertiary) 50%,
    var(--ct-bg-secondary) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: var(--ct-radius-md);
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--ct-space-md);
  color: var(--ct-text-tertiary);
  min-height: 280px;
}

.error-state svg {
  color: var(--ct-color-warning);
  opacity: 0.6;
}

.error-state span {
  font-size: var(--ct-text-sm);
}

.error-state .btn {
  margin-top: var(--ct-space-sm);
}

/* === Subject Section === */
.subject-section {
  animation: fadeInUp 0.6s ease-out 0.2s backwards;
}

/* === Timeline Section === */
.timeline-section {
  animation: fadeInUp 0.6s ease-out 0.3s backwards;
}

.section-header {
  margin-bottom: var(--ct-space-lg);
}

.section-header h3 {
  font-size: var(--ct-text-2xl);
  font-weight: 600;
  color: var(--ct-text-primary);
  margin-bottom: var(--ct-space-xs);
}

.section-subtitle {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  margin: 0;
}

/* === Animations === */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* === Responsive === */
@media (max-width: 1200px) {
  .main-content {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .analytics-page {
    padding: var(--ct-space-lg) var(--ct-space-md);
  }

  .page-header {
    flex-direction: column;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .page-title {
    font-size: var(--ct-text-3xl);
  }

  .card-header {
    flex-direction: column;
    gap: var(--ct-space-md);
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
