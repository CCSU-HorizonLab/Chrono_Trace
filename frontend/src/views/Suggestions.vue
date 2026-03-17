<template>
  <section class="sug-page">
    <!-- 装饰背景 -->
    <div class="sug-ambient" aria-hidden="true">
      <div class="sug-gradient-orb sug-orb-1"></div>
      <div class="sug-gradient-orb sug-orb-2"></div>
    </div>

    <!-- 页面标题 -->
    <header class="sug-hero">
      <div class="sug-hero-text">
        <h1>AI 建议</h1>
        <p class="sug-subtitle">实时监听 · 智能画像 · 策略输出</p>
      </div>
    </header>

    <!-- 监听控制中心 -->
    <div class="sug-section">
      <div class="sug-command-card" :class="{ 'is-monitoring': realtimeState.isMonitoring }">
        <div class="sug-command-hd" :class="{ 'is-expanded': monitorPanelExpanded }" @click="toggleMonitorPanel">
          <div class="sug-command-title">
            <span class="sug-status-beacon" :class="{ active: realtimeState.isMonitoring }"></span>
            <span>实时监听控制</span>
          </div>
          <svg class="sug-chevron" :class="{ open: monitorPanelExpanded }" width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M6 8l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>

        <div v-show="monitorPanelExpanded" class="sug-command-bd">
          <!-- 注意事项 -->
          <details class="sug-notice">
            <summary>⚠ 使用须知</summary>
            <ul>
              <li>确保微信 4.0.5 已启动并登录</li>
              <li><strong>微信窗口搜索栏必须在屏幕上显示</strong>（wxauto 限制）</li>
              <li><strong>只能监听主窗口聊天，不能监听独立弹窗</strong></li>
              <li>昵称必须与微信中显示完全一致（备注名优先）</li>
              <li>同时只能监听一个对象</li>
            </ul>
          </details>

          <!-- 操作行 -->
          <div class="sug-action-row">
            <div class="sug-picker-group">
              <label class="sug-label">监听对象</label>
              <FiltersBar
                :conversations="contacts"
                :selected-conversation-id="selectedConversationId"
                :loading="contactsLoading || realtimeState.isMonitoring"
                @update:conversation-id="onConversationChange"
              />
            </div>
            <button
              class="sug-monitor-btn"
              :class="{ stop: realtimeState.isMonitoring }"
              :disabled="realtimeState.status === 'searching' || realtimeState.status === 'stopping'"
              @click="toggleMonitoring"
            >
              <span class="sug-btn-icon">{{ realtimeState.isMonitoring ? '■' : '▶' }}</span>
              <span v-if="!realtimeState.isMonitoring">开始监听</span>
              <span v-else-if="realtimeState.status === 'stopping'">停止中...</span>
              <span v-else>停止监听</span>
            </button>
          </div>

          <!-- 状态追踪 -->
          <div class="sug-pipeline" v-if="realtimeState.status !== 'idle'">
            <div
              v-for="(step, idx) in progressSteps"
              :key="idx"
              class="sug-pipe-step"
              :class="step.status"
            >
              <span class="sug-pipe-dot">
                <svg v-if="step.status === 'completed'" width="12" height="12" viewBox="0 0 12 12"><path d="M2 6l3 3 5-5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>
                <span v-else-if="step.status === 'active'" class="sug-pipe-pulse"></span>
              </span>
              <span class="sug-pipe-label">{{ step.label }}</span>
              <span v-if="idx < progressSteps.length - 1" class="sug-pipe-line" :class="step.status"></span>
            </div>
          </div>

          <!-- 错误 -->
          <div v-if="realtimeError" class="sug-error">{{ realtimeError }}</div>
        </div>
      </div>
    </div>

    <!-- 三栏配置面板 -->
    <div class="sug-section">
      <div class="sug-panels-grid">

        <!-- 卡 1: 对象画像 -->
        <div class="sug-panel">
          <div class="sug-panel-accent accent-purple"></div>
          <div class="sug-panel-hd">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M6 21v-2a4 4 0 014-4h4a4 4 0 014 4v2"/></svg>
            <span>对象画像</span>
          </div>
          <div class="sug-panel-bd">
            <div class="sug-profile-row">
              <div class="sug-avatar" aria-hidden="true">{{ profileInitial }}</div>
              <div class="sug-profile-meta">
                <span class="sug-profile-name">{{ profile.name || realtimeState.talkerName || '未选择' }}</span>
                <div class="sug-tag-row" v-if="profile.personality_tags?.length">
                  <span v-for="t in profile.personality_tags" :key="t" class="sug-tag">{{ t }}</span>
                </div>
                <div class="sug-tag-row" v-else-if="profile.tags?.length">
                  <span v-for="t in profile.tags" :key="t" class="sug-tag">{{ t }}</span>
                </div>
              </div>
            </div>
            <!-- 画像详情 -->
            <div v-if="profile.chat_style" class="sug-detail-list">
              <div class="sug-detail-row">
                <span class="sug-detail-icon">💬</span>
                <div><span class="sug-detail-label">聊天风格</span><span class="sug-detail-text">{{ profile.chat_style }}</span></div>
              </div>
              <div class="sug-detail-row" v-if="profile.interests?.length">
                <span class="sug-detail-icon">🎯</span>
                <div><span class="sug-detail-label">兴趣话题</span><span class="sug-detail-text">{{ profile.interests.join('、') }}</span></div>
              </div>
              <div class="sug-detail-row" v-if="profile.communication_tips">
                <span class="sug-detail-icon">📌</span>
                <div><span class="sug-detail-label">沟通注意</span><span class="sug-detail-text">{{ profile.communication_tips }}</span></div>
              </div>
              <div class="sug-detail-row" v-if="profile.relationship_note">
                <span class="sug-detail-icon">💡</span>
                <div><span class="sug-detail-label">关系状态</span><span class="sug-detail-text">{{ profile.relationship_note }}</span></div>
              </div>
            </div>
            <!-- 空状态 -->
            <div v-else-if="!profileLoading" class="sug-empty-state">
              <span>暂无 AI 画像</span>
              <button v-if="realtimeState.talkerName" class="sug-action-sm" @click="showProfileDialog = true" :disabled="profileLoading">生成画像</button>
            </div>
            <div v-if="profileLoading" class="sug-loading-text">画像生成中...</div>
          </div>
        </div>

        <!-- 卡 2: 我的克隆 -->
        <div class="sug-panel">
          <div class="sug-panel-accent accent-teal"></div>
          <div class="sug-panel-hd">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M20 8v6M23 11h-6"/></svg>
            <span>我的克隆画像</span>
          </div>
          <div class="sug-panel-bd">
            <div v-if="selfProfile.typing_style" class="sug-detail-list">
              <div class="sug-detail-row">
                <span class="sug-detail-icon">✍️</span>
                <div><span class="sug-detail-label">排版风格</span><span class="sug-detail-text">{{ selfProfile.typing_style }}</span></div>
              </div>
              <div class="sug-detail-row" v-if="selfProfile.frequent_catchphrases?.length">
                <span class="sug-detail-icon">🗣️</span>
                <div><span class="sug-detail-label">常用词汇</span><span class="sug-detail-text">{{ selfProfile.frequent_catchphrases.join('、') }}</span></div>
              </div>
              <div class="sug-detail-row" v-if="selfProfile.attitude_and_role">
                <span class="sug-detail-icon">🎭</span>
                <div><span class="sug-detail-label">我的态度</span><span class="sug-detail-text">{{ selfProfile.attitude_and_role }}</span></div>
              </div>
            </div>
            <div v-else-if="!selfProfileLoading" class="sug-empty-state">
              <span>暂未提取你对TA的专属聊天风格</span>
              <button v-if="realtimeState.talkerName" class="sug-action-sm" @click="showSelfProfileDialog = true" :disabled="selfProfileLoading">扫描克隆</button>
            </div>
            <div v-if="selfProfileLoading" class="sug-loading-text">特征扫描提取中 (约15-30秒)...</div>
          </div>
        </div>

        <!-- 卡 3: 建议配置 -->
        <div class="sug-panel">
          <div class="sug-panel-accent accent-amber"></div>
          <div class="sug-panel-hd">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
            <span>建议配置</span>
          </div>
          <div class="sug-panel-bd sug-config-body">
            <div class="sug-config-group">
              <label class="sug-label">触发模式</label>
              <div class="sug-seg">
                <button :class="{ active: triggerMode === 'full_auto' }" @click="setTriggerMode('full_auto')">全自动</button>
                <button :class="{ active: triggerMode === 'semi_auto' }" @click="setTriggerMode('semi_auto')">半自动</button>
                <button :class="{ active: triggerMode === 'manual' }" @click="setTriggerMode('manual')">手动</button>
              </div>
            </div>
            <div class="sug-config-group">
              <label class="sug-label">发展走向</label>
              <div class="sug-seg intent">
                <button :class="{ active: intent === 'intimate' }" @click="setIntent('intimate')"><span class="sug-intent-icon">🔥</span>亲密</button>
                <button :class="{ active: intent === 'maintain' }" @click="setIntent('maintain')"><span class="sug-intent-icon">⚖️</span>维持</button>
                <button :class="{ active: intent === 'distance' }" @click="setIntent('distance')"><span class="sug-intent-icon">❄️</span>疏远</button>
              </div>
            </div>
            <button class="sug-generate-btn" @click="manualGenerate" :disabled="loading">
              <svg v-if="!loading" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span v-if="!loading">手动生成建议</span>
              <span v-else class="sug-loading-spinner"></span>
              <span v-if="loading">生成中…</span>
            </button>
          </div>
        </div>

      </div>
    </div>

  </section>

  <!-- 画像生成确认弹窗 -->
  <Teleport to="body">
    <div v-if="showProfileDialog" class="ct-modal-overlay" @click.self="showProfileDialog = false">
      <div class="ct-modal-dialog">
        <div class="modal-title">🧠 生成联系人画像</div>
        <div class="modal-desc">
          将使用 LLM 分析「{{ realtimeState.talkerName }}」的历史聊天，生成对方画像。
        </div>
        <div class="modal-field">
          <label>Token 预算档位</label>
          <div class="budget-options">
            <label v-for="opt in [
              { value: 'low', label: '低 (~2K)', desc: '粗略画像' },
              { value: 'medium', label: '中 (~4K)', desc: '推荐' },
              { value: 'high', label: '高 (~8K)', desc: '精细画像' },
              { value: 'custom', label: '自定义', desc: '' },
            ]" :key="opt.value" class="budget-option" :class="{ active: profileBudgetLevel === opt.value }">
              <input type="radio" :value="opt.value" v-model="profileBudgetLevel" />
              <span class="budget-label">{{ opt.label }}</span>
              <span class="budget-desc" v-if="opt.desc">{{ opt.desc }}</span>
            </label>
          </div>
          <div v-if="profileBudgetLevel === 'custom'" class="custom-budget">
            <input type="number" v-model.number="profileCustomBudget" min="500" max="50000" step="500" />
            <span class="unit">tokens</span>
          </div>
        </div>
        <div class="modal-info">
          预估消耗: ~{{ profileEstimatedTokens || '计算中' }} tokens
        </div>
        <div class="modal-actions">
          <button class="ct-btn variant-ghost" @click="showProfileDialog = false">取消</button>
          <button class="ct-btn primary" @click="generateContactProfile">确认生成</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- 本体画像生成确认弹窗 -->
  <Teleport to="body">
    <div v-if="showSelfProfileDialog" class="ct-modal-overlay" @click.self="showSelfProfileDialog = false">
      <div class="ct-modal-dialog">
        <div class="modal-title">🎭 克隆我的专属风格</div>
        <div class="modal-desc">
          将分析过去你发送给「{{ realtimeState.talkerName }}」的聊天记录，提取属于你的打字排版习惯与常用口头禅。<br/>
          <strong>此举能大幅消除预设的"AI 机器味"，让生成的回复更像你自己。</strong>
        </div>
        <div class="modal-field">
          <label>扫描提取深度</label>
          <div class="budget-options">
            <label v-for="opt in [
              { value: 'medium', label: '标准 (~4K)', desc: '推荐深度' },
              { value: 'high', label: '深度 (~8K)', desc: '消耗较多' }
            ]" :key="opt.value" class="budget-option" :class="{ active: selfProfileBudgetLevel === opt.value }">
              <input type="radio" :value="opt.value" v-model="selfProfileBudgetLevel" />
              <span class="budget-label">{{ opt.label }}</span>
              <span class="budget-desc" v-if="opt.desc">{{ opt.desc }}</span>
            </label>
          </div>
        </div>
        <div class="modal-info">
          预估消耗: ~{{ selfProfileEstimatedTokens || '计算中' }} tokens
        </div>
        <div class="modal-actions">
          <button class="ct-btn variant-ghost" @click="showSelfProfileDialog = false">取消</button>
          <button class="ct-btn primary" @click="generateSelfProfile">确认提取</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- LLM 未激活提示弹窗 -->
  <Teleport to="body">
    <div v-if="showLlmWarningDialog" class="ct-modal-overlay" @click.self="showLlmWarningDialog = false">
      <div class="ct-modal-dialog">
        <div class="modal-title">⚠️ 尚未配置大模型</div>
        <div class="modal-desc">
          尚未配置或激活 LLM 模型。AI 建议需要使用大语言模型才能运作。<br/>
          是否前往设置页面进行配置？
        </div>
        <div class="modal-actions">
          <CtButton variant="ghost" @click="showLlmWarningDialog = false">取消</CtButton>
          <CtButton class="primary" @click="goToSettings">前往设置</CtButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { bridgeReady, api } from '@/api/bridge'
