<template>
  <!-- 自我画像版：只关于我（me 切片投影），零对方元素，天然脱敏可公开 -->
  <div class="poster poster-self">
    <div class="brand-row">
      <span class="brand-mark">时痕</span>
      <span class="brand-sub">时光深度 · 我的年度语言画像</span>
    </div>

    <div class="hero">
      <div class="hero-line">这一年，你发出了</div>
      <div class="hero-num">{{ formatCount(stats.self_count) }}</div>
      <div class="hero-line">条消息</div>
    </div>

    <div class="stat-row">
      <div class="stat">
        <div class="stat-num">{{ formatCount(myBrightDays) }}</div>
        <div class="stat-label">个明亮时段</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ myTopWord }}</div>
        <div class="stat-label">你最常说的词</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ formatCount(stats.active_days) }}</div>
        <div class="stat-label">天在记录生活</div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">你的语气起伏</div>
      <PosterSparkline :points="points" pick="userScore" :width="640" :height="130" />
    </div>

    <div class="section">
      <div class="section-title">你的词</div>
      <div class="words-cloud">
        <span
          v-for="(word, index) in myWords"
          :key="word.word"
          class="word"
          :style="{ fontSize: wordSize(index), color: index === 0 ? '#7c4dff' : undefined }"
        >{{ word.word }}</span>
      </div>
    </div>

    <div v-if="myBig5" class="section">
      <div class="section-title">你的语言风格画像</div>
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
import type { SelfPosterPayload } from '@/components/deep/poster/registry'

const props = defineProps<{ payload: SelfPosterPayload }>()

const stats = computed(() => props.payload.stats)
const points = computed(() => props.payload.my_curve)
const myWords = computed(() => props.payload.my_words.slice(0, 12))
const myBig5 = computed(() => props.payload.my_big5)

function formatCount(value: number): string {
  return value >= 10000 ? `${(value / 10000).toFixed(1)} 万` : value.toLocaleString('zh-CN')
}

const myBrightDays = computed(() => {
  const scored = points.value.filter((p) => typeof p.userScore === 'number')
  if (!scored.length) return 0
  return scored.filter((p) => (p.userScore || 0) > 0).length
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

function wordSize(index: number): string {
  const scale = [32, 26, 22, 20, 18, 16, 15, 14, 13, 12, 12, 12]
  return `${scale[index] || 12}px`
}

const yearText = computed(() => String(new Date(props.payload.generated_at * 1000).getFullYear()))
</script>

<style scoped>
/* html2canvas 约束：纯色 + 简单 linear-gradient；不用 box-shadow/backdrop-filter/radial */
.poster {
  width: 720px;
  background: linear-gradient(180deg, #ffffff 0%, #fff8ef 100%);
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
  font-size: 84px;
  font-weight: 800;
  line-height: 1.15;
  color: #d97706;
  letter-spacing: -2px;
}

.stat-row {
  margin-top: 36px;
  display: flex;
  gap: 16px;
}

.stat {
  flex: 1;
  background: #ffffff;
  border: 1px solid #f0e4d4;
  border-radius: 16px;
  padding: 20px 12px;
  text-align: center;
}

.stat-num {
  font-size: 26px;
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
  color: #475569;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: #f1e7db;
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
  color: #0f172a;
}

.big5-note {
  margin-top: 10px;
  font-size: 12px;
  color: #94a3b8;
}

.footer {
  margin-top: 44px;
  padding-top: 18px;
  border-top: 1px solid #f0e4d4;
  display: flex;
  justify-content: space-between;
  color: #94a3b8;
  font-size: 13px;
}
</style>
