<template>
  <div class="ct-layout">
    <aside class="ct-sidebar">
      <!-- Logo区域 -->
      <div class="sidebar-brand">
        <div class="brand-logo">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
        </div>
        <div>
          <h1 class="brand-title">Chrono Trace</h1>
          <p class="brand-tagline">对话年轮 · 心动间距</p>
        </div>
      </div>

      <!-- 导航菜单 -->
      <nav class="ct-menu">
        <router-link to="/" class="menu-item">
          <span class="menu-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
              <polyline points="9 22 9 12 15 12 15 22"></polyline>
            </svg>
          </span>
          <span class="menu-label">首页</span>
        </router-link>

        <router-link to="/analytics" class="menu-item">
          <span class="menu-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="20" x2="18" y2="10"></line>
              <line x1="12" y1="20" x2="12" y2="4"></line>
              <line x1="6" y1="20" x2="6" y2="14"></line>
            </svg>
          </span>
          <span class="menu-label">历史数据</span>
        </router-link>

        <router-link to="/affinity" class="menu-item">
          <span class="menu-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
            </svg>
          </span>
          <span class="menu-label">好感度</span>
        </router-link>

        <router-link to="/suggestions" class="menu-item">
          <span class="menu-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
          </span>
          <span class="menu-label">AI 建议</span>
        </router-link>

        <router-link to="/settings" class="menu-item">
          <span class="menu-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
            </svg>
          </span>
          <span class="menu-label">设置</span>
        </router-link>
      </nav>

      <!-- 底部工具区 -->
      <div class="sidebar-footer">
        <ThemeToggle />
      </div>
    </aside>

    <main class="ct-content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import ThemeToggle from '@/components/base/ThemeToggle.vue'
import { initTheme } from '@/composables/useTheme'

onMounted(() => {
  initTheme()
})
</script>

<style>
/* ========================================
   Global Layout - Editorial & Sophisticated
   ======================================== */

.ct-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  min-height: 100vh;
  background: var(--ct-bg-primary);
}

/* ========================================
   Sidebar - Premium Navigation
   ======================================== */

.ct-sidebar {
  background: var(--ct-bg-elevated);
  border-right: 1px solid var(--ct-border-color);
  display: flex;
  flex-direction: column;
  padding: var(--ct-space-lg);
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  box-shadow: var(--ct-shadow-sm);
}

/* Logo区域 */
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  padding: var(--ct-space-lg) 0;
  margin-bottom: var(--ct-space-xl);
  border-bottom: 1px solid var(--ct-border-color);
}

.brand-logo {
  width: 48px;
  height: 48px;
  border-radius: var(--ct-radius-lg);
  background: linear-gradient(135deg, var(--ct-color-primary), var(--ct-color-accent));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ct-text-inverse);
  flex-shrink: 0;
  box-shadow: var(--ct-shadow-md);
}

.brand-title {
  font-family: var(--ct-font-display);
  font-size: var(--ct-text-lg);
  font-weight: 700;
  color: var(--ct-text-primary);
  margin: 0;
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.brand-tagline {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  margin: 0;
  margin-top: 2px;
  letter-spacing: 0.05em;
}

/* 导航菜单 */
.ct-menu {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xs);
  flex: 1;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  padding: var(--ct-space-md) var(--ct-space-lg);
  border-radius: var(--ct-radius-md);
  color: var(--ct-text-secondary);
  text-decoration: none;
  font-size: var(--ct-text-sm);
  font-weight: 500;
  transition: all var(--ct-transition-fast);
  position: relative;
}

.menu-item:hover {
  background: var(--ct-bg-secondary);
  color: var(--ct-text-primary);
  transform: translateX(2px);
}

.menu-item.router-link-active {
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  font-weight: 600;
}

.menu-item.router-link-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  background: var(--ct-color-primary);
  border-radius: 0 var(--ct-radius-sm) var(--ct-radius-sm) 0;
}

.menu-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.menu-label {
  flex: 1;
}

/* 底部工具区 */
.sidebar-footer {
  margin-top: auto;
  padding-top: var(--ct-space-lg);
  border-top: 1px solid var(--ct-border-color);
}

/* ========================================
   Main Content Area
   ======================================== */

.ct-content {
  padding: var(--ct-space-xl);
  overflow: auto;
  min-height: 100vh;
}

/* 响应式设计 */
@media (max-width: 1024px) {
  .ct-layout {
    grid-template-columns: 240px 1fr;
  }

  .ct-sidebar {
    padding: var(--ct-space-md);
  }

  .brand-logo {
    width: 40px;
    height: 40px;
  }

  .brand-title {
    font-size: var(--ct-text-base);
  }

  .brand-tagline {
    display: none;
  }
}

@media (max-width: 768px) {
  .ct-layout {
    grid-template-columns: 1fr;
  }

  .ct-sidebar {
    position: fixed;
    left: -100%;
    top: 0;
    width: 280px;
    z-index: 1000;
    transition: left var(--ct-transition-normal);
  }

  .ct-sidebar.open {
    left: 0;
    box-shadow: var(--ct-shadow-xl);
  }

  .ct-content {
    padding: var(--ct-space-md);
  }
}

/* 滚动条美化 */
.ct-sidebar::-webkit-scrollbar {
  width: 6px;
}

.ct-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.ct-sidebar::-webkit-scrollbar-thumb {
  background: var(--ct-border-color);
  border-radius: var(--ct-radius-full);
}

.ct-sidebar::-webkit-scrollbar-thumb:hover {
  background: var(--ct-border-color-hover);
}
</style>