import CtButton from '@/components/base/CtButton.vue'
import FiltersBar from '@/components/analytics/FiltersBar.vue'

const router = useRouter()

type Message = { role: 'ai' | 'user'; content: string }

const intent = ref<any>('maintain')
const loading = ref(false)
const error = ref('')

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

// ========== AI 建议状态 ==========
const triggerMode = ref<any>('semi_auto')
const manualSuggestion = ref<any>(null)
const manualSuggestionExpanded = ref(true)

const showLlmWarningDialog = ref(false)

function goToSettings() {
  showLlmWarningDialog.value = false
  router.push('/settings')
}

// ========== 联系人列表 ==========
const contacts = ref<any[]>([])
const contactsLoading = ref(false)
const selectedConversationId = ref<number | null>(null)

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

function onConversationChange(id: number) {
  selectedConversationId.value = id
  const c = contacts.value.find((c: any) => c.id === id)
  if (c) {
    realtimeState.talkerName = c.name
    // 选择联系人后自动检查并加载画像
    checkContactProfile(c.name)
    checkSelfProfile(c.name)
  }
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

  try {
    await bridgeReady()

    const llmRes = await api.get_llm_models()
    if (!llmRes.ok || !llmRes.models || !llmRes.models.some((m: any) => m.is_active)) {
      showLlmWarningDialog.value = true
      return
    }

    realtimeError.value = ''
    realtimeState.status = 'searching'

    window.sessionStorage.setItem('realtime_start_request', JSON.stringify({
      talkerName,
      createdAt: Date.now(),
    }))

    try {
      await api.enter_floating_mode()
      router.push('/floating')
      return
    } catch (e) {
      window.sessionStorage.removeItem('realtime_start_request')
      realtimeState.status = 'idle'
      console.warn('进入悬浮模式失败', e)
      realtimeError.value = '进入悬浮模式失败'
      return
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
    
    if (result.success || result.ok) {
      realtimeState.status = 'stopped'
      realtimeState.isMonitoring = false
      
      setTimeout(() => {
        if (realtimeState.status === 'stopped') {
          realtimeState.status = 'idle'
          realtimeState.messageCount = 0
          realtimeState.messages = []
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
    const llmRes = await api.get_llm_models()
    if (!llmRes.ok || !llmRes.models || !llmRes.models.some((m: any) => m.is_active)) {
      showLlmWarningDialog.value = true
      return
    }

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
        
        if (realtimeState.status === 'loading_model' && status.model_ready) {
          realtimeState.status = 'monitoring'
        }
        
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
        realtimeState.messages = result.messages || []
      }
    } catch (e) {
      console.error('消息轮询失败:', e)
    }
  }, 3000)
}

function stopMessagesPolling() {
  if (messagesTimer) { clearInterval(messagesTimer); messagesTimer = null }
}

// ========== 画像逻辑 ==========

const selfProfile = ref<any>({})
const selfProfileLoading = ref(false)
const showSelfProfileDialog = ref(false)
const selfProfileBudgetLevel = ref('medium')
const selfProfileEstimatedTokens = ref(0)

async function checkSelfProfile(displayName: string) {
  try {
    await bridgeReady()
    const llmRes = await api.get_llm_models()
    if (!llmRes.ok || !llmRes.models || !llmRes.models.some((m: any) => m.is_active)) {
      showLlmWarningDialog.value = true
      return
    }

    const r = await api.get_self_profile(displayName)
    if (r.ok) {
      selfProfileEstimatedTokens.value = r.estimated_tokens || 0
      if (r.has_profile && !r.expired) {
        selfProfile.value = r.profile
      } else {
        selfProfile.value = {}
      }
    }
  } catch (e) {
    console.error('检查克隆画像失败:', e)
  }
}

async function generateSelfProfile() {
  showSelfProfileDialog.value = false
  selfProfileLoading.value = true
  try {
    await bridgeReady()
    const r = await api.generate_self_profile(
      realtimeState.talkerName,
      selfProfileBudgetLevel.value,
      0
    )
    if (r.ok && r.profile) {
      selfProfile.value = r.profile
    } else {
      console.error('画像克隆失败:', r.error)
    }
  } catch (e: any) {
    console.error('提取克隆画像失败:', e)
  } finally {
    selfProfileLoading.value = false
  }
}

const profile = ref<any>({
  name: '对方昵称',
  tags: [],
})
const profileInitial = computed(() => (profile.value.name ? profile.value.name[0] : 'N'))
const profileLoading = ref(false)
const showProfileDialog = ref(false)
const profileBudgetLevel = ref('medium')
const profileCustomBudget = ref(4000)
const profileEstimatedTokens = ref(0)

async function checkContactProfile(displayName: string) {
  try {
    await bridgeReady()
    const llmRes = await api.get_llm_models()
    if (!llmRes.ok || !llmRes.models || !llmRes.models.some((m: any) => m.is_active)) {
      showLlmWarningDialog.value = true
      return
    }

    const r = await api.get_contact_profile(displayName)
    if (r.ok) {
      profileEstimatedTokens.value = r.estimated_tokens || 0
      if (r.has_profile && !r.expired) {
        profile.value = { name: displayName, ...r.profile }
      } else {
        profile.value = { name: displayName, tags: [] }
        showProfileDialog.value = true
      }
    }
  } catch (e) {
    console.error('检查画像失败:', e)
  }
}

async function generateContactProfile() {
  showProfileDialog.value = false
  profileLoading.value = true
  try {
    await bridgeReady()
    const r = await api.generate_contact_profile(
      realtimeState.talkerName,
      profileBudgetLevel.value,
      profileBudgetLevel.value === 'custom' ? profileCustomBudget.value : 0
    )
    if (r.ok && r.profile) {
      profile.value = { name: realtimeState.talkerName, ...r.profile }
    } else {
      console.error('画像生成失败:', r.error)
      profile.value = {
        name: realtimeState.talkerName,
        tags: [],
        relationship_note: `⚠️ ${r.error || '画像生成失败'}`,
      }
    }
  } catch (e: any) {
    console.error('生成画像失败:', e)
    profile.value = {
      name: realtimeState.talkerName,
      tags: [],
      relationship_note: `⚠️ ${e?.message || '画像生成异常'}`,
    }
  } finally {
    profileLoading.value = false
  }
}

function copyText(text: string) { navigator.clipboard?.writeText(text) }

// 组件挂载时恢复监听状态
onMounted(async () => {
  loadContacts()

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
      loadSuggestionConfig()

      if (realtimeState.talkerName) {
        checkContactProfile(realtimeState.talkerName)
        checkSelfProfile(realtimeState.talkerName)
      }
    }
  } catch (e) {
    console.error('恢复监听状态失败:', e)
  }
})

