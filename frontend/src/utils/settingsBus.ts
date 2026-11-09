/**
 * 打开设置抽屉并定位到指定组（account 数据与账号 / model 模型与计算 / memory 联系人记忆 / misc 杂项维护）。
 * App.vue 监听 chrono:open-settings；空态 CTA、监听卡等入口统一走这里。
 */
export function openSettingsTab(tab = '') {
  window.dispatchEvent(new CustomEvent('chrono:open-settings', { detail: { tab } }))
}
