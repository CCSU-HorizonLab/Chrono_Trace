<template>
  <!-- 时光机时间线：kind → 字标与文案的映射固定在本组件，模板不重复实现 -->
  <ol class="story-timeline">
    <li v-for="(item, i) in items" :key="i" class="tl-item">
      <span class="tl-rail">
        <span
          class="tl-dot"
          :style="{ borderColor: palette.accent, color: palette.accent }"
        >{{ glyphOf(item) }}</span>
        <span v-if="i < items.length - 1" class="tl-line" :style="{ background: palette.line }" />
      </span>
      <div class="tl-body">
        <div class="tl-title" :style="{ color: palette.text }">{{ titleOf(item) }}</div>
        <div class="tl-sub" :style="{ color: palette.muted }">{{ subOf(item) }}</div>
      </div>
      <span class="tl-date" :style="{ color: palette.sub }">{{ dateOf(item) }}</span>
    </li>
  </ol>
</template>

<script setup lang="ts">
import type { PosterMilestone } from '../registry'
import type { StoryPalette } from './palette'
import { toLocalDateKey } from '@/utils/datetime'

defineProps<{
  items: PosterMilestone[]
  palette: StoryPalette
}>()

function glyphOf(item: PosterMilestone): string {
  if (item.kind === 'first_message') return '始'
  if (item.kind === 'count_mark') return '言'
  return '默'
}

function titleOf(item: PosterMilestone): string {
  if (item.kind === 'first_message') {
    return item.scope === 'global' ? '初次相遇' : '这段时光的开始'
  }
  if (item.kind === 'count_mark') {
    const mark = item.mark ?? 0
    return mark >= 10000 ? `第一万句话来的时候，是第 ${(mark / 10000).toFixed(mark % 10000 ? 1 : 0)} 万条` : `说到第 ${mark.toLocaleString('zh-CN')} 条`
  }
  return '最长的沉默'
}

function subOf(item: PosterMilestone): string {
  if (item.kind === 'first_message') {
    return item.scope === 'global' ? '你们的第一条消息' : '这段窗口里的第一条消息'
  }
  if (item.kind === 'count_mark') return '消息量关口'
  return `沉默了 ${item.days ?? 0} 天，然后又聊上了`
}

function dateOf(item: PosterMilestone): string {
  const ts = item.kind === 'longest_silence' ? item.from_ts : item.ts
  return ts ? toLocalDateKey(new Date(ts * 1000)) : ''
}
</script>

<style scoped>
.story-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}

.tl-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.tl-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: none;
}

.tl-dot {
  width: 34px;
  height: 34px;
  border: 1px solid;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
}

.tl-line {
  width: 1px;
  flex: 1;
  min-height: 18px;
}

.tl-body {
  flex: 1;
  min-width: 0;
  padding-top: 4px;
}

.tl-title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.4;
}

.tl-sub {
  margin-top: 3px;
  font-size: 13px;
  line-height: 1.5;
}

.tl-date {
  flex: none;
  padding-top: 6px;
  font-size: 13px;
  font-weight: 600;
}
</style>
