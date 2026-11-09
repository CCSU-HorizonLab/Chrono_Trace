/**
 * README 界面截图产线：E2E 同源架构（vite dev + 系统 Chrome + mock bridge），
 * 以真实用户路径（导航/锚点/输入/打字机）逐页截取，覆盖写入 docs/images/screenshots/。
 * 数据全虚构（mock-bridge.mjs），与仓库隐私红线一致。
 *
 * 运行：node tests/e2e/capture-readme.mjs（在 frontend/ 下）
 */
import { spawn } from 'node:child_process'
import { chromium } from 'playwright-core'
import { mockBridgeInit } from './mock-bridge.mjs'

const PORT = 5199
const BASE = `http://127.0.0.1:${PORT}`
const OUT = '../docs/images/screenshots' // 相对 frontend/
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// —— 基建：vite（进程组退出，防孤儿占端口）——
const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], {
  stdio: ['ignore', 'ignore', 'ignore'],
  detached: true,
})
const stopVite = () => { try { process.kill(-vite.pid, 'SIGTERM') } catch { try { vite.kill('SIGTERM') } catch {} } }
for (let i = 0; i < 60; i++) {
  await sleep(500)
  try { if ((await fetch(`${BASE}/`, { signal: AbortSignal.timeout(3000) })).ok) break } catch {}
  if (i === 59) { stopVite(); throw new Error('vite dev server 未就绪') }
}

const browser = await chromium.launch({
  executablePath: '/usr/bin/google-chrome',
  headless: true,
  args: ['--disable-dev-shm-usage', '--no-first-run', '--force-color-profile=srgb'],
})

// 视口与既有截图规格一致（1200×780 @1x）
async function newPage() {
  const context = await browser.newContext({ viewport: { width: 1200, height: 780 }, deviceScaleFactor: 1 })
  await context.addInitScript(mockBridgeInit)
  const page = await context.newPage()
  page.on('pageerror', (e) => console.log(`  ⚠ pageerror: ${String(e).slice(0, 160)}`))
  return { page, close: () => context.close() }
}

async function open(path, settle = 1800) {
  const h = await newPage()
  await h.page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' })
  await h.page.waitForSelector('#app *', { timeout: 10000 })
  await sleep(settle) // 等 ECharts 动画与骨架屏退场
  return h
}

async function shot(page, name) {
  await page.screenshot({ path: `${OUT}/${name}.png` })
  console.log(`✓ ${name}.png`)
}

try {
  // —— 脉搏（重设计后新增：首页判读速览）——
  {
    const { page, close } = await open('/#/')
    await page.getByText('专业', { exact: false }).first().click().catch(() => {}) // 展开专业视图，图更丰满
    await sleep(600)
    await shot(page, 'pulse')
    await close()
  }

  // —— 数据页 ——
  {
    const { page, close } = await open('/#/import')
    await shot(page, 'home')
    await close()
  }

  // —— 分析页：关系洞察（默认页签）——
  {
    const { page, close } = await open('/#/analytics')
    await page.getByText('互动投入', { exact: false }).first().waitFor({ timeout: 9000 })
    await sleep(600)
    await shot(page, 'analytics-affinity')
    await close()
  }

  // —— 时光页三连：情绪 / 词云 / 大五（共用一个会话，锚点导航真实路径）——
  {
    const { page, close } = await open('/#/timeline', 2500)
    const anchor = async (label) => {
      await page.locator('.anchor-nav .btn').filter({ hasText: label }).first().click()
      await sleep(1400) // smooth 滚动 + 面板动画
    }
    await anchor('情绪')
    await shot(page, 'deep-emotion')
    await anchor('词云')
    await sleep(800)
    await shot(page, 'deep-wordcloud')
    await anchor('深钻')
    await page.locator('.tl-drill-toggle').click() // 展开大五/画像折叠区
    await sleep(1800)
    await shot(page, 'deep-big5')
    await close()
  }

  // —— 智囊：发出问题，等打字机定格与引用渲染 ——
  {
    const { page, close } = await open('/#/copilot')
    const qa = page.locator('.qa-input')
    await qa.fill('我们最近的关系怎么样？')
    await qa.press('Enter')
    await page.getByText('稳定期', { exact: false }).first().waitFor({ timeout: 12000 })
    await sleep(1000) // 打字机收尾 + 引用条入场
    await shot(page, 'qa-ask')
    await close()
  }

  // —— 画像：滚到底部海报工坊 ——
  {
    const { page, close } = await open('/#/persona', 2500)
    await page.getByText('夜爬吗', { exact: false }).first().waitFor({ timeout: 9000 })
    await page.locator('.poster-studio').scrollIntoViewIfNeeded()
    await sleep(1200) // 海报预览渲染
    await shot(page, 'persona-poster')
    await close()
  }

  // —— 设置 ——
  {
    const { page, close } = await open('/#/settings')
    await page.getByText('演示本地模型', { exact: false }).first().waitFor({ timeout: 9000 })
    await sleep(600)
    await shot(page, 'settings')
    await close()
  }

  console.log(`\n完成：截图写入 ${OUT}/`)
} finally {
  await browser.close().catch(() => {})
  stopVite()
}
