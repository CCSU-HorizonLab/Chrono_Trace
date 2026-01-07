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

    <!-- 特征提取操作栏 -->
    <div v-if="selectedConversationId" class="feature-actions">
      <div class="action-info">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="16" x2="12" y2="12"></line>
          <line x1="12" y1="8" x2="12.01" y2="8"></line>
        </svg>
        <span>特征提取可深度分析响应时间、主动性、字数投入等指标</span>
      </div>
      <div class="action-buttons">
        <button
          @click="extractFeatures"
          :disabled="isExtracting"
          class="action-btn primary"
        >
          <svg v-if="!isExtracting" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
          <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin">
            <path d="M21 12a9 9 0 1 1-6.219-8.56"></path>
          </svg>
          {{ isExtracting ? '分析中...' : '提取特征' }}
        </button>
        <button
          v-if="hasFeatures"
          @click="reanalyze"
          :disabled="isExtracting"
          class="action-btn secondary"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6"></path>
            <path d="M1 20v-6h6"></path>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          重新分析
        </button>
      </div>
    </div>

    <!-- 特征提取进度条 -->
    <div v-if="isExtracting" class="extraction-progress">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: `${extractionProgress}%` }"></div>
      </div>
      <div class="progress-text">{{ extractionProgress }}% - {{ extractionStep }}</div>
    </div>

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

        <!-- 新增：响应时间统计 -->
        <div class="stat-card feature">
          <div class="stat-icon response">⏱️</div>
          <div class="stat-content">
            <div class="stat-value">{{ formatTime(featureStats.avgResponseTime) }}</div>
            <div class="stat-label">平均响应</div>
          </div>
        </div>

        <!-- 新增：主动性统计 -->
        <div class="stat-card feature">
          <div class="stat-icon initiative">🎯</div>
          <div class="stat-content">
            <div class="stat-value">{{ (featureStats.initiativeRate * 100).toFixed(1) }}%</div>
            <div class="stat-label">对方主动率</div>
          </div>
        </div>

        <!-- 新增：字数投入比 -->
        <div class="stat-card feature">
          <div class="stat-icon words">📊</div>
          <div class="stat-content">
            <div class="stat-value">{{ featureStats.wordRatio.toFixed(2) }}x</div>
            <div class="stat-label">字数投入比</div>
          </div>
        </div>

        <!-- 新增：响应中位数 -->
        <div class="stat-card feature">
          <div class="stat-icon median">📈</div>
          <div class="stat-content">
            <div class="stat-value">{{ formatTime(featureStats.medianResponseTime) }}</div>
            <div class="stat-label">响应中位数</div>
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

    <!-- 特征分析区域 - 新增 -->
    <div v-if="hasFeatures && !loading" class="features-grid">
      <!-- 响应时间分析 -->
      <div class="feature-card response-time">
        <header class="feature-header">
          <div class="header-left">
            <div class="feature-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
              </svg>
            </div>
            <div>
              <h3>响应时间分析</h3>
              <p class="feature-subtitle">对方回复速度的深度洞察</p>
            </div>
          </div>
        </header>
        <div class="feature-body">
          <!-- 统计指标 -->
          <div class="response-stats">
            <div class="response-stat">
              <span class="stat-label">平均响应</span>
              <span class="stat-value">{{ formatTime(responseTimeStats.avg) }}</span>
            </div>
            <div class="response-stat">
              <span class="stat-label">中位数</span>
              <span class="stat-value">{{ formatTime(responseTimeStats.median) }}</span>
            </div>
            <div class="response-stat">
              <span class="stat-label">最快</span>
              <span class="stat-value highlight fast">{{ formatTime(responseTimeStats.min) }}</span>
            </div>
            <div class="response-stat">
              <span class="stat-label">最慢</span>
              <span class="stat-value highlight slow">{{ formatTime(responseTimeStats.max) }}</span>
            </div>
          </div>

          <!-- 响应时间分布图 -->
          <div class="feature-chart">
            <div ref="responseTimeChart" class="chart-mount"></div>
          </div>

          <!-- 异常值提示 -->
          <div v-if="responseTimeStats.abnormalCount > 0" class="abnormal-warning">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <span>检测到 {{ responseTimeStats.abnormalCount }} 个异常响应时间（>24小时或负数）</span>
          </div>
        </div>
      </div>

      <!-- 主动性分析 -->
      <div class="feature-card initiative">
        <header class="feature-header">
          <div class="header-left">
            <div class="feature-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <circle cx="12" cy="12" r="6"></circle>
                <circle cx="12" cy="12" r="2"></circle>
              </svg>
            </div>
            <div>
              <h3>主动性分析</h3>
              <p class="feature-subtitle">谁更主动发起对话？</p>
            </div>
          </div>
        </header>
        <div class="feature-body">
          <!-- 环形进度条 -->
          <div class="initiative-visual">
            <div class="initiative-ring">
              <svg viewBox="0 0 100 100" class="ring-chart">
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  fill="none"
                  stroke="rgba(255,255,255,0.1)"
                  stroke-width="8"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  fill="none"
                  :stroke-dasharray="`${initiativeStats.initiativeRate * 251.2} 251.2`"
                  stroke="url(#initiativeGradient)"
                  stroke-width="8"
                  stroke-linecap="round"
                  transform="rotate(-90 50 50)"
                  class="ring-progress"
                />
                <defs>
                  <linearGradient id="initiativeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="var(--ct-color-primary)" />
                    <stop offset="100%" stop-color="var(--ct-color-accent)" />
                  </linearGradient>
                </defs>
              </svg>
              <div class="ring-center">
                <span class="ring-value">{{ (initiativeStats.initiativeRate * 100).toFixed(1) }}%</span>
                <span class="ring-label">对方主动率</span>
              </div>
            </div>
          </div>

          <!-- 统计详情 -->
          <div class="initiative-details">
            <div class="initiative-stat">
              <div class="stat-bar user">
                <div class="bar-fill" :style="{ width: `${(1 - initiativeStats.initiativeRate) * 100}%` }"></div>
              </div>
              <div class="stat-info">
                <span class="stat-name">我发起</span>
                <span class="stat-count">{{ initiativeStats.userInitiatedSessions }} 次</span>
              </div>
            </div>
            <div class="initiative-stat">
              <div class="stat-bar other">
                <div class="bar-fill" :style="{ width: `${initiativeStats.initiativeRate * 100}%` }"></div>
              </div>
              <div class="stat-info">
                <span class="stat-name">对方发起</span>
                <span class="stat-count">{{ initiativeStats.otherInitiatedSessions }} 次</span>
              </div>
            </div>
          </div>

          <!-- 解读文本 -->
          <div class="initiative-interpretation">
            {{ initiativeStats.interpretation }}
          </div>
        </div>
      </div>

      <!-- 字数投入分析 -->
      <div class="feature-card word-count">
        <header class="feature-header">
          <div class="header-left">
            <div class="feature-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="21" x2="4" y2="14"></line>
                <line x1="4" y1="10" x2="4" y2="3"></line>
                <line x1="12" y1="21" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12" y2="3"></line>
                <line x1="20" y1="21" x2="20" y2="16"></line>
                <line x1="20" y1="12" x2="20" y2="3"></line>
                <line x1="1" y1="14" x2="7" y2="14"></line>
                <line x1="9" y1="8" x2="15" y2="8"></line>
                <line x1="17" y1="16" x2="23" y2="16"></line>
              </svg>
            </div>
            <div>
              <h3>字数投入分析</h3>
              <p class="feature-subtitle">双方文字投入的对比</p>
            </div>
          </div>
        </header>
        <div class="feature-body">
          <!-- 对比条形图 -->
          <div class="word-chart">
            <div ref="wordCountChart" class="chart-mount"></div>
          </div>

          <!-- 数字统计 -->
          <div class="word-stats-grid">
            <div class="word-stat-item user">
              <span class="stat-label">我的字数</span>
              <span class="stat-value">{{ formatNumber(wordCountsStats.userCharCount) }}</span>
            </div>
            <div class="word-stat-item ratio">
              <span class="stat-label">投入比</span>
              <span class="stat-value">{{ wordCountsStats.charRatio.toFixed(2) }}x</span>
            </div>
            <div class="word-stat-item other">
              <span class="stat-label">对方字数</span>
              <span class="stat-value">{{ formatNumber(wordCountsStats.otherCharCount) }}</span>
            </div>
          </div>

          <!-- 解读 -->
          <div class="word-interpretation">
            {{ wordCountsStats.interpretation }}
          </div>
        </div>
      </div>

      <!-- 会话时间轴 -->
      <div class="feature-card timeline">
        <header class="feature-header">
          <div class="header-left">
            <div class="feature-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
            </div>
            <div>
              <h3>会话分布时间轴</h3>
              <p class="feature-subtitle">所有会话的时间线视图</p>
            </div>
          </div>
          <div class="header-actions">
            <button class="icon-btn" @click="loadSessions" :disabled="loadingSessions" title="刷新">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
          </div>
        </header>
        <div class="feature-body">
          <div ref="timelineChart" class="chart-mount timeline-mount"></div>
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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
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
  start_time: number
  end_time: number
  duration: number
  message_count: number
  initiator: string
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

