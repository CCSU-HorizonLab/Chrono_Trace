<template>
  <div class="qa-shell">
    <div class="qa-header">
      <div class="qa-header-row">
        <h3 class="qa-title">问问微信</h3>
        <button v-if="qaHistory.length" class="text-action-btn qa-clear-btn" @click="handleClearQa">清空对话</button>
      </div>
      <p class="qa-subtitle">向 {{ contactName }} 的聊天记录提问，回答附带引用溯源（仅检索当前联系人）</p>
      <!-- 语义索引懒补在途：本轮回答仍以关键词检索为主，补完自动生效 -->
      <p v-if="qaIndexingHint" class="qa-indexing-hint">正在为该会话补充语义索引，完成后回答会更准</p>
    </div>

    <!-- 聊天流：时间正序，问答成对出现；流式增量在距底时自动跟随，上滚即停跟随 -->
    <div ref="qaChatBox" class="qa-chat" @scroll="handleQaScroll">
      <div v-if="!qaHistory.length && !qaLoading" class="qa-empty">
        <p class="qa-empty-text">还没有提问记录。试试：</p>
        <div class="qa-suggest-row">
          <button
            v-for="s in qaSuggestions"
            :key="s"
            class="qa-suggest-chip"
            @click="handlePickSuggestion(s)"
          >{{ s }}</button>
        </div>
      </div>

      <div v-for="(item, idx) in qaHistory" :key="item.id" class="qa-msg">
        <div class="qa-row qa-row-user">
          <div class="qa-bubble qa-bubble-user">
            <span class="qa-bubble-text">{{ item.question }}</span>
          </div>
        </div>
        <div class="qa-row qa-row-ai">
          <span class="qa-a-mark">AI</span>
          <div class="qa-bubble qa-bubble-ai">
            <!-- 错误内联：不再弹窗打断，原地重试 -->
            <div v-if="item.error" class="qa-error">
              <span class="qa-error-text">{{ item.error }}</span>
              <button class="text-action-btn" @click="handleRetryQa(item)">重试</button>
            </div>
            <template v-else>
              <!-- 首字未到：打字点等待态 -->
              <div v-if="item.streaming && !item.answer" class="qa-typing">
                <span class="qa-typing-dots"><i></i><i></i><i></i></span>
                <span class="qa-typing-hint">正在检索聊天记录并生成回答...</span>
              </div>
              <template v-else>
                <div class="qa-bubble-text qa-md" @click="handleCiteClick" v-html="renderQaEntryAnswer(item)"></div>
                <span v-if="item.streaming" class="qa-stream-cursor" aria-hidden="true"></span>
              </template>
              <span v-if="item.stopped" class="qa-stopped-badge">已停止</span>
              <span v-if="item.truncated" class="qa-stopped-badge">已截断（网络中断，回答不完整）</span>
              <span v-if="item.degraded" class="qa-stopped-badge">模型暂不可用 · 检索直出</span>
              <template v-if="!item.streaming">
                <div class="qa-actions">
                  <button
                    v-if="idx === qaHistory.length - 1 && !qaLoading"
                    class="text-action-btn"
                    @click="handleRegenerateQa"
                  >重新生成</button>
                </div>
                <details v-if="item.citations && item.citations.length" class="qa-citations-fold">
                  <summary class="qa-citations-title">引用溯源（{{ item.citations.length }} 条）</summary>
                  <div v-for="(cite, cIdx) in item.citations" :key="cIdx" class="qa-citation-row">
                    <span class="qa-citation-idx">[{{ cite.index }}]</span>
                    <span class="qa-citation-meta">{{ formatQaTime(cite.timestamp) }} · {{ cite.is_sender ? '我' : contactName }}</span>
                    <span class="qa-citation-text">"{{ cite.text }}"</span>
                  </div>
                </details>
                <details v-if="item.memoryRefs && item.memoryRefs.length" class="qa-citations-fold qa-memory-fold">
                  <summary class="qa-citations-title">参考记忆（{{ item.memoryRefs.length }} 条）· 可就地纠错</summary>
                  <div v-for="(mem, mIdx) in item.memoryRefs" :key="mIdx" class="qa-citation-row qa-memory-row">
                    <span class="qa-memory-kind" :class="{ fact: mem.source === 'fact_memory' }">
                      {{ mem.source === 'fact_memory' ? '事实' : '话题' }}
                    </span>
                    <span class="qa-citation-text">"{{ mem.content }}"</span>
                    <span v-if="mem.as_of" class="qa-citation-meta">{{ formatQaTime(mem.as_of) }}</span>
                    <template v-if="mem.source === 'fact_memory' && mem.ref_id">
                      <span v-if="qaMemoryFeedback[mem.ref_id]" class="qa-memory-done">
                        {{ qaMemoryFeedback[mem.ref_id] === 'inaccurate' ? '已标记不准确' : '已忘记' }}
                      </span>
                      <template v-else>
                        <button
                          class="text-action-btn qa-memory-btn"
                          :disabled="qaMemoryBusy[mem.ref_id]"
                          @click="handleMemoryFeedback(mem, 'inaccurate')"
                        >不准确</button>
                        <button
                          class="text-action-btn qa-memory-btn"
                          :disabled="qaMemoryBusy[mem.ref_id]"
                          @click="handleMemoryFeedback(mem, 'forget')"
                        >忘记</button>
                      </template>
                    </template>
                  </div>
                </details>
              </template>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区：auto-grow 文本域 + 内嵌发送/停止二合一；生成中可继续打字 -->
    <div class="qa-input-row">
      <div class="qa-input-box" :class="{ focused: qaInputFocused }">
        <textarea
          ref="qaInputEl"
          v-model="qaInput"
          class="qa-input"
          rows="1"
          placeholder="例如：我们聊过哪些共同爱好？TA 对加班是什么态度？"
          maxlength="200"
          @input="autoGrowQaInput"
          @focus="qaInputFocused = true"
          @blur="qaInputFocused = false"
          @keydown.enter.exact="handleQaEnter"
        ></textarea>
        <button
          class="qa-send-btn"
          :class="{ stop: qaLoading }"
          :disabled="!qaLoading && !qaInput.trim()"
          :title="qaLoading ? '停止生成' : '发送（Enter 发送，Shift+Enter 换行）'"
          @click="qaLoading ? handleStopQa() : handleAskHistory()"
        >
          <svg v-if="qaLoading" class="qa-send-icon" viewBox="0 0 16 16" aria-hidden="true">
            <rect x="3" y="3" width="10" height="10" rx="2" fill="currentColor"></rect>
          </svg>
          <svg v-else class="qa-send-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 13V3.8" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>
            <path d="M3.8 7 8 2.8 12.2 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"></path>
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 问问微信聊天流（智囊页·问答模式）：流式打字机 + 引用溯源 + 参考记忆
 * 就地纠错。自 Analytics 页签整体迁出（重设计 §4.4），状态自持——
 * 问答记录按联系人隔离（切人即清），流式推送（chrono:qa-push）按
 * req_id 匹配在途气泡。
 */
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import { api, bridgeReady } from '@/api/bridge'
import { renderQaAnswer } from '@/utils/qaMarkdown'

