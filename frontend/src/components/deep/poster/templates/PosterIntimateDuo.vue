<template>
  <!-- 定向发送版（给对方看）：星夜叙事分镜——开场→大数字→时光机→默契→金句→词云→雷达→称号→落款 -->
  <div class="poster poster-intimate">
    <!-- 开场幕（无卡）：星夜底上直接摆双方 -->
    <div class="brand-row">
      <span class="brand-mark">时痕</span>
      <span class="brand-sub">星夜故事 · 我们的一段时间</span>
    </div>

    <div class="duo">
      <div class="duo-side">
        <div class="avatar contact-avatar">
          <img v-if="payload.contact.avatar" :src="payload.contact.avatar" alt="" class="avatar-img" />
          <span v-else class="avatar-fallback">{{ contactInitial }}</span>
        </div>
        <div class="duo-name">{{ payload.contact.display_name }}</div>
      </div>
      <div class="duo-x">×</div>
      <div class="duo-side">
        <div class="avatar me-avatar"><span class="avatar-fallback">我</span></div>
        <div class="duo-name">我</div>
      </div>
    </div>

    <div class="date-range">{{ rangeText }}</div>

    <StorySection index="01" title="我们一起写下" :palette="palette">
      <StoryBigNumber
        :value="formatCount(stats.total)"
        unit="条消息"
        :caption="`跨度 ${formatCount(stats.span_days)} 天 · 其中 ${formatCount(stats.active_days)} 天有消息`"
        :palette="palette"
      />
    </StorySection>

    <StorySection v-if="milestones.length" index="02" title="时光机" :palette="palette" class="gap">
      <StoryTimeline :items="milestones" :palette="palette" />
    </StorySection>

    <StorySection v-if="chemCells.length" index="03" title="我们的默契" :palette="palette" class="gap">
      <StoryStatGrid :items="chemCells" :palette="palette" bento />
    </StorySection>

    <StorySection v-if="hasGrid" index="04" title="我们的作息" :palette="palette" class="gap">
      <StoryHeatGrid
        :counts="activityGrid.all"
        :max="activityGrid.max_all"
        :palette="palette"
        :ramp="theme.heatRamp"
      />
      <div v-if="peak" class="grid-note">最亮的一格是{{ peakSlotText(peak) }}——一周里消息最密的时辰</div>
    </StorySection>

    <StorySection v-if="calendar" index="05" :title="`最热闹的一年 · ${calendar.year}`" :palette="palette" class="gap">
      <StoryCalendar
        :year="calendar.year"
        :days="calendar.days"
        :max="calendar.max"
        :palette="palette"
        :ramp="theme.heatRamp"
      />
      <div class="grid-note">这一年你们聊了 {{ formatCount(yearTotal) }} 句{{ peakDayText }}</div>
    </StorySection>

    <StorySection v-if="detailCells.length" index="06" title="没意识到的细节" :palette="palette" class="gap">
      <StoryStatGrid :items="detailCells" :palette="palette" />
    </StorySection>

    <StorySection v-if="quotes.length" index="07" title="那些值得记住的话" :palette="palette" class="gap">
      <div class="quote-cards">
        <div
          v-for="(quote, index) in quotes"
          :key="index"
          class="quote-card"
          :class="{ me: quote.is_sender }"
        >
          <div class="quote-text">“{{ quote.text }}”</div>
          <div class="quote-meta">{{ quote.is_sender ? '我' : payload.contact.display_name }} · {{ fmtDate(quote.ts) }}</div>
        </div>
      </div>
    </StorySection>

    <StorySection index="08" title="我们各自的词" :palette="palette" class="gap">
      <div class="duo-words">
        <div class="duo-words-col">
          <div class="duo-words-head contact-head">{{ payload.contact.display_name }}</div>
          <div class="words-cloud">
            <span v-for="(word, index) in otherWords" :key="word.word" class="word contact-word" :style="{ fontSize: wordSize(index) }">{{ word.word }}</span>
          </div>
        </div>
        <div class="duo-words-col">
          <div class="duo-words-head me-head">我</div>
          <div class="words-cloud">
            <span v-for="(word, index) in meWords" :key="word.word" class="word me-word" :style="{ fontSize: wordSize(index) }">{{ word.word }}</span>
          </div>
        </div>
      </div>
    </StorySection>

    <StorySection v-if="hasBig5" index="09" title="我们的语言风格" :palette="palette" class="gap">
      <div class="radar-row">
        <BigFiveRadar :me="big5Me" :other="big5Other" :size="240" />
      </div>
      <!-- 图例补在模板层（BigFiveRadar 复用不动；色值与组件 .data-poly 一致） -->
      <div class="radar-legend">
        <span class="legend-item"><span class="legend-dot dot-me" />我</span>
        <span class="legend-item"><span class="legend-dot dot-other" />{{ payload.contact.display_name }}</span>
      </div>
    </StorySection>

    <!-- 称号幕（无序号）：金色大字居中，亮边框模拟星夜里的光；副称号成就 + 稀有度话术 -->
    <div class="badge-card">
      <div class="badge-eyebrow">你们的称号</div>
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
import StorySection from '@/components/deep/poster/sections/StorySection.vue'
import StoryBigNumber from '@/components/deep/poster/sections/StoryBigNumber.vue'
import StoryTimeline from '@/components/deep/poster/sections/StoryTimeline.vue'
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
  badgeInputFromIntimate,
  pickPosterBadge,
  posterRarityLines,
  posterSubBadges,
} from '@/components/deep/poster/badges'
import type { IntimatePosterPayload } from '@/components/deep/poster/registry'
import { toLocalDateKey } from '@/utils/datetime'

