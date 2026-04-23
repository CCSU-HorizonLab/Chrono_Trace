<template>
  <div class="fp-layout" :class="{ 'is-inspector-open': inspectorOpen }">
    <!-- 1. Header (Fixed) -->
    <header class="fp-site-header">
      <div class="fp-header-drag-zone">
        <div class="fp-brand">
          <span class="fp-status-dot" :class="{ active: realtimeState.isMonitoring }"></span>
          <span class="fp-brand-name">Chrono Trace</span>
        </div>
        <button class="fp-btn-icon close-btn" @click="exitFloating" title="退出悬浮模式">✕</button>
      </div>
      <div class="fp-contact-bar">
        <CtAvatar
          class="fp-avatar"
          :src="contactAvatar"
          :name="profile.name || realtimeState.talkerName"
          :size="34"
          radius="10px"
        />
        <div class="fp-contact-info">
          <div class="fp-contact-name">{{ profile.name || realtimeState.talkerName || '等待对象...' }}</div>
          <div class="fp-contact-tags" v-if="!profileExpanded && profile.personality_tags?.length">
            <span v-for="t in profile.personality_tags.slice(0, 3)" :key="t" class="fp-tag">{{ t }}</span>
          </div>
        </div>
        <button class="fp-btn-icon profile-toggle" :class="{ 'is-open': profileExpanded }" @click="profileExpanded = !profileExpanded">
           <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 9l6 6 6-6"/></svg>
        </button>
      </div>

      <!-- Absolute Profile Dropdown -->
      <div class="fp-profile-dropdown" v-show="profileExpanded">
        <div class="fp-contact-tags all-tags" v-if="profile.personality_tags?.length">
          <span v-for="t in profile.personality_tags" :key="t" class="fp-tag">{{ t }}</span>
        </div>
        <div class="fp-profile-attrs">
          <div v-if="profile.chat_style" class="fp-attr">
            <span class="fp-attr-lbl">画像</span><span class="fp-attr-val">{{ profile.chat_style }}</span>
          </div>
          <div v-if="profile.interests?.length" class="fp-attr">
            <span class="fp-attr-lbl">兴趣</span><span class="fp-attr-val">{{ profile.interests.join('、') }}</span>
          </div>
          <div v-if="profile.communication_tips" class="fp-attr">
            <span class="fp-attr-lbl">提示</span><span class="fp-attr-val">{{ profile.communication_tips }}</span>
          </div>
          <div v-if="profile.relationship_note" class="fp-attr">
            <span class="fp-attr-lbl">关系</span><span class="fp-attr-val">{{ profile.relationship_note }}</span>
          </div>
          <div v-if="!profile.chat_style && !profileLoading" class="fp-profile-empty">
            <span class="fp-txt-sub">暂无画像特征</span>
            <button class="fp-btn-sm" @click="showProfileDialog = true">扫描画像</button>
          </div>
        </div>
      </div>
    </header>

    <!-- App State Banners -->
    <div class="fp-banners">
      <div v-if="connectionLost" class="fp-banner error">
        <span>连接断开，等待重连…</span>
        <button class="fp-btn-sm warning" @click="retryConnection">重试</button>
      </div>
      <div v-if="uiaRecoverySummary && !connectionLost" class="fp-banner info">
        <div class="fp-banner-copy">
          <span>{{ uiaRecoverySummary }}</span>
          <span v-if="narratorVerificationText" class="fp-banner-sub">{{ narratorVerificationText }}</span>
        </div>
      </div>
      <div v-if="chatError && !connectionLost" class="fp-banner error">
        <span>{{ chatError }}</span>
        <button class="fp-btn-sm warning" @click="exitFloating">重新开始</button>
      </div>
    </div>

        <!-- Workbench Container -->
    <div class="fp-workbench-container">
      
      <!-- LEFT/MAIN COLUMN -->
      <main class="fp-main-column">
        <!-- Narrow Mode Insights Strip -->
        <div class="fp-insights-strip" @click="toggleInspector('emotion')">
      <div class="fp-insight-primary">
        <span class="fp-trend-badge" :class="emotionSummary?.trend || 'neutral'">
          {{ emotionSummary?.trend === 'positive' ? '正面向上' : emotionSummary?.trend === 'negative' ? '负面向下' : '稳定平缓' }}
        </span>
        <span class="fp-insight-text">{{ emotionSummary?.insight || '正在分析情绪数据...' }}</span>
      </div>
      <div class="fp-insight-metrics">
        <span v-if="computedChartStats?.msg_ratio" class="fp-metric-pill">比例 {{ computedChartStats.msg_ratio }}</span>
        <span class="fp-arr" :class="{'arr-up': inspectorOpen && inspectorTab === 'emotion'}">›</span>
      </div>
    </div>

    <!-- 3. SHARED INSPECTOR PANEL (Shared fixed height block) -->

        <!-- 4. Suggestion & Chat Area (Main scroll view) -->
        <div class="fp-main-stack">
      <div class="fp-scroll-area" ref="suggestionsRef">
        <div v-if="lastThread" class="fp-thread-banner compress" @click="loadLastThread">
          <div class="fp-thread-info">
            <span class="fp-thread-label">继续指导: {{ lastThread.summary }}</span>
          </div>
          <button class="fp-btn-icon tiny" @click.stop="lastThread = null">✕</button>
        </div>

        <div v-if="!allSuggestions.length && !loading" class="fp-empty-slate">
          等待接收聊天数据...
        </div>

        <div class="fp-sug-list">
          <div
            v-for="s in allSuggestions"
            :key="s.id || s._tempId"
            :class="{
              'fp-card': s._type === 'suggestion',
              [s.severity || 'medium']: s._type === 'suggestion',
              'fp-bubble': s._type === 'chat',
              user: s._type === 'chat' && s.role === 'user',
              ai: s._type === 'chat' && s.role === 'ai'
            }"
          >
            <template v-if="s._type === 'suggestion'">
              <div class="fp-card-hd" @click="toggleSuggestion(s)">
                <span class="fp-card-icon">{{ getTriggerIcon(s.trigger_type) }}</span>
                <span class="fp-card-title">{{ s.summary }}</span>
                <span class="fp-card-time">{{ s.created_at ? formatMsgTime(s.created_at) : '刚刚' }}</span>
                <button class="fp-btn-icon">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'rotate-180': isSuggestionExpanded(s) }"><path d="M6 9l6 6 6-6"/></svg>
                </button>
              </div>
              <div v-show="isSuggestionExpanded(s)" class="fp-card-bd">
                <details v-if="s.thought_process" class="fp-cot">
                  <summary>思考过程</summary>
                  <div class="fp-cot-txt">{{ s.thought_process }}</div>
                </details>
                <div v-for="(sp, i) in s.speeches" :key="i" class="fp-speech-item">
                  <span class="fp-speech-text">{{ sp }}</span>
                  <button class="fp-btn-copy" @click="copyText(sp)">复制</button>
                </div>
              </div>
            </template>

            <template v-else-if="s._type === 'chat'">
              <div class="fp-bubble-meta">
                 <span class="fp-bubble-avatar">{{ s.role === 'user' ? '我' : 'AI' }}</span>
                 <span class="fp-bubble-time">{{ formatMsgTime(s.created_at) }}</span>
              </div>
              <div class="fp-bubble-txt">{{ s.content }}</div>
            </template>
          </div>

          <div v-if="loading" class="fp-loading-state">
            <div class="fp-spinner"></div>
            <span>AI 分析中 ({{ thinkingSeconds }}s)</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. Bottom Composer -->

        <!-- 5. Bottom Composer -->
        
      </main>

      <!-- RIGHT SUPPORT RAIL (or Narrow Shared Inspector) -->
      <aside class="fp-support-rail fp-inspector">
      <div class="fp-inspector-header">
        <div class="fp-inspector-tabs">
          <button class="fp-tab-btn" :class="{ active: inspectorTab === 'emotion' }" @click="toggleInspector('emotion')">情绪明细</button>
          <button class="fp-tab-btn" :class="{ active: inspectorTab === 'context' }" @click="toggleInspector('context')">AI 参考记录</button>
        </div>
        <button class="fp-btn-icon close-rail-btn" @click="closeInspector">✕</button>
      </div>

      <div class="fp-inspector-body">
        <!-- EMOTION TAB -->
        <div v-show="inspectorTab === 'emotion'" class="fp-inspector-tab-content">
          <!-- 1. Compact Summary Strip/Cards -->
          <div class="fp-emotion-summary-cards">
            <div class="fp-summary-card">
              <span class="fp-card-lbl">情绪趋势</span>
              <span class="fp-card-val" :class="emotionSummary?.trend || 'neutral'">{{ emotionSummary?.trend === 'positive' ? '正面' : emotionSummary?.trend === 'negative' ? '负面' : '平稳' }}</span>
            </div>
            <div class="fp-summary-card">
              <span class="fp-card-lbl">发言比例</span>
              <span class="fp-card-val">{{ computedChartStats?.msg_ratio || '暂无' }}</span>
            </div>
            <div class="fp-summary-card">
              <span class="fp-card-lbl">回复率</span>
              <span class="fp-card-val">{{ computedChartStats?.reply_rate || '暂无' }}</span>
            </div>
          </div>

          <!-- 2. Main Chart or Empty State -->
          <div v-show="!hasSufficientEmotionData" class="compact-empty">
            <span class="fp-empty-icon">🌱</span>
            <span>数据不足以绘制图表 (暂存 {{ realtimeState.messageCount }} 条对话)</span>
          </div>
          
          <div v-show="hasSufficientEmotionData" class="fp-chart-workspace">
            <div class="fp-chart-header-row">
              <span class="fp-chart-lbl">主图表分析</span>
              <button class="fp-btn-text tiny-link" @click="showSecondaryCharts = !showSecondaryCharts">
                {{ showSecondaryCharts ? '收起次要图表' : '展开次要图表' }}
              </button>
            </div>
            <div class="fp-chart-stage tight-stage">
              <div class="fp-chart-item emotion-curve-main compact-main">
                <div ref="emotionChartRef" class="fp-chart-wrap"></div>
              </div>
            </div>

            <!-- 3. Secondary Charts Toggle -->
            <div v-show="showSecondaryCharts" class="fp-secondary-charts-zone">
              <div class="fp-chart-settings compact-charts-config tight-config">
                <label v-for="item in chartConfigItems.filter(i => i.key !== 'emotion_curve')" :key="item.key" class="fp-chart-toggle">
                  <input :checked="chartVisibility[item.key]" type="checkbox" @change="toggleChartVisibility(item.key)" />
                  <span>{{ item.label }}</span>
                </label>
              </div>
              <div class="fp-chart-rail tight-rail">
                <div v-if="chartVisibility.msg_frequency" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">消息频率</div>
                  <div v-show="computedChartStats?.friend_msg_count > 0" ref="freqChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!(computedChartStats?.friend_msg_count > 0)" class="fp-empty-val">缺乏特征数据</div>
                </div>
                <div v-if="chartVisibility.emotion_dist" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">情绪分布</div>
                  <div v-show="computedChartStats?.friend_msg_count > 0" ref="distChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!(computedChartStats?.friend_msg_count > 0)" class="fp-empty-val">缺乏特征数据</div>
                </div>
                <div v-if="chartVisibility.reply_gap" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">回复间隔</div>
                  <div v-show="computedChartStats?.avg_reply_gap" ref="replyGapChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!computedChartStats?.avg_reply_gap" class="fp-empty-val">暂无间隔数据</div>
                </div>
                <div v-if="chartVisibility.msg_ratio" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">发言比例</div>
                  <div ref="ratioChartRef" class="fp-chart-wrap"></div>
                </div>
                <div v-if="chartVisibility.intensity_heat" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">情绪强度</div>
                  <div v-show="computedChartStats?.friend_msg_count > 0" ref="intensityChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!(computedChartStats?.friend_msg_count > 0)" class="fp-empty-val">缺乏强度数据</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- CONTEXT TAB -->
        <div v-show="inspectorTab === 'context'" class="fp-inspector-tab-content">
          <div class="fp-context-meta">基于最近 {{ contextUsed.length }} 条主要聊天记录</div>
          <div v-if="!contextUsed.length" class="fp-context-empty">暂无可用参考记录。</div>
          <div class="fp-context-list stream-layout">
            <div v-for="(msg, i) in contextUsed" :key="i" class="fp-ctx-msg" :class="{ self: msg.sender === '我' }">
              <div class="fp-ctx-msg-hd">
                 <span class="fp-ctx-sender">{{ msg.sender }}</span>
                 <span v-if="msg.timestamp" class="fp-ctx-time">{{ formatMsgTime(msg.timestamp) }}</span>
              </div>
              <div class="fp-ctx-txt">{{ msg.content }}</div>
            </div>
          </div>
        </div>
      </div>
    </aside>

    </div>
  <footer class="fp-composer">
      <!-- Top strip -->
      <div class="fp-composer-top">
        <div class="fp-quick-prompts">
          <button v-for="q in quickPrompts" :key="q" class="fp-qp-btn" @click="sendQuickPrompt(q)">{{ q }}</button>
        </div>
        <button class="fp-ctx-btn" @click="toggleInspector('context')" :class="{ 'is-active': inspectorOpen && inspectorTab === 'context' }" title="查看AI参考记录">参考</button>
      </div>

      <!-- Settings Strip -->
      <div class="fp-composer-settings">
        <div class="fp-seg-group">
          <span class="fp-seg-title">触发模式</span>
          <button v-for="m in triggerModes" :key="m.value" class="fp-seg-btn" :class="{ active: triggerMode === m.value }" @click="setTriggerMode(m.value)" :title="m.value === 'full_auto' ? '自动分析所有新消息' : m.value === 'semi_auto' ? '需要时自动给出建议' : '仅在手动点击生成时分析'">{{ m.label }}</button>
        </div>
        <div class="fp-seg-divider"></div>
        <div class="fp-seg-group">
          <span class="fp-seg-title">关系方向</span>
          <button class="fp-seg-btn" :class="{ active: intent === 'intimate' }" @click="setIntent('intimate')" title="生成更有感情、亲密回复">亲近</button>
          <button class="fp-seg-btn" :class="{ active: intent === 'maintain' }" @click="setIntent('maintain')" title="维持当前氛围">维持</button>
          <button class="fp-seg-btn" :class="{ active: intent === 'distance' }" @click="setIntent('distance')" title="生成稍带距离感回复">疏远</button>
        </div>
      </div>

      <!-- Input Strip -->
      <div class="fp-input-row">
        <input
          v-model="userInput"
          type="text"
          class="fp-composer-input"
          :placeholder="llmError ? '模型异常' : '告诉 AI 下一步意图…'"
          :disabled="!!llmError || loading"
          @keydown.enter.exact.prevent="sendUserContext"
        />
        <button class="fp-btn-main act-send" :disabled="!userInput.trim() || loading || !!llmError" @click="sendUserContext">
           发送
        </button>
        <button class="fp-btn-main act-gen" :disabled="loading || !!llmError" @click="manualGenerate">
           生成
        </button>
      </div>

      <!-- Footer Info -->
      <div class="fp-composer-footer" v-if="llmModels.length > 0">
        <select v-model="activeModelId" class="fp-mini-select" @change="switchModel">
          <option v-for="m in llmModels" :key="m.id" :value="m.id" :disabled="disabledModels.has(m.id)">
            ⚙️ 模型: {{ m.name }} {{ disabledModels.has(m.id) ? '(已失效)' : '' }}
          </option>
        </select>
        <div v-if="llmError" class="fp-error-txt">{{ llmError }}</div>
      </div>
    </footer>
  </div>

  <Teleport to="body">
    <div v-if="showResumeDialog" class="fp-modal-overlay" @click.self="resolveResumeChoice('skip')">
      <div class="fp-modal">
        <h3 class="fp-modal-title">补全未监听消息</h3>
        <p class="fp-modal-desc">
          上次监听到 {{ resumeDialogState.lastMessageTime }}，距今约 {{ resumeDialogState.gapLabel }}。
        </p>
        <div class="fp-modal-box">{{ resumeDialogState.preview }}</div>
        <div class="fp-modal-actions">
          <button class="fp-btn-base ghost" @click="resolveResumeChoice('skip')">忽略</button>
          <button class="fp-btn-base primary" @click="resolveResumeChoice('backfill')">补全记录</button>
        </div>
      </div>
    </div>
    <div v-if="showProfileDialog" class="fp-modal-overlay" @click.self="showProfileDialog = false">
      <div class="fp-modal">
        <h3 class="fp-modal-title">重新生成画像</h3>
        <p class="fp-modal-desc">分析与「{{ realtimeState.talkerName }}」的聊天记录并重树特征框架。</p>
        <div class="fp-modal-actions">
          <button class="fp-btn-base ghost" @click="showProfileDialog = false">取消</button>
          <button class="fp-btn-base primary" @click="generateProfile">确认生成</button>
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
import CtAvatar from '@/components/base/CtAvatar.vue'
import { showConfirm, showDialog } from '@/utils/dialog'

