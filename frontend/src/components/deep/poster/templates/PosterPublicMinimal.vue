<template>
  <!-- 公开分享版：无对方姓名/头像/原文（类型上拿不到）；聚合数字 + 情感化叙事 -->
  <div class="poster poster-public">
    <div class="brand-row">
      <span class="brand-mark">时痕</span>
      <span class="brand-sub">时光深度 · 年度聊天印象</span>
    </div>

    <div class="hero">
      <div class="hero-line">这段时间</div>
      <div class="hero-num">{{ formatCount(stats.total) }}</div>
      <div class="hero-line">条消息留在了这个对话框里</div>
    </div>

    <div class="stat-row">
      <div class="stat">
        <div class="stat-num">{{ formatCount(stats.active_days) }}</div>
        <div class="stat-label">个日子有聊天痕迹</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ formatCount(stats.span_days) }}</div>
        <div class="stat-label">天的时间跨度</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ brightRatioText }}</div>
        <div class="stat-label">的时段语气偏明亮</div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">我们的语气起伏</div>
      <PosterSparkline :points="points" pick="score" :width="640" :height="130" />
    </div>

    <div class="section">
      <div class="section-title">聊得最多的词</div>
      <div class="words-cloud">
        <span
          v-for="(word, index) in topWords"
          :key="word.word"
          class="word"
          :style="{ fontSize: wordSize(index), color: index === 0 ? '#7c4dff' : undefined }"
        >{{ word.word }}</span>
      </div>
    </div>

    <div v-if="hasBig5" class="section">
      <div class="section-title">两个人的语言风格</div>
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
import type { PublicPosterPayload, PosterWord } from '@/components/deep/poster/registry'

const props = defineProps<{ payload: PublicPosterPayload }>()

const stats = computed(() => props.payload.stats)
const points = computed(() => props.payload.emotion_curve?.points || [])
const topWords = computed<PosterWord[]>(() => (props.payload.top_words?.all || []).slice(0, 12))
const big5Me = computed(() => props.payload.big5?.me?.scores || null)
const big5Other = computed(() => props.payload.big5?.other?.scores || null)
const hasBig5 = computed(() => Boolean(big5Me.value || big5Other.value))

function formatCount(value: number): string {
  return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString('zh-CN')
}

// 「明亮时段」：有分数的桶中 score>0 占比（Wrapped 式情感化指标）
const brightRatioText = computed(() => {
  const scored = points.value.filter((p) => typeof p.score === 'number')
  if (!scored.length) return '—'
  const bright = scored.filter((p) => (p.score || 0) > 0).length
  return `${Math.round((bright / scored.length) * 100)}%`
})

function wordSize(index: number): string {
  const scale = [34, 28, 24, 21, 19, 17, 16, 15, 14, 13, 12, 12]
  return `${scale[index] || 12}px`
}

const yearText = computed(() => {
  const year = new Date(props.payload.generated_at * 1000).getFullYear()
  return String(year)
})
</script>

<style scoped>
/* html2canvas 约束：纯色 + 简单 linear-gradient；不用 box-shadow/backdrop-filter/radial */
.poster {
  width: 720px;
  background: linear-gradient(180deg, #ffffff 0%, #f6f4ff 100%);
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

.hero {
  margin-top: 40px;
  text-align: center;
}

.hero-line {
  font-size: 20px;
  color: #475569;
}

.hero-num {
  font-size: 88px;
  font-weight: 800;
  line-height: 1.15;
  color: #7c4dff;
  letter-spacing: -2px;
}

.stat-row {
  margin-top: 36px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.stat {
  flex: 1;
  background: #ffffff;
  border: 1px solid #e7e4f5;
  border-radius: 16px;
  padding: 20px 12px;
  text-align: center;
}

.stat-num {
  font-size: 30px;
  font-weight: 800;
  color: #0f172a;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #64748b;
}

.section {
  margin-top: 36px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 14px;
}

.words-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px 18px;
  line-height: 1.3;
}

.word {
  color: #334155;
  font-weight: 600;
}

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
