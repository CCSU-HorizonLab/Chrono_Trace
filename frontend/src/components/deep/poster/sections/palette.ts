/**
 * 分镜调色板：纯色 token 经 props 传入（海报节点零 CSS 变量依赖——
 * html2canvas 对 CSS 变量支持不稳，纪律见 docs/analysis/time-depth.md）。
 * 各模板自定颜色，分镜组件只消费这些槽位。
 */
export type StoryPalette = {
  /** 卡面底色 */
  bg: string
  /** 主文字 */
  text: string
  /** 次要文字 */
  muted: string
  /** 大数字/强调 */
  accent: string
  /** 副强调（次高亮数字） */
  sub: string
  /** 描边/分隔线 */
  line: string
}

/** 数字格条目：num 为预格式化文本（万/亿换算由调用方决定） */
export type StoryStatItem = {
  num: string
  label: string
  tone?: 'accent' | 'sub'
}
