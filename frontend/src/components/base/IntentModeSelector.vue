<template>
  <div class="ims-wrap">
    <div class="ims-row">
      <span class="ims-label">触发模式</span>
      <div class="ims-seg">
        <button v-for="m in triggerModes" :key="m.value"
          :class="['ims-btn', { active: triggerMode === m.value }]"
          @click="setTrigger(m.value)" :title="m.tip">{{ m.label }}</button>
      </div>
    </div>
    <div class="ims-row">
      <span class="ims-label">关系走向</span>
      <div class="ims-seg">
        <button v-for="i in intents" :key="i.value"
          :class="['ims-btn', { active: intent === i.value }]"
          @click="setIntent(i.value)" :title="i.tip">{{ i.label }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { bridgeReady, api } from '@/api/bridge'

const props = defineProps<{
  triggerMode: string
  intent: string
}>()

const emit = defineEmits<{
  (e: 'update:triggerMode', value: string): void
  (e: 'update:intent', value: string): void
}>()

const triggerModes = [
  { value: 'full_auto', label: '全自动', tip: '每条对方消息都尝试生成建议' },
  { value: 'semi_auto', label: '半自动', tip: '检测到触发条件时生成建议' },
  { value: 'manual', label: '手动', tip: '仅手动点击生成时才产生建议' },
]
const intents = [
  { value: 'intimate', label: '亲近', tip: '生成更有感情、亲密回复' },
  { value: 'maintain', label: '维持', tip: '维持当前氛围' },
  { value: 'distance', label: '疏远', tip: '生成稍带距离感回复' },
]

async function setTrigger(value: string) {
  emit('update:triggerMode', value)
  try { await bridgeReady(); await api.set_suggestion_config({ trigger_mode: value }) } catch { /* 静默 */ }
}

async function setIntent(value: string) {
  emit('update:intent', value)
  try { await bridgeReady(); await api.set_suggestion_config({ intent: value }) } catch { /* 静默 */ }
  // 走向切换可能触发新一轮建议生成
  setTimeout(() => emit('update:intent', value), 0)
}
</script>

<style scoped>
.ims-wrap { display: flex; flex-direction: column; gap: 8px; }
.ims-row { display: flex; align-items: center; gap: 8px; }
.ims-label { font-size: 11px; font-weight: 600; color: var(--ct-text-secondary); white-space: nowrap; min-width: 52px; }
.ims-seg { display: flex; gap: 4px; flex: 1; }
.ims-btn {
  flex: 1; padding: 5px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;
  background: var(--ct-bg-secondary); border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary); cursor: pointer; transition: all 0.15s;
  display: inline-flex; align-items: center; justify-content: center; gap: 3px;
}
.ims-btn:hover { background: var(--ct-bg-tertiary); }
.ims-btn.active { color: var(--ct-color-primary); border-color: rgba(124,77,255,0.3); background: rgba(124,77,255,0.08); }
</style>