// 特征提取状态
const isExtracting = ref(false)
const extractionProgress = ref(0)
const extractionStep = ref('')
const hasFeatures = ref(false)

// 特征数据
const featureStats = ref({
  avgResponseTime: 0,
  medianResponseTime: 0,
  initiativeRate: 0,
  wordRatio: 0
})

const responseTimeStats = ref({
  avg: 0,
  median: 0,
  min: 0,
  max: 0,
  abnormalCount: 0,
  count: 0
})

const initiativeStats = ref({
  totalSessions: 0,
  userInitiatedSessions: 0,
  otherInitiatedSessions: 0,
  initiativeRate: 0,
  interpretation: ''
})

const wordCountsStats = ref({
  userCharCount: 0,
  otherCharCount: 0,
  charRatio: 0,
  interpretation: ''
})

// 图表实例
const responseTimeChart = ref<HTMLDivElement | null>(null)
const timelineChart = ref<HTMLDivElement | null>(null)
const wordCountChart = ref<HTMLDivElement | null>(null)

let responseTimeChartInstance: echarts.ECharts | null = null
let timelineChartInstance: echarts.ECharts | null = null
let wordCountChartInstance: echarts.ECharts | null = null

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
  if (!num) return '0'
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

// 格式化时间
function formatTime(seconds: number): string {
  if (!seconds) return '-'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
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
  hasFeatures.value = false
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
      await nextTick()
      renderTimelineChart()
    }
  } catch (e: any) {
    console.error('加载会话失败:', e)
  } finally {
    loadingSessions.value = false
  }
}

