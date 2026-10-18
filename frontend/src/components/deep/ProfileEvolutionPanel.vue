<template>
  <div class="profile-evolution card">
    <div class="panel-header">
      <div>
        <div class="panel-title">画像演变</div>
        <div class="panel-sub">
          把时间窗均分为 {{ segmentCount }} 段，分别生成 TA 的画像并对比印象的变化
        </div>
      </div>
      <div class="header-right">
        <div class="seg-group" role="group" aria-label="画像分段数">
          <button
            v-for="n in segmentOptions"
            :key="n"
            class="btn seg-btn"
            :class="{ active: segmentCount === n }"
            :disabled="state === 'generating'"
            @click="setSegments(n)"
          >{{ n }} 段</button>
        </div>
        <label v-if="state !== 'generating'" class="self-toggle">
          <input v-model="includeSelf" type="checkbox" :disabled="state === 'generating'" />
          包含我的画像
        </label>
        <button v-if="state === 'idle'" class="btn primary-btn" @click="generate(false)">
          生成对比
        </button>
        <template v-else-if="state === 'done'">
          <button class="btn" @click="generate(false)">刷新</button>
          <button class="btn primary-btn" @click="generate(true)">重新生成</button>
        </template>
        <button v-else-if="state === 'generating'" class="btn" @click="cancel">取消</button>
        <button v-else-if="state === 'error'" class="btn primary-btn" @click="generate(false)">重试</button>
      </div>
    </div>

    <div v-if="hint" class="hint">{{ hint }}</div>

    <div v-if="state === 'generating'" class="state-text">
      正在为 {{ segmentCount }} 个分段分别生成画像，最多 {{ segmentCount * (includeSelf ? 2 : 1) }} 次 AI 调用；
      已完成的分段会存为快照，中断后重试免费续跑…
    </div>
    <div v-else-if="state === 'error'" class="state-text error-text">{{ error }}</div>

    <template v-if="result && state !== 'generating' && state !== 'error'">
      <div class="segments-grid">
        <div v-for="(seg, index) in segmentList" :key="index" class="segment-col">
          <div class="segment-head">
            <span class="segment-tag">{{ seg.label }}</span>
            <span class="segment-range">{{ fmtDate(seg.from_ts) }} ~ {{ fmtDate(seg.to_ts) }}</span>
          </div>

          <template v-if="seg.contact">
            <div class="kind-title">TA 的画像
              <span v-if="seg.contact.cached" class="badge cached" title="命中历史快照，未重复调用 AI">历史快照</span>
            </div>
            <div v-if="seg.contact.error" class="kind-error">{{ seg.contact.error }}</div>
            <template v-else-if="seg.contact.profile">
              <div v-if="tagRows(index).length" class="tag-list">
                <span
                  v-for="tag in tagRows(index)"
                  :key="tag.name"
                  class="tag"
                  :class="tag.cls"
                  :title="tag.title"
                >{{ tag.name }}</span>
              </div>
              <div v-if="textOf(seg.contact.profile, 'chat_style')" class="field">
                <span class="field-label">聊天风格</span>
                <span>{{ textOf(seg.contact.profile, 'chat_style') }}</span>
              </div>
              <div v-if="listOf(seg.contact.profile, 'interests').length" class="field">
                <span class="field-label">兴趣</span>
                <span>{{ listOf(seg.contact.profile, 'interests').join('、') }}</span>
              </div>
              <div v-if="textOf(seg.contact.profile, 'relationship_note')" class="field">
                <span class="field-label">关系备注</span>
                <span>{{ textOf(seg.contact.profile, 'relationship_note') }}</span>
              </div>
            </template>
            <div v-else class="segment-empty">这段没有可用的画像</div>
          </template>

          <template v-if="seg.self">
            <div class="kind-title">我的画像
              <span v-if="seg.self.cached" class="badge cached" title="命中历史快照，未重复调用 AI">历史快照</span>
            </div>
            <div v-if="seg.self.error" class="kind-error">{{ seg.self.error }}</div>
            <template v-else-if="seg.self.profile">
              <div v-if="textOf(seg.self.profile, 'typing_style')" class="field">
                <span class="field-label">打字风格</span>
                <span>{{ textOf(seg.self.profile, 'typing_style') }}</span>
              </div>
              <div v-if="listOf(seg.self.profile, 'frequent_catchphrases').length" class="field">
                <span class="field-label">口头禅</span>
                <span>{{ listOf(seg.self.profile, 'frequent_catchphrases').join('、') }}</span>
              </div>
              <div v-if="listOf(seg.self.profile, 'sentence_patterns').length" class="field">
                <span class="field-label">句式</span>
                <span>{{ listOf(seg.self.profile, 'sentence_patterns').join('；') }}</span>
              </div>
              <div v-if="textOf(seg.self.profile, 'attitude_and_role')" class="field">
                <span class="field-label">态度角色</span>
                <span>{{ textOf(seg.self.profile, 'attitude_and_role') }}</span>
              </div>
            </template>
          </template>
        </div>
      </div>

      <div class="tag-legend">
        <span class="legend-item"><span class="tag unique" />该段独有</span>
        <span class="legend-item"><span class="tag shared" />各段都有</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { getCachedEvolution, runEvolution } from './profileEvolutionCache'
