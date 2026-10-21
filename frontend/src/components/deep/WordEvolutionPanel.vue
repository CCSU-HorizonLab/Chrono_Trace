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

      <!-- 重点词排行流动（bump）：只挑「排名有变化」的词——泛高频词各段都
           靠前、方差为 0 自然沉底，回答的是「什么词起来了、什么沉下去了」 -->
      <div v-if="bumpWords.length" class="bump-block">
        <div class="block-title">
          重点词排行流动
          <span class="block-note">点击折线或下方词云中的词可固定高亮</span>
        </div>
        <div ref="bumpRef" class="bump-chart" />
      </div>
      <div v-else class="bump-empty">各段高频词很稳定，没有明显流动</div>

      <div class="segments-grid" :style="{ gridTemplateColumns: `repeat(${segmentList.length}, 1fr)` }">
        <div v-for="(seg, index) in segmentList" :key="index" class="segment-col">
          <div class="seg-head">
            <span class="seg-range">{{ toCompactRange(seg.from_ts, seg.to_ts) }}</span>
            <span v-if="seg.truncated" class="pill" title="消息过多，已等距抽样前 1.5 万条">已抽样</span>
          </div>
          <div v-if="currentWords(seg).length" class="seg-cloud">
            <WordCloud :words="currentWords(seg)" :limit="40" :highlight="pinnedWord" @select="togglePin" />
          </div>
          <div v-else class="seg-empty">这段没有足够的文本</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
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

// ---------------------------------------------------------------------------
// 重点词排行流动：各段 words 数组顺序即排名（后端 most_common 序）。
// weight 是段内归一化 1-100 跨段不可比，选词一律用排名。挑「≥2 段出现
// 且排名有变化」里排名方差最大的 8 个——有变化才有「流动」故事。
// ---------------------------------------------------------------------------
const BUMP_WORD_LIMIT = 8

const bumpWords = computed<{ word: string; ranks: Array<number | null> }[]>(() => {
  const segs = segmentList.value
  if (segs.length < 2) return []
  const ranks = new Map<string, Array<number | null>>()
  segs.forEach((seg, segIndex) => {
    currentWords(seg).forEach((item, index) => {
      let arr = ranks.get(item.word)
      if (!arr) {
        arr = new Array<number | null>(segs.length).fill(null)
        ranks.set(item.word, arr)
      }
      arr[segIndex] = index + 1
    })
  })
  return [...ranks.entries()]
    .map(([word, arr]) => {
      const present = arr.filter((r): r is number => r != null)
      const mean = present.reduce((a, b) => a + b, 0) / (present.length || 1)
      const variance = present.reduce((a, b) => a + (b - mean) ** 2, 0) / (present.length || 1)
      const changed = new Set(present).size > 1
      return { word, ranks: arr, eligible: present.length >= 2 && changed, score: variance }
    })
    .filter((x) => x.eligible)
    .sort((a, b) => b.score - a.score)
    .slice(0, BUMP_WORD_LIMIT)
    .map(({ word, ranks: arr }) => ({ word, ranks: arr }))
})

// 固定高亮词（点击词/折线切换）：bump 折线与各段词云同时高亮
const pinnedWord = ref<string | null>(null)

function togglePin(word?: string) {
  if (!word) return
  pinnedWord.value = pinnedWord.value === word ? null : word
}

// bump 折线配色：静态全部中性灰（身份由行末直标承载），钉选词墨紫加粗、
// 其余淡化——「一词是主角、其余是上下文」的 emphasis 形态，避免 8 色线糊
const LINE_BASE = '#9B95A5'
const LINE_PINNED = '#5A4BC4'

const bumpRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function buildOption(): echarts.EChartsOption {
  const css = (name: string, fallback: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
  const textTertiary = css('--ct-text-tertiary', '#9B95A5')
  const textSecondary = css('--ct-text-secondary', '#5A5566')
  const borderColor = css('--ct-border-color', '#E9E5DF')
  const segLabels = segmentList.value.map((s) => toCompactRange(s.from_ts, s.to_ts))
  const maxRank = Math.max(8, ...bumpWords.value.flatMap((w) => w.ranks.filter((r): r is number => r != null)))
  const hasPin = !!pinnedWord.value
  return {
    grid: { left: 8, right: 96, top: 14, bottom: 26 },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const rank = Array.isArray(p.value) ? p.value[1] : p.value
        const seg = segLabels[p.dataIndex] || ''
        return `${p.seriesName}<br/>${seg}：${rank != null ? `第 ${rank} 名` : '未进该段前 30'}`
      },
    },
    xAxis: {
      type: 'category',
      data: segLabels,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: borderColor } },
      axisLabel: { color: textSecondary, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      inverse: true,
      min: 1,
      max: maxRank + 1,
      axisLabel: { color: textTertiary, fontSize: 11, formatter: (v: number) => `第${v}` },
      splitLine: { lineStyle: { color: borderColor } },
    },
    series: bumpWords.value.map(({ word, ranks }) => {
      const pinned = pinnedWord.value === word
      const faded = hasPin && !pinned
      return {
        name: word,
        type: 'line' as const,
        data: ranks,
        connectNulls: false,
        lineStyle: { width: pinned ? 3 : 2, color: pinned ? LINE_PINNED : LINE_BASE, opacity: faded ? 0.25 : 0.9 },
        itemStyle: { color: pinned ? LINE_PINNED : LINE_BASE, opacity: faded ? 0.25 : 1 },
        symbol: 'circle',
        symbolSize: 8,
        emphasis: { focus: 'series', lineStyle: { width: 3 } },
        endLabel: { show: true, formatter: () => word, color: pinned ? LINE_PINNED : textSecondary, fontSize: 11 },
        labelLayout: { hideOverlap: true },
      }
    }),
  }
}

// v-if 与数据都可能迟到（骨架→payload、切视角后才有可流动词），init 收进
// ensureChart 幂等化；watch 用 post flush 保证 bumpRef 已挂载
function ensureChart() {
  if (!bumpRef.value || chartInstance || !bumpWords.value.length) return
  chartInstance = echarts.init(bumpRef.value)
  chartInstance.setOption(buildOption())
  chartInstance.on('click', (params: any) => togglePin(params?.seriesName))
  resizeObserver = new ResizeObserver(() => chartInstance?.resize())
  resizeObserver.observe(bumpRef.value)
}

onMounted(() => nextTick(ensureChart))

watch([bumpWords, pinnedWord, () => perspective.value], () => {
  ensureChart()
  chartInstance?.setOption(buildOption(), { notMerge: true })
}, { flush: 'post' })

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chartInstance?.dispose()
  chartInstance = null
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

.bump-block {
  margin-bottom: var(--ct-space-md);
}

.block-title {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
  margin-bottom: var(--ct-space-xs);
}

.block-note {
  color: var(--ct-text-tertiary);
  font-weight: normal;
  font-size: var(--ct-text-xs);
  margin-left: var(--ct-space-sm);
}

.bump-chart {
  width: 100%;
  height: 236px;
}

.bump-empty {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  margin-bottom: var(--ct-space-md);
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
  background: var(--ct-bg-sunken);
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
