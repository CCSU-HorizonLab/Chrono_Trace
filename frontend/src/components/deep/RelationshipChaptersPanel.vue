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
        <span v-if="digestBadge" class="panel-badge">{{ digestBadge }}</span>
        <span v-if="summaryTask.running" class="sum-progress">
          <span class="sum-bar"><span class="sum-fill" :style="{ width: summaryTask.percent + '%' }" /></span>
          <span class="sum-step">{{ summaryTask.step }} {{ summaryTask.percent }}%</span>
        </span>
        <button v-if="summaryTask.running" class="btn" @click="cancelSummary">取消</button>
        <button
          v-else-if="payload?.ok"
          class="btn"
          :disabled="starting"
          @click="startSummary"
        >{{ startLabel }}</button>
        <button v-if="error" class="btn" @click="load">重试</button>
      </div>
    </div>

    <div v-if="summaryError" class="sum-error">{{ summaryError }}</div>

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

      <!-- 最初 → 现在：首末章对照 hero（纯前端拼装，单章不成立） -->
      <div v-if="hero" class="hero-card">
        <div class="hero-side">
          <div class="hero-label">最初</div>
          <div class="hero-range">{{ toCompactRange(hero.first.from_ts, hero.first.to_ts) }}</div>
          <span v-if="hero.first.phase" class="ch-phase">{{ hero.first.phase }}</span>
          <div class="hero-stats">周均 {{ perWeek(hero.first) }} 条 · TA {{ pct(hero.first.stats.other_share) }}</div>
          <div v-if="hero.first.summary" class="hero-summary">{{ hero.first.summary }}</div>
        </div>
        <div class="hero-mid">
          <span class="hero-arrow">→</span>
          <span class="hero-span">{{ heroSpan }}</span>
        </div>
        <div class="hero-side">
          <div class="hero-label">现在</div>
          <div class="hero-range">{{ toCompactRange(hero.last.from_ts, hero.last.to_ts) }}</div>
          <span v-if="hero.last.phase" class="ch-phase">{{ hero.last.phase }}</span>
          <div class="hero-stats">周均 {{ perWeek(hero.last) }} 条 · TA {{ pct(hero.last.stats.other_share) }}</div>
          <div v-if="hero.last.summary" class="hero-summary">{{ hero.last.summary }}</div>
        </div>
      </div>

      <!-- 章节卡：竖排时间线，每章一段统计 + 相对前章的变化点；
           相邻章之间插过渡卡（什么变了/触发/什么没变，引文可回溯） -->
      <div class="chapter-list">
        <template v-for="item in timeline" :key="item.kind === 'chapter' ? `c${item.ch.index}` : `t${item.t.from_index}`">
          <div v-if="item.kind === 'chapter'" class="chapter-card">
            <div class="ch-rail">
              <span class="ch-no">{{ item.ch.index + 1 }}</span>
            </div>
            <div class="ch-body">
              <div class="ch-head">
                <span class="ch-range">{{ toCompactRange(item.ch.from_ts, item.ch.to_ts) }}</span>
                <span v-if="item.ch.phase" class="ch-phase">{{ item.ch.phase }}</span>
                <span class="ch-weeks">{{ item.ch.stats.weeks }} 周</span>
              </div>
              <div class="ch-stats">
                <span>{{ item.ch.stats.texts }} 条</span>
                <span>TA 占比 {{ pct(item.ch.stats.other_share) }}</span>
                <span v-if="item.ch.stats.pos_ratio != null">正向 {{ pct(item.ch.stats.pos_ratio) }}</span>
                <span v-if="item.ch.stats.latency_hours != null">回复约 {{ latencyText(item.ch.stats.latency_hours) }}</span>
              </div>
              <div v-if="item.ch.changes.length" class="ch-changes">
                <span
                  v-for="c in item.ch.changes" :key="c.key" class="chg"
                  :class="c.direction"
                >{{ c.label }} {{ c.direction === 'up' ? '↑' : '↓' }}</span>
              </div>
              <div v-else-if="item.ch.index > 0" class="ch-stable">与前一章相比节奏平稳</div>
              <div v-if="item.ch.summary" class="ch-summary">{{ item.ch.summary }}</div>
            </div>
          </div>
          <div v-else class="transition-card">
            <div class="tr-head">第{{ item.t.from_index + 1 }} → {{ item.t.to_index + 1 }}章之间</div>
            <div class="tr-changed">{{ item.t.what_changed }}</div>
            <div v-if="item.t.trigger || item.t.what_stayed" class="tr-sub">
              <span v-if="item.t.trigger">转折 {{ item.t.trigger }}</span>
              <span v-if="item.t.trigger && item.t.what_stayed"> · </span>
              <span v-if="item.t.what_stayed">保持 {{ item.t.what_stayed }}</span>
            </div>
            <div v-if="item.t.evidence.length" class="tr-evidence">
              <span v-for="(e, j) in item.t.evidence" :key="j" class="tr-quote">「{{ e }}」</span>
            </div>
          </div>
        </template>
      </div>

      <!-- 全局弧线：全部章节就绪后的一次全局归并（转折点自带章号可回溯） -->
      <div v-if="arc" class="arc-card">
        <div class="arc-title">全局弧线</div>
        <div class="arc-text">{{ arc.arc }}</div>
        <div v-if="arc.turning_points.length" class="arc-points">
          <div v-for="(tp, j) in arc.turning_points" :key="j" class="arc-tp">{{ tp }}</div>
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
  summary?: string
  phase?: string
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

