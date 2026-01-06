<template>
  <section class="suggs">
    <header class="page-title">
      <h1>AI 建议</h1>
    </header>

    <!-- 实时监听控制区 -->
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
          <div class="input-group">
            <label>监听对象:</label>
            <input 
              v-model="realtimeState.talkerName" 
              type="text" 
              placeholder="输入联系人昵称或备注名"
              :disabled="realtimeState.isMonitoring"
            />
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

    <div class="grid">
      <div class="left">
        <!-- 1) 发展走向选择卡 -->
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

        <!-- 2) AI 建议与对话卡 -->
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
            <div v-if="!suggestion && !loading" class="empty">暂无建议，点击上方“生成建议”。</div>
            <div v-if="loading" class="skeleton">AI 正在思考…</div>
            <template v-if="suggestion">
              <div class="bubble ai">
                <div class="summary" v-if="suggestion.summary">{{ suggestion.summary }}</div>
                <ul class="speech" v-if="suggestion.speech && suggestion.speech.length">
                  <li v-for="(sp, i) in suggestion.speech" :key="i">
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
        <!-- 3) 对象信息卡 -->
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

        <!-- 4) 情绪分析（饼图） -->
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
import { ref, onMounted, watch, onBeforeUnmount, computed, reactive } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import * as echarts from 'echarts'
import CtButton from '@/components/base/CtButton.vue'

type Message = { role: 'ai' | 'user'; content: string }

const intent = ref<'intimate' | 'maintain' | 'distance'>('maintain')
const loading = ref(false)
const error = ref('')
const suggestion = ref<{ summary?: string; speech?: string[] } | null>(null)
const messages = ref<Message[]>([])
const userInput = ref('')

// ========== 实时监听状态 ==========
const monitorPanelExpanded = ref(true)

const realtimeState = reactive({
  isMonitoring: false,
  talkerName: '',
  batchId: '',
  messageCount: 0,
  status: 'idle' as 'idle' | 'searching' | 'monitoring' | 'stopping' | 'stopped'
})

const realtimeError = ref('')
let statusTimer: any = null

