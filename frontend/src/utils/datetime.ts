// 日期工具：统一用本地时区生成 YYYY-MM-DD 日期键。
// 不用 toISOString()（它取 UTC 日期），否则东八区 0:00-8:00 期间日期会落到前一天。
export function toLocalDateKey(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

// 紧凑区间标签（如「2025.10 ~ 2026.02」）：时光深度各分段卡头共用，
// 取段首/段尾所在本地月份，比逐日区间短一半
export function toCompactRange(fromTsSeconds: number, toTsSeconds: number): string {
  const fmt = (ts: number) => {
    const d = new Date(ts * 1000)
    return `${d.getFullYear()}.${d.getMonth() + 1}`
  }
  return `${fmt(fromTsSeconds)} ~ ${fmt(toTsSeconds)}`
}