const props = defineProps<{ payload: IntimatePosterPayload }>()

// 星夜主题（palette/底渐变/热力色带与方卡共用一份，见 poster/theme.ts）
const theme = POSTER_THEMES.intimate
const palette = theme.palette

const stats = computed(() => props.payload.stats)
const milestones = computed(() => props.payload.story?.milestones || [])
const quotes = computed(() => (props.payload.quotes?.items || []).slice(0, 3))
const meWords = computed(() => (props.payload.top_words?.me || []).slice(0, 8))
const otherWords = computed(() => (props.payload.top_words?.other || []).slice(0, 8))
const big5Me = computed(() => props.payload.big5?.me?.scores || null)
const big5Other = computed(() => props.payload.big5?.other?.scores || null)
const hasBig5 = computed(() => Boolean(big5Me.value || big5Other.value))
const contactInitial = computed(() => (props.payload.contact?.display_name || '友').slice(0, 1))
const badgeInput = computed(() => badgeInputFromIntimate(props.payload))
const badge = computed(() => pickPosterBadge(badgeInput.value, 'intimate'))
const subBadges = computed(() => posterSubBadges(badgeInput.value, 'intimate'))
const rarityLines = computed(() => posterRarityLines(badgeInput.value, 'intimate'))

// 作息格与最活跃年年历（定向版可用全量含日期）。注意定向版吃的是原始
// payload：grid 形状是 {all, me, max_all, max_me}——counts/max 是公开/自我
// 版投影后的字段名，在这里拿不到（作息格用合并侧 all）
const activityGrid = computed(() => props.payload.activity?.grid || null)
const hasGrid = computed(
  () => !!activityGrid.value && activityGrid.value.all.length === 7 && activityGrid.value.max_all > 0,
)
const peak = computed(() => (hasGrid.value ? gridPeak(activityGrid.value.all) : null))
const calendar = computed(() => props.payload.activity?.calendar || null)
const yearTotal = computed(
  () => (calendar.value?.days || []).reduce((sum, d) => sum + d.count, 0),
)
// 年内最密集的一天（并列取更早）——定向版可带日历日期
const peakDayText = computed(() => {
  const days = calendar.value?.days || []
  let best: { date: string; count: number } | null = null
  for (const day of days) {
    if (!best || day.count > best.count) best = day
  }
  if (!best || best.count <= 0) return ''
  const [_, month, day] = best.date.split('-')
  return `，最密集的一天是 ${Number(month)} 月 ${Number(day)} 日`
})

const rangeText = computed(
  () => `${fmtDate(props.payload.from_ts)} — ${fmtDate(props.payload.to_ts)}`,
)
const yearText = computed(() => String(new Date(props.payload.generated_at * 1000).getFullYear()))

// 默契数字格：中位回复缺席时换峰值日；深夜/先开口各自独立降级；全缺整幕隐藏
const chemCells = computed<StoryStatItem[]>(() => {
  const chem = props.payload.story?.chemistry
  if (!chem) return []
  const cells: StoryStatItem[] = []
  const rs = chem.reply_stats
  if (rs) {
    cells.push({ num: formatDuration(rs.median ?? rs.avg), label: '中位回复时间' })
  } else if (chem.peak_day) {
    cells.push({
      num: formatCount(chem.peak_day.count),
      label: `单日最多 · ${chem.peak_day.date}`,
      tone: 'sub',
    })
  }
  if (chem.late_night) {
    cells.push({ num: formatCount(chem.late_night.count), label: '深夜（0-5 点）消息', tone: 'sub' })
  }
  const ratio = chem.initiator?.user_ratio
  if (ratio != null) {
    cells.push({
      num: ratio >= 0.5 ? `你 ${Math.round(ratio * 100)}%` : `TA ${Math.round((1 - ratio) * 100)}%`,
      label: '先开口的一方',
      tone: 'sub',
    })
  }
  return cells
})

