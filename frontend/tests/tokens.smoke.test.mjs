/* 设计令牌冒烟测试（node 原生，无依赖）：
   1) src 全量 var(--ct-*) 引用必须有定义（theme.css :root 或组件局部定义）；
   2) theme.css 过渡别名块只减不增（ALIAS_CAP 随各页提交递减，清零后删块）；
   3) theme.css 不得引入外部字体（离线桌面红线）；
   4) 海报群（html2canvas 对 CSS 变量支持不稳）零 var(--ct 引用。 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const themePath = join(srcRoot, 'styles', 'theme.css')
const posterRoot = join(srcRoot, 'components', 'deep', 'poster')

/** 别名存量上限：只减不增；改写存量后手动调低，清零后删块。 */
const ALIAS_CAP = 27

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

test('过渡别名块只减不增', () => {
  const theme = readFileSync(themePath, 'utf8')
  const marker = theme.indexOf('过渡别名块')
  assert.ok(marker >= 0, 'theme.css 应有过渡别名块标记注释')
  const aliasBlock = theme.slice(marker)
  const count = [...aliasBlock.matchAll(/--ct-[a-z0-9-]+\s*:/g)].length
  assert.ok(
    count <= ALIAS_CAP,
    `过渡别名存量 ${count} 超过上限 ${ALIAS_CAP}——存量改写后手动调低 ALIAS_CAP`
  )
})

test('theme.css 不引外部字体', () => {
  const theme = readFileSync(themePath, 'utf8')
  assert.ok(!theme.includes('fonts.googleapis'), '离线桌面不得引入 Google Fonts')
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
