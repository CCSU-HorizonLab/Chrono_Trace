<template>
  <div class="fp">
    <!-- 顶部拖拽/控制栏 -->
    <header class="fp-header">
      <div class="fp-brand">
        <span class="fp-logo">⏱</span>
        <span class="fp-title">Chrono Trace</span>
      </div>
      <div class="fp-controls">
        <span class="fp-status-dot" :class="{ active: realtimeState.isMonitoring }"></span>
        <button class="fp-btn icon" @click="exitFloating" title="退出悬浮模式">✕</button>
      </div>
    </header>

    <div v-if="connectionLost" class="fp-connection-lost">
      <span>⚠️ 连接已断开，等待重新连接…</span>
      <button class="fp-btn small" @click="retryConnection">🔄 重试</button>
    </div>

    <!-- ChatWith 超时/错误提示 -->
    <div v-if="chatError && !connectionLost" class="fp-chat-error">
      <span>⚠️ {{ chatError }}</span>
      <button class="fp-btn small" @click="exitFloating">重新开始</button>
    </div>

    <!-- 监听对象信息 -->
    <div class="fp-contact">
      <div class="fp-avatar">{{ profileInitial }}</div>
      <div class="fp-contact-info">
        <div class="fp-contact-name">{{ profile.name || realtimeState.talkerName || '未选择' }}</div>
        <div class="fp-contact-tags" v-if="profile.personality_tags?.length">
          <span v-for="t in profile.personality_tags.slice(0, 4)" :key="t" class="fp-tag">{{ t }}</span>
        </div>
      </div>
      <button class="fp-btn icon" @click="profileExpanded = !profileExpanded"
        :title="profileExpanded ? '收起画像' : '展开画像'">
        {{ profileExpanded ? '▲' : '▼' }}
      </button>
    </div>

    <!-- 画像详情（折叠） -->
    <div v-show="profileExpanded" class="fp-profile-detail">
      <div v-if="profile.chat_style" class="fp-detail-row">
        <span class="fp-detail-icon">💬</span>
        <span>{{ profile.chat_style }}</span>
      </div>
      <div v-if="profile.interests?.length" class="fp-detail-row">
        <span class="fp-detail-icon">🎯</span>
        <span>{{ profile.interests.join('、') }}</span>
      </div>
      <div v-if="profile.communication_tips" class="fp-detail-row">
        <span class="fp-detail-icon">📌</span>
        <span>{{ profile.communication_tips }}</span>
      </div>
      <div v-if="profile.relationship_note" class="fp-detail-row">
        <span class="fp-detail-icon">💡</span>
        <span>{{ profile.relationship_note }}</span>
      </div>
      <div v-if="!profile.chat_style && !profileLoading" class="fp-detail-empty">
        <span>暂无画像</span>
        <button class="fp-btn small" @click="showProfileDialog = true">生成</button>
      </div>
    </div>

    <!-- 情绪曲线图 -->
    <div class="fp-section">
      <div class="fp-section-hd">
        <span>📈 情绪曲线</span>
        <span v-if="emotionSummary" class="fp-trend-badge" :class="emotionSummary.trend">
          {{ emotionSummary.trend === 'positive' ? '😊 正面' : emotionSummary.trend === 'negative' ? '😟 负面' : '😐 中性' }}
        </span>
      </div>
      <div class="fp-chart-wrap" ref="chartRef"></div>
    </div>

    <!-- 设置栏（紧凑） -->
    <div class="fp-settings">
      <div class="fp-seg">
        <button v-for="m in triggerModes" :key="m.value"
          :class="{ active: triggerMode === m.value }"
          @click="setTriggerMode(m.value)">{{ m.label }}</button>
      </div>
      <div class="fp-seg">
        <button v-for="i in intents" :key="i.value"
          :class="{ active: intent === i.value }"
          @click="setIntent(i.value)">{{ i.icon }}</button>
      </div>
    </div>

    <!-- AI 建议列表 -->
    <div class="fp-section fp-suggestions" ref="suggestionsRef">
      <div class="fp-section-hd">
        <span>💡 AI 建议</span>
        <span class="fp-badge" v-if="allSuggestions.length">{{ allSuggestions.length }}</span>
        <button class="fp-btn small" @click="showContext = !showContext"
          :class="{ active: showContext }" title="查看 AI 参考的聊天记录">
          📝 记录
        </button>
        <button class="fp-btn small" @click="manualGenerate" :disabled="loading">
          {{ loading ? '生成中…' : '🎯 生成' }}
        </button>
      </div>

      <!-- AI 参考聊天记录面板 -->
      <div v-show="showContext" class="fp-context-panel">
        <div class="fp-context-title">🔍 AI 参考的最近聊天（{{ contextUsed.length }} 条）</div>
        <div v-if="!contextUsed.length" class="fp-context-empty">尚未生成建议，暂无参考记录</div>
        <div v-for="(msg, i) in contextUsed" :key="i" class="fp-context-msg"
          :class="{ self: msg.sender === '我' }">
          <span class="fp-context-sender">{{ msg.sender }}</span>
          <span class="fp-context-text">{{ msg.content }}</span>
          <span class="fp-context-time" v-if="msg.timestamp">{{ formatMsgTime(msg.timestamp) }}</span>
        </div>
      </div>

      <div v-if="!allSuggestions.length && !loading" class="fp-empty">
        等待 AI 分析…
      </div>

      <div v-if="loading" class="fp-loading">
        <div class="fp-loading-bar"></div>
        <span>AI 正在思考 (已思考 {{ thinkingSeconds }} 秒)…</span>
      </div>

      <!-- 建议卡片 -->
      <div v-for="s in allSuggestions" :key="s.id || 'manual'" class="fp-suggestion-card" :class="s.severity">
        <div class="fp-sug-header" @click="toggleSuggestion(s)">
          <span class="fp-sug-icon">{{ getTriggerIcon(s.trigger_type) }}</span>
          <span class="fp-sug-summary">{{ s.summary }}</span>
          <span class="fp-sug-expand">{{ isSuggestionExpanded(s) ? '▼' : '▶' }}</span>
        </div>
        <div v-show="isSuggestionExpanded(s)" class="fp-sug-body">
          <div v-if="s.thought_process" class="fp-thought-process">
            <details>
              <summary>🤔 AI 思考过程</summary>
              <div class="fp-thought-content">{{ s.thought_process }}</div>
            </details>
          </div>
          <div v-for="(sp, i) in s.speeches" :key="i" class="fp-speech-item">
            <span class="fp-speech-text">{{ sp }}</span>
            <button class="fp-btn copy" @click="copyText(sp)">📋</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 用户交互输入区 -->
    <div class="fp-input-area">
      <!-- 快捷按钮 -->
      <transition-group name="fp-quick-list" tag="div" class="fp-quick-btns">
        <button v-for="q in quickPrompts" :key="q"
          class="fp-quick-btn"
          @click="sendQuickPrompt(q)">{{ q }}</button>
      </transition-group>
      <div class="fp-input-row">
        <input
          v-model="userInput"
          type="text"
          :placeholder="llmError ? '⚠️ 模型暂时不可用' : '告诉 AI 你的想法…'"
          :disabled="!!llmError"
          @keydown.enter.exact.prevent="sendUserContext"
        />
        <button class="fp-btn send" @click="sendUserContext" :disabled="!userInput.trim() || loading || !!llmError">
          ↑
        </button>
      </div>
      <!-- 模型选择栏 -->
      <div class="fp-model-row" v-if="llmModels.length > 0">
        <span class="fp-model-label">⚙️ 模型:</span>
        <select v-model="activeModelId" class="fp-model-select" @change="switchModel">
          <option v-for="m in llmModels" :key="m.id" :value="m.id" :disabled="disabledModels.has(m.id)">
            {{ m.name }} {{ disabledModels.has(m.id) ? '(不可用)' : '' }}
          </option>
        </select>
        <div v-if="llmError" class="fp-model-error" :title="llmError">❌ {{ llmError }}</div>
      </div>
    </div>
  </div>

  <!-- 画像生成弹窗（简化版） -->
  <Teleport to="body">
    <div v-if="showProfileDialog" class="fp-modal-overlay" @click.self="showProfileDialog = false">
      <div class="fp-modal">
        <div class="fp-modal-title">🧠 生成画像</div>
        <div class="fp-modal-desc">分析「{{ realtimeState.talkerName }}」的历史聊天</div>
        <div class="fp-modal-actions">
          <button class="fp-btn" @click="showProfileDialog = false">取消</button>
          <button class="fp-btn primary" @click="generateProfile">确认</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { bridgeReady, api } from '@/api/bridge'
