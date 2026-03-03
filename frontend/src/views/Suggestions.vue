<template>
  <section class="suggs">
    <header class="page-title">
      <h1>AI 建议</h1>
    </header>

    <!-- 实时监听控制区 (全宽) -->
    <div class="card realtime-monitor">
      <div class="card-hd collapsible" @click="toggleMonitorPanel">
        <span>实时监听控制</span>
        <span class="icon">{{ monitorPanelExpanded ? '▼' : '▶' }}</span>
      </div>
      
      <div v-show="monitorPanelExpanded" class="card-bd">
        <!-- 重要提示 -->
        <div class="alert warning">
          <div class="alert-title">⚠️ 重要提示</div>
          <ul class="alert-list">
            <li>确保微信 4.0.5 已启动并登录</li>
            <li><strong>微信窗口的搜索栏必须在屏幕上显示</strong>（wxauto 限制）</li>
            <li><strong>只能监听主窗口聊天（单击联系人），不能监听独立弹窗（双击联系人）</strong></li>
            <li>输入的昵称必须与微信中显示的完全一致（备注名优先）</li>
            <li>同时只能监听一个对象</li>
          </ul>
        </div>

        <!-- 监听控制 -->
        <div class="monitor-control">
          <div class="input-group contact-picker">
            <label>监听对象:</label>
            <div class="picker-wrapper">
              <input 
                v-model="contactSearch" 
                type="text" 
                placeholder="搜索联系人..."
                :disabled="realtimeState.isMonitoring"
                @focus="showContactDropdown = true"
                @input="onContactSearchInput"
                @keydown.down.prevent="highlightNext"
                @keydown.up.prevent="highlightPrev"
                @keydown.enter.prevent="selectHighlighted"
                @keydown.escape="showContactDropdown = false"
                autocomplete="off"
              />
              <div v-if="showContactDropdown && !realtimeState.isMonitoring" class="contact-dropdown">
                <div v-if="contactsLoading" class="dropdown-empty">加载中...</div>
                <div v-else-if="!filteredContacts.length" class="dropdown-empty">无匹配联系人</div>
                <div v-else class="dropdown-list">
                  <div 
                    v-for="(c, idx) in filteredContacts" 
                    :key="c.id"
                    class="dropdown-item"
                    :class="{ highlighted: idx === highlightedIndex }"
                    @mousedown.prevent="selectContact(c)"
                    @mouseenter="highlightedIndex = idx"
                  >
                    <span class="contact-name">{{ c.name }}</span>
                    <span class="contact-count">{{ c.message_count }} 条消息</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          
          <div class="button-group">
            <button 
              class="ct-btn" 
              :class="{ primary: !realtimeState.isMonitoring, danger: realtimeState.isMonitoring }"
              :disabled="realtimeState.status === 'searching' || realtimeState.status === 'stopping'"
              @click="toggleMonitoring"
            >
              <span v-if="!realtimeState.isMonitoring">开始监听</span>
              <span v-else-if="realtimeState.status === 'stopping'">停止中...</span>
              <span v-else>停止监听</span>
            </button>
          </div>
        </div>

        <!-- 监听状态 -->
        <div class="monitor-status">
          <div class="status-indicator">
            <span 
              class="dot" 
              :class="{
                idle: !realtimeState.isMonitoring,
                active: realtimeState.isMonitoring
              }"
            ></span>
            <span class="status-text">
              {{ realtimeState.isMonitoring ? '监听中' : '未监听' }}
              <span v-if="realtimeState.talkerName && realtimeState.isMonitoring">
                - {{ realtimeState.talkerName }}
              </span>
            </span>
          </div>

          <!-- 进度步骤 -->
          <div class="progress-steps">
            <div 
              v-for="(step, idx) in progressSteps" 
              :key="idx" 
              class="step"
              :class="step.status"
            >
              <span class="step-icon">
                <template v-if="step.status === 'completed'">✓</template>
                <template v-else-if="step.status === 'active'">●</template>
                <template v-else>○</template>
              </span>
              <span class="step-label">{{ step.label }}</span>
            </div>
          </div>
        </div>

        <!-- 错误提示 -->
        <div v-if="realtimeError" class="error">{{ realtimeError }}</div>
      </div>
    </div>

    <!-- ====== 左右分栏布局 ====== -->
    <div v-if="realtimeState.isMonitoring" class="split-layout">

      <!-- 📱 左侧：实时消息流 -->
      <div class="pane pane-left">
        <div class="card pane-card">
          <div class="card-hd">
            <span>📱 实时消息 ({{ realtimeState.messages.length }}条)</span>
          </div>
          <div class="card-bd messages-scroll" ref="messagesScrollRef">
            <div v-if="!realtimeState.messages.length" class="empty">
              等待消息中...
            </div>
            <div v-else class="messages-list">
              <div 
                v-for="msg in realtimeState.messages" 
                :key="msg.id" 
                class="message-item"
                :class="msg.sender"
              >
                <div class="message-header">
                  <span class="sender-badge" :class="msg.sender">
                    {{ msg.sender === 'self' ? '我' : msg.sender === 'friend' ? '对方' : '系统' }}
                  </span>
                  <span class="timestamp">{{ formatTime(msg.timestamp) }}</span>
                </div>
                <div class="message-content">{{ msg.content }}</div>
                <div v-if="msg.sentiment" class="sentiment-result">
                  <span class="sentiment-badge" :class="getSentimentClass(msg.sentiment.polarity)">
                    {{ getSentimentText(msg.sentiment.polarity) }}
                  </span>
                  <span class="sentiment-intensity">
                    强度: {{ msg.sentiment.intensity.toFixed(2) }}
                  </span>
                  <span class="sentiment-confidence">
                    置信度: {{ (msg.sentiment.confidence * 100).toFixed(0) }}%
                  </span>
                  <span v-if="msg.sentiment.rules && msg.sentiment.rules.length" class="sentiment-rules">
                    规则: {{ msg.sentiment.rules.join(', ') }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 💡 右侧：AI 建议面板 -->
      <div class="pane pane-right">
        <!-- 情绪态势指示 -->
        <div class="card emotion-pulse-card">
          <div class="card-hd">💡 情绪态势</div>
          <div class="card-bd">
            <div v-if="emotionSummary" class="emotion-pulse">
              <div class="pulse-trend" :class="emotionSummary.trend">
                <span class="trend-icon">
                  {{ emotionSummary.trend === 'positive' ? '😊' : emotionSummary.trend === 'negative' ? '😟' : '😐' }}
                </span>
                <span class="trend-label">
                  {{ emotionSummary.trend === 'positive' ? '正面' : emotionSummary.trend === 'negative' ? '负面' : '中性' }}
                </span>
              </div>
              <div class="pulse-stats">
                <div class="stat">
                  <span class="stat-label">窗口消息</span>
                  <span class="stat-value">{{ emotionSummary.window_size }}</span>
                </div>
                <div class="stat">
                  <span class="stat-label">平均极性</span>
                  <span class="stat-value" :class="emotionSummary.avg_polarity > 0 ? 'positive' : emotionSummary.avg_polarity < 0 ? 'negative' : ''">
                    {{ emotionSummary.avg_polarity.toFixed(2) }}
                  </span>
                </div>
              </div>
              <div class="polarity-bar">
                <div v-for="(p, idx) in emotionSummary.recent_polarities" :key="idx"
                     class="polarity-dot" :class="p > 0 ? 'pos' : p < 0 ? 'neg' : 'neu'">
                </div>
              </div>
            </div>
            <div v-else class="empty">监听开始后将显示情绪态势</div>
          </div>
        </div>

        <!-- 设置：触发模式 + 走向 -->
        <div class="card config-card">
          <div class="card-hd">⚙️ 建议设置</div>
          <div class="card-bd">
            <div class="config-row">
              <label>触发模式</label>
              <div class="seg-control">
                <button :class="{ active: triggerMode === 'full_auto' }" @click="setTriggerMode('full_auto')">全自动</button>
                <button :class="{ active: triggerMode === 'semi_auto' }" @click="setTriggerMode('semi_auto')">半自动</button>
                <button :class="{ active: triggerMode === 'manual' }" @click="setTriggerMode('manual')">手动</button>
              </div>
            </div>
            <div class="config-row">
              <label>发展走向</label>
              <div class="seg-control">
                <button :class="{ active: intent === 'intimate' }" @click="setIntent('intimate')">🔥 亲密</button>
                <button :class="{ active: intent === 'maintain' }" @click="setIntent('maintain')">⚖️ 维持</button>
                <button :class="{ active: intent === 'distance' }" @click="setIntent('distance')">❄️ 疏远</button>
              </div>
            </div>
            <button class="ct-btn primary manual-btn" @click="manualGenerate" :disabled="loading">
              <span v-if="!loading">🎯 手动生成建议</span>
              <span v-else>生成中…</span>
            </button>
          </div>
        </div>

        <!-- 触发提示卡片列表 -->
        <div class="card suggestions-card">
          <div class="card-hd">
            <span>📋 建议列表</span>
            <span class="badge" v-if="pendingSuggestions.length">{{ pendingSuggestions.length }}</span>
          </div>
          <div class="card-bd">
            <div v-if="!pendingSuggestions.length && !manualSuggestion" class="empty">
              {{ triggerMode === 'manual' ? '点击上方「手动生成建议」获取分析' : '等待触发条件满足…' }}
            </div>

            <!-- 手动生成的建议 -->
            <div v-if="manualSuggestion" class="trigger-card" :class="manualSuggestion.severity">
              <div class="trigger-header" @click="manualSuggestionExpanded = !manualSuggestionExpanded">
                <span class="trigger-icon">🎯</span>
                <span class="trigger-summary">{{ manualSuggestion.summary }}</span>
                <span class="expand-icon">{{ manualSuggestionExpanded ? '▼' : '▶' }}</span>
              </div>
              <div v-show="manualSuggestionExpanded" class="trigger-body">
                <ul class="speech-list">
                  <li v-for="(sp, i) in manualSuggestion.speeches" :key="i">
                    <span class="speech-text">{{ sp }}</span>
                    <button class="copy-btn" @click="copyText(sp)">复制</button>
                  </li>
                </ul>
              </div>
            </div>

            <!-- 自动/半自动触发的建议 -->
            <div v-for="s in pendingSuggestions" :key="s.id" class="trigger-card" :class="s.severity">
              <div class="trigger-header" @click="toggleSuggestion(s.id)">
                <span class="trigger-icon">
                  {{ getTriggerIcon(s.trigger_type) }}
                </span>
                <span class="trigger-summary">{{ s.summary }}</span>
                <span class="trigger-time">{{ formatTime(s.created_at) }}</span>
                <span class="expand-icon">{{ expandedSuggestions.has(s.id) ? '▼' : '▶' }}</span>
              </div>
              <div v-show="expandedSuggestions.has(s.id)" class="trigger-body">
                <ul class="speech-list">
                  <li v-for="(sp, i) in s.speeches" :key="i">
                    <span class="speech-text">{{ sp }}</span>
                    <button class="copy-btn" @click="copyText(sp)">复制</button>
                  </li>
                </ul>
                <button class="dismiss-btn" @click="dismissSuggestion(s.id)">✕ 关闭</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ====== 未监听时的默认视图（保留原有功能） ====== -->
    <div v-if="!realtimeState.isMonitoring" class="grid">
      <div class="left">
        <!-- 发展走向选择卡 -->
        <div class="card">
          <div class="ct-card-hd">发展走向</div>
          <div class="card-bd intent-row">
            <div class="seg">
              <label>
                <input type="radio" value="intimate" v-model="intent" /> 亲密
              </label>
              <label>
                <input type="radio" value="maintain" v-model="intent" /> 维持
              </label>
              <label>
                <input type="radio" value="distance" v-model="intent" /> 疏远
              </label>
            </div>
            <button class="ct-btn" :disabled="loading" @click="gen">
              <span v-if="!loading">生成建议</span>
              <span v-else>生成中…</span>
            </button>
          </div>
          <p class="hint">将根据你的目标倾向，给出更贴合的沟通策略。</p>
          <p v-if="error" class="error">{{ error }}</p>
        </div>

        <!-- AI 建议与对话卡 -->
        <div class="ct-card chat">
          <div class="card-hd tools">
            <div class="title">建议与对话</div>
            <div class="actions">
              <CtButton variant="ghost" @click="onRefresh" :disabled="loading">刷新</CtButton>
              <CtButton variant="ghost" @click="onClear">清空</CtButton>
              <CtButton variant="ghost" @click="copyAll" :disabled="!suggestion">复制</CtButton>
            </div>
          </div>
          <div class="card-bd chat-body">
            <div v-if="!suggestion && !loading" class="empty">暂无建议，点击上方"生成建议"。</div>
            <div v-if="loading" class="skeleton">AI 正在思考…</div>
            <template v-if="suggestion">
              <div class="bubble ai">
                <div class="summary" v-if="suggestion.summary">{{ suggestion.summary }}</div>
                <ul class="speech" v-if="suggestion.speeches && suggestion.speeches.length">
                  <li v-for="(sp, i) in suggestion.speeches" :key="i">
                    <span>{{ sp }}</span>
                    <button class="mini" @click="copyText(sp)">复制</button>
                  </li>
                </ul>
              </div>
              <div v-for="(m, i) in messages" :key="i" :class="['bubble', m.role]">{{ m.content }}</div>
            </template>
          </div>
          <div class="chat-input">
            <input v-model="userInput" type="text" placeholder="补充你的背景/需求，回车发送" @keydown.enter.exact.prevent="send" />
            <button class="ct-btn" @click="send" :disabled="!userInput.trim() || loading">发送</button>
          </div>
        </div>
      </div>

      <div class="right">
        <!-- 对象信息卡 -->
        <div class="card">
          <div class="ct-card-hd">对象信息</div>
          <div class="card-bd profile">
            <div class="avatar" aria-hidden="true">{{ profileInitial }}</div>
            <div class="meta">
              <div class="name">{{ profile.name || '未命名对象' }}</div>
              <div class="tags" v-if="profile.tags && profile.tags.length">
                <span v-for="t in profile.tags" :key="t">{{ t }}</span>
              </div>
              <div class="stats">
                <div>近7天互动：{{ profile.stats?.interactions7d ?? '-' }}</div>
                <div>平均响应：{{ profile.stats?.avgLatency ?? '-' }}</div>
              </div>
            </div>
          </div>
          <div class="note" v-if="profile.note">{{ profile.note }}</div>
        </div>

        <!-- 情绪分析（饼图） -->
        <div class="card">
          <div class="ct-card-hd">情绪占比（近期）</div>
          <div class="card-bd">
            <div v-if="!emotions.length" class="empty">暂无数据，待导入或等待实时生成</div>
            <div v-else ref="pieRef" class="pie"></div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onBeforeUnmount, computed, reactive, nextTick } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import * as echarts from 'echarts'
