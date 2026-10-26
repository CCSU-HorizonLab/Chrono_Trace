/**
 * activity 分镜共用纯函数：峰值格定位与话术格式化（三模板与方卡共用）。
 * 周几口径与后端一致——周一为第 0 行。
 */
export const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export function gridPeak(
  counts: number[][],
): { weekday: number; hour: number; count: number } | null {
  let best: { weekday: number; hour: number; count: number } | null = null
  counts.forEach((row, weekday) => {
    row.forEach((count, hour) => {
      const current = best
      if (count > 0 && (current === null || count > current.count)) {
        best = { weekday, hour, count }
      }
    })
  })
  return best
}

export function peakSlotText(peak: { weekday: number; hour: number }): string {
  return `${WEEKDAY_LABELS[peak.weekday]} ${peak.hour} 点`
}

export function formatCount(value: number): string {
  return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString('zh-CN')
}

/** 时长话术（秒 → 分钟/小时/天，自动选档） */
export function formatHoursOrDays(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} 分钟`
  const hours = seconds / 3600
  if (hours < 48) return `${hours >= 10 ? Math.round(hours) : hours.toFixed(1)} 小时`
  return `${(hours / 24).toFixed(1)} 天`
}
