<template>
  <div class="affinity-page">
    <header class="page-title">
      <h1>亲密度分析</h1>
    </header>

    <!-- Controls -->
    <CtCard>
      <div class="controls-row">
        <div class="control-group">
          <label class="label">选择会话</label>
          <div class="select-wrapper">
            <select 
              v-model="selectedConversationId" 
              @change="onConversationChange"
              class="ct-select"
            >
              <option v-for="c in conversations" :key="c.id" :value="c.id">
                {{ c.name || `会话 ${c.id}` }} ({{ c.message_count }}条)
              </option>
            </select>
          </div>
        </div>

        <div class="actions">
          <CtButton 
            @click="showContextForm = true" 
            variant="ghost"
            :disabled="!selectedConversationId"
          >
            关系信息
          </CtButton>
          <CtButton 
            @click="showKeywordsDialog = true" 
            variant="ghost"
            :disabled="!selectedConversationId"
          >
            配置喜好关键词
          </CtButton>
          <CtButton 
            @click="handleStartAnalysis(false)" 
            :loading="isAnalyzing"
            :disabled="!selectedConversationId"
          >
            {{ isAnalyzing ? '分析中...' : '开始分析' }}
          </CtButton>
          <CtButton 
            v-if="analysisResult"
            variant="ghost"
            @click="handleStartAnalysis(true)" 
            :disabled="!selectedConversationId || isAnalyzing"
          >
            重新分析
          </CtButton>
        </div>
      </div>
    </CtCard>

    <!-- Progress Bar -->
    <CtCard v-if="isAnalyzing" class="progress-card">
      <div class="progress-info">
        <span>{{ progressStep }}</span>
        <span>{{ progressPercent }}%</span>
      </div>
      <div class="progress-track">
        <div 
          class="progress-fill"
          :style="{ width: progressPercent + '%' }"
        ></div>
      </div>
    </CtCard>

    <!-- Empty State -->
    <div v-if="!analysisResult && !isAnalyzing" class="empty-state">
      <div class="empty-icon">📊</div>
      <p>请选择会话并开始分析,探索你们的亲密关系维度。</p>
      <p class="empty-hint">💡 首次分析需要1-2分钟进行数据预处理,请耐心等待</p>
    </div>

    <!-- Results Dashboard -->
    <div v-if="analysisResult" class="dashboard-grid fade-in">
      
      <!-- Left Column: Overall & Radar -->
      <div class="col-left">
        <!-- Overall Score Card -->
        <CtCard class="overall-card">
          <div class="overall-content">
            <div class="bg-decoration">
              <svg width="100%" height="100%" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
              </svg>
            </div>
            
            <div class="card-label-row">
              <div class="card-label">总体好感度</div>
              <WeightInfoTooltip :has-preference-keywords="hasPreferenceKeywords" />
            </div>
            
            <div class="score-ring-container">
              <svg viewBox="0 0 120 120" class="circular-chart">
                <defs>
                   <linearGradient id="score-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" :stop-color="getScoreColor(displayScore)" stop-opacity="0.8"/>
                    <stop offset="100%" :stop-color="getScoreColor(displayScore)" />
                  </linearGradient>
                </defs>
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
        </CtCard>

        <!-- Radar Chart -->
        <CtCard title="维度分布">
          <DimensionRadar :dimension-scores="allDimensions" />
        </CtCard>
      </div>

      <!-- Right Column: Detail Breakdowns -->
      <div class="col-right">
        <!-- Dimension Score Cards Grid -->
        <div class="cards-grid">
          <AffinityScoreCard
            v-if="analysisResult.emotional_resonance"
            title="情感共振率"
            :score="analysisResult.emotional_resonance.score"
            :max-score="100"
            :weight="analysisResult.emotional_resonance.weight"
            :interpretation="analysisResult.emotional_resonance.interpretation"
            @click="scrollToDetails('emotional')"
          />
          <AffinityScoreCard
             v-if="analysisResult.chat_positivity"
            title="聊天积极度"
            :score="analysisResult.chat_positivity.score"
            :max-score="100"
            :weight="analysisResult.chat_positivity.weight"
            :interpretation="analysisResult.chat_positivity.interpretation"
            @click="scrollToDetails('positivity')"
          />
          <AffinityScoreCard
             v-if="analysisResult.attitude_tendency"
            title="态度倾向"
            :score="analysisResult.attitude_tendency.score"
            :max-score="100"
            :weight="analysisResult.attitude_tendency.weight"
            :interpretation="analysisResult.attitude_tendency.interpretation"
             @click="scrollToDetails('attitude')"
          />
          <AffinityScoreCard
             v-if="analysisResult.preference_compatibility"
            title="喜好兼容度"
            :score="analysisResult.preference_compatibility.score"
            :max-score="100"
            :weight="analysisResult.preference_compatibility.weight"
            :interpretation="analysisResult.preference_compatibility.interpretation"
             @click="scrollToDetails('preference')"
             @disabled-click="handlePreferenceDisabledClick"
          />
        </div>

        <!-- Detailed Breakdowns -->
        <div class="breakdowns-list">
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
    
    <!-- Preference Keywords Dialog -->
    <PreferenceKeywordsDialog
      v-if="selectedConversationId"
      v-model="showKeywordsDialog"
      :conversation-id="selectedConversationId"
      @updated="handleKeywordsUpdated"
    />

    <!-- Relationship Context Form -->
    <RelationshipContextForm
      v-if="selectedConversationId"
      v-model="showContextForm"
      :conversation-id="selectedConversationId"
      @saved="handleContextSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api/bridge'
