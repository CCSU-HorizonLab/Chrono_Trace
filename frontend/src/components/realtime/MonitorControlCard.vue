<template>
  <section class="mcc-wrap">
    <!-- 监听控制卡 -->
    <div class="mcc-grid">
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
            <summary><AlertTriangle :size="14" style="vertical-align: -2px; margin-right: 4px; color: var(--ct-color-warning);" /> 使用须知</summary>
            <ul>
              <li>确保 Windows 微信已启动并登录。</li>
              <li><strong>无需强制前台</strong>：窗口允许被其他应用遮挡（但请勿彻底最小化至任务栏）。</li>
              <li>目标对象的昵称必须与微信中显示完全一致（如有备注名，必须输入备注名）。</li>
              <li>当前系统全局仅支持对单一对象进行并行监听。</li>
              <li>需使用微信 4.x 版本（3.9 及更早版本的数据目录不受支持，应用会引导升级）。</li>
              <li>请监听时不要切换聊天对象，否则会影响监听效果。</li>
            </ul>
          </details>

          <!-- 操作行：选人在工作台页头，这里只读展示当前对象 -->
          <div class="sug-action-row">
            <div class="sug-picker-group">
              <label class="sug-label">{{ realtimeState.isMonitoring ? '正在监听' : '监听对象' }}</label>
              <div class="sug-target-name">
                {{ realtimeState.isMonitoring ? (monitorTalkerName || contactName) : (contactName || '未选择（请在页头选择联系人）') }}
              </div>
            </div>
            <button
              class="sug-monitor-btn"
              :class="{ stop: realtimeState.isMonitoring }"
              :disabled="!contactName || realtimeState.status === 'searching' || realtimeState.status === 'stopping'"
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

      <!-- 建议配置卡（按联系人存储） -->
      <div class="sug-panel">
        <div class="sug-panel-accent accent-amber"></div>
        <div class="sug-panel-hd">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
          <span>建议配置</span>
        </div>
        <div class="sug-panel-bd sug-config-body">
          <div class="sug-config-head">当前对象：{{ contactName || '未选择' }}</div>
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
              <button :class="{ active: intent === 'intimate' }" @click="setIntent('intimate')"><span class="sug-intent-icon"><Flame :size="14" /></span>亲近</button>
              <button :class="{ active: intent === 'maintain' }" @click="setIntent('maintain')"><span class="sug-intent-icon"><Scale :size="14" /></span>维持</button>
              <button :class="{ active: intent === 'distance' }" @click="setIntent('distance')"><span class="sug-intent-icon"><Snowflake :size="14" /></span>疏远</button>
            </div>
          </div>
          <p class="sug-config-note">配置按联系人独立保存，会同步到悬浮窗，并用于自动触发或悬浮窗内的手动生成。</p>
        </div>
      </div>
    </div>

    <!-- LLM 未激活提示弹窗 -->
    <Teleport to="body">
      <div v-if="showLlmWarningDialog" class="ct-modal-overlay" @click.self="showLlmWarningDialog = false">
        <div class="ct-modal-dialog">
          <div class="modal-title" style="display: flex; align-items: center; gap: 8px;">
            <AlertTriangle :size="20" style="color: var(--ct-color-warning);" />
            <span>尚未配置大模型</span>
          </div>
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
  </section>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { AlertTriangle, Flame, Scale, Snowflake } from 'lucide-vue-next'
import { bridgeReady, api } from '@/api/bridge'
import { safeRemoveItem, safeSetItem } from '@/utils/safeStorage'
import CtButton from '@/components/base/CtButton.vue'
import { showConfirm, showDialog } from '@/utils/dialog'

// 对象工作台：选人在页头 FiltersBar 一次贯通，本卡只接收当前对象
const props = defineProps<{
  conversationId: number | null
  contactName: string
  accountWxid: string
}>()

const router = useRouter()

// ========== 实时监听状态 ==========
const monitorPanelExpanded = ref(true)

