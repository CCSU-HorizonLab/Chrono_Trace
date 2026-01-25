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
  if (p >= 70) return 'green'
  if (p >= 40) return 'yellow'
  return 'red'
})

defineEmits(['click'])
</script>

<style scoped>
.score-card {
  background: var(--card-bg, #fff);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  border: 1px solid rgba(0,0,0,0.05);
}

.score-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}

.title {
  font-weight: 600;
  font-size: 1rem;
  color: var(--text-primary, #333);
}

.score-text {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--score-color, #333);
}

.max-score {
  font-size: 0.875rem;
  color: #999;
  font-weight: 400;
}

.progress-container {
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease-out;
}

.interpretation {
  font-size: 0.875rem;
  color: #666;
  line-height: 1.4;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* Color Themes */
.score-card.green {
  --score-color: #52c41a;
}
.score-card.green .progress-bar {
  background: #52c41a;
}

.score-card.yellow {
  --score-color: #faad14;
}
.score-card.yellow .progress-bar {
  background: #faad14;
}

.score-card.red {
  --score-color: #ff4d4f;
}
.score-card.red .progress-bar {
  background: #ff4d4f;
}

/* Dark Mode Support (Basic) */
@media (prefers-color-scheme: dark) {
  .score-card {
    background: #1f1f1f;
    border-color: #333;
  }
  .title {
    color: #e0e0e0;
  }
  .progress-container {
    background: #333;
  }
  .interpretation {
    color: #aaa;
  }
}
</style>
