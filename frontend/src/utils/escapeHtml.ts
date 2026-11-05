/**
 * HTML 转义单源：聊天原文/LLM 输出进入 HTML 语境（问答回答渲染、
 * ECharts tooltip 按 HTML 渲染）前一律先过这里——两者都按不可信
 * 输入处理，任何标签原文落屏即注入面。
 */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
