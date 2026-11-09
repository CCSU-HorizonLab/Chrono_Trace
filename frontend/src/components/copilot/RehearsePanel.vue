<template>
  <div class="rehearse-shell">
    <div class="rehearse-header">
      <h3 class="rehearse-title">回复陪练</h3>
      <p class="rehearse-subtitle">贴上 {{ contactName }} 发来的消息，结合你们的聊天习惯，给出三个温度档的回复方向</p>
    </div>

    <!-- 输入：贴消息 + 演练（结果按联系人/消息各自独立，不攒会话状态） -->
    <div class="rehearse-input-box" :class="{ focused: inputFocused }">
      <textarea
        v-model="receivedText"
        class="rehearse-input"
        rows="2"
        placeholder="例如：TA 刚发来「随便，都行」，不知道怎么接…"
        maxlength="500"
        @focus="inputFocused = true"
        @blur="inputFocused = false"
        @keydown.enter.exact.prevent="handleRehearse"
      ></textarea>
      <div class="rehearse-input-foot">
        <span class="rehearse-count">{{ receivedText.length }}/500</span>
        <button
          class="ct-btn primary rehearse-btn"
          :disabled="loading || !receivedText.trim()"
          @click="loading ? handleCancel() : handleRehearse()"
        >{{ loading ? '停止' : '给我三个方向' }}</button>
      </div>
    </div>

    <!-- 结果：三档温度卡 -->
    <div v-if="loading && !options.length" class="rehearse-loading">
      <span class="rehearse-loading-dots"><i></i><i></i><i></i></span>
      <span>正在翻你们的聊天记录，想想怎么回…</span>
    </div>
    <div v-else-if="error" class="rehearse-error">
      <span>{{ error }}</span>
      <button class="text-action-btn" @click="handleRehearse">重试</button>
    </div>
    <div v-else-if="!options.length" class="rehearse-empty">
      把拿不准的消息贴在上面，这里会出现三个回复方向：稳一稳、进一步、缓一缓。
    </div>
    <div v-else class="rehearse-cards">
      <article v-for="opt in options" :key="opt.tone" class="rehearse-card" :data-tone="opt.tone">
        <header class="rehearse-card-hd">
          <span class="rehearse-tone-chip">{{ opt.label }}</span>
          <span class="rehearse-direction">{{ opt.direction }}</span>
        </header>
        <div class="rehearse-draft-box">
          <p class="rehearse-draft">{{ opt.draft }}</p>
        </div>
        <p class="rehearse-consequence"><span class="rehearse-consequence-tag">可能走向</span>{{ opt.consequence }}</p>
      </article>
      <p class="rehearse-note">草稿只作参考——发之前按你自己的语气改一改，别让 TA 认不出你。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 回复陪练（智囊页·陪练模式，重设计 §4.4）：贴一段收到的消息 →
 * 后端 rehearse_reply 结合近期对话/相关历史/长期记忆产出三温度档
 * （稳一稳/进一步/缓一缓）回复方向 + 后果预判。单次交互无会话状态，
 * 切联系人即清空。
 */
import { ref, watch } from 'vue'
import { api } from '@/api/bridge'

const props = defineProps<{
  conversationId: number
  contactName: string
}>()

type RehearseOption = {
  tone: 'steady' | 'closer' | 'cooler'
  label: string
  direction: string
  draft: string
  consequence: string
}

const receivedText = ref('')
const inputFocused = ref(false)
const loading = ref(false)
const error = ref('')
const options = ref<RehearseOption[]>([])

async function handleRehearse() {
  const text = receivedText.value.trim()
  if (!text || loading.value || !props.conversationId) return
  loading.value = true
  error.value = ''
  options.value = []
  try {
    const res = await api.rehearse_reply(props.conversationId, text)
    if (res?.ok) {
      options.value = Array.isArray(res.options) ? res.options : []
      if (!options.value.length) error.value = '模型没有给出可用的回复方向，换个说法再试。'
    } else {
      error.value = String(res?.error || '陪练失败，请重试')
    }
  } catch (e: any) {
    error.value = String(e?.message || '陪练异常')
  } finally {
    loading.value = false
  }
}

