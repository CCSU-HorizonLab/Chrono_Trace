type PyWebViewApi = {
  ping: () => Promise<string>
  // 微信数据导入
  get_wechat_paths: () => Promise<any>
  verify_wechat_key: (db_key: string) => Promise<any>
  import_wechat_data: (db_key: string, options?: Record<string, any>) => Promise<any>
  // 通用导入与分析
  ingest_data: (file_path: string, options?: Record<string, any>) => Promise<any>
  get_analysis: (date_range: { from: string; to: string }) => Promise<any>
  generate_suggestion: (intent: string, context: Record<string, any>) => Promise<any>
  get_settings: () => Promise<any>
  set_settings: (payload: Record<string, any>) => Promise<any>
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