const props = defineProps<{
  conversationId: number
  contactName: string
}>()

type QaCitation = { index: number; message_id: number; timestamp: number; is_sender: number; text: string }
// 参考记忆溯源：AI 本轮实际采用的 RAG 记忆（fact 通道 ref_id=事实主键，
// 可就地纠错；文档通道只读展示）
type QaMemoryRef = { content: string; source: string; ref_id: number; subject?: string; as_of?: number | null; confidence?: number | null }
// streaming：LLM 增量在途；stopped：用户点停已定格部分文本；error：内联错误（可重试）；
// degraded：LLM 失败降级检索直出；truncated：流式中途断网已收部分当结果
type QaEntry = {
    id: number; question: string; answer: string; citations: QaCitation[]; memoryRefs?: QaMemoryRef[]
    streaming?: boolean; stopped?: boolean; error?: string; reqId?: string
    degraded?: boolean; truncated?: boolean
}
// 时间正序（聊天流展示：新问答 push 到尾部，容器自动滚底）
const qaHistory = ref<QaEntry[]>([])
const qaInput = ref('')
const qaLoading = ref(false)
// 语义索引懒补在途提示（切联系人/重置账号时清位；不轮询，下次提问自然生效）
const qaIndexingHint = ref(false)
const qaChatBox = ref<HTMLElement | null>(null)
const qaInputEl = ref<HTMLTextAreaElement | null>(null)
const qaInputFocused = ref(false)
// 吸底跟随：流式增量只在用户位于底部附近时滚底，上滚阅读即停跟随
const qaAutoScroll = ref(true)
// 当前在途请求标识：流式增量按它匹配到气泡（重试/重新生成各自新发一个）
let qaReqId = ''

