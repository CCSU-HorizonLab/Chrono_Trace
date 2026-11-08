<template>
  <!-- 年度报告/纪念册工坊（§6.2 传播产线）：时光页年份轴/框选区间唤起。
       模板组走 REPORT_TEMPLATES（公开版经投影消费），导出链与海报共用 -->
  <div class="report-studio-overlay" @click.self="emit('close')">
    <div class="report-studio" role="dialog" aria-modal="true">
      <header class="rs-head">
        <div class="rs-title-wrap">
          <h3 class="rs-title">{{ title }}</h3>
          <p class="rs-sub">{{ contactName || '联系人' }} · {{ from }} ~ {{ to }}</p>
        </div>
        <button class="rs-close" title="关闭" @click="emit('close')">✕</button>
      </header>

      <div class="rs-body">
        <div v-if="loading" class="rs-state">正在翻这段时光…</div>
        <div v-else-if="error" class="rs-state rs-state-error">
          <span>{{ error }}</span>
          <button class="btn" @click="load">重试</button>
        </div>
        <template v-else-if="payload">
          <div class="rs-template-row">
            <button
              v-for="template in templates"
              :key="template.id"
              class="rs-template"
              :class="{ active: activeId === template.id, sensitive: template.sensitive }"
              @click="activeId = template.id"
            >
              <span class="rs-template-label">{{ template.label }}</span>
              <span class="rs-template-desc">{{ template.description }}</span>
            </button>
          </div>

          <div class="rs-preview">
            <div ref="posterRef" class="rs-holder">
              <component :is="activeTemplate.component" :payload="payload as any" />
            </div>
          </div>
        </template>
      </div>

      <footer class="rs-foot">
        <button class="btn primary" :disabled="exporting || !payload" @click="exportImage">
          {{ exporting ? '正在合成长图…' : '导出长图' }}
        </button>
        <span v-if="exportResultText" class="rs-result">{{ exportResultText }}</span>
        <span v-else-if="exportError" class="rs-error">{{ exportError }}</span>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 报告工坊：按窗口拉 get_report_payload → 双模板（公开/定向）预览 →
 * html2canvas 导出长图。定向版含对方姓名/头像，导出前确认（同海报守则）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api/bridge'
import { showConfirm } from '@/utils/dialog'
import { toLocalDateKey } from '@/utils/datetime'
import { exportNodeAsPng } from '@/components/deep/poster/exportNode'
import {
  REPORT_TEMPLATES,
  type IntimateReportPayload,
} from '@/components/deep/poster/registry'

const props = defineProps<{
  conversationId: number
  contactName?: string
  from: string
  to: string
  kind: 'year' | 'album'
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const payload = ref<IntimateReportPayload | null>(null)
const loading = ref(false)
const error = ref('')
const activeId = ref(REPORT_TEMPLATES[0].id)
const exporting = ref(false)
const exportResultText = ref('')
const exportError = ref('')
const posterRef = ref<HTMLElement | null>(null)

const templates = REPORT_TEMPLATES
const activeTemplate = computed(
  () => REPORT_TEMPLATES.find((t) => t.id === activeId.value) || REPORT_TEMPLATES[0],
)

const title = computed(() => {
  const year = props.from.slice(0, 4)
  return props.kind === 'year' ? `年度报告 · 我们的 ${year}` : '纪念册'
})

async function load() {
  const requestKey = `${props.conversationId}|${props.from}|${props.to}`
  loading.value = true
  error.value = ''
  exportResultText.value = ''
  exportError.value = ''
  try {
    const result = await api.get_report_payload(props.conversationId, props.from, props.to)
    if (requestKey !== `${props.conversationId}|${props.from}|${props.to}`) return
    if (!result?.ok) {
      error.value = result?.error || '加载失败'
      payload.value = null
      return
    }
    payload.value = result
  } catch (e: any) {
    if (requestKey !== `${props.conversationId}|${props.from}|${props.to}`) return
    error.value = e?.message || '请求失败'
  } finally {
    loading.value = false
  }
}

async function exportImage() {
  const node = posterRef.value
  if (!node || exporting.value) return
  if (activeTemplate.value.sensitive) {
    const confirmed = await showConfirm(
      '定向版包含对方姓名与头像，请确认仅发送给对方本人。',
    )
    if (!confirmed) return
  }
  exporting.value = true
  exportError.value = ''
  exportResultText.value = ''
  try {
    const label = props.kind === 'year' ? `年度报告${props.from.slice(0, 4)}` : '纪念册'
    const name = `时痕${label}_${props.contactName || ''}_${toLocalDateKey(new Date())}.png`
    const result = await exportNodeAsPng(node, name)
    if (!result.ok) {
      exportError.value = result.error
      return
    }
    exportResultText.value = result.copied
      ? `已复制到剪贴板，可直接粘贴发送（文件在 ${result.file_path}）`
      : `已保存到 ${result.file_path}`
    api.open_export_folder().catch(() => {})
  } finally {
    exporting.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  void load()
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
/* 工坊外壳走主题令牌（海报模板节点在 rs-holder 内自担海报纪律） */
.report-studio-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(27, 25, 36, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.report-studio {
  width: min(820px, 100%);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-lg);
  overflow: hidden;
}

.rs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--ct-border-color);
}

.rs-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.rs-title {
  margin: 0;
  font-size: var(--ct-text-base);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
}

.rs-sub {
  margin: 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
}

.rs-close {
  flex: none;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: var(--ct-radius-sm);
  background: transparent;
  color: var(--ct-text-tertiary);
  cursor: pointer;
  transition: background-color var(--ct-transition-fast) var(--ct-ease-out),
    color var(--ct-transition-fast) var(--ct-ease-out);
}

.rs-close:hover {
  background: var(--ct-bg-hover);
  color: var(--ct-text-primary);
}

.rs-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 14px 20px 0;
}

.rs-state {
  padding: 40px 0;
  text-align: center;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.rs-state-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--ct-space-md);
  color: var(--ct-color-error);
}

.rs-template-row {
  display: flex;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-md);
}

.rs-template {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  padding: 10px 14px;
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  cursor: pointer;
  transition: background-color 0.2s ease, border-color 0.2s ease;
}

.rs-template.active {
  background: var(--ct-color-primary-tint);
  border-color: var(--ct-color-primary);
}

.rs-template-label {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.rs-template.sensitive .rs-template-label::after {
  content: '仅给对方';
  margin-left: 6px;
  font-size: 10px;
  color: #8F5B14;
  background: var(--ct-color-warning-tint);
  border-radius: 999px;
  padding: 1px 6px;
}

.rs-template-desc {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  line-height: 1.5;
}

.rs-preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm);
}

.rs-holder {
  width: 720px;
  max-width: 100%;
  margin: 0 auto;
}

.rs-foot {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
  padding: 12px 20px 16px;
}

.rs-result {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  word-break: break-all;
}

.rs-error {
  color: var(--ct-color-error);
  font-size: var(--ct-text-xs);
}
</style>
