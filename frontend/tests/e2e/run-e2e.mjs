/**
 * 真实用户 UI 全面自动测试（E2E）：
 * vite dev server + 系统 Chrome（playwright-core 驱动）+ mock bridge 注入。
 * 逐页走真实用户旅程（导航/选人/页签/输入/打字机/降级态），断言用户
 * 可见内容与渲染产物（canvas/文本），收集 pageerror 与未覆盖 mock 方法。
 *
 * 运行：node tests/e2e/run-e2e.mjs（在 frontend/ 下）
 * 截图与报告落 /tmp/chrono-e2e/
 */
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { chromium } from 'playwright-core'
import { mockBridgeInit } from './mock-bridge.mjs'

const PORT = 5199
const BASE = `http://127.0.0.1:${PORT}`
const OUT = '/tmp/chrono-e2e'
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// —— 断言与用例框架 ——
let passed = 0
let failed = 0
const failures = []
function ok(cond, label) {
  if (cond) {
    passed++
  } else {
    failed++
    failures.push(label)
    console.log(`    ✗ ${label}`)
  }
}

async function expectText(page, text, { timeout = 8000, label } = {}) {
  try {
    await page.getByText(text, { exact: false }).first().waitFor({ timeout })
    ok(true, label || `文本可见: ${text}`)
  } catch {
    ok(false, label || `文本可见: ${text}（${timeout}ms 超时）`)
  }
}

async function expectSelector(page, sel, { timeout = 8000, label } = {}) {
  try {
    await page.locator(sel).first().waitFor({ timeout })
    ok(true, label || `元素存在: ${sel}`)
  } catch {
    ok(false, label || `元素存在: ${sel}`)
  }
}

// 通过 FiltersBar 选中联系人：点开 conversation-select 下拉 → 点 dropdown-item
async function pickContact(page, name) {
  await page.locator('.conversation-select').first().click()
  await sleep(300)
  await page.locator('.dropdown-item').filter({ hasText: name }).first().click()
  await sleep(900) // 等各页跟随加载（mock 有 50-80ms 延迟）
}

// —— 用例表 ——
const specs = []

specs.push({
  name: 'nav-主导航',
  url: '/#/',
  run: async (page) => {
    // 批4：分析页解散，导航终态四页
    for (const item of ['脉搏', '时光', '画像', '智囊']) {
      await page.locator('.menu-item', { hasText: item }).click()
      await sleep(600)
      const active = await page.locator('.menu-item.router-link-active, .menu-item.active').first().textContent().catch(() => '')
      ok(active?.trim() === item, `导航切换到「${item}」并激活`)
    }
    const navCount = await page.locator('.ct-menu .menu-item').count()
    ok(navCount === 4, `导航恰四项（实际 ${navCount}）`)
  },
})

