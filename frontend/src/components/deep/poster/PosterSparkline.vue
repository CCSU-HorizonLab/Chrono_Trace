<template>
  <svg :viewBox="`0 0 ${width} ${height}`" :width="width" :height="height" class="sparkline">
    <line
      v-if="zeroLine"
      :x1="0" :x2="width" :y1="midY" :y2="midY"
      class="zero"
    />
    <polyline
      v-for="line in lines"
      :key="line.key"
      :points="line.points"
      fill="none"
      :stroke="line.color"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { BIG5_COLOR_ME, BIG5_COLOR_OTHER } from '@/components/deep/big5Shared'

type Point = { score?: number | null; userScore?: number | null; otherScore?: number | null }

const props = defineProps<{
  points: Point[]
  /** 单值键（score/userScore/otherScore）或 'both' 双线 */
  pick?: 'score' | 'userScore' | 'otherScore' | 'both'
  width?: number
  height?: number
  /** 画零基准虚线（双极性序列如情感 -1~1 建议开） */
  zeroLine?: boolean
  /** 单值线颜色覆盖（默认沿用 BIG5_COLOR_ME；暖色模板传主题橘） */
  color?: string
}>()

const width = computed(() => props.width || 640)
const height = computed(() => props.height || 120)
const midY = computed(() => height.value / 2)

const ME = props.color || BIG5_COLOR_ME
const OTHER = BIG5_COLOR_OTHER

function scaleX(index: number, count: number) {
  if (count <= 1) return width.value / 2
  return (index / (count - 1)) * width.value
}

function scaleY(value: number) {
  const clamped = Math.max(-1, Math.min(1, value))
  return height.value / 2 - (clamped * height.value) / 2.4
}

const lines = computed(() => {
  const defs: Array<{ key: string; color: string; pick: (p: Point) => number | null | undefined }> = []
  if (props.pick === 'both') {
    defs.push({ key: 'me', color: ME, pick: (p) => p.userScore })
    defs.push({ key: 'other', color: OTHER, pick: (p) => p.otherScore })
  } else {
    const key = props.pick || 'score'
    defs.push({ key, color: ME, pick: (p) => p[key as keyof Point] as number | null })
  }
  return defs
    .map((def) => {
      const pts: string[] = []
      props.points.forEach((p, index) => {
        const value = def.pick(p)
        if (typeof value !== 'number') return
        pts.push(`${scaleX(index, props.points.length)},${scaleY(value)}`)
      })
      return { key: def.key, color: def.color, points: pts.join(' ') }
    })
    .filter((line) => line.points.split(' ').length > 1)
})
</script>

<style scoped>
.sparkline {
  display: block;
}

.zero {
  stroke: rgba(148, 163, 184, 0.35);
  stroke-dasharray: 4 4;
  stroke-width: 1;
}
</style>
