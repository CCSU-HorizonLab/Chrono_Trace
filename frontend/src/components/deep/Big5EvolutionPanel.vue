<template>
  <div class="big5-evolution card">
    <div class="panel-header">
      <div>
        <div class="panel-title">大五人格演变</div>
        <div class="panel-sub">
          把时间窗均分为 {{ segmentCount }} 段（与词云演变共用分段），看你们各自的语言风格怎么变
        </div>
      </div>
      <div class="header-right">
        <span class="badge" :class="{ 'badge-enhanced': anyEnhanced }">
          {{ anyEnhanced ? '含 AI 校正' : '本地统计' }}
        </span>
        <button v-if="!enhancingAll" class="btn enhance-btn" :disabled="busy || !enhanceable" @click="enhanceAll">
          全部增强
        </button>
        <button v-else class="btn" @click="cancelAll">取消</button>
      </div>
    </div>

    <div v-if="hint" class="hint">{{ hint }}</div>

    <div v-if="!seriesView.length" class="empty">这段时光还没有可统计的大五演变数据</div>
    <div v-else-if="!hasAnyData" class="empty">
      消息量还不足以形成稳定的风格印象（每段每侧约需 {{ minMessages }} 条以上文本）
    </div>

    <template v-else>
      <div class="legend-row">
        <span class="legend-item"><span class="swatch" :style="{ background: BIG5_COLOR_ME }" />我</span>
        <span class="legend-item"><span class="swatch" :style="{ background: BIG5_COLOR_OTHER }" />TA</span>
        <span class="legend-note">折线中断 = 该段样本不足（每侧不足 {{ minMessages }} 条）</span>
      </div>

      <div class="minis-grid">
        <div v-for="dim in dimCharts" :key="dim.key" class="mini">
          <div class="mini-head">
            <span class="mini-label">{{ dim.label }}</span>
            <span v-if="dim.trend" class="mini-trend">{{ dim.trend }}</span>
          </div>
          <svg class="mini-svg" viewBox="0 0 220 96" role="img" :aria-label="`${dim.label}随段变化`">
            <line class="axis" x1="18" y1="76" x2="212" y2="76" />
            <line class="midline" x1="18" y1="42" x2="212" y2="42" />
            <text class="midlabel" x="14" y="45">50</text>
            <template v-for="(run, ri) in dim.runs" :key="ri">
              <polyline
                v-for="(line, li) in run.lines"
                :key="`${ri}-${li}`"
                class="line"
                :stroke="run.color"
                :points="line.points"
              />
              <circle
                v-for="pt in run.points"
                :key="`${ri}-${pt.index}`"
                class="dot"
                :fill="run.color"
                :cx="pt.x"
                :cy="pt.y"
                :r="pt.r"
              >
                <title>{{ pt.title }}</title>
              </circle>
            </template>
            <text
              v-for="(x, i) in xTicks"
              :key="`x${i}`"
              class="xtick"
              :x="x"
              y="90"
              text-anchor="middle"
            >{{ i + 1 }}</text>
          </svg>
        </div>
      </div>

      <div class="segments-strip">
        <div v-for="(seg, i) in seriesView" :key="i" class="seg-item">
          <span class="seg-tag">第 {{ i + 1 }} 段</span>
          <span class="seg-range">{{ fmtDate(seg.from_ts) }} ~ {{ fmtDate(seg.to_ts) }}</span>
          <span v-if="seg.error" class="seg-error">{{ seg.error }}</span>
          <template v-else-if="seg.me || seg.other">
            <span v-if="isEnhanced(seg)" class="seg-badge">AI 增强</span>
            <button v-else class="btn seg-btn" :disabled="busy" @click="enhanceSegment(i)">
              {{ busyIndex === i ? '增强中…' : 'AI 增强本段' }}
            </button>
          </template>
          <span v-else class="seg-error">样本不足</span>
        </div>
      </div>

      <div class="disclaimer">
        语言风格印象随时间的变化，非心理测评；每段独立按该段消息统计，AI 校正为 ±15 以内有界修正
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { BIG5_COLOR_ME, BIG5_COLOR_OTHER, BIG5_DIM_ORDER } from '@/components/deep/big5Shared'
import { toLocalDateKey } from '@/utils/datetime'

type DimScore = { score: number | null; label?: string }
type SubjectPayload = {
  source?: string
  scores?: Record<string, DimScore>
} | null

type SegmentEntry = {
  from_ts: number
  to_ts: number
  me?: SubjectPayload
  other?: SubjectPayload
  error?: string
}

const props = defineProps<{
  conversationId: number
  /** deep payload 的 big5_evolution 键（series 每段双侧大五或 None） */
  evolution: { segments: number; min_messages: number; series: SegmentEntry[] } | null | undefined
  /** 父页视图纪元：切换会话/账号时丢弃过期响应 */
  viewEpoch: number
}>()

const overrides = ref<Record<number, { me?: SubjectPayload; other?: SubjectPayload }>>({})
const busyIndex = ref(-1)
const enhancingAll = ref(false)
const hint = ref('')
const runningWindow = ref<{ from_ts: number; to_ts: number } | null>(null)

