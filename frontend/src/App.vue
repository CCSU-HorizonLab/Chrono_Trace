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
        <CtAccountSelector
          v-if="wechatAccounts.length"
          :modelValue="activeAccountWxid"
          @update:modelValue="handleAccountChangeValue"
          :accounts="wechatAccounts"
        >
          <template #trigger="{ isOpen }">
            <div class="avatar-trigger-wrap" :class="{ 'is-open': isOpen }">
              <CtAvatar
                class="user-avatar popup-trigger"
                :src="currentUserProfile.avatar"
                :name="currentUserProfile.name || '我'"
                :size="42"
              />
            </div>
          </template>
        </CtAccountSelector>
        
        <CtAvatar
          v-else
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
  <!-- 关闭按钮确认对话框（close_guard 拦截 X 点击后触发） -->
  <teleport to="body">
    <div v-if="showCloseDialog" class="close-confirm-mask" @click.self="showCloseDialog = false">
      <div class="close-confirm-card" role="dialog" aria-modal="true">
        <div class="close-confirm-head">
          <span class="close-confirm-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </span>
          <h3 class="close-confirm-title">要退出 Chrono_Trace 吗？</h3>
        </div>
        <p class="close-confirm-text">退出会中断正在进行的分析与实时监听；最小化则保留在任务栏继续运行。</p>
        <label class="close-confirm-remember">
          <input type="checkbox" v-model="rememberCloseChoice" />
          <span>记住我的选择（设置 → 关闭按钮行为 可改回）</span>
        </label>
        <div class="close-confirm-actions">
          <button class="cc-btn ghost" @click="showCloseDialog = false">取消</button>
          <button class="cc-btn ghost" @click="handleCloseChoice('minimize')">最小化</button>
          <button class="cc-btn primary" @click="handleCloseChoice('exit')">退出应用</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { bridgeReady, api } from '@/api/bridge'
import CtAvatar from '@/components/base/CtAvatar.vue'
import CtAccountSelector from '@/components/base/CtAccountSelector.vue'
import { clearWechatAccountProfileCache, enrichWechatAccountsWithProfiles } from '@/utils/wechatAccounts'

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

