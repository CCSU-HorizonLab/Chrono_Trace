/**
 * 跨页共享的当前选中联系人：脉搏/时光/画像/智囊/分析五页贯通选人。
 * 项目无状态管理库，模块级单例 ref 即全局（路由切换会卸载重建视图，
 * 页面不同时存活，无需跨页响应式联动）；sessionStorage 供 F5/热更后恢复。
 * 各页 loadConversations 内「id 不在列表则清空」的守卫保留——换账号/删库时
 * 清位经共享 ref 自然传播到所有页面。
 */
import { ref, watch } from 'vue'
import { safeGetItem, safeSetItem, safeRemoveItem } from './safeStorage'

const KEY = 'chrono_contact_scope'

function restore(): number | null {
  const raw = safeGetItem(KEY, window.sessionStorage)
  const n = raw == null ? NaN : Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
}

export const sharedContactId = ref<number | null>(restore())

// 模块级 watch 常驻：任何页面改选即落 sessionStorage
watch(sharedContactId, (v) => {
  if (v == null) safeRemoveItem(KEY, window.sessionStorage)
  else safeSetItem(KEY, String(v), window.sessionStorage)
})