onBeforeUnmount(() => {
  stopStatusPolling()
  stopMessagesPolling()
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
/* ═══════════════════════════════════════
   Suggestions Page — Premium Dashboard
   ═══════════════════════════════════════ */

.sug-page {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xl);
  padding: var(--ct-space-xl) var(--ct-space-xl) var(--ct-space-3xl);
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  overflow: hidden;
}

.sug-section { display: flex; flex-direction: column; }

/* --- Ambient Background --- */
.sug-ambient {
  position: fixed; inset: 0;
  pointer-events: none; z-index: 0; overflow: hidden;
}
.sug-gradient-orb { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.07; }
.sug-orb-1 { width: 600px; height: 600px; top: -200px; right: -100px; background: var(--ct-color-primary); }
.sug-orb-2 { width: 400px; height: 400px; bottom: -150px; left: -80px; background: #34d399; }

/* --- Hero Header --- */
.sug-hero { position: relative; z-index: 1; padding: var(--ct-space-lg) 0; }
.sug-hero h1 {
  font-family: var(--ct-font-display); font-size: var(--ct-text-3xl); font-weight: 700;
  color: var(--ct-text-primary); margin: 0; letter-spacing: -0.02em;
}
.sug-subtitle {
  font-size: var(--ct-text-sm); color: var(--ct-text-tertiary);
  margin: var(--ct-space-xs) 0 0; letter-spacing: 0.15em; font-weight: 400;
}

/* ═══ Command Card ═══ */
.sug-command-card {
  position: relative; z-index: 10;
  background: var(--ct-bg-elevated); border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-xl);
  transition: border-color var(--ct-transition-normal), box-shadow var(--ct-transition-normal);
}
.sug-command-card:hover { border-color: var(--ct-border-color-hover); box-shadow: var(--ct-shadow-md); }
.sug-command-card.is-monitoring {
  border-color: var(--ct-color-success);
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.15), var(--ct-shadow-md);
}

