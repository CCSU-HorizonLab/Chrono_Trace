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
} finally {
  await server.close()
}