const router = useRouter()

function buildMissingModelLines(modelStatus: any): string {
  const details = Array.isArray(modelStatus?.missing_details) ? modelStatus.missing_details : []
  if (!details.length) {
    return '分析模型未安装完整'
  }

  return details
    .map((item: any) => {
      const modelName = item?.model_name || item?.model_key || '未知模型'
      const issue = item?.issue || '模型不可用'
      return `- ${modelName}: ${issue}`
    })
    .join('\n')
}

async function ensureRealtimeAnalysisModelsReady(): Promise<boolean> {
  try {
    const modelStatus = await api.check_analysis_model_status()
    if (modelStatus?.ok && modelStatus?.analysis_available) {
      return true
    }

    const detailLines = buildMissingModelLines(modelStatus)
    const shouldGoAnalytics = await showConfirm({
      title: '缺少分析模型',
      message:
        `检测到当前分析模型未安装完整：\n${detailLines}\n\n` +
        '实时监听依赖情绪分析模型。请先前往“历史数据”页面，选择联系人后点击一次“开始分析”，按提示完成模型安装。\n\n' +
        '现在跳转到历史数据页面吗？',
    })

    chatError.value = '缺少分析模型，请先前往历史数据页面完成安装'

    if (shouldGoAnalytics) {
      await router.push('/analytics')
    }
    return false
  } catch (e) {
    const errorMessage = (e as any)?.message || '未知错误'
    await showDialog({
      title: '无法检查分析模型',
      message:
        `分析模型状态检查失败: ${errorMessage}\n\n` +
        '请先前往“历史数据”页面尝试开始分析；如果仍失败，再检查模型文件和 Python 依赖是否完整。',
    })
    chatError.value = '分析模型状态检查失败，请先前往历史数据页面检查安装'
    return false
  }
}

const inspectorOpen = ref(false)
const isWideMode = ref(window.innerWidth >= 820)
window.addEventListener('resize', () => { isWideMode.value = window.innerWidth >= 820 })
const inspectorTab = ref<'emotion' | 'context'>('emotion')
const showSecondaryCharts = ref(false)
watch(showSecondaryCharts, (val) => { if (val) { nextTick(() => { typeof syncCharts === 'function' && syncCharts(); typeof triggerChartResize === 'function' && triggerChartResize() }) } })
const hasSufficientEmotionData = computed(() => realtimeState.messageCount >= 4 && emotionHistory.value && emotionHistory.value.length > 2)
function triggerChartResize() {
  requestAnimationFrame(() => {
    setTimeout(() => { typeof syncCharts === 'function' && syncCharts(); typeof resizeVisibleCharts === 'function' && resizeVisibleCharts(); }, 50)
    setTimeout(() => { typeof syncCharts === 'function' && syncCharts(); typeof resizeVisibleCharts === 'function' && resizeVisibleCharts(); }, 200)
    setTimeout(() => { typeof syncCharts === 'function' && syncCharts(); typeof resizeVisibleCharts === 'function' && resizeVisibleCharts(); }, 500)
  })
}

async function closeInspector() {
  inspectorOpen.value = false
  showSecondaryCharts.value = false
  try {
    if (api && api.set_floating_expanded) await api.set_floating_expanded(false)
  } catch (e) {
    console.error(e)
  }
}

async function toggleInspector(tab: 'emotion' | 'context') {
  if (inspectorOpen.value && inspectorTab.value === tab) {
    await closeInspector()
  } else {
    inspectorOpen.value = true
    inspectorTab.value = tab
    showSecondaryCharts.value = false
    try {
      if (api && api.set_floating_expanded) await api.set_floating_expanded(true)
    } catch (e) {
      console.error(e)
    }
    if (tab === 'emotion') {
      nextTick(() => { if (typeof syncCharts === 'function') syncCharts(); typeof triggerChartResize === 'function' && triggerChartResize() })
    }
  }
}


type ChartVisibilityKey =
  | 'emotion_curve'
  | 'msg_frequency'
  | 'emotion_dist'
  | 'reply_gap'
  | 'msg_ratio'
  | 'intensity_heat'

type ChartVisibilityState = Record<ChartVisibilityKey, boolean>

type EmotionPoint = {
  time: string
  polarity: number
  sender: string
  content: string
  intensity: number
  confidence: number
  timestamp: number
}

const DEFAULT_CHART_VISIBILITY: ChartVisibilityState = {
  emotion_curve: true,
  msg_frequency: true,
  emotion_dist: false,
  reply_gap: false,
  msg_ratio: true,
  intensity_heat: false,
}