.sug-command-hd {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--ct-space-lg) var(--ct-space-xl);
  cursor: pointer; user-select: none; transition: background var(--ct-transition-fast);
  border-radius: var(--ct-radius-xl);
}
.sug-command-hd.is-expanded {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
}
.sug-command-hd:hover { background: var(--ct-bg-secondary); }
.sug-command-title {
  display: flex; align-items: center; gap: var(--ct-space-sm);
  font-weight: 600; font-size: var(--ct-text-base); color: var(--ct-text-primary);
}

/* 状态灯 */
.sug-status-beacon {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--ct-text-tertiary); transition: background var(--ct-transition-normal);
}
.sug-status-beacon.active {
  background: var(--ct-color-success); box-shadow: 0 0 8px rgba(16, 185, 129, 0.6);
  animation: sug-beacon 2s ease-in-out infinite;
}
@keyframes sug-beacon {
  0%, 100% { opacity: 1; box-shadow: 0 0 8px rgba(16, 185, 129, 0.6); }
  50% { opacity: 0.6; box-shadow: 0 0 16px rgba(16, 185, 129, 0.3); }
}

.sug-chevron { color: var(--ct-text-tertiary); transition: transform var(--ct-transition-fast); }
.sug-chevron.open { transform: rotate(180deg); }

