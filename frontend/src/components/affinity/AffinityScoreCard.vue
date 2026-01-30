<template>
  <div class="score-card" :class="[colorClass, { disabled: isDisabled }]" @click="handleClick">
    <div class="header">
      <div class="title-row">
        <span class="title">{{ title }}</span>
        <!-- 测试: 强制显示徽章 -->
        <span class="weight-badge" :class="{ 'weight-zero': weight === 0 }">
          {{ weight === 0 ? '未启用' : weight !== undefined ? `${Math.round(weight * 100)}%` : '无weight' }}
        </span>
      </div>
      <span class="score-text">{{ Math.round(score) }}<span class="max-score">/{{ maxScore }}</span></span>
    </div>
    
    <div class="progress-container">
      <div class="progress-bar" :style="{ width: percentage + '%' }"></div>
    </div>
    
    <div class="interpretation" v-if="interpretation">
      {{ interpretation }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  score: number
  maxScore: number
  interpretation?: string
  weight?: number  // 维度权重 (0-1)
  disabled?: boolean  // 是否禁用状态
}>()

const isDisabled = computed(() => {
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
  padding: var(--ct-space-lg);
  box-shadow: var(--ct-shadow-sm);
  cursor: pointer;
  transition: transform var(--ct-transition-fast), box-shadow var(--ct-transition-fast);
}

.score-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--ct-shadow-md);
  border-color: var(--ct-border-color-hover);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--ct-space-md);
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
}

.title {
  font-weight: 600;
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
}

.weight-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: var(--ct-radius-full);
  font-size: 0.7rem;
  font-weight: 600;
  /* 使用明确的颜色而不是CSS变量 */
  background: #3b82f6;  /* 明亮的蓝色 */
  color: white;
  border: 2px solid #2563eb;  /* 深蓝色边框 */
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  margin-left: 6px;
}

.weight-badge.weight-zero {
  background: #6b7280;  /* 灰色 */
  border-color: #4b5563;
  opacity: 0.9;
}

.score-text {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--score-color);
  font-family: var(--ct-font-display);
}

.max-score {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  font-weight: 400;
  margin-left: 2px;
}

.progress-container {
  height: 6px;
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-full);
  overflow: hidden;
  margin-bottom: var(--ct-space-md);
}

.progress-bar {
  height: 100%;
  border-radius: var(--ct-radius-full);
  background: var(--score-color);
  transition: width 0.5s ease-out;
}

.interpretation {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  line-height: var(--ct-leading-normal);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* Color Themes */
.score-card.green { --score-color: var(--ct-color-success); }
.score-card.blue { --score-color: var(--ct-color-info); }
.score-card.yellow { --score-color: var(--ct-color-warning); }
.score-card.red { --score-color: var(--ct-color-error); }

/* Disabled State */
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