import { analyzeAffinity, getAffinityScores, getAffinityProgress, getRelationshipContext, type AffinityAnalysisResult } from '../api/affinity'
import CtCard from '@/components/base/CtCard.vue'
import CtButton from '@/components/base/CtButton.vue'
import AffinityScoreCard from '../components/affinity/AffinityScoreCard.vue'
import DimensionRadar from '../components/affinity/DimensionRadar.vue'
import SubScoreBreakdown from '../components/affinity/SubScoreBreakdown.vue'
import WeightInfoTooltip from '../components/affinity/WeightInfoTooltip.vue'
import PreferenceKeywordsDialog from '../components/affinity/PreferenceKeywordsDialog.vue'
import RelationshipContextForm from '../components/affinity/RelationshipContextForm.vue'

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
const showKeywordsDialog = ref(false)
const showContextForm = ref(false)
const pendingAnalysisForce = ref(false) // 记录待执行分析的force参数

// 计算是否有喜好关键词
const hasPreferenceKeywords = computed(() => {
  return analysisResult.value?.preference_compatibility?.weight !== undefined && 
         analysisResult.value.preference_compatibility.weight > 0
})

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

// 点击"开始分析"时先检查是否填写了关系信息
const handleStartAnalysis = async (force: boolean) => {
  if (!selectedConversationId.value) return
  
  try {
    const { has_context } = await getRelationshipContext(selectedConversationId.value)
    if (!has_context) {
      // 首次未填写 → 弹出表单
      pendingAnalysisForce.value = force
      showContextForm.value = true
      return
    }
  } catch (e) {
    console.warn('检查关系上下文失败，继续分析', e)
  }
  
  // 已填写或检查失败 → 直接分析
  startAnalysis(force)
}

// 关系信息表单保存后触发分析
const handleContextSaved = () => {
  startAnalysis(pendingAnalysisForce.value)
}

const startAnalysis = async (force: boolean) => {
  if (!selectedConversationId.value) return
  
  isAnalyzing.value = true
  progressPercent.value = 0
  progressStep.value = '准备中...'
  
  try {
    // 1. 启动异步分析，获取 task_id
    const taskId = await analyzeAffinity(selectedConversationId.value, force)
    
    // 2. 轮询后端真实进度
    await new Promise<void>((resolve, reject) => {
      const pollTimer = setInterval(async () => {
        try {
          const progress = await getAffinityProgress(taskId)
          
          if (progress.ok) {
            // 更新进度条
            progressPercent.value = progress.progress_percent
            progressStep.value = progress.current_step || '分析中...'
            
            if (progress.status === 'completed') {
              clearInterval(pollTimer)
              // 使用轮询返回的完整结果
              if (progress.result) {
                analysisResult.value = progress.result as AffinityAnalysisResult
              } else {
                // 兜底：从缓存获取结果
                const scores = await getAffinityScores(selectedConversationId.value!)
                if (scores) analysisResult.value = scores
              }
              resolve()
            } else if (progress.status === 'failed') {
              clearInterval(pollTimer)
              reject(new Error(progress.error || '分析失败'))
            }
          }
        } catch (pollErr) {
          console.error('轮询进度失败', pollErr)
          // 轮询出错不立即停止，可能是暂时性网络问题
        }
      }, 500)
    })
    
    progressPercent.value = 100
    progressStep.value = '分析完成'
    
    setTimeout(() => {
      isAnalyzing.value = false
    }, 500)
    
  } catch (e) {
    console.error('Analysis failed', e)
    progressStep.value = '分析失败: ' + (e instanceof Error ? e.message : String(e))
    setTimeout(() => {
      isAnalyzing.value = false
    }, 2000)
  }
}

