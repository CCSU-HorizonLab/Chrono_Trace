<template>
  <div class="affinity-view p-6">
    <!-- Header / Controls -->
    <div class="controls-card mb-6 p-4 bg-white rounded-xl shadow-sm border border-gray-100 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <label class="font-medium text-gray-700">选择会话:</label>
        <select 
          v-model="selectedConversationId" 
          @change="onConversationChange"
          class="border border-gray-300 rounded-md px-3 py-1.5 focus:ring-2 focus:ring-blue-500 outline-none"
        >
          <option v-for="c in conversations" :key="c.id" :value="c.id">
            {{ c.name || `会话 ${c.id}` }} ({{ c.message_count }}条)
          </option>
        </select>
      </div>

      <div class="flex gap-2">
        <button 
          @click="startAnalysis(false)" 
          class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
          :disabled="!selectedConversationId || isAnalyzing"
        >
          {{ isAnalyzing ? '分析中...' : '开始分析' }}
        </button>
        <button 
          v-if="analysisResult"
          @click="startAnalysis(true)" 
          class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors"
          :disabled="!selectedConversationId || isAnalyzing"
        >
          重新分析
        </button>
      </div>
    </div>

    <!-- Progress Bar -->
    <div v-if="isAnalyzing" class="mb-6 bg-white p-4 rounded-xl shadow-sm">
      <div class="flex justify-between mb-2 text-sm text-gray-600">
        <span>{{ progressStep }}</span>
        <span>{{ progressPercent }}%</span>
      </div>
      <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div 
          class="h-full bg-blue-600 transition-all duration-300 ease-out"
          :style="{ width: progressPercent + '%' }"
        ></div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!analysisResult && !isAnalyzing" class="text-center py-20 text-gray-500">
      <p class="text-xl">请选择会话并开始分析</p>
    </div>

    <!-- Results Dashboard -->
    <div v-if="analysisResult" class="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fade-in">
      
      <!-- Left Column: Overall & Radar -->
      <div class="lg:col-span-1 space-y-6">
        <!-- Overall Score Card -->
        <div class="overall-card bg-white p-8 rounded-2xl shadow-sm border border-gray-100 text-center relative overflow-hidden">
          <div class="absolute top-0 right-0 p-4 opacity-5">
            <svg width="100" height="100" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
          </div>
          
          <div class="text-gray-400 text-sm font-medium tracking-wide uppercase mb-6">总体好感度</div>
          
          <div class="score-ring-container">
            <svg viewBox="0 0 120 120" class="circular-chart">
              <linearGradient id="score-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" :stop-color="getScoreColor(displayScore)" stop-opacity="0.8"/>
                <stop offset="100%" :stop-color="getScoreColor(displayScore)" />
              </linearGradient>
              <path class="circle-bg"
                d="M60 10
                   a 50 50 0 0 1 0 100
                   a 50 50 0 0 1 0 -100"
              />
              <path class="circle"
                :stroke-dasharray="circumference + ', ' + circumference"
                :style="{ strokeDashoffset: strokeDashoffset, stroke: 'url(#score-gradient)' }"
                d="M60 10
                   a 50 50 0 0 1 0 100
                   a 50 50 0 0 1 0 -100"
              />
            </svg>
            <div class="score-text-overlay">
              <span class="score-number">{{ Math.round(displayScore) }}</span>
              <span class="score-label-small">OUT OF 100</span>
            </div>
          </div>
          
          <div class="interpretation-box" :style="{ borderLeftColor: getScoreColor(displayScore) }">
            <p class="interpretation-text">
              {{ analysisResult.overall_interpretation }}
            </p>
          </div>
        </div>

        <!-- Radar Chart -->
        <div class="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
          <div class="section-title">维度分布</div>
          <DimensionRadar :dimension-scores="allDimensions" />
        </div>
      </div>

      <!-- Right Column: Detail Breakdowns -->
      <div class="lg:col-span-2 space-y-6">
        <!-- Dimension Score Cards Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <AffinityScoreCard
            v-if="analysisResult.emotional_resonance"
            title="情感共振率"
            :score="analysisResult.emotional_resonance.score"
            :max-score="100"
            :interpretation="analysisResult.emotional_resonance.interpretation"
            @click="scrollToDetails('emotional')"
          />
          <AffinityScoreCard
             v-if="analysisResult.chat_positivity"
            title="聊天积极度"
            :score="analysisResult.chat_positivity.score"
            :max-score="100"
            :interpretation="analysisResult.chat_positivity.interpretation"
            @click="scrollToDetails('positivity')"
          />
          <AffinityScoreCard
             v-if="analysisResult.attitude_tendency"
            title="态度倾向"
            :score="analysisResult.attitude_tendency.score"
            :max-score="100"
            :interpretation="analysisResult.attitude_tendency.interpretation"
             @click="scrollToDetails('attitude')"
          />
          <AffinityScoreCard
             v-if="analysisResult.preference_compatibility"
            title="喜好兼容度"
            :score="analysisResult.preference_compatibility.score"
            :max-score="100"
            :interpretation="analysisResult.preference_compatibility.interpretation"
             @click="scrollToDetails('preference')"
          />
        </div>

        <!-- Detailed Breakdowns -->
        <div class="space-y-6">
          <SubScoreBreakdown 
            id="detail-emotional"
            v-if="analysisResult.emotional_resonance"
            title="情感共振率"
            :sub-scores="analysisResult.emotional_resonance.sub_scores"
          />
          <SubScoreBreakdown 
             id="detail-positivity"
            v-if="analysisResult.chat_positivity"
            title="聊天积极度"
            :sub-scores="analysisResult.chat_positivity.sub_scores"
          />
          <SubScoreBreakdown 
             id="detail-attitude"
             v-if="analysisResult.attitude_tendency"
            title="态度倾向"
            :sub-scores="analysisResult.attitude_tendency.sub_scores"
          />
          <SubScoreBreakdown 
             id="detail-preference"
             v-if="analysisResult.preference_compatibility"
            title="喜好兼容度"
            :sub-scores="analysisResult.preference_compatibility.sub_scores"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api/bridge'