type Transition = {
  from_index: number
  to_index: number
  what_changed: string
  trigger: string
  what_stayed: string
  evidence: string[]
}

type Arc = { arc: string; turning_points: string[] }

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
  summary?: {
    months_total: number
    months_ready: number
    chapters_ready: number
    transitions_ready?: number
    arc_ready?: boolean
    transitions?: Transition[]
    arc?: Arc | null
  }
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

// C3 叙事层产物：过渡卡按前章 index 对位插入；弧线整块渲染
const transitions = computed(() => summaryInfo.value?.transitions || [])
const arc = computed(() => summaryInfo.value?.arc || null)

type TimelineItem =
  | { kind: 'chapter'; ch: Chapter }
  | { kind: 'transition'; t: Transition }

const timeline = computed<TimelineItem[]>(() => {
  const list = chapters.value
  const byFrom = new Map(transitions.value.map((t) => [t.from_index, t]))
  const out: TimelineItem[] = []
  list.forEach((ch, i) => {
    out.push({ kind: 'chapter', ch })
    if (i + 1 < list.length) {
      const t = byFrom.get(ch.index)
      if (t && t.to_index === list[i + 1].index) out.push({ kind: 'transition', t })
    }
  })
  return out
})

// 最初 → 现在 hero：首末章对照，单章不成立
const hero = computed(() => {
  const list = chapters.value
  if (list.length < 2) return null
  return { first: list[0], last: list[list.length - 1] }
})

const heroSpan = computed(() => {
  const h = hero.value
  return h ? spanText(h.first.from_ts, h.last.to_ts) : ''
})

function spanText(fromTs: number, toTs: number): string {
  const days = Math.max(1, Math.round((toTs - fromTs) / 86400))
  if (days >= 365) {
    const years = days / 365
    return `历时 ${years >= 10 ? Math.round(years) : years.toFixed(1).replace(/\.0$/, '')} 年`
  }
  if (days >= 60) return `历时 ${Math.round(days / 30)} 个月`
  return `历时 ${days} 天`
}

function perWeek(ch: Chapter): number {
  return Math.round(ch.stats.texts / Math.max(ch.stats.weeks, 1))
}

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

// ---------------------------------------------------------------------------
// 摘要金字塔任务（月摘要→章节归并，后台 LLM）：启动 / 轮询 / 取消。
// 完成后重拉 payload 拿各章摘要文本；运行中每 2s 轮询进度。
// ---------------------------------------------------------------------------
const summaryTask = ref({ running: false, percent: 0, step: '', monthsDone: 0, monthsTotal: 0 })
const starting = ref(false)
const summaryError = ref('')
let pollTimer: number | null = null
let pollTaskId = ''

const summaryInfo = computed(() => payload.value?.summary)
const digestBadge = computed(() => {
  const info = summaryInfo.value
  if (!info || !info.months_total || summaryTask.value.running) return ''
  if (info.arc_ready) return '叙事就绪'
  if (info.months_ready >= info.months_total && info.chapters_ready >= (chapters.value.length || 1)) {
    return '摘要就绪'
  }
  return info.months_ready ? `摘要 ${info.months_ready}/${info.months_total} 月` : ''
})
const startLabel = computed(() =>
  summaryInfo.value?.months_ready ? '续算摘要' : '全量摘要',
)