import * as echarts from 'echarts'

const router = useRouter()

// ========== 状态 ==========
const realtimeState = reactive({
  isMonitoring: false,
  talkerName: '',
  batchId: '',
  messageCount: 0,
  status: 'idle' as string,
  messages: [] as any[]
})

const chatError = ref('')

const llmModels = ref<any[]>([])
const activeModelId = ref<number | null>(null)
const disabledModels = ref<Set<number>>(new Set())
const llmError = ref('')
const connectionLost = ref(false)  // 断流感知状态
let pollFailCount = 0  // 连续轮询失败计数

const intent = ref<'intimate' | 'maintain' | 'distance'>('maintain')
const triggerMode = ref<'full_auto' | 'semi_auto' | 'manual'>('semi_auto')
const loading = ref(false)
const userInput = ref('')
const profile = ref<any>({ name: '', tags: [] })
const profileLoading = ref(false)
const profileExpanded = ref(false)
const showProfileDialog = ref(false)
const emotionSummary = ref<any>(null)

// 建议数据
const pendingSuggestions = ref<any[]>([])
const manualSuggestion = ref<any>(null)
const expandedIds = ref<Set<string>>(new Set(['manual']))  // 展开状态管理
const showContext = ref(false)  // 是否展示 AI 参考记录
const contextUsed = ref<{ sender: string; content: string; timestamp: number }[]>([])  // AI 参考的聊天记录

