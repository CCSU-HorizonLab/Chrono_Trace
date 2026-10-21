<template>
  <div class="panel big5-evolution">
    <div class="panel-head">
      <div>
        <div class="panel-title">大五人格演变</div>
        <div class="panel-sub">
          把时间窗均分为 {{ segmentCount }} 段（与词云演变共用分段），每段一张雷达，看你们各自的语言风格怎么变
        </div>
      </div>
      <div class="panel-actions">
        <span class="panel-badge" :class="{ enhanced: anyEnhanced }">
          {{ anyEnhanced ? '含 AI 校正' : '本地统计' }}
        </span>
        <button v-if="!enhancingAll" class="btn enhance-btn" :disabled="busy || !enhanceable" @click="enhanceAll">
          全部增强
        </button>
        <button v-else class="btn" @click="cancelAll">取消</button>
      </div>
    </div>

    <div v-if="hint" class="hint">{{ hint }}</div>

    <div v-if="!seriesView.length" class="empty-state">这段时光还没有可统计的大五演变数据</div>
    <div v-else-if="!hasAnyData" class="empty-state">
      消息量还不足以形成稳定的风格印象（每段每侧约需 {{ minMessages }} 条以上文本）
    </div>

    <template v-else>
      <!-- 分段雷达小多图：段序自左向右即时间序，形状对比承担叙事；
           我/TA 图例在页签工具条，缺一侧就只画一侧 -->
      <div class="segments-cards">
        <div v-for="(seg, i) in seriesView" :key="i" class="segment-card">
          <div class="card-head">
            <span class="card-range">{{ toCompactRange(seg.from_ts, seg.to_ts) }}</span>
            <span v-if="seg.error" class="card-state error">{{ seg.error }}</span>
            <span v-else-if="!(seg.me || seg.other)" class="card-state">样本不足</span>
            <span v-else-if="isEnhanced(seg)" class="panel-badge enhanced">AI 增强</span>
            <button v-else class="btn card-enhance" :disabled="busy" @click="enhanceSegment(i)">
              {{ busyIndex === i ? '增强中…' : 'AI 增强' }}
            </button>
          </div>
          <BigFiveRadar v-if="seg.me || seg.other" compact :size="220" :me="seg.me?.scores" :other="seg.other?.scores" />
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
import { toCompactRange } from '@/utils/datetime'
import BigFiveRadar from './BigFiveRadar.vue'

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
.enhance-btn {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.hint {
  margin-bottom: var(--ct-space-sm);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.segments-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--ct-space-md);
}

.segment-card {
  background: var(--ct-bg-sunken);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm) var(--ct-space-sm) 0;
  min-width: 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-xs);
  padding: 0 var(--ct-space-xs) var(--ct-space-xs);
  flex-wrap: wrap;
}

.card-range {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-xs);
  font-weight: var(--ct-font-bold);
}

.card-enhance {
  padding: 1px 10px;
}

.card-state {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.card-state.error {
  color: var(--ct-color-error, #E8656F);
}

.disclaimer {
  margin-top: var(--ct-space-md);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}
</style>
