// 日期工具：统一用本地时区生成 YYYY-MM-DD 日期键。
// 不用 toISOString()（它取 UTC 日期），否则东八区 0:00-8:00 期间日期会落到前一天。
export function toLocalDateKey(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
