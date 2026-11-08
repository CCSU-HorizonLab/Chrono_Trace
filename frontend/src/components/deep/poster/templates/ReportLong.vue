<template>
  <!-- 年度报告/纪念册共用页序列（§6.2）：封面→总量→词云→专属梗→表情→
       里程碑→数据签名。条件幕缺数据自动跳页，页码随可见幕重排 -->
  <div class="poster report-root" :style="{ background: theme.bgGradient, color: theme.palette.text }">
    <!-- 封面（无序号幕）：年份大字 + 温度胶囊 + 天数；定向版带头像对 -->
    <section class="report-page cover">
      <div class="brand-row">
        <span class="brand-mark" :style="{ background: palette.accent }">时痕</span>
        <span class="brand-sub" :style="{ color: palette.muted }">{{ kindLabel }} · Chrono Trace</span>
      </div>

      <div class="cover-center">
        <div v-if="isIntimate && avatarPair" class="cover-avatars">
          <img v-if="contact.avatar" class="cover-avatar" :src="contact.avatar" alt="" />
          <span v-else class="cover-avatar cover-avatar-fallback" :style="{ background: palette.accent }">{{
            contact.display_name.slice(0, 1)
          }}</span>
          <span class="cover-times" :style="{ color: palette.muted }">×</span>
          <span class="cover-avatar cover-avatar-me" :style="{ background: palette.sub }">我</span>
        </div>
        <div class="cover-eyebrow" :style="{ color: palette.muted }">{{ isIntimate ? '我们的' : '有这样一段对话' }}</div>
        <!-- 区间日期 16 字符在 92px 下必折行（挂着尾连字符），长标签降档保单行 -->
        <div
          class="cover-year"
          :style="{ color: palette.accent, fontSize: periodLabel.length > 8 ? '54px' : undefined }"
        >
          {{ periodLabel }}
        </div>
        <div v-if="isIntimate" class="cover-names" :style="{ color: palette.text }">{{ contact.display_name }} 与我</div>
        <div v-if="temperature" class="cover-temp" :style="{ background: palette.accent }">
          关系温度 · {{ temperature.label }} {{ temperature.score }}°
        </div>
        <div class="cover-stats" :style="{ color: palette.muted }">
          {{ formatCount(stats.span_days) }} 天 · {{ formatCount(stats.total) }} 条消息
        </div>
      </div>
      <div class="page-no" :style="{ color: palette.muted }">01 / {{ pages.length }}</div>
    </section>

    <!-- 总量页 -->
    <section v-if="pages.includes('volume')" class="report-page">
      <StorySection :index="pageNo('volume')" title="这一年，聊了多少" :palette="palette">
        <StoryBigNumber
          :value="formatCount(stats.total)"
          unit="条消息"
          :caption="`其中 ${formatCount(stats.active_days)} 天都有消息往来`"
          :palette="palette"
        />
        <StoryStatGrid :items="volumeCells" :palette="palette" bento />
      </StorySection>
      <div class="page-no" :style="{ color: palette.muted }">{{ pageNo('volume') }} / {{ pages.length }}</div>
    </section>

    <!-- 词云页 -->
    <section v-if="pages.includes('words')" class="report-page">
      <StorySection :index="pageNo('words')" title="聊得最多的词" :palette="palette">
        <div class="words-cloud">
          <span
            v-for="(word, index) in topWords"
            :key="word.word"
            class="word"
            :style="{ fontSize: wordSize(index), color: index === 0 ? palette.accent : undefined }"
          >{{ word.word }}</span>
        </div>
        <div v-if="sideWords" class="words-side" :style="{ color: palette.muted }">{{ sideWords }}</div>
      </StorySection>
      <div class="page-no" :style="{ color: palette.muted }">{{ pageNo('words') }} / {{ pages.length }}</div>
    </section>

    <!-- 专属梗页 -->
    <section v-if="pages.includes('memes')" class="report-page">
      <StorySection :index="pageNo('memes')" title="只有你们懂的梗" :palette="palette">
        <div class="meme-list">
          <div v-for="meme in memes" :key="meme.text" class="meme-row">
            <span class="meme-text">{{ meme.text }}</span>
            <span class="meme-count" :style="{ color: palette.muted }">
              {{ formatCount(meme.count) }} 次<template v-if="isIntimate"> · 你 {{ meme.me }} / TA {{ meme.ta }}</template>
            </span>
          </div>
        </div>
        <div class="meme-note" :style="{ color: palette.muted }">按出现次数排序，出自你们的聊天原文</div>
      </StorySection>
      <div class="page-no" :style="{ color: palette.muted }">{{ pageNo('memes') }} / {{ pages.length }}</div>
    </section>

    <!-- 表情页 -->
    <section v-if="pages.includes('emoji')" class="report-page">
      <StorySection :index="pageNo('emoji')" title="表情包往来" :palette="palette">
        <div class="emoji-cols">
          <div class="emoji-col">
            <div class="emoji-col-title" :style="{ color: palette.sub }">{{ isIntimate ? '你最爱发' : '一侧最爱发' }}</div>
            <div v-for="item in emojiTopMe" :key="item.kind + item.key" class="emoji-row">
              <span class="emoji-char">{{ emojiDisplay(item) }}</span>
              <span class="emoji-count" :style="{ color: palette.muted }">×{{ item.count }}</span>
            </div>
          </div>
          <div class="emoji-col">
            <div class="emoji-col-title" :style="{ color: palette.accent }">{{ isIntimate ? 'TA 最爱发' : '另一侧最爱发' }}</div>
            <div v-for="item in emojiTopTa" :key="item.kind + item.key" class="emoji-row">
              <span class="emoji-char">{{ emojiDisplay(item) }}</span>
              <span class="emoji-count" :style="{ color: palette.muted }">×{{ item.count }}</span>
            </div>
          </div>
        </div>
        <div v-if="emojiTail" class="emoji-tail" :style="{ color: palette.muted }">{{ emojiTail }}</div>
      </StorySection>
      <div class="page-no" :style="{ color: palette.muted }">{{ pageNo('emoji') }} / {{ pages.length }}</div>
    </section>

    <!-- 里程碑页 -->
    <section v-if="pages.includes('milestones')" class="report-page">
      <StorySection :index="pageNo('milestones')" title="走过的刻度" :palette="palette">
        <StoryTimeline :items="(story?.milestones || []) as any" :palette="palette" />
        <StoryStatGrid v-if="rhythmCells.length" :items="rhythmCells" :palette="palette" />
      </StorySection>
      <div class="page-no" :style="{ color: palette.muted }">{{ pageNo('milestones') }} / {{ pages.length }}</div>
    </section>

    <!-- 数据签名页（无幕标题）：落款即证明，页码收尾 -->
    <section class="report-page signature">
      <div class="sign-center">
        <div class="sign-quote" :style="{ color: palette.text }">这段时光，被完整地记了下来。</div>
        <div class="sign-facts" :style="{ color: palette.muted }">
          {{ formatCount(stats.span_days) }} 天 · {{ formatCount(stats.total) }} 条消息 ·
          {{ formatCount(report.chars) }} 个字
        </div>
        <div v-if="rhythmLine" class="sign-facts" :style="{ color: palette.muted }">{{ rhythmLine }}</div>
        <div v-if="isIntimate" class="sign-dedicate" :style="{ color: palette.sub }">—— 给 {{ contact.display_name }}</div>
      </div>
      <div class="page-no" :style="{ color: palette.muted }">{{ pageNo('signature') }} / {{ pages.length }}</div>
      <div class="footer">
        <div class="footer-text" :style="{ color: palette.muted }">
          <div>{{ kindLabel }} · 由 时痕 Chrono Trace 生成</div>
          <div class="footer-date">{{ generatedDate }}</div>
        </div>
        <div v-if="!isIntimate" class="footer-qr">
          <img class="qr-img" :src="qrGithub" alt="Chrono Trace GitHub" />
          <span class="qr-note" :style="{ color: palette.muted }">扫码了解时痕</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import StorySection from '../sections/StorySection.vue'