const minMessages = computed(() => props.evolution?.min_messages || 30)
const segmentCount = computed(() => props.evolution?.segments || 0)

// 本段增强结果覆写层：不深改 props.payload，切换 payload 时随 epoch 清空
const seriesView = computed<SegmentEntry[]>(() =>
  (props.evolution?.series || []).map((seg, i) => (overrides.value[i] ? { ...seg, ...overrides.value[i] } : seg)),
)

const hasAnyData = computed(() => seriesView.value.some((seg) => seg.me || seg.other))

function isEnhanced(seg: SegmentEntry): boolean {
  return seg.me?.source === 'llm_enhanced' || seg.other?.source === 'llm_enhanced'
}

const anyEnhanced = computed(() => seriesView.value.some((seg) => !seg.error && isEnhanced(seg)))

// 还存在可增强的段（有数据、无错误、未增强）——全部增强按钮的可用条件
const enhanceable = computed(() =>
  seriesView.value.some((seg) => !seg.error && (seg.me || seg.other) && !isEnhanced(seg)),
)

const busy = computed(() => enhancingAll.value || busyIndex.value >= 0)

// ---- 小倍数折线几何（每维一张 mini，x=段序，y=0-100，中线 50） ----
const X0 = 18
const X1 = 212
const Y0 = 8
const Y1 = 76

const xTicks = computed(() => {
  const n = seriesView.value.length
  if (n <= 1) return [(X0 + X1) / 2]
  const step = (X1 - X0) / (n - 1)
  return Array.from({ length: n }, (_, i) => X0 + i * step)
})

function yOf(score: number): number {
  return Y0 + (100 - score) * ((Y1 - Y0) / 100)
}

type Run = {
  side: 'me' | 'other'
  color: string
  lines: { points: string }[]
  points: { index: number; x: number; y: number; r: number; title: string }[]
}

/** 单侧单维折线：None 断点拆成多段连续折线（样本不足段断开，不跨接） */
function runsFor(dimKey: string, side: 'me' | 'other'): Run[] {
  const values = seriesView.value.map((seg) => {
    const raw = seg[side]?.scores?.[dimKey]?.score
    return typeof raw === 'number' ? raw : null
  })
  const points = values
    .map((score, index) => ({ score, index }))
    .filter((item): item is { score: number; index: number } => item.score !== null)
  if (points.length < 1) return []
  const title = (index: number, score: number) =>
    `第 ${index + 1} 段 · ${side === 'me' ? '我' : 'TA'} · ${Math.round(score)}`
  const chunks: { points: { x: number; y: number; r: number; title: string; index: number }[] }[] = []
  for (const item of points) {
    const x = xTicks.value[item.index]
    const dot = {
      x, y: yOf(item.score), r: points.length === 1 ? 3 : 2.2,
      title: title(item.index, item.score), index: item.index,
    }
    const last = chunks[chunks.length - 1]
    // 连续段：与上一有效点段号相邻才接续，中间隔 None 则开新折线
    if (last && last.points[last.points.length - 1].index === item.index - 1) {
      last.points.push(dot)
    } else {
      chunks.push({ points: [dot] })
    }
  }
  return [{
    side,
    color: side === 'me' ? BIG5_COLOR_ME : BIG5_COLOR_OTHER,
    lines: chunks
      .filter((chunk) => chunk.points.length >= 2)
      .map((chunk) => ({ points: chunk.points.map((p) => `${p.x},${p.y}`).join(' ') })),
    points: chunks.flatMap((chunk) => chunk.points),
  }]
}

/** 维度中文标签：取首个有值段的 label，回退英文键 */
function labelFor(dimKey: string): string {
  for (const seg of seriesView.value) {
    const label = seg.me?.scores?.[dimKey]?.label || seg.other?.scores?.[dimKey]?.label
    if (label) return label
  }
  return dimKey
}

/** 首尾变化一句话（同一侧首末段都有值且差 ≥5 才提） */
function trendFor(dimKey: string): string {
  const pick = (side: 'me' | 'other') => {
    const values = seriesView.value
      .map((seg) => seg[side]?.scores?.[dimKey]?.score)
      .filter((v): v is number => typeof v === 'number')
    if (values.length < 2) return null
    return values[values.length - 1] - values[0]
  }
  const delta = pick('me')
  const deltaOther = pick('other')
  const fmt = (d: number) => `${d > 0 ? '↑' : '↓'}${Math.abs(Math.round(d))}`
  if (delta !== null && Math.abs(delta) >= 5 && (deltaOther === null || Math.abs(delta) >= Math.abs(deltaOther))) {
    return `我 ${fmt(delta)}`
  }
  if (deltaOther !== null && Math.abs(deltaOther) >= 5) return `TA ${fmt(deltaOther)}`
  return ''
}