const chartConfigItems: { key: ChartVisibilityKey; label: string }[] = [
  { key: 'emotion_curve', label: '对方情绪曲线' },
  { key: 'msg_frequency', label: '消息频率' },
  { key: 'emotion_dist', label: '情绪分布' },
  { key: 'reply_gap', label: '回复间隔' },
  { key: 'msg_ratio', label: '发言比例' },
  { key: 'intensity_heat', label: '情绪强度' },
]

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
const uiaRecoverySummary = ref('')
const uiaRecoveryFinalStatus = ref('')
const uiaRecoveryActions = ref<string[]>([])
const narratorVerification = ref<any>(null)
let uiaRecoveryPromptOpen = false
let uiaRecoveryPromptSuppressed = false

const llmModels = ref<any[]>([])
const activeModelId = ref<number | null>(null)
const disabledModels = ref<Set<number>>(new Set())
const llmError = ref('')
const connectionLost = ref(false)  // 断流感知状态
let pollFailCount = 0  // 连续轮询失败计数

const processedSuggestionIds = new Set<number>()

const intent = ref<'intimate' | 'maintain' | 'distance'>('maintain')
const triggerMode = ref<'full_auto' | 'semi_auto' | 'manual'>('semi_auto')
const loading = ref(false)
const userInput = ref('')
const profile = ref<any>({ name: '', tags: [] })
const contactAvatar = ref('')
const profileLoading = ref(false)
const profileExpanded = ref(false)
const showProfileDialog = ref(false)
const emotionSummary = ref<any>(null)
const chartSettingsOpen = ref(false)
const showResumeDialog = ref(false)
const activeAccountWxid = ref('')
const resumeDialogState = reactive({
  lastMessageTime: '',
  gapLabel: '',
  preview: '',
})
let resumeDialogResolver: ((value: 'skip' | 'backfill') => void) | null = null

// 建议数据
const pendingSuggestions = ref<any[]>([])
const manualSuggestion = ref<any>(null)
const expandedIds = ref<Set<string>>(new Set(['manual']))  // 展开状态管理
const showContext = ref(false)  // 是否展示 AI 参考记录
const contextUsed = ref<{ sender: string; content: string; timestamp: number }[]>([])  // AI 参考的聊天记录

// 会话线程继承
const lastThread = ref<any>(null)

// AI 对话历史 (带有时间戳)
const conversationHistory = ref<{ role: string; content: string; ts: number }[]>([])

// 情绪历史数据（用于曲线图）
const emotionHistory = ref<EmotionPoint[]>([])

const chartVisibility = reactive<ChartVisibilityState>({ ...DEFAULT_CHART_VISIBILITY })

// ECharts 引用
const emotionChartRef = ref<HTMLElement | null>(null)
const freqChartRef = ref<HTMLElement | null>(null)
const distChartRef = ref<HTMLElement | null>(null)
const replyGapChartRef = ref<HTMLElement | null>(null)
const ratioChartRef = ref<HTMLElement | null>(null)
const intensityChartRef = ref<HTMLElement | null>(null)
const suggestionsRef = ref<HTMLElement | null>(null)
const chartInstances: Partial<Record<ChartVisibilityKey, echarts.ECharts>> = {}

// 定时器
let statusTimer: any = null
let messagesTimer: any = null
let suggestionsTimer: any = null
const START_REQUEST_KEY = 'realtime_start_request'
const RESUME_THRESHOLD_SECONDS = 300
const BACKFILL_MAX_SCROLL_ROUNDS = 80

function clearUiaRecoveryTelemetry() {
  uiaRecoverySummary.value = ''
  uiaRecoveryFinalStatus.value = ''
  uiaRecoveryActions.value = []
  narratorVerification.value = null
}

function applyUiaRecoveryTelemetry(payload: any, options: { preserveOnMissing?: boolean } = {}) {
  const preserveOnMissing = options.preserveOnMissing === true
  const hasSummary = !!payload && Object.prototype.hasOwnProperty.call(payload, 'uia_recovery_summary')
  const hasFinalStatus = !!payload && (
    Object.prototype.hasOwnProperty.call(payload, 'uia_recovery_final_status')
    || Object.prototype.hasOwnProperty.call(payload, 'final_status')
  )
  const hasActions = !!payload && Object.prototype.hasOwnProperty.call(payload, 'uia_recovery_actions')
  const hasNarratorVerification = !!payload && Object.prototype.hasOwnProperty.call(payload, 'narrator_verification')

  if (hasSummary) {
    uiaRecoverySummary.value = String(payload?.uia_recovery_summary || '').trim()
  } else if (!preserveOnMissing) {
    uiaRecoverySummary.value = ''
  }

  if (hasFinalStatus) {
    uiaRecoveryFinalStatus.value = String(
      payload?.uia_recovery_final_status || payload?.final_status || '',
    ).trim()
  } else if (!preserveOnMissing) {
    uiaRecoveryFinalStatus.value = ''
  }

  if (hasActions) {
    uiaRecoveryActions.value = Array.isArray(payload?.uia_recovery_actions)
      ? payload.uia_recovery_actions
        .map((item: any) => String(item || '').trim())
        .filter(Boolean)
      : []
  } else if (!preserveOnMissing) {
    uiaRecoveryActions.value = []
  }

  if (hasNarratorVerification) {
    narratorVerification.value = payload?.narrator_verification && typeof payload.narrator_verification === 'object'
      ? payload.narrator_verification
      : null
  } else if (!preserveOnMissing) {
    narratorVerification.value = null
  }
}

const narratorVerificationText = computed(() => {
  const info = narratorVerification.value
  if (!info || typeof info !== 'object') {
    return ''
  }
  if (info.verified === true) {
    const pid = Number(info.pid || 0)
    return pid > 0 ? `讲述人验证：已启动（PID ${pid}）` : '讲述人验证：已启动'
  }
  if (info.verified === false || info.status || info.error) {
    const detail = String(info.error || info.status || '未确认启动').trim()
    return `讲述人验证：${detail}`
  }
  return ''
})

function buildUiaRecoveryDialogMessage(baseMessage: string) {
  const lines = [String(baseMessage || '').trim()]
  if (uiaRecoverySummary.value && uiaRecoverySummary.value !== lines[0]) {
    lines.push(uiaRecoverySummary.value)
  }
  if (narratorVerificationText.value) {
    lines.push(narratorVerificationText.value)
  }
  return lines.filter(Boolean).join('\n')
}

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
  '加载中...',
])

// ========== 计算属性 ==========
const chartVisibilityStorageKey = computed(() => {
  const displayName = (realtimeState.talkerName || profile.value.name || 'default').trim() || 'default'
  const account = (activeAccountWxid.value || 'default').trim() || 'default'
  return `ct_chart_visibility:${account}:${displayName}`
})

const computedChartStats = computed(() => {
  const msgs = realtimeState.messages || []
  const friendMsgs = msgs.filter(m => m.sender_attr === 'friend')
  const selfMsgs = msgs.filter(m => m.sender_attr === 'self')

  let repliedCount = 0
  for (let i = 0; i < msgs.length; i++) {
    if (msgs[i].sender_attr !== 'self') continue
    const hasReply = msgs.slice(i + 1).some(nextMsg => nextMsg.sender_attr === 'friend')
    if (hasReply) repliedCount++
  }

  const positiveCount = friendMsgs.filter(m => Number(m.sentiment?.polarity) > 0).length
  const positiveRate = friendMsgs.length ? (positiveCount / friendMsgs.length).toFixed(2) : 'N/A'
  const replyRate = selfMsgs.length ? (repliedCount / selfMsgs.length).toFixed(2) : 'N/A'
  const msgRatio = selfMsgs.length || friendMsgs.length ? `${selfMsgs.length}:${friendMsgs.length}` : 'N/A'

  const gaps = friendMsgs
    .slice(1)
    .map((m, i) => Number(m.timestamp) - Number(friendMsgs[i].timestamp))
    .filter(gap => gap > 0 && gap < 3600)
  const avgReplyGap = gaps.length
    ? Math.round(gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length)
    : null

  return {
    reply_rate: replyRate,
    positive_rate: positiveRate,
    msg_ratio: msgRatio,
    avg_reply_gap: avgReplyGap,
    friend_msg_count: friendMsgs.length,
    self_msg_count: selfMsgs.length,
  }
})

const allSuggestions = computed(() => {
  const list: any[] = []
  const seenIds = new Set<string>()

  // 手动建议优先
  if (manualSuggestion.value) {
    if (
      manualSuggestion.value.summary !== '[PURE_CHAT]'
      && manualSuggestion.value.summary !== '[SILENT]'
      && !isPlaceholderSuggestion(manualSuggestion.value)
    ) {
      const id = manualSuggestion.value.id || 'manual'
      list.push({ ...manualSuggestion.value, id: id, _type: 'suggestion' })
      seenIds.add(String(id))
    }
  }

  // 轮询建议：跳过纯对话和静默回应，以及跳过已被手动首选加载的高亮建议的同一id
  for (const s of pendingSuggestions.value) {
    if (s.summary === '[PURE_CHAT]' || s.summary === '[SILENT]') continue
    if (isPlaceholderSuggestion(s)) continue
    if (s.id && seenIds.has(String(s.id))) continue
    if (s.id) seenIds.add(String(s.id))
    list.push({ ...s, _type: 'suggestion' })
  }

  // 对话历史
  conversationHistory.value.forEach((c, idx) => {
    list.push({ ...c, _type: 'chat', _tempId: `chat_${idx}`, created_at: c.ts })
  })

  // 按时间升序排序（旧的在上，新的在下，像聊天软件）
  list.sort((a, b) => {
    const timeA = a.created_at || Math.floor(Date.now() / 1000)
    const timeB = b.created_at || Math.floor(Date.now() / 1000)
    return timeA - timeB
  })

  return list
})