import StoryBigNumber from '../sections/StoryBigNumber.vue'
import StoryStatGrid from '../sections/StoryStatGrid.vue'
import StoryTimeline from '../sections/StoryTimeline.vue'
import type { StoryStatItem } from '../sections/palette'
import { POSTER_THEMES } from '../theme'
import { formatCount } from '../activityShared'
import { emojiCharFor } from '@/utils/wechatEmoji'
import { toLocalDateKey } from '@/utils/datetime'
import type {
  IntimateReportPayload,
  PublicReportPayload,
  ReportEmojiItem,
} from '../registry'
import qrGithub from '@/assets/poster/qr-github.svg'

const props = defineProps<{
  payload: IntimateReportPayload | PublicReportPayload
  audience: 'public' | 'intimate'
}>()

const isIntimate = computed(() => props.audience === 'intimate')
const theme = computed(() => POSTER_THEMES[props.audience])
const palette = computed(() => theme.value.palette)

const stats = computed(() => props.payload.stats)
const report = computed(() => props.payload.report)
const story = computed(() => props.payload.story)
const temperature = computed(() => report.value.temperature)
const memes = computed(() => report.value.memes || [])
const contact = computed(
  () => (props.payload as IntimateReportPayload).contact || { display_name: '', avatar: null },
)
const avatarPair = computed(() => contact.value.display_name || contact.value.avatar)

