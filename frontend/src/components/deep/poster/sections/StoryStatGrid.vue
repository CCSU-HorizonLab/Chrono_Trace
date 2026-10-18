<template>
  <!-- 默契数字格：num 为预格式化文本，强调色按 tone 分档 -->
  <div class="story-stat-grid">
    <div
      v-for="(item, i) in items"
      :key="i"
      class="stat-cell"
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
import type { StoryPalette, StoryStatItem } from './palette'

defineProps<{
  items: StoryStatItem[]
  palette: StoryPalette
}>()
</script>

<style scoped>
.story-stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.stat-cell {
  border: 1px solid;
  border-radius: 14px;
  padding: 18px 14px;
  text-align: center;
  box-sizing: border-box;
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
