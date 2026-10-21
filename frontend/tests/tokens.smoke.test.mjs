/* 设计令牌冒烟测试（node 原生，无依赖）：
   1) src 全量 var(--ct-*) 引用必须有定义（theme.css :root 或组件局部定义）；
   2) 过渡别名已清零（块已删、别名令牌不得再被定义/引用）；
   3) theme.css 不得引入外部字体（离线桌面红线）；
   4) theme.css button 元素选择器只剩中性 reset（元素皮肤退场门禁）；
   5) 海报群（html2canvas 对 CSS 变量支持不稳）零 var(--ct 引用。 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const themePath = join(srcRoot, 'styles', 'theme.css')
const posterRoot = join(srcRoot, 'components', 'deep', 'poster')

/** 已清退的历史别名：不得再被定义或引用（防回潮守门）。 */
const RETIRED_ALIASES = [
  '--ct-color-primary-light', '--ct-bg-primary', '--ct-bg-secondary', '--ct-bg-tertiary',
  '--ct-bg-elevated', '--ct-radius-xl', '--ct-radius-2xl', '--ct-shadow-xl', '--ct-font-display',
  '--ct-bg-1', '--ct-bg-disabled', '--ct-bg-input', '--ct-bg-muted', '--ct-bg-rgb',
  '--ct-bg-surface', '--ct-border', '--ct-border-hover-color', '--ct-border-subtle',
  '--ct-color-danger', '--ct-color-info-muted', '--ct-color-purple-light',
  '--ct-space-4xl', '--ct-text-muted',
]

function walk(dir, exts, out = []) {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, ent.name)
    if (ent.isDirectory()) out.push(...walk(p, exts))
    else if (exts.some((e) => ent.name.endsWith(e))) out.push(p)
  }
  return out
}

const defRe = /(^|[{;\s])(--ct-[a-z0-9-]+)\s*:/g
const refRe = /var\(\s*(--ct-[a-z0-9-]+)/g

const defs = new Set()
const refs = new Map() // 令牌 → 引用文件集合（报错定位用）
for (const file of walk(srcRoot, ['.vue', '.ts', '.css'])) {
  const text = readFileSync(file, 'utf8')
  for (const m of text.matchAll(defRe)) defs.add(m[2])
  for (const m of text.matchAll(refRe)) {
    const rel = relative(srcRoot, file)
    if (!refs.has(m[1])) refs.set(m[1], new Set())
    refs.get(m[1]).add(rel)
  }
}

test('全部 var(--ct-*) 引用都有定义（无幽灵变量）', () => {
  const missing = [...refs.keys()].filter((name) => !defs.has(name)).sort()
  if (missing.length) {
    const detail = missing.map(
      (n) => `  ${n} ← ${[...refs.get(n)].slice(0, 3).join(', ')}`
    ).join('\n')
    assert.fail(`未定义令牌 ${missing.length} 个：\n${detail}`)
  }
})

test('过渡别名已清零（不得回潮）', () => {
  const theme = readFileSync(themePath, 'utf8')
  assert.ok(!theme.includes('过渡别名块'), '别名块已删除，theme.css 不应再有别名块标记')
  const revivedDefs = RETIRED_ALIASES.filter((a) => defs.has(a))
  assert.deepEqual(
    revivedDefs,
    [],
    `别名令牌被重新定义：${revivedDefs.join(', ')}`
  )
  const revivedRefs = RETIRED_ALIASES.filter((a) => refs.has(a))
  assert.deepEqual(
    revivedRefs,
    [],
    `别名令牌被重新引用：${revivedRefs.join(', ')}`
  )
})

test('theme.css 不引外部字体', () => {
  const theme = readFileSync(themePath, 'utf8')
  assert.ok(!theme.includes('fonts.googleapis'), '离线桌面不得引入 Google Fonts')
})

test('theme.css 无 button 元素级皮肤选择器', () => {
  const theme = readFileSync(themePath, 'utf8')
  // 元素皮肤已退场：唯一允许的形态是中性 reset（font/cursor），其余出现即违规
  const okReset = /^button \{\n  font: inherit;\n  cursor: pointer;\n\}/m.test(theme)
  assert.ok(okReset, 'button 元素选择器应只剩中性 reset（font: inherit; cursor: pointer）')
  const occurrences = theme.match(/\bbutton\b/g) || []
  assert.equal(
    occurrences.length,
    1,
    `元素名出现 ${occurrences.length} 处，只允许 reset 一处（伪类/组合器/变体选择器均违规）`
  )
})

test('海报群零 CSS 变量引用', () => {
  const offenders = []
  for (const file of walk(posterRoot, ['.vue', '.ts', '.css'])) {
    if (readFileSync(file, 'utf8').includes('var(--ct')) {
      offenders.push(relative(posterRoot, file))
    }
  }
  assert.deepEqual(offenders, [], 'poster/ 模板不得引用 --ct 变量（html2canvas 约束）')
})
