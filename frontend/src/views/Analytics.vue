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
              <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId"
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
      <p class="page-empty-hint">先在<button type="button" style="color: var(--ct-color-primary); text-decoration: underline; background: none; border: none; padding: 0; cursor: pointer;" @click="openSettingsTab('account')">设置 · 数据</button>中导入微信数据，完成后这里会自动显示联系人、分析入口和时间线内容。</p>
    </div>

    <div class="page-empty-grid">
      <div class="page-empty-card">
        <span class="page-empty-card-label">下一步</span>
        <strong>去<button type="button" style="color: var(--ct-color-primary); text-decoration: underline; background: none; border: none; padding: 0; cursor: pointer;" @click="openSettingsTab('account')">设置 · 数据</button>导入聊天数据</strong>
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
      <!-- 时光深度/内容时间线已迁独立时光页（批2）；TA 画像三件已迁画像页镜像双栏（批6） -->
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

  <!-- TAB: History QA (问问微信·聊天框：流式打字机 + 引用溯源 + 底部输入 + 滚底) -->
  <!-- TA 画像三件（画像档案/大五/海报）已迁独立画像页镜像双栏（重设计批6） -->

  <!-- Dialogs -->
  <PreferenceKeywordsDialog v-if="selectedConversationId" v-model="showKeywordsDialog"
    :conversation-id="selectedConversationId" @updated="handleKeywordsUpdated" />
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
import { openSettingsTab } from '@/utils/settingsBus'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { bridgeReady, api, type AnalysisDeviceMode } from '@/api/bridge'
import { analyzeAffinity, getAffinityScores, getAffinityProgress, getRelationshipContext, retryLlmRelationship, type AffinityAnalysisResult } from '@/api/affinity'
import { resolveAffinityPollAction } from '@/utils/affinityPoll'
import { getScoreColor, HEAT_RAMP, chartPalette } from '@/components/charts/chartTheme'

import FiltersBar from '@/components/analytics/FiltersBar.vue'
import { sharedContactId as selectedConversationId } from '@/utils/contactScope'

