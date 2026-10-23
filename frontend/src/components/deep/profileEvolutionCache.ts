// 画像演变调用/结果缓存（模块级单例）：Analytics 是路由级组件，切到其它
// 页面即整页卸载；一次演变最多 章数×(1+含我) 次 LLM 调用，结果只存组件
// 实例会在重挂后凭空丢失（按钮回到 idle，用户以为白生成了）。在途 promise
// 与成功结果在此保活——切页回来直接恢复显示；双击/重挂接管同一在途调用
// （后端单飞本就拒绝并发，这里不再发起第二路）。C4 起分段按章节边界，
// 键只剩 (会话, 含我) 两维。
import { api } from '@/api/bridge'

type EvolutionEntry = { promise: Promise<any> | null; res: any }

const cache = new Map<string, EvolutionEntry>()
const CACHE_LIMIT = 8

function evolutionKey(conv: number, self: boolean): string {
  return `${conv}|${self ? 1 : 0}`
}

export function getCachedEvolution(conv: number, self: boolean): EvolutionEntry | undefined {
  return cache.get(evolutionKey(conv, self))
}

export function runEvolution(conv: number, self: boolean, force: boolean): Promise<any> {
  const key = evolutionKey(conv, self)
  const entry = cache.get(key) || { promise: null, res: null }
  if (!force && entry.promise) return entry.promise
  let p: Promise<any>
  p = api.generate_profile_evolution(conv, self, force).then(
    (res: any) => {
      // 只缓存成功结果；cancelled/失败不缓存——续跑语义交给后端快照
      if (res?.ok) entry.res = res
      return res
    },
  ).finally(() => {
    if (entry.promise === p) entry.promise = null
  })
  entry.promise = p
  cache.set(key, entry)
  if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value as string)
  return p
}

// 每会话「上次发起生成」的含我标记：结果缓存键含这一维，重挂后若标记回
// 默认 false，含我的结果就在缓存里也查不到。重挂/切会话先回到上次标记，
// restoreFromCache 才能按原键命中直接显示，不必重新生成。
const lastSettings = new Map<number, { self: boolean }>()

export function getLastEvolutionSettings(conv: number): { self: boolean } | undefined {
  return lastSettings.get(conv)
}

export function rememberEvolutionSettings(conv: number, self: boolean): void {
  lastSettings.set(conv, { self })
}