watch(() => analysisResult.value, (newVal) => {
  if (newVal) {
    let start = 0
    const end = newVal.overall_score
    const duration = 1000
    const startTime = performance.now()
    
    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
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
  // Use CSS variables hex values hardcoded for SVG gradient unfortunately, 
  // or simple hex that matches theme.
  // Ideally should read from computed style but for gradient stops in SVG, hex is safer.
  if (score >= 80) return '#10b981' // success
  if (score >= 60) return '#3b82f6' // info
  if (score >= 40) return '#f59e0b' // warning
  return '#ef4444' // error
}

const radius = 55
const circumference = 2 * Math.PI * radius
const strokeDashoffset = computed(() => {
  const score = displayScore.value
  return circumference - (score / 100) * circumference
})

const scrollToDetails = (idSuffix: string) => {
  const el = document.getElementById(`detail-${idSuffix}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const handlePreferenceDisabledClick = () => {
  showKeywordsDialog.value = true
}

const handleKeywordsUpdated = async () => {
  // 关键词更新后重新分析
  if (selectedConversationId.value) {
    await startAnalysis(true)
  }
}
</script>

<style scoped>
.affinity-page {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-lg);
  padding-bottom: var(--ct-space-2xl);
}

.page-title h1 {
  margin: 0;
  color: var(--ct-color-primary);
  font-size: var(--ct-text-2xl);
  font-weight: 700;
}

.controls-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--ct-space-lg);
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
  flex: 1;
  max-width: 400px;
}

.label {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  font-weight: 500;
}

.ct-select {
  width: 100%;
  padding: var(--ct-space-sm) var(--ct-space-md);
  border-radius: var(--ct-radius-md);
  border: 1px solid var(--ct-border-color);
  background-color: var(--ct-bg-elevated);
  color: var(--ct-text-primary);
  outline: none;
  font-size: var(--ct-text-sm);
  transition: border-color 0.2s;
}

.ct-select:focus {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 2px var(--ct-color-primary-muted);
}

.actions {
  display: flex;
  gap: var(--ct-space-sm);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--ct-space-sm);
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
}

.progress-track {
  height: 8px;
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-full);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--ct-color-primary);
  transition: width 0.3s ease-out;
}

.empty-state {
  text-align: center;
  padding: var(--ct-space-3xl) 0;
  color: var(--ct-text-tertiary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--ct-space-lg);
  opacity: 0.5;
}

.empty-hint {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  margin-top: var(--ct-space-sm);
  opacity: 0.8;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ct-space-xl);
}

@media (min-width: 1024px) {
  .dashboard-grid {
    grid-template-columns: 350px 1fr;
  }
}

.col-left {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xl);
}

.col-right {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xl);
}

.cards-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ct-space-lg);
}

@media (min-width: 768px) {
  .cards-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.breakdowns-list {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-lg);
}

/* Overall Card Styling */
.overall-content {
  position: relative;
  text-align: center;
  min-height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.bg-decoration {
  position: absolute;
  top: -20px;
  right: -20px;
  width: 120px;
  height: 120px;
  opacity: 0.03;
  color: var(--ct-text-primary);
  pointer-events: none;
}

.card-label {
  font-size: var(--ct-text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ct-text-secondary);
  margin-bottom: var(--ct-space-xl);
  font-weight: 600;
}

.card-label-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-xl);
}

.score-ring-container {
  width: 160px;
  height: 160px;
  margin-bottom: var(--ct-space-xl);
  position: relative;
}

.circular-chart {
  display: block;
  width: 100%;
  height: 100%;
}

.circle-bg {
  fill: none;
  stroke: var(--ct-bg-tertiary);
  stroke-width: 8;
}

.circle {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 1s ease-out;
}

.score-text-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
}

.score-number {
  display: block;
  font-size: 3rem;
  font-weight: 700;
  line-height: 1;
  color: var(--ct-text-primary);
  font-family: var(--ct-font-display);
}

.score-label-small {
  font-size: 0.7rem;
  color: var(--ct-text-tertiary);
  margin-top: 4px;
}

.interpretation-box {
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  border-left: 4px solid var(--ct-color-primary);
  text-align: left;
  width: 100%;
}

.interpretation-text {
  margin: 0;
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: var(--ct-leading-relaxed);
}

.fade-in {
  animation: fadeIn 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