// 特征提取功能
async function extractFeatures() {
  if (!selectedConversationId.value) return

  isExtracting.value = true
  extractionProgress.value = 0
  extractionStep.value = '初始化...'

  try {
    const result = await api.extract_features(selectedConversationId.value)

    // 后端返回格式: { success: true, data: { task_id, status, message } }
    if (result.success || result.ok) {
      const data = result.data || result
      const taskId = data.task_id

      console.log('特征提取任务ID:', taskId, '状态:', data.status)

      // 如果任务已完成，直接加载数据
      if (data.status === 'completed') {
        isExtracting.value = false
        hasFeatures.value = true
        await loadFeatureData()
        return
      }

      // 轮询进度（如果任务还在进行中）
      const checkProgress = setInterval(async () => {
        try {
          const progressResult = await api.get_extraction_progress(taskId)
          const progressData = progressResult.data || progressResult

          console.log('进度更新:', progressData)

          if (progressResult.success || progressResult.ok) {
            extractionProgress.value = Math.round(progressData.progress || 0)
            extractionStep.value = progressData.message || progressData.current_step || '分析中...'

            if (progressData.status === 'completed') {
              clearInterval(checkProgress)
              isExtracting.value = false
              hasFeatures.value = true
              await loadFeatureData()
            } else if (progressData.status === 'failed') {
              clearInterval(checkProgress)
              isExtracting.value = false
              console.error('特征提取失败:', progressData.message)
            }
          }
        } catch (e) {
          clearInterval(checkProgress)
          isExtracting.value = false
          console.error('查询进度失败:', e)
        }
      }, 500)
    } else {
      isExtracting.value = false
      console.error('提取特征失败:', result.error)
    }
  } catch (e: any) {
    console.error('提取特征失败:', e)
    isExtracting.value = false
  }
}