const realtimeState = reactive({
  isMonitoring: false,
  batchId: '',
  messageCount: 0,
  status: 'idle' as 'idle' | 'searching' | 'loading_model' | 'monitoring' | 'stopping' | 'stopped'
})

// 后端正在监听的对象（可能与页头选中不同——监听不随选人切换）
const monitorTalkerName = ref('')
const realtimeError = ref('')
let statusTimer: any = null

// ========== AI 建议配置（按联系人存储） ==========
const triggerMode = ref<any>('semi_auto')
const intent = ref<any>('maintain')
const showLlmWarningDialog = ref(false)

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

function toggleMonitorPanel() {
  monitorPanelExpanded.value = !monitorPanelExpanded.value
}

async function toggleMonitoring() {
  if (realtimeState.isMonitoring) {
    await stopMonitoring()
  } else {
    await startMonitoring()
  }
}

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

async function ensureRealtimeAnalysisModelsReadyBeforeFloating(): Promise<boolean> {
  try {
    const modelStatus = await api.check_analysis_model_status()
    if (modelStatus?.ok && modelStatus?.analysis_available) {
      return true
    }

    const detailLines = buildMissingModelLines(modelStatus)
    await showConfirm({
      title: '缺少分析模型',
      message:
        `检测到当前分析模型未安装完整：\n${detailLines}\n\n` +
        '进入实时监听前，请先在本页（关系洞察）点击一次「开始全面分析」，按提示完成模型安装。',
    })

    realtimeError.value = '缺少分析模型，请先在关系洞察完成一次全面分析'

    return false
  } catch (e) {
    const errorMessage = (e as any)?.message || '未知错误'
    await showDialog({
      title: '无法检查分析模型',
      message:
        `分析模型状态检查失败: ${errorMessage}\n\n` +
        '请先在关系洞察尝试开始分析；如果仍失败，再检查模型文件和 Python 依赖是否完整。',
    })
    realtimeError.value = '分析模型状态检查失败，请先完成一次全面分析'
    return false
  }
}

function goToSettings() {
  showLlmWarningDialog.value = false
  router.push('/settings')
}

