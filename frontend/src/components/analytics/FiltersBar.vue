<template>
  <div class="filters-bar">
    <div class="left">
      <!-- 新增：联系人选择器 -->
      <div class="conversation-select">
        <label>选择联系人</label>
        <select 
          :value="selectedConversationId" 
          @change="onConversationChange"
          :disabled="loading"
        >
          <option :value="null" disabled>-- 请选择联系人 --</option>
          <option 
            v-for="conv in conversations" 
            :key="conv.id" 
            :value="conv.id"
          >
            {{ conv.name || conv.username || '未知联系人' }} ({{ conv.message_count }}条)
          </option>
        </select>
      </div>
    </div>
    <div class="center">
      <div class="dates">
        <input type="date" :value="dates.from" @change="onFrom($event)" />
        <span>—</span>
        <input type="date" :value="dates.to" @change="onTo($event)" />
      </div>
      <div class="quick">
        <button class="btn" @click="quick(7)" :disabled="loading">近7天</button>
        <button class="btn" @click="quick(30)" :disabled="loading">近30天</button>
        <button class="btn" @click="quick(180)" :disabled="loading">近半年</button>
        <button class="btn" @click="quick(365)" :disabled="loading">近一年</button>
        <button class="btn" @click="quickAll()" :disabled="loading">全部</button>
        <button class="btn" @click="$emit('refresh')" :disabled="loading">刷新</button>
      </div>
    </div>
    <div class="right">
      <button class="btn" :disabled="loading" @click="onExport">导出CSV</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type Conversation = {
  id: number
  name: string
  message_count: number
}

const props = defineProps<{ 
  conversations: Conversation[]
  selectedConversationId: number | null
  dates: { from: string; to: string }
  loading?: boolean 
}>()

const emit = defineEmits<{ 
  (e: 'update:dates', v: { from: string; to: string }): void
  (e: 'update:conversation-id', v: number): void
  (e: 'refresh'): void
  (e: 'export'): void 
}>()

function fmt(d: Date) { return d.toISOString().slice(0, 10) }
function quick(days: number) {
  const to = new Date()
  const from = new Date()
  from.setDate(to.getDate() - (days - 1))
  emit('update:dates', { from: fmt(from), to: fmt(to) })
}
function quickAll() {
  // 全部：从2000年1月1日到今天
  const to = new Date()
  const from = new Date(2000, 0, 1)
  emit('update:dates', { from: fmt(from), to: fmt(to) })
}
function onFrom(e: Event) { emit('update:dates', { from: (e.target as HTMLInputElement).value, to: props.dates.to }) }
function onTo(e: Event) { emit('update:dates', { from: props.dates.from, to: (e.target as HTMLInputElement).value }) }
function onExport() { emit('export') }
function onConversationChange(e: Event) {
  const value = (e.target as HTMLSelectElement).value
  emit('update:conversation-id', parseInt(value))
}
</script>

<style scoped>
.filters-bar {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  gap: var(--ct-space-md);
  align-items: center;
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: var(--ct-space-md) var(--ct-space-lg);
}
.conversation-select {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}
.conversation-select label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  font-weight: var(--ct-font-medium);
}
.conversation-select select {
  padding: var(--ct-space-sm) var(--ct-space-md);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-primary);
  color: var(--ct-text-primary);
  cursor: pointer;
  min-width: 200px;
  font-size: var(--ct-text-sm);
  transition: all var(--ct-transition-fast) var(--ct-ease-out);
}
.conversation-select select:focus {
  outline: none;
  border-color: var(--ct-border-color-focus);
  box-shadow: 0 0 0 3px var(--ct-color-primary-light);
}
.conversation-select select:disabled {
  background: var(--ct-bg-tertiary);
  cursor: not-allowed;
  color: var(--ct-text-tertiary);
}
.center { display: flex; align-items: center; gap: var(--ct-space-md); }
.dates { display: flex; align-items: center; gap: var(--ct-space-sm); }
.dates input {
  padding: var(--ct-space-xs) var(--ct-space-sm);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-sm);
  background: var(--ct-bg-primary);
  color: var(--ct-text-primary);
  transition: all var(--ct-transition-fast) var(--ct-ease-out);
}
.dates input:focus {
  outline: none;
  border-color: var(--ct-border-color-focus);
  box-shadow: 0 0 0 3px var(--ct-color-primary-light);
}
.quick { display: flex; gap: var(--ct-space-sm); }
.btn {
  padding: var(--ct-space-xs) var(--ct-space-sm);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-secondary);
  color: var(--ct-text-primary);
  cursor: pointer;
  font-size: var(--ct-text-xs);
  transition: all var(--ct-transition-fast) var(--ct-ease-out);
}
.btn:hover:not(:disabled) {
  background: var(--ct-bg-tertiary);
  border-color: var(--ct-border-color-hover);
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.right { display: flex; justify-content: flex-end; }
</style>
