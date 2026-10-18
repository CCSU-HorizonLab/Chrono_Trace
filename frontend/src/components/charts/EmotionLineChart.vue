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
        <div v-if="legendItems.length > 1" class="legend">
          <span v-for="item in legendItems" :key="item.label" class="legend-item">
            <span class="legend-swatch" :style="{ background: item.color }" />
            {{ item.label }}
          </span>
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

        <!-- 低置信桶底纹：该桶缺情感数据，分数仅供参考 -->
        <rect
          v-for="(band, index) in lowConfidenceBands"
          :key="`lc-${index}`"
          :x="band.x"
          :y="padding.top"
          :width="band.width"
          :height="height - padding.top - padding.bottom"
          class="low-confidence-band"
        />

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

        <!-- 消极时段：曲线低于 0 的部分与基线围成的浅红区 -->
        <polygon
          v-for="(poly, index) in negativePolygons"
          :key="`neg-${index}`"
          :points="poly"
          class="negative-shade"
        />

        <template v-for="line in renderedLines" :key="line.key">
          <polyline
            v-if="line.areaPoints"
            :points="line.areaPoints"
            fill="url(#emotion-area-gradient)"
            stroke="none"
          />
          <polyline
            v-for="(seg, segIndex) in line.segments"
            :key="`seg-${segIndex}`"
            :points="seg"
            fill="none"
            :stroke="line.color"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </template>

        <!-- 单线模式的悬停点 -->
        <g
          v-for="point in chartPoints"
          :key="point.ts"
          @mouseenter="activeIndex = point.index"
        >
          <circle :cx="point.x" :cy="point.y" :r="point.index === activeIndex ? 6 : 4" class="point-dot" :class="{ active: point.index === activeIndex }" />
        </g>
        <!-- 双线模式：仅悬停列上显示有数据各线的标记 -->
        <g v-if="renderedLines.length > 1 && activePoint">
          <circle
            v-for="mark in hoverMarks"
            :key="`hp-${mark.key}`"
            :cx="mark.x"
            :cy="mark.y"
            r="5"
            class="point-dot"
            :style="{ stroke: mark.color }"
          />
        </g>

        <!-- 好感度历史落点（菱形；0-100 映射到 -1..1 量纲） -->
        <g v-for="mark in affinityMarks" :key="`aff-${mark.ts}`">
          <rect
            :x="mark.x - 5"
            :y="mark.y - 5"
            :width="10"
            :height="10"
            class="affinity-mark"
            transform-origin="center"
            :transform="`rotate(45 ${mark.x} ${mark.y})`"
          >
            <title>好感度 {{ mark.score }}（全面分析落点，非每日快照）</title>
          </rect>
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
        <div v-if="typeof activePoint.score === 'number'">{{ unitLabel }}氛围 {{ getToneLabel(activePoint.score) }}</div>
        <div v-else class="tooltip-warn">该{{ unitLabel }}缺情感数据（未补算）</div>
        <div v-if="activePoint.userScore !== null && activePoint.userScore !== undefined">我的情绪 {{ activePoint.userScore > 0 ? '+' : '' }}{{ activePoint.userScore }}</div>
        <div v-if="activePoint.otherScore !== null && activePoint.otherScore !== undefined">TA 的情绪 {{ activePoint.otherScore > 0 ? '+' : '' }}{{ activePoint.otherScore }}</div>
        <div>消息数 {{ activePoint.msgCount || 0 }}</div>
        <div>正向 {{ activePoint.positive || 0 }} / 中性 {{ activePoint.neutral || 0 }} / 负向 {{ activePoint.negative || 0 }}</div>
        <div v-if="activeCoverage !== null && activeCoverage < 1" class="tooltip-warn">
          情感数据覆盖 {{ Math.round(activeCoverage * 100) }}%，该{{ unitLabel }}分数仅供参考
        </div>
        <div v-if="activeAffinity !== null">好感度 {{ activeAffinity }}（分析落点）</div>
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
  coverage?: number | null
  lowConfidence?: boolean
}

// 双方曲线配色经 CVD 校验（dataviz 六检全过，白底）：我=紫 / TA=深琥珀 / 好感度=深蓝
const ME_COLOR = '#7c4dff'
const OTHER_COLOR = '#d97706'
const AFFINITY_COLOR = '#2563eb'
const COMBINED_COLOR = '#5b8def'

