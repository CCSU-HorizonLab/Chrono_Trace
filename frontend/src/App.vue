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
        <router-link to="/analytics" class="menu-item">联系人洞察</router-link>
        <router-link to="/suggestions" class="menu-item">实时助手</router-link>
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
            <input type="checkbox" v-model="rememberCloseChoice" />
            <span class="cc-checkbox-box" aria-hidden="true">
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
          <button type="button" class="cc-btn cc-btn--ghost" @click="showCloseDialog = false">取消</button>
          <div class="close-confirm-actions-right">
            <button type="button" class="cc-btn cc-btn--secondary" @click="handleCloseChoice('minimize')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="4 14 10 14 10 20"></polyline>
                <polyline points="20 10 14 10 14 4"></polyline>
                <line x1="14" y1="10" x2="21" y2="3"></line>
                <line x1="3" y1="21" x2="10" y2="14"></line>
              </svg>
              <span>最小化运行</span>
            </button>
            <button type="button" class="cc-btn cc-btn--primary" @click="handleCloseChoice('exit')">
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
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(5px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: cc-fade-in 0.16s ease;
}

.close-confirm-card {
  width: 428px;
  max-width: 100%;
  border-radius: 18px;
  background: #ffffff;
  color: #1f2430;
  border: 1px solid rgba(108, 92, 231, 0.14);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18), 0 4px 16px rgba(108, 92, 231, 0.08);
  overflow: hidden;
  animation: cc-pop-in 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.close-confirm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 14px;
  background: linear-gradient(180deg, rgba(108, 92, 231, 0.06) 0%, rgba(108, 92, 231, 0.01) 100%);
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
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
  border-radius: 11px;
  flex-shrink: 0;
  background: linear-gradient(135deg, #6c5ce7 0%, #8e7cf3 100%);
  color: #ffffff;
  box-shadow: 0 6px 14px rgba(108, 92, 231, 0.24);
}

.close-confirm-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #1f2430;
  letter-spacing: 0.2px;
  line-height: 1.3;
}

.close-confirm-sub {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: #6b7280;
}

.close-confirm-x {
  width: 30px !important;
  height: 30px !important;
  min-height: 30px !important;
  padding: 0 !important;
  border-radius: 8px !important;
  border: none !important;
  background: transparent !important;
  color: #64748b !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.close-confirm-x:hover {
  background: rgba(15, 23, 42, 0.06) !important;
  color: #1f2430 !important;
}

.close-confirm-body {
  padding: 16px 20px 14px;
}

.close-confirm-text {
  margin: 0 0 14px;
  font-size: 13.5px;
  line-height: 1.68;
  color: #4b5563;
}

.close-confirm-text strong {
  color: #1f2430;
  font-weight: 600;
}

.close-confirm-remember {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  cursor: pointer;
  user-select: none;
  padding: 11px 13px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.close-confirm-remember:hover {
  background: #f5f3ff;
  border-color: rgba(108, 92, 231, 0.36);
}

.close-confirm-remember input[type='checkbox'] {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.cc-checkbox-box {
  width: 18px;
  height: 18px;
  margin-top: 1px;
  border-radius: 6px;
  border: 1.5px solid #cbd5e1;
  background: #ffffff;
  color: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.16s ease;
}

.cc-checkbox-box svg {
  width: 11px;
  height: 9px;
  transform: scale(0.75);
  transition: transform 0.16s ease;
}

.close-confirm-remember:hover .cc-checkbox-box {
  border-color: #6c5ce7;
}

.close-confirm-remember input[type='checkbox']:checked + .cc-checkbox-box {
  background: #6c5ce7;
  border-color: #6c5ce7;
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(108, 92, 231, 0.28);
}

.close-confirm-remember input[type='checkbox']:checked + .cc-checkbox-box svg {
  transform: scale(1);
}

.cc-remember-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cc-remember-main {
  font-size: 13px;
  font-weight: 600;
  color: #1f2430;
  line-height: 1.35;
}

.cc-remember-hint {
  font-size: 11.5px;
  color: #6b7280;
  line-height: 1.4;
}

.close-confirm-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 13px 20px;
  background: #f8fafc;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
}

.close-confirm-actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cc-btn {
  height: 36px !important;
  min-height: 36px !important;
  padding: 0 14px !important;
  border-radius: 10px !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.1s ease, box-shadow 0.16s ease;
}

.cc-btn:active {
  transform: scale(0.98);
}

.cc-btn--ghost {
  background: transparent !important;
  color: #64748b !important;
  border: 1px solid transparent !important;
}

.cc-btn--ghost:hover {
  background: rgba(15, 23, 42, 0.06) !important;
  color: #1f2430 !important;
}

.cc-btn--secondary {
  background: #ffffff !important;
  color: #4f46e5 !important;
  border: 1px solid rgba(108, 92, 231, 0.34) !important;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.cc-btn--secondary:hover {
  background: #f5f3ff !important;
  border-color: #6c5ce7 !important;
}

.cc-btn--primary {
  background: linear-gradient(135deg, #6c5ce7 0%, #5b4bc4 100%) !important;
  color: #ffffff !important;
  border: 1px solid transparent !important;
  box-shadow: 0 6px 16px rgba(108, 92, 231, 0.25);
}

.cc-btn--primary:hover {
  background: linear-gradient(135deg, #5f4dd6 0%, #4e3fb3 100%) !important;
  box-shadow: 0 8px 18px rgba(108, 92, 231, 0.32);
}

@keyframes cc-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes cc-pop-in { from { opacity: 0; transform: translateY(8px) scale(0.97); } to { opacity: 1; transform: none; } }
</style>
