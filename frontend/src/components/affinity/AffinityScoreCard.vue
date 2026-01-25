<template>
  <div class="score-card" :class="colorClass" @click="$emit('click')">
    <div class="header">
      <span class="title">{{ title }}</span>
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
}>()

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

defineEmits(['click'])
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

.title {
  font-weight: 600;
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
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
</style>