import CtButton from '@/components/base/CtButton.vue'

type Message = { role: 'ai' | 'user'; content: string }

const intent = ref<'intimate' | 'maintain' | 'distance'>('maintain')
const loading = ref(false)
const error = ref('')
const suggestion = ref<{ summary?: string; speeches?: string[] } | null>(null)
const messages = ref<Message[]>([])
const userInput = ref('')

// ========== 实时监听状态 ==========
const monitorPanelExpanded = ref(true)

const realtimeState = reactive({
  isMonitoring: false,
  talkerName: '',
  batchId: '',
  messageCount: 0,
  status: 'idle' as 'idle' | 'searching' | 'loading_model' | 'monitoring' | 'stopping' | 'stopped',
  messages: [] as any[]
})

const realtimeError = ref('')
let statusTimer: any = null
let messagesTimer: any = null
let suggestionsTimer: any = null  // 建议轮询定时器

// ========== AI 建议状态 ==========
const triggerMode = ref<'full_auto' | 'semi_auto' | 'manual'>('semi_auto')
const pendingSuggestions = ref<any[]>([])
const expandedSuggestions = reactive(new Set<number>())
const manualSuggestion = ref<any>(null)
const manualSuggestionExpanded = ref(true)
const emotionSummary = ref<any>(null)
const messagesScrollRef = ref<HTMLElement | null>(null)