import { analyzeAffinity, getAffinityScores, type AffinityAnalysisResult } from '../api/affinity'
import AffinityScoreCard from '../components/affinity/AffinityScoreCard.vue'
import DimensionRadar from '../components/affinity/DimensionRadar.vue'
import SubScoreBreakdown from '../components/affinity/SubScoreBreakdown.vue'

interface Conversation {
  id: number
  name: string
  message_count: number
}

const conversations = ref<Conversation[]>([])
const selectedConversationId = ref<number | null>(null)
const isAnalyzing = ref(false)
const progressPercent = ref(0)
const progressStep = ref('')
const analysisResult = ref<AffinityAnalysisResult | null>(null)
const displayScore = ref(0) // Animated score

// Computed property for Radar Chart
const allDimensions = computed(() => {
  if (!analysisResult.value) return {}
  return {
    emotional_resonance: analysisResult.value.emotional_resonance || undefined,
    chat_positivity: analysisResult.value.chat_positivity || undefined,
    attitude_tendency: analysisResult.value.attitude_tendency || undefined,
    preference_compatibility: analysisResult.value.preference_compatibility || undefined
  }
})

// Load conversations on mount
onMounted(async () => {
  try {
    const res = await api.get_conversation_list()
    if (res && res.conversations) {
      conversations.value = res.conversations
      if (conversations.value.length > 0) {
        selectedConversationId.value = conversations.value[0].id
        await onConversationChange()
      }
    }
  } catch (e) {
    console.error('Failed to load conversations', e)
  }
})

const onConversationChange = async () => {
  if (!selectedConversationId.value) return
  
  // Try to load cached scores
  try {
    const scores = await getAffinityScores(selectedConversationId.value)
    if (scores) {
      analysisResult.value = scores
    } else {
      analysisResult.value = null
    }
  } catch (e) {
    console.error('Failed to load scores', e)
    analysisResult.value = null
  }
}

