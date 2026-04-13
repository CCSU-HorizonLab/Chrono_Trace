<template>
<section class="analytics-page ct-page">
  <!-- Brand Header -->
  <header class="analytics-header">
    <div v-if="selectedConversationId" class="user-profile-header fade-in">
      <div class="profile-main">
        <div class="profile-avatar-wrap">
          <div class="profile-avatar">
            <template v-if="subject?.avatar">
              <img :src="subject.avatar" alt="avatar" />
            </template>
            <template v-else>
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
            </template>
          </div>
        </div>
        <div class="profile-info">
          <div class="name-row">
            <h1 class="profile-name">{{ currentContactName }}</h1>
            <div class="contact-selector-wrap">
              <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId" :loading="loading"
                @update:conversation-id="onConversationChange" />
            </div>
          </div>
        </div>
      </div>
      
      <div class="header-actions-group">
        <CtButton variant="ghost" @click="showContextForm = true" :disabled="isGlobalAnalyzing">关系信息</CtButton>
        <CtButton variant="ghost" @click="showKeywordsDialog = true" :disabled="isGlobalAnalyzing">配置喜好</CtButton>
        <CtButton variant="primary" @click="handleStartGlobalAnalysis" :loading="isGlobalAnalyzing && !isStopping" class="btn-full-analysis">
          {{ isGlobalAnalyzing ? "分析中..." : (hasCachedAffinityAnalysis ? "重新全面分析" : "开始全面分析") }}
        </CtButton>
        <CtButton v-if="isGlobalAnalyzing" variant="danger" @click="handleStopAnalysis" :loading="isStopping" class="btn-stop-analysis" style="margin-left: 8px;">
          停止
        </CtButton>
      </div>
    </div>
  </header>

  <div v-if="!hasConversations" class="page-empty-state fade-in">
    <div class="page-empty-glow page-empty-glow-left"></div>
    <div class="page-empty-glow page-empty-glow-right"></div>

    <div class="page-empty-hero">
      <div class="page-empty-badge">History Ready</div>

      <div class="page-empty-illustration" aria-hidden="true">
        <div class="empty-orb empty-orb-main">🗂️</div>
        <div class="empty-orb empty-orb-small empty-orb-chat">💬</div>
        <div class="empty-orb empty-orb-small empty-orb-star">✦</div>
      </div>

      <h2>还没有历史记录</h2>
      <p class="page-empty-lead">当前还没有可分析的聊天会话，但这个页面不该再是空白的。</p>
      <p class="page-empty-hint">先去首页导入微信数据，完成后这里会自动显示联系人、分析入口和时间线内容。</p>
    </div>

    <div class="page-empty-grid">
      <div class="page-empty-card">
        <span class="page-empty-card-label">下一步</span>
        <strong>去首页导入聊天数据</strong>
        <p>导入完成后，历史记录页会自动恢复完整展示。</p>
      </div>

      <div class="page-empty-card">
        <span class="page-empty-card-label">导入后可查看</span>
        <strong>关系分析、互动特征、时间线</strong>
        <p>包括联系人切换、趋势图、词云和画像回廊等内容。</p>
      </div>

      <div class="page-empty-card page-empty-card-accent">
        <span class="page-empty-card-label">当前状态</span>
        <strong>暂无可分析会话</strong>
        <p>页面已保持可见，并提供明确的下一步引导。</p>
      </div>
    </div>
  </div>

  <!-- Global Progress -->
  <div v-if="isGlobalAnalyzing" class="extraction-progress">
    <div class="progress-bar">
      <div class="progress-fill" :style="{ width: `${globalProgressPercent}%` }"></div>
    </div>
    <div class="progress-text">
      <span v-if="gpuMode === 'gpu'" class="gpu-badge">GPU 加速</span>
      <span v-else class="cpu-badge">CPU 模式</span>
      {{ globalProgressPercent.toFixed(1) }}% - {{ globalProgressStep }}
    </div>
  </div>

  <!-- Tabs Navigation (Capsule Style) -->
  <div v-if="selectedConversationId" class="tabs-container">
    <div class="ct-tabs-capsule">
      <button class="menu-item" :class="{ active: currentTab === 'affinity' }"
        @click="currentTab = 'affinity'">关系洞察</button>
      <button class="menu-item" :class="{ active: currentTab === 'features' }"
        @click="currentTab = 'features'">互动特征</button>
      <button class="menu-item" :class="{ active: currentTab === 'content' }"
        @click="currentTab = 'content'">内容与时间线</button>
      <button class="menu-item" :class="{ active: currentTab === 'persona' }"
        @click="currentTab = 'persona'">用户画像回廊</button>
    </div>
  </div>

  <!-- TAB 1: Affinity -->
  <div v-show="currentTab === 'affinity' && selectedConversationId" class="tab-content fade-in">
    <div v-if="!analysisResult && !isGlobalAnalyzing" class="empty-state">
      <div class="empty-icon">📊</div>
      <p>请点击"开始全面分析"探索你们的亲密关系维度。</p>
      <p class="empty-hint">💡 首次分析需要1-2分钟进行数据特征提取和模型推理,请耐心等待</p>
    </div>

    <!-- Analyzing State -->
    <div v-if="isGlobalAnalyzing" class="empty-state">
      <div class="empty-icon spinning">⏳</div>
      <p>正在分析中，请耐心等待...</p>
      <p class="empty-hint">💡 我们正在处理特征提取和模型推理</p>
    </div>

    <!-- Affinity Dashboard Two-Col Layout -->
    <div v-if="analysisResult && !isGlobalAnalyzing" class="ct-grid-1-1 affinity-dashboard">
      <!-- Left Column: Overview & Cards -->
      <div class="col-main">
        <div class="summary-row">
          <CtCard class="score-overview-card">
            <div class="score-section">
              <div class="score-header">
                <span class="score-title">总体好感度</span>
                <div class="trend-badge" v-if="analysisResult.score_trend">
                  较上周 <span :class="analysisResult.score_trend >= 0 ? 'up' : 'down'">{{ analysisResult.score_trend > 0 ? '↑' : '↓' }}{{ Math.abs(analysisResult.score_trend) }}%</span>
                </div>
              </div>
              
              <div class="score-visual">
                <div class="ct-score-ring large">
                  <svg viewBox="0 0 120 120" class="circular-chart">
                    <circle class="circle-bg" cx="60" cy="60" r="50" fill="none" stroke="var(--ct-bg-tertiary)" stroke-width="10" />
                    <circle class="circle-fill" cx="60" cy="60" r="50" fill="none" 
                      stroke="var(--ct-color-primary)" stroke-width="10" stroke-linecap="round"
                      :stroke-dasharray="314.159" :stroke-dashoffset="314.159 * (1 - displayScore / 100)"
                      transform="rotate(-90 60 60)" />
                  </svg>
                  <div class="ct-score-text">
                    <span class="ct-score-num">{{ Math.round(displayScore) }}</span>
                    <span class="ct-score-unit">%</span>
                  </div>
                </div>
                
                <div class="qualitative-analysis">
                  <h3>定性分析</h3>
                  <div class="analysis-bubble">
                    <p>{{ analysisResult.overall_interpretation }}</p>
                  </div>
                </div>
              </div>
            </div>
          </CtCard>
        </div>

        <div class="dimension-cards-grid">
          <AffinityScoreCard v-if="analysisResult.emotional_resonance" title="情感共振率"
            :score="analysisResult.emotional_resonance.score" 
            :max-score="100"
            :weight="analysisResult.emotional_resonance.weight"
            :interpretation="analysisResult.emotional_resonance.interpretation" />
          <AffinityScoreCard v-if="analysisResult.chat_positivity" title="聊天积极度"
            :score="analysisResult.chat_positivity.score" 
            :max-score="100"
            :weight="analysisResult.chat_positivity.weight"
            :interpretation="analysisResult.chat_positivity.interpretation" />
          <AffinityScoreCard v-if="analysisResult.attitude_tendency" title="态度倾向"
            :score="analysisResult.attitude_tendency.score" 
            :max-score="100"
            :weight="analysisResult.attitude_tendency.weight"
            :interpretation="analysisResult.attitude_tendency.interpretation" />
          <AffinityScoreCard v-if="analysisResult.preference_compatibility" title="喜好兼容度"
            :score="analysisResult.preference_compatibility.score" 
            :max-score="100"
            :weight="analysisResult.preference_compatibility.weight"
            :interpretation="analysisResult.preference_compatibility.interpretation"
            :is-bonus="true"
            :bonus-value="analysisResult.preference_compatibility.bonus_scores?.preference_bonus" />
        </div>
      </div>

      <!-- Right Column: Radar & Breakdown -->
      <div class="col-side">
        <CtCard title="关系维度雷达图" class="radar-card">
          <div class="radar-wrapper">
            <DimensionRadar :dimension-scores="allDimensions" />
          </div>

          <div class="breakdowns-container">
            <SubScoreBreakdown v-if="analysisResult.emotional_resonance" title="情感共振率"
              :sub-scores="emotionalResonanceDisplaySubScores"
              :confidence-meta="analysisResult.emotional_resonance.confidence_meta" />
            <SubScoreBreakdown v-if="analysisResult.chat_positivity" title="聊天积极度"
              :sub-scores="analysisResult.chat_positivity.sub_scores" />
            <SubScoreBreakdown v-if="analysisResult.attitude_tendency" title="态度倾向"
              :sub-scores="analysisResult.attitude_tendency.sub_scores" />
            <SubScoreBreakdown v-if="analysisResult.preference_compatibility" title="喜好兼容度"
              :sub-scores="analysisResult.preference_compatibility.sub_scores" />
          </div>
        </CtCard>
      </div>
    </div>
  </div>

  <!-- TAB 2: Features -->
  <div v-show="currentTab === 'features' && selectedConversationId" class="tab-content fade-in">
    <div v-if="!hasFeatures && !isGlobalAnalyzing" class="empty-state">
      <div class="empty-icon">📈</div>
      <p>点击"开始全面分析"获取深度互动特征分析。</p>
      <p class="empty-hint">💡 互动特征包含：回响响应分布、主动性分析、话语权比例等客观指标</p>
    </div>

    <!-- Analyzing State -->
    <div v-if="isGlobalAnalyzing" class="empty-state">
      <div class="empty-icon spinning">⏳</div>
      <p>正在分析中，请耐心等待...</p>
      <p class="empty-hint">💡 我们正在处理特征提取和模型推理</p>
    </div>

    <div v-if="hasFeatures && !isGlobalAnalyzing" class="features-layout">
      <!-- Row 1: 4 small stat cards -->
      <div class="features-row-1">
        <CtCard class="feature-stat-card">
          <div class="stat-header">
            <span class="icon-dot green"><span class="inner-dot"></span></span>
            <span class="stat-title">平均响应时间</span>
          </div>
          <div class="stat-body">
            <div class="stat-main">
              <span class="stat-num">{{ featureStats.avgResponseTime ? formatTime(featureStats.avgResponseTime).replace(/[a-zA-Z]+$/, '') : '-' }}</span>
              <span class="stat-unit">{{ featureStats.avgResponseTime ? formatTime(featureStats.avgResponseTime).replace(/[0-9.<]+/, '') : '' }}</span>
            </div>
            <div class="stat-sub">
            </div>
          </div>
        </CtCard>

        <CtCard class="feature-stat-card">
          <div class="stat-header">
            <span class="icon-dot purple"><span class="inner-dot"></span></span>
            <span class="stat-title">对方主动率</span>
          </div>
          <div class="stat-body">
            <div class="stat-main">
              <span class="stat-num">{{ ((initiativeStats.initiativeRate || 0) * 100).toFixed(0) }}</span>
              <span class="stat-unit">%</span>
            </div>
            <div class="stat-sub">
              我发起 {{ ((1 - (initiativeStats.initiativeRate || 0)) * 100).toFixed(0) }}%
            </div>
          </div>
        </CtCard>

        <CtCard class="feature-stat-card">
          <div class="stat-header">
            <span class="icon-dot orange"><span class="inner-dot"></span></span>
            <span class="stat-title">字数投入比</span>
          </div>
          <div class="stat-body">
            <div class="stat-main">
              <span class="stat-num">{{ featureStats.wordRatio ? featureStats.wordRatio.toFixed(2) : '0' }} : 1</span>
            </div>
            <div class="stat-sub">
              我 : 对方
            </div>
          </div>
        </CtCard>

        <CtCard class="feature-stat-card">
          <div class="stat-header">
            <span class="icon-dot green"><span class="inner-dot"></span></span>
            <span class="stat-title">响应中位数</span>
          </div>
          <div class="stat-body">
            <div class="stat-main">
              <span class="stat-num">{{ featureStats.medianResponseTime ? formatTime(featureStats.medianResponseTime).replace(/[a-zA-Z]+$/, '') : '-' }}</span>
              <span class="stat-unit">{{ featureStats.medianResponseTime ? formatTime(featureStats.medianResponseTime).replace(/[0-9.<]+/, '') : '' }}</span>
            </div>
            <div class="stat-sub">
              最快 {{ responseTimeStats.min ? formatTime(responseTimeStats.min) : '-' }}
            </div>
          </div>
        </CtCard>
      </div>

      <!-- Row 2: 3 chart cards -->
      <div class="features-row-2">
        <CtCard class="feature-chart-card full-width-card">
          <h3 class="chart-card-title">响应时间区间</h3>
          <div class="horizontal-bars">
            <div class="h-bar-row" v-for="key in responseTimeStats.distributionKeys" :key="key" v-show="responseTimeStats.distribution?.[key]">
              <div class="h-bar-label">
                <span class="h-bar-label-main">{{ getMergedResponseTimeLabel(key) }}</span>
                <span class="h-bar-label-sub">{{ responseTimeStats.distribution?.[key] || 0 }} 次</span>
              </div>
              <div class="h-bar-track-wrap">
                <div class="h-bar-track">
                  <div class="h-bar-fill" :style="{ width: ((responseTimeStats.distribution?.[key] || 0) / (responseTimeStats.count || 1) * 100) + '%' }"></div>
                </div>
              </div>
              <span class="h-bar-value">{{ getResponseTimePercent(key) }}</span>
            </div>
            <div v-if="!responseTimeStats.count" style="font-size:12px;color:var(--ct-text-tertiary);text-align:center;">暂无数据</div>
          </div>
        </CtCard>
      </div>

      <div class="features-row-3">
        <CtCard class="feature-chart-card">
          <h3 class="chart-card-title">主动性分析</h3>
          <div class="initiative-content">
            <div class="donut-chart-box">
              <svg viewBox="0 0 100 100" class="donut-svg">
                <circle cx="50" cy="50" r="30" fill="transparent" stroke="#82ca9d" stroke-width="20" stroke-dasharray="188.5" stroke-dashoffset="0"></circle>
                <circle cx="50" cy="50" r="30" fill="transparent" stroke="#8884d8" stroke-width="20" :stroke-dasharray="`${(1 - (initiativeStats.initiativeRate || 0)) * 188.5} 188.5`" stroke-dashoffset="0"></circle>
              </svg>
              <div class="donut-legend">
                <div class="legend-item"><span class="legend-dot purple"></span>我发起 {{ ((1 - (initiativeStats.initiativeRate || 0)) * 100).toFixed(0) }}%</div>
                <div class="legend-item"><span class="legend-dot green"></span>对方发起 {{ ((initiativeStats.initiativeRate || 0) * 100).toFixed(0) }}%</div>
              </div>
            </div>
            <div class="initiative-box">
              <span class="box-text" v-html="initiativeStats.interpretation ? initiativeStats.interpretation.replace(/\n/g, '<br>') : '暂无数据'"></span>
            </div>
          </div>
        </CtCard>

        <CtCard class="feature-chart-card">
          <h3 class="chart-card-title">字数投入对比</h3>
          <div class="word-content">
            <div class="v-bars">
              <div class="v-bar-col">
                <div class="v-bar-track"><div class="v-bar-fill purple" :style="{ height: wordCountsStats.userCharCount || wordCountsStats.otherCharCount ? (wordCountsStats.userCharCount / Math.max(wordCountsStats.userCharCount, wordCountsStats.otherCharCount, 1) * 100) + '%' : '0%' }"></div></div>
                <div class="v-bar-label">我的字数<br><strong>{{ formatNumber(wordCountsStats.userCharCount) }}</strong></div>
              </div>
              <div class="v-bar-col">
                <div class="v-bar-track"><div class="v-bar-fill red" :style="{ height: wordCountsStats.userCharCount || wordCountsStats.otherCharCount ? (wordCountsStats.otherCharCount / Math.max(wordCountsStats.userCharCount, wordCountsStats.otherCharCount, 1) * 100) + '%' : '0%' }"></div></div>
                <div class="v-bar-label">对方字数<br><strong>{{ formatNumber(wordCountsStats.otherCharCount) }}</strong></div>
              </div>
            </div>
            <div class="word-box">
              <div class="word-box-title">投入比 <span class="highlight">{{ wordCountsStats.charRatio ? wordCountsStats.charRatio.toFixed(2) : 0 }}x</span></div>
              <div class="word-box-desc" v-html="wordCountsStats.interpretation ? wordCountsStats.interpretation.replace(/\n/g, '<br>') : '暂无数据'"></div>
            </div>
          </div>
        </CtCard>
      </div>

      <!-- Row 4: Calendar -->
      <div class="features-row-4">
        <CtCard class="feature-calendar-card">
          <div class="calendar-header">
            <div class="calendar-text">
              <h3>活跃日历</h3>
              <p>按天展示会话强度分布，颜色越深代表互动越集中。</p>
            </div>
            <label class="calendar-year-picker">
              <span>年份</span>
              <select :value="activityCalendar.year" @change="handleActivityYearChange">
                <option v-for="year in activityCalendar.years" :key="year" :value="year">{{ year }}</option>
              </select>
            </label>
          </div>

          <div class="calendar-summary-card">
            <div class="calendar-summary-grid">
              <div class="calendar-summary-item">
                <span class="calendar-summary-label">活跃天数</span>
                <strong>{{ activityCalendar.summary.active_days }}</strong>
              </div>
              <div class="calendar-summary-item">
                <span class="calendar-summary-label">总消息数</span>
                <strong>{{ formatNumber(activityCalendar.summary.total_messages) }}</strong>
              </div>
              <div class="calendar-summary-item">
                <span class="calendar-summary-label">当前连续活跃</span>
                <strong>{{ activityCalendar.summary.current_streak }} 天</strong>
              </div>
              <div class="calendar-summary-item">
                <span class="calendar-summary-label">最长连续活跃</span>
                <strong>{{ activityCalendar.summary.longest_streak }} 天</strong>
              </div>
              <div class="calendar-summary-item peak-day">
                <span class="calendar-summary-label">峰值日期</span>
                <strong>{{ activityCalendar.summary.peak_day?.date || '--' }}</strong>
                <em v-if="activityCalendar.summary.peak_day">
                  {{ activityCalendar.summary.peak_day.message_count }} 条消息 / {{ activityCalendar.summary.peak_day.session_count }} 场会话
                </em>
              </div>
            </div>
          </div>

          <div v-if="activityCalendar.entries.length" class="calendar-chart-shell">
            <div class="calendar-legend">
              <span>低活跃</span>
              <div class="calendar-legend-scale">
                <i></i>
                <i></i>
                <i></i>
                <i></i>
                <i></i>
              </div>
              <span>高活跃</span>
            </div>
            <div ref="activityCalendarChart" class="calendar-chart"></div>
          </div>

          <div v-else class="calendar-empty">
            当前年份暂无活跃记录
          </div>
        </CtCard>
      </div>
    </div>
  </div>

  <!-- TAB 3: Content & Timeline -->
  <div v-show="currentTab === 'content' && selectedConversationId" class="tab-content fade-in">
    <DateRangeFilter
      :dates="dates"
      :loading="loading"
      @update:dates="onDatesChange"
      @refresh="loadAnalysis"
      @export="handleExport"
    />

    <div class="ct-grid-1-1 affinity-dashboard content-timeline-dashboard">
      <div class="col-main">
        <div class="main-content">
          <CtCard title="情感走势图" class="chart-card">
            <div v-if="analysis.timeseries.length === 0" class="empty-state inline-empty-state">
              <div class="empty-icon">-</div>
              <p>趋势数据暂未生成</p>
              <p class="empty-hint">当前时间范围内缺少足够的情感样本，可以尝试扩大日期范围。</p>
            </div>
            <EmotionLineChart v-else :timeseries="analysis.timeseries" />
          </CtCard>
          <CtCard title="关键词云" class="chart-card">
            <div v-if="analysis.wordcloud.length === 0" class="empty-state inline-empty-state">
              <div class="empty-icon">-</div>
              <p>当前时间范围内没有可用文本消息</p>
              <p class="empty-hint">可以切换到近30天、半年或全部历史查看。</p>
            </div>
            <WordCloud v-else :words="analysis.wordcloud" @select="onWordSelect" />
          </CtCard>
        </div>
      </div>
      <div class="col-side">
        <div class="subject-section">
          <SubjectCard :subject="subject" :has-analysis="hasContentAnalysis" />
        </div>
        <div class="ct-card timeline-section-card">
          <div class="section-header">
            <h3>对话时间线</h3>
            <p class="section-subtitle">按时间顺序展开的交流记录</p>
          </div>
          <div class="timeline-scroll-area">
            <ConversationTimeline :sessions="sessions" :loading="loadingSessions" />
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 4: Persona Gallery -->
  <div v-show="currentTab === 'persona' && selectedConversationId" class="tab-content fade-in">
    <div class="persona-tab-shell">
      <PersonaGallery
        :loading="loadingPersonaProfile"
        :contact-name="currentContactName"
        :profile="personaProfile"
        :profile-meta="personaProfileMeta"
        :analysis="analysis"
        :analysis-result="analysisResult"
        :feature-stats="featureStats"
        :sessions="sessions"
        :activity-calendar-summary="activityCalendar.summary"
        :current-range-label="currentRangeLabel"
      />
    </div>
  </div>

  <!-- Dialogs -->
  <PreferenceKeywordsDialog v-if="selectedConversationId" v-model="showKeywordsDialog"
    :conversation-id="selectedConversationId" @updated="handleKeywordsUpdated" />
  <RelationshipContextForm v-if="selectedConversationId" v-model="showContextForm"
    :conversation-id="selectedConversationId" @saved="handleContextSaved" />