// ========== 联系人列表 ==========
const contactSearch = ref('')
const contacts = ref<any[]>([])
const contactsLoading = ref(false)
const showContactDropdown = ref(false)
const highlightedIndex = ref(-1)

const filteredContacts = computed(() => {
  const q = contactSearch.value.trim().toLowerCase()
  if (!q) return contacts.value
  return contacts.value.filter(c => 
    c.name?.toLowerCase().includes(q)
  )
})

async function loadContacts() {
  contactsLoading.value = true
  try {
    await bridgeReady()
    const r = await api.get_conversation_list()
    if (r.ok && r.conversations) {
      contacts.value = r.conversations
    }
  } catch (e) {
    console.error('加载联系人列表失败:', e)
  } finally {
    contactsLoading.value = false
  }
}

function onContactSearchInput() {
  showContactDropdown.value = true
  highlightedIndex.value = 0
}

function selectContact(c: any) {
  realtimeState.talkerName = c.name
  contactSearch.value = c.name
  showContactDropdown.value = false
  highlightedIndex.value = -1
}

function highlightNext() {
  if (!showContactDropdown.value) { showContactDropdown.value = true; return }
  if (highlightedIndex.value < filteredContacts.value.length - 1) highlightedIndex.value++
}

function highlightPrev() {
  if (highlightedIndex.value > 0) highlightedIndex.value--
}

