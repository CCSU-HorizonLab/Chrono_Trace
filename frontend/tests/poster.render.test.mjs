/* 海报 SSR 渲染冒烟测试：vite ssrLoadModule 编译 SFC + @vue/server-renderer
   真跑 renderToString——模板渲染抛错（裸名绑定/字段名错用等）在此直接红，
   补上 build 与令牌冒烟都抓不住的「渲染层」空白。 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'

const server = await createServer({
  root: new URL('..', import.meta.url).pathname,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
})

try {
  const probe = await server.ssrLoadModule('/tests/posterRenderProbe.ts')
  const { renderFull, renderSparse, SENSITIVE_MARKERS } = probe

  const full = await renderFull()

  test('定向版全量渲染包含各分镜锚点', () => {
    const html = full.intimate
    for (const anchor of ['我们一起写下', '时光机', '我们的默契', '我们的作息', '那些值得记住的话', '我们各自的词', '我们的语言风格', '你们的称号']) {
      assert.ok(html.includes(anchor), `intimate 缺少锚点「${anchor}」`)
    }
    // 定向版在场敏感字段（反衬公开/自我版的脱敏断言）
    for (const marker of SENSITIVE_MARKERS) {
      assert.ok(html.includes(marker), `intimate 应包含「${marker}」`)
    }
  })

  test('公开版全量渲染包含锚点且零敏感串', () => {
    const html = full.publicLong
    for (const anchor of ['数字会说话', '两个人的默契', '两个人的作息', '这段对话的称号']) {
      assert.ok(html.includes(anchor), `public 缺少锚点「${anchor}」`)
    }
    for (const marker of SENSITIVE_MARKERS) {
      assert.ok(!html.includes(marker), `public 泄漏敏感串「${marker}」`)
    }
  })

  test('自我版全量渲染包含锚点且零敏感串', () => {
    const html = full.selfLong
    for (const anchor of ['你写下的', '你的日常痕迹', '你的作息', '你的称号']) {
      assert.ok(html.includes(anchor), `self 缺少锚点「${anchor}」`)
    }
    for (const marker of SENSITIVE_MARKERS) {
      assert.ok(!html.includes(marker), `self 泄漏敏感串「${marker}」`)
    }
  })

  test('三方卡渲染含称号与迷你数字行，二维码仅公开版', () => {
    assert.ok(full.sqPublic.includes('这段对话的称号'), '公开方卡缺称号引导')
    assert.ok(full.sqSelf.includes('你的称号'), '自我方卡缺称号引导')
    assert.ok(full.sqIntimate.includes('你们的称号'), '定向方卡缺称号引导')
    for (const [name, html] of [['sqPublic', full.sqPublic], ['sqSelf', full.sqSelf], ['sqIntimate', full.sqIntimate]]) {
      assert.ok(html.includes('sq-stats'), `${name} 缺迷你数字行`)
      assert.ok(html.includes('哈哈哈哈'), `${name} 缺高频词 chips`)
      assert.ok(html.length > 2500, `${name} 渲染产物异常短（${html.length}）`)
    }
    assert.ok(full.sqPublic.includes('sq-qr'), '公开方卡应有二维码')
    assert.ok(!full.sqSelf.includes('sq-qr'), '自我方卡不应有二维码')
    assert.ok(!full.sqIntimate.includes('sq-qr'), '定向方卡不应有二维码')
  })

  const sparse = await renderSparse()

  test('稀疏 payload（story/activity/quotes/big5 全缺）三模板均降级成图', () => {
    for (const [name, html] of [['intimate', sparse.intimate], ['public', sparse.publicLong], ['self', sparse.selfLong]]) {
      assert.ok(typeof html === 'string' && html.length > 2500, `${name} 稀疏渲染产物异常短（${html?.length}）`)
      assert.ok(html.includes('条消息'), `${name} 稀疏渲染缺少大数字分镜`)
    }
  })

  // ---------------- 年度报告 / 纪念册 ----------------

  const report = await probe.renderReport()
  const { REPORT_SENSITIVE_MARKERS } = probe

  test('年报定向版渲染包含各幕锚点与敏感字段（反衬公开版断言）', () => {
    const html = report.intimate
    for (const anchor of ['我们的', '只有你们懂的梗', '表情包往来', '走过的刻度', '关系温度', '给 测试联系人']) {
      assert.ok(html.includes(anchor), `intimate 报告缺少锚点「${anchor}」`)
    }
    for (const marker of REPORT_SENSITIVE_MARKERS) {
      assert.ok(html.includes(marker), `intimate 报告应包含「${marker}」`)
    }
    assert.ok(html.includes('2021.06 - 2023.11'), 'intimate 封面应印日期段')
    assert.ok(html.length > 2500, `intimate 报告渲染产物异常短（${html.length}）`)
  })

  test('年报公开版（自选窗口）零敏感串：无姓名/温度/日期段/不安全梗', () => {
    const html = report.publicCustom
    for (const anchor of ['有这样一段对话', '纪念册', '只有你们懂的梗', '含个人信息的内容已滤除', '扫码了解时痕']) {
      assert.ok(html.includes(anchor), `public 报告缺少锚点「${anchor}」`)
    }
    for (const marker of REPORT_SENSITIVE_MARKERS) {
      assert.ok(!html.includes(marker), `public 报告泄漏敏感串「${marker}」`)
    }
    // 安全梗保留、不安全梗（public_safe: false）被投影滤除
    assert.ok(html.includes('笑死我了'), 'public 报告应保留安全梗')
    assert.ok(html.includes('小笨蛋'), 'public 报告应保留安全梗')
    // 公开版封面只讲跨度天数，不印日期段
    assert.ok(html.includes('902 天'), 'public 纪念册封面应印「902 天」跨度')
    assert.ok(html.length > 2500, `public 报告渲染产物异常短（${html.length}）`)
  })

  test('年报公开版（年度窗口）封面大字是年份，落款只留生成年份', () => {
    const html = report.publicYear
    assert.ok(html.includes('年度报告'), '年度窗口应判为年度报告')
    assert.ok(html.includes('2025'), '年度报封面大字应为年份 2025')
    // 期间标签分派：自选窗口走「N 天」（见上一用例），年度窗口走年份大字
    // 落款零具体日历日期：只有生成年份，无 YYYY-MM-DD / 月份段
    assert.ok(!/\d{4}-\d{2}-\d{2}/.test(html), 'public 报告落款泄漏完整日期')
    for (const marker of REPORT_SENSITIVE_MARKERS) {
      assert.ok(!html.includes(marker), `public 年度报告泄漏敏感串「${marker}」`)
    }
  })
} finally {
  await server.close()
}
