<template>
  <div class="radar-wrap">
    <svg :viewBox="`0 0 ${size} ${size}`" class="radar-svg" :class="{ compact }">
      <!-- 网格：3 层五边形 -->
      <polygon
        v-for="layer in gridLayers"
        :key="layer"
        :points="polygonPoints(layer / 3)"
        class="grid-poly"
      />
      <!-- 轴线 -->
      <line
        v-for="(_, index) in axes"
        :key="`axis-${index}`"
        :x1="center"
        :y1="center"
        :x2="axes[index].x"
        :y2="axes[index].y"
        class="axis-line"
      />
      <!-- 对方（琥珀）先画在下层，我（紫）叠加 -->
      <polygon
        v-if="otherPoints"
        :points="otherPoints"
        class="data-poly other"
      />
      <polygon
        v-if="mePoints"
        :points="mePoints"
        class="data-poly me"
      />
      <!-- 轴标签 -->
      <text
        v-for="(label, index) in axisLabels"
        :key="`label-${index}`"
        :x="label.x"
        :y="label.y"
        class="axis-label"
        :text-anchor="label.anchor"
      >{{ label.text }}</text>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { BIG5_DIM_ORDER, BIG5_DIM_TEXT, big5LabelPos, big5PointAt } from './big5Shared'

type DimensionScore = { score: number | null; label?: string }
type Scores = Record<string, DimensionScore>

const props = defineProps<{
  me?: Scores | null
  other?: Scores | null
  size?: number
  /** 紧凑档（演变分段小多图用）：留白与轴标签字号缩小，BigFivePanel/海报不受影响 */
  compact?: boolean
}>()

// 维度顺序与轴短标签固定（雷达轴序即类别序，不随数据重排），单源 big5Shared
const size = computed(() => props.size || 260)
const center = computed(() => size.value / 2)
const padding = computed(() => (props.compact ? 24 : 34))
const radius = computed(() => size.value / 2 - padding.value)

const axes = computed(() =>
  BIG5_DIM_ORDER.map((_, index) => big5PointAt(center.value, center.value, radius.value, index, 1)),
)

const gridLayers = [1, 2, 3]

function pointAt(index: number, ratio: number) {
  return big5PointAt(center.value, center.value, radius.value, index, ratio)
}

function polygonPoints(ratio: number): string {
  return BIG5_DIM_ORDER.map((_, index) => {
    const p = pointAt(index, ratio)
    return `${p.x},${p.y}`
  }).join(' ')
}

function scoresPoints(scores?: Scores | null): string | null {
  if (!scores) return null
  const points: string[] = []
  BIG5_DIM_ORDER.forEach((dim, index) => {
    const value = scores[dim]?.score
    const ratio = typeof value === 'number' ? Math.max(0, Math.min(100, value)) / 100 : 0
    const p = pointAt(index, ratio)
    points.push(`${p.x},${p.y}`)
  })
  return points.join(' ')
}

const mePoints = computed(() => scoresPoints(props.me))
const otherPoints = computed(() => scoresPoints(props.other))

const axisLabels = computed(() => {
  const offset = props.compact ? 13 : 18
  return BIG5_DIM_ORDER.map((dim, index) => {
    const pos = big5LabelPos(center.value, center.value, radius.value, offset, index)
    return { text: BIG5_DIM_TEXT[dim], x: pos.x, y: pos.y + 4, anchor: pos.anchor }
  })
})
</script>

<style scoped>
.radar-wrap {
  display: flex;
  justify-content: center;
}

.radar-svg {
  width: 100%;
  max-width: 280px;
  height: auto;
}

.radar-svg.compact {
  max-width: 230px;
}

.grid-poly {
  fill: none;
  stroke: rgba(148, 163, 184, 0.25);
  stroke-width: 1;
}

.axis-line {
  stroke: rgba(148, 163, 184, 0.2);
  stroke-width: 1;
}

.data-poly {
  stroke-width: 2;
  fill-opacity: 0.12;
}

.data-poly.me {
  stroke: var(--ct-chart-1);
  fill: var(--ct-chart-1);
}

.data-poly.other {
  stroke: var(--ct-chart-4);
  fill: var(--ct-chart-4);
  fill-opacity: 0.1;
}

.axis-label {
  fill: var(--ct-text-secondary);
  font-size: 11px;
}

.radar-svg.compact .axis-label {
  font-size: 9px;
}
</style>
