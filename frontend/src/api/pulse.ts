import { api } from './bridge'

/** 脉搏页门面指标（指标直白化层：后端聚合，前端只展示不计算） */

export interface PulseTemperature {
    score: number
    /** 分段话术：炽热 / 温热 / 温和 / 转凉 / 冰点 */
    label: string
    /** 较上次（同口径才给，否则 null） */
    delta: number | null
    /** 好感历史折线 [(created_at, overall_score)]，同口径过滤，时间升序 */
    trend_line: [number, number][]
}

export interface PulseInitiative {
    total_sessions: number
    user_initiated: number
    other_initiated: number
    /** 你发起的占比（0-100，发起总数为 0 时 null） */
    me_pct: number | null
}

export interface PulseResponseSide {
    /** 我回 TA 的中位回复时长（分钟） */
    me_to_ta_median_min: number | null
    /** TA 回我的中位回复时长（分钟） */
    ta_to_me_median_min: number | null
    me_count: number
    ta_count: number
}

export interface PulseResponse {
    recent: PulseResponseSide | null
    /** 前 30 天对照窗（趋势感：变快/变慢） */
    prev: PulseResponseSide | null
}

export interface PulseMonthly {
    messages: number
    chars: number
    late_night: number
    late_night_by_me: number
}

export interface PulseWarningItem {
    label: string
    level: string
    note: string
}

export interface PulseWarning {
    level: string
    items: PulseWarningItem[]
}

export interface PulseVerdict {
    text: string
    /** llm = AI 关系评估判读；template = 本地统计句 */
    source: 'llm' | 'template'
}

export interface PulseProfessional {
    /** 完整好感度结果（asdict），供专业视图折叠层复用 */
    result: any
    analysis_stale: boolean
    pending_message_count: number
    absent_reason: string | null
}

export interface PulseOverview {
    ok: boolean
    error?: string
    analyzed: boolean
    verdict: PulseVerdict | null
    temperature: PulseTemperature | null
    initiative: PulseInitiative | null
    response: PulseResponse | null
    monthly: PulseMonthly
    warning: PulseWarning | null
    professional: PulseProfessional
}

/** 拉取脉搏页门面指标聚合（单点聚合，无二次请求） */
export async function getPulseOverview(conversationId: number): Promise<PulseOverview> {
    const res = await api.get_pulse_overview(conversationId)
    if (!res.ok) throw new Error(res.error || '获取脉搏概览失败')
    return res as PulseOverview
}

/** 关系周报（本周一条；后端无则同步落模板版） */
export interface WeeklyReport {
    week_start: string
    verdict: string
    source: 'llm' | 'template'
    snapshot: Record<string, any>
    updated_at: number
}

export interface WeeklyReportRes {
    ok: boolean
    report: WeeklyReport | null
    llm_configured: boolean
}

export async function getWeeklyReport(conversationId: number): Promise<WeeklyReportRes> {
    return await api.get_weekly_report(conversationId)
}

/** 请求把本周周报升级为 LLM 版（后台生成，轮询 getWeeklyReport 直到 source=llm） */
export async function requestWeeklyLlm(conversationId: number): Promise<{ ok: boolean; started: boolean; reason?: string }> {
    return await api.request_weekly_llm(conversationId)
}
