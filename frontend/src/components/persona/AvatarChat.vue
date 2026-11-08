<template>
  <div class="av-shell">
    <div class="av-header">
      <div class="av-header-row">
        <h3 class="av-title">和 {{ contactName }} 聊聊</h3>
        <button v-if="msgs.length" class="text-action-btn" @click="handleClear">清空对话</button>
      </div>
      <p class="av-subtitle">
        分身以 TA 的语气档案、画像与相关记忆作答{{ voiceNote }}
      </p>
    </div>

    <!-- 对话流：时间正序；流式增量在距底时自动跟随，上滚即停跟随 -->
    <div ref="chatBox" class="av-chat" @scroll="handleScroll">
      <div v-if="!msgs.length && !loading" class="av-empty">
        <p class="av-empty-text">还没有开始。可以这样开头：</p>
        <div class="av-suggest-row">
          <button
            v-for="s in suggestions"
            :key="s"
            class="av-suggest-chip"
            @click="handlePickSuggestion(s)"
          >{{ s }}</button>
        </div>
      </div>

      <div v-for="(item, idx) in msgs" :key="item.id" class="av-msg">
        <div class="av-row av-row-user">
          <div class="av-bubble av-bubble-user">
            <span class="av-bubble-text">{{ item.text }}</span>
          </div>
        </div>
        <div class="av-row av-row-avatar">
          <span class="av-mark" :title="contactName">{{ markChar }}</span>
          <div class="av-bubble av-bubble-avatar">
            <!-- 错误内联：原地重试，不弹窗打断 -->
            <div v-if="item.error" class="av-error">
              <span class="av-error-text">{{ item.error }}</span>
              <button class="text-action-btn" @click="handleRetry(item)">重试</button>
            </div>
            <template v-else>
              <div v-if="item.streaming && !item.reply" class="av-typing">
                <span class="av-typing-dots"><i></i><i></i><i></i></span>
                <span class="av-typing-hint">{{ contactName }}正在想怎么回…</span>
              </div>
              <template v-else>
                <div class="av-bubble-text">{{ item.reply }}</div>
                <span v-if="item.streaming" class="av-stream-cursor" aria-hidden="true"></span>
              </template>
              <span v-if="item.stopped" class="av-state-badge">已停止</span>
              <span v-if="item.truncated" class="av-state-badge">已截断（网络中断，回复不完整）</span>
              <div v-if="!item.streaming" class="av-actions">
                <!-- 逐条边界标注：截图/复制件脱离页头横幅后仍可辨认非本人 -->
                <span class="av-ai-tag">AI 模拟</span>
                <button
                  class="text-action-btn"
                  :class="{ copied: copiedKey === `a-${item.id}` }"
                  @click="handleCopy(item.reply, `a-${item.id}`)"
                >
                  {{ copiedKey === `a-${item.id}` ? '已复制' : '复制' }}
                </button>
                <button
                  v-if="idx === msgs.length - 1 && !loading"
                  class="text-action-btn"
                  @click="handleRegenerate"
                >换种回法</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区：auto-grow 文本域 + 发送/停止二合一；生成中可继续打字 -->
    <div class="av-input-row">
      <div class="av-input-box" :class="{ focused: inputFocused }">
        <textarea
          ref="inputEl"
          v-model="input"
          class="av-input"
          rows="1"
          :placeholder="`像平时那样跟 ${contactName} 说话…`"
          maxlength="200"
          @input="autoGrow"
          @focus="inputFocused = true"
          @blur="inputFocused = false"
          @keydown.enter.exact="handleEnter"
        ></textarea>
        <button
          class="av-send-btn"
          :class="{ stop: loading }"
          :disabled="!loading && !input.trim()"
          :title="loading ? '停止生成' : '发送（Enter 发送，Shift+Enter 换行）'"
          @click="loading ? handleStop() : handleSend()"
        >
          <svg v-if="loading" class="av-send-icon" viewBox="0 0 16 16" aria-hidden="true">
            <rect x="3" y="3" width="10" height="10" rx="2" fill="currentColor"></rect>
          </svg>
          <svg v-else class="av-send-icon" viewBox="0 0 16 16" aria-hidden="true">
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
 * AI 分身对话流（画像页·分身聊天，重设计 §6.3）：骨架复刻 QaChat
 * （流式打字机 chrono:avatar-push 按 req_id 匹配、rAF 节流、停止定格、
 * 错误内联重试、IME 组合态守卫），去问答特有的引用/记忆纠错，加
 * 「换种回法」。分身人格（画像+语气采样+相关记忆）在后端组装，
 * 前端只管对话流。
 */
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { api, bridgeReady } from '@/api/bridge'
import { copyText } from '@/utils/clipboard'

