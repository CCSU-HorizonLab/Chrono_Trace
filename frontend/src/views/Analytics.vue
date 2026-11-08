<template>
<section class="analytics-page ct-page">
  <!-- Brand Header：对象工作台页头，选人器常驻（未选中也可先选人） -->
  <header class="analytics-header">
    <div v-if="hasConversations" class="user-profile-header fade-in">
      <div class="profile-main">
        <div class="profile-avatar-wrap">
          <CtAvatar class="profile-avatar" :src="headerAvatarSrc" :name="currentContactName || '？'" :size="48" />
        </div>
        <div class="profile-info">
          <div class="name-row">
            <h1 class="profile-name">{{ currentContactName || '选择一位联系人' }}</h1>
            <div class="contact-selector-wrap">
              <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId" :loading="loading"
                @update:conversation-id="onConversationChange" />
            </div>
          </div>
        </div>
      </div>

      <div v-if="selectedConversationId" class="header-actions-group">
        <CtButton variant="ghost" @click="showContextForm = true" :disabled="isGlobalAnalyzing || llmPhase === 'running'">关系信息</CtButton>
        <CtButton variant="ghost" @click="showKeywordsDialog = true" :disabled="isGlobalAnalyzing || llmPhase === 'running'">配置喜好</CtButton>
        <CtButton v-if="!isGroupConversation && analysisResult" variant="ghost" :loading="reportExporting" @click="handleExportReport">
          导出体检报告
        </CtButton>
        <CtButton variant="primary" @click="handleStartGlobalAnalysis" :loading="isGlobalAnalyzing && !isStopping" :disabled="llmPhase === 'running'" class="btn-full-analysis">
          {{ isGlobalAnalyzing ? "分析中..." : (llmPhase === 'running' ? "AI 评估中..." : (hasCachedAffinityAnalysis ? "重新全面分析" : "开始全面分析")) }}
        </CtButton>
        <CtButton v-if="isGlobalAnalyzing" variant="danger" @click="handleStopAnalysis" :loading="isStopping" class="btn-stop-analysis" style="margin-left: 8px;">
          停止
        </CtButton>
        <CtButton v-if="llmPhase === 'running'" variant="danger" @click="handleSkipLlmEvaluation" :loading="isStopping" class="btn-stop-analysis" style="margin-left: 8px;">
          跳过 AI 评估
        </CtButton>
      </div>
    </div>
  </header>

  <div v-if="!hasConversations" class="page-empty-state fade-in">
    <div class="page-empty-hero">
      <div class="page-empty-badge">历史分析</div>

      <div class="page-empty-illustration" aria-hidden="true">
        <div class="empty-orb empty-orb-main"><FolderArchive :size="36" style="color: var(--ct-color-primary);" /></div>
        <div class="empty-orb empty-orb-small empty-orb-chat"><MessageSquare :size="20" style="color: var(--ct-chart-3);" /></div>
        <div class="empty-orb empty-orb-small empty-orb-star"><Sparkles :size="18" style="color: var(--ct-chart-4);" /></div>
      </div>

      <h2>还没有历史记录</h2>
      <p class="page-empty-lead">当前还没有可分析的聊天会话，但这个页面不该再是空白的。</p>
      <p class="page-empty-hint">先去<router-link to="/import" style="color: var(--ct-color-primary); text-decoration: underline;">数据页</router-link>导入微信数据，完成后这里会自动显示联系人、分析入口和时间线内容。</p>
    </div>

    <div class="page-empty-grid">
      <div class="page-empty-card">
        <span class="page-empty-card-label">下一步</span>
        <strong>去<router-link to="/import" style="color: var(--ct-color-primary); text-decoration: underline;">数据页</router-link>导入聊天数据</strong>
        <p>导入完成后，历史记录页会自动恢复完整展示。</p>
      </div>

      <div class="page-empty-card">
        <span class="page-empty-card-label">导入后可查看</span>
        <strong>关系分析、互动特征、时间线</strong>
        <p>包括联系人切换、趋势图、词云和画像档案等内容。</p>
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
        @click="currentTab = 'content'">内容时间线</button>
      <button class="menu-item" :class="{ active: currentTab === 'qa' }"
        @click="currentTab = 'qa'">智能问答</button>
      <!-- 时光深度 / TA 画像：均单聊专属（情绪演变与画像都是 1:1 语义） -->
      <button v-if="!isGroupConversation" class="menu-item" :class="{ active: currentTab === 'deep' }"
        @click="currentTab = 'deep'">时光深度</button>
      <button v-if="!isGroupConversation" class="menu-item" :class="{ active: currentTab === 'persona' }"
        @click="currentTab = 'persona'">TA 画像</button>
      <!-- 实时助手同单聊限定：监听对象/建议配置都是 1:1 语义 -->
      <button v-if="!isGroupConversation" class="menu-item" :class="{ active: currentTab === 'realtime' }"
        @click="currentTab = 'realtime'">实时助手</button>
    </div>
  </div>

  <!-- TAB 1: Affinity（群聊切换为群聊工作台——四维好感度对群聊意义有限） -->
  <div v-show="currentTab === 'affinity' && selectedConversationId" class="tab-content fade-in affinity-tab">
    <div v-if="isGroupConversation" class="group-workbench">
      <CtCard class="group-stats-card" title="群聊发言统计">
        <div v-if="groupStatsLoading" class="group-empty">统计加载中...</div>
        <template v-else-if="groupStats && groupStats.members && groupStats.members.length">
          <div class="group-overview">
            <span>文本消息 <strong>{{ groupStats.total_messages }}</strong> 条</span>
            <span>发言成员 <strong>{{ groupStats.members.length }}</strong> 人</span>
            <span v-if="groupStats.my_rank">我的发言排名 <strong>第 {{ groupStats.my_rank }}</strong></span>
            <span v-else>我未在统计范围内发言</span>
          </div>
          <div class="group-member-table">
            <div class="group-member-row group-member-head">
              <span class="gm-name">成员</span>
              <span class="gm-count">消息数</span>
              <span class="gm-share">占比</span>
              <span class="gm-chars">字数</span>
            </div>
            <div v-for="m in groupStats.members.slice(0, 20)" :key="m.name" class="group-member-row" :class="{ me: m.name === '我' }">
              <span class="gm-name">{{ m.name }}</span>
              <span class="gm-count">{{ m.message_count }}</span>
              <span class="gm-share">
                <span class="gm-share-bar"><i :style="{ width: (m.share * 100).toFixed(1) + '%' }"></i></span>
                <em>{{ (m.share * 100).toFixed(1) }}%</em>
              </span>
              <span class="gm-chars">{{ m.char_count }}</span>
            </div>
          </div>
          <div v-if="groupStats.top_words && groupStats.top_words.length" class="group-top-words">
            <span class="gtw-title">高频词</span>
            <span v-for="w in groupStats.top_words.slice(0, 15)" :key="w.word" class="gtw-chip">{{ w.word }} ×{{ w.count }}</span>
          </div>
          <p class="group-note">成员名为导入时解析的显示短名；群聊暂不提供成员关系分析。</p>
        </template>
        <p v-else class="group-empty">暂无群聊消息或统计失败。</p>
      </CtCard>

      <CtCard class="group-summary-card" title="群聊日报">
        <div class="group-summary-controls">
          <select v-model.number="groupSummaryDays" class="group-days-select" :disabled="groupSummaryLoading">
            <option :value="1">近 1 天</option>
            <option :value="7">近 7 天</option>
            <option :value="30">近 30 天</option>
          </select>
          <CtButton variant="primary" :loading="groupSummaryLoading" :disabled="groupSummaryLoading" @click="handleGenerateGroupSummary">
            {{ groupSummaryLoading ? '生成中...' : '生成日报' }}
          </CtButton>
          <CtButton v-if="groupSummaryLoading" variant="ghost" @click="handleCancelGroupSummary">取消</CtButton>
        </div>
        <div v-if="groupSummary" class="group-summary-body">
          <p v-if="groupSummary.degraded" class="group-summary-degraded">{{ groupSummary.degraded_reason }}</p>
          <p v-else class="group-summary-text">{{ groupSummary.summary }}</p>
        </div>
        <p v-else class="group-summary-hint">
          由 LLM 汇总近期主要话题、群氛围与值得注意的互动；未配置模型时仅提供左侧统计。
        </p>
      </CtCard>
    </div>

    <template v-else>
    <div v-if="!analysisResult && !isGlobalAnalyzing" class="empty-state">
      <div class="empty-icon"><BarChart3 :size="56" :stroke-width="1.5" style="color: var(--ct-color-primary);" /></div>
      <template v-if="analysisStaleNotice">
        <p>该联系人的分析结果已因版本更新过期，需要重新分析。</p>
        <p class="empty-hint" style="display: inline-flex; align-items: center; gap: 6px;"><Lightbulb :size="14" style="color: var(--ct-color-info); flex-shrink: 0;" /> 重新分析后历史趋势将恢复展示；分析口径升级期间分数出现变化属预期</p>
      </template>
      <template v-else>
        <p>请点击"开始全面分析"探索你们的亲密关系维度。</p>
        <p class="empty-hint" style="display: inline-flex; align-items: center; gap: 6px;"><Lightbulb :size="14" style="color: var(--ct-color-info); flex-shrink: 0;" /> 首次分析需要1-2分钟进行数据特征提取和模型推理，请耐心等待</p>
      </template>
    </div>

    <!-- Analyzing State（部分结果到达前占位；重分析期间旧结果保留在下方） -->
    <div v-if="isGlobalAnalyzing && !analysisResult" class="empty-state">
      <div class="empty-icon spinning"><Loader2 :size="56" class="spin-icon" style="color: var(--ct-color-primary);" /></div>
      <p>正在分析中，请耐心等待...</p>
      <p class="empty-hint" style="display: inline-flex; align-items: center; gap: 6px;"><Lightbulb :size="14" style="color: var(--ct-color-info); flex-shrink: 0;" /> 我们正在处理特征提取和模型推理</p>
    </div>

    <!-- Affinity Verdict Band + Detail Columns（渐进渲染：llm_pending 部分结果先显示） -->
    <template v-if="analysisResult">
      <!-- 结论带：总分（多少）→ 雷达（形状）→ 解读（含义），从左到右一眼读完 -->
      <CtCard class="verdict-band">
        <div class="score-header">
          <span class="score-title">总体好感度</span>
          <span
            v-if="llmPhase === 'running'"
            class="llm-phase-badge"
            title="AI 关系评估完成后总分小幅更新"
          ><Loader2 :size="12" class="spin-icon" /> AI 评估中</span>
          <div class="trend-badge" v-if="analysisResult.score_trend != null"
            :title="analysisResult.analysis_caliber ? '与上次分析的分数差（同评分口径）' : '与上次分析的分数差'">
            较上次 <span :class="analysisResult.score_trend >= 0 ? 'up' : 'down'">{{ analysisResult.score_trend > 0 ? '↑' : '↓' }}{{ Math.abs(analysisResult.score_trend).toFixed(1) }} 分</span>
          </div>
          <span
            v-if="analysisResult.analysis_stale"
            class="stale-badge"
            :title="analysisResult.pending_message_count ? `有 ${analysisResult.pending_message_count} 条新消息未纳入当前分数` : '消息集已变化，建议重新分析'"
          >{{ analysisResult.pending_message_count ? `${analysisResult.pending_message_count} 条新消息待分析` : '结果待更新' }}</span>
        </div>

        <div class="score-visual">
          <div class="ct-score-ring large">
            <svg viewBox="0 0 120 120" class="circular-chart">
              <circle class="circle-bg" cx="60" cy="60" r="50" fill="none" stroke="var(--ct-bg-sunken)" stroke-width="10" />
              <circle class="circle-fill" cx="60" cy="60" r="50" fill="none"
                stroke="var(--ct-color-primary)" stroke-width="10" stroke-linecap="round"
                :stroke-dasharray="314.159" :stroke-dashoffset="314.159 * (1 - displayScore / 100)" />
            </svg>
            <div class="ct-score-text">
              <span class="ct-score-num">{{ Math.round(displayScore) }}</span>
              <span class="ct-score-unit">%</span>
            </div>
          </div>

          <div class="verdict-radar">
            <DimensionRadar :dimension-scores="allDimensions" />
          </div>

          <div class="qualitative-analysis">
            <div class="qualitative-head">
              <h3>定性分析</h3>
              <button class="text-action-btn" :class="{ copied: overallCopied }" @click="handleCopyOverall">
                {{ overallCopied ? '已复制' : '复制' }}
              </button>
            </div>
            <div class="analysis-bubble">
              <p>{{ analysisResult.overall_interpretation }}</p>
            </div>
            <p v-if="llmPhase === 'running'" class="llm-pending-note">总分暂按本地四维归一口径，AI 评估完成后小幅更新</p>
          </div>
        </div>
      </CtCard>

      <!-- 第二部分：左=四个统计维度卡并列（AI 关系评估通栏收底），右=风险预警 -->
      <div class="ct-grid-1-1 affinity-dashboard">
        <div class="col-main">
          <div class="dimension-cards-grid">
            <AffinityScoreCard v-if="analysisResult.interaction_investment" title="互动投入"
              :score="analysisResult.interaction_investment.score"
              :max-score="100"
              :weight="analysisResult.interaction_investment.weight"
              :interpretation="analysisResult.interaction_investment.interpretation" />
            <AffinityScoreCard v-if="analysisResult.emotional_resonance" title="情感共鸣"
              :score="analysisResult.emotional_resonance.score"
              :max-score="100"
              :weight="analysisResult.emotional_resonance.weight"
              :interpretation="analysisResult.emotional_resonance.interpretation" />
            <AffinityScoreCard v-if="analysisResult.closeness_signals" title="亲近信号"
              :score="analysisResult.closeness_signals.score"
              :max-score="100"
              :weight="analysisResult.closeness_signals.weight"
              :interpretation="analysisResult.closeness_signals.interpretation" />
            <AffinityScoreCard v-if="analysisResult.preference_compatibility" title="喜好兼容度"
              :score="analysisResult.preference_compatibility.score"
              :max-score="100"
              :weight="analysisResult.preference_compatibility.weight"
              :interpretation="analysisResult.preference_compatibility.interpretation"
              :is-bonus="!(analysisResult.preference_compatibility.weight > 0)"
              :bonus-value="analysisResult.preference_compatibility.bonus_scores?.preference_bonus" />
            <AffinityScoreCard v-if="analysisResult.llm_relationship" class="span-full" title="AI 关系评估"
              :score="analysisResult.llm_relationship.score"
              :max-score="100"
              :weight="analysisResult.llm_relationship.weight"
              :interpretation="analysisResult.llm_relationship.interpretation" />
            <div v-else-if="llmPhase === 'running'" class="llm-pending-card span-full">
              <div class="llm-pending-head"><Loader2 :size="16" class="spin-icon" /> AI 关系评估 · 评估中…</div>
              <p>本地四维已完成，AI 正在通读聊天记录生成关系评估</p>
            </div>
          </div>
        </div>

        <!-- 右列：风险预警——独立于好感总分，双证据判定，不进雷达/总分 -->
        <div class="col-side">
          <RiskSignalCard :assessment="analysisResult.risk_assessment" />
          <p v-if="!analysisResult.risk_assessment" class="risk-empty-hint">
            旧分析结果不含风险预警，重新运行关系洞察分析后在此生成
          </p>
        </div>
      </div>

      <!-- 维度拆解：页尾通栏，子维度得分明细 -->
      <CtCard title="维度拆解" class="breakdown-card">
        <div class="breakdowns-container">
          <SubScoreBreakdown v-if="analysisResult.interaction_investment" title="互动投入"
            :sub-scores="analysisResult.interaction_investment.sub_scores" />
          <SubScoreBreakdown v-if="analysisResult.emotional_resonance" title="情感共鸣"
            :sub-scores="analysisResult.emotional_resonance.sub_scores"
            :confidence-meta="analysisResult.emotional_resonance.confidence_meta" />
          <SubScoreBreakdown v-if="analysisResult.closeness_signals" title="亲近信号"
            :sub-scores="analysisResult.closeness_signals.sub_scores"
            :confidence-meta="analysisResult.closeness_signals.confidence_meta" />
          <SubScoreBreakdown v-if="analysisResult.preference_compatibility" title="喜好兼容度"
            :sub-scores="analysisResult.preference_compatibility.sub_scores" />
          <SubScoreBreakdown v-if="analysisResult.llm_relationship" title="AI 关系评估"
            :sub-scores="analysisResult.llm_relationship.sub_scores"
            :notes="llmEvidenceNotes" />
          <p v-else-if="analysisResult.llm_relationship_absent_reason && llmPhase !== 'running'" class="llm-absent-note">
            AI 关系评估未参与本次评分：{{ analysisResult.llm_relationship_absent_reason }}
            <button
              class="btn llm-retry-btn"
              :disabled="llmRetryRunning"
              @click="handleRetryLlmRelationship"
            >{{ llmRetryRunning ? 'AI 评估中…' : '重试 AI 评估' }}</button>
          </p>
          <p v-if="llmRetryError" class="llm-absent-note">{{ llmRetryError }}</p>
        </div>
      </CtCard>
    </template>
    </template>
  </div>

  <!-- TAB 2: Features -->
  <div v-show="currentTab === 'features' && selectedConversationId" class="tab-content fade-in">
    <div v-if="!hasFeatures && !isGlobalAnalyzing" class="empty-state">
      <div class="empty-icon"><TrendingUp :size="56" :stroke-width="1.5" style="color: var(--ct-color-primary);" /></div>
      <p>点击"开始全面分析"获取深度互动特征分析。</p>
      <p class="empty-hint" style="display: inline-flex; align-items: center; gap: 6px;"><Lightbulb :size="14" style="color: var(--ct-color-info); flex-shrink: 0;" /> 互动特征包含：回响响应分布、主动性分析、话语权比例等客观指标</p>
    </div>

    <!-- Analyzing State（特征提取阶段完成即放开本页签） -->
    <div v-if="isGlobalAnalyzing && !hasFeatures" class="empty-state">
      <div class="empty-icon spinning"><Loader2 :size="56" class="spin-icon" style="color: var(--ct-color-primary);" /></div>
      <p>正在分析中，请耐心等待...</p>
      <p class="empty-hint" style="display: inline-flex; align-items: center; gap: 6px;"><Lightbulb :size="14" style="color: var(--ct-color-info); flex-shrink: 0;" /> 我们正在处理特征提取和模型推理</p>
    </div>

    <div v-if="hasFeatures" class="features-layout">
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
              <span class="stat-num">{{ displayWordRatioLabel }}</span>
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
                <circle cx="50" cy="50" r="30" fill="transparent" stroke="var(--ct-chart-4)" stroke-width="20" stroke-dasharray="188.5" stroke-dashoffset="0"></circle>
                <circle cx="50" cy="50" r="30" fill="transparent" stroke="var(--ct-color-primary)" stroke-width="20" :stroke-dasharray="`${(1 - (initiativeStats.initiativeRate || 0)) * 188.5} 188.5`" stroke-dashoffset="0"></circle>
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
      :all-from="conversationSpan?.from || ''"
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

  <!-- TAB 4: History QA (问问微信·聊天框：流式打字机 + 引用溯源 + 底部输入 + 滚底) -->
  <div v-show="currentTab === 'qa' && selectedConversationId" class="tab-content fade-in">
    <div class="qa-shell">
      <div class="qa-header">
        <div class="qa-header-row">
          <h3 class="qa-title">问问微信</h3>
          <button v-if="qaHistory.length" class="text-action-btn qa-clear-btn" @click="handleClearQa">清空对话</button>
        </div>
        <p class="qa-subtitle">向 {{ currentContactName }} 的聊天记录提问，回答附带引用溯源（仅检索当前联系人）</p>
        <!-- 语义索引懒补在途：本轮回答仍以关键词检索为主，补完自动生效 -->
        <p v-if="qaIndexingHint" class="qa-indexing-hint">正在为该会话补充语义索引，完成后回答会更准</p>
      </div>

      <!-- 聊天流：时间正序，问答成对出现；流式增量在距底时自动跟随，上滚即停跟随 -->
      <div ref="qaChatBox" class="qa-chat" @scroll="handleQaScroll">
        <div v-if="!qaHistory.length && !qaLoading" class="qa-empty">
          <p class="qa-empty-text">还没有提问记录。试试：</p>
          <div class="qa-suggest-row">
            <button
              v-for="s in qaSuggestions"
              :key="s"
              class="qa-suggest-chip"
              @click="handlePickSuggestion(s)"
            >{{ s }}</button>
          </div>
        </div>

        <div v-for="(item, idx) in qaHistory" :key="item.id" class="qa-msg">
          <div class="qa-row qa-row-user">
            <div class="qa-bubble qa-bubble-user">
              <span class="qa-bubble-text">{{ item.question }}</span>
            </div>
          </div>
          <div class="qa-row qa-row-ai">
            <span class="qa-a-mark">AI</span>
            <div class="qa-bubble qa-bubble-ai">
              <!-- 错误内联：不再弹窗打断，原地重试 -->
              <div v-if="item.error" class="qa-error">
                <span class="qa-error-text">{{ item.error }}</span>
                <button class="text-action-btn" @click="handleRetryQa(item)">重试</button>
              </div>
              <template v-else>
                <!-- 首字未到：打字点等待态 -->
                <div v-if="item.streaming && !item.answer" class="qa-typing">
                  <span class="qa-typing-dots"><i></i><i></i><i></i></span>
                  <span class="qa-typing-hint">正在检索聊天记录并生成回答...</span>
                </div>
                <template v-else>
                  <div class="qa-bubble-text qa-md" @click="handleCiteClick" v-html="renderQaEntryAnswer(item)"></div>
                  <span v-if="item.streaming" class="qa-stream-cursor" aria-hidden="true"></span>
                </template>
                <span v-if="item.stopped" class="qa-stopped-badge">已停止</span>
                <span v-if="item.truncated" class="qa-stopped-badge">已截断（网络中断，回答不完整）</span>
                <span v-if="item.degraded" class="qa-stopped-badge">模型暂不可用 · 检索直出</span>
                <template v-if="!item.streaming">
                  <div class="qa-actions">
                    <button
                      class="text-action-btn qa-copy-btn"
                      :class="{ copied: copiedQaKey === `a-${item.id}` }"
                      @click="handleCopyQa(item.answer, `a-${item.id}`)"
                    >
                      {{ copiedQaKey === `a-${item.id}` ? '已复制' : '复制' }}
                    </button>
                    <button
                      v-if="idx === qaHistory.length - 1 && !qaLoading"
                      class="text-action-btn"
                      @click="handleRegenerateQa"
                    >重新生成</button>
                  </div>
                  <details v-if="item.citations && item.citations.length" class="qa-citations-fold">
                    <summary class="qa-citations-title">引用溯源（{{ item.citations.length }} 条）</summary>
                    <div v-for="(cite, cIdx) in item.citations" :key="cIdx" class="qa-citation-row">
                      <span class="qa-citation-idx">[{{ cite.index }}]</span>
                      <span class="qa-citation-meta">{{ formatQaTime(cite.timestamp) }} · {{ cite.is_sender ? '我' : currentContactName }}</span>
                      <span class="qa-citation-text">"{{ cite.text }}"</span>
                    </div>
                  </details>
                  <details v-if="item.memoryRefs && item.memoryRefs.length" class="qa-citations-fold qa-memory-fold">
                    <summary class="qa-citations-title">参考记忆（{{ item.memoryRefs.length }} 条）· 可就地纠错</summary>
                    <div v-for="(mem, mIdx) in item.memoryRefs" :key="mIdx" class="qa-citation-row qa-memory-row">
                      <span class="qa-memory-kind" :class="{ fact: mem.source === 'fact_memory' }">
                        {{ mem.source === 'fact_memory' ? '事实' : '话题' }}
                      </span>
                      <span class="qa-citation-text">"{{ mem.content }}"</span>
                      <span v-if="mem.as_of" class="qa-citation-meta">{{ formatQaTime(mem.as_of) }}</span>
                      <template v-if="mem.source === 'fact_memory' && mem.ref_id">
                        <span v-if="qaMemoryFeedback[mem.ref_id]" class="qa-memory-done">
                          {{ qaMemoryFeedback[mem.ref_id] === 'inaccurate' ? '已标记不准确' : '已忘记' }}
                        </span>
                        <template v-else>
                          <button
                            class="text-action-btn qa-memory-btn"
                            :disabled="qaMemoryBusy[mem.ref_id]"
                            @click="handleMemoryFeedback(mem, 'inaccurate')"
                          >不准确</button>
                          <button
                            class="text-action-btn qa-memory-btn"
                            :disabled="qaMemoryBusy[mem.ref_id]"
                            @click="handleMemoryFeedback(mem, 'forget')"
                          >忘记</button>
                        </template>
                      </template>
                    </div>
                  </details>
                </template>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区：auto-grow 文本域 + 内嵌发送/停止二合一；生成中可继续打字 -->
      <div class="qa-input-row">
        <div class="qa-input-box" :class="{ focused: qaInputFocused }">
          <textarea
            ref="qaInputEl"
            v-model="qaInput"
            class="qa-input"
            rows="1"
            placeholder="例如：我们聊过哪些共同爱好？TA 对加班是什么态度？"
            maxlength="200"
            @input="autoGrowQaInput"
            @focus="qaInputFocused = true"
            @blur="qaInputFocused = false"
            @keydown.enter.exact="handleQaEnter"
          ></textarea>
          <button
            class="qa-send-btn"
            :class="{ stop: qaLoading }"
            :disabled="!qaLoading && !qaInput.trim()"
            :title="qaLoading ? '停止生成' : '发送（Enter 发送，Shift+Enter 换行）'"
            @click="qaLoading ? handleStopQa() : handleAskHistory()"
          >
            <svg v-if="qaLoading" class="qa-send-icon" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="3" y="3" width="10" height="10" rx="2" fill="currentColor"></rect>
            </svg>
            <svg v-else class="qa-send-icon" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 13V3.8" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>
              <path d="M3.8 7 8 2.8 12.2 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"></path>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB: 时光深度（时间窗长期演变：情绪曲线/词云演变/画像演变/里程碑，单聊专属） -->
  <!-- v-if 懒激活：首次进入页签才挂载重计算面板（词云 jieba×2、全量扫描×2）， -->
  <!-- 从不打开则零开销；激活后保持挂载（v-show 切换不重复请求）。加 -->
  <!-- !isGroupConversation：切群聊立即卸载——v-show 只隐藏不卸载，挂着的 -->
  <!-- watch 会对群聊 id 发起重载荷并把"对方=全群"的画像写进 big5 缓存 -->
  <div v-show="currentTab === 'deep' && selectedConversationId" class="tab-content fade-in deep-tab">
    <template v-if="deepActivated && !isGroupConversation">
      <DateRangeFilter
        :dates="deepDates"
        :loading="false"
        show-granularity
        :show-export="false"
        :all-from="conversationSpan?.from || ''"
        :granularity="deepGranularity"
        @update:dates="onDeepDatesChange"
        @update:granularity="deepGranularity = $event"
        @refresh="deepRefreshKey++"
      />
      <TimeDeepTab
        :key="`${selectedConversationId}-${deepRefreshKey}`"
        :conversation-id="selectedConversationId"
        :dates="deepDates"
        :granularity="deepGranularity"
        :view-epoch="viewEpoch"
        :contact-name="currentContactName"
      />
    </template>
  </div>

  <!-- TAB: TA 画像（画像档案/大五印象/分享海报，单聊专属；画像演变留在时光深度） -->
  <!-- 懒激活同上：PosterStudio/大五首次进入才挂载取数；日期窗独立 personaDates（默认全量） -->
  <div v-show="currentTab === 'persona' && selectedConversationId" class="tab-content fade-in persona-tab">
    <template v-if="personaActivated && !isGroupConversation">
      <DateRangeFilter
        :dates="personaDates"
        :loading="false"
        :show-export="false"
        :all-from="conversationSpan?.from || ''"
        @update:dates="onPersonaDatesChange"
        @refresh="deepRefreshKey++"
      />
      <div :key="`persona-${selectedConversationId}-${deepRefreshKey}`" class="persona-flow">
        <!-- 画像档案（生成入口在画廊头部） -->
        <div class="persona-tab-shell">
          <PersonaGallery
            :loading="loadingPersonaProfile"
            :contact-name="currentContactName"
            :conversation-id="selectedConversationId"
            :profile="personaProfile"
            :profile-meta="personaProfileMeta"
            :window-info="personaProfileMeta.window"
            :account-wxid="activeAccountWxid || ''"
            :analysis="analysis"
            :analysis-result="analysisResult"
            :feature-stats="featureStats"
            :sessions="sessions"
            :activity-calendar-summary="activityCalendar.summary"
            @generate="showPortraitDialog = true"
          />
          <!-- 我的画像：更新画像默认含自我画像，这里让生成结果可见 -->
          <ProfileBriefCard
            kind="self"
            class="persona-self-card"
            :contact-name="realContactName"
            :account-wxid="activeAccountWxid || ''"
            :refresh-key="profileRefreshKey"
            @generate="showPortraitDialog = true"
          />
        </div>
        <BigFivePanel :conversation-id="selectedConversationId" />
        <PosterStudio :conversation-id="selectedConversationId" :dates="personaDates" :contact-name="currentContactName" />
      </div>
    </template>
  </div>

  <!-- TAB 6: 实时助手（监听控制 + 双方画像 + 按联系人的建议配置；选人由页头 FiltersBar 贯通） -->
  <div v-show="currentTab === 'realtime' && selectedConversationId && !isGroupConversation" class="tab-content fade-in realtime-tab">
    <MonitorControlCard
      :conversation-id="selectedConversationId"
      :contact-name="currentContactName"
      :account-wxid="activeAccountWxid || ''"
    />
    <!-- 双方画像速览（重构前 Suggestions 页双卡的回归） -->
    <div class="realtime-profiles">
      <ProfileBriefCard
        kind="contact"
        :contact-name="realContactName"
        :account-wxid="activeAccountWxid || ''"
        :refresh-key="profileRefreshKey"
        @generate="showPortraitDialog = true"
      />
      <ProfileBriefCard
        kind="self"
        :contact-name="realContactName"
        :account-wxid="activeAccountWxid || ''"
        :refresh-key="profileRefreshKey"
        @generate="showPortraitDialog = true"
      />
    </div>
  </div>

  <!-- Dialogs -->
  <PreferenceKeywordsDialog v-if="selectedConversationId" v-model="showKeywordsDialog"
    :conversation-id="selectedConversationId" @updated="handleKeywordsUpdated" />
  <PortraitGenerateDialog
    :visible="showPortraitDialog"
    :display-name="currentContactName"
    :account-wxid="activeAccountWxid || undefined"
    :show-self-panel="true"
    :cancel-key="selectedConversationId || 0"
    @close="showPortraitDialog = false"
    @generated="handlePortraitGenerated"
  />
  <RelationshipContextForm v-if="selectedConversationId" v-model="showContextForm"
    :conversation-id="selectedConversationId" @saved="handleContextSaved" />
