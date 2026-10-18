<template>
  <div class="deep-emotion card">
    <div class="panel-header">
      <div>
        <div class="panel-title">情绪演变</div>
        <div class="panel-sub">按{{ granularityLabel }}聚合双方情感分（-1 压抑 ~ +1 轻松），可切换只看自己或只看 TA</div>
      </div>
      <div class="perspective-group" role="group" aria-label="视角">
        <button
          v-for="option in perspectiveOptions"
          :key="option.value"
          class="btn perspective-btn"
          :class="{ active: perspective === option.value }"
          @click="perspective = option.value"
        >{{ option.label }}</button>
      </div>
    </div>

    <div v-if="!buckets.length" class="empty">所选区间暂无消息</div>
    <template v-else>
      <EmotionLineChart
        :timeseries="buckets"
        :perspective="perspective"
        :negative-shade="true"
        :affinity-points="affinityMarks"
        :unit-label="unitLabel"
      />
      <div class="chart-notes">
        <span v-for="note in notes" :key="note" class="chart-note">{{ note }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import EmotionLineChart from '@/components/charts/EmotionLineChart.vue'
import { toLocalDateKey } from '@/utils/datetime'

type Bucket = {
  ts: string
  score: number | null
  userScore?: number | null
  otherScore?: number | null
  msgCount?: number
  coverage?: number | null
  lowConfidence?: boolean
  [key: string]: any
}

type AffinityHistory = {
  caliber_version: number
  note?: string
  points: Array<{ ts: number; score: number }>
} | null

const props = defineProps<{
  buckets: Bucket[]
  granularity: string
  affinity: AffinityHistory
}>()

const perspective = ref<'both' | 'me' | 'other'>('both')
const perspectiveOptions = [
  { value: 'both' as const, label: '双方' },
  { value: 'me' as const, label: '我' },
  { value: 'other' as const, label: 'TA' },
]

const granularityLabel = computed(
  () => ({ week: '周', month: '月', year: '年', day: '天' } as Record<string, string>)[props.granularity] || props.granularity,
)
const unitLabel = computed(
  () => ({ week: '当周', month: '当月', year: '当年', day: '当天' } as Record<string, string>)[props.granularity] || '当期',
)

// 秒级时间戳 → 当前粒度的桶标签（与后端 sentiment_bucket_expr 同口径：周=周一日期，月=YYYY-MM，年=YYYY）
function bucketLabelForTs(tsSeconds: number): string {
  const d = new Date(tsSeconds * 1000)
  if (props.granularity === 'month') {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  }
  if (props.granularity === 'year') {
    return String(d.getFullYear())
  }
  // 周（默认）与天：落到所在周的周一
  const monday = new Date(d)
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return toLocalDateKey(monday)
}

const affinityMarks = computed(() => {
  if (!props.affinity?.points?.length) return []
  return props.affinity.points.map((point) => ({
    ts: bucketLabelForTs(point.ts),
    score: point.score,
  }))
})

const notes = computed(() => {
  const list: string[] = ['浅红区块为情绪偏低的时段']
  list.push('灰底列表示该' + unitLabel.value + '缺情感数据，分数仅供参考')
  if (affinityMarks.value.length) {
    list.push(props.affinity?.note || '好感度为全面分析完成时的落点，非每日快照')
  }
  return list
})
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

.chart-notes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-md);
  margin-top: var(--ct-space-sm);
}

.chart-note {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.chart-note::before {
  content: '·';
  margin-right: 4px;
}

.empty {
  color: var(--ct-text-tertiary);
  padding: var(--ct-space-xl) 0;
  text-align: center;
}
</style>