async function loadWechatAccounts(options: { forceProfiles?: boolean } = {}) {
  try {
    await bridgeReady()
    const result = await api.get_wechat_accounts()
    if (!result?.ok) return
    wechatAccounts.value = await enrichWechatAccountsWithProfiles(
      result.accounts || [],
      { forceRefresh: options.forceProfiles },
    )
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

async function handleAccountChangeValue(wxid: string) {
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

async function handleProfileRefresh(event?: Event) {
  const detail = (event as CustomEvent | undefined)?.detail || {}
  clearWechatAccountProfileCache(detail.wxid || activeAccountWxid.value)
  await Promise.all([
    loadWechatAccounts({ forceProfiles: Boolean(detail.forceProfiles ?? true) }),
    loadCurrentUserProfile(),
  ])
}

async function handleWechatSettingsSaved(event?: Event) {
  const detail = (event as CustomEvent | undefined)?.detail || {}
  if (detail.wxid) {
    activeAccountWxid.value = detail.wxid
  }
  await Promise.all([
    loadWechatAccounts(),
    loadCurrentUserProfile(),
  ])
}

watch(() => route.fullPath, () => {
  if (!isFloatingMode.value) {
    loadWechatAccounts()
    loadCurrentUserProfile()
  }
}, { immediate: true })

// ---- 关闭按钮确认（后端 close_guard 拦截 X 后调用 window.__chronoHandleCloseRequest）----
const showCloseDialog = ref(false)
const rememberCloseChoice = ref(false)

async function __chronoHandleCloseRequest() {
  try {
    const result = await api.get_settings()
    const behavior = String(result?.close_button_behavior || 'ask').toLowerCase()
    if (behavior === 'minimize') {
      await api.perform_close_action('minimize')
      return
    }
    if (behavior === 'exit') {
      await api.perform_close_action('exit')
      return
    }
  } catch {
    // 设置读取失败按询问处理
  }
  showCloseDialog.value = true
}

async function handleCloseChoice(action: 'minimize' | 'exit') {
  showCloseDialog.value = false
  try {
    if (rememberCloseChoice.value) {
      await api.set_settings({ close_button_behavior: action })
    }
  } catch {
    // 记忆失败不影响本次动作
  }
  await api.perform_close_action(action)
}

// 挂到 window 供后端 evaluate_js 调用（类型声明见 env.d.ts）
;(window as any).__chronoHandleCloseRequest = __chronoHandleCloseRequest

onMounted(() => {
  window.addEventListener('chrono:user-avatar-refresh', handleProfileRefresh)
  window.addEventListener('chrono:wechat-settings-saved', handleWechatSettingsSaved)
  loadWechatAccounts()
})

onUnmounted(() => {
  window.removeEventListener('chrono:user-avatar-refresh', handleProfileRefresh)
  window.removeEventListener('chrono:wechat-settings-saved', handleWechatSettingsSaved)
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

.avatar-trigger-wrap {
  cursor: pointer;
  border-radius: 50%;
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.2s ease;
  display: flex;
}

.avatar-trigger-wrap:hover {
  transform: scale(1.05);
}

.avatar-trigger-wrap.is-open {
  transform: scale(0.95);
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.5);
}

.user-avatar {
  border: 2px solid rgba(255,255,255,0.3);
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  box-shadow: 0 6px 16px rgba(76, 29, 149, 0.25);
}

.user-avatar.popup-trigger {
  pointer-events: none; /* Let the wrapper handle clicks */
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

/* 关闭确认对话框 */
.close-confirm-mask {
  position: fixed; inset: 0; z-index: 3000;
  background: rgba(10, 12, 18, 0.6);
  backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
  animation: cc-fade-in 0.14s ease;
}
.close-confirm-card {
  width: 380px; padding: 22px 24px 18px; border-radius: 14px;
  background: var(--ct-bg-elevated, #1d222c); color: var(--ct-text-main, #e8eaf0);
  border: 1px solid rgba(255, 255, 255, 0.07);
  box-shadow: 0 22px 56px rgba(0, 0, 0, 0.5);
  animation: cc-pop-in 0.16s ease;
}
.close-confirm-head {
  display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
}
.close-confirm-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 10px; flex-shrink: 0;
  background: rgba(108, 92, 231, 0.14); color: #8b7ff0;
}
.close-confirm-title { margin: 0; font-size: 16px; font-weight: 600; letter-spacing: 0.2px; }
.close-confirm-text {
  margin: 0 0 14px; font-size: 13px; line-height: 1.65;
  color: var(--ct-text-secondary, rgba(232, 234, 240, 0.72));
}
.close-confirm-remember {
  display: flex; align-items: center; gap: 9px;
  font-size: 12.5px; color: var(--ct-text-secondary, rgba(232, 234, 240, 0.65));
  margin-bottom: 18px; cursor: pointer; user-select: none;
  padding: 8px 10px; border-radius: 9px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: background 0.15s ease;
}
.close-confirm-remember:hover { background: rgba(255, 255, 255, 0.06); }
.close-confirm-remember input[type='checkbox'] {
  appearance: none; -webkit-appearance: none;
  width: 16px; height: 16px; margin: 0; flex-shrink: 0;
  border-radius: 5px; cursor: pointer; position: relative;
  border: 1.5px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.04);
  transition: border-color 0.15s ease, background 0.15s ease;
}
.close-confirm-remember input[type='checkbox']:hover { border-color: #8b7ff0; }
.close-confirm-remember input[type='checkbox']:checked {
  background: #6c5ce7; border-color: #6c5ce7;
}
.close-confirm-remember input[type='checkbox']:checked::after {
  content: ''; position: absolute; left: 4.5px; top: 1.5px;
  width: 5px; height: 9px;
  border: solid #fff; border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}
.close-confirm-actions {
  display: flex; justify-content: flex-end; gap: 10px;
  padding-top: 4px; border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.cc-btn {
  padding: 8px 18px; border-radius: 9px; border: 1px solid transparent;
  font-size: 13px; font-weight: 500; cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
}
.cc-btn:active { transform: scale(0.97); }
.cc-btn.ghost {
  background: transparent; color: inherit;
  border-color: rgba(255, 255, 255, 0.16);
}
.cc-btn.ghost:hover { background: rgba(255, 255, 255, 0.07); border-color: rgba(255, 255, 255, 0.26); }
.cc-btn.primary { background: #6c5ce7; color: #fff; }
.cc-btn.primary:hover { background: #5a4bd1; }
@keyframes cc-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes cc-pop-in { from { opacity: 0; transform: translateY(6px) scale(0.98); } to { opacity: 1; transform: none; } }
</style>
