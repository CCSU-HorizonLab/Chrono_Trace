// 好感度分析轮询分派纯函数最小用例：状态映射与 cancelled 双分支
import { describe, expect, test } from 'vitest'
import { resolveAffinityPollAction } from '@/utils/affinityPoll'

describe('resolveAffinityPollAction', () => {
    test('非终态继续轮询', () => {
        expect(resolveAffinityPollAction({ ok: true, status: 'running' }, false))
            .toEqual({ kind: 'continue' })
    })

    test('llm_pending 分派渐进渲染', () => {
        expect(resolveAffinityPollAction({ ok: true, status: 'llm_pending' }, false))
            .toEqual({ kind: 'progressive' })
    })

    test('completed 分派终态', () => {
        expect(resolveAffinityPollAction({ ok: true, status: 'completed' }, true))
            .toEqual({ kind: 'complete' })
    })

    test('cancelled 已渐进显示则保留部分结果', () => {
        expect(resolveAffinityPollAction({ ok: true, status: 'cancelled' }, true))
            .toEqual({ kind: 'cancelled-partial' })
    })

    test('cancelled 未渐进显示按失败拒绝（携带后端原因）', () => {
        expect(resolveAffinityPollAction({ ok: true, status: 'cancelled', error: '分析已被用户停止' }, false))
            .toEqual({ kind: 'failed', message: '分析已被用户停止' })
    })

    test('failed 携带错误信息', () => {
        expect(resolveAffinityPollAction({ ok: true, status: 'failed', error: '模型缺失' }, false))
            .toEqual({ kind: 'failed', message: '模型缺失' })
    })

    test('任务失效（ok:false / not_found）不落死轮询', () => {
        expect(resolveAffinityPollAction({ ok: false, error: '任务不存在' }, false))
            .toEqual({ kind: 'failed', message: '任务不存在' })
        expect(resolveAffinityPollAction(undefined, false))
            .toEqual({ kind: 'failed', message: '分析任务已失效' })
    })
})
