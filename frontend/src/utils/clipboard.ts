/** PNG 图像写入剪贴板（海报导出后免开目录直接在聊天框粘贴）。
 *  图像只有 navigator.clipboard.write 一条路（execCommand 只能复制文本），
 *  QtWebEngine 等嵌入式环境不可用——调用方按 false 降级，落盘结果不受影响。 */
export async function copyImageToClipboard(blob: Blob): Promise<boolean> {
  // QtWebEngine（Linux）不仅图像剪贴板不可用，权限请求还会踩 pywebview
  // qt.py 的枚举 TypeError——异常从 Qt 槽抛穿 C++ 会 qFatal 掉整个进程。
  // 直接按失败降级，不发起请求（落盘结果不受影响）
  if (/QtWebEngine/i.test(navigator.userAgent)) return false
  try {
    if (!navigator.clipboard || typeof ClipboardItem === 'undefined') return false
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
    return true
  } catch (e) {
    console.warn('[clipboard] 图像复制失败:', e)
    return false
  }
}
