// 我/TA 实体序列色——全前端单一色源：大五演变/静态大五、情绪曲线、海报 sparkline、
// 时光深度工具条图例都从这里取（BigFivePanel/BigFiveRadar 的 CSS 内联同值，
// 改动时两处同步）。我=墨紫（=主题 primary）/ TA=琥珀 / 双方合并=青绿，
// 取自数据色板 1/4/3 位（dataviz 六检过的互斥组合）。
export const BIG5_DIM_ORDER = [
  'openness',
  'extraversion',
  'agreeableness',
  'conscientiousness',
  'neuroticism',
] as const

export const BIG5_COLOR_ME = '#5A4BC4'
export const BIG5_COLOR_OTHER = '#E0A458'
export const BIG5_COLOR_COMBINED = '#2FA39A'

// 轴短标签（雷达类视图共用）：BigFiveRadar 分段小多图与关系章节 tooltip 雷达
// 的单一来源——轴序即 BIG5_DIM_ORDER，标签与其对位
export const BIG5_DIM_TEXT: Record<string, string> = {
  openness: '开放',
  extraversion: '外向',
  agreeableness: '宜人',
  conscientiousness: '尽责',
  neuroticism: '神经质',
}

// 五边形雷达极坐标几何（BigFiveRadar 与关系章节 tooltip 雷达单源）：
// 轴 index 的角度从正上方（-π/2）起按轴数顺时针均分
export function big5AxisAngle(index: number): number {
  return -Math.PI / 2 + (index * 2 * Math.PI) / BIG5_DIM_ORDER.length
}

/** 轴 index 上 ratio（0~1，1=外圈）的点坐标 */
export function big5PointAt(
  cx: number, cy: number, r: number, index: number, ratio: number,
): { x: number; y: number } {
  const angle = big5AxisAngle(index)
  return {
    x: cx + r * ratio * Math.cos(angle),
    y: cy + r * ratio * Math.sin(angle),
  }
}

/** 轴标签锚点（径向 offset 处）；y 的基线微调（+4/+3.5）由调用方自加 */
export function big5LabelPos(
  cx: number, cy: number, r: number, offset: number, index: number,
): { x: number; y: number; anchor: 'start' | 'middle' | 'end' } {
  const angle = big5AxisAngle(index)
  return {
    x: cx + (r + offset) * Math.cos(angle),
    y: cy + (r + offset) * Math.sin(angle),
    anchor: Math.abs(Math.cos(angle)) < 0.3 ? 'middle' : Math.cos(angle) > 0 ? 'start' : 'end',
  }
}
