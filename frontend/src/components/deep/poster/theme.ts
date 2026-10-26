/**
 * 三模板共享主题：调色板 + 底渐变 + 热力色带（ramp[0] 为空档色）。
 * 纯色 token（海报节点零 CSS 变量依赖——html2canvas 纪律）；方卡与模板
 * 共用同一份，避免两处维护漂移。配色基调研 docs/analysis/time-depth.md。
 */
import type { PosterAudience } from './registry'
import type { StoryPalette } from './sections/palette'

export type PosterTheme = {
  palette: StoryPalette
  /** 模板底 linear-gradient（html2canvas 可靠的简单渐变） */
  bgGradient: string
  /** 作息格/年历 6 档色带：[空档, … 最高档]，随模板基调走 */
  heatRamp: string[]
}

export const POSTER_THEMES: Record<PosterAudience, PosterTheme> = {
  public: {
    palette: {
      bg: '#ffffff',
      text: '#2b3245',
      muted: '#68718a',
      accent: '#4f5d9e',
      sub: '#4f5d9e',
      line: '#dfe3ef',
    },
    bgGradient: 'linear-gradient(180deg, #ffffff 0%, #f5f7fc 55%, #eef1f7 100%)',
    heatRamp: ['#f0f2f8', '#dde2f2', '#bcc5e6', '#94a0d2', '#6875bb', '#414c8c'],
  },
  self: {
    palette: {
      bg: '#fffdf8',
      text: '#3d2e1e',
      muted: '#79664c',
      accent: '#d97706',
      sub: '#9a3412',
      line: '#e5d5bd',
    },
    bgGradient: 'linear-gradient(180deg, #fdf8f2 0%, #f7ecdd 55%, #f3e2c8 100%)',
    heatRamp: ['#f4ecdc', '#edd9b7', '#e3bd82', '#d89c47', '#c47c10', '#9c5c06'],
  },
  intimate: {
    palette: {
      bg: '#141a3e',
      text: '#f3ecd9',
      muted: '#b0aacf',
      accent: '#e8c47a',
      sub: '#e37f8f',
      line: '#3a3f6b',
    },
    bgGradient: 'linear-gradient(180deg, #0b1026 0%, #151b3d 60%, #221540 100%)',
    heatRamp: ['#20264b', '#2d3362', '#4a4670', '#71603f', '#a8863f', '#e8c47a'],
  },
}
