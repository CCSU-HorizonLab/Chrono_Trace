<template>
  <div class="filters-bar">
    <div class="left">
      <div class="conversation-select" ref="dropdownRef">
        <label>选择联系人</label>
        <div class="searchable-select">
          <input 
            type="text" 
            v-model="searchQuery"
            @focus="onInputFocus"
            :placeholder="selectedConversationName || '-- 请选择联系人 --'"
            :disabled="loading"
            class="select-input"
          />
          <svg class="select-arrow" :class="{ 'is-open': showDropdown }" width="20" height="20" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 8l5 5 5-5" stroke="#666" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <ul v-show="showDropdown" class="dropdown-list">
            <li 
              v-for="conv in filteredConversations" 
              :key="conv.id"
              @click="selectConversation(conv.id)"
              :class="{ active: conv.id === selectedConversationId }"
              class="dropdown-item"
            >
              {{ conv.name || conv.username || '未知联系人' }} ({{ conv.message_count }}条)
            </li>
            <li v-if="filteredConversations.length === 0" class="dropdown-item no-results">
              无匹配联系人
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'

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

const dropdownRef = ref<HTMLElement | null>(null)
const showDropdown = ref(false)
const searchQuery = ref('')

const selectedConversationName = computed(() => {
  const conv = props.conversations.find(c => c.id === props.selectedConversationId)
  if (!conv) return ''
  return `${conv.name || conv.username || '未知联系人'} (${conv.message_count}条)`
})

watch(() => props.selectedConversationId, () => {
  searchQuery.value = selectedConversationName.value
}, { immediate: true })

const filteredConversations = computed(() => {
  let list: Conversation[]
  if (!showDropdown.value || searchQuery.value === selectedConversationName.value) {
    list = [...props.conversations]
  } else {
    const q = searchQuery.value.toLowerCase()
    list = props.conversations.filter(c => {
      const name = (c.name || '').toLowerCase()
      const username = (c.username || '').toLowerCase()
      return name.includes(q) || username.includes(q)
    })
  }
  // 按消息数量递减排序
  return list.sort((a, b) => (b.message_count || 0) - (a.message_count || 0))
})

function selectConversation(id: number) {
  emit('update:conversation-id', id)
  showDropdown.value = false
}

function onClickOutside(event: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target as Node)) {
    showDropdown.value = false
    searchQuery.value = selectedConversationName.value
  }
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
})

function onInputFocus() {
  showDropdown.value = true
  searchQuery.value = ''
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
  position: relative;
}

.conversation-select label {
  font-weight: 500;
  color: var(--ct-text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.searchable-select {
  position: relative;
  min-width: 250px;
}

.select-input {
  width: 100%;
  padding: 8px 32px 8px 12px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-input);
  font-size: 1rem;
  color: var(--ct-text-primary);
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.select-input:focus {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
}

.select-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background-color: var(--ct-bg-disabled);
}

.select-arrow {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  transition: transform 0.2s ease;
}

.select-arrow.is-open {
  transform: translateY(-50%) rotate(180deg);
}

.dropdown-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  padding: 4px 0;
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  box-shadow: var(--ct-shadow-lg);
  max-height: 250px;
  overflow-y: auto;
  z-index: 100;
  list-style: none;
}

.dropdown-item {
  padding: 8px 12px;
  cursor: pointer;
  color: var(--ct-text-primary);
  transition: background-color 0.2s ease;
}

.dropdown-item:hover {
  background-color: var(--ct-bg-hover);
}

.dropdown-item.active {
  background-color: var(--ct-color-primary);
  color: white;
  font-weight: 500;
}

.dropdown-item.no-results {
  color: var(--ct-text-secondary);
  text-align: center;
  cursor: default;
}
.dropdown-item.no-results:hover {
  background-color: transparent;
}
</style>