specs.push({
  name: 'pulse-脉搏页',
  url: '/#/',
  run: async (page) => {
    await expectText(page, '关系温度', { label: '脉搏-指标卡标题' })
    await expectText(page, '温热', { label: '脉搏-温度档位' })
    await expectText(page, '63', { label: '脉搏-主动天平百分比' })
    await expectText(page, '回应', { label: '脉搏-回应温度卡' })
    await expectText(page, '留意', { label: '脉搏-冷淡预警' })
    await expectText(page, '↓1.2', { label: '脉搏-温度趋势句' })
    // 专业视图折叠层展开（批3：分析工作台并入脉搏专业视图；原分析页断言并入于此）
    const pro = page.getByText('专业', { exact: false }).first()
    if (await pro.count()) {
      await pro.click().catch(() => {})
      await sleep(600)
      await expectText(page, '互动投入', { timeout: 9000, label: '脉搏-专业视图四维卡' })
      await expectText(page, '喜好兼容度', { label: '脉搏-专业视图第四维卡' })
      await expectText(page, '关系整体温热', { label: '脉搏-定性分析文案' })
      // 分析文字原生选择：可拖选复制（Ctrl+C），点击别处取消高亮
      const bubbleSel = await page.evaluate(() => {
        const el = document.querySelector('.analysis-bubble')
        if (!el) return null
        const range = document.createRange()
        range.selectNodeContents(el)
        const sel = window.getSelection()
        sel.removeAllRanges()
        sel.addRange(range)
        return { userSelect: getComputedStyle(el).userSelect, len: sel.toString().length }
      })
      ok(bubbleSel && bubbleSel.userSelect !== 'none' && bubbleSel.len > 0, '脉搏-定性分析文字可选中')
      await page.locator('.qualitative-head h3').click()
      const bubbleCollapsed = await page.evaluate(() => window.getSelection().isCollapsed)
      ok(bubbleCollapsed, '脉搏-点击别处取消文字选区')
      // 互动特征页签（canvas 只有活跃日历一张，其余为 CSS/SVG 图）
      await page.locator('.ct-tabs-capsule .menu-item').filter({ hasText: '互动特征' }).first().click()
      await sleep(600)
      await expectSelector(page, '.h-bar-row', { timeout: 9000, label: '脉搏-响应时间分布条形图' })
      await expectSelector(page, '.feature-calendar-card canvas', { timeout: 9000, label: '脉搏-活跃日历图表' })
    } else {
      ok(false, '脉搏-专业视图入口')
    }
    // 切到无分析的联系人：降级引导
    await pickContact(page, '陈默')
    await sleep(600)
    const body = await page.textContent('body')
    ok(/分析|先做|还没有|去分析/.test(body || ''), '脉搏-无分析联系人降级引导')
    // 群聊
    await pickContact(page, '周末徒步群')
    await sleep(600)
    const body2 = await page.textContent('body')
    ok(body2 !== null && body2.length > 0, '脉搏-群聊不崩溃（页面仍有内容）')
  },
})

specs.push({
  name: 'timeline-时光页',
  url: '/#/timeline',
  run: async (page) => {
    await sleep(1200)
    await expectText(page, '我们的时光', { label: '时光-页头标题' })
    await expectText(page, '初识与熟络', { timeout: 9000, label: '时光-关系章节' })
    await expectText(page, '😂', { timeout: 9000, label: '时光-表情博物馆 Top' })
    await expectText(page, '第 1 章', { timeout: 9000, label: '时光-词云演变章节卡' })
    // 情感覆盖缺口提示条（模型换代清缓存/未分析过的会话 → 就地补算入口）
    await expectSelector(page, '.coverage-bar', { timeout: 9000, label: '时光-情感补算提示条在场' })
    await expectText(page, '情感数据覆盖', { label: '时光-补算覆盖率文案' })
    await expectSelector(page, 'canvas', { timeout: 9000, label: '时光-ECharts canvas 渲染' })
    await page.locator('.menu-item, [role="tab"], button').filter({ hasText: '里程碑' }).first().click().catch(() => {})
    await sleep(700)
    await expectText(page, '条消息', { timeout: 9000, label: '时光-里程碑内容' })
    await expectText(page, '生成年度报告', { label: '时光-报告产线入口' })
    // 群聊工作台（批4：自分析页迁入——发言统计+日报）；页头导出按钮在场
    await expectSelector(page, '.tl-export-btn', { label: '时光-导出聊天记录入口' })
    await pickContact(page, '周末徒步群')
    await sleep(900)
    await expectText(page, '群聊发言统计', { timeout: 9000, label: '时光-群聊统计卡' })
    await expectText(page, '我的发言排名', { label: '时光-群聊排名行' })
    await expectText(page, '老周', { label: '时光-群聊成员表' })
    // 生成日报（mock 同步返回 summary）
    await page.getByRole('button', { name: '生成日报' }).click()
    await expectText(page, '徒步路线', { timeout: 9000, label: '时光-群聊日报内容' })
  },
})

