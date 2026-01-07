<template>
  <div class="analysis-container">
    <!-- 背景动态效果 -->
    <div class="grid-background"></div>
    <div class="ambient-glow"></div>

    <!-- 顶部操作栏 -->
    <header class="top-bar">
      <div class="header-content">
        <div class="title-section">
          <h1 class="page-title">数据分析中心</h1>
          <p class="subtitle">聊天特征提取与可视化分析</p>
        </div>

        <div class="actions">
          <button
            @click="extractFeatures"
            :disabled="isExtracting"
            class="action-btn primary"
          >
            <span v-if="!isExtracting">提取特征</span>
            <span v-else>分析中...</span>
          </button>

          <button
            @click="reanalyze"
            :disabled="isExtracting"
            class="action-btn secondary"
          >
            重新分析
          </button>

          <select
            v-model="selectedConversation"
            @change="loadConversationData"
            class="conversation-select"
          >
            <option value="">选择联系人...</option>
            <option
              v-for="conv in conversations"
              :key="conv.id"
              :value="conv.id"
            >
              {{ conv.name }} ({{ conv.message_count }}条消息)
            </option>
          </select>
        </div>
      </div>

      <!-- 进度条 -->
      <div v-if="isExtracting" class="progress-bar">
        <div
          class="progress-fill"
          :style="{ width: `${progress}%` }"
        ></div>
      </div>
    </header>

    <!-- 主内容区 -->
    <main v-if="selectedConversation" class="main-content">
      <!-- 概览卡片行 -->
      <section class="overview-cards">
        <div class="stat-card">
          <div class="card-icon">💬</div>
          <div class="card-content">
            <div class="card-value">{{ overview.totalSessions }}</div>
            <div class="card-label">总会话数</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="card-icon">⚡</div>
          <div class="card-content">
            <div class="card-value">{{ formatTime(overview.avgResponseTime) }}</div>
            <div class="card-label">平均响应时间</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="card-icon">🎯</div>
          <div class="card-content">
            <div class="card-value">{{ (overview.initiativeRate * 100).toFixed(1) }}%</div>
            <div class="card-label">对方主动率</div>
          </div>
        </div>

        <div class="stat-card">
          <div class="card-icon">📊</div>
          <div class="card-content">
            <div class="card-value">{{ overview.wordRatio.toFixed(2) }}x</div>
            <div class="card-label">字数投入比</div>
          </div>
        </div>
      </section>

      <!-- 图表区域 -->
      <div class="charts-grid">
        <!-- 会话时间轴 -->
        <div class="chart-card large">
          <div class="card-header">
            <h3>会话分布时间轴</h3>
            <div class="card-actions">
              <button @click="refreshSessions" class="icon-btn">🔄</button>
            </div>
          </div>
          <div class="chart-container">
            <div ref="timelineChart" class="chart"></div>
          </div>
        </div>

        <!-- 响应时间分析 -->
        <div class="chart-card">
          <div class="card-header">
            <h3>响应时间分布</h3>
          </div>
          <div class="stats-row">
            <div class="mini-stat">
              <span class="mini-label">平均</span>
              <span class="mini-value">{{ formatTime(responseTime.avg) }}</span>
            </div>
            <div class="mini-stat">
              <span class="mini-label">中位数</span>
              <span class="mini-value">{{ formatTime(responseTime.median) }}</span>
            </div>
            <div class="mini-stat">
              <span class="mini-label">最快</span>
              <span class="mini-value">{{ formatTime(responseTime.min) }}</span>
            </div>
            <div class="mini-stat">
              <span class="mini-label">最慢</span>
              <span class="mini-value">{{ formatTime(responseTime.max) }}</span>
            </div>
          </div>
          <div class="chart-container">
            <div ref="responseDistChart" class="chart"></div>
          </div>
          <div v-if="responseTime.abnormalCount > 0" class="abnormal-alert">
            ⚠️ {{ responseTime.abnormalCount }} 个异常响应时间
          </div>
        </div>

        <!-- 主动性分析 -->
        <div class="chart-card">
          <div class="card-header">
            <h3>主动性分析</h3>
          </div>
          <div class="chart-container">
            <div ref="initiativeChart" class="chart"></div>
          </div>
          <div class="interpretation">
            {{ initiativeStats.interpretation }}
          </div>
        </div>

        <!-- 字数投入分析 -->
        <div class="chart-card">
          <div class="card-header">
            <h3>字数投入对比</h3>
          </div>
          <div class="chart-container">
            <div ref="wordCountChart" class="chart"></div>
          </div>
          <div class="word-stats">
            <div class="word-stat-item">
              <span class="dot user"></span>
              <span>您: {{ wordCounts.user_char_count?.toLocaleString() }}字</span>
            </div>
            <div class="word-stat-item">
              <span class="dot other"></span>
              <span>对方: {{ wordCounts.other_char_count?.toLocaleString() }}字</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 详细数据表格 -->
      <section class="data-table-section">
        <div class="section-header">
          <h3>会话详细数据</h3>
          <div class="table-controls">
            <input
              v-model="searchQuery"
              placeholder="搜索会话..."
              class="search-input"
            />
          </div>
        </div>

        <div class="table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>会话ID</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th>消息数</th>
                <th>发起者</th>
                <th>时长</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="session in filteredSessions" :key="session.id">
                <td>#{{ session.id }}</td>
                <td>{{ formatTimestamp(session.start_time) }}</td>
                <td>{{ formatTimestamp(session.end_time) }}</td>
                <td>{{ session.message_count }}</td>
                <td>
                  <span :class="['initiator-badge', session.initiator]">
                    {{ session.initiator === 'user' ? '我' : '对方' }}
                  </span>
                </td>
                <td>{{ formatDuration(session.end_time - session.start_time) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <div class="empty-icon">📊</div>
      <h2>选择一个联系人开始分析</h2>
      <p>从上方下拉菜单中选择要分析的联系人</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { pywebview } from '../pywebview'

// 数据状态
const conversations = ref([])
const selectedConversation = ref(null)
const isExtracting = ref(false)
const progress = ref(0)

// 分析数据
const overview = ref({
  totalSessions: 0,
  avgResponseTime: 0,
  initiativeRate: 0,
  wordRatio: 0
})

const sessions = ref([])
const responseTime = ref({
  avg: 0,
  median: 0,
  min: 0,
  max: 0,
  abnormalCount: 0
})

const initiativeStats = ref({
  totalSessions: 0,
  userInitiatedSessions: 0,
  otherInitiatedSessions: 0,
  initiativeRate: 0,
  interpretation: ''
})

const wordCounts = ref({
  user_char_count: 0,
  other_char_count: 0,
  char_ratio: 0,
  interpretation: ''
})

const searchQuery = ref('')

// 图表实例
const timelineChart = ref(null)
const responseDistChart = ref(null)
const initiativeChart = ref(null)
const wordCountChart = ref(null)

let timelineChartInstance = null
let responseDistChartInstance = null
let initiativeChartInstance = null
let wordCountChartInstance = null

// 计算属性
const filteredSessions = computed(() => {
  if (!searchQuery.value) return sessions.value
  const query = searchQuery.value.toLowerCase()
  return sessions.value.filter(session =>
    session.id.toString().includes(query) ||
    session.initiator.toLowerCase().includes(query)
  )
})

// 方法
const loadConversations = async () => {
  try {
    const result = await pywebview.api.get_conversation_list()
    if (result.ok) {
      conversations.value = result.conversations
    }
  } catch (error) {
    console.error('加载联系人失败:', error)
  }
}

const loadConversationData = async () => {
  if (!selectedConversation.value) return

  const convId = selectedConversation.value

  try {
    // 并行加载所有数据
    const [sessionsData, responseTimeData, initiativeData, wordCountData] = await Promise.all([
      pywebview.api.get_sessions(convId, 100, 0),
      pywebview.api.get_response_times(convId),
      pywebview.api.get_initiative_stats(convId),
      pywebview.api.get_word_counts(convId, false)
    ])

    if (sessionsData.ok) {
      sessions.value = sessionsData.sessions
      overview.value.totalSessions = sessionsData.sessions.length
      await nextTick()
      renderTimelineChart()
    }

    if (responseTimeData.ok) {
      responseTime.value = responseTimeData.stats
      overview.value.avgResponseTime = responseTimeData.stats.avg
      await nextTick()
      renderResponseDistChart()
    }

    if (initiativeData.ok) {
      initiativeStats.value = initiativeData.stats
      overview.value.initiativeRate = initiativeData.stats.initiative_rate
      await nextTick()
      renderInitiativeChart()
    }

    if (wordCountData.ok) {
      wordCounts.value = wordCountData.word_counts.overall
      overview.value.wordRatio = wordCountData.word_counts.overall.char_ratio
      await nextTick()
      renderWordCountChart()
    }
  } catch (error) {
    console.error('加载分析数据失败:', error)
  }
}

const extractFeatures = async () => {
  if (!selectedConversation.value) return

  isExtracting.value = true
  progress.value = 0

  try {
    const result = await pywebview.api.extract_features(selectedConversation.value)

    if (result.ok) {
      const taskId = result.task_id

      // 轮询进度
      const checkProgress = setInterval(async () => {
        const progressResult = await pywebview.api.get_feature_extraction_progress(taskId)

        if (progressResult.ok) {
          progress.value = progressResult.progress

          if (progressResult.status === 'completed') {
            clearInterval(checkProgress)
            isExtracting.value = false
            await loadConversationData()
          } else if (progressResult.status === 'failed') {
            clearInterval(checkProgress)
            isExtracting.value = false
            console.error('特征提取失败:', progressResult.message)
          }
        }
      }, 500)
    }
  } catch (error) {
    console.error('提取特征失败:', error)
    isExtracting.value = false
  }
}

const reanalyze = async () => {
  if (!selectedConversation.value) return
  await extractFeatures()
}

const refreshSessions = () => {
  loadConversationData()
}

// 图表渲染
const renderTimelineChart = () => {
  if (!timelineChart.value) return

  if (timelineChartInstance) {
    timelineChartInstance.dispose()
  }

  timelineChartInstance = echarts.init(timelineChart.value)

  const userSessions = sessions.value.filter(s => s.initiator === 'user')
  const otherSessions = sessions.value.filter(s => s.initiator === 'other')

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: '#00f0ff',
      textStyle: { color: '#fff' }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: '#3a3a4a' } },
      axisLabel: { color: '#8b8b9e' },
      splitLine: { lineStyle: { color: '#2a2a3a' } }
    },
    yAxis: {
      type: 'category',
      data: ['对方发起', '我发起'],
      axisLine: { lineStyle: { color: '#3a3a4a' } },
      axisLabel: { color: '#8b8b9e' }
    },
    series: [
      {
        name: '我发起',
        type: 'scatter',
        data: userSessions.map(s => [s.start_time, 1, s.message_count]),
        symbolSize: (data) => Math.sqrt(data[2]) * 8,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.4, 0.3, 1, [
            { offset: 0, color: '#00f0ff' },
            { offset: 1, color: '#0080ff' }
          ]),
          shadowBlur: 10,
          shadowColor: 'rgba(0, 240, 255, 0.5)'
        }
      },
      {
        name: '对方发起',
        type: 'scatter',
        data: otherSessions.map(s => [s.start_time, 0, s.message_count]),
        symbolSize: (data) => Math.sqrt(data[2]) * 8,
        itemStyle: {
          color: new echarts.graphic.RadialGradient(0.4, 0.3, 1, [
            { offset: 0, color: '#ff0080' },
            { offset: 1, color: '#ff0040' }
          ]),
          shadowBlur: 10,
          shadowColor: 'rgba(255, 0, 128, 0.5)'
        }
      }
    ]
  }

  timelineChartInstance.setOption(option)
}