const props = defineProps<{
  conversationId: number
  contactName: string
}>()

type AvEntry = {
  id: number
  text: string        // 用户这轮说的话
  reply: string       // 分身回复
  streaming?: boolean
  stopped?: boolean
  truncated?: boolean
  error?: string
  reqId?: string
}

const msgs = ref<AvEntry[]>([])
const input = ref('')
const loading = ref(false)
const chatBox = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)
const inputFocused = ref(false)
// 吸底跟随：流式增量只在用户位于底部附近时滚底，上滚阅读即停跟随
const autoScroll = ref(true)
// 当前在途请求标识：流式增量按它匹配到气泡
let reqId = ''
// 首轮回复后的采样规模小字（后端 voice.sample_count）
const voiceCount = ref(0)

const markChar = computed(() => (props.contactName || 'TA').trim().charAt(0) || 'T')
const voiceNote = computed(() =>
  voiceCount.value ? `（基于 ${voiceCount.value} 条 TA 消息采样）` : ''
)
const suggestions = computed(() => [
  '最近过得怎么样？',
  '还记得我们上次聊的事吗？',
  `要是能再跟${props.contactName}说句话，你想说什么？`,
  '那件事要是重来一次，你会怎么做？',
])

function scrollToBottom() {
  nextTick(() => {
    const el = chatBox.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
watch(() => msgs.value.length, scrollToBottom)
watch(loading, maybeScroll)

function handleScroll() {
  const el = chatBox.value
  if (!el) return
  autoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 48
}

function maybeScroll() {
  if (!autoScroll.value) return
  scrollToBottom()
}

// ===== 复制（带瞬时反馈）=====
const copiedKey = ref('')
let copyTimer: ReturnType<typeof setTimeout> | null = null

function handleCopy(text: string, key: string) {
  if (!copyText(text)) return
  copiedKey.value = key
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { copiedKey.value = '' }, 2000)
}

function handlePickSuggestion(text: string) {
  input.value = text
  autoGrow()
  inputEl.value?.focus()
}

// 输入区 auto-grow（1~5 行）；IME 组合态回车只上屏不发送
function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 132)}px`
}

function handleEnter(e: KeyboardEvent) {
  if (e.isComposing || e.keyCode === 229) return
  e.preventDefault()
  handleSend()
}

// ===== 流式增量（chrono:avatar-push）：rAF 尾随节流，token 级直写
// 会触发全列表重渲染，攒一帧提交观感不变（QaChat 同款）
let streamBuffer = ''
let streamEntry: AvEntry | null = null
let flushScheduled = false

function flushStream() {
  flushScheduled = false
  if (streamEntry && streamBuffer) {
    streamEntry.reply += streamBuffer
    streamBuffer = ''
    maybeScroll()
  }
}

function scheduleFlush() {
  if (flushScheduled) return
  flushScheduled = true
  requestAnimationFrame(flushStream)
}

function dropStreamBuffer() {
  streamBuffer = ''
  streamEntry = null
}

function handlePush(e: Event) {
  const payload = (e as CustomEvent).detail
  const events = Array.isArray(payload) ? payload : [payload]
  for (const ev of events) {
    if (!ev || ev.type !== 'delta' || ev.req_id !== reqId) continue
    if (Number(ev.conversation_id) !== props.conversationId) continue
    const entry = msgs.value.find(item => item.reqId === ev.req_id)
    if (!entry || !entry.streaming) continue
    streamEntry = entry
    streamBuffer += String(ev.text || '')
    scheduleFlush()
  }
}
window.addEventListener('chrono:avatar-push', handlePush)
onUnmounted(() => {
  window.removeEventListener('chrono:avatar-push', handlePush)
  if (props.conversationId) api.cancel_avatar_chat(props.conversationId).catch(() => {})
})

async function run(text: string) {
  if (loading.value || !props.conversationId || !text) return
  loading.value = true
  autoScroll.value = true
  const conversationId = props.conversationId
  const currentReqId = `av_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  reqId = currentReqId
  const entry: AvEntry = { id: Date.now(), text, reply: '', streaming: true, reqId: currentReqId }
  msgs.value.push(entry)
  scrollToBottom()
  try {
    await bridgeReady()
    // 多轮上下文：本条在途/失败/停止半截的轮次不算（后端截最近 8 轮）
    const history = msgs.value
      .filter(e => e.reqId !== currentReqId && e.reply && !e.error && !e.stopped && !e.truncated)
      .slice(-8)
      .flatMap(e => [
        { role: 'user', content: e.text },
        { role: 'assistant', content: e.reply },
      ])
    const res = await api.ask_avatar_chat(conversationId, text, history, currentReqId)
    if (conversationId !== props.conversationId) return // 已切人，丢弃过期回复
    if (res?.ok) {
      // 取消竞态：点停后完整回复恰已返回——完整回复优先于停止定格
      entry.reply = String(res.reply || entry.reply)
      entry.stopped = false
      entry.truncated = res.truncated === true
      if (res.voice?.sample_count) voiceCount.value = Number(res.voice.sample_count)
    } else if (!entry.stopped) {
      entry.error = String(res?.error || '分身回复失败，请重试')
    }
  } catch (e: any) {
    if (!entry.stopped) entry.error = String(e?.message || '分身对话异常')
  } finally {
    entry.streaming = false
    entry.reqId = ''
    if (reqId === currentReqId) {
      dropStreamBuffer()
      reqId = ''
      loading.value = false
    }
  }
}

