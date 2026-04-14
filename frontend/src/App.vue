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
        <label v-if="wechatAccounts.length" class="account-switcher">
          <span class="account-switcher-label">账号</span>
          <select :value="activeAccountWxid" class="account-switcher-select" @change="handleAccountChange">
            <option v-for="account in wechatAccounts" :key="account.wxid" :value="account.wxid">
              {{ account.label || account.wxid }}
            </option>
          </select>
        </label>
        <CtAvatar
          class="user-avatar"
          :src="currentUserProfile.avatar"
          :name="currentUserProfile.name || '我'"
          :size="42"
        />
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
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { bridgeReady, api } from '@/api/bridge'
import CtAvatar from '@/components/base/CtAvatar.vue'

const route = useRoute()

// 悬浮模式下隐藏顶部导航
const isFloatingMode = computed(() => route.path === '/floating')
const currentUserProfile = reactive({
  wxid: '',
  name: '我',
  avatar: '',
})
const wechatAccounts = ref<any[]>([])
const activeAccountWxid = ref('')

async function loadWechatAccounts() {
  try {
    await bridgeReady()
    const result = await api.get_wechat_accounts()
    if (!result?.ok) return
    wechatAccounts.value = result.accounts || []
    activeAccountWxid.value = result.active_account_wxid || ''
  } catch (error) {
    console.error('[App] 加载微信账号列表失败:', error)
  }
}

async function loadCurrentUserProfile() {
  try {
    await bridgeReady()
    const result = await api.get_current_user_profile()
    const profile = result?.profile
    if (!result?.ok || !profile) {
      currentUserProfile.wxid = ''
      currentUserProfile.name = '我'
      currentUserProfile.avatar = ''
      return
    }

    currentUserProfile.wxid = profile.wxid || ''
    currentUserProfile.name = profile.name || '我'
    currentUserProfile.avatar = profile.avatar || ''
  } catch (error) {
    console.error('[App] 加载当前用户头像失败:', error)
  }
}

async function handleAccountChange(event: Event) {
  const target = event.target as HTMLSelectElement | null
  const wxid = target?.value || ''
  if (!wxid || wxid === activeAccountWxid.value) return

  try {
    await bridgeReady()
    const result = await api.set_active_wechat_account(wxid)
    if (!result?.ok) return
    activeAccountWxid.value = result.active_account_wxid || wxid
    await Promise.all([loadWechatAccounts(), loadCurrentUserProfile()])
    window.dispatchEvent(new CustomEvent('chrono:wechat-account-changed', { detail: { wxid: activeAccountWxid.value } }))
    window.dispatchEvent(new CustomEvent('chrono:user-avatar-refresh'))
  } catch (error) {
    console.error('[App] 切换微信账号失败:', error)
  }
}

function handleProfileRefresh() {
  loadCurrentUserProfile()
}

watch(() => route.fullPath, () => {
  if (!isFloatingMode.value) {
    loadWechatAccounts()
    loadCurrentUserProfile()
  }
}, { immediate: true })

onMounted(() => {
  window.addEventListener('chrono:user-avatar-refresh', handleProfileRefresh)
  loadWechatAccounts()
})

onUnmounted(() => {
  window.removeEventListener('chrono:user-avatar-refresh', handleProfileRefresh)
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
  position: sticky;
  top: 0;
  z-index: 1000;
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

.account-switcher {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.account-switcher-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.8);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.account-switcher-select {
  min-width: 120px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}

.account-switcher-select option {
  color: #111827;
}

.user-avatar {
  border: 2px solid rgba(255,255,255,0.3);
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  box-shadow: 0 6px 16px rgba(76, 29, 149, 0.25);
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
  overflow: hidden; /* Added to keep scroll bounded to views if necessary */
}

.main-container {
  width: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden; /* Added to pass down height constraint */
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
