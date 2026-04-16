<template>
  <div class="ct-account-selector" ref="dropdownRef" @click="toggleMenu">
    <!-- Trigger Slot. If empty, provides a default button -->
    <slot name="trigger" :active-account="activeAccount" :is-open="isOpen">
      <button class="default-trigger" :class="{ 'is-open': isOpen }" type="button">
        <CtAvatar
          class="trigger-avatar"
          :src="activeAccount?.avatar"
          :name="activeAccountName"
          :size="30"
        />
        <span class="trigger-copy">
          <span class="trigger-label">{{ activeAccountName }}</span>
          <span v-if="activeAccount?.wxid" class="trigger-meta">{{ activeAccount.wxid }}</span>
        </span>
        <svg class="trigger-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>
    </slot>

    <!-- Popover Menu -->
    <Transition name="ct-popover">
      <div v-if="isOpen" class="ct-popover-menu" @click.stop>
        <div class="popover-header">
          <span class="popover-title">切换账号</span>
        </div>
        <div class="popover-scroll">
          <ul v-if="accounts.length > 0" class="account-list">
            <li 
              v-for="acc in accounts" 
              :key="acc.wxid"
              class="account-item"
              :class="{ 'is-active': acc.wxid === modelValue }"
              @click="selectAccount(acc.wxid)"
            >
              <CtAvatar 
                class="account-avatar"
                :src="acc.avatar"
                :name="getAccountName(acc)"
                :size="28"
              />
              <div class="account-info">
                <div class="account-name">{{ getAccountName(acc) }}</div>
                <div class="account-wxid">{{ acc.wxid }}</div>
              </div>
              <div class="account-check" v-if="acc.wxid === modelValue">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </div>
            </li>
          </ul>
          <div v-else class="empty-state">
            暂无可用账号
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import CtAvatar from '@/components/base/CtAvatar.vue'
import { getWechatAccountDisplayName } from '@/utils/wechatAccounts'

const props = defineProps<{
  modelValue: string
  accounts: any[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', value: string): void
}>()

const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)

const activeAccount = computed(() => {
  return props.accounts.find(a => a.wxid === props.modelValue) || null
})

const activeAccountName = computed(() => getWechatAccountDisplayName(activeAccount.value))

function getAccountName(account: any) {
  return getWechatAccountDisplayName(account)
}

function toggleMenu() {
  isOpen.value = !isOpen.value
}

function selectAccount(wxid: string) {
  if (wxid !== props.modelValue) {
    emit('update:modelValue', wxid)
    emit('change', wxid)
  }
  isOpen.value = false
}

function onClickOutside(event: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
})
</script>

<style scoped>
.ct-account-selector {
  position: relative;
  display: inline-block;
}

.default-trigger {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 220px;
  padding: 10px 14px;
  background: var(--ct-bg-elevated, #fff);
  border: 1px solid var(--ct-border-color, #e2e8f0);
  border-radius: 14px;
  color: var(--ct-text-primary, #111827);
  font-size: var(--ct-text-sm, 14px);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--ct-transition-fast, 0.2s);
}

.default-trigger:hover {
  background: var(--ct-bg-hover, #f8fafc);
  border-color: var(--ct-border-hover-color, #cbd5e1);
}

.default-trigger.is-open {
  box-shadow: 0 0 0 2px rgba(168, 85, 247, 0.15);
  border-color: var(--ct-color-primary, #a855f7);
}

.trigger-avatar {
  flex-shrink: 0;
}

.trigger-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.trigger-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  font-size: 13px;
  font-weight: 700;
}

.trigger-meta {
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
  color: var(--ct-text-tertiary, #94a3b8);
  font-family: var(--ct-font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace);
}

.trigger-arrow {
  width: 16px;
  height: 16px;
  opacity: 0.6;
  transition: transform var(--ct-transition-fast, 0.2s);
}

.default-trigger.is-open .trigger-arrow {
  transform: rotate(180deg);
}

.ct-popover-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 260px;
  background: var(--ct-bg-elevated, #ffffff);
  backdrop-filter: blur(12px);
  border: 1px solid var(--ct-border-color, #e2e8f0);
  border-radius: var(--ct-radius-lg, 12px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.1), 0 2px 6px rgba(0, 0, 0, 0.04);
  z-index: 9999;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

@media (prefers-color-scheme: dark) {
  .ct-popover-menu {
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.3), 0 2px 6px rgba(0, 0, 0, 0.1);
  }
}

.popover-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--ct-border-color, #e2e8f0);
  background: var(--ct-bg-tertiary, #f8fafc);
}

.popover-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--ct-text-secondary, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.popover-scroll {
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
}

.account-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.account-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--ct-radius-md, 8px);
  cursor: pointer;
  transition: all var(--ct-transition-fast, 0.2s);
}

.account-item:hover {
  background: var(--ct-bg-hover, #f1f5f9);
}

.account-item.is-active {
  background: var(--ct-color-primary-light, rgba(168, 85, 247, 0.1));
  color: var(--ct-color-primary, #a855f7);
}

.account-item.is-active .account-wxid,
.account-item.is-active .account-name {
  color: var(--ct-color-primary, #a855f7);
}

.account-item.is-active .account-name {
  opacity: 0.9;
}

.account-item.is-active .account-wxid {
  opacity: 0.7;
}

.account-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.account-name {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--ct-text-primary, #111827);
}

.account-wxid {
  font-size: 11px;
  color: var(--ct-text-tertiary, #94a3b8);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.account-check {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ct-color-primary, #a855f7);
}

.empty-state {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--ct-text-secondary, #64748b);
}

@media (max-width: 768px) {
  .default-trigger {
    min-width: 0;
    width: 100%;
  }
}

/* Animations */
.ct-popover-enter-active,
.ct-popover-leave-active {
  transition: opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1), transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  transform-origin: top right;
}

.ct-popover-enter-from,
.ct-popover-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.96);
}
</style>