</section>

    <!-- 导出聊天记录弹窗 -->
    <Teleport to="body">
      <div v-if="exportDialogVisible" class="ct-modal-overlay" @click.self="exportDialogVisible = false">
        <div class="export-dialog">
          <div class="pd-header">
            <h3 class="pd-title">导出聊天记录</h3>
            <button class="pd-close" @click="exportDialogVisible = false">✕</button>
          </div>
          <div v-if="!exportResult" class="export-body">
            <div class="export-formats">
              <label v-for="opt in [
                { value: 'txt', label: 'TXT 纯文本', tip: '打印/备忘录' },
                { value: 'csv', label: 'CSV 表格', tip: 'Excel/分析' },
                { value: 'html', label: 'HTML 聊天页', tip: '分享/存档' },
              ]" :key="opt.value" class="export-fmt" :class="{ active: exportFormat === opt.value }">
                <input type="radio" :value="opt.value" v-model="exportFormat" class="sr-only" />
                <span class="export-fmt-label">{{ opt.label }}</span>
                <span class="export-fmt-tip">{{ opt.tip }}</span>
              </label>
            </div>
            <div class="export-hint">导出当前选中联系人的全部聊天记录（含日期范围筛选）。</div>
          </div>
          <div v-else class="export-body">
            <div class="export-success">
              <p>✅ 已导出 {{ exportResult.count }} 条消息</p>
              <p class="export-path">{{ exportResult.path }}</p>
              <button class="ct-btn secondary ct-btn-sm" @click="openExportFolder">打开所在文件夹</button>
            </div>
          </div>
          <div class="pd-footer">
            <button v-if="!exportResult" class="ct-btn ghost" @click="exportDialogVisible = false">取消</button>
            <button v-if="!exportResult" class="ct-btn primary" :disabled="exporting" @click="confirmExport">
              {{ exporting ? '导出中…' : '导出' }}
            </button>
            <button v-else class="ct-btn primary" @click="exportDialogVisible = false">完成</button>
          </div>
        </div>
      </div>
    </Teleport>