const renderResponseDistChart = () => {
  if (!responseDistChart.value) return

  if (responseDistChartInstance) {
    responseDistChartInstance.dispose()
  }

  responseDistChartInstance = echarts.init(responseDistChart.value)

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: '#00f0ff',
      textStyle: { color: '#fff' }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: ['平均', '中位数', '最快', '最慢'],
      axisLine: { lineStyle: { color: '#3a3a4a' } },
      axisLabel: { color: '#8b8b9e' }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#3a3a4a' } },
      axisLabel: {
        color: '#8b8b9e',
        formatter: (value) => `${Math.round(value / 60)}m`
      },
      splitLine: { lineStyle: { color: '#2a2a3a', type: 'dashed' } }
    },
    series: [
      {
        type: 'bar',
        data: [
          {
            value: responseTime.value.avg || 0,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#00f0ff' },
                { offset: 1, color: '#0080ff' }
              ])
            }
          },
          {
            value: responseTime.value.median || 0,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#00ff80' },
                { offset: 1, color: '#00ff40' }
              ])
            }
          },
          {
            value: responseTime.value.min || 0,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#ff00ff' },
                { offset: 1, color: '#ff0080' }
              ])
            }
          },
          {
            value: responseTime.value.max || 0,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#ffff00' },
                { offset: 1, color: '#ff8000' }
              ])
            }
          }
        ],
        barWidth: '50%',
        itemStyle: {
          borderRadius: [8, 8, 0, 0]
        }
      }
    ]
  }

  responseDistChartInstance.setOption(option)
}

