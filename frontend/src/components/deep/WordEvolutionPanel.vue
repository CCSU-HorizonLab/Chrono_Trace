<template>
  <div class="word-evolution card">
    <div class="panel-header">
      <div>
        <div class="panel-title">词云演变</div>
        <div class="panel-sub">把时间窗对半分成前后两段，对比你们聊得最多的词有什么不同</div>
      </div>
      <div class="perspective-group" role="group" aria-label="词云视角">
        <button
          v-for="option in perspectiveOptions"
          :key="option.value"
          class="btn perspective-btn"
          :class="{ active: perspective === option.value }"
          @click="perspective = option.value"
        >{{ option.label }}</button>
      </div>
    </div>

    <div v-if="!halves.length" class="empty">所选区间暂无文本消息</div>
    <template v-else>
      <div class="caliber-row">
        <span class="badge" :class="`badge-${evolution.caliber}`">{{ caliberLabel }}</span>
        <span class="caliber-note">{{ caliberNote }}</span>
      </div>

      <div class="halves-grid">
        <div v-for="(half, index) in halves" :key="index" class="half-col">
          <div class="half-head">
            <span class="half-tag">{{ index === 0 ? '前半段' : '后半段' }}</span>
            <span class="half-range">{{ fmtDate(half.from_ts) }} ~ {{ fmtDate(half.to_ts) }}</span>
            <span v-if="half.truncated" class="half-truncated" title="消息过多，已等距抽样前 1.5 万条">已抽样</span>
          </div>
          <div v-if="currentWords(half).length" class="half-cloud">
            <WordCloud :words="currentWords(half)" :limit="40" />
          </div>
          <div v-else class="half-empty">这段没有足够的文本</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import WordCloud from '@/components/charts/WordCloud.vue'
import { toLocalDateKey } from '@/utils/datetime'

type WordItem = { word: string; weight: number }

type Half = {
  from_ts: number
  to_ts: number
  truncated: boolean
  sampled: number
  total: number
  words: { all: WordItem[]; me: WordItem[]; other: WordItem[] }
}

const props = defineProps<{
  evolution: {
    caliber: 'cleaned' | 'raw' | 'none'
    coverage_ratio: number
    halves: Half[]
  }
}>()

const perspective = ref<'all' | 'me' | 'other'>('all')
const perspectiveOptions = [
  { value: 'all' as const, label: '双方' },
  { value: 'me' as const, label: '我' },
  { value: 'other' as const, label: 'TA' },
]

const halves = computed(() => props.evolution?.halves || [])

function currentWords(half: Half): WordItem[] {
  return half?.words?.[perspective.value] || []
}

const caliberLabel = computed(
  () => ({ cleaned: '清洗口径', raw: '原始文本口径', none: '无数据' } as Record<string, string>)[props.evolution?.caliber] || '未知口径',
)

// 口径由清洗覆盖率整窗二选一，绝不前后混用（见 docs/analysis/time-depth.md）
const caliberNote = computed(() => {
  if (props.evolution?.caliber === 'cleaned') {
    return '已用分析清洗后的文本（去表情/XML/系统消息），词更干净'
  }
  if (props.evolution?.caliber === 'raw') {
    return '该会话尚未全面分析（清洗文本覆盖率 '
      + Math.round((props.evolution?.coverage_ratio || 0) * 100)
      + '%），前后两段统一用原始消息文本，保证口径一致'
  }
  return ''
})

function fmtDate(tsSeconds: number): string {
  return toLocalDateKey(new Date(tsSeconds * 1000))
}
</script>

<style scoped>
.card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: var(--ct-space-lg);
  margin-bottom: var(--ct-space-lg);
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-md);
  flex-wrap: wrap;
}

.panel-title {
  font-size: var(--ct-text-base);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
}

.panel-sub {
  margin-top: 2px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.perspective-group {
  display: flex;
  gap: var(--ct-space-xs);
  flex-shrink: 0;
}

.btn {
  padding: 5px 12px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-surface);
  color: var(--ct-text-secondary);
  border-radius: 999px;
  cursor: pointer;
  font-size: var(--ct-text-xs);
  transition: all 0.2s ease;
}

.perspective-btn.active {
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  border-color: var(--ct-color-primary);
}

.caliber-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-md);
}

.badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--ct-text-xs);
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
  flex-shrink: 0;
}

.badge-cleaned {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.caliber-note {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.halves-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ct-space-md);
}

@media (max-width: 900px) {
  .halves-grid {
    grid-template-columns: 1fr;
  }
}

.half-col {
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  min-width: 0;
}

.half-head {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-sm);
  flex-wrap: wrap;
}

.half-tag {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.half-range {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.half-truncated {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.half-empty {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  padding: var(--ct-space-lg) 0;
  text-align: center;
}

.empty {
  color: var(--ct-text-tertiary);
  padding: var(--ct-space-xl) 0;
  text-align: center;
}
</style>