</section>

</template>

<script lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { bridgeReady, api, type AnalysisDeviceMode } from '@/api/bridge'
import { analyzeAffinity, getAffinityScores, getAffinityProgress, getRelationshipContext, type AffinityAnalysisResult } from '@/api/affinity'

import FiltersBar from '@/components/analytics/FiltersBar.vue'
import DateRangeFilter from '@/components/analytics/DateRangeFilter.vue'
import SubjectCard from '@/components/analytics/SubjectCard.vue'
import EmotionLineChart from '@/components/charts/EmotionLineChart.vue'
import WordCloud from '@/components/charts/WordCloud.vue'
import ConversationTimeline from '@/components/timeline/ConversationTimeline.vue'

import AffinityScoreCard from '@/components/affinity/AffinityScoreCard.vue'
import DimensionRadar from '@/components/affinity/DimensionRadar.vue'
import SubScoreBreakdown from '@/components/affinity/SubScoreBreakdown.vue'
import WeightInfoTooltip from '@/components/affinity/WeightInfoTooltip.vue'
import PreferenceKeywordsDialog from '@/components/affinity/PreferenceKeywordsDialog.vue'
import RelationshipContextForm from '@/components/affinity/RelationshipContextForm.vue'
import CtCard from '@/components/base/CtCard.vue'
import CtButton from '@/components/base/CtButton.vue'
import PersonaGallery from '@/components/persona/PersonaGallery.vue'
import { showDialog, showConfirm } from '@/utils/dialog'