function parseSuggestionSpeeches(raw: any): string[] {
  if (Array.isArray(raw)) return raw
  if (typeof raw !== 'string') return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function isPlaceholderSuggestion(s: any): boolean {
  if (!s) return false
  const summary = String(s.summary || '').trim()
  const thought = String(s.thought_process || '').trim()
  const speeches = parseSuggestionSpeeches(s.speeches)
  const metaKeywords = ['用户', '对方', '规则', '模仿', '画像', 'JSON', 'reply', 'summary', 'thought_process', 'speeches', 'Prompt', 'prompt', '性格标签', '聊天风格', '沟通注意', '关系状态', '打字排版风格', '高频语气词汇', '常用句式模板', '模仿禁忌']

  if (summary === '...' || summary === '…') return true
  if (thought === '...' || thought === '…') return true
  if (summary.startsWith('话术应该关于')) return true
  if (thought.startsWith('thought_process:')) return true
  if (speeches.length > 0 && speeches.every((item) => /^话术\d+$/.test(String(item).trim()))) {
    return true
  }
  if (speeches.length > 0 && speeches.every((item) => {
    const text = String(item).trim()
    return text.startsWith('**') || metaKeywords.some((keyword) => text.includes(keyword))
  })) {
    return true
  }

  return false
}

function readPendingStartRequest() {
  try {
    const raw = window.sessionStorage.getItem(START_REQUEST_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function clearPendingStartRequest() {
  window.sessionStorage.removeItem(START_REQUEST_KEY)
}

function formatResumeTime(timestamp?: number) {
  if (!timestamp) return '未知时间'
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return '未知时间'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatResumeGap(gapSeconds?: number) {
  const totalSeconds = Math.max(0, Number(gapSeconds || 0))
  if (totalSeconds < 60) return `${totalSeconds} 秒`
  if (totalSeconds < 3600) return `${Math.floor(totalSeconds / 60)} 分钟`
  if (totalSeconds < 86400) return `${Math.floor(totalSeconds / 3600)} 小时`
  return `${Math.floor(totalSeconds / 86400)} 天`
}

function loadChartVisibility(displayName?: string) {
  const key = displayName?.trim()
    ? `ct_chart_visibility:${(activeAccountWxid.value || 'default').trim() || 'default'}:${displayName.trim()}`
    : chartVisibilityStorageKey.value
  try {
    const raw = window.localStorage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : null
    const nextState = { ...DEFAULT_CHART_VISIBILITY, ...(parsed || {}) }
    for (const item of chartConfigItems) {
      chartVisibility[item.key] = Boolean(nextState[item.key])
    }
  } catch {
    for (const item of chartConfigItems) {
      chartVisibility[item.key] = DEFAULT_CHART_VISIBILITY[item.key]
    }
  }
}

function persistChartVisibility() {
  try {
    window.localStorage.setItem(chartVisibilityStorageKey.value, JSON.stringify(chartVisibility))
  } catch (error) {
    console.error('保存图表设置失败:', error)
  }
}

function toggleChartVisibility(key: ChartVisibilityKey) {
  chartVisibility[key] = !chartVisibility[key]
  persistChartVisibility()
  nextTick(() => syncCharts())
}

function buildHistoricalContext() {
  return {
    profile: profile.value?.chat_style ? profile.value : undefined,
    emotion_summary: emotionSummary.value || undefined,
    chart_stats: computedChartStats.value,
  }
}

function resolveResumeChoice(choice: 'skip' | 'backfill') {
  showResumeDialog.value = false
  const resolver = resumeDialogResolver
  resumeDialogResolver = null
  resolver?.(choice)
}

async function maybeResolveResumeMode(talkerName: string): Promise<'skip' | 'backfill' | false> {
  const probe = await api.get_realtime_resume_info(
    talkerName,
    RESUME_THRESHOLD_SECONDS,
    activeAccountWxid.value || undefined,
  )
  if (!probe?.ok) {
    console.warn('[FloatingPanel] 获取回溯探测信息失败:', probe?.error || probe)
    return 'skip'
  }

  if (!probe.should_offer_resume) {
    return 'skip'
  }

  resumeDialogState.lastMessageTime = formatResumeTime(probe.last_message_timestamp)
  resumeDialogState.gapLabel = formatResumeGap(probe.gap_seconds)
  resumeDialogState.preview = String(probe.last_message_preview || '').trim() || '无预览'
  showResumeDialog.value = true

  return await new Promise<'skip' | 'backfill'>((resolve) => {
    resumeDialogResolver = resolve
  })
}

async function applyMonitoringStatus(status: any) {
  activeAccountWxid.value = status.account_wxid || activeAccountWxid.value
  realtimeState.isMonitoring = true
  realtimeState.status = 'monitoring'
  realtimeState.talkerName = status.talker_display_name || ''
  realtimeState.batchId = status.batch_id || ''
  realtimeState.messageCount = status.message_count || 0
  chatError.value = status.chat_error || ''
  applyUiaRecoveryTelemetry(status, { preserveOnMissing: true })

  startPolling()
  loadSuggestionConfig()
  loadLlmModels()
  resolveContactAvatar(realtimeState.talkerName)
  checkContactProfile(realtimeState.talkerName)
  loadChartVisibility(realtimeState.talkerName)

  try {
    const tRes = await api.get_latest_thread(realtimeState.talkerName, activeAccountWxid.value || undefined)
    if (tRes.ok && tRes.thread) {
      lastThread.value = tRes.thread
    }
  } catch (e) {
    console.error('查询历史线程失败:', e)
  }
}

async function promptAndRunUiaRecovery(talkerName: string, requestedAccountWxid = ''): Promise<boolean> {
  if (uiaRecoveryPromptOpen) {
    return false
  }
  uiaRecoveryPromptOpen = true

  try {
    const confirmed = await showConfirm({
      title: '确认自动修复',
      message: '检测到微信界面当前不可访问。继续后，程序会先尝试启动 Windows 讲述人；如果自动启动失败，会提示你手动打开讲述人。等讲述人就绪后，程序再关闭并重新打开微信。是否继续？',
    })
    if (!confirmed) {
      uiaRecoveryPromptSuppressed = true
      chatError.value = '已取消自动修复。'
      return false
    }

    uiaRecoveryPromptSuppressed = false
    clearUiaRecoveryTelemetry()
    chatError.value = '已确认自动修复，正在准备关闭微信并启动讲述人...'
    let progressTimer: number | null = window.setInterval(async () => {
      try {
        const status = await api.get_realtime_status()
        applyUiaRecoveryTelemetry(status)
        if (status?.chat_error) {
          chatError.value = status.chat_error
        }
      } catch (_e) {
        // 进度轮询失败时不打断修复流程
      }
    }, 1200)

    try {
      const result = await api.run_realtime_uia_recovery()
      applyUiaRecoveryTelemetry(result)
      if (!(result.success || result.ok)) {
        const message = result.error || '自动修复未成功完成。'
        chatError.value = message
        await showDialog({
          title: '请手动修复',
          message: buildUiaRecoveryDialogMessage(message),
        })
        return false
      }
    } finally {
      if (progressTimer !== null) {
        window.clearInterval(progressTimer)
        progressTimer = null
      }
    }

    return await startPendingMonitoring(talkerName, requestedAccountWxid, false)
  } finally {
    uiaRecoveryPromptOpen = false
  }
}

async function startPendingMonitoring(talkerName: string, requestedAccountWxid = '', allowRecoveryPrompt = true) {
  activeAccountWxid.value = requestedAccountWxid || activeAccountWxid.value
  realtimeState.talkerName = talkerName
  contactAvatar.value = ''
  realtimeState.status = 'searching'
  uiaRecoveryPromptSuppressed = false
  chatError.value = '正在准备监听对象...'

  const modelsReady = await ensureRealtimeAnalysisModelsReady()
  if (!modelsReady) {
    realtimeState.status = 'idle'
    return false
  }

  const resumeMode = await maybeResolveResumeMode(talkerName)
  if (!resumeMode) {
    return false
  }

  let progressTimer: number | null = window.setInterval(async () => {
    try {
      const status = await api.get_realtime_status()
      applyUiaRecoveryTelemetry(status)
      if (status?.chat_error) {
        chatError.value = status.chat_error
      }
    } catch (_e) {
      // 启动期间状态探测失败不打断主流程
    }
  }, 1200)

  try {
    const result = await api.start_realtime_monitor(talkerName, resumeMode, activeAccountWxid.value || undefined)
    if (!(result.success || result.ok)) {
      chatError.value = result.error || result.message || '启动监听失败'
      if (allowRecoveryPrompt && result.uia_recovery_required) {
        return await promptAndRunUiaRecovery(talkerName, requestedAccountWxid)
      }
      return false
    }

    await applyMonitoringStatus({
      ok: true,
      is_monitoring: true,
      account_wxid: activeAccountWxid.value,
      talker_display_name: talkerName,
      batch_id: result.batch_id,
      message_count: 0,
      chat_error: '',
    })
    return true
  } finally {
    if (progressTimer !== null) {
      window.clearInterval(progressTimer)
      progressTimer = null
    }
  }
}

// ========== 生命周期 ==========
onMounted(async () => {
  try {
    await bridgeReady()
    const accountResult = await api.get_wechat_accounts()
    if (accountResult?.ok) {
      activeAccountWxid.value = accountResult.active_account_wxid || ''
    }
  } catch (e) {
    console.error('[FloatingPanel] 加载微信账号上下文失败:', e)
  }

  const pendingStart = readPendingStartRequest()
  if (pendingStart?.talkerName) {
    clearPendingStartRequest()
    const started = await startPendingMonitoring(
      String(pendingStart.talkerName),
      String(pendingStart.account_wxid || activeAccountWxid.value || ''),
    )
    loadChartVisibility(String(pendingStart.talkerName))
    window.addEventListener('resize', resizeVisibleCharts)
    await nextTick()
    syncCharts()
    if (!started && !realtimeState.isMonitoring) {
      realtimeState.status = 'error'
      console.error('[FloatingPanel] 待启动监听未成功，保留悬浮页并显示错误')
    }
    return
  }
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
      applyUiaRecoveryTelemetry(status)
      if (status.ok && status.is_monitoring) {
        break
      }
      console.warn(`[FloatingPanel] 第 ${attempt + 1} 次状态检查: is_monitoring=${status?.is_monitoring}`)
    } catch (e) {
      console.error(`[FloatingPanel] 第 ${attempt + 1} 次检查失败:`, e)
    }
  }

  if (status?.ok && status.is_monitoring) {
    activeAccountWxid.value = status.account_wxid || activeAccountWxid.value
    realtimeState.isMonitoring = true
    realtimeState.status = 'monitoring'
    realtimeState.talkerName = status.talker_display_name || ''
    realtimeState.batchId = status.batch_id || ''
    realtimeState.messageCount = status.message_count || 0
    applyUiaRecoveryTelemetry(status)
    // 检查 chat_error
    if (status.chat_error) {
      chatError.value = status.chat_error
    }

    startPolling()
    loadSuggestionConfig()
    loadLlmModels()
    resolveContactAvatar(realtimeState.talkerName)
    checkContactProfile(realtimeState.talkerName)
    loadChartVisibility(realtimeState.talkerName)

    // 查询是否有上次会话线程
    try {
      const tRes = await api.get_latest_thread(realtimeState.talkerName, activeAccountWxid.value || undefined)
      if (tRes.ok && tRes.thread) {
        lastThread.value = tRes.thread
      }
    } catch (e) {
      console.error('查询历史线程失败:', e)
    }
  } else {
    // 多次重试后仍未在监听状态，退回
    console.error('[FloatingPanel] 无法恢复监听状态，退出悬浮模式')
    goBackToSuggestions()
    return
  }

  window.addEventListener('resize', resizeVisibleCharts)
  await nextTick()
  syncCharts()
})

onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener('resize', resizeVisibleCharts)
  disposeAllCharts()
  resolveResumeChoice('skip')
})

watch(() => realtimeState.talkerName, (name) => {
  if (!name) {
    contactAvatar.value = ''
    profile.value = { name: '', tags: [] }
    return
  }
  resolveContactAvatar(name)
  loadChartVisibility(name)
  nextTick(() => syncCharts())
})

watch(chartVisibilityStorageKey, () => {
  nextTick(() => syncCharts())
})

// ========== 悬浮窗控制 ==========
async function exitFloating() {
  try {
    await bridgeReady()
    // 停止监听并保存当前的对话记录
    if (realtimeState.isMonitoring) {
      // 通过 JSON 序列化反序列化可以去除 proxy 对象包装，确保传给后端的是普通对象数组
      const historyToSave = JSON.parse(JSON.stringify(conversationHistory.value))
      await api.stop_realtime_monitor(historyToSave)
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

// ========== ECharts 图表 ==========
function getChartRef(key: ChartVisibilityKey): HTMLElement | null {
  const refs: Record<ChartVisibilityKey, HTMLElement | null> = {
    emotion_curve: emotionChartRef.value,
    msg_frequency: freqChartRef.value,
    emotion_dist: distChartRef.value,
    reply_gap: replyGapChartRef.value,
    msg_ratio: ratioChartRef.value,
    intensity_heat: intensityChartRef.value,
  }
  return refs[key]
}

function getChartInstance(key: ChartVisibilityKey): echarts.ECharts | null {
  const target = getChartRef(key)
  if (!target || !chartVisibility[key]) return null
  if (!chartInstances[key]) {
    chartInstances[key] = echarts.init(target, undefined, { renderer: 'canvas' })
  }
  return chartInstances[key] || null
}

function disposeChart(key: ChartVisibilityKey) {
  if (chartInstances[key]) {
    chartInstances[key]?.dispose()
    delete chartInstances[key]
  }
}

function disposeAllCharts() {
  for (const item of chartConfigItems) {
    disposeChart(item.key)
  }
}

function resizeVisibleCharts() {
  for (const item of chartConfigItems) {
    chartInstances[item.key]?.resize()
  }
}

function buildChartBaseOption(): echarts.EChartsOption {
  return {
    grid: {
      top: 16,
      right: 12,
      bottom: 24,
      left: 34,
      containLabel: false,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e293b',
      borderColor: '#334155',
      textStyle: { color: '#f1f5f9', fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#334155' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
      axisLine: { show: false },
    },
  }
}

function buildMessageFrequencyBuckets() {
  const messages = realtimeState.messages || []
  if (!messages.length) {
    return { labels: [] as string[], values: [] as number[] }
  }

  const sortedMessages = [...messages].sort((a, b) => Number(a.timestamp) - Number(b.timestamp))
  const startTs = Number(sortedMessages[0]?.timestamp || 0)
  const endTs = Number(sortedMessages[sortedMessages.length - 1]?.timestamp || startTs)
  const span = Math.max(endTs - startTs, 1)
  const bucketCount = Math.min(12, Math.max(4, sortedMessages.length))
  const bucketSize = Math.max(60, Math.ceil(span / bucketCount))
  const counts = Array.from({ length: bucketCount }, () => 0)
  const labels = Array.from({ length: bucketCount }, (_, index) => {
    const bucketTs = startTs + index * bucketSize
    return new Date(bucketTs * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  })

  sortedMessages.forEach((message) => {
    const ts = Number(message.timestamp || startTs)
    const rawIndex = Math.floor((ts - startTs) / bucketSize)
    const bucketIndex = Math.max(0, Math.min(bucketCount - 1, rawIndex))
    counts[bucketIndex]++
  })

  return { labels, values: counts }
}

function buildReplyGapData() {
  const friendMsgs = (realtimeState.messages || []).filter(message => message.sender_attr === 'friend')
  const points = friendMsgs
    .slice(1)
    .map((message, index) => {
      const gap = Number(message.timestamp) - Number(friendMsgs[index].timestamp)
      return {
        label: new Date(Number(message.timestamp) * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        value: gap,
      }
    })
    .filter(point => point.value > 0 && point.value < 3600)

  return {
    labels: points.map(point => point.label),
    values: points.map(point => point.value),
  }
}

function syncCharts() {
  for (const item of chartConfigItems) {
    if (!chartVisibility[item.key]) {
      disposeChart(item.key)
      continue
    }

    const chart = getChartInstance(item.key)
    if (!chart) continue

    if (item.key === 'emotion_curve') {
      const times = emotionHistory.value.map(point => point.time)
      const values = emotionHistory.value.map(point => point.polarity)
      chart.setOption({
        ...buildChartBaseOption(),
        yAxis: {
          type: 'value',
          min: -1,
          max: 1,
          splitNumber: 4,
          axisLabel: { fontSize: 10, color: '#94a3b8', formatter: '{value}' },
          splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
          axisLine: { show: false },
        },
        xAxis: {
          type: 'category',
          data: times,
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          axisLine: { lineStyle: { color: '#334155' } },
          axisTick: { show: false },
        },
        tooltip: {
          trigger: 'axis',
          backgroundColor: '#1e293b',
          borderColor: '#334155',
          textStyle: { color: '#f1f5f9', fontSize: 12 },
          formatter: (params: any) => {
            const point = params[0]
            const itemData = emotionHistory.value[point.dataIndex]
            const value = Number(point.data || 0)
            const label = value > 0 ? '正面' : value < 0 ? '负面' : '中性'
            const content = itemData?.content?.length > 25 ? `${itemData.content.slice(0, 25)}…` : itemData?.content || ''
            return `<b>对方情绪</b><br/>时间：${point.name}<br/>情绪：${label} (${value.toFixed(2)})${content ? `<br/><span style="color:#94a3b8">${content}</span>` : ''}`
          },
        },
        series: [{
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: values,
          lineStyle: { width: 2.5, color: '#818cf8' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(129,140,248,0.3)' },
              { offset: 1, color: 'rgba(129,140,248,0.02)' },
            ]),
          },
          itemStyle: {
            color: (params: any) => {
              const value = Number(params.data || 0)
              if (value > 0.2) return '#34d399'
              if (value < -0.2) return '#f87171'
              return '#94a3b8'
            },
          },
        }],
      }, true)
    }

    if (item.key === 'msg_frequency') {
      const frequency = buildMessageFrequencyBuckets()
      chart.setOption({
        ...buildChartBaseOption(),
        xAxis: { ...(buildChartBaseOption().xAxis as object), data: frequency.labels },
        yAxis: { ...(buildChartBaseOption().yAxis as object), minInterval: 1 },
        series: [{
          type: 'bar',
          data: frequency.values,
          barWidth: '45%',
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: '#60a5fa',
          },
        }],
      }, true)
    }

    if (item.key === 'emotion_dist') {
      const distribution = [
        { value: emotionHistory.value.filter(point => point.polarity > 0).length, name: '正面' },
        { value: emotionHistory.value.filter(point => point.polarity === 0).length, name: '中性' },
        { value: emotionHistory.value.filter(point => point.polarity < 0).length, name: '负面' },
      ]
      chart.setOption({
        tooltip: {
          trigger: 'item',
          backgroundColor: '#1e293b',
          borderColor: '#334155',
          textStyle: { color: '#f1f5f9', fontSize: 12 },
        },
        series: [{
          type: 'pie',
          radius: ['38%', '68%'],
          center: ['50%', '54%'],
          label: { color: '#cbd5e1', fontSize: 10 },
          data: distribution,
          itemStyle: {
            borderColor: 'rgba(15,23,42,0.55)',
            borderWidth: 2,
          },
          color: ['#34d399', '#94a3b8', '#f87171'],
        }],
      }, true)
    }

    if (item.key === 'reply_gap') {
      const gapData = buildReplyGapData()
      chart.setOption({
        ...buildChartBaseOption(),
        xAxis: { ...(buildChartBaseOption().xAxis as object), data: gapData.labels },
        yAxis: {
          ...(buildChartBaseOption().yAxis as object),
          axisLabel: { fontSize: 10, color: '#94a3b8', formatter: '{value}s' },
        },
        series: [{
          type: 'line',
          data: gapData.values,
          smooth: true,
          symbolSize: 5,
          lineStyle: { width: 2, color: '#f59e0b' },
          itemStyle: { color: '#fbbf24' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(245,158,11,0.26)' },
              { offset: 1, color: 'rgba(245,158,11,0.03)' },
            ]),
          },
        }],
      }, true)
    }

    if (item.key === 'msg_ratio') {
      chart.setOption({
        tooltip: {
          trigger: 'item',
          backgroundColor: '#1e293b',
          borderColor: '#334155',
          textStyle: { color: '#f1f5f9', fontSize: 12 },
        },
        series: [{
          type: 'pie',
          radius: ['42%', '70%'],
          center: ['50%', '54%'],
          label: { color: '#cbd5e1', fontSize: 10 },
          data: [
            { value: computedChartStats.value.self_msg_count, name: '我' },
            { value: computedChartStats.value.friend_msg_count, name: '对方' },
          ],
          itemStyle: {
            borderColor: 'rgba(15,23,42,0.55)',
            borderWidth: 2,
          },
          color: ['#818cf8', '#38bdf8'],
        }],
      }, true)
    }

    if (item.key === 'intensity_heat') {
      chart.setOption({
        ...buildChartBaseOption(),
        xAxis: {
          ...(buildChartBaseOption().xAxis as object),
          data: emotionHistory.value.map(point => point.time),
        },
        yAxis: {
          type: 'value',
          min: 0,
          max: 1,
          axisLabel: { fontSize: 10, color: '#94a3b8' },
          splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } },
          axisLine: { show: false },
        },
        series: [{
          type: 'bar',
          data: emotionHistory.value.map(point => Number(point.intensity || 0)),
          barWidth: '55%',
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: (params: any) => {
              const value = Number(params.data || 0)
              if (value >= 0.75) return '#f87171'
              if (value >= 0.45) return '#fbbf24'
              return '#60a5fa'
            },
          },
        }],
      }, true)
    }
  }
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
        applyUiaRecoveryTelemetry(s)
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
        if (!s.uia_recovery_required) {
          uiaRecoveryPromptSuppressed = false
        }
        if (
          s.uia_recovery_required
          && !s.uia_recovery_in_progress
          && !uiaRecoveryPromptOpen
          && !uiaRecoveryPromptSuppressed
        ) {
          notMonitoringCount = 0
          const recovered = await promptAndRunUiaRecovery(
            realtimeState.talkerName,
            activeAccountWxid.value || '',
          )
          if (recovered) {
            return
          }
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
        updateEmotionHistory()

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
      const r = await api.get_pending_suggestions(realtimeState.batchId, activeAccountWxid.value || undefined)
      if (r.ok) {
        let addedNew = false
        const revSuggestions = [...(r.suggestions || [])].reverse()
        
        revSuggestions.forEach((s: any) => {
          if (s.id && processedSuggestionIds.has(s.id)) return
          if (s.id) processedSuggestionIds.add(s.id)
          
          if (s.summary === '[SILENT]') return
          
          addedNew = true
          // 分拣气泡与卡片
          if (s.summary === '[PURE_CHAT]') {
             if (s.reply) {
               conversationHistory.value.push({ role: 'ai', content: s.reply, ts: Math.floor(new Date(s.created_at || Date.now()).getTime()/1000) })
             }
          } else {
             const parsedSpeeches = typeof s.speeches === 'string' ? JSON.parse(s.speeches) : (s.speeches || [])
             pendingSuggestions.value.push({ ...s, speeches: parsedSpeeches, _expanded: false, _type: 'suggestion' })
             if (s.reply) {
               conversationHistory.value.push({ role: 'ai', content: s.reply, ts: Math.floor(new Date(s.created_at || Date.now()).getTime()/1000) })
             }
          }
        })
        
        emotionSummary.value = r.emotion_summary || null
        // 有新建议时自动滚底
        if (addedNew) {
          await nextTick()
          scrollToBottom()
        }
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
    .filter(msg => msg.sender_attr === 'friend' && msg.sentiment)

  const newHistory = msgs.map((msg) => {
    const date = new Date(Number(msg.timestamp) * 1000)
    return {
      time: date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      polarity: Number(msg.sentiment?.polarity || 0),
      sender: msg.sender_attr || 'friend',
      content: msg.content || '',
      intensity: Number(msg.sentiment?.intensity || 0),
      confidence: Number(msg.sentiment?.confidence || 0),
      timestamp: Number(msg.timestamp || 0),
    }
  })

  emotionHistory.value = newHistory.slice(-20)
  syncCharts()
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
      historical_context: buildHistoricalContext(),
    })
    if (r.ok && r.suggestion) {
      if (r.suggestion.reply) {
        conversationHistory.value.push({ role: 'ai', content: r.suggestion.reply, ts: Math.floor(Date.now() / 1000) })
      }
      manualSuggestion.value = r.suggestion
      // 将手动生成的卡片同步加入待处理池以将其驻留，防止下次 manual_generate 覆盖致其屏幕消失
      if (r.suggestion.summary !== '[PURE_CHAT]' && r.suggestion.summary !== '[SILENT]') {
         const parsedSpeeches = typeof r.suggestion.speeches === 'string' ? JSON.parse(r.suggestion.speeches) : (r.suggestion.speeches || [])
         pendingSuggestions.value.push({ ...r.suggestion, speeches: parsedSpeeches })
      }
      
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
    await nextTick()
    scrollToBottom()
  }
}