specs.push({
  name: 'persona-画像页',
  url: '/#/persona',
  run: async (page) => {
    await sleep(800)
    await expectText(page, 'TA 的镜像', { label: '画像-左栏标题' })
    await expectText(page, '我的镜像', { label: '画像-右栏标题' })
    await expectText(page, '夜爬吗', { timeout: 9000, label: '画像-专属梗词典' })
    await expectText(page, '分身', { label: '画像-AI 分身入口' })
    // 镜像对照纯 SQL 指标渲染
    await expectText(page, '中位', { label: '画像-镜像对照中位数' })
    // 群聊 → 提示卡指路
    await pickContact(page, '周末徒步群')
    await sleep(600)
    const body = await page.textContent('body')
    ok(/时光|分析/.test(body || ''), '画像-群聊降级提示')
  },
})

specs.push({
  name: 'avatar-分身对话',
  url: '/#/persona/avatar?cid=1',
  run: async (page) => {
    await expectText(page, '不是 林晚 本人', { label: '分身-边界横幅' })
    const input = page.locator('.av-input')
    await input.fill('这周六去夜爬吗？')
    await input.press('Enter')
    // 打字机增量（chrono:avatar-push）→ 气泡定格完整回复
    await expectText(page, '山顶冷', { timeout: 12000, label: '分身-打字机定格回复' })
    await expectText(page, '这周六去夜爬吗', { label: '分身-用户气泡' })
  },
})

specs.push({
  name: 'copilot-智囊页',
  url: '/#/copilot',
  run: async (page) => {
    await sleep(600)
    // 问答：输入 → 打字机 → 引用溯源
    const qa = page.locator('.qa-input')
    await qa.fill('我们最近的关系怎么样？')
    await qa.press('Enter')
    await expectText(page, '稳定期', { timeout: 12000, label: '智囊-问答打字机内容' })
    await expectText(page, '引用溯源', { timeout: 9000, label: '智囊-引用溯源折叠条在场' })
    // 问答回答文字原生可选中（复制按钮已撤，走 Ctrl+C 原生路径）
    const qaSel = await page.evaluate(() => {
      const el = document.querySelector('.qa-md')
      if (!el) return null
      const range = document.createRange()
      range.selectNodeContents(el)
      const sel = window.getSelection()
      sel.removeAllRanges()
      sel.addRange(range)
      return getComputedStyle(el).userSelect !== 'none' && sel.toString().length > 0
    })
    ok(qaSel === true, '智囊-问答回答文字可选中')
    // 陪练页签（分段器按钮）→ 贴 TA 消息 → 生成三温度档
    await page.locator('.copilot-modes .menu-item').filter({ hasText: '陪练' }).first().click()
    await sleep(500)
    const ta = page.locator('.rehearse-input')
    await ta.fill('这周加班有点多，可能来不了')
    await page.getByRole('button', { name: '给我三个方向' }).click()
    await expectText(page, '温和回应', { timeout: 9000, label: '智囊-陪练三温度档' })
    // 陪练草稿文字原生可选中
    const draftSel = await page.evaluate(() => {
      const el = document.querySelector('.rehearse-draft')
      if (!el) return null
      const range = document.createRange()
      range.selectNodeContents(el)
      const sel = window.getSelection()
      sel.removeAllRanges()
      sel.addRange(range)
      return getComputedStyle(el).userSelect !== 'none' && sel.toString().length > 0
    })
    ok(draftSel === true, '智囊-陪练草稿文字可选中')
    // 文字复制按钮全站撤除（原生选择+Ctrl+C 替代）
    const copyBtns = await page.getByRole('button', { name: '复制', exact: true }).count()
    ok(copyBtns === 0, `智囊-无文字复制按钮（实际 ${copyBtns}）`)
    // 群聊 → 陪练/实时置灰（分段器 disabled），问答仍可用
    await page.locator('.copilot-modes .menu-item').filter({ hasText: '问答' }).first().click()
    await pickContact(page, '周末徒步群')
    await sleep(500)
    const grey = await page.locator('.copilot-modes .menu-item[disabled]').count()
    ok(grey >= 2, '智囊-群聊下陪练/实时入口置灰')
    await expectText(page, '问问微信', { label: '智囊-群聊问答仍可用' })
  },
})