function selectHighlighted() {
  const list = filteredContacts.value
  if (highlightedIndex.value >= 0 && highlightedIndex.value < list.length) {
    selectContact(list[highlightedIndex.value])
  } else if (contactSearch.value.trim()) {
    // 允许手动输入不在列表中的名称
    realtimeState.talkerName = contactSearch.value.trim()
    showContactDropdown.value = false
  }
}

// 点击外部关闭下拉
function onClickOutside(e: MouseEvent) {
  const el = (e.target as HTMLElement)?.closest('.contact-picker')
  if (!el) showContactDropdown.value = false
}

// 进度步骤计算
const progressSteps = computed(() => {
  return [
    {
      label: '正在搜索联系人...',
      status: realtimeState.status === 'searching' ? 'active' : 
              ['loading_model', 'monitoring', 'stopping', 'stopped'].includes(realtimeState.status) ? 'completed' : 'pending'
    },
    {
      label: '正在加载AI模型...',
      status: realtimeState.status === 'loading_model' ? 'active' : 
              ['monitoring', 'stopping', 'stopped'].includes(realtimeState.status) ? 'completed' : 'pending'
    },
    {
      label: `正在监听 (已抓取 ${realtimeState.messageCount} 条消息)`,
      status: realtimeState.status === 'monitoring' ? 'active' : 
              realtimeState.status === 'stopped' ? 'completed' : 'pending'
    },
    {
      label: '监听已结束',
      status: realtimeState.status === 'stopped' ? 'completed' : 'pending'
    }
  ]
})

// 切换面板展开
function toggleMonitorPanel() {
  monitorPanelExpanded.value = !monitorPanelExpanded.value
}

// 切换监听状态
async function toggleMonitoring() {
  if (realtimeState.isMonitoring) {
    await stopMonitoring()
  } else {
    await startMonitoring()
  }
}

// 启动监听
async function startMonitoring() {
  const talkerName = realtimeState.talkerName.trim()
  
  if (!talkerName) {
    realtimeError.value = '请选择或输入监听对象'
    return
  }
  
  realtimeError.value = ''
  realtimeState.status = 'searching'
  
  try {
    await bridgeReady()
    const result = await api.start_realtime_monitor(talkerName)
    
    if (result.success || result.ok) {
      realtimeState.batchId = result.batch_id
      realtimeState.status = 'loading_model'
      realtimeState.isMonitoring = true
      
      startStatusPolling()
      startMessagesPolling()  // 新增:开始消息轮询
    } else {
      realtimeState.status = 'idle'
      realtimeError.value = result.error || result.message || '启动监听失败'
    }
  } catch (e: any) {
    realtimeState.status = 'idle'
    realtimeError.value = e?.message || '启动监听异常'
  }
}

// 停止监听
async function stopMonitoring() {
  realtimeState.status = 'stopping'
  realtimeError.value = ''
  
  try {
    await bridgeReady()
    const result = await api.stop_realtime_monitor()
    
    stopStatusPolling()
    stopMessagesPolling()
    stopSuggestionsPolling()
    
    if (result.success || result.ok) {
      realtimeState.status = 'stopped'
      realtimeState.isMonitoring = false
      
      setTimeout(() => {
        if (realtimeState.status === 'stopped') {
          realtimeState.status = 'idle'
          realtimeState.messageCount = 0
          realtimeState.messages = []
          pendingSuggestions.value = []
          emotionSummary.value = null
          manualSuggestion.value = null
        }
      }, 3000)
    } else {
      realtimeState.status = 'monitoring'
      realtimeError.value = result.error || result.message || '停止监听失败'
    }
  } catch (e: any) {
    realtimeState.status = 'monitoring'
    realtimeError.value = e?.message || '停止监听异常'
  }
}

// ========== 建议配置 ==========

async function loadSuggestionConfig() {
  try {
    const r = await api.get_suggestion_config()
    if (r.ok && r.config) {
      triggerMode.value = r.config.trigger_mode || 'semi_auto'
      intent.value = r.config.intent || 'maintain'
    }
  } catch (e) {
    console.error('加载建议配置失败:', e)
  }
}

async function setTriggerMode(mode: string) {
  triggerMode.value = mode as any
  try {
    await api.set_suggestion_config({ trigger_mode: mode })
  } catch (e) {
    console.error('设置触发模式失败:', e)
  }
}

async function setIntent(newIntent: string) {
  intent.value = newIntent as any
  try {
    await api.set_suggestion_config({ intent: newIntent })
  } catch (e) {
    console.error('设置走向失败:', e)
  }
}

// 手动生成建议
async function manualGenerate() {
  loading.value = true
  try {
    await bridgeReady()
    const r = await api.generate_suggestion(intent.value, {})
    if (r.ok && r.suggestion) {
      manualSuggestion.value = r.suggestion
      manualSuggestionExpanded.value = true
    }
  } catch (e: any) {
    console.error('手动生成失败:', e)
  } finally {
    loading.value = false
  }
}

