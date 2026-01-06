<template>
  <div class="conversation-timeline">
    <div class="timeline-header">
      <h3>交互时间线</h3>
      <div class="timeline-controls">
        <CtButton
          v-for="view in viewModes"
          :key="view.key"
          :variant="currentView === view.key ? 'primary' : 'ghost'"
          size="small"
          @click="currentView = view.key"
        >
          {{ view.label }}
        </CtButton>
      </div>
    </div>

    <div v-if="sessions.length === 0" class="empty-state">
      <p>暂无会话数据</p>
    </div>

    <div v-else class="timeline-content">
      <!-- 按日期分组视图 -->
      <div v-if="currentView === 'date'" class="view-by-date">
        <div
          v-for="(group, date) in groupedByDate"
          :key="date"
          class="date-group"
        >
          <div class="date-header">
            <div class="date-badge">{{ formatDate(date) }}</div>
            <div class="date-count">{{ group.length }} 个会话</div>
          </div>
          <div class="sessions-list">
            <div
              v-for="session in group"
              :key="session.id"
              class="session-item"
              :class="{ expanded: expandedSessions.has(session.id) }"
            >
              <div class="session-summary" @click="toggleSession(session.id)">
                <div class="session-time">
                  {{ formatTime(session.start_time) }} - {{ formatTime(session.end_time) }}
                </div>
                <div class="session-stats">
                  <span class="stat">{{ session.message_count }} 条消息</span>
                  <span class="stat">{{ formatDuration(session.duration) }}</span>
                </div>
                <div class="expand-icon">
                  {{ expandedSessions.has(session.id) ? '▼' : '▶' }}
                </div>
              </div>
              <div v-if="expandedSessions.has(session.id)" class="session-messages">
                <div
                  v-for="msg in session.messages"
                  :key="msg.id"
                  class="message-item"
                  :class="{ 'is-me': msg.is_me }"
                >
                  <div class="message-avatar">{{ msg.sender_name.charAt(0) }}</div>
                  <div class="message-content">
                    <div class="message-header">
                      <span class="message-sender">{{ msg.sender_name }}</span>
                      <span class="message-time">{{ formatTime(msg.create_time) }}</span>
                    </div>
                    <div class="message-text">{{ msg.content }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 按会话列表视图 -->
      <div v-else-if="currentView === 'session'" class="view-by-session">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="session-card"
          :class="{ expanded: expandedSessions.has(session.id) }"
        >
          <div class="session-header" @click="toggleSession(session.id)">
            <div class="session-info">
              <div class="session-title">会话 #{{ session.id }}</div>
              <div class="session-meta">
                <span>{{ formatDateTime(session.start_time) }}</span>
                <span>·</span>
                <span>{{ session.message_count }} 条消息</span>
                <span>·</span>
                <span>{{ formatDuration(session.duration) }}</span>
              </div>
            </div>
            <div class="expand-icon">
              {{ expandedSessions.has(session.id) ? '▼' : '▶' }}
            </div>
          </div>
          <div v-if="expandedSessions.has(session.id)" class="session-body">
            <div class="messages-container">
              <div
                v-for="msg in session.messages"
                :key="msg.id"
                class="message-bubble"
                :class="{ 'is-me': msg.is_me }"
              >
                <div class="bubble-header">
                  <span class="sender">{{ msg.sender_name }}</span>
                  <span class="time">{{ formatTime(msg.create_time) }}</span>
                </div>
                <div class="bubble-content">{{ msg.content }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 统计视图 -->
      <div v-else-if="currentView === 'stats'" class="view-stats">
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">总会话数</div>
            <div class="stat-value">{{ sessions.length }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">总消息数</div>
            <div class="stat-value">{{ totalMessages }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">平均会话时长</div>
            <div class="stat-value">{{ avgDuration }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">最活跃时段</div>
            <div class="stat-value">{{ peakHours }}</div>
          </div>
        </div>

        <div class="chart-container">
          <h4>每日会话数量</h4>
          <div class="simple-chart">
            <div
              v-for="(item, index) in dailySessionCount"
              :key="index"
              class="chart-bar-wrapper"
            >
              <div
                class="chart-bar"
                :style="{ height: (item.count / maxDailyCount) * 100 + '%' }"
              >
                {{ item.count }}
              </div>
              <div class="chart-label">{{ item.date }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import CtButton from '@/components/base/CtButton.vue'

type Message = {
  id: number
  sender_name: string
  content: string
  create_time: string
  is_me: boolean
}

type Session = {
  id: number
  start_time: string
  end_time: string
  duration: number
  message_count: number
  messages: Message[]
}

const props = defineProps<{
  sessions: Session[]
}>()

const currentView = ref<'date' | 'session' | 'stats'>('date')
const expandedSessions = ref<Set<number>>(new Set())

const viewModes = [
  { key: 'date', label: '按日期' },
  { key: 'session', label: '按会话' },
  { key: 'stats', label: '统计' }
]

// 按日期分组
const groupedByDate = computed(() => {
  const groups: Record<string, Session[]> = {}

  props.sessions.forEach(session => {
    const date = new Date(session.start_time).toISOString().split('T')[0]
    if (!groups[date]) {
      groups[date] = []
    }
    groups[date].push(session)
  })

  // 按日期排序（降序）
  const sortedGroups: Record<string, Session[]> = {}
  Object.keys(groups).sort().reverse().forEach(date => {
    sortedGroups[date] = groups[date]
  })

  return sortedGroups
})

// 统计数据
const totalMessages = computed(() => {
  return props.sessions.reduce((sum, s) => sum + s.message_count, 0)
})

const avgDuration = computed(() => {
  if (props.sessions.length === 0) return '0分钟'
  const totalDuration = props.sessions.reduce((sum, s) => sum + s.duration, 0)
  const avg = totalDuration / props.sessions.length
  return formatDuration(avg)
})

const peakHours = computed(() => {
  const hourCounts: Record<number, number> = {}

  props.sessions.forEach(session => {
    const hour = new Date(session.start_time).getHours()
    hourCounts[hour] = (hourCounts[hour] || 0) + 1
  })

  let peakHour = 0
  let maxCount = 0

  Object.entries(hourCounts).forEach(([hour, count]) => {
    if (count > maxCount) {
      maxCount = count
      peakHour = parseInt(hour)
    }
  })

  return `${peakHour}:00-${peakHour + 1}:00`
})

// 每日会话数量
const dailySessionCount = computed(() => {
  const counts: Record<string, number> = {}

  Object.keys(groupedByDate.value).forEach(date => {
    counts[date] = groupedByDate.value[date].length
  })

  return Object.entries(counts)
    .map(([date, count]) => ({ date, count }))
    .reverse()
    .slice(0, 7)
})

const maxDailyCount = computed(() => {
  return Math.max(...dailySessionCount.value.map(d => d.count), 1)
})

function toggleSession(sessionId: number) {
  if (expandedSessions.value.has(sessionId)) {
    expandedSessions.value.delete(sessionId)
  } else {
    expandedSessions.value.add(sessionId)
  }
  // 触发响应式更新
  expandedSessions.value = new Set(expandedSessions.value)
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  if (dateStr === today.toISOString().split('T')[0]) {
    return '今天'
  }
  if (dateStr === yesterday.toISOString().split('T')[0]) {
    return '昨天'
  }

  return date.toLocaleDateString('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'short'
  })
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatDateTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)

  if (hours > 0) {
    return `${hours}小时${minutes}分钟`
  }
  return `${minutes}分钟`
}
</script>

<style scoped>
.conversation-timeline {
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-xl);
  border: 1px solid var(--ct-border-color);
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--ct-space-lg);
}

.timeline-header h3 {
  margin: 0;
  font-size: var(--ct-text-lg);
  font-weight: var(--ct-font-semibold);
  color: var(--ct-color-primary);
}

.timeline-controls {
  display: flex;
  gap: var(--ct-space-sm);
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: var(--ct-space-3xl) var(--ct-space-lg);
  color: var(--ct-text-tertiary);
}

/* 按日期视图 */
.date-group {
  margin-bottom: var(--ct-space-xl);
}

.date-header {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-md);
  position: sticky;
  top: 0;
  background: var(--ct-bg-elevated);
  padding: var(--ct-space-sm) 0;
  z-index: 10;
}

.date-badge {
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse);
  padding: var(--ct-space-xs) var(--ct-space-md);
  border-radius: var(--ct-radius-full);
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-semibold);
}

