/* 图表主题模块——全库图表色彩的唯一来源。
   色板 = theme.css --ct-chart-1..5（墨紫/珊瑚/青绿/琥珀/洋红，dataviz 六检过：
   CVD ΔE 8.2、normal 15.8）。令牌直读（与 DimensionRadar 蓝本一致），
   不缓存——图表非每帧渲染，getComputedStyle 开销可忽略。 */
import * as echarts from 'echarts'

const cssVar = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** 数据色板（图表分类色，固定顺序分配，不循环） */
export function chartPalette(): string[] {
  const palette = [1, 2, 3, 4, 5]
    .map((i) => cssVar(`--ct-chart-${i}`))
    .filter(Boolean)
  return palette.length ? palette : ['#5A4BC4', '#E8656F', '#2FA39A', '#E0A458', '#C455D0']
}

/** 好感度/覆盖率类分数 → 语义色（青绿良好 / 墨紫中段 / 琥珀偏低 / 珊瑚危险） */
export function getScoreColor(score: number): string {
  if (score >= 80) return cssVar('--ct-color-success') || '#2FA39A'
  if (score >= 55) return cssVar('--ct-color-primary') || '#5A4BC4'
  if (score >= 35) return cssVar('--ct-color-warning') || '#E0A458'
  return cssVar('--ct-color-error') || '#E8656F'
}

/** 墨紫 5 步顺序色带（活跃日历/热力，白底 → 墨紫，lightness 单调） */
export const HEAT_RAMP = ['#F1EEFA', '#D5CFF2', '#ABA0E4', '#7E6BD6', '#5A4BC4']

/** 轴系底座：发丝线网格 + 墨字 + 白卡 tooltip（浅色卡面，替代深色驾驶舱） */
export function chronoAxisBase(): Record<string, unknown> {
  const border = cssVar('--ct-border-color') || '#E9E5DF'
  const textTertiary = cssVar('--ct-text-tertiary') || '#9B95A5'
  const textPrimary = cssVar('--ct-text-primary') || '#1B1924'
  const bgCard = cssVar('--ct-bg-card') || '#FFFFFF'
  return {
    grid: { top: 16, right: 12, bottom: 24, left: 34, containLabel: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: bgCard,
      borderColor: border,
      textStyle: { color: textPrimary, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      axisLabel: { fontSize: 10, color: textTertiary },
      axisLine: { lineStyle: { color: border } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 10, color: textTertiary },
      splitLine: { lineStyle: { color: border, type: 'dashed' } },
      axisLine: { show: false },
    },
  }
}

/* chrono 主题：init(el, 'chrono') 时提供默认 color 序列与文字色 */
let themeRegistered = false
export function registerChronoTheme() {
  if (themeRegistered) return
  themeRegistered = true
  echarts.registerTheme('chrono', {
    color: chartPalette(),
    backgroundColor: 'transparent',
    textStyle: {
      color: cssVar('--ct-text-secondary') || '#5A5566',
      fontFamily:
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei UI', 'Noto Sans CJK SC', sans-serif",
    },
  })
}

registerChronoTheme()