const props = defineProps<{
  timeseries: TimeseriesPoint[]
  /** combined=合并单线（默认，现状）；me/other=单侧；both=双方双线 */
  perspective?: 'combined' | 'both' | 'me' | 'other'
  /** 消极时段：曲线低于 0 的区段着浅红 */
  negativeShade?: boolean
  /** 好感度历史落点；ts 为桶标签（与 timeseries.ts 同口径），score 0-100 */
  affinityPoints?: Array<{ ts: string; score: number }>
  /** 桶粒度名（天/周/月/年），用于 tooltip 文案；默认「当天」 */
  unitLabel?: string
}>()

const unitLabel = computed(() => props.unitLabel || '当天')
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
// 缺覆盖桶 score 为 null：均值只统计有分数的桶
const averageScore = computed(() => {
  const scored = props.timeseries.filter((item) => typeof item.score === 'number')
  if (!scored.length) return 0
  return scored.reduce((sum, item) => sum + (item.score || 0), 0) / scored.length
})
const overallTone = computed(() => getToneSummary(averageScore.value))

interface RenderedLine {
  key: string
  color: string
  pick: (point: TimeseriesPoint) => number | null | undefined
  segments: string[]
  points: Array<{ x: number; y: number; value: number; index: number }>
  areaPoints: string
}

const renderedLines = computed<RenderedLine[]>(() => {
  const defs: Array<{ key: string; color: string; pick: (p: TimeseriesPoint) => number | null | undefined }> = []
  if (props.perspective === 'me') {
    defs.push({ key: 'me', color: ME_COLOR, pick: (p) => p.userScore })
  } else if (props.perspective === 'other') {
    defs.push({ key: 'other', color: OTHER_COLOR, pick: (p) => p.otherScore })
  } else if (props.perspective === 'both') {
    defs.push({ key: 'me', color: ME_COLOR, pick: (p) => p.userScore })
    defs.push({ key: 'other', color: OTHER_COLOR, pick: (p) => p.otherScore })
  } else {
    defs.push({ key: 'combined', color: COMBINED_COLOR, pick: (p) => p.score })
  }

  return defs.map((def) => {
    const points: Array<{ x: number; y: number; value: number; index: number }> = []
    props.timeseries.forEach((item, index) => {
      const value = def.pick(item)
      if (value === null || value === undefined || Number.isNaN(value)) return
      points.push({ x: scaleX(index, props.timeseries.length), y: scaleY(value), value, index })
    })

    // 缺值（单侧无消息/缺覆盖）处断线：仅相邻索引的点连成一段
    const segments: string[] = []
    let current: Array<{ x: number; y: number }> = []
    for (let i = 0; i < points.length; i++) {
      current.push(points[i])
      const next = points[i + 1]
      if (!next || next.index !== points[i].index + 1) {
        if (current.length > 1) segments.push(current.map((p) => `${p.x},${p.y}`).join(' '))
        current = []
      }
    }
    if (current.length > 1) segments.push(current.map((p) => `${p.x},${p.y}`).join(' '))

    // 面积只在单线模式画（双线叠面积会糊）
    let areaPoints = ''
    if (defs.length === 1 && points.length) {
      const baseline = height - padding.bottom
      areaPoints = [
        `${points[0].x},${baseline}`,
        ...points.map((p) => `${p.x},${p.y}`),
        `${points[points.length - 1].x},${baseline}`,
      ].join(' ')
    }

    return { ...def, segments, points, areaPoints }
  })
})

function pickValue(line: RenderedLine, index: number): number | null {
  const item = props.timeseries[index]
  const value = item ? line.pick(item) : null
  // null 语义是「该侧此桶无数据」，保持 null——回落 0 会把悬停标记画在
  // 中性 0 分处，误读为情绪回落（与 lowConfidenceBands 的缺失语义冲突）
  return value ?? null
}

// 双线模式悬停标记：只画有数据的一侧（无数据侧画 0 分点会误读为情绪回落）
const hoverMarks = computed(() => {
  if (renderedLines.value.length <= 1 || !activePoint.value) return []
  const marks: Array<{ key: string; color: string; x: number; y: number }> = []
  for (const line of renderedLines.value) {
    const value = pickValue(line, activeIndex.value)
    if (value === null) continue
    marks.push({ key: line.key, color: line.color, x: activePoint.value.x, y: scaleY(value) })
  }
  return marks
})

// 消息量柱：底部浅蓝细柱，量级与消息数成正比（最多 52px 高）
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