// AI 对话历史
const conversationHistory = ref<{ role: string; content: string }[]>([])

// 情绪历史数据（用于曲线图）
const emotionHistory = ref<{ time: string; polarity: number; sender: string; content: string }[]>([])

// ECharts 引用
const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null
const suggestionsRef = ref<HTMLElement | null>(null)

// 定时器
let statusTimer: any = null
let messagesTimer: any = null
let suggestionsTimer: any = null

// ========== 常量 ==========
const triggerModes = [
  { value: 'full_auto', label: '全自动' },
  { value: 'semi_auto', label: '半自动' },
  { value: 'manual', label: '手动' },
]

const intents = [
  { value: 'intimate', icon: '🔥' },
  { value: 'maintain', icon: '⚖️' },
  { value: 'distance', icon: '❄️' },
]

const quickPrompts = ref<string[]>([
  '拉近距离',
  '化解尴尬',
  '延续话题',
  '表达关心',
])

// ========== 计算属性 ==========
const profileInitial = computed(() => {
  const name = profile.value.name || realtimeState.talkerName
  return name ? name[0] : '?'
})

const allSuggestions = computed(() => {
  const list: any[] = []
  if (manualSuggestion.value) {
    list.push({ ...manualSuggestion.value, id: 'manual' })
  }
  for (const s of pendingSuggestions.value) {
    list.push({ ...s })
  }
  return list
})

// ========== 生命周期 ==========
onMounted(async () => {
  // 尝试恢复监听状态（带重试，因为现在悬浮模式先于监听启动）
  let status: any = null
  const MAX_RETRIES = 5
  const RETRY_DELAY = 1000 // ms

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      await bridgeReady()
      if (attempt > 0) {
        await new Promise(r => setTimeout(r, RETRY_DELAY))
      }
      status = await api.get_realtime_status()
      if (status.ok && status.is_monitoring) {
        break
      }
      console.warn(`[FloatingPanel] 第 ${attempt + 1} 次状态检查: is_monitoring=${status?.is_monitoring}`)
    } catch (e) {
      console.error(`[FloatingPanel] 第 ${attempt + 1} 次检查失败:`, e)
    }
  }

  if (status?.ok && status.is_monitoring) {
    realtimeState.isMonitoring = true
    realtimeState.status = 'monitoring'
    realtimeState.talkerName = status.talker_display_name || ''
    realtimeState.batchId = status.batch_id || ''
    realtimeState.messageCount = status.message_count || 0
    // 检查 chat_error
    if (status.chat_error) {
      chatError.value = status.chat_error
    }

    startPolling()
    loadSuggestionConfig()
    loadLlmModels()
    checkContactProfile(realtimeState.talkerName)
  } else {
    // 多次重试后仍未在监听状态，退回
    console.error('[FloatingPanel] 无法恢复监听状态，退出悬浮模式')
    goBackToSuggestions()
    return
  }

  // 初始化图表
  initChart()
})

onBeforeUnmount(() => {
  stopPolling()
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

// ========== 悬浮窗控制 ==========
async function exitFloating() {
  try {
    await bridgeReady()
    // 停止监听
    if (realtimeState.isMonitoring) {
      await api.stop_realtime_monitor()
    }
    stopPolling()
    // 退出悬浮模式（恢复窗口尺寸）
    await api.exit_floating_mode()
  } catch (e) {
    console.error('退出悬浮模式失败:', e)
  }
  // 跳转回建议页
  router.push('/suggestions')
}

/** 仅退回建议页（不停止监听，用于状态恢复失败时） */
async function goBackToSuggestions() {
  stopPolling()
  try {
    await bridgeReady()
    await api.exit_floating_mode()
  } catch (e) {
    console.error('退出悬浮模式失败:', e)
  }
  router.push('/suggestions')
}

// ========== ECharts 情绪曲线图 ==========
function initChart() {
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })

  const option: echarts.EChartsOption = {
    grid: {
      top: 10,
      right: 10,
      bottom: 24,
      left: 36,
    },
    xAxis: {
      type: 'category',
      data: [],
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#334155' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: -1,
      max: 1,
      splitNumber: 4,
      axisLabel: { fontSize: 10, color: '#94a3b8', formatter: '{value}' },
      splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
      axisLine: { show: false },
    },
    series: [{
      type: 'line',
      data: [],
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { width: 2.5 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(129,140,248,0.3)' },
          { offset: 1, color: 'rgba(129,140,248,0.02)' },
        ]),
      },
      itemStyle: {
        color: (params: any) => {
          const v = params.data as number
          if (v > 0.2) return '#34d399'
          if (v < -0.2) return '#f87171'
          return '#94a3b8'
        },
      },
    }],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e293b',
      borderColor: '#334155',
      textStyle: { color: '#f1f5f9', fontSize: 12 },
      formatter: (params: any) => {
        const p = params[0]
        const idx = p.dataIndex
        const v = p.data as number
        const label = v > 0 ? '正面' : v < 0 ? '负面' : '中性'
        const item = emotionHistory.value[idx]
        let html = `<b>${p.name}</b><br/>情绪: ${label} (${v.toFixed(2)})`
        if (item) {
          const sender = item.sender === 'self' ? '我' : '对方'
          const content = item.content.length > 25 ? item.content.slice(0, 25) + '…' : item.content
          html += `<br/><span style="color:#94a3b8">${sender}：${content}</span>`
        }
        return html
      },
    },
  }

  chartInstance.setOption(option)
}

