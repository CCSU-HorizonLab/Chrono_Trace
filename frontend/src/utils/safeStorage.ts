/**
 * WebStorage 安全读写。
 *
 * 个别内嵌 WebView（如 WebKitGTK）的 localStorage/sessionStorage 为 null，
 * 直接访问会抛 TypeError 使组件挂载失败。统一走本工具降级——读失败返回
 * null、写/删失败静默跳过，业务位点不再各自手抄 try/catch。
 */

export function safeGetItem(key: string, storage: Storage = window.localStorage): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

export function safeSetItem(key: string, value: string, storage: Storage = window.localStorage): void {
  try {
    storage.setItem(key, value)
  } catch {
    // storage 不可用（如 WebKitGTK）：静默跳过，不影响业务流程
  }
}

export function safeRemoveItem(key: string, storage: Storage = window.localStorage): void {
  try {
    storage.removeItem(key)
  } catch {
    // storage 不可用：静默跳过
  }
}