</template>

<script lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { bridgeReady, api, type AnalysisDeviceMode } from '@/api/bridge'
import { analyzeAffinity, getAffinityScores, getAffinityProgress, getRelationshipContext, retryLlmRelationship, type AffinityAnalysisResult } from '@/api/affinity'
import { resolveAffinityPollAction } from '@/utils/affinityPoll'
import { getScoreColor, HEAT_RAMP, chartPalette } from '@/components/charts/chartTheme'

import FiltersBar from '@/components/analytics/FiltersBar.vue'
import DateRangeFilter from '@/components/analytics/DateRangeFilter.vue'
import MonitorControlCard from '@/components/realtime/MonitorControlCard.vue'
import SubjectCard from '@/components/analytics/SubjectCard.vue'
import EmotionLineChart from '@/components/charts/EmotionLineChart.vue'
import WordCloud from '@/components/charts/WordCloud.vue'
import ConversationTimeline from '@/components/timeline/ConversationTimeline.vue'

import AffinityScoreCard from '@/components/affinity/AffinityScoreCard.vue'
import RiskSignalCard from '@/components/affinity/RiskSignalCard.vue'
import PortraitGenerateDialog from '@/components/persona/PortraitGenerateDialog.vue'
import { copyText } from '@/utils/clipboard'
import { renderQaAnswer } from '@/utils/qaMarkdown'
import DimensionRadar from '@/components/affinity/DimensionRadar.vue'
import SubScoreBreakdown from '@/components/affinity/SubScoreBreakdown.vue'
import PreferenceKeywordsDialog from '@/components/affinity/PreferenceKeywordsDialog.vue'
import RelationshipContextForm from '@/components/affinity/RelationshipContextForm.vue'
import CtCard from '@/components/base/CtCard.vue'
import CtButton from '@/components/base/CtButton.vue'
import PersonaGallery from '@/components/persona/PersonaGallery.vue'
import ProfileBriefCard from '@/components/persona/ProfileBriefCard.vue'
import { showDialog, showConfirm } from '@/utils/dialog'
import { safeGetItem, safeRemoveItem, safeSetItem } from '@/utils/safeStorage'
import { toLocalDateKey } from '@/utils/datetime'
import CtAvatar from '@/components/base/CtAvatar.vue'
import TimeDeepTab from '@/components/deep/TimeDeepTab.vue'
import BigFivePanel from '@/components/deep/BigFivePanel.vue'
import PosterStudio from '@/components/deep/PosterStudio.vue'
import {
  FolderArchive,
  MessageSquare,
  Sparkles,
  BarChart3,
  TrendingUp,
  Loader2,
  Lightbulb
} from 'lucide-vue-next'