// 启动监听：真正启动在悬浮窗，这里只写请求 + 进入悬浮模式
async function startMonitoring() {
  const talkerName = props.contactName.trim()

  if (!talkerName) {
    realtimeError.value = '请先在页头选择监听对象'
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

    const modelsReady = await ensureRealtimeAnalysisModelsReadyBeforeFloating()
    if (!modelsReady) {
      realtimeState.status = 'idle'
      return
    }

    safeSetItem('realtime_start_request', JSON.stringify({
      talkerName,
      account_wxid: props.accountWxid || undefined,
      createdAt: Date.now(),
    }), window.sessionStorage)

    try {
      await api.enter_floating_mode()
      router.push('/floating')
      return
    } catch (e) {
      safeRemoveItem('realtime_start_request', window.sessionStorage)
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

// ========== 建议配置（按联系人存储：conversation_id 维度） ==========

async function loadSuggestionConfig() {
  try {
    const r = await api.get_suggestion_config(props.conversationId || undefined)
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
    await api.set_suggestion_config({ trigger_mode: mode }, props.conversationId || undefined)
  } catch (e) {
    console.error('设置触发模式失败:', e)
  }
}

async function setIntent(newIntent: string) {
  intent.value = newIntent as any
  try {
    await api.set_suggestion_config({ intent: newIntent }, props.conversationId || undefined)
  } catch (e) {
    console.error('设置走向失败:', e)
  }
}

// 切换联系人时配置跟随当前对象
watch(() => props.conversationId, () => {
  loadSuggestionConfig()
})

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

// 组件挂载时恢复监听状态（悬浮窗退出返回本页时保持一致）
onMounted(async () => {
  loadSuggestionConfig()

  try {
    await bridgeReady()
    const status = await api.get_realtime_status()

    if (status.ok && status.is_monitoring) {
      realtimeState.isMonitoring = true
      realtimeState.status = 'monitoring'
      monitorTalkerName.value = status.talker_display_name || ''
      realtimeState.batchId = status.batch_id || ''
      realtimeState.messageCount = status.message_count || 0
      startStatusPolling()
    }
  } catch (e) {
    console.error('恢复监听状态失败:', e)
  }
})

onBeforeUnmount(() => {
  stopStatusPolling()
})
</script>

<style scoped>
.mcc-wrap { display: flex; flex-direction: column; }
.mcc-grid {
  display: grid; grid-template-columns: 2fr 1fr; gap: var(--ct-space-lg);
  align-items: start;
}
@media (max-width: 1024px) { .mcc-grid { grid-template-columns: 1fr; } }

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
.sug-picker-group { flex: 1; display: flex; flex-direction: column; gap: var(--ct-space-xs); min-width: 0; }
.sug-label {
  font-size: var(--ct-text-xs); font-weight: 600; color: var(--ct-text-secondary);
  text-transform: uppercase; letter-spacing: 0.06em;
}
.sug-target-name {
  font-size: var(--ct-text-base); font-weight: 600; color: var(--ct-text-primary);
  padding: 9px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sug-target-name:disabled { opacity: 0.5; }

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

/* ═══ 建议配置卡 ═══ */
.sug-panel {
  position: relative; background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color); border-radius: var(--ct-radius-xl);
  overflow: hidden; display: flex; flex-direction: column;
  transition: transform var(--ct-transition-normal) var(--ct-ease-out),
              box-shadow var(--ct-transition-normal) var(--ct-ease-out),
              border-color var(--ct-transition-normal);
}
.sug-panel:hover { transform: translateY(-3px); box-shadow: var(--ct-shadow-lg); border-color: var(--ct-border-color-hover); }

.sug-panel-accent { height: 3px; width: 100%; flex-shrink: 0; }
.accent-amber { background: linear-gradient(90deg, #f59e0b, #f97316); }

.sug-panel-hd {
  display: flex; align-items: center; gap: var(--ct-space-sm);
  padding: var(--ct-space-md) var(--ct-space-lg); font-weight: 600;
  font-size: var(--ct-text-sm); color: var(--ct-text-primary);
  border-bottom: 1px solid var(--ct-border-color);
}
.sug-panel-hd svg { color: var(--ct-text-tertiary); }
.sug-panel-bd { padding: var(--ct-space-lg); flex: 1; display: flex; flex-direction: column; }

.sug-config-body { gap: var(--ct-space-md); }
.sug-config-head {
  font-size: var(--ct-text-sm); font-weight: 600; color: var(--ct-text-primary);
  padding: var(--ct-space-xs) var(--ct-space-sm);
  background: var(--ct-bg-secondary); border-radius: var(--ct-radius-md);
}
.sug-config-group { display: flex; flex-direction: column; gap: var(--ct-space-xs); }
.sug-seg { display: flex; border-radius: var(--ct-radius-md); overflow: hidden; border: 1px solid var(--ct-border-color); }
.sug-seg button {
  flex: 1; padding: var(--ct-space-sm); border: none;
  background: var(--ct-bg-elevated); color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs); font-weight: 500; cursor: pointer;
  transition: all var(--ct-transition-fast);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.sug-seg button:not(:last-child) { border-right: 1px solid var(--ct-border-color); }
.sug-seg button.active { background: var(--ct-color-primary); color: white; font-weight: 600; }
.sug-seg button:hover:not(.active) { background: var(--ct-bg-tertiary); }
.sug-intent-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 2px;
}
.sug-config-note {
  margin: 0;
  padding: var(--ct-space-sm) var(--ct-space-md);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-secondary);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  line-height: 1.6;
}

/* 弹窗描述文案（配合全局 ct-modal-dialog） */
.modal-desc {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: 1.6;
}

@media (max-width: 768px) {
  .sug-action-row { flex-direction: column; align-items: stretch; }
}
</style>