import { toLocalDateKey } from '@/utils/datetime'

type KindBlock = { profile: any; created_at: number; cached: boolean; error?: string } | null
type Segment = { from_ts: number; to_ts: number; label: string; contact?: KindBlock; self?: KindBlock }

const props = defineProps<{
  conversationId: number
  dates: { from: string; to: string }
  /** 父页视图纪元：切换会话/账号时 +1，用于丢弃过期响应 */
  viewEpoch: number
  contactName?: string
}>()

const state = ref<'idle' | 'generating' | 'done' | 'error'>('idle')
const result = ref<{ segments?: Segment[] } | null>(null)
const error = ref('')
const hint = ref('')
const includeSelf = ref(false)
// 画像分段独立于词云分段（每段一次 LLM 快照，成本自控），默认 2 段
const segmentCount = ref(2)
const segmentOptions = [2, 3, 4, 5, 6]

const segmentList = computed(() => result.value?.segments || [])

function setSegments(n: number) {
  if (segmentCount.value === n || state.value === 'generating') return
  segmentCount.value = n
  // 快照按 (from,to) 精确命中，切档重开生成即回免费档；旧结果清掉防错配
  state.value = 'idle'
  result.value = null
  hint.value = ''
  error.value = ''
  restoreFromCache()
}

function fmtDate(tsSeconds: number): string {
  return toLocalDateKey(new Date(tsSeconds * 1000))
}

function textOf(profile: any, key: string): string {
  const value = profile?.[key]
  return typeof value === 'string' ? value.trim() : ''
}

function listOf(profile: any, key: string): string[] {
  const value = profile?.[key]
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : []
}

function tagRows(index: number): Array<{ name: string; cls: string; title: string }> {
  // 标签按跨段在场着色：仅本段出现 → 琥珀差异色；多段都有 → 中性色
  const own = new Set(listOf(segmentList.value[index]?.contact?.profile, 'personality_tags'))
  const elsewhere = new Set<string>()
  segmentList.value.forEach((seg, i) => {
    if (i !== index) {
      listOf(seg.contact?.profile, 'personality_tags').forEach((name) => elsewhere.add(name))
    }
  })
  return [...own].map((name) => {
    if (!elsewhere.has(name)) {
      return { name, cls: 'unique', title: '仅该段出现' }
    }
    return { name, cls: 'shared', title: '多段都有' }
  })
}

