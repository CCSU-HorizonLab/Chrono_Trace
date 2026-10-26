<template>
  <!-- 自我画像版：只关于我（me 切片投影），零对方元素，天然脱敏可公开。
       暖色叙事分镜：开场→你的大数字→数字格→语气曲线→你的词→语言风格→称号→落款 -->
  <div class="poster poster-self">
    <!-- 开场幕（无卡）：暖光底上直接摆「我」 -->
    <div class="brand-row">
      <span class="brand-mark">时痕</span>
      <span class="brand-sub">暖光故事 · 只关于你</span>
    </div>

    <div class="hero">
      <div class="hero-avatar"><span class="hero-fallback">我</span></div>
      <div class="hero-line">跨度 {{ formatCount(stats.span_days) }} 天里，你一直在说话</div>
    </div>

    <StorySection index="01" title="你写下的" :palette="palette">
      <StoryBigNumber
        :value="formatCount(stats.self_count)"
        unit="条消息"
        :caption="`其中 ${formatCount(stats.active_days)} 天都有你的声音`"
        :palette="palette"
      />
    </StorySection>

    <StorySection index="02" title="你的日常痕迹" :palette="palette" class="gap">
      <StoryStatGrid :items="dailyCells" :palette="palette" />
    </StorySection>

    <StorySection v-if="hasGrid" index="03" title="你的作息" :palette="palette" class="gap">
      <StoryHeatGrid
        :counts="activityGrid.counts"
        :max="activityGrid.max"
        :palette="palette"
        :ramp="theme.heatRamp"
      />
      <div v-if="peak" class="grid-note">最亮的一格是{{ peakSlotText(peak) }}——你消息最密的时辰</div>
    </StorySection>

    <StorySection v-if="calendar" index="04" :title="`你的 ${calendar.year}`" :palette="palette" class="gap">
      <StoryCalendar
        :year="calendar.year"
        :days="calendar.days"
        :max="calendar.max"
        :palette="palette"
        :ramp="theme.heatRamp"
      />
      <div class="grid-note">这一年你说了 {{ formatCount(yearTotal) }} 句话，颜色越深聊得越多</div>
    </StorySection>

    <StorySection v-if="detailCells.length" index="05" title="没意识到的细节" :palette="palette" class="gap">
      <StoryStatGrid :items="detailCells" :palette="palette" />
    </StorySection>

    <StorySection v-if="points.length" index="06" title="你的语气曲线" :palette="palette" class="gap">
      <!-- 宽=海报内容 624 − StorySection 内边距 28×2 − 边框 1×2，溢出会穿出卡片右缘 -->
      <PosterSparkline :points="points" pick="userScore" :width="566" :height="130" zero-line color="#d97706" />
      <div class="curve-note">向上是更明亮的语气，虚线是平静的分界</div>
    </StorySection>

    <StorySection v-if="myWords.length" index="07" title="你的词" :palette="palette" class="gap">
      <div class="words-cloud">
        <span
          v-for="(word, index) in myWords"
          :key="word.word"
          class="word"
          :style="{ fontSize: wordSize(index) }"
        >{{ word.word }}</span>
      </div>
    </StorySection>

    <StorySection v-if="myBig5" index="08" title="你的语言风格" :palette="palette" class="gap">
      <div class="big5-row">
        <BigFiveRadar :me="myBig5" :size="220" />
        <div class="big5-bars">
          <div v-for="dim in dimRows" :key="dim.key" class="big5-bar-row">
            <span class="bar-label">{{ dim.label }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: `${dim.score}%` }" />
            </div>
            <span class="bar-score">{{ Math.round(dim.score) }}</span>
          </div>
        </div>
      </div>
      <div class="big5-note">语言风格印象，非心理测评</div>
    </StorySection>

    <!-- 称号幕（无序号）：暖橘大字居中，亮边框收束；副称号成就 + 稀有度话术 -->
    <div class="badge-card">
      <div class="badge-eyebrow">你的称号</div>
      <div class="badge-title">{{ badge.title }}</div>
      <div class="badge-caption">{{ badge.caption }}</div>
      <div v-if="subBadges.length" class="badge-chips">
        <span v-for="sb in subBadges" :key="sb.id" class="badge-chip">{{ '★'.repeat(sb.grade) }} {{ sb.title }}</span>
      </div>
      <div v-if="rarityLines.length" class="badge-rarity">
        <div v-for="(line, i) in rarityLines" :key="i">{{ line }}</div>
      </div>
    </div>

    <div class="footer">
      <div>由 时痕 Chrono Trace 生成</div>
      <div class="footer-year">{{ yearText }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import BigFiveRadar from '@/components/deep/BigFiveRadar.vue'
import PosterSparkline from '@/components/deep/poster/PosterSparkline.vue'
import StorySection from '@/components/deep/poster/sections/StorySection.vue'
import StoryBigNumber from '@/components/deep/poster/sections/StoryBigNumber.vue'
import StoryStatGrid from '@/components/deep/poster/sections/StoryStatGrid.vue'
import StoryHeatGrid from '@/components/deep/poster/sections/StoryHeatGrid.vue'
import StoryCalendar from '@/components/deep/poster/sections/StoryCalendar.vue'
import type { StoryStatItem } from '@/components/deep/poster/sections/palette'
import { POSTER_THEMES } from '@/components/deep/poster/theme'
import {
  formatCount,
  formatHoursOrDays,
  gridPeak,
  peakSlotText,
} from '@/components/deep/poster/activityShared'
import {
  badgeInputFromSelf,
  pickPosterBadge,
  posterRarityLines,
  posterSubBadges,
} from '@/components/deep/poster/badges'
import type { SelfPosterPayload } from '@/components/deep/poster/registry'

const props = defineProps<{ payload: SelfPosterPayload }>()

// 暖米主题（palette/底渐变/热力色带与方卡共用一份，见 poster/theme.ts）
const theme = POSTER_THEMES.self
const palette = theme.palette

const stats = computed(() => props.payload.stats)
const points = computed(() => props.payload.my_curve)
const myWords = computed(() => props.payload.my_words.slice(0, 12))
const myBig5 = computed(() => props.payload.my_big5)
const badgeInput = computed(() => badgeInputFromSelf(props.payload))
const badge = computed(() => pickPosterBadge(badgeInput.value, 'self'))
const subBadges = computed(() => posterSubBadges(badgeInput.value, 'self'))
const rarityLines = computed(() => posterRarityLines(badgeInput.value, 'self'))
const yearText = computed(() => String(new Date(props.payload.generated_at * 1000).getFullYear()))

// 我的作息格与我的年历（my_activity 投影已是单侧口径）
const activityGrid = computed(() => props.payload.my_activity?.grid || { counts: [], max: 0 })
const hasGrid = computed(() => activityGrid.value.counts.length === 7 && activityGrid.value.max > 0)
const peak = computed(() => (hasGrid.value ? gridPeak(activityGrid.value.counts) : null))
const calendar = computed(() => props.payload.my_activity?.calendar || null)
const yearTotal = computed(() => (calendar.value?.days || []).reduce((sum, d) => sum + d.count, 0))

// 没意识到的细节：全部我的单侧口径
const detailCells = computed<StoryStatItem[]>(() => {
  const cells: StoryStatItem[] = []
  if (peak.value) {
    cells.push({ num: peakSlotText(peak.value), label: '你一周里消息最密的时辰' })
  }
  const question = props.payload.my_activity?.insights.question
  if (question && question.total > 0 && question.questions > 0) {
    cells.push({
      num: `${Math.round((question.questions / question.total) * 100)}%`,
      label: '你说的消息里是提问的',
    })
  }
  const streak = props.payload.my_activity?.insights.streak_days
  if (streak != null && streak >= 7) {
    cells.push({ num: `${streak} 天`, label: '你最长连续都在说话' })
  }
  if (stats.value.self_count >= 10000) {
    cells.push({
      num: formatHoursOrDays(stats.value.self_count * 2),
      label: '你的话逐条读 2 秒的时长',
      tone: 'sub',
    })
  }
  return cells
})

// 日常数字格：深夜/平均回复来自 my_story 单侧切片，缺席各自跳格
const dailyCells = computed<StoryStatItem[]>(() => {
  const cells: StoryStatItem[] = [
    { num: formatCount(stats.value.active_days), label: '天在记录生活' },
    { num: myTopWord.value, label: '你最常说的词' },
  ]
  const late = props.payload.my_story.late_night_self
  if (late != null) cells.push({ num: formatCount(late), label: '你的深夜（0-5 点）消息' })
  const reply = props.payload.my_story.reply_self_avg_seconds
  if (reply != null) cells.push({ num: formatDuration(reply), label: '你的平均回复时间' })
  return cells
})

const myTopWord = computed(() => myWords.value[0]?.word || '—')

const DIM_ORDER = ['openness', 'extraversion', 'agreeableness', 'conscientiousness', 'neuroticism']

const dimRows = computed(() => {
  const scores = myBig5.value || {}
  // 五维恒展示（雷达全维口径一致），缺席维度以 0 分占位
  return DIM_ORDER.map((key) => ({
    key,
    label: scores[key]?.label || key,
    score: typeof scores[key]?.score === 'number' ? scores[key]!.score as number : 0,
  }))
})

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

function wordSize(index: number): string {
  const scale = [32, 26, 22, 20, 18, 16, 15, 14, 13, 12, 12, 12]
  return `${scale[index] || 12}px`
}
</script>

<style scoped>
/* html2canvas 约束：纯色 + 简单 linear-gradient + 1px 亮边框；不用 shadow/transform/动画 */
.poster {
  width: 720px;
  background: linear-gradient(180deg, #fdf8f2 0%, #f7ecdd 55%, #f3e2c8 100%);
  padding: 44px 48px 36px;
  color: #3d2e1e;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
  box-sizing: border-box;
}

.gap {
  margin-top: 22px;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #d97706;
  color: #fdf8f2;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-sub {
  color: #79664c;
  font-size: 14px;
  letter-spacing: 1px;
}

.hero {
  margin-top: 36px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.hero-avatar {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  border: 2px solid #d97706;
  background: #fbf3e6;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hero-fallback {
  font-size: 32px;
  font-weight: 700;
  color: #3d2e1e;
}

.hero-line {
  font-size: 16px;
  color: #79664c;
  letter-spacing: 1px;
}

.curve-note {
  margin-top: 8px;
  font-size: 12px;
  color: #79664c;
}

.grid-note {
  margin-top: 10px;
  font-size: 12px;
  color: #79664c;
  text-align: center;
}

.words-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px 18px;
  line-height: 1.3;
}

.word {
  color: #3d2e1e;
  font-weight: 600;
}

.word:first-child {
  color: #d97706;
}

.big5-row {
  display: flex;
  align-items: center;
  gap: 28px;
}

.big5-bars {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.big5-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bar-label {
  width: 3.5em;
  font-size: 13px;
  color: #79664c;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: #f1e3ce;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  background: #d97706;
}

.bar-score {
  width: 2em;
  text-align: right;
  font-size: 13px;
  font-weight: 700;
  color: #3d2e1e;
}

.big5-note {
  margin-top: 10px;
  font-size: 12px;
  color: #8d7a58;
}

.badge-card {
  margin-top: 26px;
  border: 1px solid rgba(217, 119, 6, 0.4);
  background: rgba(217, 119, 6, 0.05);
  border-radius: 18px;
  padding: 30px 28px;
  text-align: center;
}

.badge-eyebrow {
  font-size: 13px;
  color: #79664c;
  letter-spacing: 3px;
}

.badge-title {
  margin-top: 10px;
  font-size: 44px;
  font-weight: 800;
  letter-spacing: 6px;
  color: #d97706;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.badge-caption {
  margin-top: 10px;
  font-size: 15px;
  line-height: 1.6;
  color: #3d2e1e;
}

.badge-chips {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}

.badge-chip {
  border: 1px solid rgba(217, 119, 6, 0.5);
  color: #d97706;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 13px;
}

.badge-rarity {
  margin-top: 14px;
  font-size: 13px;
  line-height: 1.9;
  color: #79664c;
}

.footer {
  margin-top: 40px;
  padding-top: 18px;
  border-top: 1px solid #e5d5bd;
  display: flex;
  justify-content: space-between;
  color: #8d7a58;
  font-size: 13px;
}
</style>