.date-count {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.sessions-list {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.session-item {
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  overflow: hidden;
  transition: all var(--ct-transition-fast) var(--ct-ease-out);
}

.session-item.expanded {
  border-color: var(--ct-color-primary);
}

.session-summary {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  padding: var(--ct-space-md);
  cursor: pointer;
  background: var(--ct-bg-secondary);
}

.session-summary:hover {
  background: var(--ct-bg-tertiary);
}

.session-time {
  font-weight: var(--ct-font-semibold);
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
}

.session-stats {
  flex: 1;
  display: flex;
  gap: var(--ct-space-md);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.expand-icon {
  color: var(--ct-color-primary);
  font-size: var(--ct-text-xs);
}

.session-messages {
  padding: var(--ct-space-md);
  background: var(--ct-bg-primary);
  border-top: 1px solid var(--ct-border-color);
  max-height: 400px;
  overflow-y: auto;
}

.message-item {
  display: flex;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-md);
}

.message-item:last-child {
  margin-bottom: 0;
}

.message-item.is-me {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--ct-color-primary) 0%, var(--ct-color-accent) 100%);
  color: var(--ct-text-inverse);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-semibold);
  flex-shrink: 0;
}

.message-content {
  flex: 1;
  max-width: 70%;
}

.message-header {
  display: flex;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-xs);
  font-size: var(--ct-text-xs);
}

