<template>
  <div class="filters-bar">
    <div class="left">
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
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type Conversation = {
  id: number
  name: string
  username?: string
  message_count: number
}

const props = defineProps<{ 
  conversations: Conversation[]
  selectedConversationId: number | null
  loading?: boolean 
}>()

const emit = defineEmits<{ 
  (e: 'update:conversation-id', v: number): void
}>()

function onConversationChange(e: Event) {
  const value = (e.target as HTMLSelectElement).value
  emit('update:conversation-id', parseInt(value))
}
</script>

<style scoped>
.filters-bar {
  display: flex;
  align-items: center;
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: var(--ct-space-sm) var(--ct-space-md);
}

.left {
  display: flex;
  align-items: center;
}

.conversation-select {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
}

.conversation-select label {
  font-weight: 500;
  color: var(--ct-text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.conversation-select select {
  padding: 8px 32px 8px 12px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-input) url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20width%3D%2220%22%20height%3D%2220%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cpath%20d%3D%22M5%208l5%205%205-5%22%20stroke%3D%22%23666%22%20fill%3D%22none%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E') no-repeat right 8px center;
  appearance: none;
  font-size: 1rem;
  color: var(--ct-text-primary);
  min-width: 200px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.2s ease;
}

.conversation-select select:focus {
  border-color: var(--ct-primary-color);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
}

.conversation-select select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background-color: var(--ct-bg-disabled);
}
</style>
