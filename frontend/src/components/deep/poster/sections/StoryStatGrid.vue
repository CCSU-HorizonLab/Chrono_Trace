<template>
  <!-- 数字格：默认等分铺排；bento 变体首格放大为主格（一大带小环绕） -->
  <div class="story-stat-grid" :class="{ bento: layout !== 'grid' }">
    <div
      v-for="(item, i) in items"
      :key="i"
      class="stat-cell"
      :class="cellClass(i)"
      :style="{ borderColor: palette.line, background: palette.bg }"
    >
      <div
        class="stat-num"
        :style="{ color: item.tone === 'sub' ? palette.sub : palette.accent }"
      >{{ item.num }}</div>
      <div class="stat-label" :style="{ color: palette.muted }">{{ item.label }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { StoryPalette, StoryStatItem } from './palette'

const props = defineProps<{
  items: StoryStatItem[]
  palette: StoryPalette
  /** bento 版式：首格为主格（跨两行、大数字）。条数 2~4 生效，其余回退等分 */
  bento?: boolean
}>()

type Layout = 'grid' | 'two-tall' | 'hero-tall' | 'hero-wide'
// N=2 两半等高；N=3 主格左跨两行；N=4 主格跨两行+末格通栏补位；N<2 或 >4 回退等分
const layout = computed<Layout>(() => {
  if (!props.bento) return 'grid'
  const n = props.items.length
  if (n === 2) return 'two-tall'
  if (n === 3) return 'hero-tall'
  if (n === 4) return 'hero-wide'
  return 'grid'
})

function cellClass(index: number): string {
  if (layout.value === 'grid') return ''
  if (layout.value === 'two-tall') return 'cell-tall'
  if (index === 0) return 'cell-hero'
  if (layout.value === 'hero-wide' && index === props.items.length - 1) return 'cell-wide'
  return ''
}
</script>

<style scoped>
/* html2canvas 纪律：纯色 + border + 圆角；flex 居中不引 transform */
.story-stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.story-stat-grid.bento {
  grid-template-columns: repeat(2, 1fr);
}

.bento .cell-tall {
  grid-row: span 2;
}

.bento .cell-hero {
  grid-row: span 2;
}

.bento .cell-hero .stat-num {
  font-size: 44px;
}

.bento .cell-wide {
  grid-column: 1 / -1;
}

.stat-cell {
  border: 1px solid;
  border-radius: 14px;
  padding: 18px 14px;
  text-align: center;
  box-sizing: border-box;
  /* bento 跨行高格垂直居中；等分格内容高度不变，视觉无差 */
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.stat-num {
  font-size: 34px;
  font-weight: 800;
  line-height: 1.2;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.stat-label {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
}
</style>