type Conversation = { id: number; name: string; username: string; message_count: number; last_message_time: string; avatar?: string; conversation_type?: 'private' | 'group' }
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
        AffinityScoreCard, DimensionRadar, SubScoreBreakdown, RiskSignalCard,         PreferenceKeywordsDialog, RelationshipContextForm, CtCard, CtButton, PersonaGallery, CtAvatar,
        FolderArchive, MessageSquare, Sparkles, BarChart3, TrendingUp, Loader2, Lightbulb, PortraitGenerateDialog, TimeDeepTab,
        BigFivePanel, PosterStudio, ProfileBriefCard,
        MonitorControlCard
    },
    setup() {
        const currentTab = ref('affinity')
        // 时光深度：分桶粒度（周/月/年）与手动刷新纪元（+1 强制 TimeDeepTab 重挂载重取）
        const deepGranularity = ref('week')
        const deepRefreshKey = ref(0)
        // 时光深度懒激活：首次进入该页签才置 true，面板随 v-if 挂载
        const deepActivated = ref(false)
        // TA 画像懒激活：首次进入才挂载 PersonaGallery/大五/海报（免无谓取数）
        const personaActivated = ref(false)
        const activeAccountWxid = ref('')

        // Core State
        const conversations = ref<Conversation[]>([])
        const selectedConversationId = ref<number | null>(null)

        const dates = reactive({ from: '', to: '' })
        // 时光深度独立时间窗：该页正文（章节/词云/大五/画像/里程碑）按全会话
        // 章节分段、不吃日期筛选，日期窗只缩放情绪曲线——与其它页签共享 dates
        // 时「默认近30天」会和下方的全量内容打架，故本页签默认全量、独立记忆
        const deepDates = reactive({ from: '', to: '' })
        // TA 画像同样默认全量：画像/大五印象/海报都是长周期叙事，近 30 天
        // 窗会把海报 payload 截成一小段；与时光深度各自独立记忆互不影响
        const personaDates = reactive({ from: '', to: '' })
        // 会话消息真实跨度（首/末条日期）：「全部」快捷键与时光深度默认窗的起点，
        // 替代 2000-01-01 占位——输入框显示 2000 年会让人以为筛选错了
        const conversationSpan = ref<{ from: string; to: string } | null>(null)
        const loading = ref(false)
        const loadingSessions = ref(false)
        const error = ref('')
        const analysis = reactive<Analysis>({ timeseries: [], wordcloud: [] })
        const subject = ref<Subject | undefined>(undefined)
        const sessions = ref<Session[]>([])
        const personaProfile = ref<ContactProfile | null>(null)
        // 画像简卡（实时助手双卡 + TA 画像页我的画像卡）的刷新键：生成完成后 +1
        const profileRefreshKey = ref(0)
        const loadingPersonaProfile = ref(false)
        const personaProfileMeta = reactive({
            createdAt: null as number | null,
            expiresAt: null as number | null,
            expired: false,
            estimatedTokens: 0,
            // 当前画像的窗口标注（rolling→「最近 N 天」/ custom→「起 ~ 止」）
            window: null as { kind: string; from: number; to: number; days: number; label: string } | null
        })
        const responseTimeChart = ref<HTMLDivElement | null>(null)
        const activityCalendarChart = ref<HTMLDivElement | null>(null)
        const wordCountChart = ref<HTMLDivElement | null>(null)
        let responseTimeChartInstance: echarts.ECharts | null = null
        let activityCalendarChartInstance: echarts.ECharts | null = null
        let wordCountChartInstance: echarts.ECharts | null = null

        const stats = ref<{ totalMessages: number; avgSentiment: number; activeDays: number; sessionCount: number } | null>(null)
        
        const analysisResult = ref<AffinityAnalysisResult | null>(null)
        // AI 关系评估阶段机：本地四维先行渲染后 LLM 仍在评估（running）→
        // 终态按 llm_relationship 在场与否置 done/absent；idle = 未在评估
        const llmPhase = ref<'idle' | 'running' | 'done' | 'absent'>('idle')
        // 曾分析过但当前结果不可用（缓存版本过期）——空态给"需重新分析"解释
        // 而非伪装成从未分析
        const analysisStaleNotice = ref(false)
        // AI 关系评估补评（LLM 维瞬时缺席后的重试）：进行中标志 + 最近一次失败原因
        const llmRetryRunning = ref(false)
        const llmRetryError = ref('')
        const displayScore = ref(0)
        const showKeywordsDialog = ref(false)
const showPortraitDialog = ref(false)
        const showContextForm = ref(false)
        const analysisLaunchPending = ref(false)
        const isGlobalAnalyzing = ref(false)
        const isStopping = ref(false)
        const activeTimer = ref<any>(null)
        const viewEpoch = ref(0)                 // 视图代数：切换联系人时递增，丢弃过期异步结果（F1）

        // ===== 进行中分析的跨页面恢复（切走再回来接续进度而非重新分析） =====
        const ANALYSIS_RESUME_KEY = 'chrono_analytics_active_analysis'
        type AnalysisResumeState = { conversationId: number; phase: 'extract' | 'affinity'; taskId: string }
        function saveAnalysisResume(state: AnalysisResumeState) {
            safeSetItem(ANALYSIS_RESUME_KEY, JSON.stringify(state), sessionStorage)
        }
        function clearAnalysisResume() {
            safeRemoveItem(ANALYSIS_RESUME_KEY, sessionStorage)
        }
        function loadAnalysisResume(): AnalysisResumeState | null {
            try {
                const raw = safeGetItem(ANALYSIS_RESUME_KEY, sessionStorage)
                const parsed = raw ? JSON.parse(raw) : null
                if (parsed && parsed.conversationId && parsed.taskId && parsed.phase) return parsed
                return null
            } catch { return null }
        }
        const globalProgressPercent = ref(0)
        const globalProgressStep = ref('')
        const analysisDeviceMode = ref<AnalysisDeviceMode>('auto')
        const gpuMode = ref<'gpu' | 'cpu'>('cpu')

        const hasFeatures = ref(false)
        
        const featureStats = ref({ avgResponseTime: 0, medianResponseTime: 0, initiativeRate: 0, wordRatio: 0 })
        const responseTimeStats = ref({ count: 0, avg: 0, median: 0, max: 0, mode: '', distribution: {} as Record<string, number>, distributionKeys: [] as string[] })
        const initiativeStats = ref({ totalSessions: 0, userInitiatedSessions: 0, otherInitiatedSessions: 0, initiativeRate: 0, interpretation: '' })
        const wordCountsStats = ref({ userCharCount: 0, otherCharCount: 0, charRatio: 0, interpretation: '' })
        const displayWordRatioLabel = computed(() => {
            const { userCharCount, otherCharCount } = wordCountsStats.value
            if (!userCharCount && !otherCharCount) return '0 : 1'
            if (!otherCharCount) return '∞ : 1'
            return `${(userCharCount / otherCharCount).toFixed(2)} : 1`
        })
        const activityCalendar = ref<ActivityCalendarData>({ year: new Date().getFullYear(), years: [], entries: [], summary: { active_days: 0, total_messages: 0, current_streak: 0, longest_streak: 0, peak_day: null, global_first_session_start_time: null, global_peak_session: null }, max_activity_score: 0 })
        
        let cancelCurrentAnalysis: (() => void) | null = null

        const responseTimeBucketGroups: Record<string, string[]> = {
            '<10m': ['<1m', '1m-10m'],
            '10m-1h': ['10m-30m', '30m-1h'],
            '1h-24h': ['1h-6h', '6h-24h'],
            '>1d': ['>1d']
        }

        const shouldLoadContentAnalysis = computed(() => {
            return currentTab.value === 'content' || currentTab.value === 'deep' || currentTab.value === 'persona'
        })
        const hasContentAnalysis = computed(() => {
            return Boolean(subject.value?.stats && (
                (subject.value.stats.msgCount || 0) > 0 ||
                analysis.wordcloud.length > 0 ||
                analysis.timeseries.length > 0
            ))
        })
        const hasConversations = computed(() => conversations.value.length > 0)
        const currentConversation = computed(() => {
            if (!selectedConversationId.value) return undefined
            return conversations.value.find(c => c.id === selectedConversationId.value)
        })

        const currentContactName = computed(() => {
            return currentConversation.value?.name || '选择联系人'
        })
        // 画像简卡取数用真实名（未选人为空串触发组件空态守卫，不发占位名「选择联系人」去后端）
        const realContactName = computed(() => currentConversation.value?.name || '')
        const isGroupConversation = computed(() => {
            return currentConversation.value?.conversation_type === 'group'
        })

        // ===== 群聊工作台（发言统计 + 日报）=====
        type GroupMemberStat = { name: string; message_count: number; char_count: number; share: number }
        type GroupStats = { total_messages: number; members: GroupMemberStat[]; my_rank: number | null; top_words: Array<{ word: string; count: number }> }
        const groupStats = ref<GroupStats | null>(null)
        const groupStatsLoading = ref(false)
        const groupSummary = ref<{ summary: string; degraded: boolean; degraded_reason?: string } | null>(null)
        const groupSummaryLoading = ref(false)
        const groupSummaryDays = ref(7)

        async function loadGroupStats() {
            if (!isGroupConversation.value || !selectedConversationId.value) {
                groupStats.value = null
                return
            }
            const conversationId = selectedConversationId.value
            groupStatsLoading.value = true
            try {
                await bridgeReady()
                const res = await api.get_group_stats(conversationId)
                if (conversationId !== selectedConversationId.value) return // 已切换联系人（F1）
                groupStats.value = res?.ok ? res : null
            } catch (e) {
                groupStats.value = null
            } finally {
                groupStatsLoading.value = false
            }
        }

        async function handleGenerateGroupSummary() {
            if (!selectedConversationId.value || groupSummaryLoading.value) return
            groupSummaryLoading.value = true
            const conversationId = selectedConversationId.value
            try {
                await bridgeReady()
                const res = await api.generate_group_summary(conversationId, groupSummaryDays.value)
                if (conversationId !== selectedConversationId.value) return // 已切换联系人（F1）
                if (res?.ok) {
                    groupSummary.value = res
                } else {
                    const msg = String(res?.error || '日报生成失败，请重试')
                    if (!msg.includes('已取消')) showDialog(msg) // 主动取消不弹错误
                }
            } catch (e: any) {
                showDialog(e?.message || '日报生成异常')
            } finally {
                groupSummaryLoading.value = false
            }
        }

        async function handleCancelGroupSummary() {
            if (!groupSummaryLoading.value || !selectedConversationId.value) return
            try {
                await bridgeReady()
                await api.cancel_group_summary(selectedConversationId.value)
            } catch {
                // 取消失败不打断（后端请求会自行超时返回）
            }
        }
        const headerAvatarSrc = computed(() => {
            const currentId = selectedConversationId.value
            const subjectId = subject.value?.id
            const subjectMatchesSelection = currentId != null && subjectId != null && Number(subjectId) === Number(currentId)
            if (subjectMatchesSelection && subject.value?.avatar) {
                return subject.value.avatar
            }
            return currentConversation.value?.avatar || ''
        })

        const hasPreferenceKeywords = computed(() => {
            const preference = analysisResult.value?.preference_compatibility
            if (!preference) return false
            return (preference.bonus_scores?.preference_bonus ?? 0) > 0
        })
        const hasCachedAffinityAnalysis = computed(() => Boolean(analysisResult.value))

        // ===== 问问微信（历史问答 + 引用溯源·聊天框：流式打字机）=====
        type QaCitation = { index: number; message_id: number; timestamp: number; is_sender: number; text: string }
        // 参考记忆溯源：AI 本轮实际采用的 RAG 记忆（fact 通道 ref_id=事实主键，
        // 可就地纠错；文档通道只读展示）
        type QaMemoryRef = { content: string; source: string; ref_id: number; subject?: string; as_of?: number | null; confidence?: number | null }
        // streaming：LLM 增量在途；stopped：用户点停已定格部分文本；error：内联错误（可重试）；
        // degraded：LLM 失败降级检索直出；truncated：流式中途断网已收部分当结果
        type QaEntry = {
            id: number; question: string; answer: string; citations: QaCitation[]; memoryRefs?: QaMemoryRef[]
            streaming?: boolean; stopped?: boolean; error?: string; reqId?: string
            degraded?: boolean; truncated?: boolean
        }
        // 时间正序（聊天流展示：新问答 push 到尾部，容器自动滚底）
        const qaHistory = ref<QaEntry[]>([])
        const qaInput = ref('')
        const qaLoading = ref(false)
        // 语义索引懒补在途提示（切联系人/重置账号时清位；不轮询，下次提问自然生效）
        const qaIndexingHint = ref(false)
        const qaChatBox = ref<HTMLElement | null>(null)
        const qaInputEl = ref<HTMLTextAreaElement | null>(null)
        const qaInputFocused = ref(false)
        // 吸底跟随：流式增量只在用户位于底部附近时滚底，上滚阅读即停跟随
        const qaAutoScroll = ref(true)
        // 当前在途请求标识：流式增量按它匹配到气泡（重试/重新生成各自新发一个）
        let qaReqId = ''

        function scrollQaToBottom() {
            nextTick(() => {
                const el = qaChatBox.value
                if (el) el.scrollTop = el.scrollHeight
            })
        }
        watch(() => qaHistory.value.length, scrollQaToBottom)
        // 生成结束的滚底走跟随模式（maybeScrollQa）：用户上滚阅读时不被
        // 强行拉回底部；发送时的强制滚底由 runAsk push 条目后显式做
        watch(qaLoading, maybeScrollQa)

        function handleQaScroll() {
            const el = qaChatBox.value
            if (!el) return
            qaAutoScroll.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 48
        }

        function maybeScrollQa() {
            if (!qaAutoScroll.value) return
            scrollQaToBottom()
        }

        function formatQaTime(ts: number): string {
            if (!ts) return '--'
            return new Date(ts * 1000).toLocaleString('zh-CN', {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit',
            })
        }

        // ===== 文本复制（答案/定性分析等，带瞬时反馈）=====
        const copiedQaKey = ref('')
        const overallCopied = ref(false)
        let copyFeedbackTimer: ReturnType<typeof setTimeout> | null = null

        function flashCopied(key: 'overall' | string) {
            copiedQaKey.value = key
            overallCopied.value = key === 'overall'
            if (copyFeedbackTimer) clearTimeout(copyFeedbackTimer)
            copyFeedbackTimer = setTimeout(() => {
                copiedQaKey.value = ''
                overallCopied.value = false
            }, 2000)
        }

        function handleCopyQa(text: string, key: string) {
            if (copyText(text)) flashCopied(key)
        }

        function handleCopyOverall() {
            const text = analysisResult.value?.overall_interpretation || ''
            if (copyText(text)) flashCopied('overall')
        }

        // 空态建议问题：通用记忆问句模板（点击填入输入框），不动输入焦点外的任何状态
        const qaSuggestions = computed(() => [
            '我们最近聊了什么话题？',
            `${currentContactName.value}提过哪些喜欢的东西？`,
            '我们聊过哪些共同爱好？',
            '上次我们聊得最开心的是什么？',
        ])

        function handlePickSuggestion(text: string) {
            qaInput.value = text
            autoGrowQaInput()
            qaInputEl.value?.focus()
        }

        // 模型门槛：未启用任何 LLM 时返回错误文案（由调用方内联到气泡，不弹窗）
        async function ensureQaLlmReady(): Promise<string | null> {
            try {
                const llmRes = await api.get_llm_models()
                const hasActive = Boolean(llmRes?.ok && llmRes.models?.some((m: any) => m.is_active))
                if (!hasActive) return '问问微信需要 LLM 模型，请先在「设置 → 模型服务」中配置并启用一个模型。'
                return null
            } catch {
                return '模型状态查询失败，请稍后重试。'
            }
        }

        // 输入区：auto-grow（1~5 行）；IME 组合态回车只上屏不发送
        function autoGrowQaInput() {
            const el = qaInputEl.value
            if (!el) return
            el.style.height = 'auto'
            el.style.height = `${Math.min(el.scrollHeight, 132)}px`
        }

        function handleQaEnter(e: KeyboardEvent) {
            // 中文输入法确认候选词的回车（isComposing/keyCode 229 双保险，
            // 旧 Safari 用后者）：上屏不发送——此前 keyup.enter 无守卫，
            // 组合确认的回车会把半截候选文本直接发出去
            if (e.isComposing || e.keyCode === 229) return
            e.preventDefault() // Enter 发送（单行语义），Shift+Enter 走默认换行
            handleAskHistory()
        }

        // 回答 HTML 渲染缓存：流式期间每帧全列表重渲染，历史条目 answer
        // 不变不得重跑 markdown 解析（按条目对象 WeakMap，answer 变更自动失效）
        const qaAnswerCache = new WeakMap<QaEntry, { answer: string; html: string }>()
        function renderQaEntryAnswer(item: QaEntry): string {
            let cached = qaAnswerCache.get(item)
            if (!cached || cached.answer !== item.answer) {
                cached = { answer: item.answer, html: renderQaAnswer(item.answer) }
                qaAnswerCache.set(item, cached)
            }
            return cached.html
        }

        // 流式增量（chrono:qa-push，App.vue 转投 CustomEvent）：按 req_id
        // 匹配在途气泡；已定格（停止/终态）的气泡丢弃迟到增量。增量经
        // rAF 尾随节流提交——token 级直写会让每 16ms 数次全组件重渲染
        // 加整段 markdown 重解析（O(len²)），攒一帧提交观感不变
        let qaStreamBuffer = ''
        let qaStreamEntry: QaEntry | null = null
        let qaFlushScheduled = false

        function flushQaStream() {
            qaFlushScheduled = false
            if (qaStreamEntry && qaStreamBuffer) {
                qaStreamEntry.answer += qaStreamBuffer
                qaStreamBuffer = ''
                maybeScrollQa()
            }
        }

        function scheduleQaFlush() {
            if (qaFlushScheduled) return
            qaFlushScheduled = true
            requestAnimationFrame(flushQaStream)
        }

        function dropQaStreamBuffer() {
            qaStreamBuffer = ''
            qaStreamEntry = null
        }

        // 停止时零文本被移除的在途条目：完整答案返回时回收（token 已花，
        // 答案不静默丢）。凭证存 reqId 原始字符串——条目对象经 reactive 数组
        // find 取出是代理，与 runAsk 闭包里的裸对象 === 恒不相等；清空对话/
        // 重发新问后旧条目不得复活成幽灵回答（配 qaReqId 纪元守卫双重确认）
        let qaStoppedReqId: string | null = null

        function handleQaPush(e: Event) {
            const payload = (e as CustomEvent).detail
            const events = Array.isArray(payload) ? payload : [payload]
            for (const ev of events) {
                if (!ev || ev.type !== 'delta' || ev.req_id !== qaReqId) continue
                if (Number(ev.conversation_id) !== selectedConversationId.value) continue
                const entry = qaHistory.value.find(item => item.reqId === ev.req_id)
                if (!entry || !entry.streaming) continue
                qaStreamEntry = entry
                qaStreamBuffer += String(ev.text || '')
                scheduleQaFlush()
            }
        }

        async function runAsk(question: string) {
            if (qaLoading.value || !selectedConversationId.value || !question) return
            qaLoading.value = true
            qaAutoScroll.value = true
            const conversationId = selectedConversationId.value
            const reqId = `qa_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
            qaReqId = reqId
            const entry: QaEntry = {
                id: Date.now(), // 稳定键：复制反馈不能跟着列表索引走
                question,
                answer: '',
                citations: [],
                streaming: true,
                reqId,
            }
            qaHistory.value.push(entry)
            scrollQaToBottom()
            try {
                const gateError = await ensureQaLlmReady()
                if (gateError) {
                    entry.streaming = false
                    entry.error = gateError
                    return
                }
                await bridgeReady()
                // 多轮：带上最近 3 轮可作上下文的问答——本条在途、失败、
                // 停止半截、降级通知（那不是模型答的）都不算有效答案。
                // 排除本条用 reqId 原始值：数组元素经 reactive 取出是代理，
                // 与闭包裸对象 !== 恒真，本条混进历史轮会带空答案占坑
                const history = qaHistory.value
                    .filter(e => e.reqId !== reqId && e.answer && !e.error && !e.stopped && !e.degraded && !e.truncated)
                    .slice(-3)
                    .map(e => ({ question: e.question, answer: e.answer }))
                const res = await api.ask_history(conversationId, question, history, reqId)
                if (conversationId !== selectedConversationId.value) return // 已切换联系人，丢弃过期回答
                if (res?.ok) {
                    // 取消竞态：点停后完整答案恰已返回——完整答案优先于停止定格
                    entry.answer = String(res.answer || entry.answer)
                    entry.citations = Array.isArray(res.citations) ? res.citations : []
                    entry.memoryRefs = Array.isArray(res.memory_refs) ? res.memory_refs : []
                    entry.stopped = false
                    entry.degraded = res.degraded === true
                    entry.truncated = res.truncated === true
                    // 停止时零文本被移除的条目回收插回（token 已花，答案不静默丢）；
                    // 纪元守卫防清空对话/停止后重发的旧条目复活成幽灵回答
                    if (qaHistory.value.indexOf(entry) < 0) {
                        if (qaStoppedReqId && qaStoppedReqId === reqId && qaReqId === reqId) {
                            qaHistory.value.push(entry)
                        }
                    }
                    if (qaStoppedReqId === reqId) qaStoppedReqId = null
                    // 后台语义索引懒补在途（不轮询：下次提问自然用上新索引）
                    qaIndexingHint.value = res.semantic_indexing === true
                } else {
                    if (entry.stopped) return // 本地已定格部分文本，取消返回不覆盖
                    entry.error = String(res?.error || '问答失败，请重试')
                }
            } catch (e: any) {
                if (!entry.stopped) entry.error = String(e?.message || '问答异常')
            } finally {
                entry.streaming = false
                entry.reqId = ''
                // 终态后未提交缓冲一律作废（答案以返回值为准）；纪元已易主时
                // 缓冲属新请求的流，不得误清（对齐下方 qaReqId 守卫）
                if (qaReqId === reqId) dropQaStreamBuffer()
                // 纪元守卫：停止后立即重发时 qaReqId 已易主，旧请求的收尾
                // 不得熄灭新请求的 loading 态
                if (qaReqId === reqId) {
                    qaReqId = ''
                    qaLoading.value = false
                }
            }
        }

        async function handleAskHistory() {
            const question = qaInput.value.trim()
            // 守卫与 runAsk 同口径先过再清输入：无会话等被拒场景下输入
            // 不被吞（runAsk 静默 return 无气泡留档，问题就丢了）
            if (!question || qaLoading.value || !selectedConversationId.value) return
            qaInput.value = '' // 发送即清空（失败已有问题气泡留档，错误条内联重试）
            nextTick(autoGrowQaInput)
            await runAsk(question)
        }

        function handleRetryQa(item: QaEntry) {
            if (qaLoading.value) return
            const idx = qaHistory.value.indexOf(item)
            if (idx >= 0) qaHistory.value.splice(idx, 1)
            void runAsk(item.question)
        }

        function handleRegenerateQa() {
            if (qaLoading.value || !qaHistory.value.length) return
            const last = qaHistory.value[qaHistory.value.length - 1]
            qaHistory.value.pop()
            void runAsk(last.question)
        }

        // 停止：本地立即定格部分文本（有字保留已停态、无字整条移除），
        // 再通知后端取消；迟到增量被 streaming=false 天然丢弃
        async function handleStopQa() {
            if (!qaLoading.value || !selectedConversationId.value) return
            const entry = qaHistory.value.find(item => item.streaming)
            if (entry) {
                // 先落未提交的流式缓冲再判空（定格所见即全部已收）
                if (qaStreamEntry === entry) {
                    entry.answer += qaStreamBuffer
                    dropQaStreamBuffer()
                }
                entry.streaming = false
                if (entry.answer) {
                    entry.stopped = true
                } else {
                    const idx = qaHistory.value.indexOf(entry)
                    if (idx >= 0) qaHistory.value.splice(idx, 1)
                    qaStoppedReqId = String(entry.reqId || '') // 零文本移除：完整答案返回时按 reqId 回收
                }
            }
            qaLoading.value = false
            try {
                await bridgeReady()
                await api.cancel_history_qa(selectedConversationId.value)
            } catch {
                // 取消失败不打断（后端请求会自行超时返回）
            }
        }

        function handleClearQa() {
            if (qaLoading.value) handleStopQa()
            qaHistory.value = []
            qaStoppedReqId = null // 清空意图优先：被移除条目不得借回收复活
        }

        // 参考记忆就地纠错：问答现场直接「不准确/忘记」，与记忆管理弹窗同接口；
        // 反馈按事实主键全局去重（同一事实多处引用一次纠错全部生效）
        const qaMemoryFeedback = reactive<Record<number, 'inaccurate' | 'forget'>>({})
        const qaMemoryBusy = reactive<Record<number, boolean>>({})

        async function handleMemoryFeedback(ref: QaMemoryRef, action: 'inaccurate' | 'forget') {
            const fid = Number(ref.ref_id || 0)
            if (!fid || qaMemoryFeedback[fid] || qaMemoryBusy[fid]) return
            qaMemoryBusy[fid] = true
            try {
                await bridgeReady()
                const res = await api.set_fact_feedback(fid, action)
                if (res?.ok) qaMemoryFeedback[fid] = action
            } catch {
                // 失败保持可重试，不打断问答流
            } finally {
                qaMemoryBusy[fid] = false
            }
        }

        // 引用上标可点：展开本气泡的引用溯源并滚到可见
        function handleCiteClick(e: MouseEvent) {
            const mark = (e.target as HTMLElement | null)?.closest?.('.qa-cite-mark')
            if (!mark) return
            const fold = mark.closest('.qa-bubble')?.querySelector('.qa-citations-fold') as HTMLDetailsElement | null
            if (!fold) return
            fold.open = true
            fold.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }

        const allDimensions = computed(() => {
            if (!analysisResult.value) return {}
            return {
                interaction_investment: analysisResult.value.interaction_investment || undefined,
                emotional_resonance: analysisResult.value.emotional_resonance || undefined,
                closeness_signals: analysisResult.value.closeness_signals || undefined,
                preference_compatibility: analysisResult.value.preference_compatibility || undefined,
                llm_relationship: analysisResult.value.llm_relationship || undefined
            }
        })

        // LLM 关系评估的证据条目（[{quote, month}]，来自 confidence_meta.evidence）
        const llmEvidenceNotes = computed<Array<{ quote: string; month: string }> | undefined>(() => {
            const meta = analysisResult.value?.llm_relationship?.confidence_meta as any
            const evidence = meta?.evidence
            return Array.isArray(evidence) && evidence.length
                ? evidence.map((e: any) => ({ quote: String(e.quote || ''), month: String(e.month || '') }))
                : undefined
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
            // 用本地时区日期键，避免 toISOString() 的 UTC 日期在东八区凌晨少一天
            dates.from = toLocalDateKey(from)
            dates.to = toLocalDateKey(to)
        }

        // 时光深度默认全量（与 DateRangeFilter 的「全部」快捷键同口径）
        function resetDeepDates() {
            deepDates.from = conversationSpan.value?.from || '2000-01-01'
            deepDates.to = toLocalDateKey(new Date())
        }

        function resetPersonaDates() {
            personaDates.from = conversationSpan.value?.from || '2000-01-01'
            personaDates.to = toLocalDateKey(new Date())
        }

        async function loadConversationSpan(id: number) {
            try {
                const res = await api.get_conversation_span(id)
                const data = res?.data
                if (!data?.from_date) return
                conversationSpan.value = { from: data.from_date, to: data.to_date || '' }
                // 跨度晚到：仅当默认窗还是占位起点时替换（用户已手动缩窗则不动）
                if (deepDates.from === '2000-01-01') resetDeepDates()
                if (personaDates.from === '2000-01-01') resetPersonaDates()
            } catch {
                // 查询失败维持占位，不阻塞主链路
            }
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

        // 设备向导是否已答过（区分「从未问过」与「用户在设置里明确选了自动」——
        // 后者不应被向导反复打扰或覆盖）
        const deviceWizardShown = ref(false)

        async function loadAnalysisDeviceMode() {
            try {
                const settings = await api.get_settings()
                deviceWizardShown.value = Boolean(settings?.analysis_device_wizard_shown)
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
                const res = await api.get_conversation_list(activeAccountWxid.value || undefined)
                if (res.ok) {
                    conversations.value = res.conversations
                    if (selectedConversationId.value && !conversations.value.some((item) => item.id === selectedConversationId.value)) {
                        selectedConversationId.value = null
                    }
                    if (conversations.value.length > 0 && !selectedConversationId.value) {
                        // 程序性默认选中列表第一个（用户未显式选择时）
                        onConversationChange(conversations.value[0].id)
                    } else if (conversations.value.length === 0) {
                        selectedConversationId.value = null
                    }
                }
            } catch (e: any) { console.error('加载联系人失败', e) }
        }

        function resetAccountScopedState() {
            selectedConversationId.value = null
            conversations.value = []
            analysisResult.value = null
            llmPhase.value = 'idle'
            qaHistory.value = []
            qaStoppedReqId = null // 账号切换整页换血：停止回收登记一并作废
            qaIndexingHint.value = false
            hasFeatures.value = false
            analysis.timeseries = []
            analysis.wordcloud = []
            subject.value = undefined
            sessions.value = []
            stats.value = null
            activityCalendar.value = {
                year: new Date().getFullYear(),
                years: [],
                entries: [],
                summary: {
                    active_days: 0,
                    total_messages: 0,
                    current_streak: 0,
                    longest_streak: 0,
                    peak_day: null,
                    global_first_session_start_time: null,
                    global_peak_session: null,
                },
                max_activity_score: 0,
            }
            resetPersonaProfile()
        }

        async function refreshAccountContext() {
            try {
                const result = await api.get_wechat_accounts()
                if (result?.ok) {
                    activeAccountWxid.value = result.active_account_wxid || ''
                }
            } catch (e) {
                console.error('刷新微信账号上下文失败', e)
            }
        }

        async function onConversationChange(id: number) {
            viewEpoch.value++ // 使进行中的加载与分析轮询结果全部过期（F1）
            if (qaLoading.value && selectedConversationId.value) {
                // 在途问答不再需要：取消后端请求（回答本就会被丢弃）
                api.cancel_history_qa(selectedConversationId.value).catch(() => {})
            }
            if (groupSummaryLoading.value && selectedConversationId.value) {
                api.cancel_group_summary(selectedConversationId.value).catch(() => {})
            }
            selectedConversationId.value = id
            setDefaultDates(30, getConversationAnchorDate(id))
            conversationSpan.value = null
            void loadConversationSpan(id)
            resetDeepDates()
            resetPersonaDates()
            hasFeatures.value = false
            analysisResult.value = null
            llmPhase.value = 'idle'
            qaIndexingHint.value = false
            qaHistory.value = [] // 问答记录按联系人隔离（F1 同源）
            groupSummary.value = null
            loadGroupStats()
            loadPersonaProfile(id)
            loadSessions()
            tryLoadExistingFeatures()
            void tryLoadAffinityScores().then(() => {
                // 切走时 AI 评估仍在后台跑：切回后接续轮询到终态（部分结果已由
                // tryLoadAffinityScores 显示，时序在其后避免被 idle 覆写）
                const saved = loadAnalysisResume()
                if (saved && saved.conversationId === id && saved.phase === 'affinity' && saved.taskId) {
                    resumeLlmEvaluation(saved.taskId, id)
                }
            })
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
            personaProfileMeta.window = null
        }

        function handlePortraitGenerated() {
  // 画像生成完成后刷新画像数据（画廊走 loadPersonaProfile，简卡走 refreshKey）
  profileRefreshKey.value++
  if (typeof loadPersonaProfile === 'function') loadPersonaProfile()
}

async function loadPersonaProfile(conversationId = selectedConversationId.value || undefined) {
            if (!conversationId) {
                resetPersonaProfile()
                return
            }

            const conversation = conversations.value.find((item) => item.id === conversationId)
            const displayName = conversation?.name
            // 画像档案随 TA 画像页签单聊限定：群聊不取画像（展示层与数据层同口径）
            if (!displayName || conversation?.conversation_type === 'group') {
                resetPersonaProfile()
                return
            }

            loadingPersonaProfile.value = true
            const epoch = viewEpoch.value
            try {
                const res = await api.get_contact_profile(displayName, activeAccountWxid.value || undefined)
                if (epoch !== viewEpoch.value) return // 已切换联系人，丢弃过期结果（F1）
                if (res.ok && res.has_profile) {
                    personaProfile.value = res.profile || null
                    personaProfileMeta.createdAt = res.created_at || null
                    personaProfileMeta.expiresAt = res.expires_at || null
                    personaProfileMeta.expired = Boolean(res.expired)
                    personaProfileMeta.estimatedTokens = Number(res.estimated_tokens || 0)
                    personaProfileMeta.window = res.window || null
                } else {
                    resetPersonaProfile()
                    personaProfileMeta.estimatedTokens = Number(res?.estimated_tokens || 0)
                }
            } catch (e) {
                if (epoch === viewEpoch.value) resetPersonaProfile()
            } finally {
                if (epoch === viewEpoch.value) loadingPersonaProfile.value = false
            }
        }

        function onDatesChange(newDates: { from: string; to: string }) {
            dates.from = newDates.from
            dates.to = newDates.to
            loadAnalysis()
        }

        // TimeDeepTab 自 watch dates 重载情绪曲线，无需在此触发分析
        function onDeepDatesChange(newDates: { from: string; to: string }) {
            deepDates.from = newDates.from
            deepDates.to = newDates.to
        }

        function onPersonaDatesChange(newDates: { from: string; to: string }) {
            personaDates.from = newDates.from
            personaDates.to = newDates.to
        }

        const exportDialogVisible = ref(false)
        const exportFormat = ref<'txt' | 'csv' | 'html'>('txt')
        const exporting = ref(false)
        const exportResult = ref<{ path: string; count: number } | null>(null)

        const handleExport = () => {
            if (!selectedConversationId.value) {
                showDialog('请先选择联系人。')
                return
            }
            exportResult.value = null
            exportDialogVisible.value = true
        }

        async function confirmExport() {
            if (exporting.value || !selectedConversationId.value) return
            exporting.value = true
            try {
                await bridgeReady()
                const res = await api.export_chat_records(
                    selectedConversationId.value,
                    exportFormat.value,
                    dates.from || undefined,
                    dates.to || undefined,
                )
                if (res.ok) {
                    exportResult.value = { path: res.file_path, count: res.record_count }
                } else {
                    showDialog(res.error || '导出失败')
                }
            } catch (e: any) {
                showDialog(e?.message || '导出异常')
            } finally {
                exporting.value = false
            }
        }

        function openExportFolder() {
            if (!exportResult.value) return
            // open_external_url 只放行 http/https（目录会被静默拒绝），走专用目录打开
            api.open_export_folder()
                .catch(() => {})
        }

        // ===== 关系体检报告导出（单文件 HTML，写入 chrono_trace_export）=====
        const reportExporting = ref(false)

        async function handleExportReport() {
            if (!selectedConversationId.value || reportExporting.value) return
            reportExporting.value = true
            try {
                await bridgeReady()
                const res = await api.export_affinity_report(selectedConversationId.value)
                if (res?.ok) {
                    showDialog(`体检报告已导出：${res.file_name}`)
                    // 打开导出目录（同聊天记录导出约定）
                    api.open_export_folder()
                        .catch(() => {})
                } else {
                    showDialog(res?.error || '报告导出失败')
                }
            } catch (e: any) {
                showDialog(e?.message || '报告导出异常')
            } finally {
                reportExporting.value = false
            }
        }

        async function tryLoadAffinityScores() {
            if (!selectedConversationId.value) return
            const epoch = viewEpoch.value
            analysisStaleNotice.value = false
            try {
                const scores = await getAffinityScores(selectedConversationId.value)
                if (epoch !== viewEpoch.value) return // 已切换联系人（F1）
                if (scores && scores.cache_version >= 4) {
                    analysisResult.value = scores
                    // LLM 评估仍在跑的 sentinel（缺席文案"AI 关系评估进行中"）
                    // 由切回接续轮询覆写为 running，此处先按终态缺席口径
                    llmPhase.value = scores.llm_relationship ? 'done' : 'absent'
                } else {
                    analysisResult.value = null
                    // 有历史趋势记录却无当前结果 = 结果因版本更新过期（后端
                    // cache_version 门槛拦截），给用户解释而非"从未分析"空态
                    try {
                        const raw: any = await api.get_affinity_scores(selectedConversationId.value)
                        const hist = raw?.ok ? (raw.history || {}) : {}
                        analysisStaleNotice.value = Boolean(
                            !raw?.result && (hist.last_analysis_at || (hist.score_trend || []).length)
                        )
                    } catch { /* 探测失败按未分析处理 */ }
                }
            } catch (e) {
                analysisResult.value = null
            }
        }

        /** 补评 AI 关系评估：复用缓存的本地四维，只重跑 LLM 维——网络恢复后
         * 的重试通道，秒级完成，不动「开始全面分析」主链路 */
        async function handleRetryLlmRelationship() {
            if (!selectedConversationId.value || llmRetryRunning.value) return
            llmRetryRunning.value = true
            llmRetryError.value = ''
            const epoch = viewEpoch.value
            try {
                const taskId = await retryLlmRelationship(selectedConversationId.value)
                for (;;) {
                    await new Promise(r => setTimeout(r, 800))
                    if (epoch !== viewEpoch.value) return // 已切换联系人，弃追
                    const prog = await getAffinityProgress(taskId)
                    if (prog?.status === 'completed') {
                        if (epoch !== viewEpoch.value) return
                        analysisResult.value = prog.result ?? analysisResult.value
                        llmPhase.value = analysisResult.value?.llm_relationship ? 'done' : 'absent'
                        return
                    }
                    if (prog?.status === 'failed' || prog?.status === 'cancelled' || prog?.status === 'not_found') {
                        throw new Error(prog?.error || 'AI 评估失败')
                    }
                }
            } catch (e: any) {
                llmRetryError.value = e?.message || 'AI 评估失败'
            } finally {
                llmRetryRunning.value = false
            }
        }

        async function tryLoadExistingFeatures() {
            if (!selectedConversationId.value) return
            const epoch = viewEpoch.value
            hasFeatures.value = false
            try {
                const [rtData, iniData, wcData, activityData] = await Promise.all([
                    api.get_response_times(selectedConversationId.value),
                    api.get_initiative_stats(selectedConversationId.value),
                    api.get_word_counts(selectedConversationId.value, false),
                    api.get_activity_calendar(selectedConversationId.value)
                ])
                if (epoch !== viewEpoch.value) return // 已切换联系人（F1）
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
            const epoch = viewEpoch.value // 写回前复查（F1）：与 loadAnalysis/loadSessions 同口径
            try {
                const res = await api.get_activity_calendar(selectedConversationId.value, year)
                if (epoch !== viewEpoch.value) return // 已切换联系人，丢弃过期结果（F1）
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
            const epoch = viewEpoch.value
            loading.value = true
            error.value = ''
            try {
                await bridgeReady()
                const res = await api.get_analysis({ conversation_id: selectedConversationId.value, from: dates.from, to: dates.to })
                if (epoch !== viewEpoch.value) return // 已切换联系人（F1）
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
            const epoch = viewEpoch.value
            loadingSessions.value = true
            try {
                await bridgeReady()
                const res = await api.get_sessions(selectedConversationId.value, 50, 0)
                if (epoch !== viewEpoch.value) return // 已切换联系人（F1）
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

        function buildModelStatusMessage(modelStatus: any): string {
            const details = Array.isArray(modelStatus?.missing_details) ? modelStatus.missing_details : []
            if (!details.length) {
                if (modelStatus?.error_detail) return modelStatus.error_detail
                if (modelStatus?.error) return String(modelStatus.error)
                return '无法确认分析模型状态'
            }
            return details
                .map((d: any) => `- ${d.model_name || d.model_key || '未知模型'}: ${d.issue || '模型不可用'}`)
                .join('\n')
        }

        async function ensureAnalysisModelsReady(modelStatus: any): Promise<boolean> {
            if (modelStatus?.ok && modelStatus?.analysis_available) return true

            // 打包版模型内置、此处恒短路放行；仅开发模式缺 ONNX 产物时走到这里。
            // 后端 ONNX 单后端把缺失项全部标 can_auto_download=False（运行时无
            // 导出能力，下载源模型无意义），因此不设自动下载确认弹窗——直接
            // 给出导出脚本指引
            const detailLines = buildModelStatusMessage(modelStatus)
            await showDialog({
                title: '缺少分析模型',
                message:
                    `检测到以下模型不可用:\n${detailLines}\n\n` +
                    '（推理为 ONNX 单后端，安装包内置模型开箱即用；开发环境请运行 ' +
                    'python backend/scripts/ensure_models_for_export.py --with-export ' +
                    '下载源模型并生成 ONNX 产物）'
            })
            return false
        }

        const handleStartGlobalAnalysis = async () => {
            if (!selectedConversationId.value) return
            if (isGlobalAnalyzing.value) return
            if (llmPhase.value === 'running') return // AI 评估在途：防改配置后重跑造成口径错位
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
                const modelsReady = await ensureAnalysisModelsReady(modelStatus)
                if (!modelsReady) {
                    analysisLaunchPending.value = false
                    return
                }
            } catch (e) {
                const modelStatusError = (e as any)?.message || '未知错误'
                await showDialog({
                    title: '无法开始分析',
                    message:
                        `分析模型状态检查失败: ${modelStatusError}\n\n` +
                        '可能的原因:\n' +
                        '- 本地模型文件缺失或损坏\n' +
                        '- Python 依赖未正确安装\n' +
                        '- 应用内部错误'
                })
                analysisLaunchPending.value = false
                return
            }

            if (!hasPersistedAnalysisDeviceMode(analysisDeviceMode.value) && !deviceWizardShown.value) {
                // 一次性设备选择向导：仅在「确有 GPU 加速可决策」时弹窗；
                // 无卡/通道不可用时静默走 auto 语义（后端自动回退 CPU）——
                // 不弹无选择余地的告知框，也不把 cpu 落库覆盖用户的 auto 选择
                try {
                    const gpuStatus = await api.check_gpu_status()
                    if (gpuStatus.ok && gpuStatus.cuda_available) {
                        // DirectML 支持任意 DX12 GPU（N/A 卡、核显均可）；
                        // gpu_name 来自 nvidia-smi，A 卡/核显为空时以通道名兜底
                        const gpuNameText = gpuStatus.gpu_name || 'GPU'
                        const memInfo = gpuStatus.gpu_memory_total_mb
                            ? ` (${(gpuStatus.gpu_memory_total_mb / 1024).toFixed(1)}GB)`
                            : ''
                        const useGpu = await showConfirm({
                            title: 'GPU 加速可用',
                            message:
                                `检测到 GPU 加速可用: ${gpuNameText}${memInfo}\n` +
                                `加速通道: ${gpuStatus.accelerator_label || gpuStatus.cuda_version} | ${gpuStatus.torch_version}\n\n` +
                                '启用 GPU 加速后，分析速度预计可提升 5-10 倍。\n是否启用 GPU 加速？\n\n' +
                                '提示：此选项可随时在「设置 → 分析计算设备」卡片修改。'
                        })
                        const nextMode: AnalysisDeviceMode = useGpu ? 'gpu' : 'cpu'
                        // 答「否」同样落 cpu：用户刚明确表达不用 GPU，若保持
                        // auto 后端仍会自动启用 GPU，违背其意愿；向导一次性，
                        // 之后改选走设置卡片
                        await api.set_settings({ analysis_device_mode: nextMode, analysis_device_wizard_shown: true })
                        applyAnalysisDeviceMode(nextMode)
                        deviceWizardShown.value = true
                    }
                    // 无 GPU / 通道不可用：保持 auto（本次分析后端自动用 CPU），
                    // 设备状态在设置页「分析计算设备」卡片随时可见
                } catch (e) {
                    // 状态探测失败不阻塞分析，按 auto 继续
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

        /** AI 评估阶段跳过：本地四维已显示，取消只终止 LLM 远程调用——
         * 轮询捕获 cancelled 后保留部分结果并给出可重试口径 */
        async function handleSkipLlmEvaluation() {
            if (llmPhase.value !== 'running' || isStopping.value) return
            isStopping.value = true
            try {
                await bridgeReady()
                if (api.cancel_analysis) {
                    await api.cancel_analysis()
                }
            } catch (e) {
                console.error("跳过 AI 评估失败", e)
                isStopping.value = false
            }
        }

        /** 切回仍有 AI 评估在跑的联系人：接续轮询到终态（部分结果已显示，
         * 不再走 isGlobalAnalyzing 全程进度条） */
        function resumeLlmEvaluation(taskId: string, conversationId: number) {
            llmPhase.value = 'running'
            void waitForAffinityTask(taskId, conversationId)
                .catch(() => { /* 终态失败：部分结果保留，重试按钮可补齐 */ })
                .finally(() => {
                    const cur = loadAnalysisResume()
                    if (cur && cur.conversationId === conversationId && cur.taskId === taskId) {
                        clearAnalysisResume()
                    }
                    cancelCurrentAnalysis = null
                    isStopping.value = false
                })
        }

        // 轮询特征提取任务直到终态（供正常发起与跨页面恢复共用）
        function waitForExtractionTask(taskId: string, analysisConversationId: number): Promise<void> {
            return new Promise<void>((resolve, reject) => {
                cancelCurrentAnalysis = () => reject(new Error('分析已取消'))
                activeTimer.value = setInterval(async () => {
                    try {
                        if (selectedConversationId.value !== analysisConversationId) {
                            clearInterval(activeTimer.value) // 已切换联系人，停止过期轮询（F1）
                            resolve()
                            return
                        }
                        const prog = await api.get_extraction_progress(taskId)
                        const d = prog.data || prog
                        if (prog.success || prog.ok) {
                            globalProgressPercent.value = 5 + (d.progress || 0) * 0.45
                            globalProgressStep.value = `[特征分析] ${d.message || d.current_step || '分析中...'}`
                            if (d.status === 'completed') { clearInterval(activeTimer.value); resolve() }
                            else if (d.status === 'failed' || d.status === 'cancelled') { clearInterval(activeTimer.value); reject(new Error(d.error || d.message || '分析已取消')) }
                            else if (d.status === 'not_found') { clearInterval(activeTimer.value); reject(new Error('分析任务已过期')) }
                        }
                    } catch (e) { /* 单次轮询异常继续（与好感度轮询同口径）：瞬时抛错当完成会把半成品特征置为已完成 */ }
                }, 500)
            })
        }

        // 轮询好感度任务直到终态（llm_pending 先行渲染部分结果，完成时落终态并刷新跟随数据）
        function waitForAffinityTask(affinityTaskId: string, analysisConversationId: number): Promise<void> {
            return new Promise<void>((resolve, reject) => {
                let progressiveShown = false // llm_pending 只消费一次，防 500ms 轮询反复触发动画/跟随加载
                cancelCurrentAnalysis = () => reject(new Error('分析已取消'))
                activeTimer.value = setInterval(async () => {
                    try {
                        if (selectedConversationId.value !== analysisConversationId) {
                            clearInterval(activeTimer.value) // 已切换联系人，丢弃过期分析结果（F1）
                            resolve()
                            return
                        }
                        const prog = await getAffinityProgress(affinityTaskId)
                        const action = resolveAffinityPollAction(prog, progressiveShown)
                        if (action.kind === 'continue') {
                            globalProgressPercent.value = 50 + prog.progress_percent * 0.5
                            globalProgressStep.value = `[深度推理] ${prog.current_step || '分析中...'}`
                            return
                        }
                        if (action.kind === 'progressive') {
                            // 本地四维已落库：渐进接管——进度条让位、结果区先显示部分
                            // 结果，跟随数据提前加载，AI 评估状态由 llmPhase 表达
                            progressiveShown = true
                            if (selectedConversationId.value !== analysisConversationId) { resolve(); return }
                            if (prog.result) analysisResult.value = prog.result as AffinityAnalysisResult
                            llmPhase.value = 'running'
                            isGlobalAnalyzing.value = false
                            const followUpTasks = [
                                loadSessions(),
                                loadActivityCalendar(activityCalendar.value.year)
                            ]
                            if (shouldLoadContentAnalysis.value) {
                                followUpTasks.unshift(loadAnalysis())
                            }
                            void Promise.all(followUpTasks)
                            return
                        }
                        clearInterval(activeTimer.value)
                        if (action.kind === 'complete') {
                            // 完成分支含多次 await（进度→分数→跟随加载），每次
                            // 写回前都要复查联系人（F1）：最终轮询在途时切人，
                            // A 的结果会覆盖 B 的关系洞察页
                            if (selectedConversationId.value !== analysisConversationId) { resolve(); return }
                            if (prog.result) {
                                analysisResult.value = prog.result as AffinityAnalysisResult
                            }
                            llmPhase.value = analysisResult.value?.llm_relationship ? 'done' : 'absent'

                            const scores = await getAffinityScores(analysisConversationId)
                            if (selectedConversationId.value !== analysisConversationId) { resolve(); return }
                            if (
                                scores &&
                                (
                                    !analysisResult.value ||
                                    (scores.cache_updated_at || 0) >= (analysisResult.value.cache_updated_at || 0)
                                )
                            ) {
                                analysisResult.value = scores
                            }
                            if (!progressiveShown) {
                                // 未经过 llm_pending（无 LLM 阶段/秒级完成）：跟随加载在此补齐
                                const followUpTasks = [
                                    loadSessions(),
                                    loadActivityCalendar(activityCalendar.value.year)
                                ]
                                if (shouldLoadContentAnalysis.value) {
                                    followUpTasks.unshift(loadAnalysis())
                                }
                                await Promise.all(followUpTasks)
                            }
                            resolve()
                        } else if (action.kind === 'cancelled-partial') {
                            // 取消发生在 AI 评估阶段：保留已显示的本地四维部分结果，
                            // 缺席文案改为可重试口径（缓存里仍是"评估中" sentinel）
                            analysisResult.value = {
                                ...analysisResult.value!,
                                llm_relationship_absent_reason: '已跳过 AI 评估，可点击重试补齐'
                            } as AffinityAnalysisResult
                            llmPhase.value = 'absent'
                            resolve()
                        } else {
                            reject(new Error(action.message))
                        }
                    } catch (e) { }
                }, 500)
            })
        }

        // 第二阶段：发起好感度分析并轮询到终态
        async function runAffinityStage(analysisConversationId: number): Promise<void> {
            globalProgressPercent.value = 50
            globalProgressStep.value = '正在进行深度关系推理...'
            const affinityTaskId = await analyzeAffinity(analysisConversationId, true)
            saveAnalysisResume({ conversationId: analysisConversationId, phase: 'affinity', taskId: affinityTaskId })
            await waitForAffinityTask(affinityTaskId, analysisConversationId)
        }

        async function startGlobalAnalysis() {
            let isCancelled = false
            if (!selectedConversationId.value) return
            const analysisConversationId = selectedConversationId.value // 分析发起时的联系人（F1）
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
                        saveAnalysisResume({ conversationId: analysisConversationId, phase: 'extract', taskId })
                        await waitForExtractionTask(taskId, analysisConversationId)
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
                await runAffinityStage(analysisConversationId)

                if (selectedConversationId.value === analysisConversationId) {
                    globalProgressPercent.value = 100
                    globalProgressStep.value = '全面分析完成'
                    clearAnalysisResume()
                } else {
                    // 用户已切走（软放弃）：后端仍在跑，保留恢复状态供回访接续
                    globalProgressStep.value = '分析正在后台继续，回到该联系人可接续进度'
                }
            } catch (e: any) {
                isCancelled = String(e).includes('已取消')
                clearAnalysisResume() // 终态失败/取消：清除恢复状态（切走导致的软放弃不在此路径）
                if (isCancelled) {
                    globalProgressStep.value = '分析已停止'
                } else {
                    const errorMessage = e?.message || String(e)
                    if (errorMessage.includes('模型') || errorMessage.includes('MODEL_NOT_FOUND')) {
                        // 模型随包内置（开发态由 export 脚本产出），应用内无下载通道
                        globalProgressStep.value = '分析失败: 缺少必要模型（安装版请重新安装完整安装包；开发版运行 ensure_models_for_export.py）'
                    } else if (errorMessage.includes('依赖') || errorMessage.includes('DEPENDENCY_MISSING')) {
                        globalProgressStep.value = '分析失败: 缺少 Python 依赖，请检查安装'
                    } else if (errorMessage.includes('取消')) {
                        globalProgressStep.value = '分析已停止'
                    } else {
                        globalProgressStep.value = `分析失败: ${errorMessage}`
                    }
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
            const epoch = viewEpoch.value // 写回前复查（F1）：与 loadAnalysis/loadSessions 同口径
            try {
                const [rtData, iniData, wcData] = await Promise.all([
                    api.get_response_times(selectedConversationId.value),
                    api.get_initiative_stats(selectedConversationId.value),
                    api.get_word_counts(selectedConversationId.value, false)
                ])
                if (epoch !== viewEpoch.value) return // 已切换联系人，丢弃过期结果（F1）
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
            const palette = chartPalette()
            const hairline = getComputedStyle(document.documentElement).getPropertyValue('--ct-border-color').trim() || '#E9E5DF'
            const axisText = getComputedStyle(document.documentElement).getPropertyValue('--ct-text-tertiary').trim() || '#9B95A5'
            const labelText = getComputedStyle(document.documentElement).getPropertyValue('--ct-text-secondary').trim() || '#5A5566'
            responseTimeChartInstance.setOption({
                backgroundColor: 'transparent',
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
                xAxis: { type: 'category', data: responseTimeStats.value.distributionKeys, axisLabel: { color: axisText, fontSize: 11, interval: 0 } },
                yAxis: { type: 'value', splitLine: { lineStyle: { color: hairline, type: 'dashed' } }, axisLabel: { color: axisText } },
                series: [{ type: 'bar', data: data, itemStyle: { borderRadius: [4, 4, 0, 0], color: palette[0] }, label: { show: true, position: 'top', color: labelText, fontSize: 11 } }]
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
                    textStyle: { color: '#1B1924' },
                    extraCssText: 'background:#FFFFFF;border:1px solid #E9E5DF;box-shadow:0 8px 24px rgba(27,25,36,0.08);',
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
                        color: HEAT_RAMP
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
                        color: 'rgba(90, 75, 196, 0.06)',
                        borderWidth: 2,
                        borderColor: '#FFFFFF'
                    },
                    yearLabel: { show: false },
                    dayLabel: {
                        firstDay: 1,
                        nameMap: ['日', '一', '二', '三', '四', '五', '六'],
                        color: '#9B95A5',
                        margin: 14
                    },
                    monthLabel: {
                        nameMap: 'cn',
                        color: '#5A5566',
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
                            shadowColor: 'rgba(90, 75, 196, 0.35)'
                        }
                    }
                }]
            })
        }

        function renderWordCountChart() {
            if (!wordCountChart.value) return
            if (wordCountChartInstance) wordCountChartInstance.dispose()
            wordCountChartInstance = echarts.init(wordCountChart.value)
            const palette = chartPalette()
            const hairline = getComputedStyle(document.documentElement).getPropertyValue('--ct-border-color').trim() || '#E9E5DF'
            const axisText = getComputedStyle(document.documentElement).getPropertyValue('--ct-text-tertiary').trim() || '#9B95A5'
            const labelText = getComputedStyle(document.documentElement).getPropertyValue('--ct-text-secondary').trim() || '#5A5566'
            wordCountChartInstance.setOption({
                grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
                xAxis: { type: 'category', data: ['我', '对方'], axisLabel: { color: axisText } },
                yAxis: { type: 'value', splitLine: { lineStyle: { color: hairline, type: 'dashed' } }, axisLabel: { color: axisText, formatter: (v: number) => `${(v / 1000).toFixed(0)}k` } },
                series: [{ type: 'bar', data: [{ value: wordCountsStats.value.userCharCount, itemStyle: { color: palette[0] } }, { value: wordCountsStats.value.otherCharCount, itemStyle: { color: palette[1] } }], barWidth: '40%', label: { show: true, position: 'top', color: labelText, formatter: (p: any) => formatNumber(p.value) } }]
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
            if ((newVal === 'content' || newVal === 'deep' || newVal === 'persona') && selectedConversationId.value) {
                loadAnalysis()
            }
            if (newVal === 'deep') {
                deepActivated.value = true
            }
            if (newVal === 'persona') {
                personaActivated.value = true
            }
        })

        // 切到群聊时时光深度/TA 画像/实时助手页签隐藏：若正处于该页签则回退关系洞察（群聊工作台）
        watch(isGroupConversation, (isGroup) => {
            if (isGroup && (currentTab.value === 'deep' || currentTab.value === 'persona' || currentTab.value === 'realtime')) {
                currentTab.value = 'affinity'
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

        const scrollToDetails = (idSuffix: string) => document.getElementById(`detail-${idSuffix}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        const handlePreferenceDisabledClick = () => { showKeywordsDialog.value = true }
        function onWordSelect(word: string) { console.debug('selected', word) }
        function handleResize() { responseTimeChartInstance?.resize(); activityCalendarChartInstance?.resize(); wordCountChartInstance?.resize() }

        // 跨页面恢复：重挂组件时若存在未完成的分析任务，接续轮询而非重新分析
        async function resumeAnalysisFromSaved(saved: AnalysisResumeState) {
            if (!saved?.conversationId || !saved.taskId) { clearAnalysisResume(); return }
            if (!conversations.value.some((c: any) => c.id === saved.conversationId)) {
                clearAnalysisResume(); return
            }
            if (selectedConversationId.value !== saved.conversationId) {
                await onConversationChange(saved.conversationId)
            }
            isGlobalAnalyzing.value = true
            analysisLaunchPending.value = true
            globalProgressStep.value = '检测到未完成的分析，正在接续进度...'
            globalProgressPercent.value = saved.phase === 'extract' ? 10 : 55
            try {
                if (saved.phase === 'extract') {
                    await waitForExtractionTask(saved.taskId, saved.conversationId)
                    hasFeatures.value = true
                    await Promise.all([loadFeatureData(), loadSessions(), loadActivityCalendar()])
                    await runAffinityStage(saved.conversationId)
                } else {
                    await waitForAffinityTask(saved.taskId, saved.conversationId)
                }
                if (selectedConversationId.value === saved.conversationId) {
                    globalProgressPercent.value = 100
                    globalProgressStep.value = '全面分析完成'
                    clearAnalysisResume()
                } else {
                    globalProgressStep.value = '分析正在后台继续，回到该联系人可接续进度'
                }
            } catch {
                clearAnalysisResume()
            } finally {
                analysisLaunchPending.value = false
                cancelCurrentAnalysis = null
                setTimeout(() => { isGlobalAnalyzing.value = false }, 2000)
            }
        }

        onMounted(async () => {
            if (!dates.from || !dates.to) setDefaultDates(30)
            if (!deepDates.from || !deepDates.to) resetDeepDates()
            if (!personaDates.from || !personaDates.to) resetPersonaDates()
            await loadAnalysisDeviceMode()
            await refreshAccountContext()
            await loadConversations()
            const savedResume = loadAnalysisResume()
            if (savedResume) void resumeAnalysisFromSaved(savedResume)
            window.addEventListener('resize', handleResize)
            window.addEventListener('chrono:wechat-account-changed', handleAccountChanged)
            window.addEventListener('chrono:qa-push', handleQaPush)
        })

        onUnmounted(() => {
            window.removeEventListener('resize', handleResize)
            window.removeEventListener('chrono:wechat-account-changed', handleAccountChanged)
            window.removeEventListener('chrono:qa-push', handleQaPush)
            // 在途问答随页面离去取消（对齐切联系人路径；离开后推送无人接、token 白烧）
            if (qaLoading.value && selectedConversationId.value) {
                api.cancel_history_qa(selectedConversationId.value).catch(() => {})
            }
            if (activeTimer.value) { clearInterval(activeTimer.value); activeTimer.value = null } // F2：卸载时停止分析轮询
            responseTimeChartInstance?.dispose(); activityCalendarChartInstance?.dispose(); wordCountChartInstance?.dispose()
        })

        async function handleAccountChanged() {
            resetAccountScopedState()
            await refreshAccountContext()
            await loadConversations()
        }

        return {
            currentTab, conversations, selectedConversationId, dates, loading, loadingSessions, error, analysis, subject, sessions, deepGranularity, deepRefreshKey, deepActivated, deepDates, conversationSpan, onDeepDatesChange, personaActivated, personaDates, onPersonaDatesChange, viewEpoch, handleCancelGroupSummary,
            personaProfile, loadingPersonaProfile, personaProfileMeta, profileRefreshKey, realContactName,
            analysisResult, displayScore, llmRetryRunning, llmRetryError, handleRetryLlmRelationship, showKeywordsDialog, showContextForm, showPortraitDialog, handlePortraitGenerated, isGlobalAnalyzing, isStopping, activeTimer, handleStopAnalysis, llmPhase, handleSkipLlmEvaluation, globalProgressPercent, globalProgressStep, gpuMode,
            hasConversations, hasFeatures, hasCachedAffinityAnalysis, featureStats, responseTimeStats, initiativeStats, wordCountsStats, displayWordRatioLabel, activityCalendar,
            responseTimeChart, activityCalendarChart, wordCountChart, stats, currentContactName, headerAvatarSrc, hasPreferenceKeywords, allDimensions,
            hasContentAnalysis, analysisStaleNotice, circumference, strokeDashoffset, formatNumber, formatTime, getResponseTimeLabel, getMergedResponseTimeLabel, getResponseTimePercent, onConversationChange, onDatesChange, handleExport, handleStartGlobalAnalysis, handleContextSaved, handleKeywordsUpdated, llmEvidenceNotes,
            qaHistory, qaInput, qaLoading, qaChatBox, qaIndexingHint, qaInputEl, qaInputFocused, qaSuggestions, renderQaEntryAnswer, handleAskHistory, handleQaEnter, autoGrowQaInput, handlePickSuggestion, handleStopQa, handleClearQa, handleRetryQa, handleRegenerateQa, handleCiteClick, handleQaScroll, formatQaTime, copiedQaKey, overallCopied, handleCopyQa, handleCopyOverall,
            isGroupConversation, groupStats, groupStatsLoading, groupSummary, groupSummaryLoading, groupSummaryDays, handleGenerateGroupSummary,
            reportExporting, handleExportReport,
            exportDialogVisible, exportFormat, exporting, exportResult, confirmExport, openExportFolder,
            activeAccountWxid,
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
  padding: var(--ct-space-md) var(--ct-space-xl) 0 var(--ct-space-xl);
  gap: var(--ct-space-md);
  height: 100%; /* Will only work if App.vue restricts it, but helps elasticity */
}

/* --- Header Section --- */
.analytics-header {
  flex-shrink: 0; /* Prevent header squishing */
  position: relative;
  z-index: 50;
}

/* 空态：白卡安静铺陈，插画用 tint 圆，不再用渐变光斑 */
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
  border-radius: var(--ct-radius-lg);
  background: var(--ct-bg-card);
  box-shadow: var(--ct-shadow-sm);
  overflow: hidden;
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
  padding: 6px 14px;
  margin-bottom: 18px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
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
}

.empty-orb-main {
  left: 50%;
  top: 18px;
  width: 92px;
  height: 92px;
  transform: translateX(-50%);
  background: var(--ct-color-primary-tint);
}

.empty-orb-small {
  width: 44px;
  height: 44px;
  font-size: 18px;
}

.empty-orb-chat {
  left: 28px;
  top: 72px;
  background: var(--ct-color-success-tint);
}

.empty-orb-star {
  right: 28px;
  top: 34px;
  background: var(--ct-color-warning-tint);
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

.page-empty-state .page-empty-hint {
  max-width: 620px;
  margin-top: var(--ct-space-md);
  color: var(--ct-text-tertiary);
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
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
}

.page-empty-card-accent {
  background: var(--ct-color-primary-tint);
}

.page-empty-card-label {
  display: inline-flex;
  margin-bottom: 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
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
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-sm);
  flex-wrap: wrap;
  gap: var(--ct-space-md);
}

.profile-main {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
}

.profile-avatar-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
}