const renderInitiativeChart = () => {
  if (!initiativeChart.value) return

  if (initiativeChartInstance) {
    initiativeChartInstance.dispose()
  }

  initiativeChartInstance = echarts.init(initiativeChart.value)

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: '#00f0ff',
      textStyle: { color: '#fff' }
    },
    legend: {
      orient: 'vertical',
      right: '10%',
      top: 'center',
      textStyle: { color: '#8b8b9e' }
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 10,
          borderColor: '#14141e',
          borderWidth: 2
        },
        label: {
          show: false
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 20,
            fontWeight: 'bold',
            color: '#fff'
          }
        },
        labelLine: {
          show: false
        },
        data: [
          {
            value: initiativeStats.value.userInitiatedSessions,
            name: '我发起',
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 1, 1, [
                { offset: 0, color: '#00f0ff' },
                { offset: 1, color: '#0080ff' }
              ])
            }
          },
          {
            value: initiativeStats.value.otherInitiatedSessions,
            name: '对方发起',
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 1, 1, [
                { offset: 0, color: '#ff0080' },
                { offset: 1, color: '#ff0040' }
              ])
            }
          }
        ]
      }
    ]
  }

  initiativeChartInstance.setOption(option)
}

const renderWordCountChart = () => {
  if (!wordCountChart.value) return

  if (wordCountChartInstance) {
    wordCountChartInstance.dispose()
  }

  wordCountChartInstance = echarts.init(wordCountChart.value)

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(20, 20, 30, 0.9)',
      borderColor: '#00f0ff',
      textStyle: { color: '#fff' }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: ['我', '对方'],
      axisLine: { lineStyle: { color: '#3a3a4a' } },
      axisLabel: { color: '#8b8b9e', fontSize: 14 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: {
        color: '#8b8b9e',
        formatter: (value) => `${(value / 1000).toFixed(1)}k`
      },
      splitLine: { lineStyle: { color: '#2a2a3a', type: 'dashed' } }
    },
    series: [
      {
        type: 'bar',
        data: [
          {
            value: wordCounts.value.user_char_count || 0,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#00f0ff' },
                { offset: 1, color: '#0080ff' }
              ])
            }
          },
          {
            value: wordCounts.value.other_char_count || 0,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: '#ff0080' },
                { offset: 1, color: '#ff0040' }
              ])
            }
          }
        ],
        barWidth: '40%',
        itemStyle: {
          borderRadius: [8, 8, 0, 0]
        },
        label: {
          show: true,
          position: 'top',
          color: '#fff',
          formatter: (params) => (params.value / 1000).toFixed(1) + 'k'
        }
      }
    ]
  }

  wordCountChartInstance.setOption(option)
}

