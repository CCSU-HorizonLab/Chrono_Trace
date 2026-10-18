<template>
  <!-- 幕容器：只管幕头与留白，幕内容由插槽注入（抽骨架不抽内容） -->
  <section class="story-section" :style="{ background: palette.bg, borderColor: palette.line }">
    <header v-if="title || index" class="story-head">
      <span v-if="index" class="story-index" :style="{ color: palette.accent, borderColor: palette.accent }">{{ index }}</span>
      <h2 v-if="title" class="story-title" :style="{ color: palette.text }">{{ title }}</h2>
    </header>
    <slot />
  </section>
</template>

<script setup lang="ts">
import type { StoryPalette } from './palette'

defineProps<{
  /** 幕序号（如 '02'）：分镜本身是叙事序列；开场/落款等无序号幕可省略 */
  index?: string
  title?: string
  palette: StoryPalette
}>()
</script>

<style scoped>
/* html2canvas 纪律：纯色 + border + 圆角，不用 shadow/transform/动画 */
.story-section {
  border: 1px solid;
  border-radius: 18px;
  padding: 26px 28px;
  box-sizing: border-box;
}

.story-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}

.story-index {
  font-size: 13px;
  font-weight: 700;
  border: 1px solid;
  border-radius: 8px;
  padding: 2px 8px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.story-title {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 1px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>