function updateChart() {
  if (!chartInstance) return
  const times = emotionHistory.value.map(e => e.time)
  const values = emotionHistory.value.map(e => e.polarity)
  chartInstance.setOption({
    xAxis: { data: times },
    series: [{ data: values }],
  })
}

// ========== 轮询 ==========
function startPolling() {
  stopPolling()

  let notMonitoringCount = 0  // 连续未在监听的计数
  let lastMessageCount = -1   // 记录上次的消息数量
  let unchangedCount = 0      // 消息数量未变的轮询次数

  // 状态轮询
  statusTimer = setInterval(async () => {
    try {
      await bridgeReady()
      const s = await api.get_realtime_status()
      console.log('[FloatingPanel] 状态轮询:', JSON.stringify({
        is_monitoring: s.is_monitoring,
        message_count: s.message_count,
        batch_id: s.batch_id?.slice(0, 8),
      }))
      if (s.ok) {
        realtimeState.isMonitoring = s.is_monitoring
        realtimeState.messageCount = s.message_count || 0
        pollFailCount = 0  // 成功则重置失败计数

        // 检测断流：polling_alive 为 false 表示后端轮询线程已死亡
        if (s.polling_alive === false && s.is_monitoring) {
          connectionLost.value = true
        } else if (s.polling_alive !== false) {
          connectionLost.value = false
        }

        // 检测 ChatWith 错误
        if (s.chat_error) {
          chatError.value = s.chat_error
        } else if (s.chat_ready) {
          chatError.value = ''
        }
        if (!s.is_monitoring) {
          notMonitoringCount++
          // 连续 2 次检测到未在监听才退出（避免偶发抖动）
          if (notMonitoringCount >= 2) {
            console.warn('[FloatingPanel] 连续检测到未在监听，退出悬浮模式')
            goBackToSuggestions()
          }
        } else {
          notMonitoringCount = 0
        }
      } else {
        pollFailCount++
        if (pollFailCount >= 3) {
          connectionLost.value = true
        }
      }
    } catch (e) { console.error('状态轮询失败:', e) }
  }, 2000)

  // 消息轮询
  messagesTimer = setInterval(async () => {
    if (!realtimeState.batchId) {
      console.warn('[FloatingPanel] 消息轮询: batchId 为空，跳过')
      return
    }
    try {
      await bridgeReady()
      const r = await api.get_realtime_messages(realtimeState.batchId, 50)
      console.log('[FloatingPanel] 消息轮询:', r.ok ? `${(r.messages||[]).length} 条` : '失败')
      if (r.ok) {
        const prevLen = realtimeState.messages.length
        realtimeState.messages = r.messages || []

        // 更新情绪历史
        if (realtimeState.messages.length > prevLen) {
          updateEmotionHistory()
        }

        // --- 动态联想词逻辑 ---
        if (lastMessageCount !== -1) {
          if (realtimeState.messages.length > lastMessageCount) {
            // 有新消息，重置停顿计数
            unchangedCount = 0
          } else {
            // 消息数量没变，增加停顿计数
            unchangedCount++
          }
          
          // 如果停顿了 2 次轮询（约 6 秒），并且之前有新消息触发，则请求新的联想词
          if (unchangedCount === 2 && !llmError.value) {
             const promptRes = await api.get_dynamic_quick_prompts(realtimeState.batchId)
             if (promptRes.ok && promptRes.prompts && promptRes.prompts.length > 0) {
               llmError.value = ''
               // 避免不必要的更新
               if (quickPrompts.value.join('') !== promptRes.prompts.join('')) {
                 quickPrompts.value = promptRes.prompts
               }
             } else if (!promptRes.ok && promptRes.error) {
               console.error('[FloatingPanel] 动态联想词获取失败:', promptRes.error)
               handleLlmError(promptRes.error)
             }
          }
        }
        lastMessageCount = realtimeState.messages.length
      }
    } catch (e) { console.error('消息轮询失败:', e) }
  }, 3000)

  // 建议轮询
  suggestionsTimer = setInterval(async () => {
    if (!realtimeState.batchId) return
    try {
      await bridgeReady()
      const r = await api.get_pending_suggestions(realtimeState.batchId)
      if (r.ok) {
        pendingSuggestions.value = (r.suggestions || []).map((s: any) => ({
          ...s,
          _expanded: pendingSuggestions.value.find((ps: any) => ps.id === s.id)?._expanded || false
        }))
        emotionSummary.value = r.emotion_summary || null
      }
    } catch (e) { console.error('建议轮询失败:', e) }
  }, 3000)
}

function stopPolling() {
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null }
  if (messagesTimer) { clearInterval(messagesTimer); messagesTimer = null }
  if (suggestionsTimer) { clearInterval(suggestionsTimer); suggestionsTimer = null }
}

