<template>
  <div class="ct-layout" :class="{ 'floating-mode': isFloatingMode }">
    <!-- 顶部导航栏 -->
    <header class="ct-topbar" v-show="!isFloatingMode">
      <!-- Logo与标题区域 -->
      <div class="topbar-brand">
        <!-- 暂时取消实际Logo图片或复杂图标，保留文字排版 -->
        <div class="brand-text">
          <h1 class="brand-title">Chrono_Trace</h1>
          <p class="brand-tagline">镌刻对话年轮，丈量心动间距</p>
        </div>
      </div>

      <!-- 居中导航菜单 -->
      <nav class="ct-menu">
        <router-link to="/" class="menu-item">首页</router-link>
        <router-link to="/analytics" class="menu-item">历史数据</router-link>
        <router-link to="/suggestions" class="menu-item">AI建议</router-link>
        <router-link to="/settings" class="menu-item">设置</router-link>
      </nav>

      <!-- 右侧用户区 -->
      <div class="topbar-user">
        <!-- 头像占位符 -->
        <div class="user-avatar">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </div>
        <!-- 可以在下拉菜单里放ThemeToggle或者直接放这里，此处先简化 -->
        <ThemeToggle class="theme-toggle-btn" />
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="ct-content" :class="{ 'floating-content': isFloatingMode }">
      <div class="main-container">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import ThemeToggle from '@/components/base/ThemeToggle.vue'
import { initTheme } from '@/composables/useTheme'

const route = useRoute()

// 悬浮模式下隐藏顶部导航
const isFloatingMode = computed(() => route.path === '/floating')

onMounted(() => {
  initTheme()
})
</script>

<style>
/* ========================================
   Global Layout - Full width Topbar
   ======================================== */

.ct-layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* ========================================
   Topbar - Premium Header
   ======================================== */

.ct-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--ct-space-xl);
  height: 64px;
  background: linear-gradient(100deg, var(--ct-color-primary) 0%, #a855f7 100%);
  flex-shrink: 0;
  position: relative;
  z-index: 10;
  box-shadow: var(--ct-shadow-sm);
}

/* Logo区域 */
.topbar-brand {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  width: 300px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.brand-title {
  font-family: var(--ct-font-display);
  font-size: var(--ct-text-xl);
  font-weight: 700;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0,0,0,0.1);
  margin: 0;
  line-height: 1.2;
}

.brand-tagline {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
  margin: 0;
  margin-top: 2px;
}

/* 导航菜单 - 胶囊状 */
.ct-menu {
  display: flex;
  align-items: center;
  gap: var(--ct-space-sm);
  background: rgba(255, 255, 255, 0.2);
  padding: 4px;
  border-radius: var(--ct-radius-full);
  backdrop-filter: blur(10px);
}

.menu-item {
  padding: 6px 20px;
  border-radius: var(--ct-radius-full);
  color: rgba(255, 255, 255, 0.9);
  text-decoration: none;
  font-size: var(--ct-text-sm);
  font-weight: 500;
  transition: all var(--ct-transition-fast);
}

.menu-item:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.menu-item.router-link-active {
  background: #ffffff;
  color: var(--ct-color-primary);
  font-weight: 600;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* 右侧用户区 */
.topbar-user {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--ct-space-md);
  width: 300px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #a5b4fc;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  border: 2px solid rgba(255,255,255,0.3);
  overflow: hidden;
}

.user-avatar svg {
  width: 18px;
  height: 18px;
}

.theme-toggle-btn {
  color: #fff;
  opacity: 0.8;
}
.theme-toggle-btn:hover {
  opacity: 1;
}

/* ========================================
   Main Content Area
   ======================================== */

.ct-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
}

.main-container {
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
}

/* 响应式 */
@media (max-width: 1024px) {
  .ct-topbar { padding: 0 var(--ct-space-lg); }
  .topbar-brand, .topbar-user { width: auto; }
  .brand-tagline { display: none; }
}

@media (max-width: 768px) {
  .ct-topbar {
    flex-direction: column;
    height: auto;
    padding: var(--ct-space-md);
    gap: var(--ct-space-md);
  }
}
</style>
