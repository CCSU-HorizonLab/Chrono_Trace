<template>
  <div class="panel profile-evolution">
    <div class="panel-head">
      <div>
        <div class="panel-title">画像演变</div>
        <div class="panel-sub">
          按关系章节逐章生成 TA 的画像，从上到下对比印象的变化（与章节面板同源分段）
        </div>
      </div>
      <div class="panel-actions">
        <label v-if="state !== 'generating' && !singleChapter" class="self-toggle">
          <input v-model="includeSelf" type="checkbox" :disabled="state === 'generating'" />
          包含我的画像
        </label>
        <button v-if="state === 'idle' && !singleChapter" class="btn primary" @click="generate(false)">
          生成对比
        </button>
        <template v-else-if="state === 'done'">
          <button class="btn" @click="generate(false)">刷新</button>
          <button class="btn primary" @click="generate(true)">重新生成</button>
        </template>
        <button v-else-if="state === 'generating'" class="btn" @click="cancel">取消</button>
        <button v-else-if="state === 'error'" class="btn primary" @click="generate(false)">重试</button>
      </div>
    </div>

    <div v-if="hint" class="hint">{{ hint }}</div>

    <div v-if="state === 'generating'" class="state-text">
      正在为 {{ segmentCount }} 个章节分别生成画像，最多 {{ segmentCount * (includeSelf ? 2 : 1) }} 次 AI 调用；
      已完成的章节会存为快照，中断后重试免费续跑…
    </div>
    <div v-else-if="state === 'error'" class="state-text error-text">{{ error }}</div>

    <div v-else-if="singleChapter && !result" class="empty-state guide">
      只检测到 1 个章节——没有「演变」可对比。TA 的当前画像请看「TA 画像」页签；
      会话更久、消息更多后章节检测才可能分出多章
    </div>

    <div v-else-if="state === 'idle' && !result" class="empty-state guide">
      点「生成对比」按关系章节分段生成画像——从最早的一章往下读到最近，看 TA 给你的印象怎么变；
      已完成的章节会缓存，中断后重试免费续跑
    </div>

    <template v-if="result && state !== 'generating' && state !== 'error'">
      <!-- 竖排时间线全章卡：左缘竖线贯穿 + 章间向下箭头，章头标章号与时间区间 -->
      <div class="segments-stack">
        <template v-for="(seg, index) in segmentList" :key="index">
          <div class="segment-row">
            <span class="row-dot" />
            <div class="segment-card">
              <div class="segment-head">
                <span class="segment-label">{{ seg.label || `第 ${index + 1} 章` }}</span>
                <span class="segment-range">{{ toCompactRange(seg.from_ts, seg.to_ts) }}</span>
              </div>

              <div class="kinds">
                <div v-if="seg.contact" class="kind-block">
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
                </div>

                <div v-if="seg.self" class="kind-block">
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
                </div>
              </div>
            </div>
          </div>
          <div v-if="index < segmentList.length - 1" class="row-arrow">↓</div>
        </template>
      </div>

      <div class="tag-legend">
        <span class="legend-item"><span class="tag unique" />该章独有</span>
        <span class="legend-item"><span class="tag shared" />各章都有</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import {
  getCachedEvolution, getLastEvolutionSettings, rememberEvolutionSettings, runEvolution,
} from './profileEvolutionCache'
import { toCompactRange } from '@/utils/datetime'

type KindBlock = { profile: any; created_at: number; cached: boolean; error?: string } | null
type Segment = { from_ts: number; to_ts: number; label: string; contact?: KindBlock; self?: KindBlock }

const props = defineProps<{
  conversationId: number
  /** 父页视图纪元：切换会话/账号时 +1，用于丢弃过期响应 */
  viewEpoch: number
  /** 章节边界段（deep payload.chapter_spans）：单章时隐藏生成入口（无演变可对比） */
  chapterSpans?: Array<[number, number]>
  contactName?: string
}>()

const state = ref<'idle' | 'generating' | 'done' | 'error'>('idle')
const result = ref<{ segments?: Segment[] } | null>(null)
const error = ref('')
const hint = ref('')
// 含我标记随会话记忆：重挂先回到该会话上次生成的档（否则缓存按原键查不到）
const initialSettings = getLastEvolutionSettings(props.conversationId)
const includeSelf = ref(initialSettings?.self ?? false)