// ========== 情绪历史更新 ==========
function updateEmotionHistory() {
  const msgs = realtimeState.messages
  const newHistory: { time: string; polarity: number; sender: string; content: string }[] = []

  for (const msg of msgs) {
    if (msg.sentiment) {
      const date = new Date(msg.timestamp * 1000)
      newHistory.push({
        time: date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        polarity: msg.sentiment.polarity || 0,
        sender: msg.sender_attr || 'friend',
        content: msg.content || '',
      })
    }
  }

  // 只保留最近 20 个数据点
  emotionHistory.value = newHistory.slice(-20)
  updateChart()
}

// ========== 建议配置 ==========
async function loadSuggestionConfig() {
  try {
    const r = await api.get_suggestion_config()
    if (r.ok && r.config) {
      triggerMode.value = r.config.trigger_mode || 'semi_auto'
      intent.value = r.config.intent || 'maintain'
    }
  } catch (e) { console.error('加载建议配置失败:', e) }
}

async function setTriggerMode(mode: string) {
  triggerMode.value = mode as any
  try { await api.set_suggestion_config({ trigger_mode: mode }) }
  catch (e) { console.error('设置触发模式失败:', e) }
}

async function setIntent(newIntent: string) {
  intent.value = newIntent as any
  try { await api.set_suggestion_config({ intent: newIntent }) }
  catch (e) { console.error('设置走向失败:', e) }
}

// ========== 模型配置 ==========
async function loadLlmModels() {
  try {
    const res = await api.get_llm_models()
    if (res.ok && res.models) {
      llmModels.value = res.models
      const active = res.models.find((m: any) => m.is_active)
      if (active) {
        activeModelId.value = active.id
      }
    }
  } catch (e) {
    console.error('加载 LLM 模型列表失败:', e)
  }
}

async function switchModel() {
  if (!activeModelId.value) return
  try {
    await api.save_llm_model({ id: activeModelId.value, is_active: 1 })
    llmError.value = '' // 切换模型后清除错误状态
    // 如果有快速联想失败的，重试一次
    // 注意：lastMessageCount 是局部变量，这里我们只需清空历史就可以强制重新触发
    conversationHistory.value = []
  } catch (e) {
    console.error('切换模型失败:', e)
  }
}

function handleLlmError(errorMsg: string) {
  llmError.value = errorMsg
  if (activeModelId.value) {
    disabledModels.value.add(activeModelId.value)
    disabledModels.value = new Set(disabledModels.value)
  }
}

// ========== AI 建议操作 ==========
const thinkingSeconds = ref(0)
let thinkingTimer: any = null

function __startThinkingTimer() {
  thinkingSeconds.value = 0
  if (thinkingTimer) clearInterval(thinkingTimer)
  thinkingTimer = setInterval(() => {
    thinkingSeconds.value++
  }, 1000)
}

function __stopThinkingTimer() {
  if (thinkingTimer) {
    clearInterval(thinkingTimer)
    thinkingTimer = null
  }
}

async function manualGenerate() {
  loading.value = true
  __startThinkingTimer()
  llmError.value = ''
  try {
    await bridgeReady()
    const r = await api.generate_suggestion(intent.value, {
      user_context: conversationHistory.value.length ? conversationHistory.value : undefined,
    })
    if (r.ok && r.suggestion) {
      manualSuggestion.value = r.suggestion
      expandedIds.value.add('manual')
      expandedIds.value = new Set(expandedIds.value)
    } else {
      loading.value = false
      __stopThinkingTimer()
      handleLlmError(r.error || '生成失败')
      return
    }
    // 保存 AI 参考的聊天记录
    if (r.context_used?.recent_messages) {
      contextUsed.value = r.context_used.recent_messages
    }
  } catch (e: any) { 
    console.error('手动生成失败:', e) 
    handleLlmError(e.message || '网络错误')
  }
  finally { 
    loading.value = false
    __stopThinkingTimer()
  }
}

function toggleSuggestion(s: any) {
  const id = String(s.id || 'manual')
  if (expandedIds.value.has(id)) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
  // 触发响应式更新
  expandedIds.value = new Set(expandedIds.value)
}

function isSuggestionExpanded(s: any): boolean {
  return expandedIds.value.has(String(s.id || 'manual'))
}

function copyText(text: string) {
  navigator.clipboard?.writeText(text)
}

function getTriggerIcon(type: string): string {
  const icons: Record<string, string> = {
    negative_streak: '🔴',
    emotion_shift: '⚡',
    perfunctory: '💤',
    silence: '🔇',
    positive_window: '🟢',
    topic_cooling: '🧊',
  }
  return icons[type] || '📌'
}

