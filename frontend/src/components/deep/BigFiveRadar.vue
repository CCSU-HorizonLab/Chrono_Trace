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

type DimensionScore = { score: number | null; label?: string }
type Scores = Record<string, DimensionScore>

const props = defineProps<{
  me?: Scores | null
  other?: Scores | null
  size?: number
  /** 紧凑档（演变分段小多图用）：留白与轴标签字号缩小，BigFivePanel/海报不受影响 */
  compact?: boolean
}>()

// 维度顺序固定（雷达轴序即类别序，不随数据重排）
const size = computed(() => props.size || 260)
const center = computed(() => size.value / 2)
const padding = computed(() => (props.compact ? 24 : 34))
const radius = computed(() => size.value / 2 - padding.value)

const DIM_ORDER = ['openness', 'extraversion', 'agreeableness', 'conscientiousness', 'neuroticism']
const DIM_TEXT = ['开放', '外向', '宜人', '尽责', '神经质']

const axes = computed(() =>
  DIM_ORDER.map((_, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / 5
    return {
      x: center.value + radius.value * Math.cos(angle),
      y: center.value + radius.value * Math.sin(angle),
    }
  }),
)

const gridLayers = [1, 2, 3]

function pointAt(index: number, ratio: number) {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / 5
  return {
    x: center.value + radius.value * ratio * Math.cos(angle),
    y: center.value + radius.value * ratio * Math.sin(angle),
  }
}

function polygonPoints(ratio: number): string {
  return DIM_ORDER.map((_, index) => {
    const p = pointAt(index, ratio)
    return `${p.x},${p.y}`
  }).join(' ')
}

function scoresPoints(scores?: Scores | null): string | null {
  if (!scores) return null
  const points: string[] = []
  DIM_ORDER.forEach((dim, index) => {
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
  return DIM_TEXT.map((text, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / 5
    const x = center.value + (radius.value + offset) * Math.cos(angle)
    const y = center.value + (radius.value + offset) * Math.sin(angle) + 4
    const anchor = Math.abs(Math.cos(angle)) < 0.3 ? 'middle' : Math.cos(angle) > 0 ? 'start' : 'end'
    return { text, x, y, anchor }
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
  stroke: #7c4dff;
  fill: #7c4dff;
}

.data-poly.other {
  stroke: #d97706;
  fill: #d97706;
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
