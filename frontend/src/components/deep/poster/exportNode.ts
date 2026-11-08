/**
 * 海报/报告共享的 html2canvas 导出链：字体就绪等待 → 零高守卫 →
 * 超长画布自适应缩放 → save_share_image 落盘 → best-effort 复制到剪贴板。
 * PosterStudio 与 ReportStudio 共用（报告 7 幕长图走同一守卫集）。
 */
import html2canvas from 'html2canvas'
import { api } from '@/api/bridge'
import { copyImageToClipboard } from '@/utils/clipboard'

export type ExportNodeResult =
  | { ok: true; file_path: string; copied: boolean }
  | { ok: false; error: string }

export async function exportNodeAsPng(node: HTMLElement, file_name: string): Promise<ExportNodeResult> {
  try {
    // 等捆绑字体就绪再截图——只堵「首次切模板立即导出」烘焙出回退字体的
    // 竞态；老引擎无 document.fonts 时跳过（@font-face 的 block 期已兜底）
    try {
      await document.fonts?.ready
    } catch {
      /* 老引擎跳过 */
    }
    // 零高守卫：模板渲染失败时节点为空，零高画布的 toDataURL 会返回空串
    // data:, 后端只能误报「仅支持 PNG 图像」——在此给出能定位的错误
    const height = Math.round(node.getBoundingClientRect().height)
    if (!height) {
      return { ok: false, error: '海报内容为空，无法导出（请重试或切换模板）' }
    }
    // 超长会话自适应缩放：画布单边过高时部分 WebEngine 后端无法分配画布
    // （toDataURL 得到空串），按高度把 scale 压到 2 以下保住整图
    const MAX_CANVAS_SIDE = 7800
    const scale = Math.min(2, MAX_CANVAS_SIDE / height)
    const canvas = await html2canvas(node, {
      backgroundColor: '#ffffff',
      scale, // 常规 2 倍：720px 长图导出 1440px 宽，方卡 1440×1440
      useCORS: true,
      logging: false,
    })
    const dataUrl = canvas.toDataURL('image/png')
    const result = await api.save_share_image(dataUrl, file_name)
    if (!result?.ok) {
      return { ok: false, error: result?.error || '保存失败' }
    }
    // 导出即复制（best-effort）：成功可直接在聊天框粘贴；QtWebEngine 等
    // 环境不可写图像剪贴板则静默降级，落盘结果不受影响
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    const copied = blob ? await copyImageToClipboard(blob) : false
    return { ok: true, file_path: result.file_path, copied }
  } catch (e: any) {
    return { ok: false, error: e?.message || '图片合成失败' }
  }
}
