import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 组件级自动 UI 测试（vitest + happy-dom）：与生产 build 的 vite.config
// 同别名，仅测试目录与 DOM 环境独立；冒烟脚本（node --test）不受影响
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.ts'],
  },
})
