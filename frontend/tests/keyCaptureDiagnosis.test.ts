// 密钥提取失败诊断映射契约：后端密钥提取链路（services/wechat/keys/* 与
// webview/api/key_capture.py）真实发出的每个 code 都必须有诊断条目——
// 后端新增 code 而前端未补「发生了什么 + 该做什么」时，此用例红。
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  KEY_CAPTURE_DIAGNOSIS,
  diagnoseKeyCapture,
  type KeyCaptureDiagnosis,
} from '../src/views/keyCaptureDiagnosis'

// bridge.py 还有大量非密钥域的 code 发出点，不做整文件扫描；
// 密钥相关的桥接层额外项在此登记
const EXTRA_KEY_CAPTURE_CODES = ['legacy_wechat_v3']

// vitest 以 frontend/ 为工作目录，后端源码在仓库根（happy-dom 下
// import.meta.url 是 http 协议，不能用 fileURLToPath）
const KEYS_DIR = resolve(process.cwd(), '../backend/app/services/wechat/keys')
const KEY_CAPTURE_API = resolve(process.cwd(), '../backend/app/webview/api/key_capture.py')

/** 扫源码收集 `"code": "xxx"` 字面量（变量透传与 docstring 不会误命中） */
function collectEmittedCodes(): Set<string> {
  const files = readdirSync(KEYS_DIR)
    .filter((name) => name.endsWith('.py'))
    .map((name) => join(KEYS_DIR, name))
  files.push(KEY_CAPTURE_API)

  const codes = new Set<string>()
  const pattern = /["']code["']\s*:\s*["']([a-z_]+)["']/g
  for (const file of files) {
    for (const match of readFileSync(file, 'utf8').matchAll(pattern)) {
      codes.add(match[1]!)
    }
  }
  return codes
}

describe('密钥提取失败诊断映射', () => {
  it('后端发出的每个失败 code 都有诊断条目', () => {
    const emitted = collectEmittedCodes()
    // 扫描本身生效的自证：命中的 code 少于 10 个说明源码布局变了，测试失效
    expect(emitted.size).toBeGreaterThanOrEqual(10)

    for (const code of [...emitted, ...EXTRA_KEY_CAPTURE_CODES]) {
      expect(
        KEY_CAPTURE_DIAGNOSIS[code],
        `后端 code「${code}」缺少诊断映射`,
      ).toBeTruthy()
    }
  })

  it('每条映射都是非空标题加可执行指引', () => {
    for (const [code, entry] of Object.entries(KEY_CAPTURE_DIAGNOSIS) as Array<[string, KeyCaptureDiagnosis]>) {
      expect(entry.title, `「${code}」title 为空`).toBeTruthy()
      expect(entry.hint, `「${code}」hint 为空`).toBeTruthy()
      expect(entry.hint.length, `「${code}」hint 过短，缺少可执行指引`).toBeGreaterThanOrEqual(10)
    }
  })

  it('空 code 与未知 code 回落 undefined，已知 code 命中且容忍空白', () => {
    expect(diagnoseKeyCapture('')).toBeUndefined()
    expect(diagnoseKeyCapture('   ')).toBeUndefined()
    expect(diagnoseKeyCapture('brand_new_code')).toBeUndefined()
    expect(diagnoseKeyCapture('ptrace_denied')).toBe(KEY_CAPTURE_DIAGNOSIS['ptrace_denied'])
    expect(diagnoseKeyCapture(' ptrace_denied ')).toBe(KEY_CAPTURE_DIAGNOSIS['ptrace_denied'])
  })
})