.sug-command-bd {
  padding: 0 var(--ct-space-xl) var(--ct-space-xl);
  display: flex; flex-direction: column; gap: var(--ct-space-lg);
}

/* 注意事项 (details) */
.sug-notice {
  font-size: var(--ct-text-sm); color: var(--ct-text-secondary);
  border-left: 3px solid var(--ct-color-warning); padding-left: var(--ct-space-md); margin: 0;
}
.sug-notice summary {
  cursor: pointer; font-weight: 600; color: var(--ct-color-warning); list-style: none;
  display: flex; align-items: center; gap: var(--ct-space-xs);
}
.sug-notice summary::-webkit-details-marker { display: none; }
.sug-notice summary::before { content: '▸'; transition: transform 0.2s; display: inline-block; margin-right: 4px; }
.sug-notice[open] summary::before { transform: rotate(90deg); }
.sug-notice ul { margin: var(--ct-space-sm) 0 0; padding-left: var(--ct-space-lg); display: flex; flex-direction: column; gap: 4px; }
.sug-notice li { line-height: 1.6; }
.sug-notice strong { color: var(--ct-color-error); }

/* 操作行 */
.sug-action-row { display: flex; gap: var(--ct-space-lg); align-items: flex-end; }
.sug-picker-group { flex: 1; display: flex; flex-direction: column; gap: var(--ct-space-xs); }
.sug-label {
  font-size: var(--ct-text-xs); font-weight: 600; color: var(--ct-text-secondary);
  text-transform: uppercase; letter-spacing: 0.06em;
}
.sug-picker-group :deep(.filters-bar) { box-shadow: none; padding: 0; background: transparent; }

