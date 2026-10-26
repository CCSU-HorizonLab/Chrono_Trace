<template>
  <!-- 方形主打卡（720×720）：称号为唯一焦点，朋友圈信息流/缩略图友好；
       长图讲故事、方卡抢眼球，两档互补。纯色纪律同模板（零 CSS 变量） -->
  <div class="square" :style="{ background: bg }">
    <div class="sq-brand">
      <span class="sq-mark" :style="{ background: palette.accent, color: palette.bg }">时痕</span>
      <span class="sq-sub" :style="{ color: palette.muted }">时光故事</span>
    </div>

    <div class="sq-main">
      <div v-if="names" class="sq-names" :style="{ color: palette.text }">
        <span>{{ names.left }}</span>
        <span v-if="names.right" class="sq-x" :style="{ color: palette.muted }">×</span>
        <span v-if="names.right">{{ names.right }}</span>
      </div>
      <div class="sq-eyebrow" :style="{ color: palette.muted }">{{ eyebrow }}</div>
      <div class="sq-title" :style="{ color: palette.accent }">{{ badge.title }}</div>
      <div class="sq-caption" :style="{ color: palette.text }">{{ badge.caption }}</div>
      <div v-if="subBadges.length" class="sq-chips">
        <span
          v-for="sb in subBadges"
          :key="sb.id"
          class="sq-chip"
          :style="{ borderColor: palette.accent, color: palette.accent }"
        >{{ '★'.repeat(sb.grade) }} {{ sb.title }}</span>
      </div>
    </div>

    <!-- 加料层：迷你数字行（上下细线夹住）+ 高频词 chips——方卡不再只有孤零零一个数字 -->
    <div v-if="miniStats.length || wordChips.length" class="sq-extra">
      <div v-if="miniStats.length" class="sq-stats" :style="{ borderColor: palette.line }">
        <div v-for="s in miniStats" :key="s.label" class="sq-stat">
          <div class="sq-stat-num" :style="{ color: palette.sub }">{{ s.num }}</div>
          <div class="sq-stat-label" :style="{ color: palette.muted }">{{ s.label }}</div>
        </div>
      </div>
      <div v-if="wordChips.length" class="sq-words">
        <div class="sq-words-label" :style="{ color: palette.muted }">{{ wordsLabel }}</div>
        <div class="sq-words-row">
          <span v-for="(w, i) in wordChips" :key="w" class="sq-word" :style="wordStyle(i)">{{ w }}</span>
        </div>
      </div>
    </div>

    <div class="sq-hero">
      <div class="sq-num-row">
        <span class="sq-num" :style="{ color: palette.sub }">{{ heroNum }}</span>
        <span class="sq-unit" :style="{ color: palette.muted }">{{ heroUnit }}</span>
      </div>
      <div class="sq-hero-caption" :style="{ color: palette.muted }">{{ heroCaption }}</div>
    </div>

    <div class="sq-footer" :style="{ borderColor: palette.line, color: palette.muted }">
      <span v-if="spec.qr" class="sq-footer-text">由 时痕 Chrono Trace 生成 · {{ yearText }}</span>
      <template v-else>
        <span>由 时痕 Chrono Trace 生成</span>
        <span>{{ yearText }}</span>
      </template>
      <!-- 静态二维码仅公开受众开启（spec.qr）：全局同一 URL、零会话参数 -->
      <span v-if="spec.qr" class="sq-qr">
        <img class="sq-qr-img" :src="qrGithub" alt="Chrono Trace GitHub" />
        <span class="sq-qr-note">扫码了解时痕</span>
      </span>
    </div>
  </div>
</template>

<script lang="ts">
// 命名导出走普通 script 块：<script setup> 不允许 export 语句
import type { StoryPalette } from './sections/palette'
import type { PosterBadge, SubBadge } from './badges'

export type SquareCardStat = { num: string; label: string }