const startAnalysis = async (force: boolean) => {
  if (!selectedConversationId.value) return
  
  isAnalyzing.value = true
  progressPercent.value = 0
  progressStep.value = '准备中...'
  
  try {
    // Start fake progress for UI feedback since backend might be sync or fast
    // In real implementation, we might poll "get_progress" if task_id is returned
    // But analyzeAffinity is currently implemented as a blocking call in bridge (waiting for result)
    // or we can simulate progress steps if it takes time.
    
    // Simple simulated progress
    const timer = setInterval(() => {
      if (progressPercent.value < 90) {
        progressPercent.value += 5
        if (progressPercent.value < 30) progressStep.value = '正在预处理数据...'
        else if (progressPercent.value < 60) progressStep.value = '计算各项维度评分...'
        else progressStep.value = '生成综合分析报告...'
      }
    }, 500)
    
    const result = await analyzeAffinity(selectedConversationId.value, force)
    
    clearInterval(timer)
    progressPercent.value = 100
    progressStep.value = '分析完成'
    analysisResult.value = result
    
    setTimeout(() => {
      isAnalyzing.value = false
    }, 500)
    
  } catch (e) {
    console.error('Analysis failed', e)
    progressStep.value = '分析失败: ' + (e instanceof Error ? e.message : String(e))
    isAnalyzing.value = false
  }
}

watch(() => analysisResult.value, (newVal) => {
  if (newVal) {
    // Animate score from 0 to target
    let start = 0
    const end = newVal.overall_score
    const duration = 1000
    const startTime = performance.now()
    
    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
      
      // Easing function: easeOutQuart
      const ease = 1 - Math.pow(1 - progress, 4)
      
      displayScore.value = start + (end - start) * ease
      
      if (progress < 1) {
        requestAnimationFrame(animate)
      }
    }
    
    requestAnimationFrame(animate)
  } else {
    displayScore.value = 0
  }
})

const getScoreColor = (score: number) => {
  if (score >= 80) return '#52c41a' // Green
  if (score >= 60) return '#1890ff' // Blue
  if (score >= 40) return '#faad14' // Yellow
  return '#ff4d4f' // Red
}

// SVG Circle Props
const radius = 55
const circumference = 2 * Math.PI * radius
const strokeDashoffset = computed(() => {
  const score = displayScore.value
  // Score 0-100 maps to offset circumference to 0
  // But we want a gap at bottom, usually circle is full.
  // For a full circle ring:
  return circumference - (score / 100) * circumference
})

const scrollToDetails = (idSuffix: string) => {
  const el = document.getElementById(`detail-${idSuffix}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<style scoped>
.score-ring-container {
  display: flex;
  justify-content: center;
  align-items: center;
  position: relative;
  width: 140px;
  height: 140px;
  margin: 0 auto 1rem;
}

.score-text-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.score-number {
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  color: #333;
}

.score-label-small {
  font-size: 0.75rem;
  color: #999;
  margin-top: 4px;
}

.circular-chart {
  display: block;
  margin: 0 auto;
  max-width: 100%;
  max-height: 100%;
}

.circle-bg {
  fill: none;
  stroke: #f5f5f5;
  stroke-width: 8;
}

.circle {
  fill: none;
  stroke-width: 8; 
  stroke-linecap: round;
  transition: stroke-dashoffset 0.5s ease-out;
}

.interpretation-box {
  background: #fdfdfd; 
  border-radius: 8px;
  padding: 12px 16px;
  border-left: 4px solid #eee;
  text-align: left;
  margin-top: 16px;
}

.interpretation-text {
  font-size: 0.95rem;
  color: #555;
  line-height: 1.6;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  letter-spacing: 0.02em;
}

.controls-card {
  backdrop-filter: blur(10px);
  background: rgba(255, 255, 255, 0.9);
}

.overall-card {
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04);
  transition: transform 0.3s ease;
}

.overall-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1f2937;
  letter-spacing: -0.01em;
  margin-bottom: 20px;
  padding-left: 12px;
  border-left: 4px solid #3b82f6;
}

/* Animations */
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in {
  animation: fadeIn 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

/* Custom Scrollbar for the page if needed */
</style>
