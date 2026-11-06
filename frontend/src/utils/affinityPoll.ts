// 好感度分析轮询分派：把一次 getAffinityProgress 响应映射为轮询循环
// 该做的事（纯函数，供 Analytics 轮询循环与单测共用）。UI 副作用全部
// 留在调用方，这里只回答"这一帧是什么状态、该怎么走"。

export type AffinityPollAction =
    | { kind: 'continue' }                // 非终态：继续轮询
    | { kind: 'progressive' }             // llm_pending：渐进渲染本地四维部分结果
    | { kind: 'complete' }                // completed：落终态并刷新跟随数据
    | { kind: 'cancelled-partial' }       // cancelled 且部分结果已显示：保留不抹 UI
    | { kind: 'failed'; message: string } // failed / cancelled 无部分结果 / 任务失效

export interface AffinityPollLike {
    ok?: boolean
    status?: string
    error?: string
}

export function resolveAffinityPollAction(
    prog: AffinityPollLike | null | undefined,
    progressiveShown: boolean,
): AffinityPollAction {
    // 失效先于 ok 门控分派：not_found（ok:false）落空会导致死轮询
    if (!prog || !prog.ok) {
        return { kind: 'failed', message: prog?.error || '分析任务已失效' }
    }
    switch (prog.status) {
        case 'llm_pending':
            return { kind: 'progressive' }
        case 'completed':
            return { kind: 'complete' }
        case 'cancelled':
            return progressiveShown
                ? { kind: 'cancelled-partial' }
                : { kind: 'failed', message: prog.error || '分析已取消' }
        case 'failed':
            return { kind: 'failed', message: prog.error || '分析失败' }
        default:
            return { kind: 'continue' }
    }
}