function handleSend() {
  const text = input.value.trim()
  if (!text || loading.value || !props.conversationId) return
  input.value = ''
  nextTick(autoGrow)
  void run(text)
}

function handleRetry(item: AvEntry) {
  if (loading.value) return
  const idx = msgs.value.indexOf(item)
  if (idx >= 0) msgs.value.splice(idx, 1)
  void run(item.text)
}

function handleRegenerate() {
  if (loading.value || !msgs.value.length) return
  const last = msgs.value[msgs.value.length - 1]
  msgs.value.pop()
  void run(last.text)
}

// 停止：本地立即定格部分文本，再通知后端取消；迟到增量被
// streaming=false 天然丢弃
async function handleStop() {
  if (!loading.value || !props.conversationId) return
  const entry = msgs.value.find(item => item.streaming)
  if (entry) {
    if (streamEntry === entry) {
      entry.reply += streamBuffer
      dropStreamBuffer()
    }
    entry.streaming = false
    if (entry.reply) entry.stopped = true
    else {
      const idx = msgs.value.indexOf(entry)
      if (idx >= 0) msgs.value.splice(idx, 1)
    }
  }
  loading.value = false
  try {
    await bridgeReady()
    await api.cancel_avatar_chat(props.conversationId)
  } catch {
    // 取消失败不打断（后端请求会自行超时返回）
  }
}

function handleClear() {
  msgs.value = []
  dropStreamBuffer()
}

// 切人即清：分身对话按联系人隔离（与画像页选人联动）
watch(() => props.conversationId, () => {
  msgs.value = []
  voiceCount.value = 0
  dropStreamBuffer()
  loading.value = false
  reqId = ''
})
</script>

<style scoped>
/* 分身对话流：视觉与 QaChat 聊天框同构（暖白卡面+墨紫用户泡），
   TA 侧标记用画像页实体色琥珀（BIG5_COLOR_OTHER 口径），不用问答的
   绿色 AI 标——它扮演的是 TA 不是助手 */
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