// 进度步骤计算
const progressSteps = computed(() => {
  return [
    {
      label: '正在搜索联系人...',
      status: realtimeState.status === 'searching' ? 'active' : 
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
    realtimeError.value = '请输入监听对象昵称'
    return
  }
  
  realtimeError.value = ''
  realtimeState.status = 'searching'
  
  try {
    await bridgeReady()
    const result = await api.start_realtime_monitor(talkerName)
    
    if (result.success || result.ok) {
      realtimeState.batchId = result.batch_id
      realtimeState.status = 'monitoring'
      realtimeState.isMonitoring = true
      startStatusPolling()
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
    
    if (result.success || result.ok) {
      realtimeState.status = 'stopped'
      realtimeState.isMonitoring = false
      
      // 3秒后重置状态
      setTimeout(() => {
        if (realtimeState.status === 'stopped') {
          realtimeState.status = 'idle'
          realtimeState.messageCount = 0
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

// 开始状态轮询（每 2 秒）
function startStatusPolling() {
  stopStatusPolling()
  
  statusTimer = setInterval(async () => {
    try {
      await bridgeReady()
      const status = await api.get_realtime_status()
      
      if (status.ok) {
        realtimeState.isMonitoring = status.is_monitoring
        realtimeState.messageCount = status.message_count || 0
        
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

// 停止状态轮询
function stopStatusPolling() {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
}

// ========== 原有逻辑 ==========

// 临时占位：对象信息与情绪数据（后端接好前可替换）
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
    suggestion.value = r || null
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
  const txt = [suggestion.value.summary || '', ...(suggestion.value.speech || [])].filter(Boolean).join('\n')
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
    suggestion.value = r || null
    messages.value.push({ role: 'ai', content: r?.summary || '已更新建议，请查看上方内容。' })
  } catch (e: any) {
    error.value = e?.message || '发送失败，请重试'
  } finally {
    loading.value = false
  }
}

// 组件挂载时恢复监听状态
onMounted(async () => {
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
    }
  } catch (e) {
    console.error('恢复监听状态失败:', e)
  }
})

// 组件卸载时清理
onBeforeUnmount(() => {
  stopStatusPolling()
})
</script>

<style scoped>
.suggs { display: flex; flex-direction: column; gap: var(--ct-space-lg); }
.page-title h1 { margin: 0 0 var(--ct-space-sm); color: var(--ct-color-primary); }
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

.card-hd { padding: var(--ct-space-md) var(--ct-space-lg); font-weight: var(--ct-font-semibold); color: var(--ct-color-primary); border-bottom: 1px solid var(--ct-border-color); }
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
.realtime-monitor {
  margin-bottom: var(--ct-space-lg);
}

.collapsible {
  cursor: pointer;
  user-select: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background var(--ct-transition-fast);
}

.collapsible:hover {
  background: var(--ct-bg-tertiary);
}

.icon {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  transition: transform var(--ct-transition-fast);
}

/* 警告提示框 */
.alert {
  padding: var(--ct-space-md);
  border-radius: var(--ct-radius-md);
  margin-bottom: var(--ct-space-lg);
}

.alert.warning {
  background: var(--ct-color-warning-light);
  border-left: 3px solid var(--ct-color-warning);
}

.alert-title {
  font-weight: var(--ct-font-semibold);
  color: var(--ct-color-warning);
  margin-bottom: var(--ct-space-sm);
  font-size: var(--ct-text-sm);
}

.alert-list {
  margin: 0;
  padding-left: 20px;
  color: var(--ct-color-warning);
}

.alert-list li {
  margin: var(--ct-space-xs) 0;
  font-size: var(--ct-text-sm);
  line-height: var(--ct-leading-normal);
}

.alert-list strong {
  color: var(--ct-color-error);
  font-weight: var(--ct-font-semibold);
}

/* 监听控制 */
.monitor-control {
  display: flex;
  gap: var(--ct-space-md);
  align-items: flex-end;
  margin-bottom: var(--ct-space-lg);
}

.input-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.input-group label {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  font-weight: var(--ct-font-medium);
}

.input-group input {
  padding: var(--ct-space-sm) var(--ct-space-md);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  transition: border-color var(--ct-transition-fast);
  background: var(--ct-bg-elevated);
  color: var(--ct-text-primary);
}

.input-group input:focus {
  outline: none;
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 3px var(--ct-color-primary-light);
}

.input-group input:disabled {
  background: var(--ct-bg-tertiary);
  cursor: not-allowed;
  color: var(--ct-text-tertiary);
}

.button-group {
  display: flex;
  gap: var(--ct-space-sm);
}

.ct-btn.primary {
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse);
}

.ct-btn.primary:hover:not(:disabled) {
  background: var(--ct-color-primary-hover);
}

.ct-btn.danger {
  background: var(--ct-color-error);
  color: var(--ct-text-inverse);
}

.ct-btn.danger:hover:not(:disabled) {
  background: var(--ct-color-error-hover, #c9302c);
}

.ct-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 监听状态 */
.monitor-status {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-sm) 0;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  transition: background var(--ct-transition-normal);
}

.dot.idle {
  background: var(--ct-text-tertiary);
}

.dot.active {
  background: var(--ct-color-success);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-medium);
}

/* 进度步骤 */
.progress-steps {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
  padding-left: 20px;
}

.step {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  transition: color var(--ct-transition-normal);
}

.step.active {
  color: var(--ct-color-primary);
  font-weight: var(--ct-font-medium);
}

.step.completed {
  color: var(--ct-color-success);
}

.step.pending {
  color: var(--ct-border-color-hover);
}

.step-icon {
  width: 20px;
  text-align: center;
  font-weight: var(--ct-font-bold);
}

.step-label {
  flex: 1;
}

@media (max-width: 1024px) {
  .grid { grid-template-columns: 1fr; }
  .monitor-control { flex-direction: column; align-items: stretch; }
}
</style>