// 停止：后端取消同问答 scope（下一次轮询点生效，在途结果作废）
async function handleCancel() {
  if (!loading.value) return
  loading.value = false
  error.value = ''
  try {
    await api.cancel_history_qa(props.conversationId)
  } catch {
    // 取消失败不打断（后端请求会自行超时返回）
  }
}

// 切联系人清空（单次交互语义：上一联系人的方向对新人无意义）
watch(() => props.conversationId, () => {
  if (loading.value) void handleCancel()
  receivedText.value = ''
  options.value = []
  error.value = ''
})
</script>

<style scoped>
.rehearse-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding: var(--ct-space-lg);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  min-height: 0;
  overflow-y: auto;
}

.rehearse-header { display: flex; flex-direction: column; gap: 4px; }
.rehearse-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--ct-text-primary); }
.rehearse-subtitle { margin: 0; font-size: 12px; color: var(--ct-text-tertiary); }

/* 输入：与问答输入同惯用语（border primary + tint 光圈） */
.rehearse-input-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  padding: 12px 14px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.rehearse-input-box.focused {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 3px var(--ct-color-primary-tint);
}

.rehearse-input {
  border: none;
  outline: none;
  resize: vertical;
  min-height: 56px;
  background: transparent;
  color: var(--ct-text-primary);
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
}

.rehearse-input::placeholder { color: var(--ct-text-tertiary); }

.rehearse-input-foot { display: flex; align-items: center; justify-content: space-between; }
.rehearse-count { font-size: 11px; color: var(--ct-text-tertiary); font-variant-numeric: tabular-nums; }
.rehearse-btn { padding: 6px 16px; font-size: 13px; }

/* 状态行 */
.rehearse-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--ct-text-secondary);
  padding: 12px 4px;
}

.rehearse-loading-dots { display: inline-flex; gap: 3px; flex-shrink: 0; }

.rehearse-loading-dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ct-text-tertiary);
  animation: rehearse-blink 1.2s infinite ease-in-out;
}

.rehearse-loading-dots i:nth-child(2) { animation-delay: 0.2s; }
.rehearse-loading-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes rehearse-blink {
  0%, 60%, 100% { opacity: 0.25; }
  30% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .rehearse-loading-dots i { animation: none; opacity: 0.6; }
}

.rehearse-error {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--ct-color-error-tint);
  color: var(--ct-color-error);
  border-radius: var(--ct-radius-sm);
  padding: 8px 12px;
  font-size: 12px;
}

.rehearse-empty {
  margin: auto;
  text-align: center;
  font-size: 13px;
  color: var(--ct-text-tertiary);
  max-width: 400px;
  padding: 24px 0;
}

/* 三档卡 */
.rehearse-cards { display: flex; flex-direction: column; gap: 12px; }

.rehearse-card {
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rehearse-card-hd { display: flex; align-items: center; gap: 10px; }

/* 温度徽标：tint 底 + 语义字（状态徽标惯用语）；三档用 primary 三档浓度区分 */
.rehearse-tone-chip {
  flex: none;
  font-size: 12px;
  font-weight: 600;
  border-radius: var(--ct-radius-full);
  padding: 2px 10px;
}

.rehearse-card[data-tone='steady'] .rehearse-tone-chip {
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
}

.rehearse-card[data-tone='closer'] .rehearse-tone-chip {
  background: var(--ct-color-primary);
  color: var(--ct-bg-card);
}

.rehearse-card[data-tone='cooler'] .rehearse-tone-chip {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
}

.rehearse-direction { font-size: 12px; color: var(--ct-text-secondary); }

.rehearse-draft-box {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
  padding: 10px 12px;
}

.rehearse-draft {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--ct-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}


.rehearse-consequence {
  margin: 0;
  font-size: 12px;
  color: var(--ct-text-tertiary);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.rehearse-consequence-tag {
  flex: none;
  font-size: 10px;
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-sm);
  padding: 1px 6px;
}

.rehearse-note { margin: 4px 0 0; font-size: 12px; color: var(--ct-text-tertiary); text-align: center; }

/* 通用小文本操作按钮（同 QaChat，自 Analytics 迁入） */
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
</style>
