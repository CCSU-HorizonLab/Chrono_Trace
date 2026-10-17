/** 剪贴板复制（QtWebEngine 嵌入式环境兼容）。 */

export function copyText(text: string): boolean {
  // navigator.clipboard API 在 QtWebEngine 嵌入式浏览器中不可靠（需要安全上下文
  // 且实现可能闪退渲染进程）——沿用 document.execCommand('copy') 传统方案
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    if (!ok) console.warn('[clipboard] 复制失败（execCommand 返回 false）')
    return ok
  } catch (e) {
    console.error('[clipboard] 复制异常:', e)
    return false
  }
}