// 工具函数
const formatTime = (seconds) => {
  if (!seconds) return '-'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

const formatTimestamp = (ts) => {
  return new Date(ts * 1000).toLocaleString('zh-CN')
}

const formatDuration = (seconds) => {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

// 生命周期
onMounted(async () => {
  await loadConversations()

  // 响应式调整图表大小
  window.addEventListener('resize', () => {
    timelineChartInstance?.resize()
    responseDistChartInstance?.resize()
    initiativeChartInstance?.resize()
    wordCountChartInstance?.resize()
  })
})
</script>

<style scoped>
/* 全局样式 */
:root {
  --bg-primary: #0a0a0f;
  --bg-secondary: #14141e;
  --bg-tertiary: #1a1a28;
  --accent-cyan: #00f0ff;
  --accent-blue: #0080ff;
  --accent-pink: #ff0080;
  --accent-green: #00ff80;
  --text-primary: #ffffff;
  --text-secondary: #8b8b9e;
  --border-color: #2a2a3a;
}

.analysis-container {
  min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: 'SF Mono', 'Fira Code', monospace;
  position: relative;
  overflow-x: hidden;
}

/* 背景效果 */
.grid-background {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-image:
    linear-gradient(rgba(0, 240, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 240, 255, 0.03) 1px, transparent 1px);
  background-size: 50px 50px;
  pointer-events: none;
  z-index: 0;
}

.ambient-glow {
  position: fixed;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(
    circle at center,
    rgba(0, 240, 255, 0.05) 0%,
    transparent 50%
  );
  animation: pulse 10s ease-in-out infinite;
  pointer-events: none;
  z-index: 0;
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* 顶部栏 */
.top-bar {
  position: relative;
  z-index: 10;
  background: rgba(20, 20, 30, 0.8);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border-color);
  padding: 1.5rem 2rem;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 2rem;
  flex-wrap: wrap;
}

.page-title {
  font-size: 1.8rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent-cyan), var(--accent-pink));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
  letter-spacing: -0.02em;
}