// 展开/折叠建议卡片
function toggleSuggestion(id: number) {
  if (expandedSuggestions.has(id)) {
    expandedSuggestions.delete(id)
  } else {
    expandedSuggestions.add(id)
  }
}

// 关闭建议
async function dismissSuggestion(id: number) {
  try {
    await api.dismiss_suggestion(id)
    pendingSuggestions.value = pendingSuggestions.value.filter(s => s.id !== id)
    expandedSuggestions.delete(id)
  } catch (e) {
    console.error('关闭建议失败:', e)
  }
}

// ========== 轮询 ==========

function startStatusPolling() {
  stopStatusPolling()
  statusTimer = setInterval(async () => {
    try {
      await bridgeReady()
      const status = await api.get_realtime_status()
      if (status.ok) {
        realtimeState.isMonitoring = status.is_monitoring
        realtimeState.messageCount = status.message_count || 0
        
        // 根据后端模型就绪状态更新前端状态
        if (realtimeState.status === 'loading_model' && status.model_ready) {
          realtimeState.status = 'monitoring'
        }
        
        // 如果后端状态变为未监听，同步前端
        if (!status.is_monitoring && realtimeState.status === 'monitoring') {
          stopStatusPolling()
          realtimeState.status = 'idle'
        }
      }
    } catch (e) {
      console.error('状态轮询失败:', e)
    }
  }, 2000)
}

function stopStatusPolling() {
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null }
}

function startMessagesPolling() {
  stopMessagesPolling()
  messagesTimer = setInterval(async () => {
    if (!realtimeState.batchId) return
    try {
      await bridgeReady()
      const result = await api.get_realtime_messages(realtimeState.batchId, 50)
      if (result.ok) {
        const prevLen = realtimeState.messages.length
        realtimeState.messages = result.messages || []
        // 新消息时自动滚动到底部
        if (realtimeState.messages.length > prevLen && messagesScrollRef.value) {
          nextTick(() => {
            messagesScrollRef.value!.scrollTop = messagesScrollRef.value!.scrollHeight
          })
        }
      }
    } catch (e) {
      console.error('消息轮询失败:', e)
    }
  }, 3000)
}

function stopMessagesPolling() {
  if (messagesTimer) { clearInterval(messagesTimer); messagesTimer = null }
}

// 建议轮询（每 3 秒）
function startSuggestionsPolling() {
  stopSuggestionsPolling()
  suggestionsTimer = setInterval(async () => {
    if (!realtimeState.batchId) return
    try {
      await bridgeReady()
      const result = await api.get_pending_suggestions(realtimeState.batchId)
      if (result.ok) {
        pendingSuggestions.value = result.suggestions || []
        emotionSummary.value = result.emotion_summary || null
      }
    } catch (e) {
      console.error('建议轮询失败:', e)
    }
  }, 3000)
}

function stopSuggestionsPolling() {
  if (suggestionsTimer) { clearInterval(suggestionsTimer); suggestionsTimer = null }
}

// ========== 原有逻辑 ==========

const profile = ref<{ name?: string; tags?: string[]; stats?: any; note?: string }>({
  name: '对方昵称',
  tags: ['朋友'],
  stats: { interactions7d: 12, avgLatency: '15m' },
  note: '最近工作压力大，回复不稳定。'
})
const profileInitial = computed(() => (profile.value.name ? profile.value.name[0] : 'N'))

const emotions = ref<{ name: string; value: number }[]>([
  { name: '积极', value: 40 },
  { name: '中性', value: 35 },
  { name: '消极', value: 25 }
])

async function gen() {
  loading.value = true
  error.value = ''
  try {
    await bridgeReady()
    const r = await api.generate_suggestion(intent.value, { recent: [] })
    if (r.ok && r.suggestion) {
      suggestion.value = r.suggestion
    } else {
      suggestion.value = r || null
    }
  } catch (e: any) {
    error.value = e?.message || '生成失败，请重试'
  } finally {
    loading.value = false
  }
}

function onRefresh() { if (!loading.value) gen() }
function onClear() { suggestion.value = null; messages.value = []; userInput.value = '' }
function copyText(text: string) { navigator.clipboard?.writeText(text) }
function copyAll() {
  if (!suggestion.value) return
  const txt = [suggestion.value.summary || '', ...(suggestion.value.speeches || [])].filter(Boolean).join('\n')
  navigator.clipboard?.writeText(txt)
}

async function send() {
  const content = userInput.value.trim()
  if (!content) return
  messages.value.push({ role: 'user', content })
  userInput.value = ''
  loading.value = true
  error.value = ''
  try {
    await bridgeReady()
    const r = await api.generate_suggestion(intent.value, { recent: messages.value })
    if (r.ok && r.suggestion) {
      suggestion.value = r.suggestion
      messages.value.push({ role: 'ai', content: r.suggestion.summary || '已更新建议。' })
    } else {
      suggestion.value = r || null
      messages.value.push({ role: 'ai', content: r?.summary || '已更新建议，请查看上方内容。' })
    }
  } catch (e: any) {
    error.value = e?.message || '发送失败，请重试'
  } finally {
    loading.value = false
  }
}

