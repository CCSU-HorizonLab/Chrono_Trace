<template>
  <div class="panel chapters-panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">关系章节</div>
        <div class="panel-sub">
          按消息密度、TA 占比、正向情绪、回复时延的统计变点自动切分——看这段关系的自然段落
        </div>
      </div>
      <div class="panel-actions">
        <span class="panel-badge">本地统计</span>
        <button v-if="error" class="btn" @click="load">重试</button>
      </div>
    </div>

    <div v-if="error && !payload" class="empty-state">{{ error }}</div>
    <div v-else-if="loading && !payload" class="skeleton sk-chapters" />
    <div v-else-if="payload && !payload.ok" class="empty-state">
      {{ payload.message || '这段对话还不足以划分章节' }}
    </div>

    <template v-else-if="payload">
      <!-- 顶部：周量柱（我/TA 堆叠）+ 章节分界线；下方大五 5 行分布带
           （每周一点=该周语言风格代理分，线=5 周滚动中位数；空点=样本薄诚实留白） -->
      <div ref="chartRef" class="chapters-chart" />
      <div v-if="!hasAnyBig5" class="band-note">
        各周单侧文本多不足 {{ minSideTexts }} 条，大五分布带暂无可靠样本
      </div>

      <div v-if="chapters.length <= 1" class="band-note">
        暂未检测到明显的章节变化——整体是一段连续的时光
      </div>

      <!-- 章节卡：竖排时间线，每章一段统计 + 相对前章的变化点 -->
      <div class="chapter-list">
        <div v-for="ch in chapters" :key="ch.index" class="chapter-card">
          <div class="ch-rail">
            <span class="ch-no">{{ ch.index + 1 }}</span>
          </div>
          <div class="ch-body">
            <div class="ch-head">
              <span class="ch-range">{{ toCompactRange(ch.from_ts, ch.to_ts) }}</span>
              <span class="ch-weeks">{{ ch.stats.weeks }} 周</span>
            </div>
            <div class="ch-stats">
              <span>{{ ch.stats.texts }} 条</span>
              <span>TA 占比 {{ pct(ch.stats.other_share) }}</span>
              <span v-if="ch.stats.pos_ratio != null">正向 {{ pct(ch.stats.pos_ratio) }}</span>
              <span v-if="ch.stats.latency_hours != null">回复约 {{ latencyText(ch.stats.latency_hours) }}</span>
            </div>
            <div v-if="ch.changes.length" class="ch-changes">
              <span
                v-for="c in ch.changes" :key="c.key" class="chg"
                :class="c.direction"
              >{{ c.label }} {{ c.direction === 'up' ? '↑' : '↓' }}</span>
            </div>
            <div v-else-if="ch.index > 0" class="ch-stable">与前一章相比节奏平稳</div>
          </div>
        </div>
      </div>

      <div class="disclaimer">
        章节边界由统计变点切出、只作观察叙事（非关系诊断）；大五为语言风格代理分的相对演变，非心理测评
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { api } from '@/api/bridge'
import { toCompactRange } from '@/utils/datetime'
import { BIG5_COLOR_ME, BIG5_COLOR_OTHER, BIG5_DIM_ORDER } from './big5Shared'

type Change = { key: string; label: string; direction: 'up' | 'down'; delta: number }
type Chapter = {
  index: number
  week_index: number
  from_ts: number
  to_ts: number
  stats: {
    texts: number
    me_texts: number
    other_texts: number
    other_share: number | null
    pos_ratio: number | null
    latency_hours: number | null
    weeks: number
  }
  changes: Change[]
}

type ChaptersPayload = {
  ok: boolean
  message?: string
  version: number
  span: { week_count: number; week_seconds: number }
  week_starts: number[]
  big5_labels: Record<string, string>
  weekly: {
    texts_me: number[]
    texts_other: number[]
    big5: Record<'me' | 'other', Record<string, Array<number | null>>>
  }
  chapters: Chapter[]
}

const props = defineProps<{
  conversationId: number
  /** 父页视图纪元：切换会话/账号时丢弃过期响应 */
  viewEpoch: number
}>()

const payload = ref<ChaptersPayload | null>(null)
const loading = ref(false)
const error = ref('')

const chapters = computed(() => payload.value?.chapters || [])
const minSideTexts = 10

const hasAnyBig5 = computed(() => {
  const big5 = payload.value?.weekly?.big5
  if (!big5) return false
  const sides = [big5.me, big5.other]
  return BIG5_DIM_ORDER.some((dim) =>
    sides.some((s) => (s[dim] || []).some((v) => v != null)),
  )
})

async function load() {
  const epoch = props.viewEpoch
  loading.value = true
  error.value = ''
  try {
    const result = await api.get_relationship_chapters(props.conversationId)
    if (epoch !== props.viewEpoch) return
    payload.value = result
  } catch (e: any) {
    if (epoch !== props.viewEpoch) return
    error.value = e?.message || '请求失败'
  } finally {
    if (epoch === props.viewEpoch) loading.value = false
  }
}

function pct(v: number | null | undefined): string {
  return v == null ? '—' : Math.round(v * 100) + '%'
}

