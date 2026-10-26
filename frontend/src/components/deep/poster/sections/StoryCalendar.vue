<template>
  <!-- 年历（GitHub 风）：周一为顶行、按周纵排；月标签挂在月初所在周；仅自我/定向版消费（带日期） -->
  <div class="cal">
    <div class="cal-months" :style="{ gridTemplateColumns: `repeat(${weeks.length}, 1fr)` }">
      <span
        v-for="mark in monthMarks"
        :key="mark.label"
        class="cal-month"
        :style="{ color: palette.muted, gridColumn: `${mark.week + 1} / span 2` }"
      >{{ mark.label }}</span>
    </div>
    <div
      class="cal-grid"
      :style="{ gridTemplateColumns: `repeat(${weeks.length}, 1fr)` }"
    >
      <span
        v-for="(cell, i) in cells"
        :key="i"
        class="cal-cell"
        :style="{ backgroundColor: cellColor(cell) }"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { StoryPalette } from './palette'

const props = defineProps<{
  year: number
  days: Array<{ date: string; count: number }>
  max: number
  palette: StoryPalette
  /** 6 档色带：[空档, … 最高档]，与作息格同带 */
  ramp: string[]
}>()

const countMap = computed(() => {
  const map = new Map<string, number>()
  for (const day of props.days) map.set(day.date, day.count)
  return map
})

type Cell = { date: string; count: number } | null

// 周一为顶行：首尾补空格对齐整周，年外日期置 null（画空档色）
const weeks = computed<Cell[][]>(() => {
  const first = new Date(props.year, 0, 1)
  first.setDate(first.getDate() - ((first.getDay() + 6) % 7))
  const last = new Date(props.year, 11, 31)
  last.setDate(last.getDate() + (6 - ((last.getDay() + 6) % 7)))
  const out: Cell[][] = []
  const cursor = new Date(first)
  while (cursor <= last) {
    const week: Cell[] = []
    for (let i = 0; i < 7; i++) {
      if (cursor.getFullYear() === props.year) {
        const key = `${cursor.getFullYear()}-${pad(cursor.getMonth() + 1)}-${pad(cursor.getDate())}`
        week.push({ date: key, count: countMap.value.get(key) || 0 })
      } else {
        week.push(null)
      }
      cursor.setDate(cursor.getDate() + 1)
    }
    out.push(week)
  }
  return out
})

const cells = computed(() => weeks.value.flat())

// 月标签：每月 1 日所在的周挂「N月」（与后端 date 键同格式 YYYY-MM-DD）
const monthMarks = computed(() => {
  const marks: Array<{ week: number; label: string }> = []
  weeks.value.forEach((week, w) => {
    const hit = week.find((c) => c && c.date.endsWith('-01'))
    if (hit && (w === 0 || Number(hit.date.slice(5, 7)) > 1)) {
      marks.push({ week: w, label: `${Number(hit.date.slice(5, 7))}月` })
    }
  })
  return marks
})

function pad(value: number): string {
  return value < 10 ? `0${value}` : String(value)
}

function cellColor(cell: Cell): string {
  if (!cell || !props.max) return props.ramp[0]
  const ratio = cell.count / props.max
  if (ratio >= 0.75) return props.ramp[5]
  if (ratio >= 0.5) return props.ramp[4]
  if (ratio >= 0.3) return props.ramp[3]
  if (ratio >= 0.12) return props.ramp[2]
  if (cell.count > 0) return props.ramp[1]
  return props.ramp[0]
}
</script>

<style scoped>
/* 纯色小方格 + CSS grid 纵向按周流动；不用 shadow/transform/动画 */
.cal-months {
  display: grid;
  gap: 2px;
  margin-bottom: 5px;
  font-size: 10px;
  line-height: 1;
}

.cal-grid {
  display: grid;
  grid-auto-flow: column;
  grid-template-rows: repeat(7, 9px);
  gap: 2px;
}

.cal-cell {
  border-radius: 2px;
}
</style>