// 封面期间标签：整年窗口 → 年度报告 + 年份大字；跨年区间 → 纪念册 + 日期段
const from = new Date(props.payload.from_ts * 1000)
const to = new Date(props.payload.to_ts * 1000)
const isYearWindow = computed(
  () => from.getFullYear() === to.getFullYear() && to.getTime() - from.getTime() > 300 * 86400 * 1000,
)
const kindLabel = computed(() => (isYearWindow.value ? '年度报告' : '纪念册'))
const periodLabel = computed(() =>
  isYearWindow.value
    ? String(from.getFullYear())
    : `${from.getFullYear()}.${String(from.getMonth() + 1).padStart(2, '0')} - ${to.getFullYear()}.${String(to.getMonth() + 1).padStart(2, '0')}`,
)

// 可见幕序列：缺数据的幕整页跳过，页码随之重排
const pages = computed(() => {
  const list = ['cover', 'volume']
  if ((props.payload.top_words?.all || []).length) list.push('words')
  if (memes.value.length) list.push('memes')
  if (report.value.emoji && (report.value.emoji.top_me.length || report.value.emoji.top_ta.length || report.value.emoji.custom_count))
    list.push('emoji')
  if ((story.value?.milestones || []).length) list.push('milestones')
  list.push('signature')
  return list
})

function pageNo(key: string): string {
  const index = pages.value.indexOf(key)
  return index < 0 ? '--' : String(index + 1).padStart(2, '0')
}

// 总量页数字格：字数/峰值日/最长连续/深夜（公开版峰值日无日历日期）
const volumeCells = computed<StoryStatItem[]>(() => {
  const cells: StoryStatItem[] = [
    { num: formatCount(report.value.chars), label: '个字' },
    { num: formatCount(stats.value.active_days), label: '天有消息往来' },
  ]
  const peak = story.value?.chemistry.peak_day
  if (peak) cells.push({ num: formatCount(peak.count), label: isIntimate.value ? `单日峰值（${peak.date}）` : '单日消息峰值' })
  if (report.value.streak_days != null && report.value.streak_days >= 3)
    cells.push({ num: `${report.value.streak_days} 天`, label: '最长连续不断聊' })
  const late = story.value?.chemistry.late_night
  if (late) cells.push({ num: formatCount(late.count), label: '深夜（0-5 点）的消息' })
  return cells
})

const topWords = computed(() => (props.payload.top_words?.all || []).slice(0, 14))
const sideWords = computed(() => {
  const mine = (props.payload.top_words?.me || []).slice(0, 3).map((w) => w.word)
  const theirs = (props.payload.top_words?.other || []).slice(0, 3).map((w) => w.word)
  if (!mine.length && !theirs.length) return ''
  const parts: string[] = []
  if (mine.length) parts.push(`${isIntimate.value ? '你' : '一侧'}常说：${mine.join('、')}`)
  if (theirs.length) parts.push(`${isIntimate.value ? 'TA' : '另一侧'}常说：${theirs.join('、')}`)
  return parts.join('　·　')
})

// 表情页：builtin 词经内置映射还原 emoji，映射不到保留原词
const emojiTopMe = computed(() => (report.value.emoji?.top_me || []).slice(0, 6))
const emojiTopTa = computed(() => (report.value.emoji?.top_ta || []).slice(0, 6))

function emojiDisplay(item: ReportEmojiItem): string {
  if (item.kind === 'unicode') return item.key
  return emojiCharFor(item.key) || `[${item.key}]`
}

const emojiTail = computed(() => {
  const emoji = report.value.emoji
  if (!emoji) return ''
  const parts: string[] = []
  if (emoji.custom_count) parts.push(`另有 ${formatCount(emoji.custom_count)} 次自定义表情包`)
  if (emoji.peak_label) parts.push(`互发表情的高峰在${emoji.peak_label}`)
  return parts.join('，')
})

