import { ref, watch } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'chrono-trace-theme'

const currentTheme = ref<Theme>((localStorage.getItem(STORAGE_KEY) as Theme) || 'light')

// 监听主题变化并保存到 localStorage
watch(currentTheme, (newTheme) => {
  localStorage.setItem(STORAGE_KEY, newTheme)
  applyTheme(newTheme)
}, { immediate: false })

// 应用主题到文档
function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark-theme')
  } else {
    root.classList.remove('dark-theme')
  }
}

// 初始化主题
export function initTheme() {
  applyTheme(currentTheme.value)
}

// 切换主题
export function toggleTheme() {
  currentTheme.value = currentTheme.value === 'light' ? 'dark' : 'light'
}

// 设置主题
export function setTheme(theme: Theme) {
  currentTheme.value = theme
}

// 获取当前主题
export function useTheme() {
  return {
    theme: currentTheme,
    toggleTheme,
    setTheme,
    isDark: () => currentTheme.value === 'dark'
  }
}