function scrollQaToBottom() {
    nextTick(() => {
        const el = qaChatBox.value
        if (el) el.scrollTop = el.scrollHeight
    })
}
watch(() => qaHistory.value.length, scrollQaToBottom)
// 生成结束的滚底走跟随模式（maybeScrollQa）：用户上滚阅读时不被
// 强行拉回底部；发送时的强制滚底由 runAsk push 条目后显式做
watch(qaLoading, maybeScrollQa)

function handleQaScroll() {
    const el = qaChatBox.value
    if (!el) return
    qaAutoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 48
}

function maybeScrollQa() {
    if (!qaAutoScroll.value) return
    scrollQaToBottom()
}

function formatQaTime(ts: number): string {
    if (!ts) return '--'
    return new Date(ts * 1000).toLocaleString('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
    })
}

// 空态建议问题：通用记忆问句模板（点击填入输入框），不动输入焦点外的任何状态
const qaSuggestions = computed(() => [
    '我们最近聊了什么话题？',
    `${props.contactName}提过哪些喜欢的东西？`,
    '我们聊过哪些共同爱好？',
    '上次我们聊得最开心的是什么？',
])

function handlePickSuggestion(text: string) {
    qaInput.value = text
    autoGrowQaInput()
    qaInputEl.value?.focus()
}

// 模型门槛：未启用任何 LLM 时返回错误文案（由调用方内联到气泡，不弹窗）
async function ensureQaLlmReady(): Promise<string | null> {
    try {
        const llmRes = await api.get_llm_models()
        const hasActive = Boolean(llmRes?.ok && llmRes.models?.some((m: any) => m.is_active))
        if (!hasActive) return '问问微信需要 LLM 模型，请先在「设置 → 模型服务」中配置并启用一个模型。'
        return null
    } catch {
        return '模型状态查询失败，请稍后重试。'
    }
}