.profile-avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-bg-sunken);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 2px solid var(--ct-color-primary-tint);
}

.profile-info {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.name-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  margin-bottom: 0;
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
  background: var(--ct-bg-sunken);
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
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-md);
  margin-bottom: var(--ct-space-md);
  box-shadow: var(--ct-shadow-sm);
}

.progress-bar {
  height: 8px;
  background: var(--ct-bg-sunken);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: var(--ct-color-primary);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  text-align: right;
}

.gpu-badge {
  display: inline-block;
  background: var(--ct-color-success-tint);
  color: var(--ct-color-success);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  margin-right: 8px;
  font-weight: 600;
}

.cpu-badge {
  display: inline-block;
  background: var(--ct-bg-sunken);
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
  padding: var(--ct-space-3xl) var(--ct-space-xl);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  border: 1px dashed var(--ct-border-color);
  margin-top: var(--ct-space-md);
  flex: 1;
  min-height: 400px;
  width: 100%;
}

.tab-content .empty-state .empty-icon {
  display: flex;
  align-items: center;
  justify-content: center;
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
  background: var(--ct-bg-sunken);
  padding: var(--ct-space-sm) var(--ct-space-xl);
  border-radius: var(--ct-radius-full);
}

.tab-content .inline-empty-state {
  min-height: 280px;
  margin-top: 0;
  padding: var(--ct-space-2xl) var(--ct-space-xl);
  border-radius: var(--ct-radius-lg);
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

/* 关系洞察页改为纵向文档流（结论带 → 维度卡|风险 → 维度拆解通栏），整页可滚动 */
.tab-content.affinity-tab {
  overflow-y: auto;
}

/* 时光深度五面板纵向长滚（生成画像后超 2800px），同 affinity 模式整页滚；
   该容器也是页签内锚点导航的滚动祖先 */
.tab-content.deep-tab {
  overflow-y: auto;
}

/* TA 画像页整页滚：此前 shell 内部自滚，下方大五/海报被 flex 挤压成矮条 */
.tab-content.persona-tab {
  overflow-y: auto;
}

.tab-content.affinity-tab .affinity-dashboard {
  flex: 0 0 auto;
}

/* 风险预警缺位（旧缓存）时的占位提示 */
.risk-empty-hint {
  margin-top: var(--ct-space-md);
  padding: var(--ct-space-lg);
  border: 1px dashed var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  font-size: 12px;
  color: var(--ct-text-tertiary);
  text-align: center;
}

.col-main, .col-side {
  display: flex;
  flex-direction: column;
}

/* 结论带：高度由内容决定，不再镜像右列被拉伸（原先空白的根源） */
.verdict-band {
  margin-bottom: var(--ct-space-md);
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
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-sm);
}