// 没意识到的细节（衍生惊喜指标）：定向版可指认双方
const detailCells = computed<StoryStatItem[]>(() => {
  const cells: StoryStatItem[] = []
  if (peak.value) {
    cells.push({ num: peakSlotText(peak.value), label: '你们一周里消息最密的时辰' })
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

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

function fmtDate(ts: number): string {
  return toLocalDateKey(new Date(ts * 1000))
}

function wordSize(index: number): string {
  const scale = [24, 20, 18, 16, 15, 14, 13, 12]
  return `${scale[index] || 12}px`
}
</script>

<style scoped>
/* html2canvas 约束：纯色 + 简单 linear-gradient + 1px 亮边框模拟光感；
   不用 box-shadow/text-shadow/transform/动画 */
.poster {
  width: 720px;
  background: linear-gradient(180deg, #0b1026 0%, #151b3d 60%, #221540 100%);
  padding: 44px 48px 36px;
  color: #f3ecd9;
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
  background: #e8c47a;
  color: #0b1026;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-sub {
  color: #9d97bd;
  font-size: 14px;
  letter-spacing: 1px;
}

.duo {
  margin-top: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 28px;
}

.duo-side {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.avatar {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 「光感」= 亮色描边，不用 shadow */
.contact-avatar {
  border: 2px solid #e37f8f;
  background: #2a1d3f;
}

.me-avatar {
  border: 2px solid #e8c47a;
  background: #1d2447;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-fallback {
  font-size: 32px;
  font-weight: 700;
  color: #f3ecd9;
}

.duo-name {
  font-size: 18px;
  font-weight: 700;
  color: #f3ecd9;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.duo-x {
  font-size: 26px;
  color: #6f6a99;
  font-weight: 300;
}

.date-range {
  margin-top: 14px;
  text-align: center;
  font-size: 14px;
  color: #9d97bd;
  letter-spacing: 2px;
}

.grid-note {
  margin-top: 10px;
  font-size: 12px;
  color: #9d97bd;
  text-align: center;
}

.quote-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quote-card {
  border: 1px solid rgba(232, 196, 122, 0.35);
  background: rgba(232, 196, 122, 0.06);
  border-radius: 14px;
  padding: 18px 22px;
}

.quote-text {
  font-size: 18px;
  line-height: 1.8;
  color: #f3ecd9;
  /* 金句衬线：书卷气，免增字体包体 */
  font-family: Georgia, 'Songti SC', 'Noto Serif CJK SC', serif;
}

.quote-meta {
  margin-top: 8px;
  font-size: 12px;
  color: #9d97bd;
}

.duo-words {
  display: flex;
  gap: 16px;
}

.duo-words-col {
  flex: 1;
  min-width: 0;
  border: 1px solid #3a3f6b;
  background: #10153a;
  border-radius: 14px;
  padding: 16px 18px;
}

.duo-words-head {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 10px;
}

.contact-head { color: #e37f8f; }
.me-head { color: #e8c47a; }

.words-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px 14px;
  line-height: 1.3;
}

.word {
  font-weight: 600;
}

.contact-word { color: #f0b7c0; }
.me-word { color: #f0d6a8; }

.radar-row {
  display: flex;
  justify-content: center;
}

.radar-legend {
  margin-top: 12px;
  display: flex;
  justify-content: center;
  gap: 26px;
  font-size: 13px;
  color: #b0aacf;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 7px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dot-me { background: #7c4dff; }
.dot-other { background: #d97706; }

.badge-card {
  margin-top: 26px;
  border: 1px solid rgba(232, 196, 122, 0.45);
  background: rgba(232, 196, 122, 0.05);
  border-radius: 18px;
  padding: 30px 28px;
  text-align: center;
}

.badge-eyebrow {
  font-size: 13px;
  color: #9d97bd;
  letter-spacing: 3px;
}

.badge-title {
  margin-top: 10px;
  font-size: 44px;
  font-weight: 800;
  letter-spacing: 6px;
  color: #e8c47a;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.badge-caption {
  margin-top: 10px;
  font-size: 15px;
  line-height: 1.6;
  color: #f3ecd9;
}

.badge-chips {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}

.badge-chip {
  border: 1px solid rgba(232, 196, 122, 0.55);
  color: #e8c47a;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 13px;
}

.badge-rarity {
  margin-top: 14px;
  font-size: 13px;
  line-height: 1.9;
  color: #b0aacf;
}

.footer {
  margin-top: 40px;
  padding-top: 18px;
  border-top: 1px solid #3a3f6b;
  display: flex;
  justify-content: space-between;
  color: #9d97bd;
  font-size: 13px;
}
</style>