export type SquareCardSpec = {
  bg: string
  palette: StoryPalette
  eyebrow: string
  badge: PosterBadge
  subBadges: SubBadge[]
  heroNum: string
  heroUnit: string
  heroCaption: string
  /** 迷你数字行（跨度/活跃/+1 受众适宜判据），缺席为空数组 */
  miniStats: SquareCardStat[]
  /** 高频词 chips（受众口径：公开 all / 自我 me / 定向 all），缺席为空数组 */
  wordChips: string[]
  wordsLabel: string
  /** 定向版双人名 / 自我版「我」；公开版无（不指认任何一方） */
  names?: { left: string; right?: string }
  yearText: string
  /** 落款二维码：仅公开受众开启（静态资产，全局同一 URL 零会话参数） */
  qr?: boolean
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import qrGithub from '@/assets/poster/qr-github.svg'

const props = defineProps<{ spec: SquareCardSpec }>()

// 模板绑定是 spec.* 的纯转发（computed 保响应性；普通 script 块的导入
// 对模板不可见，qrGithub 必须在 setup 里导入）
const bg = computed(() => props.spec.bg)
const palette = computed(() => props.spec.palette)
const names = computed(() => props.spec.names)
const eyebrow = computed(() => props.spec.eyebrow)
const badge = computed(() => props.spec.badge)
const subBadges = computed(() => props.spec.subBadges)
const miniStats = computed(() => props.spec.miniStats || [])
const wordChips = computed(() => props.spec.wordChips || [])
const wordsLabel = computed(() => props.spec.wordsLabel)
const heroNum = computed(() => props.spec.heroNum)
const heroUnit = computed(() => props.spec.heroUnit)
const heroCaption = computed(() => props.spec.heroCaption)
const yearText = computed(() => props.spec.yearText)

// 词 chips 尺寸递减 + 首词用主色强调（chip 文本本身仍是普通文本色阶）
const WORD_SIZES = [26, 20, 17, 15, 14, 13, 12, 12]
function wordStyle(index: number) {
  return {
    fontSize: `${WORD_SIZES[index] || 12}px`,
    color: index === 0 ? props.spec.palette.accent : props.spec.palette.text,
  }
}
</script>

<style scoped>
/* html2canvas 纪律：纯色 + 简单 linear-gradient（bg 经 props 注入）、1px 亮边框；
   不用 shadow/transform/动画 */
.square {
  width: 720px;
  height: 720px;
  padding: 40px 48px 32px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-sizing: border-box;
  color: #2b3245;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
}

.sq-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sq-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sq-sub {
  font-size: 14px;
  letter-spacing: 1px;
}

.sq-main {
  text-align: center;
}

.sq-names {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
}

.sq-x {
  margin: 0 10px;
  font-weight: 300;
}

.sq-eyebrow {
  margin-top: 18px;
  font-size: 14px;
  letter-spacing: 3px;
}

.sq-title {
  margin-top: 10px;
  font-size: 52px;
  font-weight: 800;
  letter-spacing: 8px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.sq-caption {
  margin-top: 10px;
  font-size: 14px;
  line-height: 1.6;
}

.sq-chips {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}

.sq-chip {
  border: 1px solid;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 13px;
}

.sq-extra {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 迷你数字行：上下细线夹住，数字用得意黑保持与大数字同族；
   居中聚拢 + 固定间距——两格时不会两端贴边中间空荡 */
.sq-stats {
  display: flex;
  justify-content: center;
  gap: 56px;
  padding: 12px 6px;
  border-top: 1px solid;
  border-bottom: 1px solid;
}

.sq-stat {
  text-align: center;
}

.sq-stat-num {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.sq-stat-label {
  margin-top: 2px;
  font-size: 11px;
}

.sq-words-label {
  font-size: 11px;
  letter-spacing: 2px;
  text-align: center;
}

.sq-words-row {
  margin-top: 8px;
  display: flex;
  justify-content: center;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px 16px;
  line-height: 1.3;
}

.sq-word {
  font-weight: 600;
}

.sq-hero {
  text-align: center;
}

.sq-num-row {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 8px;
}

.sq-num {
  font-size: 58px;
  font-weight: 800;
  line-height: 1.1;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.sq-unit {
  font-size: 16px;
}

.sq-hero-caption {
  margin-top: 6px;
  font-size: 13px;
}

.sq-footer {
  padding-top: 16px;
  border-top: 1px solid;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.sq-qr {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.sq-qr-img {
  width: 56px;
  height: 56px;
  display: block;
}

.sq-qr-note {
  margin-top: 2px;
  font-size: 9px;
}
</style>
