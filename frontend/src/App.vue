<template>
  <div class="ct-layout" :class="{ 'floating-mode': isFloatingMode }">
    <!-- 顶部导航栏 -->
    <header class="ct-topbar" v-show="!isFloatingMode">
      <!-- Logo与标题区域 -->
      <div class="topbar-brand">
        <!-- 暂时取消实际Logo图片或复杂图标，保留文字排版 -->
        <div class="brand-text">
          <h1 class="brand-title">Chrono Trace</h1>
          <p class="brand-tagline">镌刻对话年轮，丈量心动间距</p>
        </div>
      </div>

      <!-- 居中导航菜单：对象工作台口径——首页 / TA 档案 / 设置 -->
      <nav class="ct-menu">
        <router-link to="/" class="menu-item">首页</router-link>
        <router-link to="/analytics" class="menu-item">TA 档案</router-link>
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
      <div class="close-confirm-card" role="dialog" aria-modal="true" aria-labelledby="close-confirm-title">
        <div class="close-confirm-head">
          <div class="close-confirm-head-left">
            <span class="close-confirm-icon" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path>
                <line x1="12" y1="2" x2="12" y2="12"></line>
              </svg>
            </span>
            <div>
              <h3 id="close-confirm-title" class="close-confirm-title">要退出 Chrono Trace 吗？</h3>
              <span class="close-confirm-sub">选择关闭主窗口后的运行方式</span>
            </div>
          </div>
          <button class="close-confirm-x" type="button" @click="showCloseDialog = false" aria-label="关闭弹窗">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div class="close-confirm-body">
          <p class="close-confirm-text">
            <strong>直接退出</strong>会中断正在进行的后台分析与实时监听；<strong>最小化运行</strong>则保留在任务栏或系统托盘继续静默守护。
          </p>

          <label class="close-confirm-remember">
            <input type="checkbox" class="ct-checkbox-input" v-model="rememberCloseChoice" />
            <span class="ct-checkbox" aria-hidden="true">
              <svg viewBox="0 0 12 10" fill="none">
                <path d="M1.5 5.2L4.5 8.2L10.5 1.8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </span>
            <div class="cc-remember-copy">
              <span class="cc-remember-main">记住我的选择，下次不再询问</span>
              <span class="cc-remember-hint">后续可在「设置 → 杂项维护 → 关闭按钮行为」中随时修改</span>
            </div>
          </label>
        </div>

        <div class="close-confirm-actions">
          <button type="button" class="ct-btn ghost" @click="showCloseDialog = false">取消</button>
          <div class="close-confirm-actions-right">
            <button type="button" class="ct-btn secondary" @click="handleCloseChoice('minimize')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="4 14 10 14 10 20"></polyline>
                <polyline points="20 10 14 10 14 4"></polyline>
                <line x1="14" y1="10" x2="21" y2="3"></line>
                <line x1="3" y1="21" x2="10" y2="14"></line>
              </svg>
              <span>最小化运行</span>
            </button>
            <button type="button" class="ct-btn primary" @click="handleCloseChoice('exit')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                <polyline points="16 17 21 12 16 7"></polyline>
                <line x1="21" y1="12" x2="9" y2="12"></line>
              </svg>
              <span>退出应用</span>
            </button>
          </div>
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

// 后端实时消息推送入口（evaluate_js 调用）：转投 CustomEvent，
// 由 FloatingPanel 监听 chrono:realtime-push 按批次匹配合并上屏
function __chronoRealtimePush(payload: unknown) {
  window.dispatchEvent(new CustomEvent('chrono:realtime-push', { detail: payload }))
}
;(window as any).__chronoRealtimePush = __chronoRealtimePush

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
   Topbar - 暖纸玻璃 + 发丝线（墨痕暖白）
   ======================================== */

.ct-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--ct-space-xl);
  height: 64px;
  background: rgba(250, 249, 247, 0.86);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--ct-border-color);
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 1000;
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
  font-family: var(--ct-font-brand);
  font-size: var(--ct-text-xl);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
  margin: 0;
  line-height: 1.2;
}

