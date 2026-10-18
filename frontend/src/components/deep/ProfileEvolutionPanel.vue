<template>
  <div class="profile-evolution card">
    <div class="panel-header">
      <div>
        <div class="panel-title">画像演变</div>
        <div class="panel-sub">把时间窗对半分成前后两段，分别生成 TA 的画像并对比印象的变化</div>
      </div>
      <div class="header-right">
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
      正在为前后半窗分别生成画像，最多 {{ includeSelf ? 4 : 2 }} 次 AI 调用；
      已完成的半窗会存为快照，中断后重试免费续跑…
    </div>
    <div v-else-if="state === 'error'" class="state-text error-text">{{ error }}</div>

    <template v-if="result && state !== 'generating' && state !== 'error'">
      <div class="halves-grid">
        <div v-for="(half, index) in result.halves || []" :key="index" class="half-col">
          <div class="half-head">
            <span class="half-tag">{{ half.label }}</span>
            <span class="half-range">{{ fmtDate(half.from_ts) }} ~ {{ fmtDate(half.to_ts) }}</span>
          </div>

          <template v-if="half.contact">
            <div class="kind-title">TA 的画像
              <span v-if="half.contact.cached" class="badge cached" title="命中历史快照，未重复调用 AI">历史快照</span>
            </div>
            <div v-if="half.contact.error" class="kind-error">{{ half.contact.error }}</div>
            <template v-else-if="half.contact.profile">
              <div v-if="tagRows(half).length" class="tag-list">
                <span
                  v-for="tag in tagRows(half)"
                  :key="tag.name"
                  class="tag"
                  :class="tag.cls"
                  :title="tag.title"
                >{{ tag.name }}</span>
              </div>
              <div v-if="textOf(half.contact.profile, 'chat_style')" class="field">
                <span class="field-label">聊天风格</span>
                <span>{{ textOf(half.contact.profile, 'chat_style') }}</span>
              </div>
              <div v-if="listOf(half.contact.profile, 'interests').length" class="field">
                <span class="field-label">兴趣</span>
                <span>{{ listOf(half.contact.profile, 'interests').join('、') }}</span>
              </div>
              <div v-if="textOf(half.contact.profile, 'relationship_note')" class="field">
                <span class="field-label">关系备注</span>
                <span>{{ textOf(half.contact.profile, 'relationship_note') }}</span>
              </div>
            </template>
            <div v-else class="half-empty">这段没有可用的画像</div>
          </template>

          <template v-if="half.self">
            <div class="kind-title">我的画像
              <span v-if="half.self.cached" class="badge cached" title="命中历史快照，未重复调用 AI">历史快照</span>
            </div>
            <div v-if="half.self.error" class="kind-error">{{ half.self.error }}</div>
            <template v-else-if="half.self.profile">
              <div v-if="textOf(half.self.profile, 'typing_style')" class="field">
                <span class="field-label">打字风格</span>
                <span>{{ textOf(half.self.profile, 'typing_style') }}</span>
              </div>
              <div v-if="listOf(half.self.profile, 'frequent_catchphrases').length" class="field">
                <span class="field-label">口头禅</span>
                <span>{{ listOf(half.self.profile, 'frequent_catchphrases').join('、') }}</span>
              </div>
              <div v-if="listOf(half.self.profile, 'sentence_patterns').length" class="field">
                <span class="field-label">句式</span>
                <span>{{ listOf(half.self.profile, 'sentence_patterns').join('；') }}</span>
              </div>
              <div v-if="textOf(half.self.profile, 'attitude_and_role')" class="field">
                <span class="field-label">态度角色</span>
                <span>{{ textOf(half.self.profile, 'attitude_and_role') }}</span>
              </div>
            </template>
          </template>
        </div>
      </div>

      <div class="tag-legend">
        <span class="legend-item"><span class="tag only-pre" />仅前段</span>
        <span class="legend-item"><span class="tag only-post" />仅后段</span>
        <span class="legend-item"><span class="tag both" />两段都有</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { toLocalDateKey } from '@/utils/datetime'

type KindBlock = { profile: any; created_at: number; cached: boolean; error?: string } | null
type Half = { from_ts: number; to_ts: number; label: string; contact?: KindBlock; self?: KindBlock }

const props = defineProps<{
  conversationId: number
  dates: { from: string; to: string }
  /** 父页视图纪元：切换会话/账号时 +1，用于丢弃过期响应 */
  viewEpoch: number
  contactName?: string
}>()

const state = ref<'idle' | 'generating' | 'done' | 'error'>('idle')
const result = ref<{ halves?: Half[] } | null>(null)
const error = ref('')
const hint = ref('')
const includeSelf = ref(false)

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

const preTags = computed(() => listOf(result.value?.halves?.[0]?.contact?.profile, 'personality_tags'))
const postTags = computed(() => listOf(result.value?.halves?.[1]?.contact?.profile, 'personality_tags'))

function tagRows(half: Half): Array<{ name: string; cls: string; title: string }> {
  // 标签按所在半窗着色：另一段没有 → 差异色；两段都有 → 中性色
  const isPre = half.label === '前半段'
  const own = new Set(isPre ? preTags.value : postTags.value)
  const other = new Set(isPre ? postTags.value : preTags.value)
  return [...own].map((name) => {
    if (!other.has(name)) {
      return { name, cls: isPre ? 'only-pre' : 'only-post', title: isPre ? '仅前段出现' : '仅后段出现' }
    }
    return { name, cls: 'both', title: '前后两段都有' }
  })
}

async function generate(force: boolean) {
  // 会话一致性守卫：慢响应后到时不能覆盖切走后的面板（画像张冠李戴）
  const requestConv = props.conversationId
  const requestEpoch = props.viewEpoch
  state.value = 'generating'
  error.value = ''
  hint.value = ''
  try {
    const res = await api.generate_profile_evolution(
      props.conversationId, props.dates.from, props.dates.to,
      includeSelf.value, force,
    )
    if (requestConv !== props.conversationId || requestEpoch !== props.viewEpoch) return
    if (res?.cancelled) {
      state.value = result.value ? 'done' : 'idle'
      hint.value = '已取消；已完成的半窗已存为快照，重试会续跑'
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
    const cachedCount = (res.halves || []).filter(
      (half: Half) => half.contact?.cached || half.self?.cached,
    ).length
    if (cachedCount) hint.value = `${cachedCount} 个半窗命中历史快照，未重复调用 AI`
  } catch (e: any) {
    if (requestConv !== props.conversationId || requestEpoch !== props.viewEpoch) return
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
  },
)
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

.halves-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--ct-space-md);
}

.half-col {
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  min-width: 0;
}

.half-head {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-sm);
  flex-wrap: wrap;
}

.half-tag {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.half-range {
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

.tag.only-pre {
  border-color: #d97706;
  color: #d97706;
}

.tag.only-post {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
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

.half-empty {
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
