<template>
  <div class="score-card" :class="[colorClass, { disabled: isDisabled }]" @click="handleClick">
    <div class="header">
      <div class="title-row">
        <span class="title">{{ title }}</span>
        <span
          class="weight-badge"
          :class="{
            'weight-zero': !props.isBonus && props.weight === 0,
            'bonus-badge': props.isBonus && props.bonusValue !== undefined && props.bonusValue > 0,
            'bonus-inactive': props.isBonus && (props.bonusValue === undefined || props.bonusValue <= 0),
          }"
        >
          <template v-if="props.isBonus">
            {{ props.bonusValue !== undefined && props.bonusValue > 0 ? `+${props.bonusValue.toFixed(1)} 加分` : '加分项' }}
          </template>
          <template v-else>
            {{ props.weight === 0 ? '未启用' : props.weight !== undefined ? `${Math.round(props.weight * 100)}%` : '' }}
          </template>
        </span>
      </div>
      <span class="score-text">{{ Math.round(score) }}<span class="max-score">/{{ maxScore }}</span></span>
    </div>

    <div class="progress-container">
      <div class="progress-bar" :style="{ width: percentage + '%' }"></div>
    </div>

    <div v-if="interpretation" class="interpretation-wrap">
      <div ref="interpEl" class="interpretation" :class="{ expanded: interpExpanded }">{{ interpretation }}</div>
      <div class="interp-actions">
        <button v-if="interpClamped" class="interp-btn" @click.stop="interpExpanded = !interpExpanded">
          {{ interpExpanded ? '收起' : '展开全部' }}
        </button>
        <button class="interp-btn" :class="{ copied: interpCopied }" @click.stop="handleCopy">
          {{ interpCopied ? '已复制' : '复制' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { copyText } from '@/utils/clipboard'

const props = defineProps<{
  title: string
  score: number
  maxScore: number
  interpretation?: string
  weight?: number
  disabled?: boolean
  isBonus?: boolean
  bonusValue?: number
}>()

const isDisabled = computed(() => {
  if (props.isBonus) return false
  return props.disabled || props.weight === 0
})

const percentage = computed(() => {
  return Math.min(100, Math.max(0, (props.score / props.maxScore) * 100))
})

const colorClass = computed(() => {
  const p = percentage.value
  if (p >= 80) return 'green'
  if (p >= 60) return 'blue'
  if (p >= 40) return 'yellow'
  return 'red'
})

const emit = defineEmits(['click', 'disabled-click'])

const interpEl = ref<HTMLElement | null>(null)
const interpExpanded = ref(false)
const interpClamped = ref(false)
const interpCopied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null

// 折行截断检测：line-clamp 下 scrollHeight 仍是全文高度
const detectClamp = async () => {
  await nextTick()
  const el = interpEl.value
  if (!el || el.clientHeight === 0) return // 尚未布局（tab 隐藏等），保留旧判定
  interpClamped.value = el.scrollHeight > el.clientHeight + 2
}

// 卡片可能在未布局时测过一次（tab 隐藏/字体未就绪），尺寸变化后重测；
// 展开态不重测，避免展开后被误收回
let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  void detectClamp()
  if (typeof ResizeObserver !== 'undefined' && interpEl.value) {
    resizeObserver = new ResizeObserver(() => {
      if (!interpExpanded.value) void detectClamp()
    })
    resizeObserver.observe(interpEl.value)
  }
})
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (copyTimer) clearTimeout(copyTimer)
})
watch(() => props.interpretation, () => {
  interpExpanded.value = false
  void detectClamp()
})

const handleCopy = () => {
  if (!copyText(props.interpretation || '')) return
  interpCopied.value = true
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { interpCopied.value = false }, 2000)
}

const handleClick = () => {
  if (isDisabled.value) {
    emit('disabled-click')
  } else {
    emit('click')
  }
}
</script>

<style scoped>
.score-card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: 1.5rem;
  box-shadow: var(--ct-shadow-sm);
  cursor: pointer;
  transition: transform var(--ct-transition-fast), box-shadow var(--ct-transition-fast);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.score-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--ct-shadow-md);
  border-color: var(--ct-border-color-hover);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--ct-space-lg);
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
}

.title {
  font-weight: 700;
  font-size: var(--ct-text-base);
  color: var(--ct-text-primary);
}

.weight-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: var(--ct-radius-full);
  font-size: 0.75rem;
  font-weight: 600;
  background: #3b82f6;
  color: white;
  border: 2px solid #2563eb;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  margin-left: 8px;
}

.weight-badge.weight-zero {
  background: #6b7280;
  border-color: #4b5563;
  opacity: 0.9;
}

.weight-badge.bonus-badge {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  border-color: #b45309;
  color: white;
}

.weight-badge.bonus-inactive {
  background: #6b7280;
  border-color: #4b5563;
  opacity: 0.9;
}

.score-text {
  font-size: 2rem;
  font-weight: 700;
  color: var(--score-color);
  font-family: var(--ct-font-display);
  line-height: 1;
}

.max-score {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  font-weight: 400;
  margin-left: 2px;
}

.progress-container {
  height: 8px;
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-full);
  overflow: hidden;
  margin-bottom: var(--ct-space-lg);
}

.progress-bar {
  height: 100%;
  border-radius: var(--ct-radius-full);
  background: var(--score-color);
  transition: width 0.5s ease-out;
}

.interpretation-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xs);
}

.interpretation {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: var(--ct-leading-normal);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  user-select: text;
  -webkit-user-select: text;
}

.interpretation.expanded {
  display: block;
  -webkit-line-clamp: none;
}

.interp-actions {
  display: flex;
  gap: var(--ct-space-sm);
}

.interp-btn {
  align-self: flex-start;
  background: none;
  border: none;
  padding: 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  cursor: pointer;
}

.interp-btn:hover {
  color: var(--ct-color-primary);
}

.interp-btn.copied {
  color: var(--ct-color-success);
}

.score-card.green { --score-color: var(--ct-color-success); }
.score-card.blue { --score-color: var(--ct-color-info); }
.score-card.yellow { --score-color: var(--ct-color-warning); }
.score-card.red { --score-color: var(--ct-color-error); }

.score-card.disabled {
  opacity: 0.6;
  background: var(--ct-bg-secondary);
  cursor: not-allowed;
}

.score-card.disabled:hover {
  transform: none;
  box-shadow: var(--ct-shadow-sm);
  border-color: var(--ct-border-color);
}

.score-card.disabled .score-text,
.score-card.disabled .title {
  color: var(--ct-text-tertiary);
}
</style>