import AffinityScoreCard from '@/components/affinity/AffinityScoreCard.vue'
import RiskSignalCard from '@/components/affinity/RiskSignalCard.vue'
import { copyText } from '@/utils/clipboard'
import DimensionRadar from '@/components/affinity/DimensionRadar.vue'
import SubScoreBreakdown from '@/components/affinity/SubScoreBreakdown.vue'
import PreferenceKeywordsDialog from '@/components/affinity/PreferenceKeywordsDialog.vue'
import RelationshipContextForm from '@/components/affinity/RelationshipContextForm.vue'
import CtCard from '@/components/base/CtCard.vue'
import CtButton from '@/components/base/CtButton.vue'
import { showDialog, showConfirm } from '@/utils/dialog'
import { safeGetItem, safeRemoveItem, safeSetItem } from '@/utils/safeStorage'
import { toLocalDateKey } from '@/utils/datetime'
import CtAvatar from '@/components/base/CtAvatar.vue'
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
        FiltersBar,
        AffinityScoreCard, DimensionRadar, SubScoreBreakdown, RiskSignalCard, PreferenceKeywordsDialog, RelationshipContextForm, CtCard, CtButton, CtAvatar,
        FolderArchive, MessageSquare, Sparkles, BarChart3, TrendingUp, Loader2, Lightbulb
    },
    setup() {
        const currentTab = ref('affinity')
        const activeAccountWxid = ref('')

        // Core State
        const conversations = ref<Conversation[]>([])

        const dates = reactive({ from: '', to: '' })
        const loadingSessions = ref(false)
        const sessions = ref<Session[]>([])
        const responseTimeChart = ref<HTMLDivElement | null>(null)
        const activityCalendarChart = ref<HTMLDivElement | null>(null)
        const wordCountChart = ref<HTMLDivElement | null>(null)
        let responseTimeChartInstance: echarts.ECharts | null = null
        let activityCalendarChartInstance: echarts.ECharts | null = null
        let wordCountChartInstance: echarts.ECharts | null = null

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

        const hasConversations = computed(() => conversations.value.length > 0)
        const currentConversation = computed(() => {
            if (!selectedConversationId.value) return undefined
            return conversations.value.find(c => c.id === selectedConversationId.value)
        })

        const currentContactName = computed(() => {
            return currentConversation.value?.name || '选择联系人'
        })
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
        const headerAvatarSrc = computed(() => currentConversation.value?.avatar || '')

        const hasPreferenceKeywords = computed(() => {
            const preference = analysisResult.value?.preference_compatibility
            if (!preference) return false
            return (preference.bonus_scores?.preference_bonus ?? 0) > 0
        })
        const hasCachedAffinityAnalysis = computed(() => Boolean(analysisResult.value))

        // ===== 文本复制（定性分析，带瞬时反馈；qa 专属复制已随智囊页迁出）=====
        const overallCopied = ref(false)
        let copyFeedbackTimer: ReturnType<typeof setTimeout> | null = null

        function flashCopied(key: 'overall' | string) {
            if (key === 'overall') {
                overallCopied.value = true
                if (copyFeedbackTimer) clearTimeout(copyFeedbackTimer)
                copyFeedbackTimer = setTimeout(() => { overallCopied.value = false }, 2000)
            }
        }

        function handleCopyOverall() {
            const text = analysisResult.value?.overall_interpretation || ''
            if (copyText(text)) flashCopied('overall')
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
                    } else {
                        // 跨页共享选人：带着已有选中进入本页，驱动首次加载
                        onConversationChange(selectedConversationId.value)
                    }
                }
            } catch (e: any) { console.error('加载联系人失败', e) }
        }

        function resetAccountScopedState() {
            selectedConversationId.value = null
            conversations.value = []
            analysisResult.value = null
            llmPhase.value = 'idle'
            hasFeatures.value = false
            sessions.value = []
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
            if (groupSummaryLoading.value && selectedConversationId.value) {
                api.cancel_group_summary(selectedConversationId.value).catch(() => {})
            }
            selectedConversationId.value = id
            setDefaultDates(30, getConversationAnchorDate(id))
            hasFeatures.value = false
            analysisResult.value = null
            llmPhase.value = 'idle'
            groupSummary.value = null
            loadGroupStats()
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
            const epoch = viewEpoch.value // 写回前复查（F1）：与 loadSessions 同口径
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
                            void Promise.all([
                                loadSessions(),
                                loadActivityCalendar(activityCalendar.value.year)
                            ])
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
                                await Promise.all([
                                    loadSessions(),
                                    loadActivityCalendar(activityCalendar.value.year)
                                ])
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
            const epoch = viewEpoch.value // 写回前复查（F1）：与 loadSessions 同口径
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
            await loadAnalysisDeviceMode()
            await refreshAccountContext()
            await loadConversations()
            const savedResume = loadAnalysisResume()
            if (savedResume) void resumeAnalysisFromSaved(savedResume)
            window.addEventListener('resize', handleResize)
            window.addEventListener('chrono:wechat-account-changed', handleAccountChanged)
        })

        onUnmounted(() => {
            window.removeEventListener('resize', handleResize)
            window.removeEventListener('chrono:wechat-account-changed', handleAccountChanged)
            if (activeTimer.value) { clearInterval(activeTimer.value); activeTimer.value = null } // F2：卸载时停止分析轮询
            responseTimeChartInstance?.dispose(); activityCalendarChartInstance?.dispose(); wordCountChartInstance?.dispose()
        })

        async function handleAccountChanged() {
            resetAccountScopedState()
            await refreshAccountContext()
            await loadConversations()
        }

        return {
            currentTab, conversations, selectedConversationId, dates, loadingSessions, sessions, viewEpoch, handleCancelGroupSummary,
            analysisResult, displayScore, llmRetryRunning, llmRetryError, handleRetryLlmRelationship, showKeywordsDialog, showContextForm, isGlobalAnalyzing, isStopping, activeTimer, handleStopAnalysis, llmPhase, handleSkipLlmEvaluation, globalProgressPercent, globalProgressStep, gpuMode,
            hasConversations, hasFeatures, hasCachedAffinityAnalysis, featureStats, responseTimeStats, initiativeStats, wordCountsStats, displayWordRatioLabel, activityCalendar,
            responseTimeChart, activityCalendarChart, wordCountChart, currentContactName, headerAvatarSrc, hasPreferenceKeywords, allDimensions,
            analysisStaleNotice, circumference, strokeDashoffset, formatNumber, formatTime, getResponseTimeLabel, getMergedResponseTimeLabel, getResponseTimePercent, onConversationChange, handleExport, handleStartGlobalAnalysis, handleContextSaved, handleKeywordsUpdated, llmEvidenceNotes,
            overallCopied, handleCopyOverall,
            isGroupConversation, groupStats, groupStatsLoading, groupSummary, groupSummaryLoading, groupSummaryDays, handleGenerateGroupSummary,
            reportExporting, handleExportReport,
            exportDialogVisible, exportFormat, exporting, exportResult, confirmExport, openExportFolder,
            activeAccountWxid,
            getScoreColor, scrollToDetails, handlePreferenceDisabledClick, loadSessions, handleActivityYearChange
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