.message-sender {
  font-weight: var(--ct-font-semibold);
  color: var(--ct-text-primary);
}

.message-time {
  color: var(--ct-text-tertiary);
}

.message-text {
  background: var(--ct-bg-secondary);
  padding: var(--ct-space-sm) var(--ct-space-md);
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
  word-break: break-word;
}

.message-item.is-me .message-text {
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse);
}

/* 会话卡片视图 */
.session-card {
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  margin-bottom: var(--ct-space-md);
  overflow: hidden;
}

.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--ct-space-md);
  cursor: pointer;
  background: var(--ct-bg-secondary);
}

.session-header:hover {
  background: var(--ct-bg-tertiary);
}

.session-title {
  font-weight: var(--ct-font-semibold);
  color: var(--ct-text-primary);
  margin-bottom: var(--ct-space-xs);
}

.session-meta {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  display: flex;
  gap: var(--ct-space-sm);
}

.session-body {
  padding: var(--ct-space-md);
  border-top: 1px solid var(--ct-border-color);
}

.messages-container {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.message-bubble {
  max-width: 80%;
}

.message-bubble.is-me {
  margin-left: auto;
}

.bubble-header {
  display: flex;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-xs);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
}

.bubble-content {
  background: var(--ct-bg-secondary);
  padding: var(--ct-space-sm) var(--ct-space-md);
  border-radius: var(--ct-radius-lg);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
  word-break: break-word;
}

.message-bubble.is-me .bubble-content {
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse);
}

/* 统计视图 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-lg);
}

.stat-card {
  background: var(--ct-bg-secondary);
  padding: var(--ct-space-lg);
  border-radius: var(--ct-radius-md);
  text-align: center;
}

.stat-label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  margin-bottom: var(--ct-space-sm);
}

.stat-value {
  font-size: var(--ct-text-2xl);
  font-weight: var(--ct-font-bold);
  color: var(--ct-color-primary);
}

.chart-container {
  margin-top: var(--ct-space-lg);
}

.chart-container h4 {
  margin: 0 0 var(--ct-space-lg) 0;
  font-size: var(--ct-text-base);
  color: var(--ct-text-primary);
}

.simple-chart {
  display: flex;
  align-items: flex-end;
  gap: var(--ct-space-md);
  height: 200px;
  padding: var(--ct-space-lg) 0;
}

.chart-bar-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ct-space-sm);
}

.chart-bar {
  width: 100%;
  min-height: 4px;
  background: linear-gradient(180deg, var(--ct-color-primary) 0%, var(--ct-color-accent) 100%);
  border-radius: var(--ct-radius-sm) var(--ct-radius-sm) 0 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  color: var(--ct-text-inverse);
  font-size: var(--ct-text-xs);
  font-weight: var(--ct-font-semibold);
  padding-top: var(--ct-space-xs);
  transition: height var(--ct-transition-normal);
}

.chart-label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  text-align: center;
}

/* 响应式 */
@media (max-width: 768px) {
  .timeline-header {
    flex-direction: column;
    gap: var(--ct-space-md);
    align-items: flex-start;
  }

  .timeline-controls {
    width: 100%;
    justify-content: space-between;
  }

  .message-item {
    flex-direction: column;
  }

  .message-item.is-me {
    flex-direction: column;
  }

  .message-content {
    max-width: 100%;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .simple-chart {
    height: 150px;
  }
}
</style>