.trend-badge .up { color: var(--ct-color-success); }
.trend-badge .down { color: var(--ct-color-error); }

/* 分析新鲜度徽标：导入新消息未重分析时提示（warning 深字口径） */
.stale-badge {
  margin-left: 8px;
  font-size: var(--ct-text-xs);
  padding: 2px 8px;
  border-radius: var(--ct-radius-sm);
  color: #8F5B14;
  background: var(--ct-color-warning-tint);
  cursor: help;
}

/* 三段结论：总分（数量）→ 雷达（形状）→ 解读（含义），左到右 */
.score-visual {
  display: grid;
  grid-template-columns: auto minmax(240px, 300px) 1fr;
  gap: var(--ct-space-2xl);
  align-items: center;
}

.ct-score-ring.large {
  width: 150px;
  height: 150px;
  flex-shrink: 0;
}

.ct-score-ring.large .ct-score-num {
  font-size: 48px;
  color: var(--ct-color-primary);
}

.ct-score-ring.large .ct-score-unit {
  font-size: 16px;
  color: var(--ct-text-tertiary);
  margin-left: 4px;
}

.qualitative-analysis {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.qualitative-analysis h3 {
  font-size: var(--ct-text-base);
  margin-bottom: 8px;
  color: var(--ct-text-primary);
}

.qualitative-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-sm);
}