/** 自动滚动建议列表到底部 */
function scrollToBottom() {
  const listEl = suggestionsRef.value?.querySelector('.fp-suggestions-list')
  if (listEl) {
    listEl.scrollTop = listEl.scrollHeight
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

  conversationHistory.value.push({ role: 'user', content, ts: Math.floor(Date.now() / 1000) })
  userInput.value = ''
  loading.value = true
  __startThinkingTimer()
  llmError.value = ''

  try {
    await bridgeReady()
    const r = await api.generate_suggestion(intent.value, {
      user_context: conversationHistory.value.map(c => ({ role: c.role, content: c.content })),
      include_history: true,
      historical_context: buildHistoricalContext(),
    })
    if (r.ok && r.suggestion) {
      // 如果 AI 返回了 reply（回应用户的话），插入对话流
      if (r.suggestion.reply) {
        conversationHistory.value.push({ role: 'ai', content: r.suggestion.reply, ts: Math.floor(Date.now() / 1000) })
      }
      manualSuggestion.value = r.suggestion
      // 同步插入历史建议池
      if (r.suggestion.summary !== '[PURE_CHAT]' && r.suggestion.summary !== '[SILENT]') {
         const parsedSpeeches = typeof r.suggestion.speeches === 'string' ? JSON.parse(r.suggestion.speeches) : (r.suggestion.speeches || [])
         pendingSuggestions.value.push({ ...r.suggestion, speeches: parsedSpeeches })
      }
      
      expandedIds.value.add(String(r.suggestion.id || 'manual'))
      expandedIds.value = new Set(expandedIds.value)
    } else {
      conversationHistory.value.push({ role: 'ai', content: `[生成失败] ${r.error || '未知错误'}`, ts: Math.floor(Date.now() / 1000) })
      handleLlmError(r.error || '生成失败')
    }
    // 保存 AI 参考的聊天记录
    if (r.context_used?.recent_messages) {
      contextUsed.value = r.context_used.recent_messages
    }
  } catch (e: any) {
    console.error('发送失败:', e)
    conversationHistory.value.push({ role: 'ai', content: `[系统错误] ${e.message || '网络或接口故障'}`, ts: Math.floor(Date.now() / 1000) })
    handleLlmError(e.message || '系统错误')
  } finally {
    loading.value = false
    __stopThinkingTimer()
    // 自动滚动到底部
    await nextTick()
    scrollToBottom()
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
      applyUiaRecoveryTelemetry(s)
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
async function resolveContactAvatar(displayName: string) {
  const name = String(displayName || '').trim()
  if (!name) {
    contactAvatar.value = ''
    return
  }

  try {
    await bridgeReady()
    const result = await api.get_conversation_list(activeAccountWxid.value || undefined)
    const conversations = result?.conversations || []
    const matched = conversations.find((item: any) => {
      return item?.name === name || item?.username === name
    })
    contactAvatar.value = String(matched?.avatar || '').trim()
  } catch (e) {
    console.error('加载联系人头像失败:', e)
  }
}

async function checkContactProfile(name: string) {
  if (!name) return
  try {
    await bridgeReady()
    const r = await api.get_contact_profile(name, activeAccountWxid.value || undefined)
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
    const r = await api.generate_contact_profile(
      realtimeState.talkerName,
      'medium',
      0,
      activeAccountWxid.value || undefined,
    )
    if (r.ok && r.profile) {
      profile.value = { name: realtimeState.talkerName, ...r.profile }
    }
  } catch (e) { console.error('生成画像失败:', e) }
  finally { profileLoading.value = false }
}

// ========== 继承上次会话 ==========
async function loadLastThread() {
  if (!lastThread.value) return
  try {
    await bridgeReady()
    const r = await api.load_thread_context(lastThread.value.id)
    // 兼容后端可能返回 r.data 或 r.context
    const threadData = r.data || r.context
    if (r.ok && threadData) {
      if (threadData.suggestions && threadData.suggestions.length > 0) {
        // 分拣
        const loadedSuggs: any[] = []
        const loadedChats: any[] = []
        threadData.suggestions.forEach((s: any) => {
          if (s.id) processedSuggestionIds.add(s.id)
          if (s.summary === '[SILENT]') return
          
          if (s.summary !== '[PURE_CHAT]') {
             const parsedSpeeches = typeof s.speeches === 'string' ? JSON.parse(s.speeches) : (s.speeches || [])
             loadedSuggs.push({ ...s, speeches: parsedSpeeches, _type: 'suggestion' })
          }
        })
        
        pendingSuggestions.value = loadedSuggs
        // 直接从快照恢复完整的与 AI 聊天气泡记录
        if (threadData.user_chat_history && Array.isArray(threadData.user_chat_history)) {
          conversationHistory.value = threadData.user_chat_history
        } else {
          conversationHistory.value = []
        }
        
        if (threadData.messages && threadData.messages.length > 0) {
          contextUsed.value = threadData.messages
        }
      }
      
      // 取消横幅
      lastThread.value = null
      setTimeout(scrollToBottom, 200)
    } else {
      lastThread.value = null
      console.warn('[loadLastThread] 接口返回失败:', r)
    }
  } catch (e: any) {
    console.error('加载上次会话失败:', e)
    lastThread.value = null
  }
}
</script>

<style scoped>


/* Workbench Structural Layout */
.fp-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--ct-bg-app, #f8fafc);
  font-family: var(--ct-font-body, Inter, sans-serif);
}

/* Base states: Compact Default (Closed) */
.fp-workbench-container {
  display: grid;
  flex: 1;
  min-height: 0;
  width: 100%;
  overflow: hidden; /* Strict bound */
  grid-template-columns: 1fr;
  grid-template-rows: auto 0 1fr;
  grid-template-areas:
    "insights"
    "inspector"
    "main";
  transition: grid-template-rows 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.fp-main-column {
  display: contents; /* Grid flattening fallback */
}
.fp-insights-strip { grid-area: insights; }

.fp-main-stack { 
  grid-area: main; 
  overflow: hidden; 
  position: relative; 
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--ct-bg-tertiary);
  width: 100%;
}

.fp-composer { 
  flex-shrink: 0; 
  z-index: 10;
}

.fp-support-rail {
  grid-area: inspector;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
  display: flex !important;
  flex-direction: column;
  overflow: hidden;
  background: var(--ct-bg-app);
  border-bottom: 1px solid var(--ct-border-color);
  z-index: 5;
  min-height: 0;
}

/* 1. Narrow mode + open behavior */
@media (max-width: 819px) {
  .fp-layout.is-inspector-open .fp-workbench-container {
    grid-template-rows: auto clamp(160px, 30%, 220px) 1fr;
  }
  .fp-layout.is-inspector-open .fp-support-rail {
    opacity: 1;
    pointer-events: auto;
  }
}

/* 2. Wide mode + open behavior (Explicit Coupling) */
@media (min-width: 820px) {
  .fp-layout.is-inspector-open .fp-chart-rail {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    grid-auto-flow: row;
    overflow-x: hidden;
    overflow-y: auto;
    padding-bottom: 24px;
    height: auto;
  }

  .fp-layout.is-inspector-open .fp-workbench-container {
    display: flex;
    flex-direction: row;
    min-height: 0;
    overflow: hidden;
    flex: 1;
    width: 100%;
  }
  .fp-layout.is-inspector-open .fp-main-column {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .fp-layout.is-inspector-open .fp-main-stack { 
    flex: 1; 
    overflow: hidden; 
    position: relative; 
    min-height: 0; 
    display: flex;
    flex-direction: column;
  }
  .fp-layout.is-inspector-open .fp-insights-strip { display: none; }
  
  .fp-layout.is-inspector-open .fp-support-rail {
    flex-shrink: 0;
    width: 320px;
    border-bottom: none;
    border-left: 1px solid var(--ct-border-color);
    box-shadow: -2px 0 8px rgba(0,0,0,0.015);
    opacity: 1;
    pointer-events: auto;
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
}
/* Replaced old Workbench CSS Block fully */
/* Remove old layout */
/* Base Buttons */
.fp-btn-icon { background: transparent; border: none; cursor: pointer; color: var(--ct-text-tertiary); display: inline-flex; align-items: center; justify-content: center; padding: 4px; border-radius: var(--ct-radius-sm); transition: all 0.2s; }
.fp-btn-icon:hover { background: var(--ct-bg-secondary); color: var(--ct-text-primary); }
.fp-btn-sm { font-size: 11px; font-weight: 500; padding: 4px 10px; border-radius: var(--ct-radius-sm); background: var(--ct-color-primary-light); color: var(--ct-color-primary); border: 1px solid var(--ct-color-primary); cursor: pointer; }
.fp-btn-base { font-size: 13px; font-weight: 500; padding: 6px 14px; border-radius: var(--ct-radius-md); cursor: pointer; border: none; transition: all 0.2s; }
.fp-btn-base.primary { background: var(--ct-color-primary); color: white; }
.fp-btn-base.primary:hover { background: var(--ct-color-primary-hover); }
.fp-btn-base.ghost { background: transparent; border: 1px solid var(--ct-border-color); color: var(--ct-text-secondary); }
.fp-btn-text { font-size: 11px; font-weight: 500; color: var(--ct-color-primary); background: none; border: none; cursor: pointer; padding: 0; }
.fp-btn-text:hover { text-decoration: underline; }

/* 1. Header */
.fp-site-header { background: var(--ct-bg-elevated); border-bottom: 1px solid var(--ct-border-color); flex-shrink: 0; position: relative; z-index: 10; box-shadow: 0 1px 3px rgba(15,23,42,0.02); }
.fp-header-drag-zone { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; -webkit-app-region: drag; }
.fp-brand { display: flex; align-items: center; gap: 8px; }
.fp-status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ct-text-tertiary); }
.fp-status-dot.active { background: var(--ct-color-success); box-shadow: 0 0 6px var(--ct-color-success); }
.fp-brand-name { font-family: var(--ct-font-display); font-size: 12px; font-weight: 600; color: var(--ct-text-secondary); }
.close-btn { -webkit-app-region: no-drag; }
.fp-contact-bar { display: flex; align-items: center; gap: 10px; padding: 4px 12px 12px; -webkit-app-region: no-drag; cursor: pointer; }
.fp-avatar { background: var(--ct-bg-tertiary); color: var(--ct-color-primary); font-weight: 700; font-size: 15px; border: 1px solid var(--ct-border-color); }
.fp-contact-info { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; }
.fp-contact-name { font-size: 14px; font-weight: 600; color: var(--ct-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.2; }
.fp-contact-tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
.fp-tag { font-size: 10px; font-weight: 500; background: var(--ct-bg-tertiary); color: var(--ct-text-secondary); padding: 2px 6px; border-radius: 4px; }
.profile-toggle.is-open { transform: rotate(180deg); }

/* Absolute Profile Dropdown */
.fp-profile-dropdown { position: absolute; top: 100%; left: 0; right: 0; background: var(--ct-bg-elevated); border-bottom: 1px solid var(--ct-border-color); box-shadow: 0 8px 24px rgba(15,23,42,0.06); padding: 12px; z-index: 9; }
.all-tags { margin-bottom: 12px; }
.fp-attr { display: flex; gap: 8px; font-size: 12px; line-height: 1.5; margin-bottom: 8px; }
.fp-attr-lbl { color: var(--ct-text-primary); font-weight: 600; flex-shrink: 0; }
.fp-attr-val { color: var(--ct-text-secondary); word-break: break-word; }
.fp-profile-empty { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-top: 1px dashed var(--ct-border-color); }
.fp-txt-sub { font-size: 11px; color: var(--ct-text-tertiary); }

/* Banners */
.fp-banners { flex-shrink: 0; z-index: 8; position: relative; }
.fp-banner { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; font-size: 11px; font-weight: 500; }
.fp-banner.error { background: #fef2f2; color: #991b1b; border-bottom: 1px solid #fca5a5; }
.fp-banner.info { background: #eff6ff; color: #1d4ed8; border-bottom: 1px solid #93c5fd; }
.fp-banner-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.fp-banner-sub { font-size: 10px; color: rgba(29, 78, 216, 0.8); line-height: 1.35; word-break: break-word; }

/* 2. Insights Strip */
.fp-insights-strip { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--ct-bg-elevated); border-bottom: 1px solid var(--ct-border-color); cursor: pointer; flex-shrink: 0; transition: background 0.2s; position: relative; z-index: 7; }
.fp-insights-strip:hover { background: var(--ct-bg-secondary); }
.fp-insight-primary { display: flex; align-items: center; gap: 8px; min-width: 0; }
.fp-trend-badge { font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; }
.fp-trend-badge.positive { background: var(--ct-color-success-light); color: var(--ct-color-success); }
.fp-trend-badge.negative { background: var(--ct-color-error-light); color: var(--ct-color-error); }
.fp-trend-badge.neutral { background: var(--ct-bg-tertiary); color: var(--ct-text-secondary); }
.fp-insight-text { font-size: 11px; color: var(--ct-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fp-insight-metrics { display: flex; align-items: center; gap: 6px; }
.fp-metric-pill { font-size: 10px; color: var(--ct-text-tertiary); font-variant-numeric: tabular-nums; }
.fp-arr { font-size: 14px; color: var(--ct-text-tertiary); margin-top: -2px; font-family: monospace; transition: transform 0.2s; }
.fp-arr.arr-up { transform: rotate(-90deg); }

/* 3. SHARED INSPECTOR PANEL */
.fp-inspector { display: flex; flex-direction: column; flex: 0 0 auto; height: clamp(184px, 31%, 236px); min-height: 184px; background: var(--ct-bg-app); border-bottom: 1px solid var(--ct-border-color); box-shadow: inset 0 -4px 8px rgba(0,0,0,0.015); z-index: 5; }
.fp-inspector-header { display: flex; justify-content: space-between; align-items: center; padding: 3px 8px; border-bottom: 1px solid var(--ct-border-color); background: var(--ct-bg-elevated); gap: 6px; }
.fp-inspector-tabs { display: flex; gap: 6px; min-width: 0; }
.fp-tab-btn { background: var(--ct-bg-secondary); border: 1px solid transparent; font-size: 11px; font-weight: 600; color: var(--ct-text-secondary); cursor: pointer; padding: 2px 8px; border-radius: 4px; transition: all 0.2s; white-space: nowrap; }
.fp-tab-btn.active { color: var(--ct-color-primary); border-color: rgba(124, 77, 255, 0.2); background: rgba(124, 77, 255, 0.08); box-shadow: inset 0 0 0 1px rgba(124, 77, 255, 0.06); }
.fp-inspector-body { flex: 1; overflow-y: auto; padding: 0; background: var(--ct-bg-tertiary); display: flex; flex-direction: column; }
.fp-inspector-body::-webkit-scrollbar { width: 6px; }
.fp-inspector-body::-webkit-scrollbar-thumb { background: var(--ct-border-color-hover); border-radius: 4px; }
.fp-inspector-tab-content { display: flex; flex-direction: column; height: 100%; }

/* Chart Sub-Tab */
.compact-charts-config { display: flex; flex-wrap: nowrap; gap: 4px; padding: 4px 8px; background: var(--ct-bg-elevated); border-bottom: 1px solid var(--ct-border-color); overflow-x: auto; scrollbar-width: none; }
.compact-charts-config::-webkit-scrollbar { display: none; }
.fp-chart-toggle { display: inline-flex; align-items: center; gap: 2px; font-size: 10px; color: var(--ct-text-secondary); cursor: pointer; white-space: nowrap; padding: 2px 6px; border: 1px solid var(--ct-border-color); border-radius: 999px; background: var(--ct-bg-secondary); }
.fp-chart-stage { padding: 4px 6px 4px; }
.fp-chart-rail { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(132px, 1fr); gap: 6px; padding: 0 6px 6px; overflow-x: auto; overscroll-behavior-x: contain; }
.fp-chart-rail::-webkit-scrollbar { height: 6px; }
.fp-chart-rail::-webkit-scrollbar-thumb { background: var(--ct-border-color-hover); border-radius: 999px; }
.fp-chart-item { background: var(--ct-bg-elevated); border: 1px solid var(--ct-border-color); border-radius: var(--ct-radius-md); display: flex; flex-direction: column; box-shadow: var(--ct-shadow-sm); overflow: hidden; min-height: 0; }
.fp-chart-item.emotion-curve-main { aspect-ratio: auto; }
.fp-chart-item.compact-main { height: 124px; }
.fp-chart-item.compact-secondary { height: 108px; min-width: 132px; }
.fp-chart-lbl { font-size: 10.5px; font-weight: 600; color: var(--ct-text-secondary); padding: 8px 8px 0; flex-shrink: 0; }
.fp-chart-wrap { flex: 1; min-height: 0; padding: 2px 4px 4px; }

.compact-empty { font-size: 11px; color: var(--ct-text-tertiary); text-align: center; padding: 24px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100px; }
/* Context Sub-Tab */
.fp-context-meta { font-size: 10px; color: var(--ct-text-tertiary); padding: 4px 8px 0; text-align: left; }
.fp-context-empty { font-size: 12px; color: var(--ct-text-secondary); text-align: center; padding: 24px; }
.stream-layout { padding: 4px 8px 8px; display: flex; flex-direction: column; gap: 6px; }
.fp-ctx-msg { background: var(--ct-bg-elevated); border-radius: var(--ct-radius-sm); padding: 6px 8px; border: 1px solid var(--ct-border-color); width: 96%; align-self: flex-start; box-shadow: var(--ct-shadow-sm); }
.fp-ctx-msg.self { align-self: flex-end; background: var(--ct-color-primary-light); border-color: rgba(124, 77, 255, 0.2); }
.fp-ctx-msg-hd { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 4px; }
.fp-ctx-sender { font-size: 11px; font-weight: 600; color: var(--ct-text-secondary); }
.fp-ctx-msg.self .fp-ctx-sender { color: var(--ct-color-primary); }
.fp-ctx-time { font-size: 10px; color: var(--ct-text-tertiary); }
.fp-ctx-txt { font-size: 11px; line-height: 1.4; color: var(--ct-text-primary); word-break: break-word; white-space: pre-wrap; }

/* 5. Main Suggestion Stack */
.fp-main-stack { position: relative; min-height: 0; display: flex; flex-direction: column; background: var(--ct-bg-tertiary); overflow: hidden; }
.fp-scroll-area { flex: 1; overflow-y: auto; padding: 12px 10px; }
.fp-scroll-area::-webkit-scrollbar { width: 6px; }
.fp-scroll-area::-webkit-scrollbar-thumb { background: var(--ct-border-color-hover); border-radius: 4px; }

/* Thread Banner */
.fp-thread-banner { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--ct-bg-elevated); border: 1px solid var(--ct-border-color); border-left: 3px solid var(--ct-color-primary); border-radius: var(--ct-radius-md); margin-bottom: 12px; cursor: pointer; box-shadow: var(--ct-shadow-sm); }
.fp-thread-label { font-size: 12px; font-weight: 600; color: var(--ct-text-primary); }

/* Suggestion Cards & Chats */
.fp-empty-slate { text-align: center; padding: 32px; font-size: 12px; color: var(--ct-text-tertiary); }
.fp-sug-list { display: flex; flex-direction: column; gap: 12px; }
.fp-card { background: var(--ct-bg-elevated); border: 1px solid var(--ct-border-color); border-radius: var(--ct-radius-lg); box-shadow: var(--ct-shadow-sm); overflow: hidden; }
.fp-card.high { border-left: 3px solid var(--ct-color-error); }
.fp-card.medium { border-left: 3px solid var(--ct-color-warning); }
.fp-card.low { border-left: 3px solid var(--ct-color-success); }
.fp-card-hd { display: flex; align-items: center; gap: 8px; padding: 12px; cursor: pointer; transition: background 0.15s; }
.fp-card-hd:hover { background: var(--ct-bg-secondary); }
.fp-card-icon { font-size: 14px; flex-shrink: 0; }
.fp-card-title { font-size: 13.5px; font-weight: 600; color: var(--ct-text-primary); flex: 1; line-height: 1.4; }
.fp-card-time { font-size: 10px; color: var(--ct-text-tertiary); }
.fp-card-bd { padding: 0 12px 12px; border-top: 1px solid var(--ct-border-color); padding-top: 12px; background: var(--ct-bg-secondary); }
.fp-cot { background: var(--ct-bg-elevated); border-radius: var(--ct-radius-md); padding: 10px; margin-bottom: 12px; border: 1px solid var(--ct-border-color); }
.fp-cot summary { font-size: 11px; color: var(--ct-text-secondary); cursor: pointer; user-select: none; font-weight: 600; outline: none; }
.fp-cot-txt { font-size: 12px; line-height: 1.6; color: var(--ct-text-secondary); margin-top: 8px; border-top: 1px dashed var(--ct-border-color); padding-top: 8px; white-space: pre-wrap; }
.fp-speech-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--ct-bg-elevated); border-radius: var(--ct-radius-md); margin-bottom: 8px; border: 1px solid var(--ct-border-color); box-shadow: 0 1px 2px rgba(15,23,42,0.02); }
.fp-speech-text { font-size: 13px; line-height: 1.6; color: var(--ct-text-primary); flex: 1; }
.fp-btn-copy { font-size: 11px; font-weight: 500; color: var(--ct-text-secondary); background: var(--ct-bg-secondary); border: 1px solid var(--ct-border-color); padding: 4px 10px; border-radius: var(--ct-radius-sm); cursor: pointer; transition: all 0.2s; flex-shrink: 0; }
.fp-btn-copy:hover { color: var(--ct-color-primary); border-color: var(--ct-color-primary); background: white; box-shadow: var(--ct-shadow-sm); }

/* Chat Bubbles */
.fp-bubble { max-width: 88%; padding: 10px 14px; border-radius: 12px; align-self: flex-start; background: var(--ct-bg-elevated); border: 1px solid var(--ct-border-color); border-top-left-radius: 4px; box-shadow: var(--ct-shadow-sm); }
.fp-bubble.user { align-self: flex-end; background: var(--ct-color-primary); color: white; border: none; border-top-left-radius: 12px; border-top-right-radius: 4px; box-shadow: 0 2px 8px rgba(124, 77, 255, 0.2); }
.fp-bubble-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 16px; }
.fp-bubble-avatar { font-size: 10px; font-weight: 700; color: var(--ct-text-tertiary); background: var(--ct-bg-secondary); padding: 2px 6px; border-radius: 4px; }
.fp-bubble.user .fp-bubble-avatar { color: white; background: rgba(0,0,0,0.15); }
.fp-bubble-time { font-size: 10px; color: var(--ct-text-tertiary); opacity: 0.8; }
.fp-bubble.user .fp-bubble-time { color: rgba(255,255,255,0.8); }
.fp-bubble-txt { font-size: 14px; line-height: 1.5; word-break: break-word; white-space: pre-wrap; }

/* Loading State */
.fp-loading-state { padding: 24px; display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 12px; color: var(--ct-color-primary); font-weight: 500; }
.fp-spinner { width: 14px; height: 14px; border: 2px solid var(--ct-color-primary-light); border-top-color: var(--ct-color-primary); border-radius: 50%; animation: fp-spin 0.8s linear infinite; }
@keyframes fp-spin { to { transform: rotate(360deg); } }

/* 6. Bottom Composer */
.fp-composer { background: var(--ct-bg-elevated); border-top: 1px solid var(--ct-border-color); padding: 12px; flex-shrink: 0; position: relative; z-index: 10; box-shadow: 0 -4px 16px rgba(15,23,42,0.04); display: flex; flex-direction: column; gap: 10px; }
.fp-composer-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.fp-quick-prompts { flex: 1; display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.fp-quick-prompts::-webkit-scrollbar { display: none; }
.fp-qp-btn { font-size: 11px; font-weight: 500; padding: 4px 12px; background: var(--ct-bg-secondary); border: 1px solid var(--ct-border-color); border-radius: 12px; color: var(--ct-text-secondary); cursor: pointer; white-space: nowrap; transition: all 0.2s; }
.fp-qp-btn:hover { background: var(--ct-bg-elevated); border-color: var(--ct-color-primary); color: var(--ct-color-primary); box-shadow: var(--ct-shadow-sm); }
.fp-ctx-btn { font-size: 11px; font-weight: 600; color: var(--ct-color-primary); background: var(--ct-color-primary-light); border: none; cursor: pointer; flex-shrink: 0; padding: 4px 10px; border-radius: var(--ct-radius-sm); transition: all 0.2s; }
.fp-ctx-btn:hover { opacity: 0.9; }
.fp-ctx-btn.is-active { background: var(--ct-color-primary); color: white; }

.fp-composer-settings { display: flex; align-items: center; gap: 8px; justify-content: space-between; background: var(--ct-bg-secondary); padding: 4px; border-radius: var(--ct-radius-md); border: 1px solid var(--ct-border-color); }

.fp-seg-title { font-size: 11px; color: var(--ct-text-tertiary); font-weight: 500; margin-right: 2px; }
.fp-seg-divider { width: 1px; height: 14px; background: var(--ct-border-color); margin: 0 4px; pointer-events: none; }
.fp-seg-group { display: flex; flex: 1; padding: 2px; }
.fp-seg-btn { flex: 1; padding: 4px; border: none; background: transparent; font-size: 11px; font-weight: 500; color: var(--ct-text-secondary); border-radius: var(--ct-radius-sm); cursor: pointer; transition: all 0.2s; text-align: center; }
.fp-seg-btn.active { background: var(--ct-bg-elevated); color: var(--ct-text-primary); box-shadow: 0 1px 2px rgba(15,23,42,0.06); border: 1px solid var(--ct-border-color); }
.fp-seg-divider { width: 1px; background: var(--ct-border-color); margin: 4px 2px; }

.fp-input-row { display: flex; gap: 8px; align-items: stretch; }
.fp-composer-input { flex: 1; min-width: 0; background: var(--ct-bg-primary); border: 1px solid var(--ct-border-color); border-radius: var(--ct-radius-md); padding: 10px 12px; font-size: 13px; color: var(--ct-text-primary); outline: none; transition: border-color 0.2s; box-shadow: inset 0 1px 2px rgba(15,23,42,0.02); }
.fp-composer-input:focus { border-color: var(--ct-color-primary); box-shadow: 0 0 0 2px var(--ct-color-primary-light); }
.fp-btn-main { border: none; border-radius: var(--ct-radius-md); font-size: 13px; font-weight: 600; padding: 0 16px; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; }
.fp-btn-main:disabled { opacity: 0.5; cursor: not-allowed; }
.act-send { background: var(--ct-bg-secondary); border: 1px solid var(--ct-border-color); color: var(--ct-text-primary); padding: 0 12px; }
.act-send:hover:not(:disabled) { background: var(--ct-border-color-hover); }
.act-gen { background: var(--ct-color-primary); color: white; box-shadow: var(--ct-shadow-sm); }
.act-gen:hover:not(:disabled) { background: var(--ct-color-primary-hover); box-shadow: var(--ct-shadow-md); }

.fp-composer-footer { display: flex; align-items: center; justify-content: space-between; margin-top: -2px; }
.fp-mini-select { font-size: 10px; color: var(--ct-text-tertiary); background: transparent; border: none; outline: none; cursor: pointer; max-width: 200px; padding: 0; font-family: inherit; }
.fp-error-txt { font-size: 10px; color: var(--ct-color-error); }

/* Modals */
.fp-modal-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.5); display: flex; align-items: center; justify-content: center; z-index: 9999; backdrop-filter: blur(2px); }
.fp-modal { background: var(--ct-bg-elevated); border-radius: var(--ct-radius-lg); padding: 24px; width: 320px; box-shadow: var(--ct-shadow-xl); border: 1px solid var(--ct-border-color); }
.fp-modal-title { font-size: 16px; font-weight: 600; color: var(--ct-text-primary); margin: 0 0 8px 0; }
.fp-modal-desc { font-size: 13px; color: var(--ct-text-secondary); margin-bottom: 16px; line-height: 1.5; }
.fp-modal-box { padding: 12px; background: var(--ct-bg-secondary); border-radius: var(--ct-radius-md); font-size: 12px; color: var(--ct-text-secondary); margin-bottom: 20px; border: 1px dashed var(--ct-border-color); line-height: 1.5; word-break: break-word; }
.fp-modal-actions { display: flex; justify-content: flex-end; gap: 8px; }

/* QA Emotion Tab CSS */
.fp-emotion-summary-cards { display: flex; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--ct-border-color); background: var(--ct-bg-tertiary); }
.fp-summary-card { flex: 1; display: flex; flex-direction: column; background: var(--ct-bg-elevated); border: 1px solid var(--ct-border-color); border-radius: var(--ct-radius-md); padding: 8px 10px; box-shadow: var(--ct-shadow-sm); }
.fp-card-lbl { font-size: 10.5px; color: var(--ct-text-tertiary); margin-bottom: 3px; }
.fp-card-val { font-size: 13px; font-weight: 600; color: var(--ct-text-primary); }
.fp-card-val.positive { color: var(--ct-color-success); }
.fp-card-val.negative { color: var(--ct-color-error); }
.fp-chart-workspace { display: flex; flex-direction: column; flex: 1; min-height: 0; background: var(--ct-bg-tertiary); }
.fp-chart-header-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px 4px; }
.tiny-link { font-size: 10px; padding: 2px 6px; }
.tight-stage { padding: 4px 10px; }
.fp-secondary-charts-zone { display: flex; flex-direction: column; background: var(--ct-bg-tertiary); padding-bottom: 8px; }
.tight-config { background: transparent; border-bottom: none; padding: 6px 10px 4px; }
.tight-rail { padding: 0 10px; }
.fp-empty-icon { font-size: 24px; margin-bottom: 8px; opacity: 0.5; filter: grayscale(1); }

.fp-empty-val { font-size: 10.5px; color: var(--ct-text-tertiary); text-align: center; margin-top: 16px; opacity: 0.6; }
</style>
