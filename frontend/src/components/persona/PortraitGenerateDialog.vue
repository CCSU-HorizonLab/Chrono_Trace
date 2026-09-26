<template>
  <Teleport to="body">
    <div v-if="visible" class="ct-modal-overlay" @click.self="$emit('close')">
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
            <h3 class="pd-title">生成画像</h3>
            <p class="pd-subtitle">围绕「<strong>{{ displayName }}</strong>」历史聊天，按需生成画像</p>
          </div>
          <button class="pd-close" @click="$emit('close')" aria-label="关闭">
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
              <span class="pd-card-label">自我克隆</span>
            </label>
            <p class="pd-card-hint">提取你的打字风格与常用表达</p>
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

        <div class="pd-footer">
          <button class="pd-btn pd-btn-ghost" @click="$emit('close')">取消</button>
          <button class="pd-btn pd-btn-primary" @click="handleGenerate" :disabled="!generateContact && (!showSelfPanel || !generateSelf)">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            确认生成
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'

const props = withDefaults(defineProps<{
  visible: boolean
  displayName: string
  accountWxid?: string
  showSelfPanel?: boolean
  /** 初始时是否预选联系人画像 */
  defaultContact?: boolean
  /** 初始时是否预选自我克隆 */
  defaultSelf?: boolean
}>(), {
  showSelfPanel: true,
  defaultContact: true,
  defaultSelf: false,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'generated', kind: 'contact' | 'self' | 'both'): void
  (e: 'error', message: string): void
}>()

const generateContact = ref(props.defaultContact)
const generateSelf = ref(props.defaultSelf)
const contactBudget = ref('medium')
const selfBudget = ref('medium')

const contactBudgetOptions = [
  { value: 'low', label: '最近 7 天', tip: '简略' },
  { value: 'medium', label: '最近 30 天', tip: '普通' },
  { value: 'high', label: '最近 90 天', tip: '精细' },
]
const selfBudgetOptions = [
  { value: 'medium', label: '最近 30 天', tip: '普通' },
  { value: 'high', label: '最近 90 天', tip: '精细' },
]

async function handleGenerate() {
  emit('close')
  let hasError = false
  let errorMsg = ''
  let generatedKind: 'contact' | 'self' | 'both' = 'contact'

  try {
    await bridgeReady()

    if (generateContact.value) {
      const res = await api.generate_contact_profile(
        props.displayName, contactBudget.value, undefined, props.accountWxid || undefined
      )
      if (res && res.success === false) {
        hasError = true
        errorMsg = res.error || '联系人画像生成失败'
      }
    }

    if (props.showSelfPanel && generateSelf.value && !hasError) {
      const res = await api.generate_self_profile(
        props.displayName, selfBudget.value, undefined, props.accountWxid || undefined
      )
      if (res && res.success === false) {
        hasError = true
        errorMsg = res.error || '自我克隆画像提取失败'
      }
      if (generateContact.value) generatedKind = 'both'
      else generatedKind = 'self'
    }
  } catch (e: any) {
    hasError = true
    errorMsg = e?.message || '生成异常'
  }

  if (hasError) {
    emit('error', errorMsg)
  } else {
    emit('generated', generatedKind)
  }
}
</script>

<style scoped>
.ct-modal-overlay {
  position: fixed; inset: 0; z-index: 3000;
  background: rgba(10, 12, 18, 0.6);
  display: flex; align-items: center; justify-content: center;
}
.portrait-dialog {
  width: 520px; max-width: 92vw;
  background: var(--ct-bg-elevated, #1d222c);
  border-radius: 16px; border: 1px solid var(--ct-border-color);
  box-shadow: 0 24px 64px rgba(0,0,0,0.45);
  overflow: hidden;
}
.pd-header {
  display: flex; align-items: center; gap: 12px;
  padding: 18px 20px; border-bottom: 1px solid var(--ct-border-color);
}
.pd-icon-wrap {
  width: 40px; height: 40px; border-radius: 12px;
  background: rgba(108,92,231,0.14); color: #8b7ff0;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.pd-title { margin: 0; font-size: 17px; font-weight: 600; }
.pd-subtitle { margin: 2px 0 0; font-size: 12px; color: var(--ct-text-secondary); }
.pd-close {
  margin-left: auto; background: none; border: none; cursor: pointer;
  color: var(--ct-text-secondary); padding: 6px; border-radius: 8px;
}
.pd-close:hover { background: var(--ct-bg-tertiary); color: var(--ct-text-primary); }
.pd-panels { display: flex; gap: 12px; padding: 16px 20px; }
.pd-card {
  flex: 1; border: 1px solid var(--ct-border-color); border-radius: 12px;
  padding: 14px; transition: opacity 0.15s, border-color 0.15s;
}
.pd-card.is-off { opacity: 0.45; }
.pd-card-toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; margin-bottom: 6px; }
.pd-toggle-track {
  width: 34px; height: 20px; border-radius: 999px;
  background: var(--ct-bg-tertiary); position: relative;
  transition: background 0.15s;
}
.pd-toggle-track.on { background: #6c5ce7; }
.pd-toggle-thumb {
  position: absolute; top: 2px; left: 2px; width: 16px; height: 16px;
  border-radius: 50%; background: #fff; transition: left 0.15s;
}
.pd-toggle-track.on .pd-toggle-thumb { left: 16px; }
.pd-card-label { font-size: 13px; font-weight: 600; }
.pd-card-hint { margin: 0 0 10px; font-size: 11px; color: var(--ct-text-tertiary); }
.pd-options.disabled { opacity: 0.5; pointer-events: none; }
.pd-options-label { font-size: 11px; font-weight: 600; color: var(--ct-text-secondary); display: block; margin-bottom: 6px; }
.pd-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.pd-chip {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 6px 12px; border-radius: 10px; cursor: pointer;
  border: 1px solid var(--ct-border-color); background: var(--ct-bg-secondary);
  transition: all 0.15s;
}
.pd-chip.active { border-color: rgba(108,92,231,0.4); background: rgba(108,92,231,0.08); }
.pd-chip-text { font-size: 12px; font-weight: 600; }
.pd-chip-tip { font-size: 10px; color: var(--ct-text-tertiary); }
.pd-est { margin-top: 8px; font-size: 10px; color: var(--ct-text-tertiary); line-height: 1.5; }
.pd-footer {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 20px; border-top: 1px solid var(--ct-border-color);
}
.pd-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 20px; border-radius: 10px; font-size: 13px; font-weight: 600;
  cursor: pointer; border: 1px solid transparent;
}
.pd-btn-ghost { background: transparent; color: var(--ct-text-secondary); border-color: var(--ct-border-color); }
.pd-btn-ghost:hover { background: var(--ct-bg-tertiary); }
.pd-btn-primary { background: #6c5ce7; color: #fff; }
.pd-btn-primary:hover { background: #5a4bd1; }
.pd-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
.sr-only { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
</style>