// 输入区：auto-grow（1~5 行）；IME 组合态回车只上屏不发送
function autoGrowQaInput() {
    const el = qaInputEl.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`
}

function handleQaEnter(e: KeyboardEvent) {
    // 中文输入法确认候选词的回车（isComposing/keyCode 229 双保险，
    // 旧 Safari 用后者）：上屏不发送——此前 keyup.enter 无守卫，
    // 组合确认的回车会把半截候选文本直接发出去
    if (e.isComposing || e.keyCode === 229) return
    e.preventDefault() // Enter 发送（单行语义），Shift+Enter 走默认换行
    handleAskHistory()
}

// 回答 HTML 渲染缓存：流式期间每帧全列表重渲染，历史条目 answer
// 不变不得重跑 markdown 解析（按条目对象 WeakMap，answer 变更自动失效）
const qaAnswerCache = new WeakMap<QaEntry, { answer: string; html: string }>()
function renderQaEntryAnswer(item: QaEntry): string {
    let cached = qaAnswerCache.get(item)
    if (!cached || cached.answer !== item.answer) {
        cached = { answer: item.answer, html: renderQaAnswer(item.answer) }
        qaAnswerCache.set(item, cached)
    }
    return cached.html
}

// 流式增量（chrono:qa-push，App.vue 转投 CustomEvent）：按 req_id
// 匹配在途气泡；已定格（停止/终态）的气泡丢弃迟到增量。增量经
// rAF 尾随节流提交——token 级直写会让每 16ms 数次全组件重渲染
// 加整段 markdown 重解析（O(len²)），攒一帧提交观感不变
let qaStreamBuffer = ''
let qaStreamEntry: QaEntry | null = null
let qaFlushScheduled = false

function flushQaStream() {
    qaFlushScheduled = false
    if (qaStreamEntry && qaStreamBuffer) {
        qaStreamEntry.answer += qaStreamBuffer
        qaStreamBuffer = ''
        maybeScrollQa()
    }
}

function scheduleQaFlush() {
    if (qaFlushScheduled) return
    qaFlushScheduled = true
    requestAnimationFrame(flushQaStream)
}

function dropQaStreamBuffer() {
    qaStreamBuffer = ''
    qaStreamEntry = null
}

// 停止时零文本被移除的在途条目：完整答案返回时回收（token 已花，
// 答案不静默丢）。凭证存 reqId 原始字符串——条目对象经 reactive 数组
// find 取出是代理，与 runAsk 闭包里的裸对象 === 恒不相等；清空对话/
// 重发新问后旧条目不得复活成幽灵回答（配 qaReqId 纪元守卫双重确认）
let qaStoppedReqId: string | null = null

function handleQaPush(e: Event) {
    const payload = (e as CustomEvent).detail
    const events = Array.isArray(payload) ? payload : [payload]
    for (const ev of events) {
        if (!ev || ev.type !== 'delta' || ev.req_id !== qaReqId) continue
        if (Number(ev.conversation_id) !== props.conversationId) continue
        const entry = qaHistory.value.find(item => item.reqId === ev.req_id)
        if (!entry || !entry.streaming) continue
        qaStreamEntry = entry
        qaStreamBuffer += String(ev.text || '')
        scheduleQaFlush()
    }
}

async function runAsk(question: string) {
    if (qaLoading.value || !props.conversationId || !question) return
    qaLoading.value = true
    qaAutoScroll.value = true
    const conversationId = props.conversationId
    const reqId = `qa_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    qaReqId = reqId
    const entry: QaEntry = {
        id: Date.now(), // 稳定键：复制反馈不能跟着列表索引走
        question,
        answer: '',
        citations: [],
        streaming: true,
        reqId,
    }
    qaHistory.value.push(entry)
    scrollQaToBottom()
    try {
        const gateError = await ensureQaLlmReady()
        if (gateError) {
            entry.streaming = false
            entry.error = gateError
            return
        }
        await bridgeReady()
        // 多轮：带上最近 3 轮可作上下文的问答——本条在途、失败、
        // 停止半截、降级通知（那不是模型答的）都不算有效答案。
        // 排除本条用 reqId 原始值：数组元素经 reactive 取出是代理，
        // 与闭包裸对象 !== 恒真，本条混进历史轮会带空答案占坑
        const history = qaHistory.value
            .filter(e => e.reqId !== reqId && e.answer && !e.error && !e.stopped && !e.degraded && !e.truncated)
            .slice(-3)
            .map(e => ({ question: e.question, answer: e.answer }))
        const res = await api.ask_history(conversationId, question, history, reqId)
        if (conversationId !== props.conversationId) return // 已切换联系人，丢弃过期回答
        if (res?.ok) {
            // 取消竞态：点停后完整答案恰已返回——完整答案优先于停止定格
            entry.answer = String(res.answer || entry.answer)
            entry.citations = Array.isArray(res.citations) ? res.citations : []
            entry.memoryRefs = Array.isArray(res.memory_refs) ? res.memory_refs : []
            entry.stopped = false
            entry.degraded = res.degraded === true
            entry.truncated = res.truncated === true
            // 停止时零文本被移除的条目回收插回（token 已花，答案不静默丢）；
            // 纪元守卫防清空对话/停止后重发的旧条目复活成幽灵回答
            if (qaHistory.value.indexOf(entry) < 0) {
                if (qaStoppedReqId && qaStoppedReqId === reqId && qaReqId === reqId) {
                    qaHistory.value.push(entry)
                }
            }
            if (qaStoppedReqId === reqId) qaStoppedReqId = null
            // 后台语义索引懒补在途（不轮询：下次提问自然用上新索引）
            qaIndexingHint.value = res.semantic_indexing === true
        } else {
            if (entry.stopped) return // 本地已定格部分文本，取消返回不覆盖
            entry.error = String(res?.error || '问答失败，请重试')
        }
    } catch (e: any) {
        if (!entry.stopped) entry.error = String(e?.message || '问答异常')
    } finally {
        entry.streaming = false
        entry.reqId = ''
        // 终态后未提交缓冲一律作废（答案以返回值为准）；纪元已易主时
        // 缓冲属新请求的流，不得误清（对齐下方 qaReqId 守卫）
        if (qaReqId === reqId) dropQaStreamBuffer()
        // 纪元守卫：停止后立即重发时 qaReqId 已易主，旧请求的收尾
        // 不得熄灭新请求的 loading 态
        if (qaReqId === reqId) {
            qaReqId = ''
            qaLoading.value = false
        }
    }
}

