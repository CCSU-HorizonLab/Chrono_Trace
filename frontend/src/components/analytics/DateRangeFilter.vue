<template>
  <div class="date-range-filter">
    <div class="dates">
      <input type="date" :value="dates.from" @change="onFrom($event)" :disabled="loading" />
      <span class="separator">—</span>
      <input type="date" :value="dates.to" @change="onTo($event)" :disabled="loading" />
    </div>
    <div class="quick-links">
      <button class="btn" @click="quick(7)" :disabled="loading">近7天</button>
      <button class="btn" @click="quick(30)" :disabled="loading">近30天</button>
      <button class="btn" @click="quick(180)" :disabled="loading">近半年</button>
      <button class="btn" @click="quick(365)" :disabled="loading">近一年</button>
      <button class="btn" @click="quickAll()" :disabled="loading">全部</button>
      <button class="btn" @click="$emit('refresh')" :disabled="loading">刷新</button>
      <button class="btn btn-export" :disabled="loading" @click="$emit('export')">导出CSV</button>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ 
  dates: { from: string; to: string }
  loading?: boolean 
}>()

const emit = defineEmits<{ 
  (e: 'update:dates', v: { from: string; to: string }): void
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
  const to = new Date()
  const from = new Date(2000, 0, 1)
  emit('update:dates', { from: fmt(from), to: fmt(to) })
}
function onFrom(e: Event) { emit('update:dates', { from: (e.target as HTMLInputElement).value, to: props.dates.to }) }
function onTo(e: Event) { emit('update:dates', { from: props.dates.from, to: (e.target as HTMLInputElement).value }) }
</script>

<style scoped>
.date-range-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ct-space-md);
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-md);
  padding: 12px var(--ct-space-lg);
  margin-bottom: var(--ct-space-lg);
  border: 1px solid var(--ct-border-color);
  box-shadow: 0 1px 3px rgba(0,0,0,0.05); /* Same as header card */
}

.dates {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  flex-shrink: 0;
}

.dates input[type="date"] {
  padding: 6px 10px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-sm);
  background: var(--ct-bg-input);
  color: var(--ct-text-primary);
  font-size: 0.9rem;
}

.separator {
  color: var(--ct-text-secondary);
  margin: 0 4px;
}

.quick-links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-xs);
  align-items: center;
  flex: 1 1 auto; /* Take remaining space or full width when wrapped */
  min-width: 320px; /* Ensure it wraps completely dropping to a new line when squeezed */
}

.btn {
  padding: 6px 12px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-surface);
  color: var(--ct-text-secondary);
  border-radius: 20px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.btn:hover:not(:disabled) {
  background: var(--ct-primary-light);
  color: var(--ct-primary-color);
  border-color: var(--ct-primary-color);
}

.btn-export {
  /* 移除强制靠右，让它自适应折叠跟随其它按钮 */
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 800px) {
  .btn-export {
    margin-left: 0;
  }
}
</style>