specs.push({
  name: 'crosspage-跨页选人同步',
  url: '/#/copilot',
  run: async (page) => {
    await sleep(800)
    // 智囊页选非默认联系人（陈默），切页后各页 FiltersBar 应跟随同一人
    await pickContact(page, '陈默')
    for (const item of ['时光', '画像', '脉搏']) {
      await page.locator('.menu-item', { hasText: item }).click()
      await sleep(900)
      const ph = await page.locator('.select-input').first().getAttribute('placeholder')
      ok(ph?.includes('陈默'), `跨页-${item}页跟随选中人（placeholder=${ph}）`)
    }
  },
})

specs.push({
  name: 'onboarding-首次引导向导',
  url: '/#/',
  beforeInit: 'window.__E2E_EMPTY_DB = true',
  run: async (page) => {
    await expectText(page, '欢迎使用 Chrono Trace', { timeout: 12000, label: '向导-标题' })
    await expectText(page, '标记重要的人', { label: '向导-四步指示' })
    await expectText(page, '确认数据目录', { label: '向导-导入面板在场' })
    await page.getByText('暂时跳过', { exact: false }).first().click()
    await sleep(600)
    ok((await page.locator('.ob-overlay').count()) === 0, '向导-跳过后关闭')
  },
})

specs.push({
  name: 'settings-设置抽屉',
  url: '/#/',
  run: async (page) => {
    // 齿轮入口 → 抽屉四组页签 → 默认组（数据与账号）内嵌导入面板
    await page.locator('.settings-trigger').click()
    await sleep(800)
    await expectText(page, '数据与账号', { timeout: 9000, label: '抽屉-数据与账号组' })
    await expectText(page, '模型与计算', { label: '抽屉-模型与计算组' })
    await expectText(page, '微信数据导入', { timeout: 9000, label: '抽屉-导入面板在场' })
    const body = await page.textContent('body')
    ok(/增量导入|已导入/.test(body || ''), '抽屉-导入完成状态（增量入口在场）')
    // 模型组：LLM 列表渲染
    await page.locator('.sd-tabs button').filter({ hasText: '模型与计算' }).click()
    await sleep(600)
    await expectText(page, '演示本地模型', { timeout: 9000, label: '抽屉-LLM 模型列表' })
    await expectText(page, '联系人记忆', { label: '抽屉-记忆组在场' })
    // 关闭
    await page.locator('.sd-close').click()
    await sleep(400)
    ok((await page.locator('.sd-drawer').count()) === 0, '抽屉-关闭后收起')
  },
})

specs.push({
  name: 'floating-悬浮窗页',
  url: '/#/floating',
  run: async (page) => {
    await sleep(800)
    const body = await page.textContent('body')
    ok((body || '').length > 50, '悬浮窗-独立页渲染不空白')
  },
})

// —— 基建：vite + chrome ——
async function startVite() {
  // vite5 默认绑 [::1]（IPv6），显式 --host 127.0.0.1 防 fetch/Chrome 解析错族；
  // detached+进程组退出：npx 只是包装进程，单 kill(proc.pid) 会留 vite 孤儿占端口
  const proc = spawn('npx', ['vite', '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], {
    cwd: process.cwd(),
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: true,
  })
  proc.stderr.on('data', (d) => process.stderr.write(`[vite] ${d}`))
  const killGroup = () => { try { process.kill(-proc.pid, 'SIGTERM') } catch { try { proc.kill('SIGTERM') } catch {} } }
  for (let i = 0; i < 60; i++) {
    await sleep(500)
    try {
      const res = await fetch(`${BASE}/`, { signal: AbortSignal.timeout(3000) })
      if (res.ok) return { proc, stop: killGroup }
    } catch {}
  }
  killGroup() // 未就绪也不留孤儿进程
  throw new Error('vite dev server 未就绪')
}