// ========== 用户交互 ==========
async function sendUserContext() {
  const content = userInput.value.trim()
  if (!content || loading.value || !!llmError.value) return

  conversationHistory.value.push({ role: 'user', content })
  userInput.value = ''
  loading.value = true
  __startThinkingTimer()
  llmError.value = ''

  try {
    await bridgeReady()
    const r = await api.generate_suggestion(intent.value, {
      user_context: conversationHistory.value,
      include_history: true,
    })
    if (r.ok && r.suggestion) {
      manualSuggestion.value = r.suggestion
      expandedIds.value.add('manual')
      expandedIds.value = new Set(expandedIds.value)
      conversationHistory.value.push({ role: 'ai', content: r.suggestion.summary || '已生成建议' })
    } else {
      conversationHistory.value.push({ role: 'ai', content: `[生成失败] ${r.error || '未知错误'}` })
      handleLlmError(r.error || '生成失败')
    }
    // 保存 AI 参考的聊天记录
    if (r.context_used?.recent_messages) {
      contextUsed.value = r.context_used.recent_messages
    }
  } catch (e: any) {
    console.error('发送失败:', e)
    conversationHistory.value.push({ role: 'ai', content: `[系统错误] ${e.message || '网络或接口故障'}` })
    handleLlmError(e.message || '系统错误')
  } finally {
    loading.value = false
    __stopThinkingTimer()
  }
}

/** 格式化消息时间 */
function formatMsgTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function sendQuickPrompt(prompt: string) {
  userInput.value = prompt
  sendUserContext()
}

/** 断流后重试连接 */
async function retryConnection() {
  connectionLost.value = false
  pollFailCount = 0
  chatError.value = ''
  try {
    await bridgeReady()
    const s = await api.get_realtime_status()
    if (s.ok && s.is_monitoring) {
      realtimeState.isMonitoring = true
      realtimeState.messageCount = s.message_count || 0
      if (s.chat_error) {
        chatError.value = s.chat_error
      }
    } else {
      // 监听已完全停止，退回建议页
      goBackToSuggestions()
    }
  } catch (e) {
    console.error('重试连接失败:', e)
    connectionLost.value = true
  }
}

// ========== 画像 ==========
async function checkContactProfile(name: string) {
  if (!name) return
  try {
    await bridgeReady()
    const r = await api.get_contact_profile(name)
    if (r.ok && r.has_profile && !r.expired) {
      profile.value = { name, ...r.profile }
    } else {
      profile.value = { name, tags: [] }
    }
  } catch (e) { console.error('检查画像失败:', e) }
}

async function generateProfile() {
  showProfileDialog.value = false
  profileLoading.value = true
  try {
    await bridgeReady()
    const r = await api.generate_contact_profile(realtimeState.talkerName, 'medium', 0)
    if (r.ok && r.profile) {
      profile.value = { name: realtimeState.talkerName, ...r.profile }
    }
  } catch (e) { console.error('生成画像失败:', e) }
  finally { profileLoading.value = false }
}
</script>

<style scoped>
/* ==================== 悬浮面板全局 ==================== */
.fp {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--ct-bg-primary);
  font-family: var(--ct-font-body);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
}

/* ==================== 顶部栏 ==================== */
.fp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--ct-bg-elevated);
  border-bottom: 1px solid var(--ct-border-color);
  /* 允许拖拽窗口 */
  -webkit-app-region: drag;
  flex-shrink: 0;
}

.fp-brand {
  display: flex;
  align-items: center;
  gap: 6px;
}

.fp-logo {
  font-size: 16px;
}

.fp-title {
  font-family: var(--ct-font-display);
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-color-primary);
}

.fp-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  -webkit-app-region: no-drag;
}

.fp-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ct-text-tertiary);
  transition: background 0.3s;
}

.fp-status-dot.active {
  background: var(--ct-color-success);
  box-shadow: 0 0 6px var(--ct-color-success);
  animation: fp-pulse 2s infinite;
}

@keyframes fp-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--ct-color-success); }
  50% { opacity: 0.6; box-shadow: 0 0 12px var(--ct-color-success); }
}

/* ==================== 联系人信息 ==================== */
.fp-contact {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--ct-border-color);
  flex-shrink: 0;
}

.fp-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--ct-color-primary), var(--ct-color-accent));
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 14px;
  flex-shrink: 0;
}

.fp-contact-info {
  flex: 1;
  min-width: 0;
}

.fp-contact-name {
  font-weight: 600;
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fp-contact-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 3px;
}

/* ==================== 快捷按钮动画 ==================== */
.fp-quick-list-move,
.fp-quick-list-enter-active,
.fp-quick-list-leave-active {
  transition: all 0.4s ease;
}
.fp-quick-list-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.fp-quick-list-leave-to {
  opacity: 0;
  transform: translateY(-10px);
  position: absolute;
}

/* ==================== 思维链 CoT ==================== */
.fp-thought-process {
  margin-bottom: 8px;
  background: var(--ct-bg-elevated);
  border-radius: 6px;
  border: 1px dashed var(--ct-border-color);
}

.fp-thought-process details {
  padding: 6px 10px;
}

.fp-thought-process summary {
  font-size: 11px;
  color: var(--ct-text-secondary);
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  outline: none;
}

.fp-thought-process summary::marker {
  color: var(--ct-text-tertiary);
}

.fp-thought-content {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--ct-border-color);
  font-size: 12px;
  color: var(--ct-text-secondary);
  line-height: 1.5;
  white-space: pre-wrap;
}

