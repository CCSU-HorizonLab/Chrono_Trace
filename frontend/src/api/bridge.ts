type PyWebViewApi = {
  ping: () => Promise<string>
  // 微信数据导入
  get_wechat_paths: () => Promise<any>
  verify_wechat_key: (db_key: string) => Promise<any>
  import_wechat_data: (db_key: string, options?: Record<string, any>) => Promise<any>
  // 通用导入与分析
  ingest_data: (file_path: string, options?: Record<string, any>) => Promise<any>
  get_conversation_list: () => Promise<any>
  get_analysis: (params: { conversation_id: number; from: string; to: string }) => Promise<any>
  generate_suggestion: (intent: string, context: Record<string, any>) => Promise<any>
  get_settings: () => Promise<any>
  set_settings: (payload: Record<string, any>) => Promise<any>
  // 仪表板统计
  get_dashboard_stats: () => Promise<any>
  // 文件/目录选择
  select_file: (title?: string, file_types?: string) => Promise<any>
  select_directory: (title?: string) => Promise<any>
  scan_wechat_directory: (wechat_dir: string) => Promise<any>
  // 实时监听
  start_realtime_monitor: (talker_display_name: string) => Promise<any>
  stop_realtime_monitor: () => Promise<any>
  get_realtime_status: () => Promise<any>
  get_realtime_messages: (batch_id: string, limit?: number) => Promise<any>
  // AI 建议
  get_pending_suggestions: (batch_id: string) => Promise<any>
  dismiss_suggestion: (suggestion_id: number) => Promise<any>
  get_suggestion_config: () => Promise<any>
  set_suggestion_config: (config: any) => Promise<any>
  get_dynamic_quick_prompts: (batch_id: string) => Promise<any>
  // LLM 模型管理
  get_llm_models: () => Promise<any>
  save_llm_model: (model: Record<string, any>) => Promise<any>
  delete_llm_model: (model_id: number) => Promise<any>
  fetch_provider_models: (base_url: string, api_key?: string) => Promise<any>
  // 联系人画像与本体画像
  get_contact_profile: (display_name: string) => Promise<any>
  generate_contact_profile: (display_name: string, budget_level?: string, custom_budget?: number) => Promise<any>
  get_self_profile: (display_name: string) => Promise<any>
  generate_self_profile: (display_name: string, budget_level?: string, custom_budget?: number) => Promise<any>
  // 特征提取
  extract_features: (conversation_id: number, config?: Record<string, any>) => Promise<any>
  get_extraction_progress: (task_id: string) => Promise<any>
  get_sessions: (conversation_id: number, limit?: number, offset?: number) => Promise<any>
  get_session_messages: (session_id: number) => Promise<any>
  get_response_times: (conversation_id: number) => Promise<any>
  get_initiative_stats: (conversation_id: number) => Promise<any>
  get_word_counts: (conversation_id: number, by_session?: boolean) => Promise<any>
  reanalyze: (conversation_id: number) => Promise<any>
  // 悬浮窗管理
  enter_floating_mode: () => Promise<any>
  exit_floating_mode: () => Promise<any>
  get_floating_status: () => Promise<any>
  // 好感度分析进度
  get_affinity_progress: (task_id: string) => Promise<any>
}

function getApi(): PyWebViewApi {
  const api = (window as any)?.pywebview?.api
  if (!api) throw new Error('pywebview.api 未就绪')
  return api as PyWebViewApi
}

export async function bridgeReady(): Promise<void> {
  if ((window as any)?.pywebview?.api) return
  await new Promise<void>((resolve) => {
    window.addEventListener('pywebviewready', () => resolve(), { once: true })
  })
}

export const api: PyWebViewApi = new Proxy({} as any, {
  get(_, prop: string) {
    return async (...args: any[]) => {
      await bridgeReady()
      const a = getApi()
      return (a as any)[prop](...args)
    }
  }
})