// x 轴刻度直接基于 timeseries 索引（不随曲线空值断线漂移）
const xTicks = computed(() => {
  const count = props.timeseries.length
  if (!count) return []
  if (count <= 6) {
    return props.timeseries.map((item, index) => ({
      x: scaleX(index, count),
      label: formatDateLabel(item.ts),
    }))
  }
  const lastIndex = count - 1
  const indexes = new Set([0, Math.floor(lastIndex / 3), Math.floor((lastIndex * 2) / 3), lastIndex])
  return [...indexes].sort((a, b) => a - b).map((index) => ({
    x: scaleX(index, count),
    label: formatDateLabel(props.timeseries[index].ts),
  }))
})

const legendItems = computed(() => {
  const items: Array<{ label: string; color: string }> = []
  if (props.perspective === 'both') {
    items.push({ label: '我', color: ME_COLOR }, { label: 'TA', color: OTHER_COLOR })
  }
  if (props.affinityPoints?.length) {
    items.push({ label: '好感度落点', color: AFFINITY_COLOR })
  }
  return items
})

const chartPoints = computed(() => {
  if (renderedLines.value.length !== 1) return []
  const line = renderedLines.value[0]
  return line.points.map((point) => ({
    x: point.x,
    y: point.y,
    value: point.value,
    ts: props.timeseries[point.index]?.ts ?? String(point.index),
    index: point.index,
  }))
})

const negativePolygons = computed(() => {
  if (!props.negativeShade) return []
  const polygons: string[] = []
  const baseline = zeroY
  for (const line of renderedLines.value) {
    let run: Array<{ x: number; y: number }> = []
    const flush = () => {
      if (run.length > 1) {
        polygons.push(
          [`${run[0].x},${baseline}`, ...run.map((p) => `${p.x},${p.y}`), `${run[run.length - 1].x},${baseline}`].join(' '),
        )
      }
      run = []
    }
    for (const point of line.points) {
      if (point.value < 0) run.push(point)
      else flush()
    }
    flush()
  }
  return polygons
})

const affinityMarks = computed(() => {
  if (!props.affinityPoints?.length) return []
  const byTs = new Map(props.affinityPoints.map((p) => [p.ts, p.score]))
  const marks: Array<{ ts: string; x: number; y: number; score: number }> = []
  props.timeseries.forEach((item, index) => {
    const score = byTs.get(item.ts)
    if (score === undefined) return
    marks.push({
      ts: item.ts,
      x: scaleX(index, props.timeseries.length),
      y: scaleY(score / 50 - 1), // 0-100 → -1..1
      score,
    })
  })
  return marks
})

const lowConfidenceBands = computed(() => {
  const innerWidth = width - padding.left - padding.right
  const bandWidth = innerWidth / Math.max(props.timeseries.length, 1)
  return props.timeseries
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.lowConfidence)
    .map(({ index }) => ({
      x: padding.left + index * bandWidth,
      width: bandWidth,
    }))
})

const activePoint = computed(() => {
  if (activeIndex.value < 0 || activeIndex.value >= props.timeseries.length) return null
  const item = props.timeseries[activeIndex.value]
  return { ...item, x: scaleX(activeIndex.value, props.timeseries.length), y: scaleY(typeof item.score === 'number' ? item.score : 0) }
})

const activeCoverage = computed(() => activePoint.value?.coverage ?? null)
const activeAffinity = computed(() => {
  if (!activePoint.value || !props.affinityPoints?.length) return null
  return props.affinityPoints.find((p) => p.ts === activePoint.value?.ts)?.score ?? null
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
  if (ts.length === 10) {
    const [, month = '', day = ''] = ts.split('-')
    return `${month}/${day}`
  }
  return ts // 周桶为周一日期；月/年桶本就是短标签
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

.legend {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
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

.low-confidence-band {
  fill: rgba(148, 163, 184, 0.12);
}

.message-bar {
  fill: rgba(91, 141, 239, 0.12);
  rx: 8px;
  transition: fill 0.18s ease;
}

.message-bar.active {
  fill: rgba(91, 141, 239, 0.2);
}

.negative-shade {
  fill: rgba(239, 68, 68, 0.08);
  pointer-events: none;
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

.affinity-mark {
  fill: #ffffff;
  stroke: #2563eb;
  stroke-width: 2;
  pointer-events: all;
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

.tooltip-warn {
  color: #fbbf24;
}

.empty {
  color: var(--ct-text-tertiary);
}
</style>
