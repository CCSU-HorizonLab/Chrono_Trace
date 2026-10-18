<template>
  <div class="story-bignum">
    <div class="num-row" :style="{ color: tone === 'sub' ? palette.sub : palette.accent }">
      <span class="num">{{ value }}</span>
      <span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <p v-if="caption" class="caption" :style="{ color: palette.muted }">{{ caption }}</p>
  </div>
</template>

<script setup lang="ts">
import type { StoryPalette } from './palette'

withDefaults(
  defineProps<{
    /** 预格式化数字文本（万/亿换算与精度由调用方决定） */
    value: string
    unit?: string
    caption?: string
    palette: StoryPalette
    tone?: 'accent' | 'sub'
  }>(),
  { tone: 'accent' },
)
</script>

<style scoped>
/* 大数字固定得意黑；容器不定宽——GB2312 外字符回退栈的宽度差由
   数字自身 display 吸收，不塌布局 */
.num-row {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
}

.num {
  font-size: 84px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -2px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.unit {
  font-size: 24px;
  font-weight: 700;
}

.caption {
  margin-top: 8px;
  text-align: center;
  font-size: 15px;
  line-height: 1.6;
}
</style>
