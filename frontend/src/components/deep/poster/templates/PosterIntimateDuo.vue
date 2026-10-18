<template>
  <!-- 定向发送版（给对方看）：双方头像姓名 + 对比雷达 + 迷你曲线 + 金句卡 -->
  <div class="poster poster-intimate">
    <div class="brand-row">
      <span class="brand-mark">时痕</span>
      <span class="brand-sub">时光深度 · 我们的一段时间</span>
    </div>

    <div class="duo">
      <div class="duo-side">
        <div class="avatar me-avatar">
          <img v-if="payload.contact.avatar" :src="payload.contact.avatar" alt="" class="avatar-img" />
          <span v-else class="avatar-fallback">{{ contactInitial }}</span>
        </div>
        <div class="duo-name">{{ payload.contact.display_name }}</div>
      </div>
      <div class="duo-x">×</div>
      <div class="duo-side">
        <div class="avatar other-avatar"><span class="avatar-fallback">我</span></div>
        <div class="duo-name">我</div>
      </div>
    </div>

    <div class="hero">
      <div class="hero-line">这段时间，我们一起写下</div>
      <div class="hero-num">{{ formatCount(stats.total) }}</div>
      <div class="hero-line">条消息 · 跨度 {{ formatCount(stats.span_days) }} 天</div>
    </div>

    <div class="section">
      <div class="section-title">我们的语气一起起伏</div>
      <PosterSparkline :points="points" pick="both" :width="640" :height="140" />
      <div class="spark-legend">
        <span><i class="dot me" />我</span>
        <span><i class="dot other" />{{ payload.contact.display_name }}</span>
      </div>
    </div>

    <div v-if="quotes.length" class="section">
      <div class="section-title">那些值得记住的话</div>
      <div class="quote-cards">
        <div v-for="(quote, index) in quotes" :key="index" class="quote-card" :class="{ me: quote.is_sender }">
          <div class="quote-text">“{{ quote.text }}”</div>
          <div class="quote-meta">{{ quote.is_sender ? '我' : payload.contact.display_name }} · {{ fmtDate(quote.ts) }}</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">我们各自的词</div>
      <div class="duo-words">
        <div class="duo-words-col">
          <div class="duo-words-head me-head">我</div>
          <div class="words-cloud">
            <span v-for="(word, index) in meWords" :key="word.word" class="word me-word" :style="{ fontSize: wordSize(index) }">{{ word.word }}</span>
          </div>
        </div>
        <div class="duo-words-col">
          <div class="duo-words-head other-head">{{ payload.contact.display_name }}</div>
          <div class="words-cloud">
            <span v-for="(word, index) in otherWords" :key="word.word" class="word other-word" :style="{ fontSize: wordSize(index) }">{{ word.word }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="hasBig5" class="section">
      <div class="section-title">我们的语言风格</div>
      <div class="radar-row">
        <BigFiveRadar :me="big5Me" :other="big5Other" :size="240" />
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
import type { IntimatePosterPayload } from '@/components/deep/poster/registry'
import { toLocalDateKey } from '@/utils/datetime'

const props = defineProps<{ payload: IntimatePosterPayload }>()

const stats = computed(() => props.payload.stats)
const points = computed(() => props.payload.emotion_curve?.points || [])
const quotes = computed(() => (props.payload.quotes?.items || []).slice(0, 3))
const meWords = computed(() => (props.payload.top_words?.me || []).slice(0, 8))
const otherWords = computed(() => (props.payload.top_words?.other || []).slice(0, 8))
const big5Me = computed(() => props.payload.big5?.me?.scores || null)
const big5Other = computed(() => props.payload.big5?.other?.scores || null)
const hasBig5 = computed(() => Boolean(big5Me.value || big5Other.value))
const contactInitial = computed(() => (props.payload.contact?.display_name || '友').slice(0, 1))

function formatCount(value: number): string {
  return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString('zh-CN')
}

function fmtDate(ts: number): string {
  return toLocalDateKey(new Date(ts * 1000))
}

function wordSize(index: number): string {
  const scale = [24, 20, 18, 16, 15, 14, 13, 12]
  return `${scale[index] || 12}px`
}

const yearText = computed(() => String(new Date(props.payload.generated_at * 1000).getFullYear()))
</script>

<style scoped>
/* html2canvas 约束：纯色 + 简单 linear-gradient；不用 box-shadow/backdrop-filter/radial */
.poster {
  width: 720px;
  background: linear-gradient(180deg, #ffffff 0%, #f3f0ff 55%, #fdf6ec 100%);
  padding: 44px 48px 36px;
  color: #0f172a;
  font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
  box-sizing: border-box;
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
  background: #7c4dff;
  color: #ffffff;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-sub {
  color: #475569;
  font-size: 14px;
}

.duo {
  margin-top: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
}

.duo-side {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.avatar {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.me-avatar {
  border: 3px solid #d97706;
  background: #fdf1e0;
}

.other-avatar {
  border: 3px solid #7c4dff;
  background: #efe9ff;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-fallback {
  font-size: 30px;
  font-weight: 700;
  color: #64748b;
}

.duo-name {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.duo-x {
  font-size: 26px;
  color: #94a3b8;
  font-weight: 300;
}

.hero {
  margin-top: 30px;
  text-align: center;
}

.hero-line {
  font-size: 19px;
  color: #475569;
}

.hero-num {
  font-size: 76px;
  font-weight: 800;
  line-height: 1.15;
  color: #7c4dff;
  letter-spacing: -2px;
}

.section {
  margin-top: 34px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 14px;
}

.spark-legend {
  margin-top: 8px;
  display: flex;
  gap: 18px;
  font-size: 13px;
  color: #64748b;
}

.spark-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}

.dot.me { background: #7c4dff; }
.dot.other { background: #d97706; }

.quote-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quote-card {
  border: 1px solid #f0e4d4;
  background: #fffdf8;
  border-radius: 14px;
  padding: 16px 20px;
}

.quote-card.me {
  border-color: #e7e4f5;
  background: #fbfaff;
}

.quote-text {
  font-size: 16px;
  line-height: 1.7;
  color: #0f172a;
}

.quote-meta {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}

.duo-words {
  display: flex;
  gap: 20px;
}

.duo-words-col {
  flex: 1;
  min-width: 0;
  background: #ffffff;
  border: 1px solid #e7e4f5;
  border-radius: 16px;
  padding: 16px 18px;
}

.duo-words-head {
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 10px;
}

.me-head { color: #7c4dff; }
.other-head { color: #d97706; }

.words-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px 14px;
  line-height: 1.3;
}

.word {
  color: #334155;
  font-weight: 600;
}

.me-word { color: #5b4a86; }
.other-word { color: #9a6414; }

.radar-row {
  display: flex;
  justify-content: center;
}

.footer {
  margin-top: 44px;
  padding-top: 18px;
  border-top: 1px solid #e7e4f5;
  display: flex;
  justify-content: space-between;
  color: #94a3b8;
  font-size: 13px;
}
</style>