/* 监听按钮 */
.sug-monitor-btn {
  display: inline-flex; align-items: center; gap: var(--ct-space-sm);
  padding: 10px 28px; border: none; border-radius: var(--ct-radius-lg);
  font-weight: 600; font-size: var(--ct-text-sm); cursor: pointer; white-space: nowrap;
  transition: all var(--ct-transition-fast);
  background: linear-gradient(135deg, var(--ct-color-primary), #6366f1);
  color: white; box-shadow: 0 4px 14px rgba(124, 77, 255, 0.25);
}
.sug-monitor-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(124, 77, 255, 0.35); }
.sug-monitor-btn.stop { background: linear-gradient(135deg, var(--ct-color-error), #dc2626); box-shadow: 0 4px 14px rgba(239, 68, 68, 0.25); }
.sug-monitor-btn.stop:hover:not(:disabled) { box-shadow: 0 6px 20px rgba(239, 68, 68, 0.35); }
.sug-monitor-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.sug-btn-icon { font-size: 11px; }

/* Pipeline 进度 */
.sug-pipeline { display: flex; flex-direction: column; gap: 0; padding: var(--ct-space-sm) 0; }
.sug-pipe-step {
  display: flex; align-items: center; gap: var(--ct-space-sm);
  position: relative; padding: var(--ct-space-xs) 0;
  color: var(--ct-text-tertiary); font-size: var(--ct-text-sm);
  transition: color var(--ct-transition-fast);
}
.sug-pipe-step.active { color: var(--ct-color-primary); font-weight: 500; }
.sug-pipe-step.completed { color: var(--ct-color-success); }
.sug-pipe-dot {
  width: 20px; height: 20px; border-radius: 50%;
  border: 2px solid var(--ct-border-color); display: flex;
  align-items: center; justify-content: center; flex-shrink: 0;
  transition: border-color var(--ct-transition-fast);
}
.sug-pipe-step.active .sug-pipe-dot { border-color: var(--ct-color-primary); }
.sug-pipe-step.completed .sug-pipe-dot { border-color: var(--ct-color-success); background: var(--ct-color-success); color: white; }
.sug-pipe-pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--ct-color-primary); animation: sug-pulse 1.5s ease-in-out infinite; }
@keyframes sug-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.5); opacity: 0.5; } }
.sug-pipe-label { flex: 1; }

