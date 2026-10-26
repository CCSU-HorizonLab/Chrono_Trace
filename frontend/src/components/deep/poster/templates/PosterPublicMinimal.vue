<template>
  <!-- 公开分享版：无对方姓名/头像/原文（类型上拿不到）；浅色克制叙事分镜 -->
  <div class="poster poster-public">
    <!-- 开场幕（无卡）：中性措辞，不带任何一方身份 -->
    <div class="brand-row">
      <span class="brand-mark">时痕</span>
      <span class="brand-sub">时光故事 · 一段对话的印象</span>
    </div>

    <div class="hero-line hero-open">这段时间，有一个对话框一直在闪</div>

    <StorySection index="01" title="数字会说话" :palette="palette">
      <StoryBigNumber
        :value="formatCount(stats.total)"
        unit="条消息"
        :caption="`跨度 ${formatCount(stats.span_days)} 天 · 其中 ${formatCount(stats.active_days)} 天有消息`"
        :palette="palette"
      />
    </StorySection>

    <StorySection v-if="milestones.length" index="02" title="时间线" :palette="palette" class="gap">
      <StoryTimeline :items="milestones" :palette="palette" />
    </StorySection>

    <StorySection v-if="chemCells.length" index="03" title="两个人的默契" :palette="palette" class="gap">
      <StoryStatGrid :items="chemCells" :palette="palette" bento />
    </StorySection>

    <StorySection v-if="hasGrid" index="04" title="两个人的作息" :palette="palette" class="gap">
      <StoryHeatGrid
        :counts="activityGrid.counts"
        :max="activityGrid.max"
        :palette="palette"
        :ramp="theme.heatRamp"
      />
      <div v-if="peak" class="grid-note">最亮的一格是{{ peakSlotText(peak) }}——一周里消息最密的时辰</div>
    </StorySection>

    <StorySection v-if="detailCells.length" index="05" title="没意识到的细节" :palette="palette" class="gap">
      <StoryStatGrid :items="detailCells" :palette="palette" />
    </StorySection>

    <StorySection v-if="points.length" index="06" title="语气的起伏" :palette="palette" class="gap">
      <!-- 宽=海报内容 624 − StorySection 内边距 28×2 − 边框 1×2，溢出会穿出卡片右缘 -->
      <PosterSparkline :points="points" pick="score" :width="566" :height="130" zero-line color="#4f5d9e" />
      <div class="curve-note">向上是更明亮的语气，虚线是平静的分界</div>
    </StorySection>

    <StorySection v-if="topWords.length" index="07" title="聊得最多的词" :palette="palette" class="gap">
      <div class="words-cloud">
        <span
          v-for="(word, index) in topWords"
          :key="word.word"
          class="word"
          :style="{ fontSize: wordSize(index) }"
        >{{ word.word }}</span>
      </div>
    </StorySection>

    <StorySection v-if="hasBig5" index="08" title="两个人的语言风格" :palette="palette" class="gap">
      <div class="radar-row">
        <BigFiveRadar :me="big5Me" :other="big5Other" :size="240" />
      </div>
    </StorySection>

    <!-- 称号幕（无序号）：靛蓝大字居中收束；副称号成就 + 稀有度话术（会话内口径） -->
    <div class="badge-card">
      <div class="badge-eyebrow">这段对话的称号</div>
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
import StoryTimeline from '@/components/deep/poster/sections/StoryTimeline.vue'
import StoryStatGrid from '@/components/deep/poster/sections/StoryStatGrid.vue'
import StoryHeatGrid from '@/components/deep/poster/sections/StoryHeatGrid.vue'
import type { StoryStatItem } from '@/components/deep/poster/sections/palette'
import { POSTER_THEMES } from '@/components/deep/poster/theme'
import {
  formatCount,
  formatHoursOrDays,
  gridPeak,
  peakSlotText,
} from '@/components/deep/poster/activityShared'
import {
  badgeInputFromPublic,
  pickPosterBadge,
  posterRarityLines,
  posterSubBadges,
} from '@/components/deep/poster/badges'
import type { PublicPosterPayload, PosterWord } from '@/components/deep/poster/registry'

const props = defineProps<{ payload: PublicPosterPayload }>()

// 浅靛主题（palette/底渐变/热力色带与方卡共用一份，见 poster/theme.ts）
const theme = POSTER_THEMES.public
const palette = theme.palette

const stats = computed(() => props.payload.stats)
const milestones = computed(() => props.payload.story?.milestones || [])
const points = computed(() => props.payload.emotion_curve?.points || [])
const topWords = computed<PosterWord[]>(() => (props.payload.top_words?.all || []).slice(0, 12))
const big5Me = computed(() => props.payload.big5?.me?.scores || null)
const big5Other = computed(() => props.payload.big5?.other?.scores || null)
const hasBig5 = computed(() => Boolean(big5Me.value || big5Other.value))
const badgeInput = computed(() => badgeInputFromPublic(props.payload))
const badge = computed(() => pickPosterBadge(badgeInput.value, 'public'))
const subBadges = computed(() => posterSubBadges(badgeInput.value, 'public'))
const rarityLines = computed(() => posterRarityLines(badgeInput.value, 'public'))
const yearText = computed(() => String(new Date(props.payload.generated_at * 1000).getFullYear()))