/* ==================== 模型选择区 ==================== */
.fp-model-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 0 4px;
}

.fp-model-label {
  font-size: 11px;
  color: var(--ct-text-secondary);
}

.fp-model-select {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-primary);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  outline: none;
  cursor: pointer;
}

.fp-model-select:focus {
  border-color: var(--ct-color-primary);
}

.fp-model-select option:disabled {
  color: var(--ct-text-tertiary);
  font-style: italic;
}

.fp-model-error {
  font-size: 11px;
  color: var(--ct-color-danger);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
}

.fp-tag {
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  padding: 1px 6px;
  border-radius: var(--ct-radius-full);
  font-size: 10px;
  font-weight: 500;
}

/* ==================== 画像详情 ==================== */
.fp-profile-detail {
  padding: 6px 12px 10px;
  border-bottom: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
  flex-shrink: 0;
}

.fp-detail-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--ct-text-secondary);
  line-height: 1.5;
}

.fp-detail-icon {
  flex-shrink: 0;
  font-size: 12px;
}

.fp-detail-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--ct-text-tertiary);
  padding: 4px 0;
}

/* ==================== 情绪曲线图 ==================== */
.fp-section {
  flex-shrink: 0;
  border-bottom: 1px solid var(--ct-border-color);
}

.fp-section-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ct-text-secondary);
}

.fp-trend-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--ct-radius-full);
  font-weight: 500;
}

.fp-trend-badge.positive {
  background: var(--ct-color-success-light);
  color: var(--ct-color-success);
}

.fp-trend-badge.negative {
  background: var(--ct-color-error-light);
  color: var(--ct-color-error);
}

.fp-trend-badge.neutral {
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-tertiary);
}

.fp-chart-wrap {
  width: 100%;
  height: 140px;
  padding: 0 4px;
}

/* ==================== 设置栏 ==================== */
.fp-settings {
  display: flex;
  gap: 6px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--ct-border-color);
  flex-shrink: 0;
}

.fp-seg {
  display: flex;
  border-radius: var(--ct-radius-md);
  overflow: hidden;
  border: 1px solid var(--ct-border-color);
  flex: 1;
}

.fp-seg button {
  flex: 1;
  padding: 4px 2px;
  border: none;
  background: var(--ct-bg-elevated);
  color: var(--ct-text-tertiary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}

.fp-seg button:not(:last-child) {
  border-right: 1px solid var(--ct-border-color);
}

.fp-seg button.active {
  background: var(--ct-color-primary);
  color: white;
  font-weight: 600;
}

.fp-seg button:hover:not(.active) {
  background: var(--ct-bg-tertiary);
}

/* ==================== AI 建议 ==================== */
.fp-suggestions {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  border-bottom: none;
}

.fp-suggestions .fp-section-hd {
  position: sticky;
  top: 0;
  background: var(--ct-bg-primary);
  z-index: 2;
  border-bottom: 1px solid var(--ct-border-color);
}

.fp-badge {
  background: var(--ct-color-error);
  color: white;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 600;
}

.fp-empty {
  padding: 20px 12px;
  text-align: center;
  color: var(--ct-text-tertiary);
  font-size: 12px;
}

.fp-loading {
  padding: 12px;
  text-align: center;
  color: var(--ct-color-primary);
  font-size: 12px;
}

.fp-loading-bar {
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--ct-color-primary), transparent);
  background-size: 200% 100%;
  animation: fp-loading-slide 1.5s infinite;
  border-radius: 1px;
  margin-bottom: 8px;
}

@keyframes fp-loading-slide {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.fp-suggestion-card {
  margin: 6px 10px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  overflow: hidden;
  transition: all 0.15s;
}

.fp-suggestion-card.high { border-left: 3px solid var(--ct-color-error); }
.fp-suggestion-card.medium { border-left: 3px solid var(--ct-color-warning); }
.fp-suggestion-card.low { border-left: 3px solid var(--ct-color-success); }

.fp-sug-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  cursor: pointer;
  transition: background 0.15s;
}

.fp-sug-header:hover { background: var(--ct-bg-tertiary); }

.fp-sug-icon { font-size: 13px; flex-shrink: 0; }
.fp-sug-summary { flex: 1; font-size: 12px; font-weight: 500; line-height: 1.4; }
.fp-sug-expand { color: var(--ct-text-tertiary); font-size: 10px; flex-shrink: 0; }

/* ==================== AI 参考记录面板 ==================== */
.fp-context-panel {
  margin: 0 10px 6px;
  padding: 8px;
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  max-height: 180px;
  overflow-y: auto;
}

.fp-context-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--ct-text-secondary);
  margin-bottom: 6px;
}

.fp-context-empty {
  font-size: 11px;
  color: var(--ct-text-tertiary);
  text-align: center;
  padding: 8px 0;
}

.fp-context-msg {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 6px;
  border-radius: var(--ct-radius-sm);
  font-size: 11px;
  line-height: 1.5;
}

.fp-context-msg:nth-child(odd) {
  background: var(--ct-bg-tertiary);
}

