<template>
  <Teleport to="body">
    <div v-if="visible" class="ct-modal-overlay" @click.self="!generating && $emit('close')">
      <div class="portrait-dialog">
        <div class="pd-header">
          <div class="pd-icon-wrap">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2a5 5 0 015 5c0 3.5-5 7-5 7s-5-3.5-5-7a5 5 0 015-5z"/>
              <circle cx="12" cy="7" r="1.5"/>
              <path d="M5 21c0-4 3-6 7-6s7 2 7 6"/>
            </svg>
          </div>
          <div class="pd-title-area">
            <h3 class="pd-title">{{ generating ? '正在生成画像' : '生成画像' }}</h3>
            <p class="pd-subtitle">{{ generating ? 'LLM 分析历史聊天中，可随时关闭终止；完成后自动更新（期间请勿开始监听）' : `围绕「${displayName}」历史聊天，按需生成画像` }}</p>
          </div>
          <button class="pd-close" @click="handleClose" aria-label="关闭">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>

        <div class="pd-panels">
          <div class="pd-card" :class="{ 'is-off': !generateContact }">
            <label class="pd-card-toggle">
              <span class="pd-toggle-track" :class="{ on: generateContact }">
                <input v-model="generateContact" type="checkbox" class="sr-only" />
                <span class="pd-toggle-thumb"></span>
              </span>
              <span class="pd-card-label">联系人画像</span>
            </label>
            <p class="pd-card-hint">分析对方聊天风格，生成性格与沟通特征</p>
            <div class="pd-options" :class="{ disabled: !generateContact }">
              <span class="pd-options-label">回看跨度</span>
              <div class="pd-chips">
                <label v-for="opt in contactBudgetOptions" :key="opt.value" class="pd-chip" :class="{ active: contactBudget === opt.value }">
                  <input type="radio" :value="opt.value" v-model="contactBudget" :disabled="!generateContact" class="sr-only" />
                  <span class="pd-chip-text">{{ opt.label }}</span>
                  <span v-if="opt.tip" class="pd-chip-tip">{{ opt.tip }}</span>
                </label>
              </div>
              <div class="pd-est">按时间分桶采样，不做 token 截断；内容不足时自动向更早聊天顺延。</div>
            </div>
          </div>

          <div v-if="showSelfPanel" class="pd-card" :class="{ 'is-off': !generateSelf }">
            <label class="pd-card-toggle">
              <span class="pd-toggle-track" :class="{ on: generateSelf }">
                <input v-model="generateSelf" type="checkbox" class="sr-only" />
                <span class="pd-toggle-thumb"></span>
              </span>
              <span class="pd-card-label">我的画像</span>
            </label>
            <p class="pd-card-hint">提取你在和 TA 聊天中的说话风格，让 AI 建议像你本人</p>
            <div class="pd-options" :class="{ disabled: !generateSelf }">
              <span class="pd-options-label">扫描深度</span>
              <div class="pd-chips">
                <label v-for="opt in selfBudgetOptions" :key="opt.value" class="pd-chip" :class="{ active: selfBudget === opt.value }">
                  <input type="radio" :value="opt.value" v-model="selfBudget" :disabled="!generateSelf" class="sr-only" />
                  <span class="pd-chip-text">{{ opt.label }}</span>
                  <span v-if="opt.tip" class="pd-chip-tip">{{ opt.tip }}</span>
                </label>
              </div>
              <div class="pd-est">按时间分桶采样，不做 token 截断；内容不足时自动向更早聊天顺延。</div>
            </div>
          </div>
        </div>

        <div class="pd-window">
          <span class="pd-window-label">自定义时间窗</span>
          <div class="pd-window-inputs">
            <input v-model="customFrom" type="date" :disabled="generating" />
            <span class="pd-window-sep">至</span>
            <input v-model="customTo" type="date" :disabled="generating" />
            <button v-if="customFrom || customTo" class="pd-window-clear" @click="customFrom = ''; customTo = ''">清除</button>
          </div>
          <p class="pd-window-note">留空按上方档位回看最近聊天；填写起止日期则只分析该区间，存为可回看的历史快照</p>
        </div>

        <div class="pd-footer">
          <p v-if="genError" class="pd-error">{{ genError }}</p>
          <button
            class="pd-btn"
            :class="generating ? 'pd-btn-stop' : 'pd-btn-ghost'"
            @click="handleClose"
            :title="generating ? '关闭弹窗并终止本次画像生成' : undefined"
          >
            {{ generating ? '终止并关闭' : '取消' }}
          </button>
          <button
            class="pd-btn pd-btn-primary"
            @click="handleGenerate"
            :disabled="generating || (!generateContact && (!showSelfPanel || !generateSelf))"
          >
            <svg
              width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
              :class="{ spin: generating }"
            ><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            {{ generating ? '生成中…' : '确认生成' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import { safeGetItem, safeSetItem } from '@/utils/safeStorage'

const props = withDefaults(defineProps<{
  visible: boolean
  displayName: string
  accountWxid?: string
  showSelfPanel?: boolean
  /** 初始时是否预选联系人画像 */
  defaultContact?: boolean
  /** 初始时是否预选我的画像（建议质量依赖自我画像注入，默认勾选） */
  defaultSelf?: boolean
  /** 取消键（conversation_id）：生成中关闭弹窗时终止后端画像生成 */
  cancelKey?: number
}>(), {
  showSelfPanel: true,
  defaultContact: true,
  defaultSelf: true,
  cancelKey: 0,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'generated', kind: 'contact' | 'self' | 'both'): void
}>()

const generateContact = ref(props.defaultContact)
const generateSelf = ref(props.defaultSelf)
// 记忆的回看档位（storage 不可用时降级默认档）
const contactBudget = ref(safeGetItem('chrono:portraitContactBudget') || 'medium')
const selfBudget = ref('medium')
const generating = ref(false)
const genError = ref('')
const cancelRequested = ref(false)
// 可选自定义时间窗（YYYY-MM-DD）；留空为档位滚动窗模式
const customFrom = ref('')
const customTo = ref('')

/** 解析自定义窗：返回 {fromTs, toTs}（闭区间秒级）；空返回 null；非法返回错误串 */
function resolveCustomWindow(): { fromTs: number; toTs: number } | string | null {
  if (!customFrom.value && !customTo.value) return null
  if (!customFrom.value || !customTo.value) return '自定义时间窗需同时填写起止日期'
  const fromTs = Math.floor(new Date(customFrom.value + 'T00:00:00').getTime() / 1000)
  const toTs = Math.floor(new Date(customTo.value + 'T23:59:59').getTime() / 1000)
  if (!fromTs || !toTs || fromTs >= toTs) return '自定义时间窗无效：起点需早于终点'
  return { fromTs, toTs }
}

const contactBudgetOptions = [
  { value: 'low', label: '最近 7 天', tip: '简略' },
  { value: 'medium', label: '最近 30 天', tip: '普通' },
  { value: 'high', label: '最近 90 天', tip: '精细' },
]
const selfBudgetOptions = [
  { value: 'medium', label: '最近 30 天', tip: '普通' },
  { value: 'high', label: '最近 90 天', tip: '精细' },
]

/** 关闭弹窗：生成中先终止后端画像生成（在途调用随后以 cancelled 返回，
 *  静默收尾不再弹错误），弹窗立即关闭不等 HTTP */
async function handleClose() {
  if (!generating.value) {
    emit('close')
    return
  }
  cancelRequested.value = true
  try {
    await bridgeReady()
    if (props.cancelKey) {
      await api.cancel_profile_generation(props.cancelKey)
    }
  } catch {
    // 取消请求失败不阻断关闭：在途生成最多跑完当前尝试
  }
  emit('close')
}

async function handleGenerate() {
  if (generating.value) return
  const customWindow = resolveCustomWindow()
  if (typeof customWindow === 'string') {
    genError.value = customWindow
    return
  }
  generating.value = true
  genError.value = ''
  cancelRequested.value = false
  let hasError = false
  let errorMsg = ''
  let generatedKind: 'contact' | 'self' | 'both' = 'contact'

  try {
    await bridgeReady()

    if (generateContact.value) {
      // 记住档位：Analytics 快捷「更新画像」与弹窗下次默认保持一致
      safeSetItem('chrono:portraitContactBudget', contactBudget.value)
      const res = await api.generate_contact_profile(
        props.displayName, contactBudget.value, undefined, props.accountWxid || undefined,
        props.cancelKey || undefined,
        customWindow?.fromTs, customWindow?.toTs
      )
      if (cancelRequested.value || res?.cancelled) {
        return
      }
      if (!res || !res.ok) {
        hasError = true
        errorMsg = res?.error || '联系人画像生成失败'
      }
    }

    if (cancelRequested.value) return

    if (props.showSelfPanel && generateSelf.value && !hasError) {
      const res = await api.generate_self_profile(
        props.displayName, selfBudget.value, undefined, props.accountWxid || undefined,
        props.cancelKey || undefined,
        customWindow?.fromTs, customWindow?.toTs
      )
      if (cancelRequested.value || res?.cancelled) {
        return
      }
      if (!res || !res.ok) {
        hasError = true
        errorMsg = res?.error || '我的画像生成失败'
      }
      if (generateContact.value) generatedKind = 'both'
      else generatedKind = 'self'
    }
  } catch (e: any) {
    if (cancelRequested.value) return
    hasError = true
    errorMsg = e?.message || '生成异常'
  } finally {
    generating.value = false
  }

  if (hasError) {
    // 失败留在弹窗内联展示：秒关弹窗会让用户以为没触发（此前正是此问题）
    genError.value = errorMsg
  } else if (cancelRequested.value) {
    emit('close')
  } else {
    emit('close')
    emit('generated', generatedKind)
  }
}
</script>

<style scoped>
/* 遮罩吃全局 .ct-modal-overlay（panels.css），此处只管弹窗本体 */
.portrait-dialog {
  width: 520px; max-width: 92vw;
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.pd-header {
  display: flex; align-items: center; gap: 12px;
  padding: 18px 20px; border-bottom: 1px solid var(--ct-border-color);
}
.pd-icon-wrap {
  width: 40px; height: 40px; border-radius: var(--ct-radius-md);
  background: var(--ct-color-primary-tint); color: var(--ct-color-primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.pd-title { margin: 0; font-size: var(--ct-text-base); font-weight: var(--ct-font-bold); }
.pd-subtitle { margin: 2px 0 0; font-size: var(--ct-text-xs); color: var(--ct-text-secondary); }
.pd-close {
  margin-left: auto; background: none; border: none; cursor: pointer;
  color: var(--ct-text-tertiary); padding: 6px; border-radius: var(--ct-radius-sm);
  transition: background-color var(--ct-transition-fast) var(--ct-ease-out),
              color var(--ct-transition-fast) var(--ct-ease-out);
}
.pd-close:hover { background: var(--ct-bg-hover); color: var(--ct-text-primary); }
.pd-panels { display: flex; gap: 12px; padding: 16px 20px; }
.pd-card {
  flex: 1; border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
  padding: 14px; transition: opacity 0.15s;
}
.pd-card.is-off { opacity: 0.45; }
.pd-card-toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; margin-bottom: 6px; }
.pd-toggle-track {
  width: 34px; height: 20px; border-radius: var(--ct-radius-full);
  background: var(--ct-bg-sunken); position: relative;
  transition: background 0.15s;
}
.pd-toggle-track.on { background: var(--ct-color-primary); }
.pd-toggle-thumb {
  position: absolute; top: 2px; left: 2px; width: 16px; height: 16px;
  border-radius: 50%; background: #fff; transition: left 0.15s;
}
.pd-toggle-track.on .pd-toggle-thumb { left: 16px; }
.pd-card-label { font-size: var(--ct-text-sm); font-weight: var(--ct-font-semibold); }
.pd-card-hint { margin: 0 0 10px; font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.pd-options.disabled { opacity: 0.5; pointer-events: none; }
.pd-options-label { font-size: var(--ct-text-xs); font-weight: var(--ct-font-semibold); color: var(--ct-text-secondary); display: block; margin-bottom: 6px; }
.pd-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.pd-chip {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 6px 12px;
  border-radius: var(--ct-radius-sm); background: var(--ct-bg-sunken);
  transition: background-color 0.15s;
}
.pd-chip.active { background: var(--ct-color-primary-tint); }
.pd-chip-text { font-size: var(--ct-text-xs); font-weight: var(--ct-font-semibold); }
.pd-chip-tip { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.pd-est { margin-top: 8px; font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); line-height: 1.5; }
/* 自定义时间窗（可选）：留空走档位滚动窗，填写则按区间生成 custom 快照 */
.pd-window {
  padding: 0 20px 14px;
}
.pd-window-label { font-size: var(--ct-text-xs); font-weight: var(--ct-font-semibold); color: var(--ct-text-secondary); display: block; margin-bottom: 6px; }
.pd-window-inputs { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pd-window-inputs input[type="date"] {
  padding: 5px 10px; border-radius: var(--ct-radius-sm); font-size: var(--ct-text-xs);
  border: 1px solid var(--ct-border-color); background: var(--ct-bg-sunken);
  color: var(--ct-text-primary);
}
.pd-window-sep { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.pd-window-clear {
  background: none; border: none; cursor: pointer; padding: 2px 6px;
  font-size: var(--ct-text-xs); color: var(--ct-text-secondary); border-radius: var(--ct-radius-sm);
}
.pd-window-clear:hover { color: var(--ct-color-error); }
.pd-window-note { margin: 6px 0 0; font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); line-height: 1.5; }
.pd-footer {
  display: flex; justify-content: flex-end; gap: 10px; align-items: center;
  padding: 14px 20px; border-top: 1px solid var(--ct-border-color);
}
/* 生成失败内联提示：弹窗保持打开，避免「秒关无反馈」体感 */
.pd-error {
  flex: 1; margin: 0; text-align: left;
  font-size: var(--ct-text-xs); color: var(--ct-color-error);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* 生成中图标旋转 */
.spin {
  animation: pd-rotate 1s linear infinite;
}
@keyframes pd-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.pd-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 20px; border-radius: var(--ct-radius-md); font-size: var(--ct-text-sm); font-weight: var(--ct-font-semibold);
  cursor: pointer; border: 1px solid transparent;
}
.pd-btn-ghost { background: transparent; color: var(--ct-text-secondary); border-color: var(--ct-border-color); }
.pd-btn-ghost:hover { background: var(--ct-bg-hover); }
/* 生成中的关闭按钮 = 终止操作：用危险色提示后果 */
.pd-btn-stop { background: transparent; color: var(--ct-color-error); border-color: var(--ct-color-error-tint); }
.pd-btn-stop:hover { background: var(--ct-color-error-tint); }
.pd-btn-primary { background: var(--ct-color-primary); color: var(--ct-text-inverse); }
.pd-btn-primary:hover { background: var(--ct-color-primary-hover); }
.pd-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
.sr-only { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
</style>
