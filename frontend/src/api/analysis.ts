/**
 * 特征提取相关API调用
 *
 * 提供会话切分、响应时间计算、主动性统计、字数统计等功能的API接口
 */

import { api } from './bridge'

// ============================================================================
// 类型定义
// ============================================================================

/**
 * 会话数据
 */
export interface Session {
  id?: number
  conversation_id: number
  start_time: number
  end_time: number
  message_count: number
  initiator: 'user' | 'other'
  source: string
  created_at: number
}

/**
 * 响应时间统计
 */
export interface ResponseTimeStats {
  count: number
  avg: number | null
  median: number | null
  min: number | null
  max: number | null
  stddev: number | null
  abnormal_count: number
}

/**
 * 主动性统计
 */
export interface InitiativeStats {
  total_sessions: number
  user_initiated_sessions: number
  other_initiated_sessions: number
  initiative_rate: number
  interpretation: string
}

/**
 * 字数统计
 */
export interface WordCounts {
  overall: {
    user_char_count: number
    other_char_count: number
    char_ratio: number
    interpretation: string
  }
  by_session: Array<{
    conversation_id: number
    session_id: number | null
    user_char_count: number
    other_char_count: number
    char_ratio: number
    last_updated: number
  }>
}

/**
 * 特征提取结果
 */
export interface FeatureExtractionResult {
  task_id: string
  sessions: Session[]
  response_time_stats: ResponseTimeStats
  initiative_stats: InitiativeStats
  word_counts: WordCounts
}

/**
 * 任务进度
 */
export interface TaskProgress {
  status: 'in_progress' | 'completed' | 'failed' | 'not_found'
  progress: number
  current_step: string
  message: string
}

// ============================================================================
// API函数
// ============================================================================

/**
 * 执行完整的特征提取流程
 *
 * @param conversation_id - 对话ID
 * @param config - 可选配置参数
 * @returns 特征提取结果（包含task_id）
 */
export async function extract_features(
  conversation_id: number,
  config?: Record<string, any>
): Promise<FeatureExtractionResult> {
  try {
    const result = await api.extract_features(conversation_id, config)
    if (result.success === false) {
      throw new Error(result.error || '特征提取失败')
    }
    return result.data
  } catch (error) {
    console.error('[extract_features] API调用失败:', error)
    throw error
  }
}

/**
 * 查询任务进度
 *
 * @param task_id - 任务ID
 * @returns 任务进度信息
 */
export async function get_extraction_progress(task_id: string): Promise<TaskProgress> {
  try {
    const result = await api.get_extraction_progress(task_id)
    if (result.success === false) {
      throw new Error(result.error || '查询任务进度失败')
    }
    return result.data
  } catch (error) {
    console.error('[get_extraction_progress] API调用失败:', error)
    throw error
  }
}

/**
 * 获取会话列表
 *
 * @param conversation_id - 对话ID
 * @param limit - 每页数量，默认50
 * @param offset - 偏移量，默认0
 * @returns 会话列表
 */
export async function get_sessions(
  conversation_id: number,
  limit: number = 50,
  offset: number = 0
): Promise<Session[]> {
  try {
    const result = await api.get_sessions(conversation_id, limit, offset)
    if (result.success === false) {
      throw new Error(result.error || '获取会话列表失败')
    }
    return result.data || []
  } catch (error) {
    console.error('[get_sessions] API调用失败:', error)
    throw error
  }
}

/**
 * 获取响应时间统计
 *
 * @param conversation_id - 对话ID
 * @returns 响应时间统计数据
 */
export async function get_response_time_stats(conversation_id: number): Promise<ResponseTimeStats> {
  try {
    const result = await api.get_response_times(conversation_id)
    if (result.success === false) {
      throw new Error(result.error || '获取响应时间统计失败')
    }
    return result.data
  } catch (error) {
    console.error('[get_response_time_stats] API调用失败:', error)
    throw error
  }
}

/**
 * 获取主动性统计
 *
 * @param conversation_id - 对话ID
 * @returns 主动性统计数据
 */
export async function get_initiative_stats(conversation_id: number): Promise<InitiativeStats> {
  try {
    const result = await api.get_initiative_stats(conversation_id)
    if (result.success === false) {
      throw new Error(result.error || '获取主动性统计失败')
    }
    return result.data
  } catch (error) {
    console.error('[get_initiative_stats] API调用失败:', error)
    throw error
  }
}

/**
 * 获取字数统计
 *
 * @param conversation_id - 对话ID
 * @param by_session - 是否按会话统计，默认false
 * @returns 字数统计数据
 */
export async function get_word_counts(
  conversation_id: number,
  by_session: boolean = false
): Promise<WordCounts> {
  try {
    const result = await api.get_word_counts(conversation_id, by_session)
    if (result.success === false) {
      throw new Error(result.error || '获取字数统计失败')
    }
    return result.data
  } catch (error) {
    console.error('[get_word_counts] API调用失败:', error)
    throw error
  }
}

/**
 * 重新分析对话（删除旧数据+重新提取特征）
 *
 * @param conversation_id - 对话ID
 * @returns 特征提取结果
 */
export async function reanalyze(conversation_id: number): Promise<FeatureExtractionResult> {
  try {
    const result = await api.reanalyze(conversation_id)
    if (result.success === false) {
      throw new Error(result.error || '重新分析失败')
    }
    return result.data
  } catch (error) {
    console.error('[reanalyze] API调用失败:', error)
    throw error
  }
}

// ============================================================================
// 辅助函数
// ============================================================================

/**
 * 格式化时间戳为可读时间
 *
 * @param timestamp - Unix时间戳（秒）
 * @returns 格式化的时间字符串
 */
export function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp * 1000)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

/**
 * 计算会话时长（秒）
 *
 * @param start_time - 开始时间戳
 * @param end_time - 结束时间戳
 * @returns 会话时长描述
 */
export function formatSessionDuration(start_time: number, end_time: number): string {
  const duration_seconds = end_time - start_time
  const hours = Math.floor(duration_seconds / 3600)
  const minutes = Math.floor((duration_seconds % 3600) / 60)

  if (hours > 0) {
    return `${hours}小时${minutes}分钟`
  } else if (minutes > 0) {
    return `${minutes}分钟`
  } else {
    return `${duration_seconds}秒`
  }
}

/**
 * 格式化响应时间（秒转分钟/秒）
 *
 * @param seconds - 响应时间（秒）
 * @returns 格式化的时间字符串
 */
export function formatResponseTime(seconds: number | null): string {
  if (seconds === null) return '无数据'

  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hours > 0) {
    return `${hours}小时${minutes}分钟`
  } else if (minutes > 0) {
    return `${minutes}分钟${secs}秒`
  } else {
    return `${secs}秒`
  }
}

/**
 * 转换主动率为百分比
 *
 * @param rate - 主动率（0-1）
 * @returns 百分比字符串
 */
export function formatInitiativeRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}