/* 通用小文本操作按钮（复制等） */
.text-action-btn {
  flex-shrink: 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-sunken);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  padding: 2px 10px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.text-action-btn:hover {
  color: var(--ct-color-primary);
  border-color: var(--ct-color-primary);
}

.text-action-btn.copied {
  color: var(--ct-color-success);
  border-color: var(--ct-color-success);
}

.analysis-bubble {
  padding: var(--ct-space-md) var(--ct-space-xl);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
  position: relative;
  line-height: 1.6;
  font-size: var(--ct-text-base);
  color: var(--ct-text-secondary);
  user-select: text;
  -webkit-user-select: text;
}

/* Dimension Cards Grid */
.dimension-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ct-space-md);
  margin-top: var(--ct-space-md);
  flex: 1;
}

/* AI 关系评估：解读段较长，通栏收底 */
.dimension-cards-grid .span-full {
  grid-column: 1 / -1;
}

.dimension-cards-grid > * {
  display: flex;
  flex-direction: column;
}

/* 结论带内的雷达 */
.verdict-radar {
  height: 230px;
}

/* 维度拆解：页尾通栏卡 */
.breakdown-card {
  margin-top: var(--ct-space-md);
}

.breakdowns-container {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
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
    grid-template-columns: 1fr;
    justify-items: center;
  }

  .verdict-radar {
    width: 100%;
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

/* --- Interactive Features Layout --- */
/* tab-content 本身 overflow:hidden，内容超高的 tab 由布局层自滚（同 affinity-tab 口径），
   否则 4 行统计卡之后的内容被静默裁掉 */
.features-layout {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xl);
  margin-top: var(--ct-space-md);
}