function stopPoll() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function poll(taskId: string) {
  stopPoll()
  pollTaskId = taskId
  pollTimer = window.setInterval(async () => {
    const epoch = props.viewEpoch
    const res = await api.get_chapter_summaries_progress(taskId).catch(() => null)
    if (epoch !== props.viewEpoch) {
      stopPoll()
      summaryTask.value.running = false
      return
    }
    if (!res?.ok) return
    summaryTask.value = {
      running: res.status === 'running',
      percent: res.progress_percent || 0,
      step: res.current_step || '',
      monthsDone: res.months_done || 0,
      monthsTotal: res.months_total || 0,
    }
    if (res.status === 'failed') {
      summaryError.value = res.error || '摘要任务失败'
    }
    if (res.status !== 'running') {
      stopPoll()
      load() // 终态刷新：各章摘要文本随 payload 下发
    }
  }, 2000)
}

async function startSummary() {
  starting.value = true
  summaryError.value = ''
  try {
    const res = await api.start_chapter_summaries(props.conversationId)
    if (res?.ok && res.task_id) {
      summaryTask.value.running = true
      poll(String(res.task_id))
    } else if (res?.status === 'complete') {
      await load()
    } else {
      summaryError.value = res?.error || '摘要任务启动失败'
    }
  } catch (e: any) {
    summaryError.value = e?.message || '摘要任务启动失败'
  } finally {
    starting.value = false
  }
}

async function cancelSummary() {
  await api.cancel_chapter_summaries(pollTaskId || undefined).catch(() => null)
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
      // 逐字竖排：分布带行高 46px 只容得下窄列，横排三字会压进 y 轴标签区
      text: (labels[dim] || dim).split('').join('\n'),
      left: 4, top: top + 3,
      textStyle: { fontSize: 11, color: textSecondary, lineHeight: 13 },
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

watch(() => [props.conversationId, props.viewEpoch], () => {
  stopPoll() // 切会话：旧会话的摘要轮询不再有意义（后端任务自身照跑完落库）
  summaryTask.value = { running: false, percent: 0, step: '', monthsDone: 0, monthsTotal: 0 }
  summaryError.value = ''
  load()
})

onUnmounted(() => {
  stopPoll()
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

/* 阶段徽标（观察叙事措辞）：tint 底胶囊，与变化点 chips 同惯用语 */
.ch-phase {
  padding: 1px 8px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
  font-size: var(--ct-text-xs);
  white-space: nowrap;
}

/* 章节叙事（摘要金字塔产物）：正文次色小字，统计行之下 */
.ch-summary {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  line-height: 1.6;
  margin-top: 4px;
}

/* 最初 → 现在 hero：首末章对照，中间历时箭头 */
.hero-card {
  display: flex;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-sm);
}

.hero-side {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-sm) var(--ct-space-md);
}

.hero-label {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.hero-range {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-bold);
}

.hero-stats {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  font-variant-numeric: tabular-nums;
}

.hero-summary {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.hero-mid {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.hero-arrow {
  color: var(--ct-color-primary);
  font-size: var(--ct-text-lg);
  line-height: 1;
}

.hero-span {
  white-space: nowrap;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

/* 过渡卡：相邻章之间的缩小对比卡，缩进对齐章体列（左缘=章序号宽+列间距） */
.transition-card {
  margin-left: calc(22px + var(--ct-space-md));
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-xs) var(--ct-space-md);
}

.tr-head {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  font-variant-numeric: tabular-nums;
}

.tr-changed {
  margin-top: 2px;
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
}

.tr-sub {
  margin-top: 2px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.tr-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-md);
  margin-top: 3px;
}

/* 引文：逐字摘自章叙事的可回溯证据（后端已做子串校验） */
.tr-quote {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

/* 全局弧线：章节时间线之后的全局归并块，转折点自带章号 */
.arc-card {
  margin-top: var(--ct-space-sm);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-sm) var(--ct-space-md);
}

.arc-title {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-bold);
}

.arc-text {
  margin-top: 4px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
  line-height: 1.7;
}

.arc-points {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.arc-tp {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  line-height: 1.6;
}

/* 摘要任务进度：细进度条 + 当前步骤（2s 轮询） */
.sum-progress {
  display: inline-flex;
  align-items: center;
  gap: var(--ct-space-xs);
}

.sum-bar {
  width: 96px;
  height: 4px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-bg-sunken);
  overflow: hidden;
}

.sum-fill {
  display: block;
  height: 100%;
  background: var(--ct-color-primary);
  transition: width 0.4s ease;
}

.sum-step {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.sum-error {
  margin-bottom: var(--ct-space-sm);
  color: var(--ct-color-error);
  font-size: var(--ct-text-xs);
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