async function reanalyze() {
  if (!selectedConversationId.value) return
  await extractFeatures()
}

// 加载特征数据
async function loadFeatureData() {
  if (!selectedConversationId.value) return

  try {
    const [responseTimeData, initiativeData, wordCountData] = await Promise.all([
      api.get_response_times(selectedConversationId.value),
      api.get_initiative_stats(selectedConversationId.value),
      api.get_word_counts(selectedConversationId.value, false)
    ])

    console.log('加载特征数据:', { responseTimeData, initiativeData, wordCountData })

    // 处理响应时间数据
    if (responseTimeData.success && responseTimeData.data) {
      responseTimeStats.value = responseTimeData.data
      featureStats.value.avgResponseTime = responseTimeData.data.avg
      featureStats.value.medianResponseTime = responseTimeData.data.median
      await nextTick()
      renderResponseTimeChart()
    }

    // 处理主动性数据
    if (initiativeData.success && initiativeData.data) {
      // 转换字段名：下划线 -> 驼峰
      initiativeStats.value = {
        totalSessions: initiativeData.data.total_sessions,
        userInitiatedSessions: initiativeData.data.user_initiated_sessions,
        otherInitiatedSessions: initiativeData.data.other_initiated_sessions,
        initiativeRate: initiativeData.data.initiative_rate,
        interpretation: initiativeData.data.interpretation
      }
      featureStats.value.initiativeRate = initiativeData.data.initiative_rate
    }

    // 处理字数数据
    if (wordCountData.success && wordCountData.data?.overall) {
      const overall = wordCountData.data.overall
      // 转换字段名：下划线 -> 驼峰
      wordCountsStats.value = {
        userCharCount: overall.user_char_count,
        otherCharCount: overall.other_char_count,
        charRatio: overall.char_ratio,
        interpretation: overall.interpretation
      }
      featureStats.value.wordRatio = overall.char_ratio
      await nextTick()
      renderWordCountChart()
    }
  } catch (e: any) {
    console.error('加载特征数据失败:', e)
  }
}

// 渲染响应时间图表
function renderResponseTimeChart() {
  if (!responseTimeChart.value) return

  if (responseTimeChartInstance) {
    responseTimeChartInstance.dispose()
  }

  responseTimeChartInstance = echarts.init(responseTimeChart.value)

  const option: echarts.EChartsOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: 'rgba(99, 102, 241, 0.3)',
      textStyle: { color: '#e2e8f0', fontSize: 13 },
      formatter: (params: any) => {
        const value = params[0]
        return `${value.name}<br/><span style="color:#818cf8">●</span> ${formatTime(value.value)}`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: ['平均', '中位数', '最快', '最慢'],
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 12 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: {
        color: 'rgba(255,255,255,0.6)',
        formatter: (value: number) => `${Math.round(value / 60)}m`
      },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }
    },
    series: [
      {
        type: 'bar',
        data: [
          {
            value: responseTimeStats.value.avg,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#818cf8' },
                { offset: 1, color: '#6366f1' }
              ])
            }
          },
          {
            value: responseTimeStats.value.median,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#34d399' },
                { offset: 1, color: '#10b981' }
              ])
            }
          },
          {
            value: responseTimeStats.value.min,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#f472b6' },
                { offset: 1, color: '#ec4899' }
              ])
            }
          },
          {
            value: responseTimeStats.value.max,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#fbbf24' },
                { offset: 1, color: '#f59e0b' }
              ])
            }
          }
        ],
        barWidth: '50%',
        itemStyle: { borderRadius: [6, 6, 0, 0] }
      }
    ]
  }

  responseTimeChartInstance.setOption(option)
}

