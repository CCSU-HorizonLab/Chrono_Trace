<template>
  <div v-if="visible" class="coverage-bar">
    <template v-if="!task">
      <div class="coverage-info">
        <div class="coverage-title">
          情感数据覆盖 {{ percentText }}
          <span class="coverage-detail">（{{ coverage!.cached }}/{{ coverage!.total }} 条，缺 {{ coverage!.missing }} 条）</span>
        </div>
        <div class="coverage-desc">
          深度曲线需要逐条消息的情感打分。未分析过的会话可先补算（本地模型推理，大会话需数分钟，结果永久缓存，之后全面分析直接复用）。
        </div>
        <div v-if="startError" class="coverage-error">{{ startError }}</div>
      </div>
      <button class="btn primary" :disabled="starting" @click="start">
        {{ starting ? '启动中…' : '开始补算' }}
      </button>
    </template>

    <template v-else>
      <div class="coverage-info">
        <div class="coverage-title">
          情感补算 {{ task.progress_percent }}%
          <span class="coverage-detail">{{ task.current_step }}</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: `${task.progress_percent}%` }" />
        </div>
        <div v-if="task.status === 'failed'" class="coverage-error">
          补算失败：{{ task.error || '未知错误' }}
          <button class="btn retry" @click="retry">重试</button>
        </div>
        <div v-else class="coverage-desc">
          可随时取消；已补算的部分会保留，下次继续从缺口接着算。补算期间无法同时开始全面分析。
        </div>
      </div>
      <button
        v-if="task.status === 'running'"
        class="btn cancel"
        :disabled="cancelling"
        @click="cancel"
      >{{ cancelling ? '取消中…' : '取消' }}</button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '@/api/bridge'

type Coverage = {
  total: number
  cached: number
  missing: number
  ratio: number
  need_backfill: boolean
}

type TaskProgress = {
  status: 'running' | 'completed' | 'failed' | 'cancelled' | string
  progress_percent?: number
  current_step?: string
  error?: string | null
}

const props = defineProps<{ conversationId: number }>()
const emit = defineEmits<{ (e: 'backfilled'): void }>()

const coverage = ref<Coverage | null>(null)
const task = ref<TaskProgress | null>(null)
const taskId = ref('')
const starting = ref(false)
const cancelling = ref(false)
const startError = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const percentText = computed(() => {
  if (!coverage.value) return '-'
  return coverage.value.total ? `${Math.round(coverage.value.ratio * 100)}%` : '0%'
})

const visible = computed(() => Boolean(coverage.value?.need_backfill || task.value))

async function refreshCoverage() {
  try {
    const result = await api.get_sentiment_coverage(props.conversationId)
    if (result?.ok) coverage.value = result
  } catch {
    // 覆盖率查询失败不阻塞主内容，静默隐藏提示条
  }
}

async function start() {
  starting.value = true
  startError.value = ''
  try {
    const result = await api.start_sentiment_backfill(props.conversationId)
    if (!result?.ok) {
      startError.value = result?.error || '启动失败'
      return
    }
    if (result.status === 'started') {
      taskId.value = result.task_id
      task.value = { status: 'running', progress_percent: 0, current_step: '准备补算' }
      startPolling()
    } else {
      // status === 'complete'：无缺口，直接按已完成处理
      coverage.value = null
      emit('backfilled')
    }
  } catch (e: any) {
    startError.value = e?.message || '启动失败'
  } finally {
    starting.value = false
  }
}

function retry() {
  task.value = null
  taskId.value = ''
  start()
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (!taskId.value) return
    try {
      const progress = await api.get_sentiment_backfill_progress(taskId.value)
      if (!progress || progress.status === 'not_found') return
      task.value = progress
      if (progress.status === 'completed') {
        stopPolling()
        task.value = null
        await refreshCoverage()
        emit('backfilled')
      } else if (progress.status === 'cancelled' || progress.status === 'failed') {
        stopPolling()
        if (progress.status === 'cancelled') {
          task.value = null
          await refreshCoverage()
        }
      }
    } catch {
      // 单次轮询失败忽略，下个周期重试
    }
  }, 1500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function cancel() {
  cancelling.value = true
  try {
    await api.cancel_sentiment_backfill()
  } catch {
    // 取消请求失败时靠轮询发现终态
  } finally {
    cancelling.value = false
  }
}

watch(() => props.conversationId, () => {
  stopPolling()
  task.value = null
  taskId.value = ''
  coverage.value = null
  startError.value = ''
  refreshCoverage()
}, { immediate: true })

onUnmounted(stopPolling)
</script>

<style scoped>
.coverage-bar {
  display: flex;
  align-items: center;
  gap: var(--ct-space-lg);
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-left: 3px solid var(--ct-color-primary);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md) var(--ct-space-lg);
  margin-bottom: var(--ct-space-lg);
}

.coverage-info {
  flex: 1;
  min-width: 0;
}

.coverage-title {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.coverage-detail {
  color: var(--ct-text-secondary);
  font-weight: normal;
  font-size: var(--ct-text-xs);
}

.coverage-desc {
  margin-top: var(--ct-space-xs);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  line-height: 1.6;
}

.coverage-error {
  margin-top: var(--ct-space-xs);
  color: var(--ct-color-error, #dc2626);
  font-size: var(--ct-text-xs);
}

.progress-track {
  margin-top: var(--ct-space-sm);
  height: 6px;
  border-radius: 999px;
  background: var(--ct-bg-tertiary);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--ct-color-primary);
  transition: width 0.4s ease;
}

.btn {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-surface);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.btn.primary {
  background: var(--ct-color-primary);
  border-color: var(--ct-color-primary);
  color: #ffffff;
}

.btn.primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn.cancel {
  color: var(--ct-text-secondary);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
