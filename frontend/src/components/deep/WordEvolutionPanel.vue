<template>
  <div class="panel word-evolution">
    <div class="panel-head">
      <div>
        <div class="panel-title">词云演变</div>
        <div class="panel-sub">时间窗均分为 {{ segmentList.length }} 段，对比你们聊得最多的词有什么不同</div>
      </div>
      <div class="panel-actions">
        <div role="group" aria-label="词云视角">
          <button
            v-for="option in perspectiveOptions"
            :key="option.value"
            class="btn"
            :class="{ active: perspective === option.value }"
            @click="perspective = option.value"
          >{{ option.label }}</button>
        </div>
      </div>
    </div>

    <div v-if="evolution?.error" class="empty-state">{{ evolution.error }}</div>
    <div v-else-if="!segmentList.length" class="empty-state">所选区间暂无文本消息</div>
    <template v-else>
      <div class="caliber-row">
        <span class="panel-badge" :class="{ enhanced: evolution.caliber === 'cleaned' }">{{ caliberLabel }}</span>
        <span class="caliber-note">{{ caliberNote }}</span>
      </div>

      <div class="segments-grid" :style="{ gridTemplateColumns: `repeat(${segmentList.length}, 1fr)` }">
        <div v-for="(seg, index) in segmentList" :key="index" class="segment-col">
          <div class="seg-head">
            <span class="seg-range">{{ toCompactRange(seg.from_ts, seg.to_ts) }}</span>
            <span v-if="seg.truncated" class="pill" title="消息过多，已等距抽样前 1.5 万条">已抽样</span>
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
import { toCompactRange } from '@/utils/datetime'

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
}>()

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
</script>

<style scoped>
.caliber-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-md);
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

.seg-range {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.seg-empty {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  padding: var(--ct-space-lg) 0;
  text-align: center;
}
</style>
