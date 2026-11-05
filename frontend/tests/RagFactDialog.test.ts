// RagFactDialog 组件级自动 UI 测试：演变链（supersede 时间线）展开、
// 敏感遮蔽、入口徽标显隐与懒加载缓存。Bridge 走 window.pywebview.api
// 真实代理链（bridgeReady 直通），mock 只替换后端返回。
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RagFactDialog from '@/components/settings/RagFactDialog.vue'

function factPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 11,
    subject: 'contact',
    kind: 'health',
    content: '对方提到：对虾过敏',
    as_of: 1789900000,
    confidence: 0.62,
    sensitive: false,
    enabled: true,
    user_action: null,
    evidence_messages: [],
    evidence_excerpts: [],
    supersedes_fact_id: null,
    ...overrides,
  }
}

const evolutionNodes = [
  {
    id: 3,
    subject: 'contact',
    kind: 'health',
    content: '对方提到：对虾不过敏了',
    sensitive: false,
    status: 'active',
    as_of: 1789900000,
    confidence: 0.8,
    updated_at: 1789900600,
    is_current: true,
  },
  {
    id: 1,
    subject: 'contact',
    kind: 'health',
    content: '对方提到：对虾过敏',
    sensitive: false,
    status: 'superseded',
    as_of: 1789800000,
    confidence: 0.6,
    updated_at: 1789800600,
    is_current: false,
  },
]

let evolutionCalls = 0

function installBridge(facts: Array<Record<string, unknown>>) {
  evolutionCalls = 0
  ;(window as unknown as Record<string, unknown>).pywebview = {
    api: {
      get_contact_facts: vi.fn(async () => ({
        ok: true,
        conversation_id: 1,
        resolved_account_wxid: 'wxid_a',
        contact_avatar: '',
        user_avatar: '',
        raw_fact_count: facts.length,
        fact_count: facts.length,
        enabled_fact_count: facts.length,
        selected_fact_count: facts.length,
        offset: 0,
        limit: 50,
        total: facts.length,
        disabled_count: 0,
        document_count: 1,
        kinds: [],
        facts,
      })),
      get_fact_evolution: vi.fn(async () => {
        evolutionCalls += 1
        return { ok: true, fact_id: 11, conversation_id: 1, nodes: evolutionNodes }
      }),
      get_current_user_profile: vi.fn(async () => ({ ok: false })),
    },
  }
}

function mountDialog() {
  return mount(RagFactDialog, {
    props: {
      visible: true,
      conversationId: 1,
      displayName: '小王',
      accountWxid: 'wxid_a',
    },
    // Teleport 弹窗原地渲染，wrapper.find 可直接命中
    global: { stubs: { teleport: true } },
  })
}

beforeEach(() => {
  vi.resetAllMocks()
})

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).pywebview
})

describe('RagFactDialog 演变链', () => {
  test('无历史事实不渲染演变入口', async () => {
    installBridge([factPayload({ supersedes_fact_id: null })])
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.find('.rfd-item').exists()).toBe(true)
    expect(wrapper.find('.rfd-evo-toggle').exists()).toBe(false)
  })

  test('有历史事实显示入口，展开渲染旧→新时间线并只请求一次', async () => {
    installBridge([factPayload({ supersedes_fact_id: 3 })])
    const wrapper = mountDialog()
    await flushPromises()

    const toggle = wrapper.find('.rfd-evo-toggle')
    expect(toggle.exists()).toBe(true)
    expect(wrapper.find('.rfd-evo-list').exists()).toBe(false)

    await toggle.trigger('click')
    await flushPromises()
    expect(evolutionCalls).toBe(1)

    const nodes = wrapper.findAll('.rfd-evo-node')
    expect(nodes.length).toBe(2)
    // 旧版「已被取代」灰化、当前版「当前说法」高亮
    const texts = nodes.map((n) => n.text())
    expect(texts.some((t) => t.includes('已被取代'))).toBe(true)
    expect(texts.some((t) => t.includes('当前说法'))).toBe(true)
    expect(nodes.some((n) => n.classes().includes('current'))).toBe(true)
    // 两条陈述都可见（非敏感节点）
    expect(wrapper.find('.rfd-evo-list').text()).toContain('对虾过敏')
    expect(wrapper.find('.rfd-evo-list').text()).toContain('对虾不过敏了')

    // 收起再展开：链数据已缓存，不再请求后端
    await toggle.trigger('click')
    expect(wrapper.find('.rfd-evo-list').exists()).toBe(false)
    await toggle.trigger('click')
    await flushPromises()
    expect(evolutionCalls).toBe(1)
    expect(wrapper.find('.rfd-evo-list').exists()).toBe(true)
  })

  test('敏感旧版本只显示保护占位，不渲染原文', async () => {
    installBridge([factPayload({ supersedes_fact_id: 3 })])
    ;(window as unknown as { pywebview: { api: Record<string, unknown> } }).pywebview.api
      .get_fact_evolution = vi.fn(async () => ({
      ok: true,
      fact_id: 11,
      conversation_id: 1,
      nodes: [
        ...evolutionNodes.slice(0, 1),
        { ...evolutionNodes[1], content: '对方提到：有心理就诊史', sensitive: true },
      ],
    }))
    const wrapper = mountDialog()
    await flushPromises()

    await wrapper.find('.rfd-evo-toggle').trigger('click')
    await flushPromises()

    const list = wrapper.find('.rfd-evo-list')
    expect(list.text()).toContain('敏感记忆已保护')
    expect(list.text()).not.toContain('心理就诊史')
  })

  test('接口失败时展开显示可重试占位而非终态失效诊断', async () => {
    installBridge([factPayload({ supersedes_fact_id: 3 })])
    ;(window as unknown as { pywebview: { api: Record<string, unknown> } }).pywebview.api
      .get_fact_evolution = vi.fn(async () => ({ ok: false, error: 'fact_not_found' }))
    const wrapper = mountDialog()
    await flushPromises()

    await wrapper.find('.rfd-evo-toggle').trigger('click')
    await flushPromises()

    // 瞬时失败是可重试态：不得渲染成「链已失效」终态（那是空链的语义）
    expect(wrapper.find('.rfd-evo-empty').text()).toContain('拉取失败')
    expect(wrapper.find('.rfd-evo-empty').text()).not.toContain('演变链已失效')
  })
})