async function generate(force: boolean) {
  // 会话一致性守卫：慢响应后到时不能覆盖切走后的面板（画像张冠李戴）。
  // 日期一并入守卫——生成期间改时间窗，旧窗数据不能落回新日期下
  const requestConv = props.conversationId
  const requestEpoch = props.viewEpoch
  const requestFrom = props.dates.from
  const requestTo = props.dates.to
  state.value = 'generating'
  error.value = ''
  hint.value = ''
  try {
    const res = await runEvolution(
      requestConv, requestFrom, requestTo, includeSelf.value, force, segmentCount.value,
    )
    if (
      requestConv !== props.conversationId || requestEpoch !== props.viewEpoch
      || requestFrom !== props.dates.from || requestTo !== props.dates.to
    ) return
    if (res?.cancelled) {
      state.value = result.value ? 'done' : 'idle'
      hint.value = '已取消；已完成的分段已存为快照，重试会续跑'
      return
    }
    if (!res?.ok) {
      if (res?.reason === 'already_running') {
        hint.value = res?.message || '画像演变生成中'
        state.value = result.value ? 'done' : 'idle'
        return
      }
      state.value = 'error'
      error.value = res?.error || '生成失败'
      return
    }
    result.value = res
    state.value = 'done'
    const cachedCount = (res.segments || []).filter(
      (seg: Segment) => seg.contact?.cached || seg.self?.cached,
    ).length
    if (cachedCount) hint.value = `${cachedCount} 个分段命中历史快照，未重复调用 AI`
  } catch (e: any) {
    if (
      requestConv !== props.conversationId || requestEpoch !== props.viewEpoch
      || requestFrom !== props.dates.from || requestTo !== props.dates.to
    ) return
    state.value = 'error'
    error.value = e?.message || '请求失败'
  }
}

async function cancel() {
  try {
    await api.cancel_profile_evolution(props.conversationId)
    hint.value = '正在取消…'
  } catch {
    // 取消请求失败：生成请求本身会照常返回，状态随之复位
  }
}

watch(
  () => [props.conversationId, props.dates.from, props.dates.to, props.viewEpoch],
  () => {
    state.value = 'idle'
    result.value = null
    error.value = ''
    hint.value = ''
    restoreFromCache()
  },
)

// 重挂恢复：在途调用接管等待（完成后照常渲染），已完成则直接显示
// ——路由切走再切回不再丢结果/丢进度
function restoreFromCache() {
  const entry = getCachedEvolution(
    props.conversationId, props.dates.from, props.dates.to,
    segmentCount.value, includeSelf.value,
  )
  if (entry?.promise) {
    void generate(false)
  } else if (entry?.res) {
    result.value = entry.res
    state.value = 'done'
  }
}

restoreFromCache()
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

.seg-group {
  display: flex;
  gap: var(--ct-space-xs);
}

.seg-btn.active {
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  border-color: var(--ct-color-primary);
}

.self-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  cursor: pointer;
  user-select: none;
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

.primary-btn {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.hint {
  margin-bottom: var(--ct-space-sm);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.state-text {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
  padding: var(--ct-space-lg) 0;
  text-align: center;
}

.error-text {
  color: var(--ct-color-error, #dc2626);
}

.segments-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--ct-space-md);
}

.segment-col {
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  min-width: 0;
}

.segment-head {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-sm);
  flex-wrap: wrap;
}

.segment-tag {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.segment-range {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
}

.kind-title {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
  margin: var(--ct-space-sm) 0 var(--ct-space-xs);
}

.badge.cached {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: var(--ct-text-xs);
  font-weight: normal;
  border: 1px solid var(--ct-color-primary);
  color: var(--ct-color-primary);
}

.kind-error {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  padding: var(--ct-space-xs) 0;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: var(--ct-space-sm);
}

.tag {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--ct-text-xs);
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
}

.tag.unique {
  border-color: #d97706;
  color: #d97706;
}

.tag.shared {
  border-color: var(--ct-border-color);
  color: var(--ct-text-secondary);
}

.field {
  display: flex;
  gap: var(--ct-space-sm);
  padding: 3px 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-primary);
  line-height: 1.6;
}

.field-label {
  flex-shrink: 0;
  color: var(--ct-text-tertiary);
}

.segment-empty {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  padding: var(--ct-space-sm) 0;
}

.tag-legend {
  display: flex;
  justify-content: center;
  gap: var(--ct-space-lg);
  margin-top: var(--ct-space-md);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-item .tag {
  padding: 0;
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
</style>
