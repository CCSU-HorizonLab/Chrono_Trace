/**
 * 问问微信回答的受限 Markdown 渲染。
 *
 * 白名单三件套（加粗 / 列表 / 换行）+ 引用编号上标——LLM 问答回答的
 * 实际形态就这几种，不引入完整 markdown 库（表格/代码块等语法用不上，
 * 库的攻击面反而更大）。先整体 HTML 转义再替换标记：LLM 输出按不可信
 * 输入处理，任何标签原文落屏。
 *
 * [n] 上标：终态回答后端已剥离编号，但流式增量里的 [n] 需要原地渲染
 * （打字机过程中就要像引用的样子），统一走本渲染器即可。
 */

import { escapeHtml } from './escapeHtml'

/** 行内标记：加粗与引用上标（在已转义文本上做，标记字符不含 HTML 语义） */
function renderInline(text: string): string {
  return text
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[(\d+)\]/g, '<sup class="qa-cite-mark" data-idx="$1">$1</sup>')
}

/** 渲染为可 v-html 的 HTML 片段；空输入返回空串（调用方保留占位态） */
export function renderQaAnswer(raw: string): string {
  const lines = escapeHtml(String(raw ?? '')).split(/\n/)
  let html = ''
  let listTag: 'ul' | 'ol' | null = null
  const closeList = () => {
    if (listTag) {
      html += `</${listTag}>`
      listTag = null
    }
  }
  for (const line of lines) {
    const trimmed = line.trim()
    const bullet = trimmed.match(/^[-*]\s+(.+)$/)
    // 有序标记：点号后必须空格（Markdown 规范），顿号后空格可选（中文
    // 习惯「1、苹果」）——零空格的点号会吞掉行首小数/点分日期
    // （「3.5 公斤」「2024.10.1」），它们不是列表
    const ordered = trimmed.match(/^(\d+)(?:[.]\s+|[、]\s*)(.+)$/)
    if (bullet) {
      if (listTag !== 'ul') {
        closeList()
        html += '<ul>'
        listTag = 'ul'
      }
      html += `<li>${renderInline(bullet[1])}</li>`
    } else if (ordered) {
      if (listTag !== 'ol') {
        closeList()
        html += '<ol>'
        listTag = 'ol'
      }
      html += `<li>${renderInline(ordered[2])}</li>`
    } else {
      closeList()
      if (trimmed) html += `<p>${renderInline(trimmed)}</p>`
    }
  }
  closeList()
  return html
}
