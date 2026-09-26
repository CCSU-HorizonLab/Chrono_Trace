<template>
  <transition name="ct-dialog-fade">
    <div v-if="visible" class="ct-dialog-overlay" @click.self="handleWrapperClick">
      <div class="ct-dialog" :class="{ 'is-wechat-upgrade': isWechatUpgrade }" role="dialog" aria-modal="true">
        <!-- 顶栏 -->
        <header class="ct-dialog-header">
          <div class="ct-dialog-head-left">
            <!-- 微信升级专属绿色图标 -->
            <span v-if="isWechatUpgrade" class="ct-dialog-icon wechat" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <path
                  d="M9.5 4C5.36 4 2 6.91 2 10.5C2 12.43 2.97 14.16 4.5 15.35L3.8 17.8L6.39 16.5C7.37 16.82 8.41 17 9.5 17C9.84 17 10.17 16.98 10.5 16.94C10.18 16.18 10 15.36 10 14.5C10 10.91 13.36 8 17.5 8C17.67 8 17.83 8.01 18 8.02C17.24 5.69 13.72 4 9.5 4ZM7 8.5C7.55 8.5 8 8.95 8 9.5C8 10.05 7.55 10.5 7 10.5C6.45 10.5 6 10.05 6 9.5C6 8.95 6.45 8.5 7 8.5ZM12 8.5C12.55 8.5 13 8.95 13 9.5C13 10.05 12.55 10.5 12 10.5C11.45 10.5 11 10.05 11 9.5C11 8.95 11.45 8.5 12 8.5Z"
                  fill="currentColor"
                />
                <path
                  d="M22 14.5C22 11.46 19.09 9 15.5 9C11.91 9 9 11.46 9 14.5C9 17.54 11.91 20 15.5 20C16.43 20 17.31 19.83 18.11 19.53L20.3 20.6L19.72 18.56C21.11 17.54 22 16.1 22 14.5ZM13.5 13C13.91 13 14.25 13.34 14.25 13.75C14.25 14.16 13.91 14.5 13.5 14.5C13.09 14.5 12.75 14.16 12.75 13.75C12.75 13.34 13.09 13 13.5 13ZM17.5 13C17.91 13 18.25 13.34 18.25 13.75C18.25 14.16 17.91 14.5 17.5 14.5C17.09 14.5 16.75 14.16 16.75 13.75C16.75 13.34 17.09 13 17.5 13Z"
                  fill="currentColor"
                />
              </svg>
            </span>

            <!-- 常规弹窗图标 -->
            <span v-else class="ct-dialog-icon" :class="effectiveType" aria-hidden="true">
              <svg v-if="effectiveType === 'error'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
              <svg v-else-if="effectiveType === 'warning'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
            </span>

            <div class="ct-dialog-title-wrap">
              <h3 class="ct-dialog-title">
                {{ isWechatUpgrade ? '请升级微信至 4.0 及以上版本' : (title || '提示') }}
              </h3>
              <span v-if="isWechatUpgrade" class="ct-dialog-sub">
                发现旧版微信 3.9 数据库，需升级客户端后方可导入
              </span>
            </div>
          </div>

          <button type="button" class="ct-dialog-close" title="关闭" @click="handleWrapperClick">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </header>

        <!-- 微信 4.0 升级专属结构化内容区 -->
        <div v-if="isWechatUpgrade" class="ct-dialog-body wechat-upgrade-body">
          <!-- 检测到的旧版目录信息卡片 -->
          <div v-if="parsedWechatInfo.dir || parsedWechatInfo.accounts" class="wu-path-card">
            <div class="wu-path-head">
              <span class="wu-path-badge">已检测到旧版 (3.9) 目录</span>
              <span v-if="parsedWechatInfo.accounts" class="wu-account-tag">{{ parsedWechatInfo.accounts }}</span>
            </div>
            <div v-if="parsedWechatInfo.dir" class="wu-path-code">{{ parsedWechatInfo.dir }}</div>
          </div>

          <!-- 核心说明与步骤 -->
          <div class="wu-reason-box">
            <p class="wu-reason-text">
              <strong>Chrono Trace 仅支持微信 4.0 及以上版本：</strong>新版数据库结构与密钥获取体系已全面升级，旧版 3.9 数据库无法直接解析与导入。
            </p>
            <div class="wu-steps">
              <div class="wu-step-item">
                <span class="wu-step-num">1</span>
                <span>打开电脑微信 <strong>「左下角设置 → 关于微信 → 检查更新」</strong> 直接升级；</span>
              </div>
              <div class="wu-step-item">
                <span class="wu-step-num">2</span>
                <span>或点击下方官方快速链接下载安装最新版微信，登录同一账号后回到本页重试。</span>
              </div>
            </div>
          </div>

          <!-- 官方快速链接卡片：[微信，是一个生活方式](https://weixin.qq.com/) -->
          <a
            href="https://weixin.qq.com/"
            target="_blank"
            rel="noopener noreferrer"
            class="wu-quick-link-card"
            @click.prevent="openExternal('https://weixin.qq.com/')"
          >
            <div class="wu-link-logo" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M9.5 4C5.36 4 2 6.91 2 10.5C2 12.43 2.97 14.16 4.5 15.35L3.8 17.8L6.39 16.5C7.37 16.82 8.41 17 9.5 17C9.84 17 10.17 16.98 10.5 16.94C10.18 16.18 10 15.36 10 14.5C10 10.91 13.36 8 17.5 8C17.67 8 17.83 8.01 18 8.02C17.24 5.69 13.72 4 9.5 4Z"
                  fill="currentColor"
                />
                <path
                  d="M22 14.5C22 11.46 19.09 9 15.5 9C11.91 9 9 11.46 9 14.5C9 17.54 11.91 20 15.5 20C16.43 20 17.31 19.83 18.11 19.53L20.3 20.6L19.72 18.56C21.11 17.54 22 16.1 22 14.5Z"
                  fill="currentColor"
                />
              </svg>
            </div>
            <div class="wu-link-info">
              <div class="wu-link-title-row">
                <span class="wu-link-title">微信，是一个生活方式</span>
                <span class="wu-link-official">官方下载</span>
              </div>
              <span class="wu-link-url">https://weixin.qq.com/</span>
            </div>
            <span class="wu-link-action">
              <span>前往下载</span>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
                <path d="M7 17 17 7" />
                <path d="M7 7h10v10" />
              </svg>
            </span>
          </a>
        </div>

        <!-- 常规弹窗正文 -->
        <div v-else class="ct-dialog-body">
          <slot>{{ message }}</slot>
        </div>

        <!-- 底栏按钮区 -->
        <footer class="ct-dialog-footer">
          <template v-if="isWechatUpgrade">
            <button type="button" class="ct-dlg-btn secondary" @click="handleConfirm">
              我知道了
            </button>
            <button type="button" class="ct-dlg-btn wechat-primary" @click="openExternal('https://weixin.qq.com/')">
              <span>打开微信官网</span>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
                <path d="M7 17 17 7" />
                <path d="M7 7h10v10" />
              </svg>
            </button>
          </template>
          <template v-else>
            <button v-if="showCancel" type="button" class="ct-dlg-btn secondary" @click="handleCancel">
              {{ cancelText || '取消' }}
            </button>
            <button type="button" class="ct-dlg-btn primary" :class="effectiveType" @click="handleConfirm">
              {{ confirmText || '确定' }}
            </button>
          </template>
        </footer>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { api } from '@/api/bridge';

const props = defineProps<{
  title?: string;
  message?: string;
  showCancel?: boolean;
  type?: 'info' | 'warning' | 'error' | 'wechat_upgrade';
  confirmText?: string;
  cancelText?: string;
  detectedPath?: string;
  detectedAccounts?: string;
  quickLinkUrl?: string;
  quickLinkTitle?: string;
}>();

const emit = defineEmits<{
  (e: 'confirm'): void;
  (e: 'cancel'): void;
}>();

const visible = ref(false);

const isWechatUpgrade = computed(() => {
  if (props.type === 'wechat_upgrade') return true;
  const combined = `${props.title || ''}\n${props.message || ''}`;
  return (
    combined.includes('升级微信') ||
    (combined.includes('微信') && combined.includes('4.0') && combined.includes('3.9'))
  );
});

const effectiveType = computed(() => {
  if (props.type && props.type !== 'wechat_upgrade') return props.type;
  if ((props.title || '').includes('失败') || (props.title || '').includes('错误')) return 'error';
  if (props.showCancel) return 'warning';
  return 'info';
});

const parsedWechatInfo = computed(() => {
  if (props.detectedPath || props.detectedAccounts) {
    return {
      dir: props.detectedPath || '',
      accounts: props.detectedAccounts || '',
    };
  }
  const lines = String(props.message || '')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  let dir = '';
  let accounts = '';
  for (const line of lines) {
    if (/^[A-Za-z]:\\|^\/|WeChat Files/i.test(line) && !line.includes('常见位置')) {
      dir = line;
    } else if (line.startsWith('检测到') && line.includes('账号')) {
      accounts = line;
    }
  }
  return { dir, accounts };
});

async function openExternal(url: string) {
  try {
    if ((window as any)?.pywebview?.api?.open_external_url) {
      const res = await api.open_external_url(url);
      if (res?.ok) return;
    }
  } catch {
    // ignore and fallback to window.open
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

const open = () => {
  visible.value = true;
};

const handleConfirm = () => {
  visible.value = false;
  emit('confirm');
};

const handleCancel = () => {
  visible.value = false;
  emit('cancel');
};

const handleWrapperClick = () => {
  if (props.showCancel) {
    handleCancel();
  } else {
    handleConfirm();
  }
};

defineExpose({
  open,
  close: () => {
    visible.value = false;
  },
});
</script>

<style scoped>
.ct-dialog-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(15, 23, 42, 0.46);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 99999;
}

.ct-dialog {
  background: var(--ct-bg-card, #ffffff);
  border: 1px solid var(--ct-border, #e2e8f0);
  border-radius: 16px;
  box-shadow:
    0 24px 60px rgba(15, 23, 42, 0.24),
    0 4px 16px rgba(15, 23, 42, 0.06);
  width: min(440px, calc(100vw - 32px));
  max-height: 84vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--ct-text-primary, #0f172a);
  animation: ct-dialog-zoom 0.18s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.ct-dialog.is-wechat-upgrade {
  width: min(480px, calc(100vw - 32px));
}

/* 顶栏 */
.ct-dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 22px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.ct-dialog-head-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.ct-dialog-icon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ct-dialog-icon.info {
  background: linear-gradient(135deg, #f3e8ff, #ede9fe);
  color: #7c4dff;
  border: 1px solid rgba(124, 77, 255, 0.18);
}

.ct-dialog-icon.warning {
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  color: #d97706;
  border: 1px solid rgba(245, 158, 11, 0.24);
}

.ct-dialog-icon.error {
  background: linear-gradient(135deg, #fee2e2, #fecaca);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.22);
}

.ct-dialog-icon.wechat {
  background: linear-gradient(135deg, #dcfce7, #bbf7d0);
  color: #07c160;
  border: 1px solid rgba(7, 193, 96, 0.25);
  box-shadow: 0 2px 8px rgba(7, 193, 96, 0.12);
}

.ct-dialog-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.ct-dialog-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.ct-dialog-sub {
  font-size: 12px;
  color: #64748b;
}

.ct-dialog-close {
  width: 30px !important;
  height: 30px !important;
  padding: 0 !important;
  border-radius: 8px !important;
  border: 1px solid #e2e8f0 !important;
  background: #f8fafc !important;
  color: #64748b !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.ct-dialog-close:hover {
  background: #fef2f2 !important;
  color: #ef4444 !important;
  border-color: #fecaca !important;
}

/* 正文区 */
.ct-dialog-body {
  padding: 18px 22px;
  font-size: 13.5px;
  color: #475569;
  overflow-y: auto;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.ct-dialog-body.wechat-upgrade-body {
  white-space: normal;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 22px 18px;
}

/* 检测到的旧版目录卡片 */
.wu-path-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  padding: 10px 13px;
}

.wu-path-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.wu-path-badge {
  font-size: 11.5px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: #fef3c7;
  color: #b45309;
}

.wu-account-tag {
  font-size: 11.5px;
  color: #64748b;
}

.wu-path-code {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
  color: #1e293b;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  padding: 6px 10px;
  word-break: break-all;
}

/* 说明与步骤 */
.wu-reason-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.wu-reason-text {
  margin: 0;
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
}

.wu-reason-text strong {
  color: #0f172a;
}

.wu-steps {
  display: flex;
  flex-direction: column;
  gap: 7px;
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 12px;
  border: 1px dashed #cbd5e1;
}

.wu-step-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
  color: #334155;
  line-height: 1.5;
}

.wu-step-num {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

/* 官方快速链接卡片：[微信，是一个生活方式](https://weixin.qq.com/) */
.wu-quick-link-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
  border: 1px solid #86efac;
  text-decoration: none !important;
  cursor: pointer;
  transition: all 0.18s ease;
}

.wu-quick-link-card:hover {
  border-color: #22c55e;
  box-shadow: 0 6px 16px rgba(7, 193, 96, 0.14);
  transform: translateY(-1px);
}

.wu-link-logo {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: #07c160;
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 3px 8px rgba(7, 193, 96, 0.25);
}

.wu-link-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.wu-link-title-row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.wu-link-title {
  font-size: 14px;
  font-weight: 700;
  color: #065f46;
}

.wu-link-official {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(7, 193, 96, 0.16);
  color: #047857;
}

.wu-link-url {
  font-size: 11.5px;
  color: #059669;
  font-family: 'JetBrains Mono', Consolas, monospace;
}

.wu-link-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border-radius: 8px;
  background: #ffffff;
  color: #059669;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid rgba(7, 193, 96, 0.28);
  flex-shrink: 0;
  white-space: nowrap;
}

/* 底栏按钮 */
.ct-dialog-footer {
  padding: 14px 22px 18px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  background: #ffffff;
}

.ct-dlg-btn {
  height: 36px !important;
  padding: 0 16px !important;
  border-radius: 9px !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 6px !important;
  cursor: pointer;
  white-space: nowrap !important;
  transition: all 0.16s ease;
}

.ct-dlg-btn:active {
  transform: scale(0.98);
}

.ct-dlg-btn.secondary {
  background: #ffffff !important;
  color: #475569 !important;
  border: 1px solid #cbd5e1 !important;
}

.ct-dlg-btn.secondary:hover {
  background: #f8fafc !important;
  color: #0f172a !important;
  border-color: #94a3b8 !important;
}

.ct-dlg-btn.primary {
  background: #7c4dff !important;
  color: #ffffff !important;
  border: 1px solid #6d28d9 !important;
  box-shadow: 0 4px 12px rgba(124, 77, 255, 0.24) !important;
}

.ct-dlg-btn.primary:hover {
  background: #6d28d9 !important;
}

.ct-dlg-btn.primary.error {
  background: #ef4444 !important;
  border-color: #dc2626 !important;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.24) !important;
}

.ct-dlg-btn.wechat-primary {
  background: #07c160 !important;
  color: #ffffff !important;
  border: 1px solid #059669 !important;
  box-shadow: 0 4px 12px rgba(7, 193, 96, 0.25) !important;
}

.ct-dlg-btn.wechat-primary:hover {
  background: #06ad56 !important;
}

.ct-dialog-fade-enter-active,
.ct-dialog-fade-leave-active {
  transition: opacity 0.18s ease;
}

.ct-dialog-fade-enter-from,
.ct-dialog-fade-leave-to {
  opacity: 0;
}

@keyframes ct-dialog-zoom {
  0% {
    transform: translateY(8px) scale(0.97);
    opacity: 0;
  }
  100% {
    transform: translateY(0) scale(1);
    opacity: 1;
  }
}
</style>