// 组件挂载时恢复监听状态
onMounted(async () => {
  // 加载联系人列表
  loadContacts()
  // 点击外部关闭下拉
  document.addEventListener('click', onClickOutside)

  try {
    await bridgeReady()
    const status = await api.get_realtime_status()
    
    if (status.ok && status.is_monitoring) {
      realtimeState.isMonitoring = true
      realtimeState.status = 'monitoring'
      realtimeState.talkerName = status.talker_display_name || ''
      realtimeState.batchId = status.batch_id || ''
      realtimeState.messageCount = status.message_count || 0
      startStatusPolling()
      startMessagesPolling()
      startSuggestionsPolling()
      loadSuggestionConfig()
    }
  } catch (e) {
    console.error('恢复监听状态失败:', e)
  }
})

// 组件卸载时清理
onBeforeUnmount(() => {
  stopStatusPolling()
  stopMessagesPolling()
  stopSuggestionsPolling()
  document.removeEventListener('click', onClickOutside)
})

// ========== 辅助函数 ==========

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  if (diff < 60000) {
    return '刚刚'
  } else if (diff < 3600000) {
    return `${Math.floor(diff / 60000)}分钟前`
  } else if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } else {
    return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }
}

function getSentimentClass(polarity: number): string {
  if (polarity > 0) return 'positive'
  if (polarity < 0) return 'negative'
  return 'neutral'
}

function getSentimentText(polarity: number): string {
  if (polarity > 0) return '正面'
  if (polarity < 0) return '负面'
  return '中性'
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
</script>

<style scoped>
.suggs { display: flex; flex-direction: column; gap: var(--ct-space-lg); }
.page-title h1 { margin: 0 0 var(--ct-space-sm); color: var(--ct-color-primary); }

/* ====== 左右分栏布局 ====== */
.split-layout {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: var(--ct-space-lg);
  min-height: 500px;
}

.pane-left, .pane-right { display: flex; flex-direction: column; gap: var(--ct-space-lg); }

.pane-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.messages-scroll {
  flex: 1;
  max-height: 600px;
  overflow-y: auto;
  padding: var(--ct-space-sm);
}

/* 情绪态势指示 */
.emotion-pulse {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.pulse-trend {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  font-size: var(--ct-text-lg);
  font-weight: var(--ct-font-semibold);
}

.pulse-trend.positive { color: #4caf50; }
.pulse-trend.negative { color: var(--ct-color-error); }
.pulse-trend.neutral { color: var(--ct-text-secondary); }

.trend-icon { font-size: 1.5em; }

.pulse-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ct-space-sm);
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--ct-space-sm);
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-md);
}

.stat-label { font-size: var(--ct-text-xs); color: var(--ct-text-secondary); }
.stat-value { font-weight: var(--ct-font-semibold); font-size: var(--ct-text-sm); }
.stat-value.positive { color: #4caf50; }
.stat-value.negative { color: var(--ct-color-error); }

.polarity-bar {
  display: flex;
  gap: 4px;
  padding: var(--ct-space-xs) 0;
}

.polarity-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  transition: all var(--ct-transition-fast);
}

.polarity-dot.pos { background: #4caf50; }
.polarity-dot.neg { background: var(--ct-color-error); }
.polarity-dot.neu { background: var(--ct-text-tertiary); }

/* 建议设置 */
.config-card .card-bd {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.config-row {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xs);
}

.config-row label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  font-weight: var(--ct-font-medium);
}

.seg-control {
  display: flex;
  gap: 0;
  border-radius: var(--ct-radius-md);
  overflow: hidden;
  border: 1px solid var(--ct-border-color);
}

.seg-control button {
  flex: 1;
  padding: var(--ct-space-xs) var(--ct-space-sm);
  border: none;
  background: var(--ct-bg-elevated);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}

.seg-control button:not(:last-child) {
  border-right: 1px solid var(--ct-border-color);
}

.seg-control button.active {
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse);
  font-weight: var(--ct-font-semibold);
}

.seg-control button:hover:not(.active) {
  background: var(--ct-bg-tertiary);
}

.manual-btn {
  width: 100%;
  margin-top: var(--ct-space-xs);
}

/* 触发卡片 */
.suggestions-card .badge {
  background: var(--ct-color-error);
  color: white;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: var(--ct-text-xs);
  margin-left: var(--ct-space-sm);
}

.trigger-card {
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  margin-bottom: var(--ct-space-sm);
  overflow: hidden;
  transition: all var(--ct-transition-fast);
}

.trigger-card.high { border-left: 3px solid var(--ct-color-error); }
.trigger-card.medium { border-left: 3px solid var(--ct-color-warning); }
.trigger-card.low { border-left: 3px solid #4caf50; }

.trigger-header {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-sm) var(--ct-space-md);
  cursor: pointer;
  transition: background var(--ct-transition-fast);
}

.trigger-header:hover {
  background: var(--ct-bg-tertiary);
}

.trigger-icon { font-size: 1.1em; flex-shrink: 0; }
.trigger-summary { flex: 1; font-size: var(--ct-text-sm); font-weight: var(--ct-font-medium); }
.trigger-time { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); flex-shrink: 0; }
.expand-icon { color: var(--ct-text-tertiary); font-size: var(--ct-text-xs); flex-shrink: 0; }

.trigger-body {
  padding: var(--ct-space-sm) var(--ct-space-md) var(--ct-space-md);
  border-top: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
}

.speech-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.speech-list li {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-sm);
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-sm);
}

.speech-text {
  flex: 1;
  font-size: var(--ct-text-sm);
  line-height: var(--ct-leading-relaxed);
}

.copy-btn {
  border: none;
  background: transparent;
  color: var(--ct-color-primary);
  cursor: pointer;
  font-size: var(--ct-text-xs);
  white-space: nowrap;
  flex-shrink: 0;
}

.dismiss-btn {
  border: none;
  background: transparent;
  color: var(--ct-text-tertiary);
  cursor: pointer;
  font-size: var(--ct-text-xs);
  margin-top: var(--ct-space-sm);
  padding: var(--ct-space-xs) var(--ct-space-sm);
}