// 渲染会话时间轴
function renderTimelineChart() {
  if (!timelineChart.value || !sessions.value.length) return

  if (timelineChartInstance) {
    timelineChartInstance.dispose()
  }

  timelineChartInstance = echarts.init(timelineChart.value)

  const userSessions = sessions.value.filter(s => s.initiator === 'user')
  const otherSessions = sessions.value.filter(s => s.initiator === 'other')

  const option: echarts.EChartsOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: 'rgba(99, 102, 241, 0.3)',
      textStyle: { color: '#e2e8f0', fontSize: 13 },
      formatter: (params: any) => {
        const data = params[0]
        const date = new Date(data.value[0] * 1000).toLocaleString('zh-CN')
        return `${date}<br/>消息数: ${data.value[2]}<br/>发起者: ${data.value[3] === 'user' ? '我' : '对方'}`
      }
    },
    grid: {
      left: '5%',
      right: '3%',
      bottom: '5%',
      top: '5%',
      containLabel: true
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } }
    },
    yAxis: {
      type: 'category',
      data: ['对方发起', '我发起'],
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 12 }
    },
    series: [
      {
        name: '我发起',
        type: 'scatter',
        data: userSessions.map(s => [s.start_time, 1, s.message_count, s.initiator]),
        symbolSize: (data: number[]) => Math.sqrt(data[2]) * 10,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.4, 0.3, 1, [
            { offset: 0, color: 'rgba(99, 102, 241, 0.8)' },
            { offset: 1, color: 'rgba(99, 102, 241, 0.3)' }
          ]),
          shadowBlur: 10,
          shadowColor: 'rgba(99, 102, 241, 0.5)'
        }
      },
      {
        name: '对方发起',
        type: 'scatter',
        data: otherSessions.map(s => [s.start_time, 0, s.message_count, s.initiator]),
        symbolSize: (data: number[]) => Math.sqrt(data[2]) * 10,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.4, 0.3, 1, [
            { offset: 0, color: 'rgba(236, 72, 153, 0.8)' },
            { offset: 1, color: 'rgba(236, 72, 153, 0.3)' }
          ]),
          shadowBlur: 10,
          shadowColor: 'rgba(236, 72, 153, 0.5)'
        }
      }
    ]
  }

  timelineChartInstance.setOption(option)
}

// 渲染字数对比图
function renderWordCountChart() {
  if (!wordCountChart.value) return

  if (wordCountChartInstance) {
    wordCountChartInstance.dispose()
  }

  wordCountChartInstance = echarts.init(wordCountChart.value)

  const option: echarts.EChartsOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: 'rgba(99, 102, 241, 0.3)',
      textStyle: { color: '#e2e8f0', fontSize: 13 },
      formatter: (params: any) => {
        const value = params[0]
        return `${value.name}<br/><span style="color:#818cf8">●</span> ${formatNumber(value.value)}字`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: ['我', '对方'],
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
      axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 13 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: {
        color: 'rgba(255,255,255,0.6)',
        formatter: (value: number) => `${(value / 1000).toFixed(0)}k`
      },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }
    },
    series: [
      {
        type: 'bar',
        data: [
          {
            value: wordCountsStats.value.userCharCount,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#818cf8' },
                { offset: 1, color: '#6366f1' }
              ])
            }
          },
          {
            value: wordCountsStats.value.otherCharCount,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#f472b6' },
                { offset: 1, color: '#ec4899' }
              ])
            }
          }
        ],
        barWidth: '40%',
        itemStyle: { borderRadius: [6, 6, 0, 0] },
        label: {
          show: true,
          position: 'top',
          color: 'rgba(255,255,255,0.8)',
          fontSize: 12,
          formatter: (params: any) => formatNumber(params.value)
        }
      }
    ]
  }

  wordCountChartInstance.setOption(option)
}

