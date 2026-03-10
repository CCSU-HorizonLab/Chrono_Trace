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

    <!-- ====== 左右分栏布局（统一视图） ====== -->
    <div class="split-layout">



      <!-- 💡 右侧：对象信息与建议面板 -->
      <div class="pane pane-right">
        <!-- 对象信息卡 -->
        <div class="card">
          <div class="ct-card-hd">对象信息</div>
          <div class="card-bd profile">
            <div class="avatar" aria-hidden="true">{{ profileInitial }}</div>
            <div class="meta">
              <div class="name">{{ profile.name || realtimeState.talkerName || '未选择对象' }}</div>
              <!-- AI 画像标签 -->
              <div class="tags" v-if="profile.personality_tags?.length">
                <span v-for="t in profile.personality_tags" :key="t">{{ t }}</span>
              </div>
              <!-- 无画像时的旧标签 -->
              <div class="tags" v-else-if="profile.tags?.length">
                <span v-for="t in profile.tags" :key="t">{{ t }}</span>
              </div>
            </div>
          </div>
          <!-- AI 画像详情 -->
          <div v-if="profile.chat_style" class="profile-detail">
            <div class="detail-item">
              <span class="detail-label">💬 聊天风格</span>
              <span class="detail-text">{{ profile.chat_style }}</span>
            </div>
            <div class="detail-item" v-if="profile.interests?.length">
              <span class="detail-label">🎯 兴趣话题</span>
              <span class="detail-text">{{ profile.interests.join('、') }}</span>
            </div>
            <div class="detail-item" v-if="profile.communication_tips">
              <span class="detail-label">📌 沟通注意</span>
              <span class="detail-text">{{ profile.communication_tips }}</span>
            </div>
            <div class="detail-item" v-if="profile.relationship_note">
              <span class="detail-label">💡 关系状态</span>
              <span class="detail-text">{{ profile.relationship_note }}</span>
            </div>
          </div>
          <!-- 无画像提示 -->
          <div v-else-if="!profileLoading" class="profile-empty">
            <span>暂无 AI 画像</span>
            <button
              v-if="realtimeState.talkerName"
              class="btn-sm"
              @click="showProfileDialog = true"
              :disabled="profileLoading"
            >生成画像</button>
          </div>
          <div v-if="profileLoading" class="profile-loading">画像生成中...</div>
        </div>

        <!-- 本体克隆信息卡 -->
        <div class="card config-card">
          <div class="card-hd">👤 我的克隆画像 (送给AI的模仿样本)</div>
          <div class="card-bd">
            <div v-if="selfProfile.typing_style" class="profile-detail">
              <div class="detail-item">
                <span class="detail-label">✍️ 排版风格</span>
                <span class="detail-text">{{ selfProfile.typing_style }}</span>
              </div>
              <div class="detail-item" v-if="selfProfile.frequent_catchphrases?.length">
                <span class="detail-label">🗣️ 常用词汇</span>
                <span class="detail-text">{{ selfProfile.frequent_catchphrases.join('、') }}</span>
              </div>
              <div class="detail-item" v-if="selfProfile.attitude_and_role">
                <span class="detail-label">🎭 我的态度</span>
                <span class="detail-text">{{ selfProfile.attitude_and_role }}</span>
              </div>
            </div>
            <!-- 无画像提示 -->
            <div v-else-if="!selfProfileLoading" class="profile-empty">
              <span>系统暂未提取你对TA的专属聊天风格</span>
              <button
                v-if="realtimeState.talkerName"
                class="btn-sm"
                @click="showSelfProfileDialog = true"
                :disabled="selfProfileLoading"
              >立即扫描克隆</button>
            </div>
            <div v-if="selfProfileLoading" class="profile-loading">特征扫描提取中 (约15-30秒)...</div>
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
import { ref, onMounted, watch, onBeforeUnmount, computed, reactive, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { bridgeReady, api } from '@/api/bridge'
import * as echarts from 'echarts'
import CtButton from '@/components/base/CtButton.vue'

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

  // 选择联系人后自动检查并加载画像
  checkContactProfile(c.name)
  checkSelfProfile(c.name)
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
    checkContactProfile(realtimeState.talkerName)
    checkSelfProfile(realtimeState.talkerName)
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
  
  try {
    await bridgeReady()
    
    // 检查 LLM 模型是否激活
    const llmRes = await api.get_llm_models()
    if (!llmRes.ok || !llmRes.models || !llmRes.models.some((m: any) => m.is_active)) {
      showLlmWarningDialog.value = true
      return
    }

    realtimeError.value = ''
    realtimeState.status = 'searching'
    
    // 先进入悬浮窗模式（让用户立刻看到 UI，不阻塞等待 ChatWith）
    try {
      await api.enter_floating_mode()
      router.push('/floating')
    } catch (e) {
      console.warn('进入悬浮模式失败，保持当前页面:', e)
    }
    
    // 再启动监听（ChatWith 在后台异步执行，不阻塞前端）
    const result = await api.start_realtime_monitor(talkerName)
    
    if (result.success || result.ok) {
      realtimeState.batchId = result.batch_id
      realtimeState.status = 'loading_model'
      realtimeState.isMonitoring = true
      
      startStatusPolling()
      startMessagesPolling()
      loadSuggestionConfig()    // 加载建议配置
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


// ========== 原有逻辑 ==========

const selfProfile = ref<any>({})
const selfProfileLoading = ref(false)
const showSelfProfileDialog = ref(false)
const selfProfileBudgetLevel = ref('medium')
const selfProfileEstimatedTokens = ref(0)

async function checkSelfProfile(displayName: string) {
  try {
    await bridgeReady()
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

// 检查联系人画像
async function checkContactProfile(displayName: string) {
  try {
    await bridgeReady()
    const r = await api.get_contact_profile(displayName)
    if (r.ok) {
      profileEstimatedTokens.value = r.estimated_tokens || 0
      if (r.has_profile && !r.expired) {
        // 有有效缓存 → 直接展示
        profile.value = { name: displayName, ...r.profile }
      } else {
        // 无缓存或已过期 → 弹窗询问
        profile.value = { name: displayName, tags: [] }
        showProfileDialog.value = true
      }
    }
  } catch (e) {
    console.error('检查画像失败:', e)
  }
}

// 生成联系人画像
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

// 组件卸载时清理
onBeforeUnmount(() => {
  stopStatusPolling()
  stopMessagesPolling()
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

/* 画像详情 */
.profile-detail {
  padding: var(--ct-space-sm) var(--ct-space-md);
  border-top: 1px solid var(--ct-border);
}
.detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--ct-space-xs) 0;
}
.detail-item + .detail-item { border-top: 1px solid var(--ct-border-light, rgba(255,255,255,0.04)); }
.detail-label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  font-weight: var(--ct-font-medium);
}
.detail-text {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: 1.5;
}
.profile-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ct-space-sm) var(--ct-space-md);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
}
.profile-loading {
  padding: var(--ct-space-sm) var(--ct-space-md);
  font-size: var(--ct-text-sm);
  color: var(--ct-color-primary);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.btn-sm {
  padding: 4px 12px;
  font-size: var(--ct-text-xs);
  border-radius: var(--ct-radius-sm);
  border: 1px solid var(--ct-color-primary);
  color: var(--ct-color-primary);
  background: transparent;
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}
.btn-sm:hover { background: var(--ct-color-primary-light); }
.btn-sm:disabled { opacity: 0.5; cursor: not-allowed; }

/* 弹窗内部特有样式 */
.modal-desc {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: 1.5;
  margin-bottom: var(--ct-space-md);
}
.modal-field > label {
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-medium);
  color: var(--ct-text-secondary);
}
.budget-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ct-space-xs);
}
.budget-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--ct-radius-sm);
  border: 1px solid var(--ct-border-color);
  cursor: pointer;
  transition: all var(--ct-transition-fast);
  font-size: var(--ct-text-sm);
}
.budget-option:hover { border-color: var(--ct-color-primary); }
.budget-option.active {
  border-color: var(--ct-color-primary);
  background: var(--ct-color-primary-light);
}
.budget-option input[type="radio"] { display: none; }
.budget-label { font-weight: var(--ct-font-medium); }
.budget-desc { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }

.custom-budget {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--ct-space-xs);
  grid-column: 1 / -1;
}
.custom-budget input {
  width: 120px;
  padding: 6px 10px;
  border-radius: var(--ct-radius-sm);
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-elevated);
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
}
.custom-budget .unit { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.modal-info {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  margin-top: var(--ct-space-sm);
}
</style>