const segmentList = computed(() => result.value?.segments || [])
const segmentCount = computed(() => segmentList.value.length || props.chapterSpans?.length || 0)
// 章节边界已知且只 1 章：诚实降级——单章画像与「TA 画像」页签重复，不值一次 LLM
const singleChapter = computed(() => (props.chapterSpans?.length ?? 0) === 1)

function textOf(profile: any, key: string): string {
  const value = profile?.[key]
  return typeof value === 'string' ? value.trim() : ''
}

function listOf(profile: any, key: string): string[] {
  const value = profile?.[key]
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : []
}

function tagRows(index: number): Array<{ name: string; cls: string; title: string }> {
  // 标签按跨章在场着色：仅本章出现 → 琥珀差异色；多章都有 → 中性色
  const own = new Set(listOf(segmentList.value[index]?.contact?.profile, 'personality_tags'))
  const elsewhere = new Set<string>()
  segmentList.value.forEach((seg, i) => {
    if (i !== index) {
      listOf(seg.contact?.profile, 'personality_tags').forEach((name) => elsewhere.add(name))
    }
  })
  return [...own].map((name) => {
    if (!elsewhere.has(name)) {
      return { name, cls: 'unique', title: '仅该章出现' }
    }
    return { name, cls: 'shared', title: '多章都有' }
  })
}

async function generate(force: boolean) {
  // 会话一致性守卫：慢响应后到时不能覆盖切走后的面板（画像张冠李戴）
  const requestConv = props.conversationId
  const requestEpoch = props.viewEpoch
  // 记住本次发起的含我标记：切页回来/切回本会话按原标记直接恢复显示
  rememberEvolutionSettings(requestConv, includeSelf.value)
  state.value = 'generating'
  error.value = ''
  hint.value = ''
  try {
    const res = await runEvolution(requestConv, includeSelf.value, force)
    if (requestConv !== props.conversationId || requestEpoch !== props.viewEpoch) return
    if (res?.cancelled) {
      state.value = result.value ? 'done' : 'idle'
      hint.value = '已取消；已完成的章节已存为快照，重试会续跑'
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
    if (cachedCount) hint.value = `${cachedCount} 个章节命中历史快照，未重复调用 AI`
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
  () => [props.conversationId, props.viewEpoch],
  () => {
    // 切会话：含我标记跟着切到该会话上次的生成档，缓存按原键命中直接显示
    const last = getLastEvolutionSettings(props.conversationId)
    includeSelf.value = last?.self ?? false
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
  const entry = getCachedEvolution(props.conversationId, includeSelf.value)
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
.self-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  cursor: pointer;
  user-select: none;
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
  color: var(--ct-color-error, #E8656F);
}

.empty-state.guide {
  text-align: left;
  line-height: 1.8;
}

/* 竖排时间线：左缘竖线贯穿全栈，每段一个圆点锚在竖线上 */
.segments-stack {
  position: relative;
  display: flex;
  flex-direction: column;
}

.segments-stack::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 14px;
  bottom: 14px;
  width: 2px;
  background: var(--ct-border-color);
  border-radius: 999px;
}

.segment-row {
  position: relative;
  padding-left: var(--ct-space-lg);
}

.row-dot {
  position: absolute;
  left: 0;
  top: 14px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--ct-color-primary);
  background: var(--ct-bg-card);
}

.row-arrow {
  padding-left: var(--ct-space-lg);
  text-align: center;
  color: var(--ct-text-tertiary);
  line-height: 1.2;
  margin: var(--ct-space-xs) 0;
}

.segment-card {
  background: var(--ct-bg-sunken);
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

.segment-label {
  color: var(--ct-color-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.segment-range {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

/* 全宽卡内 TA/我两块并排（窄屏自动叠放） */
.kinds {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--ct-space-md);
}

.kind-title {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
  margin: var(--ct-space-xs) 0 var(--ct-space-xs);
}

.kind-title:first-child {
  margin-top: 0;
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
  color: var(--ct-text-secondary);
}

.tag.unique {
  border-color: #8F5B14;
  color: #8F5B14;
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