function onWordSelect(word: string) {
  console.debug('selected word:', word)
}

// 响应式调整图表大小
function handleResize() {
  responseTimeChartInstance?.resize()
  timelineChartInstance?.resize()
  wordCountChartInstance?.resize()
}

onMounted(async () => {
  if (!dates.from || !dates.to) setDefaultDates(7)
  await loadConversations()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  responseTimeChartInstance?.dispose()
  timelineChartInstance?.dispose()
  wordCountChartInstance?.dispose()
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

/* === Feature Actions === */
.feature-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--ct-space-lg);
  padding: var(--ct-space-lg) var(--ct-space-xl);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(168, 85, 247, 0.1));
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: var(--ct-radius-lg);
  margin-bottom: var(--ct-space-lg);
  animation: fadeInUp 0.6s ease-out;
}

.action-info {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.action-info svg {
  flex-shrink: 0;
  color: var(--ct-color-primary);
}

.action-buttons {
  display: flex;
  gap: var(--ct-space-md);
}

.action-btn {
  padding: var(--ct-space-sm) var(--ct-space-lg);
  border-radius: var(--ct-radius-md);
  border: none;
  font-size: var(--ct-text-sm);
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: var(--ct-space-sm);
  transition: all var(--ct-transition-fast) var(--ct-ease-out);
}

.action-btn.primary {
  background: linear-gradient(135deg, var(--ct-color-primary), var(--ct-color-accent));
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.action-btn.primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
}

.action-btn.secondary {
  background: var(--ct-bg-elevated);
  color: var(--ct-text-primary);
  border: 1px solid var(--ct-border-color);
}

.action-btn.secondary:hover:not(:disabled) {
  background: var(--ct-bg-tertiary);
  border-color: var(--ct-border-color-hover);
}

.action-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.action-btn svg.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* === Extraction Progress === */
.extraction-progress {
  margin-bottom: var(--ct-space-lg);
  animation: fadeInUp 0.4s ease-out;
}

.progress-bar {
  height: 4px;
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-sm);
  overflow: hidden;
  margin-bottom: var(--ct-space-sm);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--ct-color-primary), var(--ct-color-accent));
  transition: width 0.3s ease;
  box-shadow: 0 0 10px var(--ct-color-primary);
}

.progress-text {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  text-align: right;
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

.stat-card.feature {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.05), rgba(168, 85, 247, 0.05));
  border-color: rgba(99, 102, 241, 0.2);
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

.stat-icon.response {
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.2), rgba(245, 158, 11, 0.2));
}

.stat-icon.initiative {
  background: linear-gradient(135deg, rgba(236, 72, 153, 0.2), rgba(244, 114, 182, 0.2));
}

.stat-icon.words {
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.2), rgba(16, 185, 129, 0.2));
}

.stat-icon.median {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(129, 140, 248, 0.2));
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

/* === Features Grid === */
.features-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ct-space-xl);
  animation: fadeInUp 0.6s ease-out 0.2s backwards;
}

.feature-card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-xl);
  box-shadow: var(--ct-shadow-sm);
  overflow: hidden;
  transition: all var(--ct-transition-normal);
}

.feature-card:hover {
  box-shadow: var(--ct-shadow-md);
  border-color: rgba(99, 102, 241, 0.2);
}

.feature-card.timeline {
  grid-column: 1 / -1;
}

.feature-header {
  padding: var(--ct-space-lg) var(--ct-space-xl);
  border-bottom: 1px solid var(--ct-border-color);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.feature-header .header-left {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
}

.feature-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--ct-radius-lg);
  background: linear-gradient(135deg, var(--ct-color-primary-light), var(--ct-color-accent-light));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ct-color-primary);
}

.feature-header h3 {
  font-size: var(--ct-text-lg);
  font-weight: 600;
  color: var(--ct-text-primary);
  margin-bottom: var(--ct-space-xs);
}