// 里程碑页节奏格：早安晚安（§6.5）
const rhythmCells = computed<StoryStatItem[]>(() => {
  const rhythm = report.value.rhythm
  const cells: StoryStatItem[] = []
  if (rhythm.morning_days)
    cells.push({ num: `${rhythm.morning_days} 天`, label: isIntimate.value ? '以一句早安开场' : '以早安开场' })
  if (rhythm.night_days)
    cells.push({ num: `${rhythm.night_days} 天`, label: isIntimate.value ? '聊到互道晚安才收尾' : '聊到晚安才收尾' })
  return cells
})

const rhythmLine = computed(() => {
  const rhythm = report.value.rhythm
  const parts: string[] = []
  if (rhythm.morning_days) parts.push(`互道早安 ${rhythm.morning_days} 天`)
  if (rhythm.night_days) parts.push(`互道晚安 ${rhythm.night_days} 天`)
  return parts.join(' · ')
})

const generatedDate = computed(() => toLocalDateKey(new Date(props.payload.generated_at * 1000)))

function wordSize(index: number): string {
  const scale = [34, 28, 24, 21, 19, 17, 16, 15, 14, 13, 12, 12, 12, 12]
  return `${scale[index] || 12}px`
}
</script>

<style scoped>
/* html2canvas 纪律：纯色 + 简单 linear-gradient + 1px 亮边框；不用 shadow/transform/动画 */
.report-root {
  width: 720px;
  padding: 44px 48px 36px;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
  box-sizing: border-box;
}

.report-page {
  min-height: 680px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 26px 0 14px;
  border-bottom: 1px dashed;
  border-color: inherit;
}

.report-page:last-child {
  border-bottom: none;
}

.page-no {
  margin-top: auto;
  text-align: right;
  font-size: 12px;
  letter-spacing: 2px;
  font-family: 'Smiley Sans', 'PingFang SC', sans-serif;
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
  color: #ffffff;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-sub {
  font-size: 14px;
  letter-spacing: 1px;
}

/* ---------- 封面 ---------- */
.cover {
  justify-content: flex-start;
}

.cover-center {
  margin: auto 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  text-align: center;
}

.cover-avatars {
  display: flex;
  align-items: center;
  gap: 16px;
}

.cover-avatar {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  object-fit: cover;
}

.cover-avatar-fallback,
.cover-avatar-me {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 26px;
  font-weight: 700;
}

.cover-avatar-me {
  font-size: 20px;
}

.cover-times {
  font-size: 18px;
}

.cover-eyebrow {
  font-size: 18px;
  letter-spacing: 4px;
}

.cover-year {
  font-size: 92px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: 4px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.cover-names {
  font-size: 20px;
  letter-spacing: 2px;
}

.cover-temp {
  margin-top: 6px;
  color: #ffffff;
  font-size: 15px;
  letter-spacing: 2px;
  border-radius: 999px;
  padding: 7px 22px;
}

.cover-stats {
  font-size: 14px;
  letter-spacing: 1px;
}

/* ---------- 词云 / 专属梗 ---------- */
.words-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px 18px;
  line-height: 1.3;
}

.word {
  font-weight: 600;
}

.words-side {
  margin-top: 16px;
  font-size: 13px;
  line-height: 1.8;
}

.meme-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.meme-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
}

.meme-text {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 1px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.meme-row:first-child .meme-text {
  font-size: 34px;
}

.meme-count {
  flex-shrink: 0;
  font-size: 13px;
}

.meme-note {
  margin-top: 14px;
  font-size: 12px;
  text-align: center;
}

/* ---------- 表情页 ---------- */
.emoji-cols {
  display: flex;
  gap: 24px;
}

.emoji-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.emoji-col-title {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 1px;
}

.emoji-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid;
  border-color: inherit;
  border-radius: 12px;
  padding: 6px 14px;
}

.emoji-char {
  font-size: 26px;
  line-height: 1.4;
}

.emoji-row:nth-child(2) .emoji-char {
  font-size: 34px;
}

.emoji-count {
  font-size: 13px;
}

.emoji-tail {
  margin-top: 14px;
  font-size: 13px;
  text-align: center;
}

/* ---------- 签名页 ---------- */
.signature {
  justify-content: flex-start;
}

.sign-center {
  margin: auto 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  text-align: center;
}

.sign-quote {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: 3px;
  font-family: 'Smiley Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.sign-facts {
  font-size: 14px;
  letter-spacing: 1px;
}

.sign-dedicate {
  margin-top: 8px;
  font-size: 15px;
  letter-spacing: 2px;
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  font-size: 13px;
}

.footer-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.footer-date {
  font-size: 12px;
}

.footer-qr {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.qr-img {
  width: 72px;
  height: 72px;
  display: block;
}

.qr-note {
  margin-top: 3px;
  font-size: 10px;
}
</style>
