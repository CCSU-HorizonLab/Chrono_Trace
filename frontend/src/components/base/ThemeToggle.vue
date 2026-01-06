<template>
  <button
    class="theme-toggle"
    :class="{ 'is-dark': isDark }"
    @click="toggleTheme"
    :title="isDark ? '切换到浅色模式' : '切换到深色模式'"
  >
    <span class="theme-icon">
      {{ isDark ? '🌙' : '☀️' }}
    </span>
    <span class="theme-label">
      {{ isDark ? '深色' : '浅色' }}
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTheme } from '@/composables/useTheme'

const { theme, toggleTheme, isDark } = useTheme()

const currentTheme = computed(() => theme.value)
</script>

<style scoped>
.theme-toggle {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-sm) var(--ct-space-md);
  background: var(--ct-bg-tertiary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  color: var(--ct-text-primary);
  cursor: pointer;
  font-size: 14px;
  font-family: inherit;
}

.theme-toggle:hover {
  background: var(--ct-bg-secondary);
  border-color: var(--ct-border-color-hover);
}

.theme-icon {
  font-size: 16px;
  line-height: 1;
  transition: transform 0.3s ease;
}

.theme-toggle:hover .theme-icon {
  transform: rotate(20deg);
}

.theme-label {
  font-weight: 500;
}
</style>