const dimCharts = computed(() =>
  BIG5_DIM_ORDER.map((key) => ({
    key,
    label: labelFor(key),
    trend: trendFor(key),
    runs: [...runsFor(key, 'me'), ...runsFor(key, 'other')],
  })),
)

function fmtDate(tsSeconds: number): string {
  return toLocalDateKey(new Date(tsSeconds * 1000))
}

// ---- 逐段 / 全部 AI 增强（顺序逐段，已增强跳过；结果覆写回 series[i]） ----
function applyResult(index: number, result: any) {
  overrides.value = {
    ...overrides.value,
    [index]: { me: result?.subjects?.me ?? null, other: result?.subjects?.other ?? null },
  }
}

async function enhanceSegment(index: number) {
  const seg = seriesView.value[index]
  if (!seg || seg.error || busy.value) return
  const epoch = props.viewEpoch
  busyIndex.value = index
  hint.value = ''
  try {
    const result = await callEnhance(seg)
    if (epoch !== props.viewEpoch) return
    if (!result?.ok) {
      hint.value = result?.message || result?.error || 'AI 校正不可用'
      return
    }
    applyResult(index, result)
  } catch (e: any) {
    if (epoch === props.viewEpoch) hint.value = e?.message || '请求失败'
  } finally {
    if (epoch === props.viewEpoch) busyIndex.value = -1
  }
}

async function enhanceAll() {
  const epoch = props.viewEpoch
  enhancingAll.value = true
  hint.value = ''
  try {
    for (let i = 0; i < seriesView.value.length; i++) {
      if (epoch !== props.viewEpoch) return
      const seg = seriesView.value[i]
      if (!seg || seg.error || !(seg.me || seg.other) || isEnhanced(seg)) continue
      busyIndex.value = i
      const result = await callEnhance(seg)
      busyIndex.value = -1
      if (epoch !== props.viewEpoch) return
      if (!result?.ok) {
        hint.value = result?.message || result?.error || 'AI 校正不可用'
        return
      }
      applyResult(i, result)
    }
  } finally {
    if (epoch === props.viewEpoch) {
      enhancingAll.value = false
      busyIndex.value = -1
    }
  }
}

async function callEnhance(seg: SegmentEntry) {
  runningWindow.value = { from_ts: seg.from_ts, to_ts: seg.to_ts }
  try {
    return await api.enhance_big5_impressions(props.conversationId, '', seg.from_ts, seg.to_ts)
  } finally {
    runningWindow.value = null
  }
}

async function cancelAll() {
  const win = runningWindow.value
  if (!win) {
    hint.value = '当前没有可取消的请求（两次调用间隙无法中断）'
    return
  }
  try {
    await api.cancel_big5_impressions(props.conversationId, '', win.from_ts, win.to_ts)
    hint.value = '正在取消…'
  } catch {
    // 取消请求失败：增强请求本身会照常返回，状态随之复位
  }
}

// payload 重拉（分段数/时间窗/会话变化）时清覆写与状态
function resetState() {
  overrides.value = {}
  busyIndex.value = -1
  enhancingAll.value = false
  hint.value = ''
}
watch(() => props.evolution, resetState)
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

.header-right {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  flex-shrink: 0;
}

.badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--ct-text-xs);
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
}

.badge-enhanced {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
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

.enhance-btn {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.hint {
  margin-bottom: var(--ct-space-sm);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.legend-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
  margin-bottom: var(--ct-space-md);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-note {
  color: var(--ct-text-tertiary);
}

.swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}


.minis-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--ct-space-md);
}

.mini {
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm) var(--ct-space-sm) 0;
  min-width: 0;
}

.mini-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-xs);
  padding: 0 var(--ct-space-xs) var(--ct-space-xs);
}

.mini-label {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-xs);
  font-weight: var(--ct-font-bold);
}

.mini-trend {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.mini-svg {
  display: block;
  width: 100%;
  height: auto;
}

.axis {
  stroke: var(--ct-border-color);
  stroke-width: 1;
}

.midline {
  stroke: var(--ct-border-color);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}

.midlabel {
  fill: var(--ct-text-tertiary);
  font-size: 8px;
  text-anchor: end;
}

.line {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}


.dot {
  stroke: var(--ct-bg-elevated);
  stroke-width: 1;
}


.xtick {
  fill: var(--ct-text-tertiary);
  font-size: 8px;
}

.segments-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-sm);
  margin-top: var(--ct-space-md);
}

.seg-item {
  display: inline-flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: 4px 12px;
  border: 1px solid var(--ct-border-color);
  border-radius: 999px;
  background: var(--ct-bg-secondary);
  font-size: var(--ct-text-xs);
}

.seg-tag {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
}

.seg-range {
  color: var(--ct-text-secondary);
}

.seg-btn {
  padding: 1px 10px;
}

.seg-badge {
  color: var(--ct-color-primary);
}

.seg-error {
  color: var(--ct-text-tertiary);
}

.disclaimer {
  margin-top: var(--ct-space-md);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.empty {
  color: var(--ct-text-tertiary);
  padding: var(--ct-space-xl) 0;
  text-align: center;
}
</style>