type Conversation = { id: number; name: string; username: string; message_count: number; last_message_time: string }
type Session = { id: number; start_time: number; end_time: number; duration: number; message_count: number; initiator: string; messages: any[] }
type TimeseriesPoint = {
    ts: string
    score: number
    positive?: number
    neutral?: number
    negative?: number
    msgCount?: number
    userScore?: number
    otherScore?: number
}
type SubjectStats = { msgCount: number; avgScore: number; maxDay?: string; minDay?: string }
type Subject = { id?: string | number; name: string; avatar?: string; stats?: SubjectStats }
type Analysis = { subject?: Subject; timeseries: TimeseriesPoint[]; wordcloud: { word: string; weight: number }[] }
type ContactProfile = {
    personality_tags?: string[]
    chat_style?: string
    interests?: string[]
    relationship_note?: string
    communication_tips?: string
}
type ActivityCalendarEntry = {
    date: string
    message_count: number
    session_count: number
    active_duration_seconds: number
    user_initiated_sessions: number
    other_initiated_sessions: number
    activity_score: number
    activity_level: number
    first_time: string
    last_time: string
}
type ActivityCalendarSummary = {
    active_days: number
    total_messages: number
    current_streak: number
    longest_streak: number
    peak_day: null | {
        date: string
        message_count: number
        session_count: number
        activity_score: number
    }
    global_first_session_start_time: number | null
    global_peak_session: null | {
        start_time: number
        message_count: number
    }
}
type ActivityCalendarData = {
    year: number
    years: number[]
    entries: ActivityCalendarEntry[]
    summary: ActivityCalendarSummary
    max_activity_score: number
}