.sug-error {
  padding: var(--ct-space-sm) var(--ct-space-md);
  background: var(--ct-color-error-light); color: var(--ct-color-error);
  border-radius: var(--ct-radius-md); font-size: var(--ct-text-sm);
  border-left: 3px solid var(--ct-color-error);
}

/* ═══ Panels Grid ═══ */
.sug-panels-grid {
  position: relative; z-index: 1;
  display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--ct-space-lg);
}
.sug-panel {
  position: relative; background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color); border-radius: var(--ct-radius-xl);
  overflow: hidden; display: flex; flex-direction: column;
  transition: transform var(--ct-transition-normal) var(--ct-ease-out),
              box-shadow var(--ct-transition-normal) var(--ct-ease-out),
              border-color var(--ct-transition-normal);
}
.sug-panel:hover { transform: translateY(-3px); box-shadow: var(--ct-shadow-lg); border-color: var(--ct-border-color-hover); }

/* 顶部装饰条 */
.sug-panel-accent { height: 3px; width: 100%; flex-shrink: 0; }
.accent-purple { background: linear-gradient(90deg, var(--ct-color-primary), #a855f7); }
.accent-teal { background: linear-gradient(90deg, #14b8a6, #06b6d4); }
.accent-amber { background: linear-gradient(90deg, #f59e0b, #f97316); }

.sug-panel-hd {
  display: flex; align-items: center; gap: var(--ct-space-sm);
  padding: var(--ct-space-md) var(--ct-space-lg); font-weight: 600;
  font-size: var(--ct-text-sm); color: var(--ct-text-primary);
  border-bottom: 1px solid var(--ct-border-color);
}
.sug-panel-hd svg { color: var(--ct-text-tertiary); }
.sug-panel-bd { padding: var(--ct-space-lg); flex: 1; display: flex; flex-direction: column; }

/* Profile Card */
.sug-profile-row { display: flex; align-items: center; gap: var(--ct-space-md); margin-bottom: var(--ct-space-md); }
.sug-avatar {
  width: 44px; height: 44px; border-radius: 50%;
  background: linear-gradient(135deg, var(--ct-color-primary-light), var(--ct-color-primary-muted));
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: var(--ct-text-lg); color: var(--ct-color-primary);
  flex-shrink: 0; border: 2px solid var(--ct-color-primary-muted);
}
.sug-profile-meta { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.sug-profile-name {
  font-weight: 600; font-size: var(--ct-text-base); color: var(--ct-text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sug-tag-row { display: flex; flex-wrap: wrap; gap: 4px; }
.sug-tag {
  display: inline-block; padding: 2px 8px; font-size: 11px; font-weight: 500;
  border-radius: var(--ct-radius-full); background: var(--ct-color-primary-light); color: var(--ct-color-primary);
}

/* Detail List */
.sug-detail-list { display: flex; flex-direction: column; gap: 0; }
.sug-detail-row { display: flex; gap: var(--ct-space-sm); padding: var(--ct-space-sm) 0; align-items: flex-start; }
.sug-detail-row + .sug-detail-row { border-top: 1px solid var(--ct-border-color); }
.sug-detail-icon { font-size: 15px; line-height: 1; flex-shrink: 0; margin-top: 2px; }
.sug-detail-row > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.sug-detail-label { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.sug-detail-text { font-size: var(--ct-text-sm); color: var(--ct-text-secondary); line-height: 1.5; word-break: break-word; }

/* Empty/Loading */
.sug-empty-state {
  display: flex; align-items: center; justify-content: space-between; gap: var(--ct-space-sm);
  padding: var(--ct-space-md); border-radius: var(--ct-radius-md);
  background: var(--ct-bg-secondary); font-size: var(--ct-text-sm); color: var(--ct-text-tertiary);
}
.sug-action-sm {
  padding: 4px 14px; font-size: var(--ct-text-xs); font-weight: 600;
  border-radius: var(--ct-radius-full); border: 1px solid var(--ct-color-primary);
  color: var(--ct-color-primary); background: transparent; cursor: pointer; white-space: nowrap;
  transition: all var(--ct-transition-fast);
}
.sug-action-sm:hover:not(:disabled) { background: var(--ct-color-primary-light); }
.sug-action-sm:disabled { opacity: 0.5; cursor: not-allowed; }
.sug-loading-text { font-size: var(--ct-text-sm); color: var(--ct-color-primary); padding: var(--ct-space-sm) 0; animation: sug-beacon 1.5s ease-in-out infinite; }

/* ═══ Config Panel ═══ */
.sug-config-body { gap: var(--ct-space-lg); }
.sug-config-group { display: flex; flex-direction: column; gap: var(--ct-space-xs); }
.sug-seg { display: flex; border-radius: var(--ct-radius-md); overflow: hidden; border: 1px solid var(--ct-border-color); }
.sug-seg button {
  flex: 1; padding: var(--ct-space-sm); border: none;
  background: var(--ct-bg-elevated); color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs); font-weight: 500; cursor: pointer;
  transition: all var(--ct-transition-fast);
}
.sug-seg button:not(:last-child) { border-right: 1px solid var(--ct-border-color); }
.sug-seg button.active { background: var(--ct-color-primary); color: white; font-weight: 600; }
.sug-seg button:hover:not(.active) { background: var(--ct-bg-tertiary); }
.sug-intent-icon { margin-right: 2px; }

/* CTA 按钮 */
.sug-generate-btn {
  display: flex; align-items: center; justify-content: center; gap: var(--ct-space-sm);
  width: 100%; padding: 12px; border: none; border-radius: var(--ct-radius-lg);
  background: linear-gradient(135deg, var(--ct-color-primary), #7c3aed);
  color: white; font-weight: 600; font-size: var(--ct-text-sm); cursor: pointer;
  transition: all var(--ct-transition-fast);
  box-shadow: 0 4px 14px rgba(124, 77, 255, 0.2); margin-top: var(--ct-space-xs);
}
.sug-generate-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(124, 77, 255, 0.35); }
.sug-generate-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.sug-loading-spinner {
  width: 16px; height: 16px; border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white; border-radius: 50%; animation: sug-spin 0.6s linear infinite;
}
@keyframes sug-spin { to { transform: rotate(360deg); } }

/* ═══ Modal Styles ═══ */
.modal-desc { font-size: var(--ct-text-sm); color: var(--ct-text-secondary); line-height: 1.5; margin-bottom: var(--ct-space-md); }
.modal-field > label { font-size: var(--ct-text-sm); font-weight: var(--ct-font-medium); color: var(--ct-text-secondary); }
.budget-options { display: grid; grid-template-columns: 1fr 1fr; gap: var(--ct-space-xs); }
.budget-option {
  display: flex; align-items: center; gap: 6px; padding: 8px 10px;
  border-radius: var(--ct-radius-sm); border: 1px solid var(--ct-border-color);
  cursor: pointer; transition: all var(--ct-transition-fast); font-size: var(--ct-text-sm);
}
.budget-option:hover { border-color: var(--ct-color-primary); }
.budget-option.active { border-color: var(--ct-color-primary); background: var(--ct-color-primary-light); }
.budget-option input[type="radio"] { display: none; }
.budget-label { font-weight: var(--ct-font-medium); }
.budget-desc { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.custom-budget { display: flex; align-items: center; gap: 6px; margin-top: var(--ct-space-xs); grid-column: 1 / -1; }
.custom-budget input { width: 120px; padding: 6px 10px; border-radius: var(--ct-radius-sm); border: 1px solid var(--ct-border-color); background: var(--ct-bg-elevated); color: var(--ct-text-primary); font-size: var(--ct-text-sm); }
.custom-budget .unit { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.modal-info { font-size: var(--ct-text-sm); color: var(--ct-text-tertiary); margin-top: var(--ct-space-sm); }

/* ═══ Responsive ═══ */
@media (max-width: 1024px) { .sug-panels-grid { grid-template-columns: 1fr; } }
@media (max-width: 768px) {
  .sug-action-row { flex-direction: column; align-items: stretch; }
  .sug-hero h1 { font-size: var(--ct-text-2xl); }
}
</style>
