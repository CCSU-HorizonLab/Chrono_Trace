<template>
  <div class="chart">
    <div v-if="!timeseries?.length" class="empty">所选区间暂无数据</div>
    <div v-else class="chart-shell">
      <div class="chart-meta">
        <div class="meta-item">
          <span class="meta-label">整体聊天氛围</span>
          <span class="meta-value">{{ overallTone.label }}</span>
          <span class="meta-note">{{ overallTone.description }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">样本消息</span>
          <span class="meta-value">{{ totalMessages }}</span>
        </div>
      </div>

      <svg
        ref="svgEl"
        :viewBox="`0 0 ${width} ${height}`"
        preserveAspectRatio="none"
        @mouseleave="activeIndex = -1"
      >
        <defs>
          <linearGradient id="emotion-area-gradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stop-color="#5b8def" stop-opacity="0.28" />
            <stop offset="100%" stop-color="#5b8def" stop-opacity="0.04" />
          </linearGradient>
        </defs>

        <line
          v-for="tick in yTicks"
          :key="`y-${tick.value}`"
          :x1="padding.left"
          :x2="width - padding.right"
          :y1="tick.y"
          :y2="tick.y"
          class="grid-line"
        />
        <line
          :x1="padding.left"
          :x2="width - padding.right"
          :y1="zeroY"
          :y2="zeroY"
          class="zero-line"
        />

        <text
          v-for="tick in yTicks"
          :key="`yl-${tick.value}`"
          :x="padding.left - 10"
          :y="tick.y + 4"
          class="axis-label axis-label-y"
        >
          {{ tick.label }}
        </text>

        <rect
          v-for="(bar, index) in bars"
          :key="`bar-${index}`"
          :x="bar.x"
          :y="bar.y"
          :width="bar.width"
          :height="bar.height"
          class="message-bar"
          :class="{ active: index === activeIndex }"
          @mouseenter="activeIndex = index"
        />

        <polyline :points="areaPoints" fill="url(#emotion-area-gradient)" stroke="none" />
        <polyline :points="linePoints" fill="none" stroke="#5b8def" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />

        <g
          v-for="(point, index) in chartPoints"
          :key="point.ts"
          @mouseenter="activeIndex = index"
        >
          <circle :cx="point.x" :cy="point.y" :r="index === activeIndex ? 6 : 4" class="point-dot" :class="{ active: index === activeIndex }" />
        </g>

        <line
          v-if="activePoint"
          :x1="activePoint.x"
          :x2="activePoint.x"
          :y1="padding.top"
          :y2="height - padding.bottom"
          class="cursor-line"
        />

        <text
          v-for="(tick, index) in xTicks"
          :key="`x-${index}`"
          :x="tick.x"
          :y="height - 12"
          class="axis-label axis-label-x"
          text-anchor="middle"
        >
          {{ tick.label }}
        </text>
      </svg>

      <div v-if="activePoint" class="tooltip" :style="tooltipStyle">
        <div class="tooltip-date">{{ activePoint.ts }}</div>
        <div>当天氛围 {{ getToneLabel(activePoint.score) }}</div>
        <div>消息数 {{ activePoint.msgCount || 0 }}</div>
        <div>正向 {{ activePoint.positive || 0 }} / 中性 {{ activePoint.neutral || 0 }} / 负向 {{ activePoint.negative || 0 }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

type TimeseriesPoint = {
  ts: string
  score: number
  positive?: number
  neutral?: number
  negative?: number
  msgCount?: number
  userScore?: number | null
  otherScore?: number | null
}

const props = defineProps<{ timeseries: TimeseriesPoint[] }>()

const width = 800
const height = 300
const padding = { top: 20, right: 24, bottom: 34, left: 44 }
const svgEl = ref<SVGSVGElement | null>(null)
const activeIndex = ref(-1)

const yTicks = computed(() => {
  return [
    { value: 1, label: '更轻松' },
    { value: 0.5, label: '偏积极' },
    { value: 0, label: '比较平稳' },
    { value: -0.5, label: '有点低落' },
    { value: -1, label: '更压抑' },
  ].map((item) => ({
    ...item,
    y: scaleY(item.value),
  }))
})

const totalMessages = computed(() => props.timeseries.reduce((sum, item) => sum + (item.msgCount || 0), 0))
const averageScore = computed(() => {
  if (!props.timeseries.length) return 0
  return props.timeseries.reduce((sum, item) => sum + item.score, 0) / props.timeseries.length
})
const overallTone = computed(() => getToneSummary(averageScore.value))

const chartPoints = computed(() => {
  if (!props.timeseries.length) return []
  return props.timeseries.map((item, index) => ({
    ...item,
    x: scaleX(index, props.timeseries.length),
    y: scaleY(item.score),
  }))
})

const linePoints = computed(() => chartPoints.value.map((point) => `${point.x},${point.y}`).join(' '))
const areaPoints = computed(() => {
  if (!chartPoints.value.length) return ''
  const first = chartPoints.value[0]
  const last = chartPoints.value[chartPoints.value.length - 1]
  return [
    `${first.x},${height - padding.bottom}`,
    ...chartPoints.value.map((point) => `${point.x},${point.y}`),
    `${last.x},${height - padding.bottom}`,
  ].join(' ')
})

const bars = computed(() => {
  const maxCount = Math.max(...props.timeseries.map((item) => item.msgCount || 0), 1)
  const baseline = height - padding.bottom
  const maxBarHeight = 52
  return props.timeseries.map((item, index) => {
    const centerX = scaleX(index, props.timeseries.length)
    const barHeight = ((item.msgCount || 0) / maxCount) * maxBarHeight
    return {
      x: centerX - 8,
      y: baseline - barHeight,
      width: 16,
      height: barHeight,
    }
  })
})

const xTicks = computed(() => {
  const data = chartPoints.value
  if (!data.length) return []
  if (data.length <= 6) {
    return data.map((point) => ({ x: point.x, label: formatDateLabel(point.ts) }))
  }

  const lastIndex = data.length - 1
  const indexes = new Set([0, Math.floor(lastIndex / 3), Math.floor((lastIndex * 2) / 3), lastIndex])
  return [...indexes].sort((a, b) => a - b).map((index) => ({
    x: data[index].x,
    label: formatDateLabel(data[index].ts),
  }))
})

const activePoint = computed(() => {
  if (activeIndex.value < 0 || activeIndex.value >= chartPoints.value.length) return null
  return chartPoints.value[activeIndex.value]
})

const tooltipStyle = computed(() => {
  const point = activePoint.value
  if (!point) return {}
  const left = `${Math.min(Math.max((point.x / width) * 100, 10), 78)}%`
  const top = `${Math.min(Math.max((point.y / height) * 100 - 6, 6), 68)}%`
  return { left, top }
})

const zeroY = scaleY(0)

function scaleX(index: number, count: number) {
  const innerWidth = width - padding.left - padding.right
  if (count <= 1) return padding.left + innerWidth / 2
  return padding.left + (index / (count - 1)) * innerWidth
}

function scaleY(score: number) {
  const clamped = Math.max(-1, Math.min(1, score))
  const innerHeight = height - padding.top - padding.bottom
  return padding.top + ((1 - clamped) / 2) * innerHeight
}

function formatDateLabel(ts: string) {
  const [, month = '', day = ''] = ts.split('-')
  return `${month}/${day}`
}

function getToneLabel(score: number) {
  return getToneSummary(score).label
}

function getToneSummary(score: number) {
  if (score >= 0.45) {
    return { label: '明显偏积极', description: '这段时间聊天大多轻松、愉快。' }
  }
  if (score >= 0.15) {
    return { label: '整体偏积极', description: '互动状态不错，聊天氛围比较舒服。' }
  }
  if (score > -0.15) {
    return { label: '比较平稳', description: '整体起伏不大，以日常交流为主。' }
  }
  if (score > -0.45) {
    return { label: '略显低落', description: '这段时间情绪偏谨慎，偶尔有压力感。' }
  }
  return { label: '明显偏低落', description: '最近聊天里压抑或消极情绪更突出。' }
}
</script>

<style scoped>
.chart {
  width: 100%;
  min-height: 320px;
}

.chart-shell {
  position: relative;
}

.chart-meta {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.meta-item {
  display: inline-flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.meta-value {
  color: var(--ct-text-primary);
  font-weight: 700;
}

.meta-note {
  color: var(--ct-text-tertiary);
}

svg {
  width: 100%;
  height: 280px;
  display: block;
  overflow: visible;
}

.grid-line {
  stroke: rgba(148, 163, 184, 0.18);
  stroke-dasharray: 4 4;
}

.zero-line {
  stroke: rgba(239, 68, 68, 0.28);
  stroke-dasharray: 6 4;
}

.axis-label {
  fill: var(--ct-text-tertiary);
  font-size: 11px;
}

.axis-label-y {
  text-anchor: end;
}

.message-bar {
  fill: rgba(91, 141, 239, 0.12);
  rx: 8px;
  transition: fill 0.18s ease;
}

.message-bar.active {
  fill: rgba(91, 141, 239, 0.2);
}

.point-dot {
  fill: #ffffff;
  stroke: #5b8def;
  stroke-width: 2;
  transition: r 0.18s ease, fill 0.18s ease;
}

.point-dot.active {
  fill: #5b8def;
}

.cursor-line {
  stroke: rgba(91, 141, 239, 0.28);
  stroke-dasharray: 4 4;
}

.tooltip {
  position: absolute;
  min-width: 170px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.6;
  pointer-events: none;
  transform: translate(-50%, -100%);
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.22);
}

.tooltip-date {
  color: #ffffff;
  font-weight: 700;
  margin-bottom: 4px;
}

.empty {
  color: var(--ct-text-tertiary);
}
</style>