.subtitle {
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin: 0.25rem 0 0 0;
}

.actions {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.action-btn {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  font-family: inherit;
}

.action-btn.primary {
  background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
  color: var(--bg-primary);
  box-shadow: 0 4px 15px rgba(0, 240, 255, 0.3);
}

.action-btn.primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 240, 255, 0.4);
}

.action-btn.secondary {
  background: transparent;
  color: var(--accent-cyan);
  border: 1px solid var(--accent-cyan);
}

.action-btn.secondary:hover:not(:disabled) {
  background: rgba(0, 240, 255, 0.1);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.conversation-select {
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.9rem;
  font-family: inherit;
  cursor: pointer;
  min-width: 250px;
}

.conversation-select:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

/* 进度条 */
.progress-bar {
  margin-top: 1rem;
  height: 3px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-cyan), var(--accent-pink));
  transition: width 0.3s ease;
  box-shadow: 0 0 10px var(--accent-cyan);
}

/* 主内容 */
.main-content {
  position: relative;
  z-index: 1;
  padding: 2rem;
  max-width: 1800px;
  margin: 0 auto;
}

/* 概览卡片 */
.overview-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.stat-card {
  background: rgba(26, 26, 40, 0.6);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 1.5rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  transition: all 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-4px);
  border-color: var(--accent-cyan);
  box-shadow: 0 8px 30px rgba(0, 240, 255, 0.2);
}