.fp-context-msg.self .fp-context-sender {
  color: var(--ct-color-primary);
}

.fp-context-sender {
  font-weight: 600;
  color: var(--ct-color-accent);
  flex-shrink: 0;
  min-width: 28px;
}

.fp-context-text {
  flex: 1;
  color: var(--ct-text-primary);
  word-break: break-all;
}

.fp-context-time {
  flex-shrink: 0;
  color: var(--ct-text-tertiary);
  font-size: 10px;
}

.fp-btn.small.active {
  background: var(--ct-color-primary-light);
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.fp-context-panel::-webkit-scrollbar {
  width: 3px;
}

.fp-context-panel::-webkit-scrollbar-thumb {
  background: var(--ct-border-color);
  border-radius: 2px;
}

.fp-sug-body {
  padding: 6px 10px 10px;
  border-top: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
}

.fp-speech-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 8px;
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-sm);
  margin-bottom: 4px;
}

.fp-speech-text {
  flex: 1;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ct-text-primary);
}

/* ==================== 用户输入区 ==================== */
.fp-input-area {
  flex-shrink: 0;
  border-top: 1px solid var(--ct-border-color);
  background: var(--ct-bg-elevated);
}

.fp-quick-btns {
  display: flex;
  gap: 4px;
  padding: 6px 10px 0;
  overflow-x: auto;
}

.fp-quick-btn {
  padding: 3px 10px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  background: var(--ct-bg-secondary);
  color: var(--ct-text-secondary);
  font-size: 11px;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.15s;
}

.fp-quick-btn:hover {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-light);
}

.fp-input-row {
  display: flex;
  gap: 6px;
  padding: 8px 10px;
}

.fp-input-row input {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  font-size: 12px;
  background: var(--ct-bg-primary);
  color: var(--ct-text-primary);
  transition: border-color 0.15s;
}

.fp-input-row input:focus {
  outline: none;
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 2px var(--ct-color-primary-light);
}

/* ==================== 通用按钮 ==================== */
.fp-btn {
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.fp-btn.icon {
  width: 24px;
  height: 24px;
  border-radius: var(--ct-radius-sm);
  color: var(--ct-text-tertiary);
  font-size: 12px;
}

.fp-btn.icon:hover {
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-primary);
}

.fp-btn.small {
  padding: 3px 10px;
  font-size: 11px;
  border-radius: var(--ct-radius-sm);
  color: var(--ct-color-primary);
  border: 1px solid var(--ct-color-primary);
}

.fp-btn.small:hover {
  background: var(--ct-color-primary-light);
}

.fp-btn.small:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.fp-btn.copy {
  padding: 2px;
  font-size: 12px;
  flex-shrink: 0;
  opacity: 0.5;
}

.fp-btn.copy:hover { opacity: 1; }

.fp-btn.send {
  width: 32px;
  height: 32px;
  border-radius: var(--ct-radius-md);
  background: var(--ct-color-primary);
  color: white;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}

.fp-btn.send:hover:not(:disabled) {
  background: var(--ct-color-primary-hover);
  transform: translateY(-1px);
}

.fp-btn.send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.fp-btn.primary {
  background: var(--ct-color-primary);
  color: white;
  padding: 6px 16px;
  border-radius: var(--ct-radius-md);
  font-size: 13px;
  font-weight: 500;
}

.fp-btn.primary:hover {
  background: var(--ct-color-primary-hover);
}

/* ==================== 弹窗 ==================== */
.fp-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.fp-modal {
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-lg);
  padding: 20px;
  width: 300px;
  box-shadow: var(--ct-shadow-xl);
}

.fp-modal-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 8px;
}

.fp-modal-desc {
  font-size: 13px;
  color: var(--ct-text-secondary);
  margin-bottom: 16px;
}

.fp-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* ==================== 滚动条 ==================== */
.fp-suggestions::-webkit-scrollbar {
  width: 4px;
}

.fp-suggestions::-webkit-scrollbar-track {
  background: transparent;
}

.fp-suggestions::-webkit-scrollbar-thumb {
  background: var(--ct-border-color);
  border-radius: 2px;
}

/* ==================== 断流感知横幅 ==================== */
.fp-connection-lost {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: linear-gradient(135deg, #fecaca 0%, #fde2e2 100%);
  border-bottom: 1px solid #ef4444;
  color: #991b1b;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
  animation: fp-pulse-bg 2s ease-in-out infinite;
}

@keyframes fp-pulse-bg {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.75; }
}

.fp-connection-lost .fp-btn.small {
  background: #ef4444;
  color: white;
  border: none;
  padding: 3px 10px;
  border-radius: var(--ct-radius-md);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

/* ==================== ChatWith 错误提示 ==================== */
.fp-chat-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: #fef3c7;
  border-bottom: 1px solid #f59e0b;
  color: #92400e;
  font-size: 12px;
  flex-shrink: 0;
}

.fp-chat-error .fp-btn.small {
  background: #f59e0b;
  color: white;
  border: none;
  padding: 3px 10px;
  border-radius: var(--ct-radius-md);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
</style>