async function handleAskHistory() {
    const question = qaInput.value.trim()
    // 守卫与 runAsk 同口径先过再清输入：无会话等被拒场景下输入
    // 不被吞（runAsk 静默 return 无气泡留档，问题就丢了）
    if (!question || qaLoading.value || !props.conversationId) return
    qaInput.value = '' // 发送即清空（失败已有问题气泡留档，错误条内联重试）
    nextTick(autoGrowQaInput)
    await runAsk(question)
}

function handleRetryQa(item: QaEntry) {
    if (qaLoading.value) return
    const idx = qaHistory.value.indexOf(item)
    if (idx >= 0) qaHistory.value.splice(idx, 1)
    void runAsk(item.question)
}

function handleRegenerateQa() {
    if (qaLoading.value || !qaHistory.value.length) return
    const last = qaHistory.value[qaHistory.value.length - 1]
    qaHistory.value.pop()
    void runAsk(last.question)
}

// 停止：本地立即定格部分文本（有字保留已停态、无字整条移除），
// 再通知后端取消；迟到增量被 streaming=false 天然丢弃
async function handleStopQa() {
    if (!qaLoading.value || !props.conversationId) return
    const entry = qaHistory.value.find(item => item.streaming)
    if (entry) {
        // 先落未提交的流式缓冲再判空（定格所见即全部已收）
        if (qaStreamEntry === entry) {
            entry.answer += qaStreamBuffer
            dropQaStreamBuffer()
        }
        entry.streaming = false
        if (entry.answer) {
            entry.stopped = true
        } else {
            const idx = qaHistory.value.indexOf(entry)
            if (idx >= 0) qaHistory.value.splice(idx, 1)
            qaStoppedReqId = String(entry.reqId || '') // 零文本移除：完整答案返回时按 reqId 回收
        }
    }
    qaLoading.value = false
    try {
        await bridgeReady()
        await api.cancel_history_qa(props.conversationId)
    } catch {
        // 取消失败不打断（后端请求会自行超时返回）
    }
}

function handleClearQa() {
    if (qaLoading.value) handleStopQa()
    qaHistory.value = []
    qaStoppedReqId = null // 清空意图优先：被移除条目不得借回收复活
}

// 参考记忆就地纠错：问答现场直接「不准确/忘记」，与记忆管理弹窗同接口；
// 反馈按事实主键全局去重（同一事实多处引用一次纠错全部生效）
const qaMemoryFeedback = reactive<Record<number, 'inaccurate' | 'forget'>>({})
const qaMemoryBusy = reactive<Record<number, boolean>>({})

async function handleMemoryFeedback(ref: QaMemoryRef, action: 'inaccurate' | 'forget') {
    const fid = Number(ref.ref_id || 0)
    if (!fid || qaMemoryFeedback[fid] || qaMemoryBusy[fid]) return
    qaMemoryBusy[fid] = true
    try {
        await bridgeReady()
        const res = await api.set_fact_feedback(fid, action)
        if (res?.ok) qaMemoryFeedback[fid] = action
    } catch {
        // 失败保持可重试，不打断问答流
    } finally {
        qaMemoryBusy[fid] = false
    }
}

