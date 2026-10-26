<template>
  <!-- 作息热力格：7 行（周一为顶）× 24 时辰列；纯色 cell、无绝对日期（html2canvas 纪律） -->
  <div class="heat">
    <div class="heat-body">
      <template v-for="(row, r) in counts" :key="r">
        <span class="heat-wd" :style="{ color: palette.muted }">{{ WEEKDAY_LABELS[r] }}</span>
        <span
          v-for="(count, h) in row"
          :key="h"
          class="heat-cell"
          :style="{ backgroundColor: cellColor(count) }"
        />
      </template>
    </div>
    <div class="heat-hours">
      <span
        v-for="tick in hourTicks"
        :key="tick.label"
        class="heat-tick"
        :style="{ color: palette.muted, gridColumn: tick.col, justifySelf: tick.align }"
      >{{ tick.label }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { WEEKDAY_LABELS } from '../activityShared'
import type { StoryPalette } from './palette'

const props = defineProps<{
  /** 7×24 计数（周一为第 0 行） */
  counts: number[][]
  max: number
  palette: StoryPalette
  /** 6 档色带：[空档, … 最高档]，随模板基调走 */
  ramp: string[]
}>()

const hourTicks = [
  { label: '0点', col: '2 / span 2', align: 'start' as const },
  { label: '6点', col: '8 / span 2', align: 'start' as const },
  { label: '12点', col: '14 / span 2', align: 'start' as const },
  { label: '18点', col: '20 / span 2', align: 'start' as const },
  { label: '24点', col: '24 / span 2', align: 'end' as const },
]

// 分档阈值按峰值比例：聊天作息长尾尖峰，低档收得紧才不至全图糊成一片
function level(count: number): number {
  if (!count || !props.max) return 0
  const ratio = count / props.max
  if (ratio >= 0.75) return 5
  if (ratio >= 0.5) return 4
  if (ratio >= 0.3) return 3
  if (ratio >= 0.12) return 2
  return 1
}

function cellColor(count: number): string {
  return props.ramp[level(count)]
}
</script>

<style scoped>
/* 纯色 cell + CSS grid；不用 shadow/transform/动画（html2canvas 纪律） */
.heat-body {
  display: grid;
  grid-template-columns: 34px repeat(24, 1fr);
  gap: 3px 2px;
  align-items: center;
}

.heat-wd {
  font-size: 11px;
  line-height: 1;
}

.heat-cell {
  height: 16px;
  border-radius: 3px;
}

.heat-hours {
  display: grid;
  grid-template-columns: 34px repeat(24, 1fr);
  gap: 3px 2px;
  margin-top: 6px;
  font-size: 10px;
  line-height: 1;
}
</style>
