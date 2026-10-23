<template>
  <div class="panel big-five">
    <div class="panel-head">
      <div>
        <div class="panel-title">大五人格印象</div>
        <div class="panel-sub">{{ sourceNote }}</div>
      </div>
      <div class="panel-actions">
        <span class="panel-badge" :class="sourceBadgeClass">{{ sourceBadgeText }}</span>
        <button v-if="!enhancing" class="btn enhance-btn" :disabled="loading" @click="enhance">
          AI 校正
        </button>
        <button v-else class="btn" @click="cancelEnhance">取消</button>
      </div>
    </div>

    <div v-if="loading" class="empty-state">正在统计语言风格…</div>
    <div v-else-if="error" class="state-row">
      <span class="error-text">{{ error }}</span>
      <button class="btn" @click="load">重试</button>
    </div>
    <div v-else-if="!me && !other" class="empty-state">消息量还不足以形成稳定的风格印象（需约 30 条以上文本）</div>

    <div v-if="enhanceHint" class="enhance-hint">{{ enhanceHint }}</div>

    <template v-if="!loading && !error && (me || other)">
      <div class="big5-body">
        <div class="radar-col">
          <BigFiveRadar :me="meScores" :other="otherScores" />
          <div class="legend-row radar-legend">
            <span><span class="swatch me" />我</span>
            <span><span class="swatch other" />TA</span>
          </div>
        </div>

        <div class="dims-col">
          <div v-for="subject in activeSubjects" :key="subject.key" class="dim-group">
            <div class="dim-group-title">{{ subject.key === 'me' ? '我' : 'TA' }}</div>
            <div v-for="dim in subject.dims" :key="dim.key" class="dim-row">
              <span class="dim-label">{{ dim.label }}</span>
              <div class="dim-track">
                <!-- 不确定带：有界校正 ±15，真实位置只在此带内——精确点分假装精度 -->
                <div
                  v-if="dim.bandFrom !== undefined"
                  class="dim-band"
                  :style="{ left: `${dim.bandFrom}%`, width: `${(dim.bandTo || 0) - dim.bandFrom}%` }"
                />
                <div
                  class="dim-fill"
                  :class="subject.key"
                  :style="{ width: `${dim.score}%` }"
                />
                <div
                  v-if="dim.baseScore !== undefined"
                  class="dim-base-tick"
                  :style="{ left: `${dim.baseScore}%` }"
                  :title="`统计基础分 ${dim.baseScore}`"
                />
              </div>
              <span class="dim-score">
                {{ Math.round(dim.score) }}<template v-if="dim.bandFrom !== undefined"><span class="dim-band-text"> · {{ dim.bandFrom }}-{{ dim.bandTo }}</span></template>
              </span>
              <span v-if="dim.adjustment" class="dim-adjust" :class="{ up: dim.adjustment > 0 }">
                {{ dim.adjustment > 0 ? '+' : '' }}{{ dim.adjustment }}
              </span>
            </div>
            <div v-if="subject.evidenceList.length" class="evidence-box">
              <button class="evidence-toggle" @click="evidenceExpanded[subject.key] = !subject.expanded">
                {{ subject.expanded ? '收起证据' : `查看证据（${subject.evidenceList.length} 条）` }}
              </button>
              <div v-if="subject.expanded" class="evidence-list">
                <div v-for="(item, index) in subject.evidenceList" :key="index" class="evidence-item">
                  <div class="evidence-dim">{{ item.label }}</div>
                  <div v-if="item.quote" class="evidence-quote">“{{ item.quote }}”</div>
                  <div v-if="item.reason" class="evidence-reason">{{ item.reason }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="disclaimer">{{ disclaimer }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import BigFiveRadar from '@/components/deep/BigFiveRadar.vue'

type DimScore = {
  score: number | null
  label?: string
  base_score?: number
  adjustment?: number
}
type SubjectPayload = {
  source: string
  scores: Record<string, DimScore>
  evidence?: Record<string, { quote: string; reason: string }>
  indicators?: Record<string, number | null> | null
} | null

const props = defineProps<{ conversationId: number }>()

const payload = ref<{ ok: boolean; source?: string; window?: { kind?: string; from?: number; to?: number }; subjects?: Record<string, SubjectPayload>; disclaimer?: string } | null>(null)
const loading = ref(false)
const enhancing = ref(false)
const error = ref('')
const enhanceHint = ref('')
const evidenceExpanded = reactive<Record<string, boolean>>({})

const me = computed(() => payload.value?.subjects?.me || null)
const other = computed(() => payload.value?.subjects?.other || null)
const meScores = computed(() => me.value?.scores || null)
const otherScores = computed(() => other.value?.scores || null)

const DIM_ORDER = ['openness', 'extraversion', 'agreeableness', 'conscientiousness', 'neuroticism']

const isEnhanced = computed(() =>
  Boolean(me.value?.source === 'llm_enhanced' || other.value?.source === 'llm_enhanced'),
)
const sourceBadgeText = computed(() => (isEnhanced.value ? 'AI 增强' : '本地统计'))
const sourceBadgeClass = computed(() => (isEnhanced.value ? 'enhanced' : ''))
/** 语料口径：全会话 or 指定窗——面板默认全会话，缺了这行就分不清语料范围 */
const windowNote = computed(() => {
  const win = payload.value?.window
  if (win?.kind === 'custom' && win.from && win.to) {
    const fmt = (ts: number) => new Date(ts * 1000).toLocaleDateString('zh-CN')
    return `，语料：指定窗 ${fmt(win.from)} ~ ${fmt(win.to)}`
  }
  return '，语料：全会话'
})
const sourceNote = computed(() =>
  isEnhanced.value
    ? `本地统计 + AI 有界校正（±15 以内），附原文证据${windowNote.value}`
    : `纯本地行为统计，无需配置模型；点「AI 校正」可结合原文做有界修正${windowNote.value}`,
)
const disclaimer = computed(
  () => payload.value?.disclaimer || '语言风格印象，非心理测评；大五为连续维度（0-100），不构成人格结论',
)

interface DimRow {
  key: string
  label: string
  score: number
  baseScore?: number
  /** 不确定带 [base-15, base+15]（clamp 0-100）：只有 AI 增强行有，纯统计行无 */
  bandFrom?: number
  bandTo?: number
  adjustment?: number
}

const activeSubjects = computed(() => {
  const list: Array<{ key: string; dims: DimRow[]; evidenceList: Array<{ label: string; quote: string; reason: string }>; expanded: boolean }> = []
  for (const key of ['me', 'other'] as const) {
    const subject = key === 'me' ? me.value : other.value
    if (!subject) continue
    const dims: DimRow[] = []
    for (const dimKey of DIM_ORDER) {
      const item = subject.scores?.[dimKey]
      if (typeof item?.score !== 'number') continue
      const baseScore = typeof item.base_score === 'number' ? item.base_score : undefined
      dims.push({
        key: dimKey,
        label: item.label || dimKey,
        score: item.score,
        baseScore,
        bandFrom: baseScore !== undefined ? Math.max(0, Math.round(baseScore - 15)) : undefined,
        bandTo: baseScore !== undefined ? Math.min(100, Math.round(baseScore + 15)) : undefined,
        adjustment: typeof item.adjustment === 'number' ? item.adjustment : undefined,
      })
    }
    const evidenceList = Object.entries(subject.evidence || {})
      .filter(([, value]) => value?.quote || value?.reason)
      .map(([dimKey, value]) => ({
        label: subject.scores?.[dimKey]?.label || dimKey,
        quote: value.quote || '',
        reason: value.reason || '',
      }))
    list.push({ key, dims, evidenceList, expanded: evidenceExpanded[key] === true })
  }
  return list
})

async function load() {
  // 会话一致性守卫：大五计算含全量扫描+jieba，慢响应后到时不能覆盖
  // 新会话的面板（否则画像张冠李戴）
  const requestConv = props.conversationId
  loading.value = true
  error.value = ''
  try {
    const result = await api.get_big5_impressions(props.conversationId)
    if (requestConv !== props.conversationId) return
    if (!result?.ok) {
      error.value = result?.error || '加载失败'
      return
    }
    payload.value = result
  } catch (e: any) {
    if (requestConv !== props.conversationId) return
    error.value = e?.message || '请求失败'
  } finally {
    loading.value = false
  }
}

async function enhance() {
  const requestConv = props.conversationId
  enhancing.value = true
  enhanceHint.value = ''
  try {
    const result = await api.enhance_big5_impressions(props.conversationId)
    if (requestConv !== props.conversationId) return
    if (!result?.ok) {
      enhanceHint.value = result?.message || result?.error || 'AI 校正不可用'
      return
    }
    payload.value = result
  } catch (e: any) {
    if (requestConv !== props.conversationId) return
    enhanceHint.value = e?.message || '请求失败'
  } finally {
    if (requestConv === props.conversationId) enhancing.value = false
  }
}

async function cancelEnhance() {
  try {
    await api.cancel_big5_impressions(props.conversationId)
    enhanceHint.value = '正在取消…'
  } catch {
    // 取消请求失败：增强请求本身会照常返回，enhancing 随之复位
  }
}

watch(() => props.conversationId, () => {
  payload.value = null
  enhanceHint.value = ''
  load()
}, { immediate: true })
</script>

<style scoped>
/* 卡容器/头/徽标/按钮/空态走全局 panels.css，这里只留私有变体 */
.enhance-btn {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.big5-body {
  display: flex;
  gap: var(--ct-space-lg);
  flex-wrap: wrap;
}

.radar-col {
  flex: 0 0 260px;
  max-width: 100%;
}

.radar-legend {
  margin-top: var(--ct-space-xs);
  justify-content: center;
}

.swatch.me { background: var(--ct-chart-1); }
.swatch.other { background: var(--ct-chart-4); }

.dims-col {
  flex: 1 1 320px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.dim-group-title {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
  margin-bottom: var(--ct-space-xs);
}

.dim-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: 3px 0;
}

.dim-label {
  width: 3.5em;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  flex-shrink: 0;
}

.dim-track {
  position: relative;
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: var(--ct-bg-sunken);
  overflow: visible;
}

.dim-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.5s ease;
}

.dim-fill.me { background: var(--ct-chart-1); }
.dim-fill.other { background: var(--ct-chart-4); }

/* 不确定带：主体色 12% 淡染的底带，fill 压在其上 */
.dim-band {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 999px;
  background: color-mix(in srgb, var(--ct-text-tertiary) 18%, transparent);
}

.dim-base-tick {
  position: absolute;
  top: -3px;
  width: 2px;
  height: 14px;
  background: var(--ct-text-tertiary);
  border-radius: 1px;
}

.dim-score {
  text-align: right;
  white-space: nowrap;
  color: var(--ct-text-primary);
  font-size: var(--ct-text-xs);
  font-weight: var(--ct-font-bold);
}

.dim-band-text {
  color: var(--ct-text-tertiary);
  font-weight: var(--ct-font-normal);
}

.dim-adjust {
  width: 2.5em;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.dim-adjust.up {
  color: var(--ct-color-success);
}

.evidence-box {
  margin-top: var(--ct-space-xs);
}

.evidence-toggle {
  background: none;
  border: none;
  color: var(--ct-color-primary);
  font-size: var(--ct-text-xs);
  cursor: pointer;
  padding: 0;
}

.evidence-list {
  margin-top: var(--ct-space-xs);
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.evidence-item {
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm) var(--ct-space-md);
}

.evidence-dim {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  margin-bottom: 2px;
}

.evidence-quote {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
  line-height: 1.6;
}

.evidence-reason {
  margin-top: 2px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.disclaimer {
  margin-top: var(--ct-space-md);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.state-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
}

.error-text {
  color: var(--ct-color-error, #E8656F);
  font-size: var(--ct-text-sm);
}

.enhance-hint {
  margin-top: var(--ct-space-xs);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}
</style>