.text-action-btn.copied {
  color: var(--ct-color-success);
  border-color: var(--ct-color-success);
}

.av-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding: var(--ct-space-lg);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  min-height: 0; /* 聊天流在 flex 列内收缩，出滚动条而不是撑破页 */
}

.av-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.av-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-md);
}

.av-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ct-text-primary);
}

.av-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

.av-chat {
  flex: 1;
  min-height: 280px;
  max-height: 56vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding-right: 4px;
}

.av-empty {
  margin: auto;
  padding: var(--ct-space-2xl);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ct-space-md);
  text-align: center;
}

.av-empty-text {
  margin: 0;
  font-size: 13px;
  color: var(--ct-text-tertiary);
}

.av-suggest-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  max-width: 460px;
}

.av-suggest-chip {
  padding: 5px 12px;
  font-size: 12px;
  color: var(--ct-text-secondary);
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.av-suggest-chip:hover {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-subtle);
}

.av-msg {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.av-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.av-row-user {
  justify-content: flex-end;
}

.av-bubble {
  max-width: 82%;
  padding: 10px 14px;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.av-bubble-user {
  background: var(--ct-color-primary-subtle);
  border-bottom-right-radius: 4px;
}

.av-bubble-avatar {
  background: var(--ct-bg-card);
  border-bottom-left-radius: 4px;
}

.av-bubble-text {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
  color: var(--ct-text-primary);
}

/* TA 侧头像标：琥珀实体色（与镜像双栏 TA 圆点同口径） */
.av-mark {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--ct-radius-full);
  font-size: 11px;
  font-weight: 600;
  background: rgba(224, 164, 88, 0.18);
  color: #B97F27;
}

.av-error {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  flex-wrap: wrap;
}

.av-error-text {
  font-size: 12px;
  color: var(--ct-color-error);
}

.av-typing {
  display: flex;
  align-items: center;
  gap: 8px;
}

.av-typing-dots {
  display: inline-flex;
  gap: 3px;
}

.av-typing-dots i {
  width: 5px;
  height: 5px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-text-tertiary);
  animation: av-dot-bounce 1.2s infinite ease-in-out;
}

.av-typing-dots i:nth-child(2) { animation-delay: 0.15s; }
.av-typing-dots i:nth-child(3) { animation-delay: 0.3s; }

@keyframes av-dot-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-3px); opacity: 1; }
}

.av-typing-hint {
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

.av-stream-cursor {
  width: 2px;
  height: 14px;
  background: var(--ct-color-primary);
  animation: av-blink 0.9s steps(2) infinite;
}

@keyframes av-blink {
  0% { opacity: 1; }
  50% { opacity: 0; }
  100% { opacity: 1; }
}

.av-state-badge {
  align-self: flex-start;
  font-size: 11px;
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-full);
  padding: 1px 8px;
}

.av-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 逐条边界标注：tint 底+琥珀字（状态徽标惯用语，不抢回复内容） */
.av-ai-tag {
  font-size: 10px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: var(--ct-radius-sm);
  background: var(--ct-color-warning-tint);
  color: #8A6117;
}

.av-input-row {
  display: flex;
  align-items: flex-end;
}

.av-input-box {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 6px 6px 6px 14px;
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

/* 输入焦点 = border primary + 3px primary-tint 光圈（全局惯用语） */
.av-input-box.focused {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 3px var(--ct-color-primary-tint);
}

.av-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ct-text-primary);
  font-family: inherit;
  max-height: 132px;
  padding: 4px 0;
}

.av-input::placeholder {
  color: var(--ct-text-tertiary);
}

.av-send-btn {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--ct-radius-full);
  background: var(--ct-color-primary);
  color: var(--ct-bg-card);
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.av-send-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.av-send-btn.stop {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-primary);
}

.av-send-icon {
  width: 14px;
  height: 14px;
}

/* 减弱动效：打字点/光标动画停用（全局惯用语） */
@media (prefers-reduced-motion: reduce) {
  .av-typing-dots i,
  .av-stream-cursor {
    animation: none;
  }
}
</style>