.dismiss-btn:hover { color: var(--ct-color-error); }

/* ====== 原有布局样式 ====== */
.grid { display: grid; grid-template-columns: 1fr 360px; gap: var(--ct-space-lg); }
.left, .right { display: flex; flex-direction: column; gap: var(--ct-space-lg); }

.card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-sm);
  padding: var(--ct-space-lg);
  transition: transform var(--ct-transition-normal) var(--ct-ease-out),
              box-shadow var(--ct-transition-normal) var(--ct-ease-out),
              border-color var(--ct-transition-normal) var(--ct-ease-out);
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: var(--ct-shadow-md);
  border-color: var(--ct-border-color-hover);
}

.card-hd { padding: var(--ct-space-md) var(--ct-space-lg); font-weight: var(--ct-font-semibold); color: var(--ct-color-primary); border-bottom: 1px solid var(--ct-border-color); display: flex; align-items: center; }
.card-bd { padding: var(--ct-space-lg); }
.hint { color: var(--ct-text-secondary); font-size: var(--ct-text-xs); padding: 0 var(--ct-space-lg) var(--ct-space-md); margin: 0; }
.error { color: var(--ct-color-error); background: var(--ct-color-error-light); margin: var(--ct-space-sm) 0 0; padding: var(--ct-space-sm) var(--ct-space-md); border-radius: var(--ct-radius-md); font-size: var(--ct-text-sm); }

.intent-row { display: flex; align-items: center; justify-content: space-between; gap: var(--ct-space-md); }
.seg { display: flex; gap: var(--ct-space-md); background: var(--ct-color-primary-light); padding: var(--ct-space-sm) var(--ct-space-md); border-radius: var(--ct-radius-lg); }
.seg label { display: flex; align-items: center; gap: var(--ct-space-sm); }

.mini { border: none; background: transparent; color: var(--ct-color-primary); cursor: pointer; }

.chat .tools { display: flex; align-items: center; justify-content: space-between; }
.chat-body { display: flex; flex-direction: column; gap: 10px; min-height: 140px; }
.bubble { max-width: 100%; padding: 10px var(--ct-space-md); border-radius: var(--ct-radius-lg); }
.bubble.ai { background: var(--ct-bg-secondary); align-self: flex-start; }
.bubble.user { background: var(--ct-color-accent); color: var(--ct-text-primary); align-self: flex-end; }
.summary { font-weight: var(--ct-font-semibold); margin-bottom: var(--ct-space-sm); }
.speech { display: flex; flex-direction: column; gap: var(--ct-space-sm); padding-left: var(--ct-space-lg); }
.speech li { display: flex; align-items: center; justify-content: space-between; gap: var(--ct-space-sm); }
.skeleton { color: var(--ct-text-tertiary); }
.empty { color: var(--ct-text-tertiary); }
.chat-input { display: flex; gap: var(--ct-space-sm); padding: var(--ct-space-md) var(--ct-space-lg); border-top: 1px solid var(--ct-border-color); }

.profile { display: flex; gap: var(--ct-space-md); align-items: center; }
.avatar { width: 40px; height: 40px; border-radius: 50%; background: var(--ct-color-accent); display: flex; align-items: center; justify-content: center; color: var(--ct-text-primary); font-weight: var(--ct-font-bold); }
.meta .name { font-weight: var(--ct-font-semibold); margin-bottom: var(--ct-space-xs); }
.tags { display: flex; gap: var(--ct-space-sm); flex-wrap: wrap; margin: var(--ct-space-xs) 0; }
.tags span { background: var(--ct-color-primary-light); color: var(--ct-color-primary); padding: var(--ct-space-xs) var(--ct-space-sm); border-radius: var(--ct-radius-sm); font-size: var(--ct-text-xs); }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: var(--ct-space-sm); font-size: var(--ct-text-xs); color: var(--ct-text-secondary); }
.note { padding: 0 var(--ct-space-lg) var(--ct-space-lg); color: var(--ct-text-secondary); font-size: var(--ct-text-sm); }

.pie { width: 100%; height: 260px; }

/* ========== 实时监听样式 ========== */
.realtime-monitor { margin-bottom: var(--ct-space-lg); }

.collapsible {
  cursor: pointer; user-select: none;
  display: flex; justify-content: space-between; align-items: center;
  transition: background var(--ct-transition-fast);
}
.collapsible:hover { background: var(--ct-bg-tertiary); }
.icon { color: var(--ct-text-tertiary); font-size: var(--ct-text-xs); transition: transform var(--ct-transition-fast); }

.alert { padding: var(--ct-space-md); border-radius: var(--ct-radius-md); margin-bottom: var(--ct-space-lg); }
.alert.warning { background: var(--ct-color-warning-light); border-left: 3px solid var(--ct-color-warning); }
.alert-title { font-weight: var(--ct-font-semibold); color: var(--ct-color-warning); margin-bottom: var(--ct-space-sm); font-size: var(--ct-text-sm); }
.alert-list { margin: 0; padding-left: 20px; color: var(--ct-color-warning); }
.alert-list li { margin: var(--ct-space-xs) 0; font-size: var(--ct-text-sm); line-height: var(--ct-leading-normal); }
.alert-list strong { color: var(--ct-color-error); font-weight: var(--ct-font-semibold); }

