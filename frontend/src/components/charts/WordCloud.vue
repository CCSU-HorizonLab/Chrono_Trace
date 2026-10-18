<template>
  <div class="wordcloud">
    <div v-if="!words?.length" class="empty">暂无词云</div>
    <div v-else class="cloud">
      <span v-for="(w, i) in topWords" :key="i" class="item" :style="styleFor(w)" @click="$emit('select', w.word)" :title="`${w.word} (${w.weight})`">{{ w.word }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  words: { word: string; weight: number }[]
  limit?: number
  /** 高亮词（词云演变联动）：命中词放大着主色，其余淡化 */
  highlight?: string
}>()
const topWords = computed(() => (props.words || []).slice(0, props.limit || 80))

function styleFor(w: { word: string; weight: number }) {
  const weights = topWords.value.map(x => x.weight)
  const minW = Math.min(...weights, 1)
  const maxW = Math.max(...weights, 1)
  const t = (w.weight - minW) / (maxW - minW || 1)
  const font = 12 + t * 20
  const hue = 230 - Math.round(t * 140)
  if (!props.highlight) {
    return { fontSize: font + 'px', color: `hsl(${hue} 70% 45%)` }
  }
  if (w.word === props.highlight) {
    return { fontSize: font + 4 + 'px', color: '#7c4dff', fontWeight: 600 }
  }
  return { fontSize: font + 'px', color: `hsl(${hue} 70% 45%)`, opacity: 0.35 }
}
</script>

<style scoped>
.cloud { display: flex; flex-wrap: wrap; gap: 8px 10px; }
.item { cursor: pointer; user-select: none; line-height: 1; }
.empty { color: #6b7280; }
</style>