.brand-tagline {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  margin: 0;
  margin-top: 2px;
}

/* 导航菜单 - 沉底胶囊 */
.ct-menu {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
  background: var(--ct-bg-sunken);
  padding: 4px;
  border-radius: var(--ct-radius-full);
}

.menu-item {
  padding: 6px 20px;
  border-radius: var(--ct-radius-full);
  color: var(--ct-text-secondary);
  text-decoration: none;
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-medium);
  transition: color var(--ct-transition-fast) var(--ct-ease-out),
              background-color var(--ct-transition-fast) var(--ct-ease-out);
}

.menu-item:hover {
  color: var(--ct-text-primary);
  background: var(--ct-bg-hover);
}

.menu-item.router-link-active {
  background: var(--ct-bg-card);
  color: var(--ct-color-primary);
  font-weight: var(--ct-font-semibold);
  box-shadow: var(--ct-shadow-sm);
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
  transition: box-shadow var(--ct-transition-fast) var(--ct-ease-out);
  display: flex;
}

.avatar-trigger-wrap:hover {
  box-shadow: 0 0 0 3px var(--ct-color-primary-tint);
}

.avatar-trigger-wrap.is-open {
  box-shadow: 0 0 0 3px var(--ct-color-primary-tint), 0 0 0 1px var(--ct-color-primary);
}

.user-avatar {
  border: 2px solid var(--ct-bg-card);
  box-shadow: var(--ct-shadow-sm);
}

.user-avatar.popup-trigger {
  pointer-events: none; /* 让外层 wrap 接管点击 */
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

/* 关闭确认对话框（墨痕暖白） */
.close-confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(27, 25, 36, 0.45);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: cc-fade-in 0.16s ease;
}

.close-confirm-card {
  width: 428px;
  max-width: 100%;
  border-radius: var(--ct-radius-lg);
  background: var(--ct-bg-card);
  color: var(--ct-text-primary);
  box-shadow: var(--ct-shadow-lg);
  overflow: hidden;
  animation: cc-pop-in 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.close-confirm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--ct-border-color);
}

.close-confirm-head-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.close-confirm-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: var(--ct-radius-md);
  flex-shrink: 0;
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
}

.close-confirm-title {
  margin: 0;
  font-size: var(--ct-text-base);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
  line-height: 1.3;
}

.close-confirm-sub {
  display: block;
  margin-top: 2px;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.close-confirm-x {
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: var(--ct-radius-sm);
  border: none;
  background: transparent;
  color: var(--ct-text-tertiary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color var(--ct-transition-fast) var(--ct-ease-out),
              color var(--ct-transition-fast) var(--ct-ease-out);
}

.close-confirm-x:hover {
  background: var(--ct-bg-hover);
  color: var(--ct-text-primary);
}

.close-confirm-body {
  padding: 16px 20px 14px;
}

.close-confirm-text {
  margin: 0 0 14px;
  font-size: var(--ct-text-sm);
  line-height: 1.68;
  color: var(--ct-text-secondary);
}

.close-confirm-text strong {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-semibold);
}

.close-confirm-remember {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  cursor: pointer;
  user-select: none;
  padding: 11px 13px;
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
  border: 1px solid transparent;
  transition: background-color var(--ct-transition-fast) var(--ct-ease-out),
              border-color var(--ct-transition-fast) var(--ct-ease-out);
}

.close-confirm-remember:hover {
  background: var(--ct-bg-hover);
  border-color: var(--ct-border-color-hover);
}

.cc-remember-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cc-remember-main {
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-semibold);
  color: var(--ct-text-primary);
  line-height: 1.35;
}

.cc-remember-hint {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  line-height: 1.4;
}

.close-confirm-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 13px 20px;
  background: var(--ct-bg-sunken);
  border-top: 1px solid var(--ct-border-color);
}

.close-confirm-actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

@keyframes cc-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes cc-pop-in { from { opacity: 0; transform: translateY(8px) scale(0.97); } to { opacity: 1; transform: none; } }
</style>