async function main() {
  console.log('▶ 启动 vite dev server…')
  const vite = await startVite()
  let browser
  const allPageErrors = []
  const allConsoleErrors = []
  const uncovered = new Set()
  try {
    browser = await chromium.launch({
      executablePath: '/usr/bin/google-chrome',
      headless: true,
      args: ['--disable-dev-shm-usage', '--no-first-run'],
    })
    console.log('▶ Chrome 已启动，开始用例\n')

    for (const spec of specs) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
      if (spec.beforeInit) await context.addInitScript(spec.beforeInit)
      await context.addInitScript(mockBridgeInit)
      const page = await context.newPage()
      const pageErrors = []
      const consoleErrors = []
      page.on('pageerror', (e) => pageErrors.push(String(e)))
      page.on('console', (msg) => {
        if (msg.type() === 'error') consoleErrors.push(msg.text())
        if (msg.text().includes('未覆盖方法: ')) {
          uncovered.add(msg.text().replace(/.*未覆盖方法: /, ''))
        }
      })
      console.log(`▶ ${spec.name}`)
      const before = { p: passed, f: failed }
      try {
        await page.goto(`${BASE}${spec.url}`, { waitUntil: 'domcontentloaded' })
        await page.waitForSelector('#app *', { timeout: 10000 })
        await spec.run(page)
      } catch (e) {
        failed++
        failures.push(`${spec.name}: 用例异常 ${String(e).slice(0, 200)}`)
        console.log(`    ✗ 用例异常: ${String(e).slice(0, 200)}`)
      }
      await page.screenshot({ path: `${OUT}/${spec.name}.png`, fullPage: false }).catch(() => {})
      const specFail = failed - before.f
      console.log(
        `  ${specFail === 0 ? '✓' : '✗'} ${spec.name}（${passed - before.p} 断言通过，${specFail} 失败）` +
          (pageErrors.length ? ` · pageerror×${pageErrors.length}` : ''),
      )
      allPageErrors.push(...pageErrors.map((e) => `[${spec.name}] ${e}`))
      allConsoleErrors.push(...consoleErrors.map((e) => `[${spec.name}] ${e}`))
      await context.close()
    }
  } finally {
    await browser?.close().catch(() => {})
    vite.stop()
  }

  // —— 报告 ——
  const report = {
    total: passed + failed,
    passed,
    failed,
    failures,
    pageErrors: allPageErrors,
    consoleErrors: allConsoleErrors.slice(0, 40),
    uncoveredMockMethods: [...uncovered],
  }
  writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2))
  console.log(`\n════════ E2E 汇总 ════════`)
  console.log(`断言：${passed} 通过 / ${failed} 失败（共 ${passed + failed}）`)
  console.log(`pageerror：${allPageErrors.length} 条`)
  console.log(`未覆盖 mock 方法：${uncovered.size ? [...uncovered].join(', ') : '无'}`)
  if (failures.length) {
    console.log('\n失败明细：')
    for (const f of failures) console.log(`  ✗ ${f}`)
  }
  if (allPageErrors.length) {
    console.log('\npageerror 明细（前 10）：')
    for (const e of allPageErrors.slice(0, 10)) console.log(`  · ${e.slice(0, 220)}`)
  }
  console.log(`\n截图与报告：${OUT}/`)
  process.exit(failed > 0 || allPageErrors.length > 0 ? 1 : 0)
}

main().catch((e) => {
  console.error('E2E 运行失败:', e)
  process.exit(2)
})