// 作息格（公开版只有合并格，无绝对日期）
const activityGrid = computed(() => props.payload.activity?.grid || { counts: [], max: 0 })
const hasGrid = computed(() => activityGrid.value.counts.length === 7 && activityGrid.value.max > 0)
const peak = computed(() => (hasGrid.value ? gridPeak(activityGrid.value.counts) : null))

// 没意识到的细节（衍生惊喜指标）：公开版中性措辞，逐项独立降级
const detailCells = computed<StoryStatItem[]>(() => {
  const cells: StoryStatItem[] = []
  if (peak.value) {
    cells.push({ num: peakSlotText(peak.value), label: '一周里消息最密的时辰' })
  }
  const question = props.payload.activity?.insights.question
  if (question && question.total > 0 && question.questions > 0) {
    cells.push({
      num: `${Math.round((question.questions / question.total) * 100)}%`,
      label: '的消息是提问',
    })
  }
  const streak = props.payload.activity?.insights.streak_days
  if (streak != null && streak >= 7) {
    cells.push({ num: `${streak} 天`, label: '最长连续每天都有对话' })
  }
  if (stats.value.total >= 10000) {
    cells.push({
      num: formatHoursOrDays(stats.value.total * 2),
      label: '逐条读 2 秒所需的时长',
      tone: 'sub',
    })
  }
  return cells
})

// 默契数字格：公开版中性措辞（不指认谁先开口）；缺席各自跳格，全缺整幕隐藏
const chemCells = computed<StoryStatItem[]>(() => {
  const chem = props.payload.story?.chemistry
  if (!chem) return []
  const cells: StoryStatItem[] = []
  const rs = chem.reply_stats
  if (rs) {
    cells.push({ num: formatDuration(rs.median ?? rs.avg), label: '回复中位时间' })
  } else if (chem.peak_day) {
    // 公开版峰值日不带日历日期（投影层已剥 date 字段），只留条数
    cells.push({ num: formatCount(chem.peak_day.count), label: '单日消息峰值' })
  }
  if (chem.late_night) {
    cells.push({ num: formatCount(chem.late_night.count), label: '深夜（0-5 点）的消息' })
  }
  const ratio = chem.initiator?.user_ratio
  if (ratio != null) {
    const lead = Math.max(ratio, 1 - ratio)
    cells.push({
      num: `${Math.round(lead * 100)}%`,
      label: '的话题由同一个人先开口',
    })
  }
  return cells
})

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

function wordSize(index: number): string {
  const scale = [34, 28, 24, 21, 19, 17, 16, 15, 14, 13, 12, 12]
  return `${scale[index] || 12}px`
}
</script>

<style scoped>
/* html2canvas 约束：纯色 + 简单 linear-gradient + 1px 亮边框；不用 shadow/transform/动画 */
.poster {
  width: 720px;
  background: linear-gradient(180deg, #ffffff 0%, #f5f7fc 55%, #eef1f7 100%);
  padding: 44px 48px 36px;
  color: #2b3245;
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
  background: #4f5d9e;
  color: #ffffff;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-sub {
  color: #68718a;
  font-size: 14px;
  letter-spacing: 1px;
}

.hero-open {
  margin-top: 40px;
  text-align: center;
  font-size: 20px;
  letter-spacing: 2px;
  color: #68718a;
}

.curve-note {
  margin-top: 8px;
  font-size: 12px;
  color: #68718a;
}

.grid-note {
  margin-top: 10px;
  font-size: 12px;
  color: #68718a;
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
  color: #3b4258;
  font-weight: 600;
}

.word:first-child {
  color: #4f5d9e;
}

.radar-row {
  display: flex;
  justify-content: center;
}

.badge-card {
  margin-top: 26px;
  border: 1px solid rgba(79, 93, 158, 0.35);
  background: rgba(79, 93, 158, 0.05);
  border-radius: 18px;
  padding: 30px 28px;
  text-align: center;
}

.badge-eyebrow {
  font-size: 13px;
  color: #68718a;
  letter-spacing: 3px;
}

.badge-title {
  margin-top: 10px;
  font-size: 44px;
  font-weight: 800;
  letter-spacing: 6px;
  color: #4f5d9e;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.badge-caption {
  margin-top: 10px;
  font-size: 15px;
  line-height: 1.6;
  color: #2b3245;
}

.badge-chips {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}

.badge-chip {
  border: 1px solid rgba(79, 93, 158, 0.45);
  color: #4f5d9e;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 13px;
}

.badge-rarity {
  margin-top: 14px;
  font-size: 13px;
  line-height: 1.9;
  color: #68718a;
}

.footer {
  margin-top: 40px;
  padding-top: 18px;
  border-top: 1px solid #dfe3ef;
  display: flex;
  justify-content: space-between;
  color: #8b93a8;
  font-size: 13px;
}
</style>