.feature-subtitle {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  margin: 0;
}

.feature-body {
  padding: var(--ct-space-xl);
}

/* === Response Time Stats === */
.response-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-lg);
}

.response-stat {
  text-align: center;
  padding: var(--ct-space-md);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
  border: 1px solid var(--ct-border-color);
}

.response-stat .stat-label {
  display: block;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  margin-bottom: var(--ct-space-sm);
}

.response-stat .stat-value {
  display: block;
  font-size: var(--ct-text-lg);
  font-weight: 700;
  color: var(--ct-text-primary);
}

.response-stat .stat-value.highlight.fast {
  color: var(--ct-color-success);
}

.response-stat .stat-value.highlight.slow {
  color: var(--ct-color-warning);
}

.feature-chart {
  margin-bottom: var(--ct-space-md);
}

.chart-mount {
  width: 100%;
  height: 250px;
}

.abnormal-warning {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-md);
  background: rgba(245, 158, 11, 0.1);
  border-left: 3px solid var(--ct-color-warning);
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  color: var(--ct-color-warning);
}

.abnormal-warning svg {
  flex-shrink: 0;
}

/* === Initiative Visual === */
.initiative-visual {
  display: flex;
  justify-content: center;
  margin-bottom: var(--ct-space-xl);
}

.initiative-ring {
  position: relative;
  width: 200px;
  height: 200px;
}

.ring-chart {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.ring-progress {
  transition: stroke-dasharray 1s ease;
}

.ring-center {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
}

.ring-value {
  display: block;
  font-size: var(--ct-text-3xl);
  font-weight: 700;
  color: var(--ct-text-primary);
  line-height: 1;
}

.ring-label {
  display: block;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  margin-top: var(--ct-space-xs);
}

.initiative-details {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-lg);
}

.initiative-stat {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.stat-bar {
  height: 8px;
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-sm);
  overflow: hidden;
  position: relative;
}

.stat-bar.user .bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--ct-color-primary), var(--ct-color-accent));
  border-radius: var(--ct-radius-sm);
  transition: width 0.6s ease;
}

.stat-bar.other .bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--ct-color-accent), var(--ct-color-primary));
  border-radius: var(--ct-radius-sm);
  transition: width 0.6s ease;
}

.stat-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-name {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
}

.stat-count {
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-text-primary);
}

.initiative-interpretation {
  padding: var(--ct-space-md);
  background: rgba(99, 102, 241, 0.05);
  border-left: 3px solid var(--ct-color-primary);
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: 1.6;
}

/* === Word Stats === */
.word-chart {
  margin-bottom: var(--ct-space-lg);
}

.word-stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-lg);
}

.word-stat-item {
  text-align: center;
  padding: var(--ct-space-md);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
}

.word-stat-item.user {
  border-top: 3px solid var(--ct-color-primary);
}

.word-stat-item.ratio {
  border-top: 3px solid var(--ct-color-accent);
}

.word-stat-item.other {
  border-top: 3px solid var(--ct-color-success);
}

.word-stat-item .stat-label {
  display: block;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  margin-bottom: var(--ct-space-xs);
}

.word-stat-item .stat-value {
  display: block;
  font-size: var(--ct-text-xl);
  font-weight: 700;
  color: var(--ct-text-primary);
}

.word-interpretation {
  padding: var(--ct-space-md);
  background: rgba(16, 185, 129, 0.05);
  border-left: 3px solid var(--ct-color-success);
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: 1.6;
}

/* === Timeline === */
.timeline-mount {
  height: 350px;
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

  .features-grid {
    grid-template-columns: 1fr;
  }

  .feature-card.timeline {
    grid-column: 1;
  }
}

@media (max-width: 768px) {
  .analytics-page {
    padding: var(--ct-space-lg) var(--ct-space-md);
  }

  .page-header {
    flex-direction: column;
  }

  .feature-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .action-buttons {
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

  .response-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .response-stats {
    grid-template-columns: 1fr;
  }

  .word-stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