export default {
    components: {
        FiltersBar, DateRangeFilter, SubjectCard, EmotionLineChart, WordCloud, ConversationTimeline,
        AffinityScoreCard, DimensionRadar, SubScoreBreakdown, WeightInfoTooltip,
        PreferenceKeywordsDialog, RelationshipContextForm, CtCard, CtButton, PersonaGallery
    },
    setup() {
        const currentTab = ref('affinity')

        // Core State
        const conversations = ref<Conversation[]>([])
        const selectedConversationId = ref<number | null>(null)
        const dates = reactive({ from: '', to: '' })
        const loading = ref(false)
        const loadingSessions = ref(false)
        const error = ref('')
        const analysis = reactive<Analysis>({ timeseries: [], wordcloud: [] })
        const subject = ref<Subject | undefined>(undefined)
        const sessions = ref<Session[]>([])
        const personaProfile = ref<ContactProfile | null>(null)
        const loadingPersonaProfile = ref(false)
        const personaProfileMeta = reactive({
            createdAt: null as number | null,
            expiresAt: null as number | null,
            expired: false,
            estimatedTokens: 0
        })
        const responseTimeChart = ref<HTMLDivElement | null>(null)
        const activityCalendarChart = ref<HTMLDivElement | null>(null)
        const wordCountChart = ref<HTMLDivElement | null>(null)
        let responseTimeChartInstance: echarts.ECharts | null = null
        let activityCalendarChartInstance: echarts.ECharts | null = null
        let wordCountChartInstance: echarts.ECharts | null = null

        const stats = ref<{ totalMessages: number; avgSentiment: number; activeDays: number; sessionCount: number } | null>(null)
        
        const analysisResult = ref<AffinityAnalysisResult | null>(null)
        const displayScore = ref(0)
        const showKeywordsDialog = ref(false)
        const showContextForm = ref(false)
        const analysisLaunchPending = ref(false)
        const isGlobalAnalyzing = ref(false)
        const isStopping = ref(false)
        const activeTimer = ref<any>(null)
        const globalProgressPercent = ref(0)
        const globalProgressStep = ref('')
        const analysisDeviceMode = ref<AnalysisDeviceMode>('auto')
        const gpuMode = ref<'gpu' | 'cpu'>('cpu')

        const hasFeatures = ref(false)
        
        const featureStats = ref({ avgResponseTime: 0, medianResponseTime: 0, initiativeRate: 0, wordRatio: 0 })
        const responseTimeStats = ref({ count: 0, avg: 0, median: 0, max: 0, mode: '', distribution: {} as Record<string, number>, distributionKeys: [] as string[] })
        const initiativeStats = ref({ totalSessions: 0, userInitiatedSessions: 0, otherInitiatedSessions: 0, initiativeRate: 0, interpretation: '' })
        const wordCountsStats = ref({ userCharCount: 0, otherCharCount: 0, charRatio: 0, interpretation: '' })
        const activityCalendar = ref<ActivityCalendarData>({ year: new Date().getFullYear(), years: [], entries: [], summary: { active_days: 0, total_messages: 0, current_streak: 0, longest_streak: 0, peak_day: null, global_first_session_start_time: null, global_peak_session: null }, max_activity_score: 0 })
        
        let cancelCurrentAnalysis: (() => void) | null = null

        const responseTimeBucketGroups: Record<string, string[]> = {
            '<10m': ['<1m', '1m-10m'],
            '10m-1h': ['10m-30m', '30m-1h'],
            '1h-24h': ['1h-6h', '6h-24h'],
            '>1d': ['>1d']
        }

        const currentRangeLabel = computed(() => {
            if (!dates.from || !dates.to) return '默认近30天，可切换时间范围'
            return `${dates.from} 至 ${dates.to}`
        })
        const shouldLoadContentAnalysis = computed(() => {
            return currentTab.value === 'content' || currentTab.value === 'persona'
        })
        const hasContentAnalysis = computed(() => {
            return Boolean(subject.value?.stats && (
                (subject.value.stats.msgCount || 0) > 0 ||
                analysis.wordcloud.length > 0 ||
                analysis.timeseries.length > 0
            ))
        })
        const hasConversations = computed(() => conversations.value.length > 0)

        const currentContactName = computed(() => {
            if (!selectedConversationId.value) return '选择联系人'
            return conversations.value.find(c => c.id === selectedConversationId.value)?.name || '选择联系人'
        })

        const hasPreferenceKeywords = computed(() => {
            const preference = analysisResult.value?.preference_compatibility
            if (!preference) return false
            return (preference.bonus_scores?.preference_bonus ?? 0) > 0
        })
        const hasCachedAffinityAnalysis = computed(() => Boolean(analysisResult.value))

        const allDimensions = computed(() => {
            if (!analysisResult.value) return {}
            return {
                emotional_resonance: analysisResult.value.emotional_resonance || undefined,
                chat_positivity: analysisResult.value.chat_positivity || undefined,
                attitude_tendency: analysisResult.value.attitude_tendency || undefined,
                preference_compatibility: analysisResult.value.preference_compatibility || undefined
            }
        })

        const emotionalResonanceDisplaySubScores = computed(() => {
            const subScores = analysisResult.value?.emotional_resonance?.sub_scores
            if (!subScores) return {}

            const {
                empathy_recognition,
                negative_resolution,
                ...baseSubScores
            } = subScores

            return baseSubScores
        })

        const radius = 50
        const circumference = 2 * Math.PI * radius
        const strokeDashoffset = computed(() => circumference - (displayScore.value / 100) * circumference)

        function formatNumber(num: number): string {
            if (!num) return '0'
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
            return num.toString()
        }

        function formatTime(seconds: number): string {
            if (seconds === undefined || seconds === null) return '-'
            if (seconds < 1 && seconds > 0) return '<1s'
            if (seconds === 0) return '0s'
            if (seconds < 60) return `${Math.round(seconds)}s`
            if (seconds < 3600) return `${Math.round(seconds / 60)}m`
            if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
            return `${(seconds / 86400).toFixed(1)}d`
        }

        function getResponseTimeLabel(rangeKey: string): string {
            const labelMap: Record<string, string> = {
                '<1m': '1分钟内',
                '1m-10m': '1到10分钟',
                '10m-30m': '10到30分钟',
                '30m-1h': '30分钟到1小时',
                '1h-6h': '1到6小时',
                '6h-24h': '6到24小时',
                '>1d': '1天以上'
            }
            return labelMap[rangeKey] || rangeKey
        }

        function getResponseTimePercent(rangeKey: string): string {
            const count = responseTimeStats.value.distribution?.[rangeKey] || 0
            const total = responseTimeStats.value.count || 1
            return `${((count / total) * 100).toFixed(1)}%`
        }

        function getMergedResponseTimeLabel(rangeKey: string): string {
            const labelMap: Record<string, string> = {
                '<10m': '10分钟内',
                '10m-1h': '10分钟 - 1小时',
                '1h-24h': '1小时 - 1天',
                '>1d': '1天以上'
            }
            return labelMap[rangeKey] || rangeKey
        }

        function aggregateResponseTimeDistribution(distribution: Record<string, number> | null | undefined): Record<string, number> | null {
            if (!distribution) return null

            return Object.entries(responseTimeBucketGroups).reduce<Record<string, number>>((acc, [targetKey, sourceKeys]) => {
                acc[targetKey] = sourceKeys.reduce((sum, sourceKey) => sum + (distribution[sourceKey] || 0), 0)
                return acc
            }, {})
        }

        function getConversationAnchorDate(conversationId?: number | null): Date {
            const conversation = conversations.value.find(c => c.id === conversationId)
            const rawLastMessageTime = conversation?.last_message_time?.trim()
            if (rawLastMessageTime) {
                const normalized = rawLastMessageTime.replace(' ', 'T')
                const parsed = new Date(normalized)
                if (!Number.isNaN(parsed.getTime())) {
                    return parsed
                }
            }
            return new Date()
        }

        function setDefaultDates(days = 7, anchorDate?: Date) {
            const to = anchorDate ? new Date(anchorDate) : new Date()
            const from = new Date(to)
            from.setDate(to.getDate() - (days - 1))
            dates.from = from.toISOString().slice(0, 10)
            dates.to = to.toISOString().slice(0, 10)
        }

        function applyAnalysisDeviceMode(mode: AnalysisDeviceMode) {
            analysisDeviceMode.value = mode
            gpuMode.value = mode === 'gpu' ? 'gpu' : 'cpu'
        }

        function hasPersistedAnalysisDeviceMode(mode: unknown): mode is AnalysisDeviceMode {
            return mode === 'gpu' || mode === 'cpu'
        }

        function hasExistingFeatureData(
            responseTimes: any,
            initiative: any,
            wordCounts: any,
            activity: any
        ) {
            const hasResponseTimes = Boolean(responseTimes?.success && responseTimes.data && responseTimes.data.count > 0)
            const hasInitiative = Boolean(
                initiative?.success &&
                initiative.data &&
                Number(initiative.data.total_sessions || 0) > 0
            )
            const overallWordCounts = wordCounts?.data?.overall
            const hasWordCounts = Boolean(
                wordCounts?.success &&
                overallWordCounts &&
                (
                    Number(overallWordCounts.user_char_count || 0) > 0 ||
                    Number(overallWordCounts.other_char_count || 0) > 0
                )
            )
            const hasActivity = Boolean(
                activity?.success &&
                activity.data &&
                Array.isArray(activity.data.heatmap) &&
                activity.data.heatmap.length > 0
            )

            return hasResponseTimes || hasInitiative || hasWordCounts || hasActivity
        }

        async function loadAnalysisDeviceMode() {
            try {
                const settings = await api.get_settings()
                const nextMode = settings?.analysis_device_mode
                applyAnalysisDeviceMode(nextMode === 'gpu' || nextMode === 'cpu' || nextMode === 'auto' ? nextMode : 'auto')
            } catch (e) {
                applyAnalysisDeviceMode('auto')
            }
        }

        function refreshSummaryStats() {
            const timeseries = analysis.timeseries || []
            const totalSentiment = timeseries.reduce((sum: number, p: any) => sum + (p.score || 0), 0)
            stats.value = {
                totalMessages: subject.value?.stats?.msgCount || 0,
                avgSentiment: timeseries.length ? parseFloat((totalSentiment / timeseries.length).toFixed(2)) : 0,
                activeDays: timeseries.length,
                sessionCount: sessions.value.length
            }
        }

        async function loadConversations() {
            try {
                await bridgeReady()
                const res = await api.get_conversation_list()
                if (res.ok) {
                    conversations.value = res.conversations
                    if (conversations.value.length > 0 && !selectedConversationId.value) {
                        onConversationChange(conversations.value[0].id)
                    } else if (conversations.value.length === 0) {
                        selectedConversationId.value = null
                    }
                }
            } catch (e: any) { console.error('加载联系人失败', e) }
        }

        async function onConversationChange(id: number) {
            selectedConversationId.value = id
            setDefaultDates(30, getConversationAnchorDate(id))
            hasFeatures.value = false
            analysisResult.value = null
            loadPersonaProfile(id)
            loadSessions()
            tryLoadExistingFeatures()
            tryLoadAffinityScores()
            if (shouldLoadContentAnalysis.value) {
                loadAnalysis()
            }
        }

        function resetPersonaProfile() {
            personaProfile.value = null
            personaProfileMeta.createdAt = null
            personaProfileMeta.expiresAt = null
            personaProfileMeta.expired = false
            personaProfileMeta.estimatedTokens = 0
        }

        async function loadPersonaProfile(conversationId = selectedConversationId.value || undefined) {
            if (!conversationId) {
                resetPersonaProfile()
                return
            }

            const conversation = conversations.value.find((item) => item.id === conversationId)
            const displayName = conversation?.name
            if (!displayName) {
                resetPersonaProfile()
                return
            }

            loadingPersonaProfile.value = true
            try {
                const res = await api.get_contact_profile(displayName)
                if (res.ok && res.has_profile) {
                    personaProfile.value = res.profile || null
                    personaProfileMeta.createdAt = res.created_at || null
                    personaProfileMeta.expiresAt = res.expires_at || null
                    personaProfileMeta.expired = Boolean(res.expired)
                    personaProfileMeta.estimatedTokens = Number(res.estimated_tokens || 0)
                } else {
                    resetPersonaProfile()
                    personaProfileMeta.estimatedTokens = Number(res?.estimated_tokens || 0)
                }
            } catch (e) {
                resetPersonaProfile()
            } finally {
                loadingPersonaProfile.value = false
            }
        }

        function onDatesChange(newDates: { from: string; to: string }) {
            dates.from = newDates.from
            dates.to = newDates.to
            loadAnalysis()
        }

        const handleExport = () => {
            // Note: export function might just redirect or emit. Assuming an unimplemented function for now
            console.warn('Export to CSV is clicked.')
            showDialog('导出功能尚未实现。')
        }

        async function tryLoadAffinityScores() {
            if (!selectedConversationId.value) return
            try {
                const scores = await getAffinityScores(selectedConversationId.value)
                if (scores && scores.cache_version >= 4) {
                    analysisResult.value = scores
                } else {
                    analysisResult.value = null
                }
            } catch (e) {
                analysisResult.value = null
            }
        }

        async function tryLoadExistingFeatures() {
            if (!selectedConversationId.value) return
            hasFeatures.value = false
            try {
                const [rtData, iniData, wcData, activityData] = await Promise.all([
                    api.get_response_times(selectedConversationId.value),
                    api.get_initiative_stats(selectedConversationId.value),
                    api.get_word_counts(selectedConversationId.value, false),
                    api.get_activity_calendar(selectedConversationId.value)
                ])
                if (hasExistingFeatureData(rtData, iniData, wcData, activityData)) {
                    hasFeatures.value = true
                    await Promise.all([
                        loadFeatureData(),
                        loadActivityCalendar()
                    ])
                }
            } catch (e) { }
        }

        async function loadActivityCalendar(year?: number) {
            if (!selectedConversationId.value) return
            try {
                const res = await api.get_activity_calendar(selectedConversationId.value, year)
                if (res.success && res.data) {
                    activityCalendar.value = res.data
                    if (currentTab.value === 'features') {
                        await nextTick()
                        renderActivityCalendar()
                    }
                }
            } catch (e) { console.error(e) }
        }

        async function loadAnalysis() {
            if (!selectedConversationId.value) return
            loading.value = true
            error.value = ''
            try {
                await bridgeReady()
                const res = await api.get_analysis({ conversation_id: selectedConversationId.value, from: dates.from, to: dates.to })
                if (res.error) { error.value = res.error; return }
                analysis.timeseries = res?.timeseries ?? []
                analysis.wordcloud = res?.wordcloud ?? []
                subject.value = res?.subject ?? subject.value
                refreshSummaryStats()
            } catch (e: any) {
                error.value = e?.message || '加载失败'
            } finally { loading.value = false }
        }

        async function loadSessions() {
            if (!selectedConversationId.value) return
            loadingSessions.value = true
            try {
                await bridgeReady()
                const res = await api.get_sessions(selectedConversationId.value, 50, 0)
                if (res.success && res.data && res.data.sessions) {
                    sessions.value = res.data.sessions.map((s: any) => ({
                        ...s,
                        start_time: s.start_time * 1000,
                        end_time: s.end_time * 1000,
                        duration: (s.end_time || 0) - (s.start_time || 0)
                    }))
                    refreshSummaryStats()
                }
            } catch (e) { console.error(e) } finally { loadingSessions.value = false }
        }

        const handleStartGlobalAnalysis = async () => {
            if (!selectedConversationId.value) return
            if (isGlobalAnalyzing.value) return
            if (analysisLaunchPending.value || isGlobalAnalyzing.value) return
            analysisLaunchPending.value = true
            try {
                const { has_context } = await getRelationshipContext(selectedConversationId.value)
                if (!has_context) {
                    showContextForm.value = true
                    analysisLaunchPending.value = false
                    return
                }
            } catch (e) { }

            try {
                const modelStatus = await api.check_analysis_model_status()
                if (!modelStatus.ok || !modelStatus.analysis_available) {
                    await showDialog({
                        title: '无法开始分析',
                        message:
                            '当前因网络原因无法使用分析功能，且本地没有可用的模型缓存。\n' +
                            '请检查网络，或先在网络正常时完成一次模型缓存后再试。'
                    })
                    analysisLaunchPending.value = false
                    return
                }
            } catch (e) {
                await showDialog({
                    title: '无法开始分析',
                    message:
                        '当前无法确认分析模型状态，已终止本次分析。\n' +
                        '请检查网络或稍后重试。'
                })
                analysisLaunchPending.value = false
                return
            }

            if (!hasPersistedAnalysisDeviceMode(analysisDeviceMode.value)) {
                applyAnalysisDeviceMode('cpu')
                try {
                const gpuStatus = await api.check_gpu_status()
                if (gpuStatus.ok && gpuStatus.cuda_available) {
                    const memInfo = gpuStatus.gpu_memory_total_mb
                        ? ` (${(gpuStatus.gpu_memory_total_mb / 1024).toFixed(1)}GB)`
                        : ''
                    const useGpu = await showConfirm({
                        title: 'GPU 加速可用',
                        message:
                            `检测到 GPU: ${gpuStatus.gpu_name}${memInfo}\n` +
                            `CUDA ${gpuStatus.cuda_version} | PyTorch ${gpuStatus.torch_version}\n\n` +
                            '启用 GPU 加速后，分析速度预计可提升 5-10 倍。\n是否启用 GPU 加速？\n\n' +
                            '💡 此选项可随时在「通用设置」页面修改。'
                    })
                    const nextMode: AnalysisDeviceMode = useGpu ? 'gpu' : 'cpu'
                    await api.set_settings({ analysis_device_mode: nextMode })
                    applyAnalysisDeviceMode(nextMode)
                } else if (gpuStatus.ok && gpuStatus.has_nvidia_gpu) {
                    const doInstall = await showConfirm({
                        title: '检测到 GPU 硬件',
                        message:
                            '检测到您的计算机配备了 NVIDIA GPU，但当前未安装支持 CUDA 的环境依赖，导致无法启用 GPU 加速。\n\n' +
                            '是否现在进行【一键配置】？这将自动下载和安装所需的 PyTorch 环境（通常需要几分钟，会在后台执行）。'
                    })
                    if (doInstall) {
                        try {
                            const installRes = await api.start_gpu_install()
                            if (installRes.ok) {
                                await showDialog({
                                    title: '开始配置',
                                    message: 'GPU 环境配置已在后台启动，您可以随时前往「通用设置」页面查看实时安装进度。\n本次分析将暂时使用 CPU 模式进行，安装完成后下次可使用 GPU 加速。'
                                })
                            } else {
                                await showDialog({ title: '安装启动失败', message: installRes.error || '未知错误' })
                            }
                        } catch(e) {}
                    } else {
                        await showDialog({
                            title: 'CPU 模式',
                            message: '将使用 CPU 模式进行分析。'
                        })
                    }
                    await api.set_settings({ analysis_device_mode: 'cpu' })
                    applyAnalysisDeviceMode('cpu')
                } else {
                    await showDialog({
                        title: 'CPU 模式',
                        message:
                            'GPU 加速不可用，将使用 CPU 模式进行分析。\n' +
                            '如需启用 GPU，请安装支持 CUDA 的 PyTorch 版本。\n\n' +
                            '💡 此选项可随时在「通用设置」页面修改。'
                    })
                    await api.set_settings({ analysis_device_mode: 'cpu' })
                    applyAnalysisDeviceMode('cpu')
                }
                } catch (e) {
                    await api.set_settings({ analysis_device_mode: 'cpu' })
                    applyAnalysisDeviceMode('cpu')
                }
            }
            await startGlobalAnalysis()
        }

        const handleContextSaved = () => handleStartGlobalAnalysis()
        const handleKeywordsUpdated = async () => { if (selectedConversationId.value) await startGlobalAnalysis() }


        async function handleStopAnalysis() {
            if (!isGlobalAnalyzing.value) return
            isStopping.value = true
            try {
                await bridgeReady()
                if (api.cancel_analysis) {
                    await api.cancel_analysis()
                }
                // Do not instantly change UI. Let the polling interval catch the cancelled status.
            } catch (e) {
                console.error("取消分析失败", e)
                isStopping.value = false
            }
        }

        async function startGlobalAnalysis() {
            let isCancelled = false
            if (!selectedConversationId.value) return
            isGlobalAnalyzing.value = true
            globalProgressPercent.value = 0
            globalProgressStep.value = '即将开始...'

            try {
                // Stage 1: Feature Extraction
                globalProgressStep.value = '正在提取客观互动特征...'
                globalProgressPercent.value = 5
                const extractRes = await api.extract_features(selectedConversationId.value, {
                    analysis_device_mode: analysisDeviceMode.value
                })
                
                if (!isGlobalAnalyzing.value) {
                    throw new Error('分析已取消')
                }
                
                if (!extractRes.success && !extractRes.ok) {
                    if (extractRes.error && String(extractRes.error).includes('取消')) {
                        throw new Error('分析已取消')
                    }
                    throw new Error(extractRes.error || '特征提取失败')
                }

                if (extractRes.success || extractRes.ok) {
                    const taskId = (extractRes.data || extractRes).task_id
                    if ((extractRes.data || extractRes).status !== 'completed') {
                        await new Promise<void>((resolve, reject) => {
                            cancelCurrentAnalysis = () => reject(new Error('分析已取消'))
                            activeTimer.value = setInterval(async () => {
                                try {
                                    const prog = await api.get_extraction_progress(taskId)
                                    const d = prog.data || prog
                                    if (prog.success || prog.ok) {
                                        globalProgressPercent.value = 5 + (d.progress || 0) * 0.45
                                        globalProgressStep.value = `[特征分析] ${d.message || d.current_step || '分析中...'}`
                                        if (d.status === 'completed') { clearInterval(activeTimer.value); resolve() }
                                        else if (d.status === 'failed' || d.status === 'cancelled') { clearInterval(activeTimer.value); reject(new Error(d.error || '分析已取消')) } // Don't block affinity if features fail
                                    }
                                } catch (e) { clearInterval(activeTimer.value); resolve() }
                            }, 500)
                        })
                    }
                    hasFeatures.value = true
                    await Promise.all([
                        loadFeatureData(),
                        loadSessions(),
                        loadActivityCalendar()
                    ])
                }

                if (!isGlobalAnalyzing.value) {
                    throw new Error('分析已取消')
                }

                // Stage 2: Affinity Model
                globalProgressPercent.value = 50
                globalProgressStep.value = '正在进行深度关系推理...'
                const affinityTaskId = await analyzeAffinity(selectedConversationId.value, true)
                
                if (!isGlobalAnalyzing.value) {
                    throw new Error('分析已取消')
                }
                
                await new Promise<void>((resolve, reject) => {
                    cancelCurrentAnalysis = () => reject(new Error('分析已取消'))
                    activeTimer.value = setInterval(async () => {
                        try {
                            const prog = await getAffinityProgress(affinityTaskId)
                            if (prog.ok) {
                                globalProgressPercent.value = 50 + prog.progress_percent * 0.5
                                globalProgressStep.value = `[深度推理] ${prog.current_step || '分析中...'}`
                                if (prog.status === 'completed') {
                                    clearInterval(activeTimer.value)
                                    if (prog.result) {
                                        analysisResult.value = prog.result as AffinityAnalysisResult
                                    }

                                    const scores = await getAffinityScores(selectedConversationId.value!)
                                    if (
                                        scores &&
                                        (
                                            !analysisResult.value ||
                                            (scores.cache_updated_at || 0) >= (analysisResult.value.cache_updated_at || 0)
                                        )
                                    ) {
                                        analysisResult.value = scores
                                    }
                                    const followUpTasks = [
                                        loadSessions(),
                                        loadActivityCalendar(activityCalendar.value.year)
                                    ]
                                    if (shouldLoadContentAnalysis.value) {
                                        followUpTasks.unshift(loadAnalysis())
                                    }
                                    await Promise.all(followUpTasks)
                                    resolve()
                                } else if (prog.status === 'failed' || prog.status === 'cancelled') {
                                    clearInterval(activeTimer.value); reject(new Error(prog.error || '分析已取消'))
                                }
                            }
                        } catch (e) { }
                    }, 500)
                })

                globalProgressPercent.value = 100
                globalProgressStep.value = '全面分析完成'
            } catch (e: any) {
                isCancelled = String(e).includes('已取消')
                if (isCancelled) {
                    globalProgressStep.value = '分析已停止'
                } else {
                    globalProgressStep.value = '分析失败: ' + String(e)
                }
            } finally {
                cancelCurrentAnalysis = null
                analysisLaunchPending.value = false
                isStopping.value = false
                setTimeout(() => { isGlobalAnalyzing.value = false }, 2000)
            }
        }

        async function loadFeatureData() {
            if (!selectedConversationId.value) return
            try {
                const [rtData, iniData, wcData] = await Promise.all([
                    api.get_response_times(selectedConversationId.value),
                    api.get_initiative_stats(selectedConversationId.value),
                    api.get_word_counts(selectedConversationId.value, false)
                ])
                if (rtData.success && rtData.data) {
                    const aggregatedDistribution = aggregateResponseTimeDistribution(rtData.data.distribution)
                    responseTimeStats.value = {
                        ...responseTimeStats.value,
                        ...rtData.data,
                        distribution: aggregatedDistribution || responseTimeStats.value.distribution,
                        distributionKeys: Object.keys(responseTimeBucketGroups)
                    }
                    featureStats.value.avgResponseTime = rtData.data.avg
                    featureStats.value.medianResponseTime = rtData.data.median
                    if (currentTab.value === 'features') await nextTick(() => renderResponseTimeChart())
                }
                if (iniData.success && iniData.data) {
                    initiativeStats.value = {
                        totalSessions: iniData.data.total_sessions, userInitiatedSessions: iniData.data.user_initiated_sessions,
                        otherInitiatedSessions: iniData.data.other_initiated_sessions, initiativeRate: iniData.data.initiative_rate, interpretation: iniData.data.interpretation
                    }
                    featureStats.value.initiativeRate = iniData.data.initiative_rate
                }
                if (wcData.success && wcData.data?.overall) {
                    const o = wcData.data.overall
                    wordCountsStats.value = { userCharCount: o.user_char_count, otherCharCount: o.other_char_count, charRatio: o.char_ratio, interpretation: o.interpretation }
                    featureStats.value.wordRatio = o.char_ratio
                    if (currentTab.value === 'features') await nextTick(() => renderWordCountChart())
                }
            } catch (e) { }
        }

        function renderResponseTimeChart() {
            if (!responseTimeChart.value || !responseTimeStats.value.distribution) return
            if (responseTimeChartInstance) responseTimeChartInstance.dispose()
            responseTimeChartInstance = echarts.init(responseTimeChart.value)
            const data = responseTimeStats.value.distributionKeys.map(k => responseTimeStats.value.distribution![k] || 0)
            responseTimeChartInstance.setOption({
                backgroundColor: 'transparent',
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
                xAxis: { type: 'category', data: responseTimeStats.value.distributionKeys, axisLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 11, interval: 0 } },
                yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }, axisLabel: { color: 'rgba(255,255,255,0.6)' } },
                series: [{ type: 'bar', data: data, itemStyle: { borderRadius: [4, 4, 0, 0], color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: '#818cf8' }, { offset: 1, color: '#6366f1' }]) }, label: { show: true, position: 'top', color: 'rgba(255,255,255,0.7)', fontSize: 11 } }]
            })
        }

        function renderActivityCalendar() {
            if (!activityCalendarChart.value || !activityCalendar.value.entries.length) return
            if (activityCalendarChartInstance) activityCalendarChartInstance.dispose()
            activityCalendarChartInstance = echarts.init(activityCalendarChart.value)

            const calendarData = activityCalendar.value.entries.map((entry) => ({
                value: [entry.date, entry.activity_score],
                entry
            }))

            activityCalendarChartInstance.setOption({
                backgroundColor: 'transparent',
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(15, 23, 42, 0.96)',
                    borderColor: 'rgba(148, 163, 184, 0.18)',
                    textStyle: { color: '#e2e8f0' },
                    formatter: (params: any) => {
                        const entry = params.data?.entry as ActivityCalendarEntry | undefined
                        if (!entry) return ''
                        return [
                            `<div style="font-weight:600;margin-bottom:6px;">${entry.date}</div>`,
                            `<div>活跃分数：${entry.activity_score}</div>`,
                            `<div>消息数：${entry.message_count}</div>`,
                            `<div>会话数：${entry.session_count}</div>`,
                            `<div>活跃时长：${formatTime(entry.active_duration_seconds)}</div>`,
                            `<div>时间范围：${entry.first_time} - ${entry.last_time}</div>`,
                            `<div>我发起 ${entry.user_initiated_sessions} / 对方发起 ${entry.other_initiated_sessions}</div>`
                        ].join('')
                    }
                },
                visualMap: {
                    min: 0,
                    max: Math.max(activityCalendar.value.max_activity_score, 1),
                    show: false,
                    inRange: {
                        color: ['#eef2ff', '#c7d2fe', '#818cf8', '#4f46e5', '#312e81']
                    }
                },
                calendar: {
                    top: 34,
                    left: 28,
                    right: 22,
                    bottom: 20,
                    range: `${activityCalendar.value.year}`,
                    cellSize: ['auto', 18],
                    splitLine: { show: false },
                    itemStyle: {
                        color: 'rgba(99, 102, 241, 0.06)',
                        borderWidth: 2,
                        borderColor: '#ffffff'
                    },
                    yearLabel: { show: false },
                    dayLabel: {
                        firstDay: 1,
                        nameMap: ['日', '一', '二', '三', '四', '五', '六'],
                        color: '#94a3b8',
                        margin: 14
                    },
                    monthLabel: {
                        nameMap: 'cn',
                        color: '#64748b',
                        fontWeight: 600,
                        margin: 18
                    }
                },
                series: [{
                    type: 'heatmap',
                    coordinateSystem: 'calendar',
                    data: calendarData,
                    itemStyle: {
                        borderRadius: 4
                    },
                    emphasis: {
                        itemStyle: {
                            shadowBlur: 8,
                            shadowColor: 'rgba(79, 70, 229, 0.35)'
                        }
                    }
                }]
            })
        }

        function renderWordCountChart() {
            if (!wordCountChart.value) return
            if (wordCountChartInstance) wordCountChartInstance.dispose()
            wordCountChartInstance = echarts.init(wordCountChart.value)
            wordCountChartInstance.setOption({
                grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
                xAxis: { type: 'category', data: ['我', '对方'], axisLabel: { color: 'rgba(255,255,255,0.6)' } },
                yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }, axisLabel: { color: 'rgba(255,255,255,0.6)', formatter: (v: number) => `${(v / 1000).toFixed(0)}k` } },
                series: [{ type: 'bar', data: [{ value: wordCountsStats.value.userCharCount, itemStyle: { color: '#818cf8' } }, { value: wordCountsStats.value.otherCharCount, itemStyle: { color: '#f472b6' } }], barWidth: '40%', label: { show: true, position: 'top', color: 'rgba(255,255,255,0.8)', formatter: (p: any) => formatNumber(p.value) } }]
            })
        }

        async function handleActivityYearChange(event: Event) {
            const target = event.target as HTMLSelectElement | null
            if (!target) return
            const nextYear = Number(target.value)
            if (!Number.isFinite(nextYear)) return
            await loadActivityCalendar(nextYear)
        }

        watch(() => currentTab.value, async (newVal) => {
            await nextTick()
            if (newVal === 'features') {
                if (hasFeatures.value) {
                    renderResponseTimeChart()
                    renderWordCountChart()
                    if (activityCalendar.value.entries.length) renderActivityCalendar()
                }
            }
            if ((newVal === 'content' || newVal === 'persona') && selectedConversationId.value) {
                loadAnalysis()
            }
        })

        watch(() => analysisResult.value, (newVal) => {
            if (newVal) {
                let start = 0; const end = newVal.overall_score; const duration = 1000; const startTime = performance.now()
                const animate = (currentTime: number) => {
                    const progress = Math.min((currentTime - startTime) / duration, 1)
                    displayScore.value = start + (end - start) * (1 - Math.pow(1 - progress, 4))
                    if (progress < 1) requestAnimationFrame(animate)
                }
                requestAnimationFrame(animate)
            } else displayScore.value = 0
        })

        const getScoreColor = (score: number) => { if (score >= 80) return '#10b981'; if (score >= 55) return '#3b82f6'; if (score >= 35) return '#f59e0b'; return '#ef4444' }
        const scrollToDetails = (idSuffix: string) => document.getElementById(`detail-${idSuffix}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        const handlePreferenceDisabledClick = () => { showKeywordsDialog.value = true }
        function onWordSelect(word: string) { console.debug('selected', word) }
        function handleResize() { responseTimeChartInstance?.resize(); activityCalendarChartInstance?.resize(); wordCountChartInstance?.resize() }

        onMounted(async () => {
            if (!dates.from || !dates.to) setDefaultDates(30)
            await loadAnalysisDeviceMode()
            await loadConversations()
            window.addEventListener('resize', handleResize)
        })

        onUnmounted(() => {
            window.removeEventListener('resize', handleResize)
            responseTimeChartInstance?.dispose(); activityCalendarChartInstance?.dispose(); wordCountChartInstance?.dispose()
        })

        return {
            currentTab, conversations, selectedConversationId, dates, loading, loadingSessions, error, analysis, subject, sessions,
            personaProfile, loadingPersonaProfile, personaProfileMeta,
            analysisResult, displayScore, showKeywordsDialog, showContextForm, isGlobalAnalyzing, isStopping, activeTimer, handleStopAnalysis, globalProgressPercent, globalProgressStep, gpuMode,
            hasConversations, hasFeatures, hasCachedAffinityAnalysis, featureStats, responseTimeStats, initiativeStats, wordCountsStats, activityCalendar,
            responseTimeChart, activityCalendarChart, wordCountChart, stats, currentContactName, hasPreferenceKeywords, allDimensions, emotionalResonanceDisplaySubScores,
            currentRangeLabel, hasContentAnalysis, circumference, strokeDashoffset, formatNumber, formatTime, getResponseTimeLabel, getMergedResponseTimeLabel, getResponseTimePercent, onConversationChange, onDatesChange, handleExport, handleStartGlobalAnalysis, handleContextSaved, handleKeywordsUpdated,
            getScoreColor, scrollToDetails, handlePreferenceDisabledClick, onWordSelect, loadAnalysis, loadSessions, handleActivityYearChange
        }
    }
}

</script>

<style scoped>
/* ========================================
   Analytics Page Styles
   ======================================== */
.analytics-page {
  display: flex;
  flex-direction: column;
  padding: var(--ct-space-md) var(--ct-space-xl) 0 var(--ct-space-xl) !important;
  gap: var(--ct-space-md) !important;
  height: 100%; /* Will only work if App.vue restricts it, but helps elasticity */
}

/* --- Header Section --- */
.analytics-header {
  flex-shrink: 0; /* Prevent header squishing */
  position: relative;
  z-index: 50;
}

.page-empty-state {
  position: relative;
  flex: 1;
  min-height: 520px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 28px;
  padding: clamp(32px, 6vw, 72px);
  border-radius: 28px;
  border: 1px solid rgba(124, 77, 255, 0.12);
  background:
    radial-gradient(circle at top, rgba(124, 77, 255, 0.14), transparent 34%),
    radial-gradient(circle at bottom right, rgba(245, 166, 35, 0.12), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 255, 0.94));
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.page-empty-glow {
  position: absolute;
  width: 280px;
  height: 280px;
  border-radius: 999px;
  filter: blur(42px);
  opacity: 0.5;
  pointer-events: none;
}

.page-empty-glow-left {
  top: -100px;
  left: -80px;
  background: rgba(124, 77, 255, 0.18);
}

.page-empty-glow-right {
  right: -110px;
  bottom: -120px;
  background: rgba(245, 166, 35, 0.18);
}

.page-empty-hero {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 720px;
}

.page-empty-badge {
  display: inline-flex;
  align-items: center;
  padding: 8px 14px;
  margin-bottom: 18px;
  border-radius: 999px;
  border: 1px solid rgba(124, 77, 255, 0.16);
  background: rgba(255, 255, 255, 0.72);
  color: var(--ct-color-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  box-shadow: 0 8px 20px rgba(124, 77, 255, 0.08);
}

.page-empty-illustration {
  position: relative;
  width: 180px;
  height: 140px;
  margin-bottom: 10px;
}

.empty-orb {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  backdrop-filter: blur(10px);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.12);
}

.empty-orb-main {
  left: 50%;
  top: 18px;
  width: 92px;
  height: 92px;
  transform: translateX(-50%);
  background: linear-gradient(135deg, rgba(124, 77, 255, 0.18), rgba(124, 77, 255, 0.08));
  border: 1px solid rgba(124, 77, 255, 0.14);
  font-size: 42px;
}

.empty-orb-small {
  width: 44px;
  height: 44px;
  font-size: 18px;
}

.empty-orb-chat {
  left: 28px;
  top: 72px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.16), rgba(59, 130, 246, 0.08));
  border: 1px solid rgba(59, 130, 246, 0.14);
}

.empty-orb-star {
  right: 28px;
  top: 34px;
  background: linear-gradient(135deg, rgba(245, 166, 35, 0.2), rgba(245, 166, 35, 0.08));
  border: 1px solid rgba(245, 166, 35, 0.14);
  color: #b45309;
}

.page-empty-state h2 {
  margin: 0 0 12px;
  font-size: clamp(30px, 4.2vw, 42px);
  color: var(--ct-text-primary);
}

.page-empty-state p {
  margin: 0;
  line-height: 1.8;
  color: var(--ct-text-secondary);
}

.page-empty-lead {
  max-width: 560px;
  font-size: var(--ct-text-lg);
}

.page-empty-hint {
  max-width: 620px;
  margin-top: var(--ct-space-md) !important;
  color: var(--ct-text-tertiary) !important;
}

.page-empty-grid {
  position: relative;
  z-index: 1;
  width: 100%;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.page-empty-card {
  text-align: left;
  padding: 18px 18px 20px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.page-empty-card-accent {
  background: linear-gradient(180deg, rgba(124, 77, 255, 0.08), rgba(255, 255, 255, 0.9));
  border-color: rgba(124, 77, 255, 0.16);
}

.page-empty-card-label {
  display: inline-flex;
  margin-bottom: 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ct-text-tertiary);
}

.page-empty-card strong {
  display: block;
  margin-bottom: 8px;
  font-size: 17px;
  line-height: 1.4;
  color: var(--ct-text-primary);
}

.page-empty-card p {
  font-size: var(--ct-text-sm);
  line-height: 1.7;
  color: var(--ct-text-secondary);
}

.user-profile-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--ct-space-sm) var(--ct-space-lg);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-2xl);
  box-shadow: var(--ct-shadow-sm);
  border: 1px solid var(--ct-border-subtle);
  flex-wrap: wrap;
  gap: var(--ct-space-md);
}

.profile-main {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
}

.profile-avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 2px solid var(--ct-color-primary-subtle);
}

.profile-info {
  display: flex;
  flex-direction: column;
}

.name-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.profile-name {
  font-size: var(--ct-text-xl, 1.25rem);
  font-weight: 700;
  color: var(--ct-text-primary);
  word-break: break-word;
}

.profile-stats {
  display: flex;
  gap: var(--ct-space-xs);
}

.stat-tag {
  padding: 2px 8px;
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-full);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.header-actions-group {
  display: flex;
  gap: var(--ct-space-xs);
}

/* --- Global Progress --- */
.extraction-progress {
  padding: var(--ct-space-md) var(--ct-space-xl);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
  margin-bottom: var(--ct-space-md);
  box-shadow: var(--ct-shadow-sm);
  border: 1px solid var(--ct-border-subtle);
}

.progress-bar {
  height: 8px;
  background: var(--ct-bg-tertiary);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: var(--ct-color-primary);
  transition: width 0.3s ease;
}

.progress-text {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  text-align: right;
}

.gpu-badge {
  display: inline-block;
  background: linear-gradient(135deg, #1f7a8c, #bfdb38);
  color: #fff;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  margin-right: 8px;
  font-weight: 600;
}

.cpu-badge {
  display: inline-block;
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-secondary);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  margin-right: 8px;
}

.spinning {
  display: inline-block;
  animation: spin 2s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}

/* --- Tabs Styling --- */
/* --- Tabs Alignment --- */
.tabs-container {
  display: flex;
  justify-content: center;
}

/* --- Tab Content --- */
.tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tab-content .empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--ct-space-4xl) var(--ct-space-xl);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-2xl);
  border: 1px dashed var(--ct-border-subtle);
  margin-top: var(--ct-space-md);
  flex: 1;
  min-height: 400px;
  width: 100%;
}

.tab-content .empty-state .empty-icon {
  font-size: 64px;
  margin-bottom: var(--ct-space-lg);
  opacity: 0.9;
}

.tab-content .empty-state p {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-lg);
  font-weight: 500;
  margin-top: 0;
  margin-bottom: var(--ct-space-md);
}

.tab-content .empty-state .empty-hint {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
  font-weight: 400;
  background: var(--ct-bg-tertiary);
  padding: var(--ct-space-sm) var(--ct-space-xl);
  border-radius: var(--ct-radius-full);
}

.tab-content .inline-empty-state {
  min-height: 280px;
  margin-top: 0;
  padding: var(--ct-space-2xl) var(--ct-space-xl);
  border-radius: var(--ct-radius-xl);
}

.tab-content .inline-empty-state .empty-icon {
  font-size: 40px;
  margin-bottom: var(--ct-space-md);
}

/* --- Affinity Dashboard (Two Column) --- */
.affinity-dashboard {
  flex: 1;
  align-items: stretch;
}

.col-main, .col-side {
  display: flex;
  flex-direction: column;
}

.summary-row {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.score-overview-card {
  height: 100%;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.score-section {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.score-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.score-title {
  font-size: var(--ct-text-base);
  font-weight: 600;
  color: var(--ct-text-secondary);
}

.trend-badge {
  font-size: var(--ct-text-xs);
  padding: 2px 6px;
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-sm);
}

.trend-badge .up { color: var(--ct-color-success); }
.trend-badge .down { color: var(--ct-color-error); }

.score-visual {
  display: flex;
  align-items: center;
  gap: var(--ct-space-2xl);
}

.ct-score-ring.large {
  width: 140px;
  height: 140px;
  flex-shrink: 0;
}

.ct-score-ring.large .ct-score-num {
  font-size: 44px;
  background: linear-gradient(135deg, var(--ct-color-primary), #a855f7);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.ct-score-ring.large .ct-score-unit {
  font-size: 16px;
  color: var(--ct-text-tertiary);
  margin-left: 4px;
}

.qualitative-analysis {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.qualitative-analysis h3 {
  font-size: var(--ct-text-base);
  margin-bottom: 8px;
  color: var(--ct-text-primary);
}

.analysis-bubble {
  padding: var(--ct-space-md) var(--ct-space-xl);
  background: var(--ct-bg-tertiary);
  border-radius: var(--ct-radius-md);
  position: relative;
  line-height: 1.6;
  font-size: var(--ct-text-base);
  color: var(--ct-text-secondary);
  border-left: 4px solid var(--ct-color-primary);
  overflow-y: auto;
  max-height: 160px;
}

/* Dimension Cards Grid */
.dimension-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ct-space-md);
  margin-top: var(--ct-space-md);
  flex: 1;
}

.dimension-cards-grid > * {
  display: flex;
  flex-direction: column;
}

/* Side Column */
.radar-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.radar-card :deep(.ct-card-bd) {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.radar-wrapper {
  flex: 1;
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.breakdowns-container {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ct-space-lg);
}

/* --- Responsive Hacks --- */
@media (max-width: 768px) {
  .user-profile-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ct-space-lg);
  }
  
  .header-actions-group {
    width: 100%;
  }

  .score-visual {
    flex-direction: column;
    gap: var(--ct-space-lg);
  }

  .dimension-cards-grid {
    grid-template-columns: 1fr;
  }

  .breakdowns-container {
    grid-template-columns: 1fr;
  }
}

/* Transitions */
.fade-in {
  animation: fadeIn 0.4s ease-out forwards;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Component Overrides for Analytics Context */
.score-overview-card :deep(.card-body) {
  padding: var(--ct-space-xl);
}

/* --- Interactive Features Layout --- */
.features-layout {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xl);
  margin-top: var(--ct-space-md);
}

.persona-tab-shell {
  margin-top: var(--ct-space-md);
  padding-bottom: var(--ct-space-xl);
}

.features-row-1 {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--ct-space-lg);
}

.feature-stat-card {
  display: flex;
  flex-direction: column;
  min-height: 120px;
}
.feature-stat-card :deep(.ct-card-bd) {
  padding: var(--ct-space-lg);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.stat-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: var(--ct-space-md);
}

.icon-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
}
.icon-dot .inner-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.icon-dot.green { background: #e6f4ea; border-color: #82ca9d; }
.icon-dot.green .inner-dot { background: #82ca9d; }

.icon-dot.purple { background: #f3e8ff; border-color: #8884d8; }
.icon-dot.purple .inner-dot { background: #8884d8; }

.icon-dot.orange { background: #fff1f2; border-color: #fca5a5; }
.icon-dot.orange .inner-dot { background: #fca5a5; }

.stat-title {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  font-weight: 500;
}

.stat-body {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex: 1;
}

.stat-main {
  display: flex;
  align-items: baseline;
  gap: 4px;
  color: var(--ct-text-primary);
}

.stat-num {
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
}

.stat-unit {
  font-size: var(--ct-text-sm);
  font-weight: 600;
}

.stat-sub {
  font-size: 11px;
  color: var(--ct-text-tertiary);
}

.trend-down {
  color: #fbbf24;
}

.features-row-2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--ct-space-lg);
}

.features-row-3 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--ct-space-lg);
}

.feature-chart-card {
  display: flex;
  flex-direction: column;
}
.feature-chart-card :deep(.ct-card-bd) {
  padding: var(--ct-space-lg) var(--ct-space-xl);
}

.chart-card-title {
  font-size: var(--ct-text-base);
  font-weight: 600;
  color: var(--ct-text-primary);
  margin-top: 0;
  margin-bottom: var(--ct-space-xl);
}

/* Horizontal Bar Chart */
.horizontal-bars {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: var(--ct-space-md);
}

.h-bar-row {
  display: grid;
  grid-template-columns: minmax(120px, 180px) minmax(0, 1fr) 64px;
  align-items: center;
  gap: 16px;
}

.h-bar-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.h-bar-label-main {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-primary);
  font-weight: 600;
  line-height: 1.2;
}

.h-bar-label-sub {
  font-size: 11px;
  color: var(--ct-text-tertiary);
  line-height: 1;
}

.h-bar-track-wrap {
  display: flex;
  align-items: center;
  min-width: 0;
}

.h-bar-track {
  flex: 1;
  height: 10px;
  background: linear-gradient(180deg, rgba(136, 132, 216, 0.08), rgba(136, 132, 216, 0.02));
  border-radius: 999px;
  overflow: hidden;
  position: relative;
}

.h-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #7c71df 0%, #9a90ef 100%);
  border-radius: 999px;
  min-width: 6px;
}

.h-bar-value {
  width: 64px;
  text-align: right;
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  font-weight: 600;
}

.initiative-content {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--ct-space-xl);
  min-height: 120px;
  flex-wrap: wrap;
}

.donut-chart-box {
  display: flex;
  align-items: center;
  gap: 16px;
}

.donut-svg {
  width: 100px;
  height: 100px;
  transform: rotate(-90deg);
}

.donut-legend {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ct-text-secondary);
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.legend-dot.purple { background: #8884d8; }
.legend-dot.green { background: #82ca9d; }

.initiative-box {
  background: var(--ct-bg-tertiary);
  padding: 12px 16px;
  border-radius: 8px;
  border-left: 2px solid #8884d8;
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  max-width: 150px;
}

.initiative-box .box-text {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
  line-height: 1.5;
}

/* Word Comparison */
.word-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-xl);
  min-height: 120px;
  flex-wrap: wrap;
}

.v-bars {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  height: 100%;
}

.v-bar-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  height: 100%;
  justify-content: flex-end;
}

.v-bar-track {
  width: 48px;
  height: 80px;
  display: flex;
  align-items: flex-end;
}

.v-bar-fill {
  width: 100%;
  border-radius: 6px 6px 0 0;
}
.v-bar-fill.purple { background: #8884d8; }
.v-bar-fill.red { background: #fca5a5; }

.v-bar-label {
  font-size: 10px;
  color: var(--ct-text-tertiary);
  text-align: center;
  line-height: 1.4;
}
.v-bar-label strong {
  color: var(--ct-text-primary);
  font-size: 11px;
}

.word-box {
  background: var(--ct-bg-tertiary);
  padding: 12px 16px;
  border-radius: 8px;
  border-left: 2px solid #8884d8;
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  flex: 1;
}

.word-box-title {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  font-weight: 500;
  margin-bottom: 4px;
}

.word-box-title .highlight {
  font-size: var(--ct-text-base);
  font-weight: 700;
  color: var(--ct-text-primary);
  margin-left: 4px;
}

.word-box-desc {
  font-size: 11px;
  color: var(--ct-text-tertiary);
}

/* Row 4 */
.features-row-4 {
  display: flex;
  margin-bottom: var(--ct-space-xl);
}

.feature-calendar-card {
  width: 100%;
}

.feature-calendar-card :deep(.ct-card-bd) {
  padding: var(--ct-space-lg) var(--ct-space-xl);
}

.calendar-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ct-space-lg);
  flex-wrap: wrap;
  margin-bottom: var(--ct-space-lg);
}

.calendar-year-picker {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.08), rgba(99, 102, 241, 0.03));
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.calendar-year-picker select {
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ct-text-primary);
  font-weight: 600;
  min-width: 88px;
}

.calendar-text h3 {
  font-size: var(--ct-text-base);
  font-weight: 600;
  color: var(--ct-text-primary);
  margin: 0 0 4px 0;
}

.calendar-text p {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
  margin: 0;
}

.calendar-summary-card {
  margin-bottom: 14px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 252, 0.88));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
  padding: 10px 12px;
}

.calendar-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.calendar-summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 10px;
  background: transparent;
  border: 0;
  min-width: 0;
  position: relative;
}

.calendar-summary-item:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 8px;
  right: -4px;
  width: 1px;
  height: calc(100% - 16px);
  background: rgba(148, 163, 184, 0.18);
}

.calendar-summary-item strong {
  font-size: 17px;
  line-height: 1.15;
  color: var(--ct-text-primary);
  white-space: nowrap;
}

.calendar-summary-item em {
  font-style: normal;
  font-size: 11px;
  color: var(--ct-text-tertiary);
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.calendar-summary-label {
  font-size: 11px;
  color: var(--ct-text-tertiary);
  line-height: 1.2;
}

.calendar-summary-item.peak-day {
  grid-column: span 1;
}

.calendar-chart-shell {
  border-radius: 20px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background:
    radial-gradient(circle at top left, rgba(129, 140, 248, 0.12), transparent 32%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 252, 0.96));
  padding: 14px 14px 10px;
  overflow-x: auto;
  overflow-y: hidden;
}

.calendar-legend {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  font-size: 12px;
  color: var(--ct-text-tertiary);
  margin-bottom: 8px;
}

.calendar-legend-scale {
  display: inline-flex;
  gap: 6px;
}

.calendar-legend-scale i {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 4px;
}

.calendar-legend-scale i:nth-child(1) { background: #eef2ff; }
.calendar-legend-scale i:nth-child(2) { background: #c7d2fe; }
.calendar-legend-scale i:nth-child(3) { background: #818cf8; }
.calendar-legend-scale i:nth-child(4) { background: #4f46e5; }
.calendar-legend-scale i:nth-child(5) { background: #312e81; }

.calendar-chart {
  width: 100%;
  min-width: 760px;
  height: 280px;
}

.calendar-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  border-radius: 20px;
  border: 1px dashed rgba(148, 163, 184, 0.22);
  background: rgba(248, 250, 252, 0.65);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
}


/* --- Content & Timeline Layout --- */
.content-timeline-dashboard {
  /* 当左右分开时，由于 grid 会双列都跟随最高的自适应拉伸。
     如果希望右侧【严格等于左侧的高度】（左侧高度作为撑起的基础），使用绝对定位是一种好办法。 */
  display: block;
  position: relative;
  overflow: visible;
  padding-bottom: var(--ct-space-xl);
}

@media (min-width: 1025px) {
  .content-timeline-dashboard .col-main {
    width: calc(50% - var(--ct-space-xl) / 2);
  }
  .content-timeline-dashboard .col-side {
    position: absolute;
    top: 0;
    right: 0;
    width: calc(50% - var(--ct-space-xl) / 2);
    height: calc(100% - var(--ct-space-xl)); /* Fix: exclude bottom padding from height */
    display: flex;
    flex-direction: column;
  }
}

@media (max-width: 1024px) {
  .content-timeline-dashboard {
    display: flex;
    flex-direction: column;
    gap: var(--ct-space-xl);
  }
  .content-timeline-dashboard .col-main,
  .content-timeline-dashboard .col-side {
    width: 100%;
  }
  .content-timeline-dashboard .timeline-section-card {
    min-height: 500px;
  }
}

.content-timeline-dashboard .main-content {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.content-timeline-dashboard .timeline-section-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 24px;
  animation: fadeInUp 0.6s ease-out 0.3s backwards;
  margin-bottom: 0;
}

.content-timeline-dashboard .timeline-section-card .section-header {
  flex-shrink: 0;
  margin-bottom: var(--ct-space-md);
}

.content-timeline-dashboard .timeline-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding-right: var(--ct-space-sm);
  padding-bottom: 24px;
}
.content-timeline-dashboard .timeline-scroll-area::-webkit-scrollbar {
  width: 6px;
}
.content-timeline-dashboard .timeline-scroll-area::-webkit-scrollbar-thumb {
  background-color: var(--ct-border-subtle);
  border-radius: 3px;
}

.content-timeline-dashboard .subject-section {
  flex-shrink: 0;
}

/* Common */
.subject-section {
  margin-bottom: var(--ct-space-xl);
}

.section-header {
    margin-bottom: var(--ct-space-lg);
}

.section-header h3 {
    font-size: var(--ct-text-2xl);
    font-weight: 600;
    color: var(--ct-text-primary);
    margin-bottom: var(--ct-space-xs);
    margin-top: 0;
}

.section-subtitle {
    font-size: var(--ct-text-sm);
    color: var(--ct-text-tertiary);
    margin: 0;
}

.fade-in {
    animation: fadeIn 0.4s ease-out forwards;
}

@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}

@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateY(20px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Responsive adjustments */
@media (max-width: 1200px) {

    .features-row-1 {
        grid-template-columns: repeat(2, 1fr);
    }

    .calendar-summary-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .calendar-summary-item.peak-day {
        grid-column: span 2;
    }

    .calendar-summary-item:nth-child(2)::after,
    .calendar-summary-item:nth-child(4)::after {
        display: none;
    }

    .main-content,
    .features-grid {
        grid-template-columns: 1fr;
    }

    .feature-card.timeline {
        grid-column: 1;
    }
}

@media (max-width: 768px) {
    .analytics-page {
        padding: var(--ct-space-lg) var(--ct-space-md) !important;
    }

    .page-empty-state {
        min-height: 460px;
        gap: 22px;
        border-radius: 22px;
    }

    .page-empty-grid {
        grid-template-columns: 1fr;
    }

    .page-empty-illustration {
        transform: scale(0.92);
    }

    .page-header,
    .feature-actions,
    .card-header {
        flex-direction: column;
        gap: var(--ct-space-md);
        align-items: stretch;
    }

    .action-buttons {
        flex-direction: column;
    }

    .stats-grid,
    .response-stats {
        grid-template-columns: repeat(2, 1fr);
    }

    .h-bar-row {
        grid-template-columns: minmax(96px, 136px) minmax(0, 1fr) 56px;
        gap: 12px;
    }

    .calendar-header {
        flex-direction: column;
        align-items: stretch;
    }

    .calendar-year-picker {
        justify-content: space-between;
    }
}

@media (max-width: 480px) {

    .page-empty-badge {
        font-size: 11px;
        letter-spacing: 0.06em;
    }

    .page-empty-state h2 {
        font-size: 28px;
    }

    .page-empty-card {
        padding: 16px;
    }

    .features-row-1,
    .features-row-3,
    .stats-grid,
    .response-stats,
    .word-stats-grid {
        grid-template-columns: 1fr;
    }

    .calendar-summary-grid {
        grid-template-columns: 1fr;
    }

    .calendar-summary-item.peak-day {
        grid-column: auto;
    }

    .calendar-summary-item::after {
        display: none;
    }

    .calendar-chart {
        min-width: 680px;
        height: 260px;
    }

    .h-bar-row {
        grid-template-columns: 1fr;
        gap: 8px;
    }

    .h-bar-value {
        width: auto;
        text-align: left;
    }
}

</style>