// 引用上标可点：展开本气泡的引用溯源并滚到可见
function handleCiteClick(e: MouseEvent) {
    const mark = (e.target as HTMLElement | null)?.closest?.('.qa-cite-mark')
    if (!mark) return
    const fold = mark.closest('.qa-bubble')?.querySelector('.qa-citations-fold') as HTMLDetailsElement | null
    if (!fold) return
    fold.open = true
    fold.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}

// 问答记录按联系人隔离（F1 同源）：切人清历史与在途（token 白烧的
// 取消对齐原页签卸载路径）
watch(() => props.conversationId, (id) => {
    if (qaLoading.value) void handleStopQa()
    qaHistory.value = []
    qaIndexingHint.value = false
    qaStoppedReqId = null
    if (!id) return
})

window.addEventListener('chrono:qa-push', handleQaPush)
onUnmounted(() => {
    window.removeEventListener('chrono:qa-push', handleQaPush)
    // 在途问答随页面离去取消（对齐切联系人路径；离开后推送无人接、token 白烧）
    if (qaLoading.value && props.conversationId) {
        api.cancel_history_qa(props.conversationId).catch(() => {})
    }
})
</script>

<style scoped>
/* 通用小文本操作按钮（清空对话/复制/重试等，自 Analytics 迁入） */
.text-action-btn {
  flex-shrink: 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-sunken);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  padding: 2px 10px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.text-action-btn:hover {
  color: var(--ct-color-primary);
  border-color: var(--ct-color-primary);
}

/* --- 问问微信（历史问答·聊天框） --- */
.qa-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding: var(--ct-space-lg);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  min-height: 0; /* 聊天流在 flex 列内收缩，出滚动条而不是撑破页 */
}

.qa-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 标题行：标题左、清空对话右 */
.qa-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-md);
}

.qa-clear-btn {
  flex-shrink: 0;
}

.qa-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ct-text-primary);
}

.qa-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

/* 语义索引懒补在途的轻提示（一次性标志，不轮询进度） */
.qa-indexing-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ct-color-primary, #5A4BC4);
}

/* 聊天流：自带滚动，新消息滚底 */
.qa-chat {
  flex: 1;
  min-height: 280px;
  max-height: 56vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding-right: 4px;
}

.qa-empty {
  margin: auto; /* 空态在聊天流内垂直居中 */
  padding: var(--ct-space-2xl);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ct-space-md);
  text-align: center;
  border-radius: var(--ct-radius-md);
}

.qa-empty-text {
  margin: 0;
  font-size: 13px;
  color: var(--ct-text-tertiary);
}

/* 空态建议问题：点击即填入输入框 */
.qa-suggest-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  max-width: 420px;
}

.qa-suggest-chip {
  padding: 5px 12px;
  font-size: 12px;
  color: var(--ct-text-secondary);
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.qa-suggest-chip:hover {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-subtle);
}

.qa-msg {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.qa-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.qa-row-user {
  justify-content: flex-end;
}

.qa-bubble {
  max-width: 82%;
  padding: 10px 14px;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qa-bubble-user {
  background: var(--ct-color-primary-subtle);
  border-bottom-right-radius: 4px;
}

.qa-bubble-ai {
  background: var(--ct-bg-card);
  border-bottom-left-radius: 4px;
}

.qa-bubble-text {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
  color: var(--ct-text-primary);
}

.qa-a-mark {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--ct-radius-full);
  font-size: 10px;
  font-weight: 600;
  background: var(--ct-color-success-light);
  color: var(--ct-color-success);
}

/* 输入区：胶囊容器（auto-grow 文本域 + 内嵌发送/停止二合一），焦点
   光圈落在容器上（textarea 自身无边框） */
.qa-input-row {
  display: flex;
  align-items: flex-end;
}

.qa-input-box {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 6px 6px 6px 14px;
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.qa-input-box.focused {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 3px var(--ct-color-primary-tint);
}

.qa-input {
  flex: 1;
  padding: 6px 0;
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
  border: none;
  background: transparent;
  color: var(--ct-text-primary);
  outline: none;
  resize: none; /* 高度由 autoGrowQaInput 管（1~5 行） */
  max-height: 132px;
  overflow-y: auto;
}

.qa-input::placeholder {
  color: var(--ct-text-tertiary);
}

/* 发送/停止二合一：发送态 primary 上箭头，生成中同位变停止方块 */
.qa-send-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--ct-radius-full);
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse); /* primary 底反白字（令牌而非裸值） */
  cursor: pointer;
  transition: background-color 0.15s ease, opacity 0.15s ease;
}

