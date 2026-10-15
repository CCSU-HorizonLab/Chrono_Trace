/**
 * 跨页面共享的联系人选中状态（联系人洞察 ↔ 实时助手）。
 *
 * 存储 sessionStorage + CustomEvent 广播，与已有的微信账号切换机制
 * （chrono:wechat-account-changed）同模式——不引入 Pinia，保持轻量。
 */

import { safeGetItem, safeRemoveItem, safeSetItem } from './safeStorage'

export interface SharedContact {
  conversationId: number
  displayName: string
  avatar?: string
}

const STORAGE_KEY = 'chrono_selected_contact'
export const CONTACT_CHANGED_EVENT = 'chrono:contact-changed'

export function saveSharedContact(contact: SharedContact | null): void {
  if (contact) {
    safeSetItem(STORAGE_KEY, JSON.stringify(contact), sessionStorage)
  } else {
    safeRemoveItem(STORAGE_KEY, sessionStorage)
  }
  window.dispatchEvent(new CustomEvent(CONTACT_CHANGED_EVENT, { detail: contact }))
}

export function loadSharedContact(): SharedContact | null {
  const raw = safeGetItem(STORAGE_KEY, sessionStorage)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (parsed?.conversationId && parsed?.displayName) return parsed
    return null
  } catch {
    return null
  }
}

export function clearSharedContact(): void {
  saveSharedContact(null)
}