.persona-flow {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-lg);
}

/* 滚动已上提到 .tab-content.persona-tab，shell 只做排布不再自滚 */
.persona-tab-shell {
  margin-top: var(--ct-space-md);
  padding-bottom: var(--ct-space-xl);
}

.persona-self-card {
  margin-top: var(--ct-space-lg);
}

/* 实时助手页双方画像速览（监听控制卡下方） */
.realtime-profiles {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ct-space-lg);
  margin-top: var(--ct-space-lg);
}
@media (max-width: 1024px) {
  .realtime-profiles { grid-template-columns: 1fr; }
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

/* 图标点三色槽：青绿/墨紫/珊瑚（数据色板成员，非语义告警） */
.icon-dot.green { background: var(--ct-color-success-tint); border-color: var(--ct-color-success); }
.icon-dot.green .inner-dot { background: var(--ct-color-success); }

.icon-dot.purple { background: var(--ct-color-primary-tint); border-color: var(--ct-color-primary); }
.icon-dot.purple .inner-dot { background: var(--ct-color-primary); }

.icon-dot.orange { background: var(--ct-color-error-tint); border-color: var(--ct-color-error); }
.icon-dot.orange .inner-dot { background: var(--ct-color-error); }

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
  background: var(--ct-bg-sunken);
  border-radius: 999px;
  overflow: hidden;
  position: relative;
}

.h-bar-fill {
  height: 100%;
  background: var(--ct-color-primary);
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
/* 实体色口径与 big5Shared 一致：我=墨紫、对方=琥珀 */
.legend-dot.purple { background: var(--ct-color-primary); }
.legend-dot.green { background: var(--ct-chart-4); }

.initiative-box {
  background: var(--ct-bg-sunken);
  padding: 12px 16px;
  border-radius: var(--ct-radius-md);
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
/* 我=墨紫、对方=琥珀（与 donut/大五实体色一致） */
.v-bar-fill.purple { background: var(--ct-color-primary); }
.v-bar-fill.red { background: var(--ct-chart-4); }

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
  background: var(--ct-bg-sunken);
  padding: 12px 16px;
  border-radius: var(--ct-radius-md);
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
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
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
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
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
  background: var(--ct-border-color);
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
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
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

/* 与图表 HEAT_RAMP（墨紫 5 步顺序色带）同源，图例即所见 */
.calendar-legend-scale i:nth-child(1) { background: #F1EEFA; }
.calendar-legend-scale i:nth-child(2) { background: #D5CFF2; }
.calendar-legend-scale i:nth-child(3) { background: #ABA0E4; }
.calendar-legend-scale i:nth-child(4) { background: #7E6BD6; }
.calendar-legend-scale i:nth-child(5) { background: #5A4BC4; }

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
  border-radius: var(--ct-radius-md);
  border: 1px dashed var(--ct-border-color);
  background: var(--ct-bg-sunken);
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
  background-color: var(--ct-border-color);
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
}

@media (max-width: 768px) {
    .analytics-page {
        padding: var(--ct-space-lg) var(--ct-space-md);
    }

    .page-empty-state {
        min-height: 460px;
        gap: 22px;
    }

    .page-empty-grid {
        grid-template-columns: 1fr;
    }

    .page-empty-illustration {
        transform: scale(0.92);
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
    .features-row-3 {
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

/* LLM 关系评估缺席说明（灰字，不阻断其余维度展示） */
.llm-absent-note {
  font-size: 12px;
  color: var(--ct-text-secondary, #5A5566);
  margin: 4px 0 0;
}

.llm-retry-btn {
  margin-left: 10px;
  vertical-align: middle;
}

/* AI 评估中渐进徽标（状态徽标惯用语：tint 底 + 主色字，info=primary） */
.llm-phase-badge {
  margin-left: 8px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ct-text-xs);
  padding: 2px 8px;
  border-radius: var(--ct-radius-sm);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
}

/* 渐进期间定性注解：总分口径说明（AI 到位后小幅更新） */
.llm-pending-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

/* AI 关系评估占位卡：与 AffinityScoreCard 同位，评估完成后原位替换 */
.llm-pending-card {
  border: 1px dashed var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  justify-content: center;
}
.llm-pending-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ct-text-primary);
}
.llm-pending-card p {
  margin: 0;
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

/* 导出弹窗（白卡解剖：发丝线分区，按钮走 ct-btn 体系） */
.export-dialog {
  width: 420px; max-width: 92vw;
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-lg);
  overflow: hidden;
}
.export-body { padding: 16px 20px; }
.export-formats { display: flex; gap: 8px; }
.export-fmt {
  flex: 1; padding: 12px 8px; border-radius: var(--ct-radius-md); cursor: pointer;
  border: 1px solid var(--ct-border-color); background: var(--ct-bg-card);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  transition: border-color 0.15s, background-color 0.15s;
}
.export-fmt:hover { border-color: var(--ct-border-color-hover); }
.export-fmt.active { border-color: var(--ct-color-primary); background: var(--ct-color-primary-tint); }
.export-fmt-label { font-size: 13px; font-weight: 600; }
.export-fmt-tip { font-size: 10px; color: var(--ct-text-tertiary); }
.export-hint { margin-top: 12px; font-size: 11px; color: var(--ct-text-tertiary); line-height: 1.5; }
.export-success { text-align: center; padding: 12px 0; }
.export-success p { margin: 4px 0; font-size: 14px; }
.export-path { font-size: 11px; color: var(--ct-text-tertiary); word-break: break-all; }
.pd-header { display: flex; align-items: center; gap: 12px; padding: 18px 20px; border-bottom: 1px solid var(--ct-border-color); }
.pd-title { margin: 0; font-size: 17px; font-weight: 600; flex: 1; }
.pd-close { background: none; border: none; cursor: pointer; color: var(--ct-text-secondary); font-size: 16px; padding: 4px 8px; border-radius: var(--ct-radius-sm); }
.pd-close:hover { color: var(--ct-text-primary); background: var(--ct-bg-hover); }
.pd-footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--ct-border-color); }
.sr-only { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }

/* --- 问问微信（历史问答·聊天框） --- */
.qa-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding: var(--ct-space-lg);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-lg);
  min-height: 0; /* 聊天流在 flex 列内收缩，出滚动条而不是撑破页 */
}

.qa-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 标题行：标题左、清空对话右 */
.qa-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-md);
}

.qa-clear-btn {
  flex-shrink: 0;
}

.qa-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ct-text-primary);
}

.qa-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

/* 语义索引懒补在途的轻提示（一次性标志，不轮询进度） */
.qa-indexing-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ct-color-primary, #5A4BC4);
}

/* 聊天流：自带滚动，新消息滚底 */
.qa-chat {
  flex: 1;
  min-height: 280px;
  max-height: 56vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  padding-right: 4px;
}

.qa-empty {
  margin: auto; /* 空态在聊天流内垂直居中 */
  padding: var(--ct-space-2xl);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ct-space-md);
  text-align: center;
  border-radius: var(--ct-radius-md);
}

.qa-empty-text {
  margin: 0;
  font-size: 13px;
  color: var(--ct-text-tertiary);
}

/* 空态建议问题：点击即填入输入框 */
.qa-suggest-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  max-width: 420px;
}

.qa-suggest-chip {
  padding: 5px 12px;
  font-size: 12px;
  color: var(--ct-text-secondary);
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-full);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.qa-suggest-chip:hover {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-subtle);
}

.qa-msg {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.qa-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.qa-row-user {
  justify-content: flex-end;
}

.qa-bubble {
  max-width: 82%;
  padding: 10px 14px;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qa-bubble-user {
  background: var(--ct-color-primary-subtle);
  border-bottom-right-radius: 4px;
}

.qa-bubble-ai {
  background: var(--ct-bg-card);
  border-bottom-left-radius: 4px;
}

.qa-bubble-text {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
  color: var(--ct-text-primary);
}

.qa-a-mark {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--ct-radius-full);
  font-size: 10px;
  font-weight: 600;
  background: var(--ct-color-success-light);
  color: var(--ct-color-success);
}

/* 输入区：胶囊容器（auto-grow 文本域 + 内嵌发送/停止二合一），焦点
   光圈落在容器上（textarea 自身无边框） */
.qa-input-row {
  display: flex;
  align-items: flex-end;
}

.qa-input-box {
  flex: 1;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 6px 6px 6px 14px;
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.qa-input-box.focused {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 3px var(--ct-color-primary-tint);
}

.qa-input {
  flex: 1;
  padding: 6px 0;
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
  border: none;
  background: transparent;
  color: var(--ct-text-primary);
  outline: none;
  resize: none; /* 高度由 autoGrowQaInput 管（1~5 行） */
  max-height: 132px;
  overflow-y: auto;
}

.qa-input::placeholder {
  color: var(--ct-text-tertiary);
}

/* 发送/停止二合一：发送态 primary 上箭头，生成中同位变停止方块 */
.qa-send-btn {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--ct-radius-full);
  background: var(--ct-color-primary);
  color: var(--ct-text-inverse); /* primary 底反白字（令牌而非裸值） */
  cursor: pointer;
  transition: background-color 0.15s ease, opacity 0.15s ease;
}

.qa-send-btn:not(:disabled):hover {
  background: var(--ct-color-primary-hover);
}

.qa-send-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.qa-send-icon {
  width: 16px;
  height: 16px;
}

/* 回答操作条：复制 / 重新生成 */
.qa-actions {
  display: flex;
  gap: 6px;
}

.qa-copy-btn,
.qa-actions .text-action-btn {
  align-self: flex-start;
}

/* 回答正文（受限 Markdown 渲染：段落/列表/加粗/引用上标） */
.qa-md {
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
  color: var(--ct-text-primary);
}

.qa-md p {
  margin: 0 0 6px;
}

.qa-md p:last-child {
  margin-bottom: 0;
}

.qa-md ul,
.qa-md ol {
  margin: 0 0 6px;
  padding-left: 20px;
}

.qa-md li {
  margin: 2px 0;
}

/* 引用上标（[n] 渲染产物）：可点，展开本气泡引用溯源 */
.qa-cite-mark {
  font-size: 10px;
  margin: 0 1px;
  padding: 0 3px;
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-subtle);
  border-radius: var(--ct-radius-sm);
  cursor: pointer;
  user-select: none;
}

/* 流式光标：增量在途时文尾呼吸竖条 */
.qa-stream-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--ct-color-primary);
  animation: qa-cursor-blink 1s step-end infinite;
}

@keyframes qa-cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* 停止定格徽标（非错误：沉底中性徽标） */
.qa-stopped-badge {
  align-self: flex-start;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-full);
}

/* 内联错误条：error tint 底 + 重试，不打断（不弹窗） */
.qa-error {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  padding: 8px 10px;
  background: var(--ct-color-error-tint);
  border-radius: var(--ct-radius-md);
}

.qa-error-text {
  flex: 1;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-color-error);
  word-break: break-word;
}

.qa-citations-fold {
  border-top: 1px dashed var(--ct-border-color);
  padding-top: 8px;
}

.qa-citations-title {
  font-size: 11px;
  color: var(--ct-text-tertiary);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}

.qa-citation-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 11px;
  line-height: 1.6;
  padding-top: 4px;
}

.qa-citation-idx {
  flex-shrink: 0;
  font-family: var(--ct-font-mono);
  color: var(--ct-color-primary);
}

.qa-citation-meta {
  flex-shrink: 0;
  color: var(--ct-text-tertiary);
}

.qa-citation-text {
  color: var(--ct-text-secondary);
  font-style: italic;
  word-break: break-word;
  user-select: text;
  -webkit-user-select: text;
}

/* 参考记忆行：kind 徽标 + 陈述 + 就地纠错按钮（与记忆管理弹窗同接口） */
.qa-memory-kind {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: var(--ct-radius-full);
  font-size: 10px;
  color: var(--ct-text-tertiary);
  background: var(--ct-bg-hover);
}

.qa-memory-kind.fact {
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
}

.qa-memory-btn {
  flex-shrink: 0;
  font-size: 11px;
}

.qa-memory-btn:not(:disabled):hover {
  color: var(--ct-color-error);
}

.qa-memory-done {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--ct-text-tertiary);
}

/* 加载占位：打字点 + 进度文案（气泡内独立 div，display:flex 自带） */
.qa-typing {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.qa-typing-dots {
  display: inline-flex;
  gap: 3px;
  flex-shrink: 0;
}

.qa-typing-dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ct-text-tertiary);
  animation: qa-typing-blink 1.2s infinite ease-in-out;
}

.qa-typing-dots i:nth-child(2) { animation-delay: 0.2s; }
.qa-typing-dots i:nth-child(3) { animation-delay: 0.4s; }

.qa-typing-hint {
  font-size: 12px;
  color: var(--ct-text-tertiary);
}

@keyframes qa-typing-blink {
  0%, 60%, 100% { opacity: 0.25; }
  30% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .qa-typing-dots i { animation: none; opacity: 0.6; }
  .qa-stream-cursor { animation: none; opacity: 0.7; }
}

/* --- 群聊工作台 --- */
.group-workbench {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--ct-space-md);
  align-items: start;
}

.group-stats-card,
.group-summary-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group-overview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-lg);
  font-size: 12px;
  color: var(--ct-text-secondary);
}

.group-overview strong {
  color: var(--ct-text-primary);
  font-family: var(--ct-font-mono);
}

.group-member-table {
  display: flex;
  flex-direction: column;
  font-size: 12px;
}

.group-member-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) 70px minmax(0, 2fr) 70px;
  gap: 8px;
  align-items: center;
  padding: 5px 6px;
  border-bottom: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
}

.group-member-row:last-child {
  border-bottom: none;
}

.group-member-head {
  color: var(--ct-text-tertiary);
  font-size: 11px;
  font-weight: 500;
}

.group-member-row.me .gm-name {
  color: var(--ct-color-primary);
  font-weight: 600;
}

.gm-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gm-count,
.gm-chars {
  text-align: right;
  font-family: var(--ct-font-mono);
}

.gm-share {
  display: flex;
  align-items: center;
  gap: 6px;
}

.gm-share-bar {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: var(--ct-bg-sunken);
  overflow: hidden;
}

.gm-share-bar i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--ct-color-primary);
}

.gm-share em {
  font-style: normal;
  font-size: 11px;
  font-family: var(--ct-font-mono);
  color: var(--ct-text-tertiary);
  min-width: 44px;
  text-align: right;
}

.group-top-words {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.gtw-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--ct-text-tertiary);
}

.gtw-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
}

.group-note,
.group-empty,
.group-summary-hint {
  margin: 0;
  font-size: 11px;
  color: var(--ct-text-tertiary);
}

.group-summary-controls {
  display: flex;
  gap: 10px;
  align-items: center;
}

.group-days-select {
  padding: 7px 10px;
  padding-right: 28px;
  font-size: 12px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background-color: var(--ct-bg-card);
  color: var(--ct-text-primary);
  outline: none;
}

.group-summary-body {
  padding: var(--ct-space-md);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
}

.group-summary-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--ct-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.group-summary-degraded {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-color-warning);
}
</style>
