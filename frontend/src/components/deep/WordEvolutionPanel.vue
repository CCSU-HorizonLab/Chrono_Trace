<template>
  <div class="word-evolution card">
    <div class="panel-header">
      <div>
        <div class="panel-title">词云演变</div>
        <div class="panel-sub">把时间窗均分为 {{ segments }} 段，对比你们聊得最多的词有什么不同</div>
      </div>
      <div class="control-group">
        <div class="perspective-group" role="group" aria-label="词云分段数">
          <button
            v-for="n in segmentOptions"
            :key="n"
            class="btn seg-btn"
            :class="{ active: segments === n }"
            @click="emit('update:segments', n)"
          >{{ n }} 段</button>
        </div>
        <div class="perspective-group" role="group" aria-label="词云视角">
          <button
            v-for="option in perspectiveOptions"
            :key="option.value"
            class="btn perspective-btn"
            :class="{ active: perspective === option.value }"
            @click="perspective = option.value"
          >{{ option.label }}</button>
        </div>
      </div>
    </div>

    <div v-if="evolution?.error" class="empty">{{ evolution.error }}</div>
    <div v-else-if="!segmentList.length" class="empty">所选区间暂无文本消息</div>
    <template v-else>
      <div class="caliber-row">
        <span class="badge" :class="`badge-${evolution.caliber}`">{{ caliberLabel }}</span>
        <span class="caliber-note">{{ caliberNote }}</span>
      </div>

      <div class="segments-grid" :style="{ gridTemplateColumns: `repeat(${segmentList.length}, 1fr)` }">
        <div v-for="(seg, index) in segmentList" :key="index" class="segment-col">
          <div class="seg-head">
            <span class="seg-tag">第 {{ index + 1 }} 段</span>
            <span class="seg-range">{{ fmtDate(seg.from_ts) }} ~ {{ fmtDate(seg.to_ts) }}</span>
            <span v-if="seg.truncated" class="seg-truncated" title="消息过多，已等距抽样前 1.5 万条">已抽样</span>
          </div>
          <div v-if="currentWords(seg).length" class="seg-cloud">
            <WordCloud :words="currentWords(seg)" :limit="40" />
          </div>
          <div v-else class="seg-empty">这段没有足够的文本</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import WordCloud from '@/components/charts/WordCloud.vue'
import { toLocalDateKey } from '@/utils/datetime'

type WordItem = { word: string; weight: number }

type Segment = {
  from_ts: number
  to_ts: number
  truncated: boolean
  sampled: number
  total: number
  words: { all: WordItem[]; me: WordItem[]; other: WordItem[] }
}

const props = defineProps<{
  evolution: {
    caliber: 'cleaned' | 'raw' | 'none'
    coverage_ratio: number
    segments: Segment[]
    error?: string
  }
  /** 分段数（2~6）；选择器经 update:segments 冒泡，父级重拉数据 */
  segments: number
}>()

const emit = defineEmits<{ (e: 'update:segments', value: number): void }>()

// 与后端 DEEP_WORDCLOUD_SEGMENTS_MIN/MAX 对齐
const segmentOptions = [2, 3, 4, 5, 6]

const perspective = ref<'all' | 'me' | 'other'>('all')
const perspectiveOptions = [
  { value: 'all' as const, label: '双方' },
  { value: 'me' as const, label: '我' },
  { value: 'other' as const, label: 'TA' },
]

const segmentList = computed(() => props.evolution?.segments || [])

function currentWords(seg: Segment): WordItem[] {
  return seg?.words?.[perspective.value] || []
}

const caliberLabel = computed(
  () => ({ cleaned: '清洗口径', raw: '原始文本口径', none: '无数据' } as Record<string, string>)[props.evolution?.caliber] || '未知口径',
)

// 口径由清洗覆盖率整窗二选一，绝不各段混用（见 docs/analysis/time-depth.md）
const caliberNote = computed(() => {
  if (props.evolution?.caliber === 'cleaned') {
    return '已用分析清洗后的文本（去表情/XML/系统消息），词更干净'
  }
  if (props.evolution?.caliber === 'raw') {
    return '该会话尚未全面分析（清洗文本覆盖率 '
      + Math.round((props.evolution?.coverage_ratio || 0) * 100)
      + '%），各段统一用原始消息文本，保证口径一致'
  }
  return ''
})

function fmtDate(tsSeconds: number): string {
  return toLocalDateKey(new Date(tsSeconds * 1000))
}
</script>

<style scoped>
.card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: var(--ct-space-lg);
  margin-bottom: var(--ct-space-lg);
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ct-space-md);
  margin-bottom: var(--ct-space-md);
  flex-wrap: wrap;
}

.panel-title {
  font-size: var(--ct-text-base);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
}

.panel-sub {
  margin-top: 2px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.control-group {
  display: flex;
  gap: var(--ct-space-sm);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.perspective-group {
  display: flex;
  gap: var(--ct-space-xs);
  flex-shrink: 0;
}

.btn {
  padding: 5px 12px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-surface);
  color: var(--ct-text-secondary);
  border-radius: 999px;
  cursor: pointer;
  font-size: var(--ct-text-xs);
  transition: all 0.2s ease;
}

.seg-btn.active,
.perspective-btn.active {
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  border-color: var(--ct-color-primary);
}

.caliber-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-md);
}

.badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--ct-text-xs);
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
  flex-shrink: 0;
}

.badge-cleaned {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.caliber-note {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.segments-grid {
  display: grid;
  gap: var(--ct-space-md);
}

@media (max-width: 900px) {
  .segments-grid {
    grid-template-columns: 1fr !important;
  }
}

.segment-col {
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  min-width: 0;
}

.seg-head {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-sm);
  flex-wrap: wrap;
}

.seg-tag {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.seg-range {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.seg-truncated {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.seg-empty {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  padding: var(--ct-space-lg) 0;
  text-align: center;
}

.empty {
  color: var(--ct-text-tertiary);
  padding: var(--ct-space-xl) 0;
  text-align: center;
}
</style>
