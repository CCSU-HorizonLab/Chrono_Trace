import { api } from './bridge'

// Types
export interface SubScore {
    [key: string]: number
}

export interface DimensionScore {
    name: string
    score: number
    weight: number
    weighted_score: number
    interpretation: string
    sub_scores: SubScore
}

export interface AffinityAnalysisResult {
    overall_score: number
    overall_interpretation: string
    emotional_resonance: DimensionScore | null
    chat_positivity: DimensionScore | null
    attitude_tendency: DimensionScore | null
    preference_compatibility: DimensionScore | null
    conversation_id: number
    analysis_timestamp: number
    analysis_duration_ms: number
    task_id: string
    status: 'pending' | 'running' | 'completed' | 'failed'
    progress_percent: number
    current_step: string
    error?: string
}

export interface AffinityConfig {
    weight_emotional_resonance: number
    weight_chat_positivity: number
    weight_attitude_tendency: number
    weight_preference_compatibility: number
    reply_timeliness_threshold_seconds: number
    session_gap_threshold_seconds: number
    preference_keywords: string[]
}

// API Functions

/**
 * Trigger full affinity analysis
 */
export async function analyzeAffinity(
    conversationId: number,
    forceReanalyze: boolean = false,
    configOverrides?: Partial<AffinityConfig>
): Promise<AffinityAnalysisResult> {
    const res = await api.analyze_affinity(conversationId, forceReanalyze, configOverrides)
    if (!res.ok) throw new Error(res.error || 'Analysis failed')
    return res.result
}

/**
 * Get cached affinity analysis results
 */
export async function getAffinityScores(conversationId: number): Promise<AffinityAnalysisResult | null> {
    const res = await api.get_affinity_scores(conversationId)
    if (!res.ok) throw new Error(res.error || 'Failed to get scores')
    return res.result
}

/**
 * Get affinity configuration
 */
export async function getAffinityConfig(conversationId: number): Promise<AffinityConfig> {
    const res = await api.get_affinity_config(conversationId)
    if (!res.ok) throw new Error(res.error || 'Failed to get config')
    return res.config
}

/**
 * Update affinity configuration
 */
export async function updateAffinityConfig(conversationId: number, config: Partial<AffinityConfig>): Promise<AffinityConfig> {
    const res = await api.update_affinity_config(conversationId, config)
    if (!res.ok) throw new Error(res.error || 'Failed to update config')
    return res.config
}

/**
 * Get all keyword categories
 */
export async function getKeywords(): Promise<Record<string, string[]>> {
    const res = await api.get_affinity_keywords()
    if (!res.ok) throw new Error(res.error || 'Failed to get keywords')
    return res.keywords
}

/**
 * Add keywords to a category
 */
export async function addKeywords(category: string, keywords: string[]): Promise<string[]> {
    const res = await api.add_affinity_keywords(category, keywords)
    if (!res.ok) throw new Error(res.error || 'Failed to add keywords')
    return res.keywords
}

/**
 * Remove keywords from a category
 */
export async function removeKeywords(category: string, keywords: string[]): Promise<string[]> {
    const res = await api.remove_affinity_keywords(category, keywords)
    if (!res.ok) throw new Error(res.error || 'Failed to remove keywords')
    return res.keywords
}

/**
 * Get preference keywords for a conversation
 */
export async function getPreferenceKeywords(conversationId: number): Promise<string[]> {
    const res = await api.get_preference_keywords(conversationId)
    if (!res.ok) throw new Error(res.error || 'Failed to get preference keywords')
    return res.keywords
}

/**
 * Update preference keywords for a conversation
 */
export async function updatePreferenceKeywords(conversationId: number, keywords: string[]): Promise<string[]> {
    const res = await api.update_preference_keywords(conversationId, keywords)
    if (!res.ok) throw new Error(res.error || 'Failed to update preference keywords')
    return res.keywords
}