.qa-send-btn:not(:disabled):hover {
  background: var(--ct-color-primary-hover);
}

.qa-send-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.qa-send-icon {
  width: 16px;
  height: 16px;
}

/* 回答操作条：复制 / 重新生成 */
.qa-actions {
  display: flex;
  gap: 6px;
}

.qa-actions .text-action-btn {
  align-self: flex-start;
}

/* 回答正文（受限 Markdown 渲染：段落/列表/加粗/引用上标） */
.qa-md {
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
  color: var(--ct-text-primary);
}

.qa-md p {
  margin: 0 0 6px;
}

.qa-md p:last-child {
  margin-bottom: 0;
}

.qa-md ul,
.qa-md ol {
  margin: 0 0 6px;
  padding-left: 20px;
}

.qa-md li {
  margin: 2px 0;
}

/* 引用上标（[n] 渲染产物）：可点，展开本气泡引用溯源 */
.qa-cite-mark {
  font-size: 10px;
  margin: 0 1px;
  padding: 0 3px;
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-subtle);
  border-radius: var(--ct-radius-sm);
  cursor: pointer;
  user-select: none;
}

/* 流式光标：增量在途时文尾呼吸竖条 */
.qa-stream-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--ct-color-primary);
  animation: qa-cursor-blink 1s step-end infinite;
}

@keyframes qa-cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* 停止定格徽标（非错误：沉底中性徽标） */
.qa-stopped-badge {
  align-self: flex-start;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-full);
}

/* 内联错误条：error tint 底 + 重试，不打断（不弹窗） */
.qa-error {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  padding: 8px 10px;
  background: var(--ct-color-error-tint);
  border-radius: var(--ct-radius-md);
}

.qa-error-text {
  flex: 1;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-color-error);
  word-break: break-word;
}

.qa-citations-fold {
  border-top: 1px dashed var(--ct-border-color);
  padding-top: 8px;
}

.qa-citations-title {
  font-size: 11px;
  color: var(--ct-text-tertiary);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}

.qa-citation-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 11px;
  line-height: 1.6;
  padding-top: 4px;
}

.qa-citation-idx {
  flex-shrink: 0;
  font-family: var(--ct-font-mono);
  color: var(--ct-color-primary);
}

.qa-citation-meta {
  flex-shrink: 0;
  color: var(--ct-text-tertiary);
}

.qa-citation-text {
  color: var(--ct-text-secondary);
  font-style: italic;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
}

/* 参考记忆行：kind 徽标 + 陈述 + 就地纠错按钮（与记忆管理弹窗同接口） */
.qa-memory-kind {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: var(--ct-radius-full);
  font-size: 10px;
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-hover);
}

.qa-memory-kind.fact {
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
}

.qa-memory-btn {
  flex-shrink: 0;
  font-size: 11px;
}

.qa-memory-btn:not(:disabled):hover {
  color: var(--ct-color-error);
}

.qa-memory-done {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--ct-text-tertiary);
}

/* 加载占位：打字点 + 进度文案（气泡内独立 div，display:flex 自带） */
.qa-typing {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.qa-typing-dots {
  display: inline-flex;
  gap: 3px;
  flex-shrink: 0;
}

.qa-typing-dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ct-text-tertiary);
  animation: qa-typing-blink 1.2s infinite ease-in-out;
}

.qa-typing-dots i:nth-child(2) { animation-delay: 0.2s; }
.qa-typing-dots i:nth-child(3) { animation-delay: 0.4s; }

.qa-typing-hint {
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

@keyframes qa-typing-blink {
  0%, 60%, 100% { opacity: 0.25; }
  30% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .qa-typing-dots i { animation: none; opacity: 0.6; }
  .qa-stream-cursor { animation: none; opacity: 0.7; }
}
</style>