.monitor-control { display: flex; gap: var(--ct-space-md); align-items: flex-end; margin-bottom: var(--ct-space-lg); }
.input-group { flex: 1; display: flex; flex-direction: column; gap: var(--ct-space-sm); }
.input-group label { font-size: var(--ct-text-sm); color: var(--ct-text-secondary); font-weight: var(--ct-font-medium); }
.input-group input {
  padding: var(--ct-space-sm) var(--ct-space-md); border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md); font-size: var(--ct-text-sm);
  transition: border-color var(--ct-transition-fast); background: var(--ct-bg-elevated); color: var(--ct-text-primary);
}
.input-group input:focus { outline: none; border-color: var(--ct-color-primary); box-shadow: 0 0 0 3px var(--ct-color-primary-light); }
.input-group input:disabled { background: var(--ct-bg-tertiary); cursor: not-allowed; color: var(--ct-text-tertiary); }
.button-group { display: flex; gap: var(--ct-space-sm); }

.ct-btn.primary { background: var(--ct-color-primary); color: var(--ct-text-inverse); }
.ct-btn.primary:hover:not(:disabled) { background: var(--ct-color-primary-hover); }
.ct-btn.danger { background: var(--ct-color-error); color: var(--ct-text-inverse); }
.ct-btn.danger:hover:not(:disabled) { background: var(--ct-color-error-hover, #c9302c); }
.ct-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.monitor-status { display: flex; flex-direction: column; gap: var(--ct-space-md); }
.status-indicator { display: flex; align-items: center; gap: var(--ct-space-sm); padding: var(--ct-space-sm) 0; }
.dot { width: 10px; height: 10px; border-radius: 50%; transition: background var(--ct-transition-normal); }
.dot.idle { background: var(--ct-text-tertiary); }
.dot.active { background: var(--ct-color-success); animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.status-text { font-size: var(--ct-text-sm); color: var(--ct-text-primary); font-weight: var(--ct-font-medium); }

.progress-steps { display: flex; flex-direction: column; gap: var(--ct-space-sm); padding-left: 20px; }
.step { display: flex; align-items: center; gap: var(--ct-space-sm); font-size: var(--ct-text-sm); color: var(--ct-text-secondary); transition: color var(--ct-transition-normal); }
.step.active { color: var(--ct-color-primary); font-weight: var(--ct-font-medium); }
.step.completed { color: var(--ct-color-success); }
.step.pending { color: var(--ct-border-color-hover); }
.step-icon { width: 20px; text-align: center; font-weight: var(--ct-font-bold); }
.step-label { flex: 1; }

/* 消息列表 */
.messages-list { display: flex; flex-direction: column; gap: var(--ct-space-md); }
.message-item { padding: var(--ct-space-md); border-radius: var(--ct-radius-md); border: 1px solid var(--ct-border-color); background: var(--ct-bg-elevated); transition: all var(--ct-transition-fast); }
.message-item:hover { border-color: var(--ct-color-primary); box-shadow: var(--ct-shadow-sm); }
.message-item.system { opacity: 0.7; background: var(--ct-bg-tertiary); }
.message-header { display: flex; align-items: center; gap: var(--ct-space-sm); margin-bottom: var(--ct-space-sm); font-size: var(--ct-text-xs); }
.sender-badge { padding: 2px 8px; border-radius: var(--ct-radius-sm); font-weight: var(--ct-font-medium); font-size: var(--ct-text-xs); }
.sender-badge.self { background: var(--ct-color-primary-light); color: var(--ct-color-primary); }
.sender-badge.friend { background: #e3f2fd; color: #2196f3; }
.sender-badge.system { background: var(--ct-bg-tertiary); color: var(--ct-text-tertiary); }
.timestamp { color: var(--ct-text-tertiary); font-size: var(--ct-text-xs); }
.message-content { padding: var(--ct-space-sm) 0; color: var(--ct-text-primary); line-height: var(--ct-leading-relaxed); word-break: break-word; }
.sentiment-result { display: flex; flex-wrap: wrap; gap: var(--ct-space-sm); margin-top: var(--ct-space-sm); padding-top: var(--ct-space-sm); border-top: 1px dashed var(--ct-border-color); font-size: var(--ct-text-xs); }
.sentiment-badge { padding: 2px 8px; border-radius: var(--ct-radius-sm); font-weight: var(--ct-font-semibold); }
.sentiment-badge.positive { background: #e8f5e9; color: #4caf50; }
.sentiment-badge.negative { background: var(--ct-color-error-light); color: var(--ct-color-error); }
.sentiment-badge.neutral { background: var(--ct-bg-tertiary); color: var(--ct-text-secondary); }
.sentiment-intensity, .sentiment-confidence, .sentiment-rules { color: var(--ct-text-secondary); }
.sentiment-rules { font-style: italic; }

/* 联系人搜索下拉 */
.contact-picker { position: relative; }
.picker-wrapper { position: relative; width: 100%; }
.picker-wrapper input { width: 100%; box-sizing: border-box; }

.contact-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 100;
  max-height: 240px;
  overflow-y: auto;
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-top: none;
  border-radius: 0 0 var(--ct-radius-md) var(--ct-radius-md);
  box-shadow: var(--ct-shadow-md);
}

.dropdown-empty {
  padding: var(--ct-space-md);
  text-align: center;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
}

.dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ct-space-sm) var(--ct-space-md);
  cursor: pointer;
  transition: background var(--ct-transition-fast);
}

.dropdown-item:hover,
.dropdown-item.highlighted {
  background: var(--ct-color-primary-light);
}

.contact-name {
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-medium);
  color: var(--ct-text-primary);
}

.contact-count {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  flex-shrink: 0;
}

/* 响应式 */
@media (max-width: 1000px) {
  .split-layout { grid-template-columns: 1fr; }
  .grid { grid-template-columns: 1fr; }
  .monitor-control { flex-direction: column; align-items: stretch; }
}
</style>
