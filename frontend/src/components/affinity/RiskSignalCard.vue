<template>
  <div v-if="assessment" class="risk-signal-card">
    <div class="risk-header">
      <h3 class="risk-title">风险预警</h3>
      <span class="risk-summary" :class="summaryClass">{{ summaryLabel }}</span>
    </div>
    <p class="risk-desc">
      独立于好感度总分的双向证据判定：统计条件与对话证据同时满足才「预警」，单项命中最高「留意」。
      <span v-if="!assessment.llm_evidence_available">本次未配置 AI 关系评估，各信号封顶「留意」。</span>
    </p>
    <div class="signal-list">
      <div
        v-for="(signal, key) in assessment.signals"
        :key="key"
        class="signal-item"
        :class="`signal-${signalClass(signal.level)}`"
      >
        <div class="signal-row">
          <span class="signal-label">{{ signal.label }}</span>
          <span class="signal-level" :class="`level-${signalClass(signal.level)}`">{{ signal.level }}</span>
        </div>
        <p class="signal-basis">{{ signal.stat_basis }}</p>
        <div v-if="signal.evidence && signal.evidence.length" class="signal-evidence">
          <span v-for="(quote, idx) in signal.evidence" :key="idx" class="evidence-quote">"{{ quote }}"</span>
        </div>
        <p v-if="signal.note" class="signal-note">{{ signal.note }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RiskAssessment } from '@/api/affinity'

const props = defineProps<{
  assessment: RiskAssessment | null | undefined
}>()

// 级别 → 样式类（未见异常 → normal，留意 → watch，预警 → alert）
const signalClass = (level: string): string => {
  if (level === '预警') return 'alert'
  if (level === '留意') return 'watch'
  return 'normal'
}

const summaryLabel = computed(() => {
  const level = props.assessment?.highest_level
  if (level === '预警') return '存在预警信号'
  if (level === '留意') return '有信号待留意'
  return '未见异常'
})

const summaryClass = computed(() => `summary-${signalClass(props.assessment?.highest_level || '未见异常')}`)
</script>

<style scoped>
.risk-signal-card {
  margin-top: var(--ct-space-md);
  padding: var(--ct-space-md);
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
}

.risk-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--ct-space-xs);
}

.risk-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ct-text-primary);
  padding-left: var(--ct-space-xs);
  border-left: 2px solid var(--ct-color-error);
}

.risk-summary {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--ct-radius-full);
  font-weight: 500;
}

.summary-alert {
  background: var(--ct-color-error-light);
  color: var(--ct-color-error);
}

.summary-watch {
  background: var(--ct-color-warning-light);
  color: var(--ct-color-warning);
}

.summary-normal {
  background: var(--ct-color-success-light);
  color: var(--ct-color-success);
}

.risk-desc {
  margin: 0 0 var(--ct-space-sm);
  font-size: 11px;
  line-height: 1.5;
  color: var(--ct-text-tertiary);
}

.signal-list {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xs);
}

.signal-item {
  padding: 8px 10px;
  border-radius: var(--ct-radius-sm);
  border-left: 3px solid var(--ct-border-color);
  background: var(--ct-bg-sunken);
}

.signal-alert {
  border-left-color: var(--ct-color-error);
}

.signal-watch {
  border-left-color: var(--ct-color-warning);
}

.signal-normal {
  border-left-color: var(--ct-color-success);
}

.signal-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.signal-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

.signal-level {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: var(--ct-radius-full);
  font-weight: 500;
}

.level-alert {
  background: var(--ct-color-error-light);
  color: var(--ct-color-error);
}

.level-watch {
  background: var(--ct-color-warning-light);
  color: var(--ct-color-warning);
}

.level-normal {
  background: var(--ct-color-success-light);
  color: var(--ct-color-success);
}

.signal-basis {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--ct-text-secondary);
}

.signal-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.evidence-quote {
  font-size: 11px;
  font-style: italic;
  padding: 2px 8px;
  border-radius: var(--ct-radius-sm);
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
}

.signal-note {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--ct-text-tertiary);
}
</style>
