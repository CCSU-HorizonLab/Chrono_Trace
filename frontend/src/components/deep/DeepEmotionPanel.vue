<template>
  <div class="panel deep-emotion">
    <div class="panel-head">
      <div>
        <div class="panel-title">情绪演变</div>
        <div class="panel-sub">按{{ granularityLabel }}聚合情感分（-1 压抑 ~ +1 轻松），滚动窗口看走势，可切双方/我/TA 或三线同显</div>
      </div>
      <div class="panel-actions">
        <div class="action-group" role="group" aria-label="视角">
          <span class="group-label">视角</span>
          <div class="group-btns">
            <button
              v-for="option in perspectiveOptions"
              :key="option.value"
              class="btn"
              :class="{ active: perspective === option.value }"
              @click="perspective = option.value"
            >{{ option.label }}</button>
          </div>
        </div>
        <div class="action-group" role="group" aria-label="滚动窗口">
          <span class="group-label">窗口</span>
          <div class="group-btns">
            <button
              v-for="option in rollingOptions"
              :key="option.value"
              class="btn"
              :class="{ active: rollingWindow === option.value }"
              @click="rollingWindow = option.value"
            >{{ option.label }}</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!buckets.length" class="empty-state">所选区间暂无消息</div>
    <template v-else>
      <EmotionLineChart
        :timeseries="smoothedBuckets"
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
  cachedCount?: number
  userCount?: number
  otherCount?: number
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

const perspective = ref<'combined' | 'me' | 'other' | 'all'>('combined')
const perspectiveOptions = [
  { value: 'combined' as const, label: '双方' },
  { value: 'me' as const, label: '我' },
  { value: 'other' as const, label: 'TA' },
  { value: 'all' as const, label: '全部' },
]

// 滚动窗口：0=原始桶均值；K>0=每点是「过去 K 个桶」的加权均值（默认 3）
const rollingWindow = ref(3)
const rollingOptions = computed(() => [
  { value: 0, label: '原始' },
  { value: 3, label: `近3${granularityLabel.value}` },
  { value: 5, label: `近5${granularityLabel.value}` },
  { value: 7, label: `近7${granularityLabel.value}` },
])

const granularityLabel = computed(
  () => ({ week: '周', month: '月', year: '年', day: '天' } as Record<string, string>)[props.granularity] || props.granularity,
)
const unitLabel = computed(
  () => ({ week: '当周', month: '当月', year: '当年', day: '当天' } as Record<string, string>)[props.granularity] || '当期',
)

// 尾随窗口加权均值：score/userScore/otherScore 各用自己侧的已缓存消息数做权重
// （消息多的桶话语权大，避免 1 条消息的桶与 500 条的桶同权）；窗口内权重全 0
// （无任何缓存）→ null 断线。计数与低置信底纹保持原桶原值，不随平滑改写。
const smoothedBuckets = computed<Bucket[]>(() => {
  const k = rollingWindow.value
  if (!k) return props.buckets
  const seriesSpec: Array<{ value: 'score' | 'userScore' | 'otherScore'; weight: 'cachedCount' | 'userCount' | 'otherCount' }> = [
    { value: 'score', weight: 'cachedCount' },
    { value: 'userScore', weight: 'userCount' },
    { value: 'otherScore', weight: 'otherCount' },
  ]
  return props.buckets.map((_, i) => {
    const out: Bucket = { ...props.buckets[i] }
    for (const spec of seriesSpec) {
      let weightedSum = 0
      let weightSum = 0
      for (let j = Math.max(0, i - k + 1); j <= i; j++) {
        const bucket = props.buckets[j]
        const v = bucket[spec.value]
        const w = Number(bucket[spec.weight] ?? 0)
        if (typeof v === 'number' && w > 0) {
          weightedSum += v * w
          weightSum += w
        }
      }
      out[spec.value] = weightSum > 0 ? Math.round((weightedSum / weightSum) * 1000) / 1000 : null
    }
    return out
  })
})

// 秒级时间戳 → 当前粒度的桶标签（与后端 sentiment_bucket_expr 同口径：周=周一日期，月=YYYY-MM，年=YYYY）
function bucketLabelForTs(tsSeconds: number): string {
  const d = new Date(tsSeconds * 1000)
  if (props.granularity === 'day') {
    return toLocalDateKey(d)
  }
  if (props.granularity === 'month') {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  }
  if (props.granularity === 'year') {
    return String(d.getFullYear())
  }
  // 周（默认）：落到所在周的周一
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
  if (rollingWindow.value > 0) {
    list.push(`曲线为近 ${rollingWindow.value}${granularityLabel.value}滑动平均（按消息数加权）`)
  }
  list.push('灰底列表示该' + unitLabel.value + '缺情感数据，分数仅供参考')
  if (affinityMarks.value.length) {
    list.push(props.affinity?.note || '好感度为全面分析完成时的落点，非每日快照')
  }
  return list
})
</script>

<style scoped>








.action-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.group-label {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.group-btns {
  display: flex;
  gap: var(--ct-space-xs);
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

</style>