.card-icon {
  font-size: 2.5rem;
  filter: drop-shadow(0 0 10px var(--accent-cyan));
}

.card-value {
  font-size: 2rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.card-label {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-top: 0.25rem;
}

/* 图表网格 */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.chart-card {
  background: rgba(26, 26, 40, 0.6);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 1.5rem;
  transition: all 0.3s ease;
}

.chart-card.large {
  grid-column: 1 / -1;
}

.chart-card:hover {
  border-color: rgba(0, 240, 255, 0.3);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.card-header h3 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.icon-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 1.2rem;
  padding: 0.5rem;
  border-radius: 6px;
  transition: all 0.3s ease;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--accent-cyan);
}

.chart-container {
  position: relative;
  height: 300px;
}

.chart {
  width: 100%;
  height: 100%;
}

/* 统计行 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  margin-bottom: 1rem;
}

.mini-stat {
  text-align: center;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
}

.mini-label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 0.25rem;
}

.mini-value {
  display: block;
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--accent-cyan);
}

/* 异常提示 */
.abnormal-alert {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 128, 0, 0.1);
  border-left: 3px solid #ff8000;
  border-radius: 6px;
  font-size: 0.85rem;
  color: #ff8000;
}

/* 解读文本 */
.interpretation {
  margin-top: 1rem;
  padding: 1rem;
  background: rgba(0, 240, 255, 0.05);
  border-left: 3px solid var(--accent-cyan);
  border-radius: 6px;
  font-size: 0.9rem;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* 字数统计 */
.word-stats {
  display: flex;
  gap: 1.5rem;
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
}

.word-stat-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot.user {
  background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
  box-shadow: 0 0 10px var(--accent-cyan);
}

.dot.other {
  background: linear-gradient(135deg, var(--accent-pink), var(--accent-blue));
  box-shadow: 0 0 10px var(--accent-pink);
}

/* 数据表格 */
.data-table-section {
  background: rgba(26, 26, 40, 0.6);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 1.5rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.section-header h3 {
  font-size: 1.2rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.search-input {
  padding: 0.5rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.85rem;
  font-family: inherit;
  width: 250px;
}

.search-input:focus {
  outline: none;
  border-color: var(--accent-cyan);
}

.table-container {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table thead {
  background: rgba(255, 255, 255, 0.03);
}

.data-table th {
  padding: 1rem;
  text-align: left;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.data-table td {
  padding: 1rem;
  border-top: 1px solid var(--border-color);
  font-size: 0.9rem;
  color: var(--text-primary);
}

.data-table tbody tr {
  transition: all 0.3s ease;
}

.data-table tbody tr:hover {
  background: rgba(0, 240, 255, 0.03);
}

.initiator-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.initiator-badge.user {
  background: rgba(0, 240, 255, 0.15);
  color: var(--accent-cyan);
}

.initiator-badge.other {
  background: rgba(255, 0, 128, 0.15);
  color: var(--accent-pink);
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  color: var(--text-secondary);
  text-align: center;
}

.empty-icon {
  font-size: 5rem;
  margin-bottom: 1.5rem;
  filter: drop-shadow(0 0 20px var(--accent-cyan));
}

.empty-state h2 {
  font-size: 1.5rem;
  color: var(--text-primary);
  margin: 0 0 0.5rem 0;
}

.empty-state p {
  font-size: 1rem;
  margin: 0;
}

/* 响应式 */
@media (max-width: 1200px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }

  .chart-card.large {
    grid-column: 1;
  }
}

@media (max-width: 768px) {
  .header-content {
    flex-direction: column;
    align-items: stretch;
  }

  .actions {
    flex-direction: column;
    width: 100%;
  }

  .conversation-select {
    width: 100%;
  }

  .overview-cards {
    grid-template-columns: 1fr;
  }

  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }

  .word-stats {
    flex-direction: column;
    gap: 0.5rem;
  }

  .section-header {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }

  .search-input {
    width: 100%;
  }
}
</style>