function latencyText(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)} 分钟`
  if (hours < 48) return `${Math.round(hours)} 小时`
  return `${(hours / 24).toFixed(1)} 天`
}

// ---------------------------------------------------------------------------
// 图：一个 echarts 实例、6 个 grid——顶部周量堆叠柱，下接大五 5 行分布带。
// 每行：周点（原始代理分，半透明小点）+ 5 周滚动中位线；章节边界为竖虚线，
// 贯穿全部行，把「章」钉在时间轴上。实体色单源 big5Shared（我墨紫/TA 琥珀）。
// ---------------------------------------------------------------------------
const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const GRID_TOP = 30
const VOL_H = 84
const BAND_H = 46
const BAND_GAP = 22

function rollingMedian(values: Array<number | null>, half = 2): Array<number | null> {
  return values.map((_, i) => {
    const window = values
      .slice(Math.max(0, i - half), i + half + 1)
      .filter((v): v is number => v != null)
    if (!window.length) return null
    window.sort((a, b) => a - b)
    const mid = window.length >> 1
    return window.length % 2
      ? window[mid]
      : (window[mid - 1] + window[mid]) / 2
  })
}

function fmtWeek(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function fmtWeekFull(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

// x 轴标签随跨度自适应：582 周标「8/31」毫无信息量——半年内标月/日，
// 两年半内标每月首周（YY/M），更长只标每年首周（YYYY）
function axisWeekLabels(weekStarts: number[]): string[] {
  const n = weekStarts.length
  if (n <= 27) return weekStarts.map(fmtWeek)
  const out: string[] = []
  let last = -1
  for (const ts of weekStarts) {
    const d = new Date(ts * 1000)
    if (n <= 130) {
      const m = d.getFullYear() * 12 + d.getMonth()
      out.push(m !== last ? `${String(d.getFullYear()).slice(2)}/${d.getMonth() + 1}` : '')
      last = m
    } else {
      const y = d.getFullYear()
      out.push(y !== last ? String(y) : '')
      last = y
    }
  }
  return out
}

function buildOption(): echarts.EChartsOption | null {
  const data = payload.value
  if (!data?.ok || !data.week_starts.length) return null

  const css = (name: string, fallback: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
  const textTertiary = css('--ct-text-tertiary', '#9B95A5')
  const textSecondary = css('--ct-text-secondary', '#5A5566')
  const borderColor = css('--ct-border-color', '#E9E5DF')
  const bgCard = css('--ct-bg-card', '#FFFFFF')
  const labels = data.big5_labels || {}
  const categories = axisWeekLabels(data.week_starts)
  const boundaries = data.chapters.slice(1).map((c) => ({ xAxis: c.week_index }))

  const grids: any[] = []
  const xAxes: any[] = []
  const yAxes: any[] = []
  const series: any[] = []
  const titles: any[] = [{ text: '每周消息量', left: 2, top: 6, textStyle: { fontSize: 11, color: textSecondary } }]

  grids.push({ top: GRID_TOP, left: 44, right: 8, height: VOL_H })
  xAxes.push({
    type: 'category', data: categories, gridIndex: 0,
    axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: borderColor } },
  })
  yAxes.push({
    type: 'value', gridIndex: 0, axisLabel: { fontSize: 9, color: textTertiary },
    splitLine: { lineStyle: { color: borderColor, type: 'dashed' } }, axisLine: { show: false },
  })
  series.push(
    {
      name: '我', type: 'bar', stack: 'vol', xAxisIndex: 0, yAxisIndex: 0,
      data: data.weekly.texts_me, itemStyle: { color: BIG5_COLOR_ME, opacity: 0.72 },
      barWidth: '62%',
    },
    {
      name: 'TA', type: 'bar', stack: 'vol', xAxisIndex: 0, yAxisIndex: 0,
      data: data.weekly.texts_other, itemStyle: { color: BIG5_COLOR_OTHER, opacity: 0.72 },
      barWidth: '62%',
      // 章节分界线挂在 TA 柱（永远在场），贯穿全图的视觉锚
      markLine: {
        symbol: 'none', silent: true, animation: false,
        lineStyle: { color: textTertiary, type: 'dashed', width: 1, opacity: 0.6 },
        label: { show: false }, data: boundaries,
      },
    },
  )

  BIG5_DIM_ORDER.forEach((dim, di) => {
    const gridIndex = di + 1
    const top = GRID_TOP + VOL_H + 14 + di * (BAND_H + BAND_GAP)
    grids.push({ top, left: 44, right: 8, height: BAND_H })
    titles.push({
      text: labels[dim] || dim, left: 2, top: top + BAND_H / 2 - 8,
      textStyle: { fontSize: 11, color: textSecondary },
    })
    xAxes.push({
      type: 'category', data: categories, gridIndex,
      axisLabel: { show: di === BIG5_DIM_ORDER.length - 1, fontSize: 10, color: textTertiary, hideOverlap: true },
      axisTick: { show: false }, axisLine: { lineStyle: { color: borderColor } },
    })
    yAxes.push({
      type: 'value', gridIndex, min: 0, max: 100,
      axisLabel: { fontSize: 9, color: textTertiary },
      splitLine: { show: false }, axisLine: { show: false },
    })
    for (const [sideKey, color] of [['me', BIG5_COLOR_ME], ['other', BIG5_COLOR_OTHER]] as const) {
      const scores = data.weekly.big5[sideKey]?.[dim] || []
      series.push({
        name: `${labels[dim] || dim}·${sideKey === 'me' ? '我' : 'TA'}`,
        type: 'scatter', xAxisIndex: gridIndex, yAxisIndex: gridIndex,
        data: scores, symbolSize: 4.5,
        itemStyle: { color, opacity: 0.42 },
      })
      series.push({
        type: 'line', xAxisIndex: gridIndex, yAxisIndex: gridIndex,
        data: rollingMedian(scores), symbol: 'none', smooth: false,
        lineStyle: { color, width: 2 },
        emphasis: { disabled: true }, silent: true,
        markLine: di === 0
          ? {
              symbol: 'none', silent: true, animation: false,
              lineStyle: { color: textTertiary, type: 'dashed', width: 1, opacity: 0.6 },
              label: { show: false }, data: boundaries,
            }
          : undefined,
      })
    }
  })

  const chartH = GRID_TOP + VOL_H + 14 + 5 * (BAND_H + BAND_GAP) + 18 // 末行轴标签
  return {
    animation: false,
    _chartH: chartH,
    grid: grids,
    title: titles,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      backgroundColor: bgCard, borderColor, padding: [6, 10],
      textStyle: { fontSize: 12, color: css('--ct-text-primary', '#1B1924') },
      axisPointer: { type: 'line', lineStyle: { color: textTertiary, type: 'dashed' } },
      // category 标签已折叠为年份/月份，tooltip 补完整周首日期；中位线系列无名字不占行
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params]
        if (!arr.length) return ''
        const weekIdx = arr[0].dataIndex
        const rows = arr.filter((p) => p.seriesName).map((p) => {
          const v = p.value
          const isVol = p.seriesName === '我' || p.seriesName === 'TA'
          const text = v == null ? '—' : isVol ? `${Math.round(v)} 条` : v.toFixed(1)
          return `${p.marker}${p.seriesName}　${text}`
        })
        return `<b>${fmtWeekFull(data.week_starts[weekIdx])}</b> 那周<br/>${rows.join('<br/>')}`
      },
    },
    xAxis: xAxes,
    yAxis: yAxes,
    series,
  } as any
}

function ensureChart() {
  const option = buildOption()
  if (!chartRef.value || !option) return
  // 容器高度随 grid 布局走（周量+5 行分布带+末行轴标签），echarts 以容器为准
  chartRef.value.style.height = `${(option as any)._chartH}px`
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
    resizeObserver = new ResizeObserver(() => chartInstance?.resize())
    resizeObserver.observe(chartRef.value)
  }
  chartInstance.setOption(option, { notMerge: true })
}

watch(
  [payload, () => props.viewEpoch],
  () => nextTick(() => {
    if (!payload.value?.ok) {
      chartInstance?.clear()
      return
    }
    ensureChart()
  }),
  { flush: 'post' },
)

onMounted(() => {
  load()
  nextTick(ensureChart)
})

watch(() => [props.conversationId, props.viewEpoch], load)

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.chapters-panel {
  display: flex;
  flex-direction: column;
}

.chapters-chart {
  width: 100%;
  min-height: 200px; /* ensureChart 按布局精确设置，这里只兜骨架期 */
  margin-bottom: var(--ct-space-sm);
}

.band-note {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  margin-bottom: var(--ct-space-sm);
}

.chapter-list {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.chapter-card {
  display: flex;
  gap: var(--ct-space-md);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-sm) var(--ct-space-md);
}

.ch-rail {
  display: flex;
  align-items: flex-start;
  padding-top: 2px;
}

/* 章序号：正文栈粗体，序号是结构信息（真序列）而非装饰 */
.ch-no {
  min-width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--ct-radius-sm);
  background: var(--ct-bg-card);
  color: var(--ct-text-primary);
  font-size: var(--ct-text-xs);
  font-weight: var(--ct-font-bold);
  font-variant-numeric: tabular-nums;
}

.ch-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ch-head {
  display: flex;
  align-items: baseline;
  gap: var(--ct-space-sm);
}

.ch-range {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-bold);
}

.ch-weeks {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.ch-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-md);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  font-variant-numeric: tabular-nums;
}

.ch-changes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-xs);
  margin-top: 2px;
}

/* 变化点：tint 底胶囊，方向用箭头字符（中性呈现，升降不预设好坏） */
.chg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 8px;
  border-radius: var(--ct-radius-full);
  font-size: var(--ct-text-xs);
}

.chg.up {
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
}

.chg.down {
  background: var(--ct-bg-card);
  color: var(--ct-text-secondary);
}

.ch-stable {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  margin-top: 2px;
}

.disclaimer {
  margin-top: var(--ct-space-md);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.empty-state {
  padding: var(--ct-space-lg) 0;
  text-align: center;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
}

.sk-chapters {
  height: 480px;
  border-radius: var(--ct-radius-lg);
}
</style>
