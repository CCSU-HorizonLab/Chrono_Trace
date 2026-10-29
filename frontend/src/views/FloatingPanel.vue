<template>
  <div class="fp-layout">
    <!-- 1. Header (Fixed) -->
    <header class="fp-site-header">
      <div class="fp-header-drag-zone" @mousedown="startFloatingDrag">
        <div class="fp-brand">
          <span class="fp-status-dot" :class="{ active: realtimeState.isMonitoring }"></span>
          <span class="fp-brand-name">Chrono Trace</span>
          <span v-if="realtimeState.isMonitoring" class="fp-brand-pulse-badge">实时</span>
        </div>
        <button class="fp-btn-back" @click="exitFloating" title="退出悬浮模式并结束监听，返回应用主界面">
          <Maximize2 :size="12" />
          <span>返回主界面</span>
        </button>
      </div>

      <div class="fp-contact-bar" @click="profileExpanded = !profileExpanded" title="点击展开/收起人物画像详情">
        <CtAvatar
          class="fp-avatar"
          :src="contactAvatar"
          :name="contactDisplayName"
          :size="32"
          radius="8px"
        />
        <div class="fp-contact-info">
          <div class="fp-contact-name-row">
            <span class="fp-contact-name" :title="contactDisplayName">{{ contactDisplayName }}</span>
            <span class="fp-monitor-tag" :class="{ active: realtimeState.isMonitoring }">
              {{ realtimeState.isMonitoring ? '监听中' : '未就绪' }}
            </span>
          </div>
          <div class="fp-contact-sub-row">
            <div class="fp-contact-tags" v-if="profile.personality_tags?.length">
              <span v-for="t in profile.personality_tags.slice(0, 2)" :key="t" class="fp-tag">{{ t }}</span>
              <span v-if="profile.personality_tags.length > 2" class="fp-tag more">+{{ profile.personality_tags.length - 2 }}</span>
            </div>
            <span v-else class="fp-contact-empty-hint">暂无画像特征</span>
          </div>
        </div>
        <button class="fp-btn-icon profile-toggle" :class="{ 'is-open': profileExpanded }">
           <ChevronDown :size="14" />
        </button>
      </div>

      <!-- Absolute Profile Dropdown -->
      <div class="fp-profile-dropdown" v-show="profileExpanded">
        <div class="fp-contact-tags all-tags" v-if="profile.personality_tags?.length">
          <span v-for="t in profile.personality_tags" :key="t" class="fp-tag">{{ t }}</span>
        </div>
        <div class="fp-profile-attrs">
          <div v-if="profile.chat_style" class="fp-attr">
            <span class="fp-attr-lbl">画像</span><span class="fp-attr-val">{{ profile.chat_style }}</span>
          </div>
          <div v-if="profile.interests?.length" class="fp-attr">
            <span class="fp-attr-lbl">兴趣</span><span class="fp-attr-val">{{ profile.interests.join('、') }}</span>
          </div>
          <div v-if="profile.communication_tips" class="fp-attr">
            <span class="fp-attr-lbl">提示</span><span class="fp-attr-val">{{ profile.communication_tips }}</span>
          </div>
          <div v-if="profile.relationship_note" class="fp-attr">
            <span class="fp-attr-lbl">关系</span><span class="fp-attr-val">{{ profile.relationship_note }}</span>
          </div>
          <div v-if="!profile.chat_style && !profileLoading" class="fp-profile-empty">
            <span class="fp-txt-sub">暂无画像特征</span>
            <button class="fp-btn-sm" @click="showProfileDialog = true">扫描画像</button>
          </div>
        </div>
      </div>
    </header>

    <!-- App State Banners -->
    <div class="fp-banners">
      <div v-if="connectionLost" class="fp-banner error">
        <span>连接断开，等待重连…</span>
        <button class="fp-btn-sm warning" @click="retryConnection">重试</button>
      </div>
      <div v-if="chatError && !connectionLost" class="fp-banner error">
        <span>{{ chatError }}</span>
        <button class="fp-btn-sm warning" @click="exitFloating">重新开始</button>
      </div>
    </div>

        <!-- Workbench Container -->
    <div class="fp-workbench-container">
      
      <!-- LEFT/MAIN COLUMN -->
      <main class="fp-main-column">
        <!-- Compact Context & Insights Ribbon (Micro status bar) -->
        <div class="fp-insights-strip">
          <div class="fp-insight-primary" @click="toggleInspector('emotion')" title="点击展开情绪走势明细">
            <span class="fp-trend-badge" :class="emotionSummary?.trend || 'neutral'">
              {{ emotionSummary?.trend === 'positive' ? '正面向上' : emotionSummary?.trend === 'negative' ? '负面向下' : '稳定平缓' }}
            </span>
            <span class="fp-insight-text">{{ emotionSummary?.insight || '正在分析情绪数据...' }}</span>
          </div>
          <div class="fp-insight-actions">
            <button
              class="fp-ribbon-btn fp-rag-btn"
              :class="{ 'has-rag': !!latestRagContext, 'active': inspectorOpen && inspectorTab === 'context' }"
              @click.stop="openLatestRagDetail"
              title="查看与管理 AI 建议的参考依据及长期记忆"
            >
              <Brain :size="12" />
              <span>依据与记忆</span>
            </button>
            <button
              class="fp-ribbon-btn fp-chart-btn"
              :class="{ 'active': inspectorOpen && inspectorTab === 'emotion' }"
              @click.stop="toggleInspector('emotion')"
              title="展开/收起情绪走势图"
            >
              <Activity :size="12" />
            </button>
          </div>
        </div>

        <!-- 4. Suggestion & Chat Area (Main scroll view) -->
        <div class="fp-main-stack">
          <div class="fp-scroll-area" ref="suggestionsRef">
            <div v-if="lastThread" class="fp-thread-banner compress" @click="loadLastThread">
              <div class="fp-thread-info">
                <span class="fp-thread-label">继续指导: {{ lastThread.summary }}</span>
              </div>
              <button class="fp-btn-icon tiny" @click.stop="lastThread = null"><X :size="12" /></button>
            </div>

            <div v-if="!allSuggestions.length && !loading" class="fp-empty-slate">
              <div class="fp-empty-card">
                <div class="fp-empty-icon-wrap">
                  <MessageSquare :size="24" class="fp-empty-svg" />
                </div>
                <div class="fp-empty-title">
                  <span v-if="realtimeState.isMonitoring && realtimeState.messageCount > 0">正在分析微信对话…</span>
                  <span v-else-if="realtimeState.isMonitoring && !chatReady">正在定位聊天记录…</span>
                  <span v-else-if="realtimeState.isMonitoring">监听已就绪，等待新消息</span>
                  <span v-else>等待启动监听</span>
                </div>
                <div class="fp-empty-desc">
                  <template v-if="realtimeState.isMonitoring && realtimeState.messageCount > 0">
                    已捕获 {{ realtimeState.messageCount }} 条消息，AI 正在生成策略建议（深度思考模型约需 30-60 秒）…
                  </template>
                  <template v-else-if="realtimeState.isMonitoring && !chatReady">
                    正在查找「{{ contactDisplayName }}」的聊天数据，完成后自动开始监听…
                  </template>
                  <template v-else-if="realtimeState.isMonitoring">
                    在微信中与「{{ contactDisplayName }}」展开对话，AI 军师将在此实时提供高情商回复与策略指导。
                  </template>
                  <template v-else>
                    请确保微信已登录并保持后台运行，系统将自动绑定并开启实时军师建议。
                  </template>
                </div>
                <div class="fp-empty-tip">
                  <Sparkles :size="12" />
                  <span>可在下方直接向 AI 军师提问或手动生成</span>
                </div>
              </div>
            </div>

        <div class="fp-sug-list">
          <template v-for="s in allSuggestions" :key="s.id || s._tempId">
            <!-- 1. AI 策略建议卡片 -->
            <div
              v-if="s._type === 'suggestion'"
              :data-sid="s.id || 'manual'"
              class="fp-card"
              :class="[s.severity || 'medium']"
            >
              <div class="fp-card-hd" @click="toggleSuggestion(s)">
                <span class="fp-card-icon"><component :is="getTriggerIconComponent(s.trigger_type)" :size="13" /></span>
                <span class="fp-card-title">{{ s.summary }}</span>
                <span class="fp-card-time">{{ s.created_at ? formatMsgTime(s.created_at) : '刚刚' }}</span>
                <button class="fp-btn-icon">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ 'rotate-180': isSuggestionExpanded(s) }"><path d="M6 9l6 6 6-6"/></svg>
                </button>
              </div>
              <div v-show="isSuggestionExpanded(s)" class="fp-card-bd">
                <details v-if="s.thought_process" class="fp-cot">
                  <summary>思考过程</summary>
                  <div class="fp-cot-txt">{{ s.thought_process }}</div>
                </details>
                <div v-for="(sp, i) in s.speeches" :key="i" class="fp-speech-item">
                  <span class="fp-speech-text">{{ sp }}</span>
                  <!-- 复制反馈键含 id 兜底：手动建议无 s.id，裸用会撞 "undefined-0" -->
                  <button
                    class="fp-btn-copy"
                    :class="{ copied: copiedSpeechKey === `${s.id || s._tempId}-${i}` }"
                    @click="handleCopySpeech(sp, s, i)"
                  >
                    {{ copiedSpeechKey === `${s.id || s._tempId}-${i}` ? '已复制' : '复制' }}
                  </button>
                </div>
                <div v-if="getRagBadge(s.rag_context)" class="fp-rag-row">
                  <span
                    class="fp-rag-badge"
                    :class="getRagBadge(s.rag_context)?.state"
                    :style="canOpenRagDetail(s.rag_context) ? 'cursor:pointer' : ''"
                    :title="canOpenRagDetail(s.rag_context) ? '点击查看参考依据' : ''"
                    @click.stop="openRagDetail(s.rag_context)"
                  >
                    {{ getRagBadge(s.rag_context)?.label }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 2. 微信抓取实时消息行（含真实头像 + 仿微信引用消息块） -->
            <div
              v-else-if="s._type === 'live_msg'"
              class="fp-msg-row"
              :class="s.sender_attr === 'self' ? 'right' : 'left'"
            >
              <div class="fp-msg-avatar" :class="s.sender_attr === 'self' ? 'self' : 'contact'">
                <img
                  v-if="getBubbleAvatar(s.sender_attr === 'self') && !avatarLoadErrors[getBubbleAvatar(s.sender_attr === 'self')]"
                  :src="getBubbleAvatar(s.sender_attr === 'self')"
                  class="fp-msg-avatar-img"
                  referrerpolicy="no-referrer"
                  :alt="s.sender_attr === 'self' ? '我' : (contactDisplayName || '对方')"
                  @error="avatarLoadErrors[getBubbleAvatar(s.sender_attr === 'self')] = true"
                />
                <svg v-else class="fp-msg-avatar-svg" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect width="36" height="36" rx="6" :fill="s.sender_attr === 'self' ? '#2FA39A' : '#dfdfdf'" />
                  <circle cx="18" cy="13" r="5.5" fill="#ffffff" />
                  <path d="M7 29C7 24.0294 11.0294 20 16 20H20C24.9706 20 29 24.0294 29 29V31C29 32.1046 28.1046 33 27 33H9C7.89543 33 7 32.1046 7 31V29Z" fill="#ffffff" />
                </svg>
              </div>

              <div class="fp-bubble" :class="s.sender_attr === 'self' ? 'wechat-self' : 'wechat-other'">
                <div class="fp-bubble-meta">
                  <span class="fp-bubble-badge" :class="s.sender_attr === 'self' ? 'wechat-self' : 'wechat-other'">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <span>{{ s.sender_attr === 'self' ? '微信 · 我' : `微信 · ${contactDisplayName}` }}</span>
                  </span>
                  <span class="fp-bubble-time">{{ formatMsgTime(s.created_at) }}</span>
                </div>
                <template v-if="parseWechatQuoteMessage(s.content).isQuote">
                  <div class="fp-bubble-txt">{{ parseWechatQuoteMessage(s.content).replyText }}</div>
                  <div
                    class="fp-wechat-quote"
                    :class="{ 'is-expanded': isQuoteExpanded(String(s.id || s.created_at || s.content)) }"
                    title="点击展开或收起引用全文"
                    @click.stop="toggleQuoteExpand(String(s.id || s.created_at || s.content))"
                  >
                    <span class="fp-wechat-quote-bar"></span>
                    <div class="fp-wechat-quote-body">
                      <div class="fp-wechat-quote-text">
                        <span class="fp-wechat-quote-author">{{ parseWechatQuoteMessage(s.content).quoteAuthor }}：</span>
                        <span>{{ parseWechatQuoteMessage(s.content).quoteText }}</span>
                      </div>
                      <span v-if="parseWechatQuoteMessage(s.content).quoteText.length > 42" class="fp-wechat-quote-toggle">
                        {{ isQuoteExpanded(String(s.id || s.created_at || s.content)) ? '收起' : '展开全文' }}
                      </span>
                    </div>
                  </div>
                </template>
                <div v-else class="fp-bubble-txt">{{ s.content }}</div>
              </div>
            </div>

            <!-- 3. 用户与 AI 军师对话行（含用户头像 / AI 专属图标） -->
            <div
              v-else-if="s._type === 'chat'"
              class="fp-msg-row"
              :class="s.role === 'user' ? 'right' : 'left'"
            >
              <div class="fp-msg-avatar" :class="s.role === 'user' ? 'ai-user-av' : 'ai-bot-av'">
                <template v-if="s.role === 'user'">
                  <img
                    v-if="userAvatar && !avatarLoadErrors[userAvatar]"
                    :src="userAvatar"
                    class="fp-msg-avatar-img"
                    referrerpolicy="no-referrer"
                    alt="我"
                    @error="avatarLoadErrors[userAvatar] = true"
                  />
                  <svg v-else class="fp-msg-avatar-svg" viewBox="0 0 36 36" fill="none">
                    <rect width="36" height="36" rx="6" fill="#5A4BC4" />
                    <circle cx="18" cy="13" r="5.5" fill="#ffffff" />
                    <path d="M7 29C7 24.0294 11.0294 20 16 20H20C24.9706 20 29 24.0294 29 29V31C29 32.1046 28.1046 33 27 33H9C7.89543 33 7 32.1046 7 31V29Z" fill="#ffffff" />
                  </svg>
                </template>
                <svg v-else class="fp-msg-avatar-svg" viewBox="0 0 36 36" fill="none">
                  <rect width="36" height="36" rx="6" fill="#EEEBFA" />
                  <rect x="9" y="13" width="18" height="12" rx="3" stroke="#5A4BC4" stroke-width="2.2" fill="#ffffff" />
                  <circle cx="18" cy="8" r="2" fill="#5A4BC4" />
                  <path d="M18 10v3" stroke="#5A4BC4" stroke-width="2.2" stroke-linecap="round" />
                  <circle cx="14.5" cy="19" r="1.5" fill="#5A4BC4" />
                  <circle cx="21.5" cy="19" r="1.5" fill="#5A4BC4" />
                </svg>
              </div>

              <div class="fp-bubble" :class="s.role === 'user' ? 'ai-user' : 'ai-assistant'">
                <div class="fp-bubble-meta">
                  <span class="fp-bubble-badge" :class="s.role === 'user' ? 'ai-user' : 'ai-assistant'">
                    <svg v-if="s.role === 'user'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="12" cy="12" r="10"></circle>
                      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                      <line x1="12" y1="17" x2="12.01" y2="17"></line>
                    </svg>
                    <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="3" y="11" width="18" height="10" rx="2"></rect>
                      <circle cx="12" cy="5" r="2"></circle>
                      <path d="M12 7v4"></path>
                    </svg>
                    <span>{{ s.role === 'user' ? '向 AI 提问' : 'AI 助手' }}</span>
                  </span>
                  <span class="fp-bubble-time">{{ formatMsgTime(s.created_at) }}</span>
                </div>
                <div class="fp-bubble-txt">{{ s.content }}</div>
                <div v-if="getRagBadge(s.rag_context)" class="fp-rag-row">
                  <span
                    class="fp-rag-badge"
                    :class="getRagBadge(s.rag_context)?.state"
                    :style="canOpenRagDetail(s.rag_context) ? 'cursor:pointer' : ''"
                    :title="canOpenRagDetail(s.rag_context) ? '点击查看参考依据' : ''"
                    @click.stop="openRagDetail(s.rag_context)"
                  >
                    {{ getRagBadge(s.rag_context)?.label }}
                  </span>
                </div>
              </div>
            </div>
          </template>

          <div v-if="loading" class="fp-loading-state">
            <div class="fp-spinner"></div>
            <div class="fp-loading-copy">
              <span>{{ streamStageText || 'AI 分析中' }} ({{ thinkingSeconds }}s)</span>
              <pre v-if="streamPreview" class="fp-stream-preview">{{ streamPreview }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. Bottom Composer -->

        <!-- 5. Bottom Composer -->
        
      </main>

      <!-- RIGHT SUPPORT RAIL (or Narrow Shared Inspector) -->
      <teleport to="body" :disabled="inspectorDocked">
    <aside class="fp-inspector-overlay" :class="{ 'is-visible': inspectorOpen, 'is-docked': inspectorDocked }" @click.self="!inspectorDocked && closeInspector()">
        <div class="fp-inspector">
      <div class="fp-inspector-header">
        <span class="fp-inspector-title">AI 生成建议时使用的上下文</span>
        <div class="fp-inspector-tabs">
          <button class="fp-dock-toggle" @click="inspectorDocked = !inspectorDocked"
                  :title="inspectorDocked ? '切换为浮层模式' : '切换为分屏模式（主内容仍可见）'">
            {{ inspectorDocked ? '收起分屏' : '分屏' }}
          </button>
          <button class="fp-btn-icon fp-inspector-close" @click="closeInspector" title="收起面板"><X :size="12" /></button>
          <button class="fp-tab-btn" :class="{ active: inspectorTab === 'emotion' }" @click="toggleInspector('emotion')">情绪趋势</button>
          <button class="fp-tab-btn" :class="{ active: inspectorTab === 'context' }" @click="toggleInspector('context')">建议依据</button>
        </div>
        <button class="fp-btn-icon close-rail-btn" @click="closeInspector"><X :size="14" /></button>
      </div>

      <div class="fp-inspector-body">
        <!-- EMOTION TAB -->
        <div v-show="inspectorTab === 'emotion'" class="fp-inspector-tab-content">
          <!-- 1. Compact Summary Strip/Cards -->
          <div class="fp-emotion-summary-cards">
            <div class="fp-summary-card">
              <span class="fp-card-lbl">情绪趋势</span>
              <span class="fp-card-val" :class="emotionSummary?.trend || 'neutral'">{{ emotionSummary?.trend === 'positive' ? '正面' : emotionSummary?.trend === 'negative' ? '负面' : '平稳' }}</span>
            </div>
            <div class="fp-summary-card">
              <span class="fp-card-lbl">发言比例</span>
              <span class="fp-card-val">{{ computedChartStats?.msg_ratio || '暂无' }}</span>
            </div>
            <div class="fp-summary-card">
              <span class="fp-card-lbl">回复率</span>
              <span class="fp-card-val">{{ computedChartStats?.reply_rate || '暂无' }}</span>
            </div>
          </div>

          <!-- 2. Main Chart or Empty State -->
          <div v-show="!hasSufficientEmotionData" class="compact-empty">
            <span class="fp-empty-icon"><Sprout :size="20" style="color: #2FA39A;" /></span>
            <span>数据不足以绘制图表 (暂存 {{ (realtimeState.messages || []).length }} 条对话)</span>
          </div>
          
          <div v-show="hasSufficientEmotionData" class="fp-chart-workspace">
            <div class="fp-chart-header-row">
              <span class="fp-chart-lbl">主图表分析</span>
              <button class="fp-btn-text tiny-link" @click="showSecondaryCharts = !showSecondaryCharts">
                {{ showSecondaryCharts ? '收起次要图表' : '展开次要图表' }}
              </button>
            </div>
            <div class="fp-chart-stage tight-stage">
              <div class="fp-chart-item emotion-curve-main compact-main">
                <div ref="emotionChartRef" class="fp-chart-wrap"></div>
              </div>
            </div>

            <!-- 3. Secondary Charts Toggle -->
            <div v-show="showSecondaryCharts" class="fp-secondary-charts-zone">
              <div class="fp-chart-settings compact-charts-config tight-config">
                <label v-for="item in chartConfigItems.filter(i => i.key !== 'emotion_curve')" :key="item.key" class="fp-chart-toggle">
                  <input :checked="chartVisibility[item.key]" type="checkbox" @change="toggleChartVisibility(item.key)" />
                  <span>{{ item.label }}</span>
                </label>
              </div>
              <div class="fp-chart-rail tight-rail">
                <div v-if="chartVisibility.msg_frequency" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">消息频率</div>
                  <div v-show="computedChartStats?.friend_msg_count > 0" ref="freqChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!(computedChartStats?.friend_msg_count > 0)" class="fp-empty-val">缺乏特征数据</div>
                </div>
                <div v-if="chartVisibility.emotion_dist" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">情绪分布</div>
                  <div v-show="computedChartStats?.friend_msg_count > 0" ref="distChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!(computedChartStats?.friend_msg_count > 0)" class="fp-empty-val">缺乏特征数据</div>
                </div>
                <div v-if="chartVisibility.reply_gap" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">回复间隔</div>
                  <div v-show="computedChartStats?.avg_reply_gap" ref="replyGapChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!computedChartStats?.avg_reply_gap" class="fp-empty-val">暂无间隔数据</div>
                </div>
                <div v-if="chartVisibility.msg_ratio" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">发言比例</div>
                  <div ref="ratioChartRef" class="fp-chart-wrap"></div>
                </div>
                <div v-if="chartVisibility.intensity_heat" class="fp-chart-item compact-secondary">
                  <div class="fp-chart-lbl">情绪强度</div>
                  <div v-show="computedChartStats?.friend_msg_count > 0" ref="intensityChartRef" class="fp-chart-wrap"></div>
                  <div v-show="!(computedChartStats?.friend_msg_count > 0)" class="fp-empty-val">缺乏强度数据</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- CONTEXT TAB -->
        <div v-show="inspectorTab === 'context'" class="fp-inspector-tab-content">
          <!-- RAG 提醒：无索引时建议只基于近期对话，记忆槽为空 -->
          <div v-if="ragNeedsAttention" class="fp-rag-notice">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <div class="fp-rag-notice-body">
              <template v-if="ragStatus && !ragStatus.enabled">
                联系人记忆未启用，AI 建议仅参考近期对话。可在「设置 → 联系人记忆」中开启。
              </template>
              <template v-else-if="ragStatus && (ragStatus.status === 'queued' || ragStatus.status === 'building')">
                正在为「{{ ragStatus.display_name }}」构建记忆索引，完成后建议将自动携带长期记忆。
              </template>
              <template v-else>
                尚未为「{{ ragStatus?.display_name || '该联系人' }}」建立长期记忆索引，当前建议仅基于近期对话。
                <button class="fp-rag-notice-btn" :disabled="ragBuilding" @click="buildRagIndex">
                  {{ ragBuilding ? '提交中…' : '立即构建' }}
                </button>
              </template>
            </div>
          </div>
          <div class="fp-context-meta">基于最近 {{ contextUsed.length }} 条主要聊天记录</div>
          <div v-if="!contextUsed.length" class="fp-context-empty">暂无可用参考记录。</div>
          <div class="fp-context-list stream-layout">
            <div v-for="(msg, i) in contextUsed" :key="i" class="fp-ctx-msg" :class="{ self: msg.sender === '我' }">
              <div class="fp-ctx-msg-hd">
                 <span class="fp-ctx-sender">{{ msg.sender }}</span>
                 <span v-if="msg.timestamp" class="fp-ctx-time">{{ formatMsgTime(msg.timestamp) }}</span>
              </div>
              <template v-if="parseWechatQuoteMessage(msg.content).isQuote">
                <div class="fp-ctx-txt">{{ parseWechatQuoteMessage(msg.content).replyText }}</div>
                <div class="fp-wechat-quote">
                  <span class="fp-wechat-quote-bar"></span>
                  <div class="fp-wechat-quote-body">
                    <div class="fp-wechat-quote-text">
                      <span class="fp-wechat-quote-author">{{ parseWechatQuoteMessage(msg.content).quoteAuthor }}：</span>
                      <span>{{ parseWechatQuoteMessage(msg.content).quoteText }}</span>
                    </div>
                  </div>
                </div>
              </template>
              <div v-else class="fp-ctx-txt">{{ msg.content }}</div>
            </div>
          </div>
        </div>
      </div>
          </div>
</aside>
  </teleport>

    </div>
  <footer class="fp-composer">
      <!-- 5.1 Quick Prompts Strip (Only when valid prompts exist) -->
      <div v-if="quickPrompts.length > 0 && quickPrompts.some(q => q && q !== '加载中...')" class="fp-quick-prompts-bar">
        <div class="fp-quick-prompts">
          <button
            v-for="q in quickPrompts.filter(q => q && q !== '加载中...')"
            :key="q"
            class="fp-qp-chip"
            @click="sendQuickPrompt(q)"
          >
            <Sparkles :size="10" />
            <span>{{ q }}</span>
          </button>
        </div>
      </div>

      <!-- 5.2 Unified Slim Strategy Bar (Single Row: Trigger Mode + Relationship Direction) -->
      <div class="fp-strategy-bar">
        <div class="fp-seg-group mode-seg">
          <button
            v-for="m in triggerModes"
            :key="m.value"
            class="fp-seg-btn"
            :class="{ active: triggerMode === m.value }"
            @click="setTriggerMode(m.value)"
            :title="m.value === 'full_auto' ? '自动分析所有新消息' : m.value === 'semi_auto' ? '需要时自动给出建议' : '仅在手动点击生成时分析'"
          >
            {{ m.label }}
          </button>
        </div>

        <div class="fp-strategy-divider"></div>

        <div class="fp-seg-group intent-seg">
          <button
            class="fp-seg-btn"
            :class="{ active: intent === 'intimate' }"
            @click="setIntent('intimate')"
            title="生成更有感情、亲密回复"
          >
            <Flame :size="11" />
            <span>亲近</span>
          </button>
          <button
            class="fp-seg-btn"
            :class="{ active: intent === 'maintain' }"
            @click="setIntent('maintain')"
            title="维持当前氛围"
          >
            <Scale :size="11" />
            <span>维持</span>
          </button>
          <button
            class="fp-seg-btn"
            :class="{ active: intent === 'distance' }"
            @click="setIntent('distance')"
            title="生成稍带距离感回复"
          >
            <Snowflake :size="11" />
            <span>疏远</span>
          </button>
        </div>
      </div>

      <!-- 5.3 Action Input Row (The Hero Row, input box guaranteed space) -->
      <div class="fp-input-row">
        <input
          v-model="userInput"
          type="text"
          class="fp-composer-input"
          :placeholder="llmError ? '模型异常，请检查配置' : '向 AI 军师提问或输入要求…'"
          :disabled="!!llmError || loading"
          @keydown.enter.exact.prevent="handleInputEnter"
        />
        <button
          v-if="userInput.trim()"
          class="fp-btn-act primary send-btn"
          :disabled="loading || !!llmError"
          @click="sendUserContext"
          title="发送指令/问题给 AI (Enter)"
        >
          <Send :size="13" />
          <span>发送</span>
        </button>
        <button
          class="fp-btn-act"
          :class="userInput.trim() ? 'secondary gen-sub-btn' : 'primary gen-btn'"
          :disabled="loading || !!llmError"
          @click="manualGenerate"
          :title="userInput.trim() ? '直接基于最新聊天生成建议' : '根据最新对话生成策略回复建议'"
        >
          <Sparkles :size="13" />
          <span>{{ userInput.trim() ? '生成' : '生成建议' }}</span>
        </button>
      </div>

      <!-- 5.4 Micro Footer (Model Selector & Status) -->
      <div class="fp-composer-footer">
        <div class="fp-model-picker" v-if="llmModels.length > 0">
          <select v-model="activeModelId" class="fp-mini-select" @change="switchModel">
            <option v-for="m in llmModels" :key="m.id" :value="m.id" :disabled="disabledModels.has(m.id)">
              模型: {{ m.name }} {{ disabledModels.has(m.id) ? '(已失效)' : '' }}
            </option>
          </select>
          <ChevronDown :size="10" class="fp-select-arrow" />
        </div>
        <div v-if="llmError" class="fp-error-txt" :title="llmError">{{ llmError }}</div>
        <div v-else class="fp-footer-hint">Enter 发送</div>
      </div>
    </footer>
  </div>

  <Teleport to="body">
    <div v-if="showResumeDialog" class="fp-modal-overlay" @click.self="resolveResumeChoice('skip')">
      <div class="fp-modal">
        <h3 class="fp-modal-title">补全未监听消息</h3>
        <p class="fp-modal-desc">
          上次监听到 {{ resumeDialogState.lastMessageTime }}，距今约 {{ resumeDialogState.gapLabel }}。
        </p>
        <div class="fp-modal-box">{{ resumeDialogState.preview }}</div>
        <div class="fp-modal-actions">
          <button class="fp-btn-base ghost" @click="resolveResumeChoice('skip')">忽略</button>
          <button class="fp-btn-base primary" @click="resolveResumeChoice('backfill')">补全记录</button>
        </div>
      </div>
    </div>
    <div v-if="showProfileDialog" class="fp-modal-overlay" @click.self="showProfileDialog = false">
      <div class="fp-modal">
        <h3 class="fp-modal-title">重新生成画像</h3>
        <p class="fp-modal-desc">分析与「{{ realtimeState.talkerName }}」的聊天记录并重树特征框架。</p>
        <div class="fp-modal-actions">
          <button class="fp-btn-base ghost" @click="showProfileDialog = false">取消</button>
          <button class="fp-btn-base primary" @click="generateProfile">确认生成</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- 直接复用设置页现成的「记忆管理」弹窗组件 RagFactDialog -->
  <RagFactDialog
    :visible="ragDetail.visible"
    :log-id="ragDetail.logId"
    :conversation-id="ragStatus?.conversation_id || null"
    :account-wxid="activeAccountWxid"
    :display-name="realtimeState.talkerName"
    :avatar-url="contactAvatar"
    :user-avatar-url="userAvatar"
    @close="closeRagDetail"
  />
</template>


<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  X,
  Maximize2,
  Sprout,
  Flame,
  Scale,
  Snowflake,
  AlertCircle,
  Zap,
  Moon,
  VolumeX,
  Sparkles,
  Pin,
  ChevronDown,
  Brain,
  Activity,
  MessageSquare,
  Send,
} from 'lucide-vue-next'
import { bridgeReady, api } from '@/api/bridge'
import * as echarts from 'echarts'
import { chronoAxisBase } from '@/components/charts/chartTheme'
import CtAvatar from '@/components/base/CtAvatar.vue'
import RagFactDialog from '@/components/settings/RagFactDialog.vue'
import { showConfirm, showDialog } from '@/utils/dialog'
import { safeGetItem, safeRemoveItem, safeSetItem } from '@/utils/safeStorage'
import { copyText } from '@/utils/clipboard'

const router = useRouter()

function buildMissingModelLines(modelStatus: any): string {
  const details = Array.isArray(modelStatus?.missing_details) ? modelStatus.missing_details : []
  if (!details.length) {
    return '分析模型未安装完整'
  }

  return details
    .map((item: any) => {
      const modelName = item?.model_name || item?.model_key || '未知模型'
      const issue = item?.issue || '模型不可用'
      return `- ${modelName}: ${issue}`
    })
    .join('\n')
}

async function ensureRealtimeAnalysisModelsReady(): Promise<boolean> {
  try {
    const modelStatus = await api.check_analysis_model_status()
    if (modelStatus?.ok && modelStatus?.analysis_available) {
      return true
    }

    const detailLines = buildMissingModelLines(modelStatus)
    const shouldGoAnalytics = await showConfirm({
      title: '缺少分析模型',
      message:
        `检测到当前分析模型未安装完整：\n${detailLines}\n\n` +
        '实时监听依赖情绪分析模型。请先前往“历史数据”页面，选择联系人后点击一次“开始分析”，按提示完成模型安装。\n\n' +
        '现在跳转到历史数据页面吗？',
    })

    chatError.value = '缺少分析模型，请先前往历史数据页面完成安装'

    if (shouldGoAnalytics) {
      await router.push('/analytics')
    }
    return false
  } catch (e) {
    const errorMessage = (e as any)?.message || '未知错误'
    await showDialog({
      title: '无法检查分析模型',
      message:
        `分析模型状态检查失败: ${errorMessage}\n\n` +
        '请先前往“历史数据”页面尝试开始分析；如果仍失败，再检查模型文件和 Python 依赖是否完整。',
    })
    chatError.value = '分析模型状态检查失败，请先前往历史数据页面检查安装'
    return false
  }
}

const inspectorOpen = ref(false)
const isWideMode = ref(window.innerWidth >= 820)
// 提为具名函数，保证 add/remove 用同一引用，避免组件卸载后监听残留
const handleInspectorResize = () => { isWideMode.value = window.innerWidth >= 820 }
window.addEventListener('resize', handleInspectorResize)
const inspectorTab = ref<'emotion' | 'context'>('emotion')
const inspectorDocked = ref(false)  // 分屏模式：面板停靠底部，主内容仍可见
const showSecondaryCharts = ref(false)
watch(showSecondaryCharts, (val) => { if (val) { nextTick(() => { typeof syncCharts === 'function' && syncCharts(); typeof triggerChartResize === 'function' && triggerChartResize() }) } })
// 用合并了基线的消息数组（含预热 sentiment），而非仅 buffer 计数——否则开场恒判数据不足
const hasSufficientEmotionData = computed(() => (realtimeState.messages || []).length >= 4 && emotionHistory.value && emotionHistory.value.length > 2)
function triggerChartResize() {
  requestAnimationFrame(() => {
    setTimeout(() => { typeof syncCharts === 'function' && syncCharts(); typeof resizeVisibleCharts === 'function' && resizeVisibleCharts(); }, 50)
    setTimeout(() => { typeof syncCharts === 'function' && syncCharts(); typeof resizeVisibleCharts === 'function' && resizeVisibleCharts(); }, 200)
    setTimeout(() => { typeof syncCharts === 'function' && syncCharts(); typeof resizeVisibleCharts === 'function' && resizeVisibleCharts(); }, 500)
  })
}

async function closeInspector() {
  inspectorOpen.value = false
  inspectorDocked.value = false
  showSecondaryCharts.value = false
}

async function toggleInspector(tab: 'emotion' | 'context') {
  if (inspectorOpen.value && inspectorTab.value === tab) {
    await closeInspector()
  } else {
    inspectorOpen.value = true
    inspectorTab.value = tab
    showSecondaryCharts.value = false
    if (tab === 'emotion') {
      nextTick(() => { if (typeof syncCharts === 'function') syncCharts(); typeof triggerChartResize === 'function' && triggerChartResize() })
    }
    if (tab === 'context') {
      loadMonitorRagStatus()
    }
  }
}

// ===== RAG 索引状态（建议依据提醒）=====
// 无索引时 AI 建议只基于近期对话（记忆槽为空），需要在此提醒并可一键构建
const ragStatus = ref<any>(null)
const ragBuilding = ref(false)

async function loadMonitorRagStatus() {
  try {
    await bridgeReady()
    const r = await api.get_monitor_rag_status(activeAccountWxid.value || undefined)
    if (r?.ok) ragStatus.value = r
  } catch (e) {
    console.debug('[FloatingPanel] RAG 状态获取失败:', e)
  }
}

const ragNeedsAttention = computed(() => {
  const s = ragStatus.value
  if (!s || !s.monitoring) return false
  if (!s.enabled) return true
  return !s.has_index
})

async function buildRagIndex() {
  const s = ragStatus.value
  if (!s?.conversation_id || ragBuilding.value) return
  ragBuilding.value = true
  try {
    await bridgeReady()
    const r = await api.rebuild_rag_index(s.conversation_id, activeAccountWxid.value || undefined)
    if (r?.ok) {
      // 队列串行构建，完成后状态经下次打开/轮询刷新
      ragStatus.value = { ...s, status: r.state || 'queued' }
      // 构建中稍后回查一次，横幅能自动消失（队列串行，15s 通常不够全量，
      // 回查后仍在构建则由再次打开面板兜底）
      setTimeout(loadMonitorRagStatus, 15000)
    }
  } catch (e) {
    console.error('[FloatingPanel] RAG 索引构建发起失败:', e)
  } finally {
    ragBuilding.value = false
  }
}


type ChartVisibilityKey =
  | 'emotion_curve'
  | 'msg_frequency'
  | 'emotion_dist'
  | 'reply_gap'
  | 'msg_ratio'
  | 'intensity_heat'

type ChartVisibilityState = Record<ChartVisibilityKey, boolean>

type EmotionPoint = {
  time: string
  polarity: number
  sender: string
  content: string
  intensity: number
  confidence: number
  timestamp: number
}

const DEFAULT_CHART_VISIBILITY: ChartVisibilityState = {
  emotion_curve: true,
  msg_frequency: true,
  emotion_dist: false,
  reply_gap: false,
  msg_ratio: true,
  intensity_heat: false,
}

const chartConfigItems: { key: ChartVisibilityKey; label: string }[] = [
  { key: 'emotion_curve', label: '对方情绪曲线' },
  { key: 'msg_frequency', label: '消息频率' },
  { key: 'emotion_dist', label: '情绪分布' },
  { key: 'reply_gap', label: '回复间隔' },
  { key: 'msg_ratio', label: '发言比例' },
  { key: 'intensity_heat', label: '情绪强度' },
]

// ========== 状态 ==========
const realtimeState = reactive({
  isMonitoring: false,
  talkerName: '',
  batchId: '',
  messageCount: 0,
  status: 'idle' as string,
  messages: [] as any[],
  // 当前监听会话号：建议配置按联系人存储的读写维度
  conversationId: 0
})

const chatError = ref('')
// 后端 chat_ready：聊天定位真正完成才显示「监听已就绪」——启动瞬间
// is_monitoring 即为真，直接用它会把「正在定位」误报成「已就绪」
const chatReady = ref(false)

const llmModels = ref<any[]>([])
const activeModelId = ref<number | null>(null)
const disabledModels = ref<Set<number>>(new Set())
const llmError = ref('')
const connectionLost = ref(false)  // 断流感知状态
let pollFailCount = 0  // 连续轮询失败计数

const processedSuggestionIds = new Set<number>()

const intent = ref<'intimate' | 'maintain' | 'distance'>('maintain')
const triggerMode = ref<'full_auto' | 'semi_auto' | 'manual'>('semi_auto')
const loading = ref(false)
const userInput = ref('')
const profile = ref<any>({ name: '', tags: [] })
const contactAvatar = ref('')
const profileLoading = ref(false)
const profileExpanded = ref(false)
const showProfileDialog = ref(false)
const emotionSummary = ref<any>(null)
const chartSettingsOpen = ref(false)
const showResumeDialog = ref(false)
const activeAccountWxid = ref('')
const resumeDialogState = reactive({
  lastMessageTime: '',
  gapLabel: '',
  preview: '',
})
let resumeDialogResolver: ((value: 'skip' | 'backfill') => void) | null = null

// 建议数据
const pendingSuggestions = ref<any[]>([])
// 原始消息即时回显（不等 LLM 建议——思考模型一次调用 30-60s，此前面板全程空白）
const liveEchoMessages = ref<any[]>([])
const echoedMessageIds = new Set<number>()
const manualSuggestion = ref<any>(null)
const expandedIds = ref<Set<string>>(new Set(['manual']))  // 展开状态管理
const showContext = ref(false)  // 是否展示 AI 参考记录
const contextUsed = ref<{ sender: string; content: string; timestamp: number }[]>([])  // AI 参考的聊天记录

// 会话线程继承
const lastThread = ref<any>(null)

// AI 对话历史 (带有时间戳)
type RagContextState =
  | 'no_hit'
  | 'referenced'
  | 'not_referenced'
  | 'fact_hit'
  | 'document_hit'
  | 'relationship_policy'
  | 'hot_context'
  | 'degraded'
  | 'hidden'
type RagContextSummary = {
  state?: RagContextState
  label?: string
  hit_count?: number
  referenced_count?: number
  log_id?: number | null
}
// 后端时间戳统一为 Unix 秒；此处兜底转换成毫秒（>1e12 视为已是毫秒，空值用当前时间）
// 直接 new Date(秒) 会落到 1970 年，导致气泡时间与排序错乱
function toMs(v: any): number {
  const n = Number(v)
  return (n && n > 1e12) ? n : (n ? n * 1000 : Date.now())
}
const conversationHistory = ref<{ role: string; content: string; ts: number; rag_context?: RagContextSummary }[]>([])

// 情绪历史数据（用于曲线图）
const emotionHistory = ref<EmotionPoint[]>([])

const chartVisibility = reactive<ChartVisibilityState>({ ...DEFAULT_CHART_VISIBILITY })

// ECharts 引用
const emotionChartRef = ref<HTMLElement | null>(null)
const freqChartRef = ref<HTMLElement | null>(null)
const distChartRef = ref<HTMLElement | null>(null)
const replyGapChartRef = ref<HTMLElement | null>(null)
const ratioChartRef = ref<HTMLElement | null>(null)
const intensityChartRef = ref<HTMLElement | null>(null)
const suggestionsRef = ref<HTMLElement | null>(null)
const chartInstances: Partial<Record<ChartVisibilityKey, echarts.ECharts>> = {}

// 定时器
let statusTimer: any = null
let messagesTimer: any = null
let suggestionsTimer: any = null
const START_REQUEST_KEY = 'realtime_start_request'
const RESUME_THRESHOLD_SECONDS = 300
const BACKFILL_MAX_SCROLL_ROUNDS = 80

// ========== 常量 ==========
const triggerModes = [
  { value: 'full_auto', label: '全自动' },
  { value: 'semi_auto', label: '半自动' },
  { value: 'manual', label: '手动' },
]

const intents = [
  { value: 'intimate', icon: Flame },
  { value: 'maintain', icon: Scale },
  { value: 'distance', icon: Snowflake },
]

const quickPrompts = ref<string[]>([])

// ========== 计算属性与交互辅助 ==========
const contactDisplayName = computed(() => {
  const name = (profile.value?.name || realtimeState.talkerName || '').trim()
  return name || '等待监听对象...'
})

const latestRagContext = computed(() => {
  for (let i = allSuggestions.value.length - 1; i >= 0; i--) {
    const s = allSuggestions.value[i]
    if (s.rag_context?.log_id) return s.rag_context
  }
  return null
})

function openLatestRagDetail() {
  if (latestRagContext.value) {
    openRagDetail(latestRagContext.value)
  } else {
    toggleInspector('context')
  }
}

function handleInputEnter() {
  if (userInput.value.trim()) {
    sendUserContext()
  } else if (!loading.value && !llmError.value) {
    manualGenerate()
  }
}
const chartVisibilityStorageKey = computed(() => {
  const displayName = (realtimeState.talkerName || profile.value.name || 'default').trim() || 'default'
  const account = (activeAccountWxid.value || 'default').trim() || 'default'
  return `ct_chart_visibility:${account}:${displayName}`
})

const computedChartStats = computed(() => {
  const msgs = realtimeState.messages || []
  const friendMsgs = msgs.filter(m => m.sender_attr === 'friend')
  const selfMsgs = msgs.filter(m => m.sender_attr === 'self')

  let repliedCount = 0
  for (let i = 0; i < msgs.length; i++) {
    if (msgs[i].sender_attr !== 'self') continue
    const hasReply = msgs.slice(i + 1).some(nextMsg => nextMsg.sender_attr === 'friend')
    if (hasReply) repliedCount++
  }

  const positiveCount = friendMsgs.filter(m => Number(m.sentiment?.polarity) > 0).length
  const positiveRate = friendMsgs.length ? (positiveCount / friendMsgs.length).toFixed(2) : 'N/A'
  const replyRate = selfMsgs.length ? (repliedCount / selfMsgs.length).toFixed(2) : 'N/A'
  const msgRatio = selfMsgs.length || friendMsgs.length ? `${selfMsgs.length}:${friendMsgs.length}` : 'N/A'

  const gaps = friendMsgs
    .slice(1)
    .map((m, i) => Number(m.timestamp) - Number(friendMsgs[i].timestamp))
    .filter(gap => gap > 0 && gap < 3600)
  const avgReplyGap = gaps.length
    ? Math.round(gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length)
    : null

  return {
    reply_rate: replyRate,
    positive_rate: positiveRate,
    msg_ratio: msgRatio,
    avg_reply_gap: avgReplyGap,
    friend_msg_count: friendMsgs.length,
    self_msg_count: selfMsgs.length,
  }
})

const allSuggestions = computed(() => {
  const list: any[] = []
  const seenIds = new Set<string>()

  // 手动建议优先
  if (manualSuggestion.value) {
    if (
      manualSuggestion.value.summary !== '[PURE_CHAT]'
      && manualSuggestion.value.summary !== '[SILENT]'
      && !isPlaceholderSuggestion(manualSuggestion.value)
    ) {
      const id = manualSuggestion.value.id || 'manual'
      list.push({ ...manualSuggestion.value, id: id, _type: 'suggestion' })
      seenIds.add(String(id))
    }
  }

  // 轮询建议：跳过纯对话和静默回应，以及跳过已被手动首选加载的高亮建议的同一id
  for (const s of pendingSuggestions.value) {
    if (s.summary === '[PURE_CHAT]' || s.summary === '[SILENT]') continue
    if (isPlaceholderSuggestion(s)) continue
    if (s.id && seenIds.has(String(s.id))) continue
    if (s.id) seenIds.add(String(s.id))
    list.push({ ...s, _type: 'suggestion' })
  }

  // 对话历史
  conversationHistory.value.forEach((c, idx) => {
    list.push({ ...c, _type: 'chat', _tempId: `chat_${idx}`, created_at: c.ts })
  })

  // 原始消息回显（微信消息秒级上屏，AI 建议稍后跟进）
  for (const m of liveEchoMessages.value) {
    // 系统行（撤回/拍一拍等）不是聊天消息，
    // 不能按“非我方”渲染成对方气泡。
    if (String(m.sender_attr || '').toLowerCase() === 'system'
      || String(m.message_type || '').toLowerCase() === 'system') continue
    list.push({ ...m, _type: 'live_msg', created_at: m.ts })
  }

  // 按时间升序排序（旧的在上，新的在下，像聊天软件）
  list.sort((a, b) => {
    const timeA = a.created_at || Math.floor(Date.now() / 1000)
    const timeB = b.created_at || Math.floor(Date.now() / 1000)
    return timeA - timeB
  })

  return list
})

type ParsedWechatQuote = {
  replyText: string
  isQuote: boolean
  hasQuote: boolean
  quoteAuthor: string
  quoteText: string
}

const WECHAT_QUOTE_RE = /^([\s\S]+?)\s+引用\s+([^\n]{1,64}?)\s+的消息\s*[:：]\s*([\s\S]+)$/

function parseWechatQuoteMessage(raw: any): ParsedWechatQuote {
  const text = String(raw || '').trim()
  const m = text.match(WECHAT_QUOTE_RE)
  if (!m) {
    return {
      replyText: text,
      isQuote: false,
      hasQuote: false,
      quoteAuthor: '',
      quoteText: '',
    }
  }
  return {
    replyText: (m[1] || '').trim(),
    isQuote: true,
    hasQuote: true,
    quoteAuthor: (m[2] || '').trim(),
    quoteText: (m[3] || '').trim(),
  }
}

const expandedQuoteKeys = ref<Set<string>>(new Set())

function isQuoteExpanded(key: string): boolean {
  return expandedQuoteKeys.value.has(String(key))
}

function toggleQuoteExpand(key: string) {
  const k = String(key)
  const next = new Set(expandedQuoteKeys.value)
  if (next.has(k)) {
    next.delete(k)
  } else {
    next.add(k)
  }
  expandedQuoteKeys.value = next
}

function parseSuggestionSpeeches(raw: any): string[] {
  if (Array.isArray(raw)) return raw
  if (typeof raw !== 'string') return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function isPlaceholderSuggestion(s: any): boolean {
  if (!s) return false
  const summary = String(s.summary || '').trim()
  const thought = String(s.thought_process || '').trim()
  const speeches = parseSuggestionSpeeches(s.speeches)
  const metaKeywords = ['用户', '对方', '规则', '模仿', '画像', 'JSON', 'reply', 'summary', 'thought_process', 'speeches', 'Prompt', 'prompt', '性格标签', '聊天风格', '沟通注意', '关系状态', '打字排版风格', '高频语气词汇', '常用句式模板', '模仿禁忌']

  if (summary === '...' || summary === '…') return true
  if (thought === '...' || thought === '…') return true
  if (summary.startsWith('话术应该关于')) return true
  if (thought.startsWith('thought_process:')) return true
  if (speeches.length > 0 && speeches.every((item) => /^话术\d+$/.test(String(item).trim()))) {
    return true
  }
  if (speeches.length > 0 && speeches.every((item) => {
    const text = String(item).trim()
    return text.startsWith('**') || metaKeywords.some((keyword) => text.includes(keyword))
  })) {
    return true
  }

  return false
}

function readPendingStartRequest() {
  const raw = safeGetItem(START_REQUEST_KEY, window.sessionStorage)
  try {
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function clearPendingStartRequest() {
  safeRemoveItem(START_REQUEST_KEY, window.sessionStorage)
}

function formatResumeTime(timestamp?: number) {
  if (!timestamp) return '未知时间'
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return '未知时间'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatResumeGap(gapSeconds?: number) {
  const totalSeconds = Math.max(0, Number(gapSeconds || 0))
  if (totalSeconds < 60) return `${totalSeconds} 秒`
  if (totalSeconds < 3600) return `${Math.floor(totalSeconds / 60)} 分钟`
  if (totalSeconds < 86400) return `${Math.floor(totalSeconds / 3600)} 小时`
  return `${Math.floor(totalSeconds / 86400)} 天`
}

function loadChartVisibility(displayName?: string) {
  const key = displayName?.trim()
    ? `ct_chart_visibility:${(activeAccountWxid.value || 'default').trim() || 'default'}:${displayName.trim()}`
    : chartVisibilityStorageKey.value
  try {
    const raw = safeGetItem(key)
    const parsed = raw ? JSON.parse(raw) : null
    const nextState = { ...DEFAULT_CHART_VISIBILITY, ...(parsed || {}) }
    for (const item of chartConfigItems) {
      chartVisibility[item.key] = Boolean(nextState[item.key])
    }
  } catch {
    for (const item of chartConfigItems) {
      chartVisibility[item.key] = DEFAULT_CHART_VISIBILITY[item.key]
    }
  }
}

function persistChartVisibility() {
  safeSetItem(chartVisibilityStorageKey.value, JSON.stringify(chartVisibility))
}

function toggleChartVisibility(key: ChartVisibilityKey) {
  chartVisibility[key] = !chartVisibility[key]
  persistChartVisibility()
  nextTick(() => syncCharts())
}

function buildHistoricalContext() {
  return {
    profile: profile.value?.chat_style ? profile.value : undefined,
    emotion_summary: emotionSummary.value || undefined,
    chart_stats: computedChartStats.value,
  }
}

function resolveResumeChoice(choice: 'skip' | 'backfill') {
  showResumeDialog.value = false
  const resolver = resumeDialogResolver
  resumeDialogResolver = null
  resolver?.(choice)
}

async function maybeResolveResumeMode(talkerName: string): Promise<'skip' | 'backfill' | false> {
  const probe = await api.get_realtime_resume_info(
    talkerName,
    RESUME_THRESHOLD_SECONDS,
    activeAccountWxid.value || undefined,
  )
  if (!probe?.ok) {
    console.warn('[FloatingPanel] 获取回溯探测信息失败:', probe?.error || probe)
    return 'skip'
  }

  if (!probe.should_offer_resume) {
    return 'skip'
  }

  resumeDialogState.lastMessageTime = formatResumeTime(probe.last_message_timestamp)
  resumeDialogState.gapLabel = formatResumeGap(probe.gap_seconds)
  resumeDialogState.preview = String(probe.last_message_preview || '').trim() || '无预览'
  showResumeDialog.value = true

  return await new Promise<'skip' | 'backfill'>((resolve) => {
    resumeDialogResolver = resolve
  })
}

async function applyMonitoringStatus(status: any) {
  activeAccountWxid.value = status.account_wxid || activeAccountWxid.value
  realtimeState.isMonitoring = true
  realtimeState.status = 'monitoring'
  realtimeState.talkerName = status.talker_display_name || ''
  realtimeState.batchId = status.batch_id || ''
  realtimeState.messageCount = status.message_count || 0
  realtimeState.conversationId = Number(status.conversation_id || 0)
  chatError.value = status.chat_error || ''

  startPolling()
  loadSuggestionConfig()
  loadLlmModels()
  resolveContactAvatar(realtimeState.talkerName)
  checkContactProfile(realtimeState.talkerName)
  loadChartVisibility(realtimeState.talkerName)

  try {
    const tRes = await api.get_latest_thread(realtimeState.talkerName, activeAccountWxid.value || undefined)
    // 空会话（0 条消息，如空闲归档器产生的空档）没有可续内容——不显示横幅
    if (tRes.ok && tRes.thread && Number(tRes.thread.message_count || 0) > 0) {
      lastThread.value = tRes.thread
    }
  } catch (e) {
    console.error('查询历史线程失败:', e)
  }
}

async function startPendingMonitoring(talkerName: string, requestedAccountWxid = '') {
  activeAccountWxid.value = requestedAccountWxid || activeAccountWxid.value
  realtimeState.talkerName = talkerName
  contactAvatar.value = ''
  realtimeState.status = 'searching'
  chatReady.value = false
  chatError.value = '正在准备监听对象...'

  const modelsReady = await ensureRealtimeAnalysisModelsReady()
  if (!modelsReady) {
    realtimeState.status = 'idle'
    return false
  }

  const resumeMode = await maybeResolveResumeMode(talkerName)
  if (!resumeMode) {
    return false
  }

  let progressTimer: number | null = window.setInterval(async () => {
    try {
      const status = await api.get_realtime_status()
      if (status?.chat_error) {
        chatError.value = status.chat_error
      }
    } catch (_e) {
      // 启动期间状态探测失败不打断主流程
    }
  }, 1200)

  try {
    const result = await api.start_realtime_monitor(talkerName, resumeMode, activeAccountWxid.value || undefined)
    if (!(result.success || result.ok)) {
      chatError.value = result.error || result.message || '启动监听失败'
      return false
    }

    // 启动成功后取真实状态（含 conversation_id：建议配置按联系人读写的键），
    // 拉取失败时用手搓兜底对象（conversationId 退 0 仅影响配置键，不影响监听）
    let initialStatus: any = {
      ok: true,
      is_monitoring: true,
      account_wxid: activeAccountWxid.value,
      talker_display_name: talkerName,
      batch_id: result.batch_id,
      message_count: 0,
      chat_error: '',
    }
    try {
      const st = await api.get_realtime_status()
      if (st?.ok && st.is_monitoring) initialStatus = st
    } catch (_e) {
      console.warn('[FloatingPanel] 启动后拉取监听状态失败，使用兜底状态')
    }

    await applyMonitoringStatus(initialStatus)
    return true
  } finally {
    if (progressTimer !== null) {
      window.clearInterval(progressTimer)
      progressTimer = null
    }
  }
}

// ========== 生命周期 ==========
onMounted(async () => {
  window.addEventListener('chrono:realtime-push', handleRealtimePush)
  try {
    await bridgeReady()
    const accountResult = await api.get_wechat_accounts()
    if (accountResult?.ok) {
      activeAccountWxid.value = accountResult.active_account_wxid || ''
    }
  } catch (e) {
    console.error('[FloatingPanel] 加载微信账号上下文失败:', e)
  }

  const pendingStart = readPendingStartRequest()
  if (pendingStart?.talkerName) {
    clearPendingStartRequest()
    const started = await startPendingMonitoring(
      String(pendingStart.talkerName),
      String(pendingStart.account_wxid || activeAccountWxid.value || ''),
    )
    loadChartVisibility(String(pendingStart.talkerName))
    window.addEventListener('resize', resizeVisibleCharts)
    await nextTick()
    syncCharts()
    if (!started && !realtimeState.isMonitoring) {
      realtimeState.status = 'error'
      console.error('[FloatingPanel] 待启动监听未成功，保留悬浮页并显示错误')
    }
    return
  }
  // 尝试恢复监听状态（带重试，因为现在悬浮模式先于监听启动）
  let status: any = null
  const MAX_RETRIES = 5
  const RETRY_DELAY = 1000 // ms

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      await bridgeReady()
      if (attempt > 0) {
        await new Promise(r => setTimeout(r, RETRY_DELAY))
      }
      status = await api.get_realtime_status()
      if (status.ok && status.is_monitoring) {
        break
      }
      console.warn(`[FloatingPanel] 第 ${attempt + 1} 次状态检查: is_monitoring=${status?.is_monitoring}`)
    } catch (e) {
      console.error(`[FloatingPanel] 第 ${attempt + 1} 次检查失败:`, e)
    }
  }

  if (status?.ok && status.is_monitoring) {
    activeAccountWxid.value = status.account_wxid || activeAccountWxid.value
    realtimeState.isMonitoring = true
    realtimeState.status = 'monitoring'
    realtimeState.talkerName = status.talker_display_name || ''
    realtimeState.batchId = status.batch_id || ''
    realtimeState.messageCount = status.message_count || 0
    realtimeState.conversationId = Number(status.conversation_id || 0)
    // 检查 chat_error
    if (status.chat_error) {
      chatError.value = status.chat_error
    }

    startPolling()
    loadSuggestionConfig()
    loadLlmModels()
    resolveContactAvatar(realtimeState.talkerName)
    checkContactProfile(realtimeState.talkerName)
    loadChartVisibility(realtimeState.talkerName)

    // 查询是否有上次会话线程
    try {
      const tRes = await api.get_latest_thread(realtimeState.talkerName, activeAccountWxid.value || undefined)
      if (tRes.ok && tRes.thread && Number(tRes.thread.message_count || 0) > 0) {
        lastThread.value = tRes.thread
      }
    } catch (e) {
      console.error('查询历史线程失败:', e)
    }
  } else {
    // 多次重试后仍未在监听状态，退回
    console.error('[FloatingPanel] 无法恢复监听状态，退出悬浮模式')
    goBackToSuggestions()
    return
  }

  window.addEventListener('resize', resizeVisibleCharts)
  await nextTick()
  syncCharts()
})

onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener('chrono:realtime-push', handleRealtimePush)
  window.removeEventListener('resize', handleInspectorResize)
  window.removeEventListener('resize', resizeVisibleCharts)
  disposeAllCharts()
  resolveResumeChoice('skip')
})

watch(() => realtimeState.talkerName, (name) => {
  if (!name) {
    contactAvatar.value = ''
    profile.value = { name: '', tags: [] }
    return
  }
  resolveContactAvatar(name)
  loadChartVisibility(name)
  nextTick(() => syncCharts())
})

watch(chartVisibilityStorageKey, () => {
  nextTick(() => syncCharts())
})

// ========== 悬浮窗控制 ==========
async function exitFloating() {
  try {
    await bridgeReady()
    // 停止监听并保存当前的对话记录
    if (realtimeState.isMonitoring) {
      // 通过 JSON 序列化反序列化可以去除 proxy 对象包装，确保传给后端的是普通对象数组
      const historyToSave = JSON.parse(JSON.stringify(conversationHistory.value))
      await api.stop_realtime_monitor(historyToSave)
    }
    stopPolling()
    // 退出悬浮模式（恢复窗口尺寸）
    await api.exit_floating_mode()
  } catch (e) {
    console.error('退出悬浮模式失败:', e)
  }
  // 跳转回对象工作台（实时助手 tab 所在页）
  router.push('/analytics')
}

async function startFloatingDrag(event: MouseEvent) {
  // 返回按钮和其它交互控件保留点击行为，不触发窗口拖动。
  if ((event.target as HTMLElement | null)?.closest('button, a, input, select, textarea')) return
  event.preventDefault()
  let lastX = event.screenX
  let lastY = event.screenY
  let moving = true
  let moveQueue = Promise.resolve()
  const move = async (moveEvent: MouseEvent) => {
    if (!moving) return
    const dx = moveEvent.screenX - lastX
    const dy = moveEvent.screenY - lastY
    lastX = moveEvent.screenX
    lastY = moveEvent.screenY
    if (!dx && !dy) return
    moveQueue = moveQueue.then(async () => {
      await bridgeReady()
      await api.move_floating_window(dx, dy)
    }).catch((e) => console.error('移动悬浮窗失败:', e))
  }
  const stop = () => {
    moving = false
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', stop)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', stop, { once: true })
}

/** 仅退回对象工作台（不停止监听，用于状态恢复失败时） */
async function goBackToSuggestions() {
  stopPolling()
  try {
    await bridgeReady()
    await api.exit_floating_mode()
  } catch (e) {
    console.error('退出悬浮模式失败:', e)
  }
  router.push('/analytics')
}

// ========== ECharts 图表 ==========
function getChartRef(key: ChartVisibilityKey): HTMLElement | null {
  const refs: Record<ChartVisibilityKey, HTMLElement | null> = {
    emotion_curve: emotionChartRef.value,
    msg_frequency: freqChartRef.value,
    emotion_dist: distChartRef.value,
    reply_gap: replyGapChartRef.value,
    msg_ratio: ratioChartRef.value,
    intensity_heat: intensityChartRef.value,
  }
  return refs[key]
}

function getChartInstance(key: ChartVisibilityKey): echarts.ECharts | null {
  const target = getChartRef(key)
  if (!target || !chartVisibility[key]) return null
  if (!chartInstances[key]) {
    chartInstances[key] = echarts.init(target, undefined, { renderer: 'canvas' })
  }
  return chartInstances[key] || null
}

function disposeChart(key: ChartVisibilityKey) {
  if (chartInstances[key]) {
    chartInstances[key]?.dispose()
    delete chartInstances[key]
  }
}

function disposeAllCharts() {
  for (const item of chartConfigItems) {
    disposeChart(item.key)
  }
}

function resizeVisibleCharts() {
  for (const item of chartConfigItems) {
    chartInstances[item.key]?.resize()
  }
}

function buildChartBaseOption(): echarts.EChartsOption {
  return chronoAxisBase() as echarts.EChartsOption
}

function buildMessageFrequencyBuckets() {
  const messages = realtimeState.messages || []
  if (!messages.length) {
    return { labels: [] as string[], values: [] as number[] }
  }

  const sortedMessages = [...messages].sort((a, b) => Number(a.timestamp) - Number(b.timestamp))
  const startTs = Number(sortedMessages[0]?.timestamp || 0)
  const endTs = Number(sortedMessages[sortedMessages.length - 1]?.timestamp || startTs)
  const span = Math.max(endTs - startTs, 1)
  const bucketCount = Math.min(12, Math.max(4, sortedMessages.length))
  const bucketSize = Math.max(60, Math.ceil(span / bucketCount))
  const counts = Array.from({ length: bucketCount }, () => 0)
  const labels = Array.from({ length: bucketCount }, (_, index) => {
    const bucketTs = startTs + index * bucketSize
    return new Date(bucketTs * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  })

  sortedMessages.forEach((message) => {
    const ts = Number(message.timestamp || startTs)
    const rawIndex = Math.floor((ts - startTs) / bucketSize)
    const bucketIndex = Math.max(0, Math.min(bucketCount - 1, rawIndex))
    counts[bucketIndex]++
  })

  return { labels, values: counts }
}

function buildReplyGapData() {
  const friendMsgs = (realtimeState.messages || []).filter(message => message.sender_attr === 'friend')
  const points = friendMsgs
    .slice(1)
    .map((message, index) => {
      const gap = Number(message.timestamp) - Number(friendMsgs[index].timestamp)
      return {
        label: new Date(Number(message.timestamp) * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        value: gap,
      }
    })
    .filter(point => point.value > 0 && point.value < 3600)

  return {
    labels: points.map(point => point.label),
    values: points.map(point => point.value),
  }
}

function syncCharts() {
  for (const item of chartConfigItems) {
    if (!chartVisibility[item.key]) {
      disposeChart(item.key)
      continue
    }

    const chart = getChartInstance(item.key)
    if (!chart) continue

    if (item.key === 'emotion_curve') {
      const times = emotionHistory.value.map(point => point.time)
      const values = emotionHistory.value.map(point => point.polarity)
      chart.setOption({
        ...buildChartBaseOption(),
        yAxis: {
          ...(buildChartBaseOption().yAxis as object),
          min: -1,
          max: 1,
          splitNumber: 4,
          axisLabel: { fontSize: 10, formatter: '{value}' },
        },
        xAxis: {
          ...(buildChartBaseOption().xAxis as object),
          data: times,
        },
        tooltip: {
          ...buildChartBaseOption().tooltip,
          trigger: 'axis',
          formatter: (params: any) => {
            const point = params[0]
            const itemData = emotionHistory.value[point.dataIndex]
            const value = Number(point.data || 0)
            const label = value > 0 ? '正面' : value < 0 ? '负面' : '中性'
            const raw = itemData?.content?.length > 25 ? `${itemData.content.slice(0, 25)}…` : itemData?.content || ''
            // 聊天原文经 HTML 转义后再拼 tooltip（ECharts 按 HTML 渲染，防注入）
            const content = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            return `<b>对方情绪</b><br/>时间：${point.name}<br/>情绪：${label} (${value.toFixed(2)})${content ? `<br/><span style="color:#9B95A5">${content}</span>` : ''}`
          },
        },
        series: [{
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: values,
          lineStyle: { width: 2.5, color: '#5A4BC4' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(90,75,196,0.3)' },
              { offset: 1, color: 'rgba(90,75,196,0.02)' },
            ]),
          },
          itemStyle: {
            color: (params: any) => {
              const value = Number(params.data || 0)
              if (value > 0.2) return '#2FA39A'
              if (value < -0.2) return '#E8656F'
              return '#9B95A5'
            },
          },
        }],
      }, true)
    }

    if (item.key === 'msg_frequency') {
      const frequency = buildMessageFrequencyBuckets()
      chart.setOption({
        ...buildChartBaseOption(),
        xAxis: { ...(buildChartBaseOption().xAxis as object), data: frequency.labels },
        yAxis: { ...(buildChartBaseOption().yAxis as object), minInterval: 1 },
        series: [{
          type: 'bar',
          data: frequency.values,
          barWidth: '45%',
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: '#5A4BC4',
          },
        }],
      }, true)
    }

    if (item.key === 'emotion_dist') {
      const distribution = [
        { value: emotionHistory.value.filter(point => point.polarity > 0).length, name: '正面' },
        { value: emotionHistory.value.filter(point => point.polarity === 0).length, name: '中性' },
        { value: emotionHistory.value.filter(point => point.polarity < 0).length, name: '负面' },
      ]
      chart.setOption({
        tooltip: {
          trigger: 'item',
          backgroundColor: '#FFFFFF',
          borderColor: '#E9E5DF',
          textStyle: { color: '#1B1924', fontSize: 12 },
        },
        series: [{
          type: 'pie',
          radius: ['38%', '68%'],
          center: ['50%', '54%'],
          label: { color: '#5A5566', fontSize: 10 },
          data: distribution,
          itemStyle: {
            borderColor: '#FFFFFF',
            borderWidth: 2,
          },
          color: ['#2FA39A', '#9B95A5', '#E8656F'],
        }],
      }, true)
    }

    if (item.key === 'reply_gap') {
      const gapData = buildReplyGapData()
      chart.setOption({
        ...buildChartBaseOption(),
        xAxis: { ...(buildChartBaseOption().xAxis as object), data: gapData.labels },
        yAxis: {
          ...(buildChartBaseOption().yAxis as object),
          axisLabel: { fontSize: 10, formatter: '{value}s' },
        },
        series: [{
          type: 'line',
          data: gapData.values,
          smooth: true,
          symbolSize: 5,
          lineStyle: { width: 2, color: '#E0A458' },
          itemStyle: { color: '#E0A458' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(224,164,88,0.26)' },
              { offset: 1, color: 'rgba(224,164,88,0.03)' },
            ]),
          },
        }],
      }, true)
    }

    if (item.key === 'msg_ratio') {
      chart.setOption({
        tooltip: {
          trigger: 'item',
          backgroundColor: '#FFFFFF',
          borderColor: '#E9E5DF',
          textStyle: { color: '#1B1924', fontSize: 12 },
        },
        series: [{
          type: 'pie',
          radius: ['42%', '70%'],
          center: ['50%', '54%'],
          label: { color: '#5A5566', fontSize: 10 },
          data: [
            { value: computedChartStats.value.self_msg_count, name: '我' },
            { value: computedChartStats.value.friend_msg_count, name: '对方' },
          ],
          itemStyle: {
            borderColor: '#FFFFFF',
            borderWidth: 2,
          },
          color: ['#5A4BC4', '#E0A458'],
        }],
      }, true)
    }

    if (item.key === 'intensity_heat') {
      chart.setOption({
        ...buildChartBaseOption(),
        xAxis: {
          ...(buildChartBaseOption().xAxis as object),
          data: emotionHistory.value.map(point => point.time),
        },
        yAxis: {
          ...(buildChartBaseOption().yAxis as object),
          min: 0,
          max: 1,
        },
        series: [{
          type: 'bar',
          data: emotionHistory.value.map(point => Number(point.intensity || 0)),
          barWidth: '55%',
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: (params: any) => {
              const value = Number(params.data || 0)
              if (value >= 0.75) return '#E8656F'
              if (value >= 0.45) return '#E0A458'
              return '#5A4BC4'
            },
          },
        }],
      }, true)
    }
  }
}

// ========== 轮询 ==========
function startPolling() {
  stopPolling()

  let notMonitoringCount = 0  // 连续未在监听的计数
  let lastMessageCount = -1   // 记录上次的消息数量
  let unchangedCount = 0      // 消息数量未变的轮询次数

  // 状态轮询
  statusTimer = setInterval(async () => {
    try {
      await bridgeReady()
      const s = await api.get_realtime_status()
      console.log('[FloatingPanel] 状态轮询:', JSON.stringify({
        is_monitoring: s.is_monitoring,
        message_count: s.message_count,
        batch_id: s.batch_id?.slice(0, 8),
      }))
      if (s.ok) {
        realtimeState.isMonitoring = s.is_monitoring
        realtimeState.messageCount = s.message_count || 0
        chatReady.value = !!s.chat_ready
        pollFailCount = 0  // 成功则重置失败计数

        // 检测断流：polling_alive 为 false 表示后端轮询线程已死亡
        if (s.polling_alive === false && s.is_monitoring) {
          connectionLost.value = true
        } else if (s.polling_alive !== false) {
          connectionLost.value = false
        }

        // 检测 ChatWith 错误
        if (s.chat_error) {
          chatError.value = s.chat_error
        } else if (s.chat_ready) {
          chatError.value = ''
        }
        if (!s.is_monitoring) {
          notMonitoringCount++
          // 连续 2 次检测到未在监听才退出（避免偶发抖动）
          if (notMonitoringCount >= 2) {
            console.warn('[FloatingPanel] 连续检测到未在监听，退出悬浮模式')
            goBackToSuggestions()
          }
        } else {
          notMonitoringCount = 0
        }
      } else {
        pollFailCount++
        if (pollFailCount >= 3) {
          connectionLost.value = true
        }
      }
    } catch (e) { console.error('状态轮询失败:', e) }
  }, 2000)

  // 消息轮询
  messagesTimer = setInterval(async () => {
    if (!realtimeState.batchId) {
      console.warn('[FloatingPanel] 消息轮询: batchId 为空，跳过')
      return
    }
    try {
      await bridgeReady()
      const r = await api.get_realtime_messages(realtimeState.batchId, 50)
      console.log('[FloatingPanel] 消息轮询:', r.ok ? `${(r.messages||[]).length} 条` : '失败')
      if (r.ok) {
        const prevLen = realtimeState.messages.length
        realtimeState.messages = r.messages || []
        updateEmotionHistory()

        // --- 动态联想词逻辑 ---
        if (lastMessageCount !== -1) {
          if (realtimeState.messages.length > lastMessageCount) {
            // 有新消息，重置停顿计数
            unchangedCount = 0
          } else {
            // 消息数量没变，增加停顿计数
            unchangedCount++
          }
          
          // 如果停顿了 2 次轮询（约 6 秒），并且之前有新消息触发，则请求新的联想词
          if (unchangedCount === 2 && !llmError.value) {
             const promptRes = await api.get_dynamic_quick_prompts(realtimeState.batchId)
             if (promptRes.ok && promptRes.prompts && promptRes.prompts.length > 0) {
               llmError.value = ''
               // 避免不必要的更新
               if (quickPrompts.value.join('') !== promptRes.prompts.join('')) {
                 quickPrompts.value = promptRes.prompts
               }
             } else if (!promptRes.ok && promptRes.error) {
               console.error('[FloatingPanel] 动态联想词获取失败:', promptRes.error)
               handleLlmError(promptRes.error)
             }
          }
        }
        lastMessageCount = realtimeState.messages.length
      }
    } catch (e) { console.error('消息轮询失败:', e) }
  }, 3000)

  // 建议轮询
  suggestionsTimer = setInterval(async () => {
    if (!realtimeState.batchId) return
    try {
      await bridgeReady()
      api.get_realtime_recent_messages(realtimeState.batchId, 12, activeAccountWxid.value || undefined)
        .then((mr: any) => {
          if (!mr?.ok || !Array.isArray(mr.messages)) return
          mergeEchoMessages(mr.messages)
        })
        .catch(() => {})
      const r = await api.get_pending_suggestions(realtimeState.batchId, activeAccountWxid.value || undefined)
      if (r.ok) {
        let addedNew = false
        const revSuggestions = [...(r.suggestions || [])].reverse()
        
        revSuggestions.forEach((s: any) => {
          if (s.id && processedSuggestionIds.has(s.id)) return
          if (s.id) processedSuggestionIds.add(s.id)
          
          if (s.summary === '[SILENT]') return
          
          addedNew = true
          // 分拣气泡与卡片
          if (s.summary === '[PURE_CHAT]') {
             if (s.reply) {
               conversationHistory.value.push({ role: 'ai', content: s.reply, ts: Math.floor(toMs(s.created_at)/1000) })
             }
          } else {
             // 守护解析：一条脏 speeches（截断/非 JSON 旧数据）裸 parse 会
             // 冒泡中止本 tick 整段建议分拣与后续 emotionSummary 更新
             const parsedSpeeches = parseSuggestionSpeeches(s.speeches)
             pendingSuggestions.value.push({ ...s, speeches: parsedSpeeches, _expanded: false, _type: 'suggestion' })
             if (s.reply) {
               conversationHistory.value.push({ role: 'ai', content: s.reply, ts: Math.floor(toMs(s.created_at)/1000) })
             }
          }
        })
        
        emotionSummary.value = r.emotion_summary || null
        // 有新建议时自动滚底
        if (addedNew) {
          await nextTick()
          scrollToBottom()
        }
      }
    } catch (e) { console.error('建议轮询失败:', e) }
  }, 3000)
}

function stopPolling() {
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null }
  if (messagesTimer) { clearInterval(messagesTimer); messagesTimer = null }
  if (suggestionsTimer) { clearInterval(suggestionsTimer); suggestionsTimer = null }
}

// ========== 实时消息推送（后端 evaluate_js 即时上屏，轮询作对账兜底） ==========

// 回显合并（推送与 3s 轮询共用；按数字 id 幂等去重，两者并存不重复）
function mergeEchoMessages(items: any[]) {
  for (const m of items) {
    if (!m?.id || echoedMessageIds.has(m.id)) continue
    echoedMessageIds.add(m.id)
    liveEchoMessages.value.push({
      _type: 'live_msg', id: m.id, sender_attr: m.sender_attr,
      content: m.content, ts: m.timestamp,
    })
    setTimeout(scrollToBottom, 50)
  }
}

// payload: [{batch_id, account_wxid, messages}]（与 get_realtime_recent_messages 项同形状）
function handleRealtimePush(e: Event) {
  const payload = (e as CustomEvent).detail
  if (!Array.isArray(payload) || !realtimeState.batchId) return
  for (const evt of payload) {
    if (evt?.batch_id !== realtimeState.batchId) continue
    mergeEchoMessages(Array.isArray(evt.messages) ? evt.messages : [])
  }
}

// ========== 情绪历史更新 ==========
function updateEmotionHistory() {
  const msgs = realtimeState.messages
    .filter(msg => msg.sender_attr === 'friend' && msg.sentiment)

  const newHistory = msgs.map((msg) => {
    const date = new Date(Number(msg.timestamp) * 1000)
    return {
      time: date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      polarity: Number(msg.sentiment?.polarity || 0),
      sender: msg.sender_attr || 'friend',
      content: msg.content || '',
      intensity: Number(msg.sentiment?.intensity || 0),
      confidence: Number(msg.sentiment?.confidence || 0),
      timestamp: Number(msg.timestamp || 0),
    }
  })

  emotionHistory.value = newHistory.slice(-20)
  syncCharts()
}

// ========== 建议配置（按联系人存储：以当前监听会话号为读写维度） ==========
async function loadSuggestionConfig() {
  try {
    const r = await api.get_suggestion_config(realtimeState.conversationId || undefined)
    if (r.ok && r.config) {
      triggerMode.value = r.config.trigger_mode || 'semi_auto'
      intent.value = r.config.intent || 'maintain'
    }
  } catch (e) { console.error('加载建议配置失败:', e) }
}

async function setTriggerMode(mode: string) {
  triggerMode.value = mode as any
  try { await api.set_suggestion_config({ trigger_mode: mode }, realtimeState.conversationId || undefined) }
  catch (e) { console.error('设置触发模式失败:', e) }
}

async function setIntent(newIntent: string) {
  intent.value = newIntent as any
  try { await api.set_suggestion_config({ intent: newIntent }, realtimeState.conversationId || undefined) }
  catch (e) { console.error('设置走向失败:', e) }
  // 走向切换可能触发新一轮建议生成——延时滚动让新内容可见
  setTimeout(scrollToBottom, 500)
}

// ========== 模型配置 ==========
async function loadLlmModels() {
  try {
    const res = await api.get_llm_models()
    if (res.ok && res.models) {
      llmModels.value = res.models
      const active = res.models.find((m: any) => m.is_active)
      if (active) {
        activeModelId.value = active.id
      }
    }
  } catch (e) {
    console.error('加载 LLM 模型列表失败:', e)
  }
}

async function switchModel() {
  if (!activeModelId.value) return
  try {
    await api.save_llm_model({ id: activeModelId.value, is_active: 1 })
    llmError.value = '' // 切换模型后清除错误状态
    // 如果有快速联想失败的，重试一次
    // 注意：lastMessageCount 是局部变量，这里我们只需清空历史就可以强制重新触发
    conversationHistory.value = []
  } catch (e) {
    console.error('切换模型失败:', e)
  }
}

function handleLlmError(errorMsg: string) {
  llmError.value = errorMsg
  if (activeModelId.value) {
    disabledModels.value.add(activeModelId.value)
    disabledModels.value = new Set(disabledModels.value)
  }
}

// ========== AI 建议操作 ==========
const thinkingSeconds = ref(0)
const streamPreview = ref('')
const streamStageText = ref('')
let thinkingTimer: any = null

function __startThinkingTimer() {
  thinkingSeconds.value = 0
  if (thinkingTimer) clearInterval(thinkingTimer)
  thinkingTimer = setInterval(() => {
    thinkingSeconds.value++
  }, 1000)
}

function __stopThinkingTimer() {
  if (thinkingTimer) {
    clearInterval(thinkingTimer)
    thinkingTimer = null
  }
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function resetSuggestionStreamUi() {
  streamPreview.value = ''
  streamStageText.value = ''
}

function applyStreamEvent(event: any) {
  if (!event || typeof event !== 'object') return
  if (event.type === 'stage') {
    const message = String(event.message || '').trim()
    const stage = String(event.stage || '').trim()
    streamStageText.value = message || stage || 'AI 分析中'
  } else if (event.type === 'delta') {
    const text = String(event.text || '')
    if (!text) return
    streamPreview.value = (streamPreview.value + text).slice(-1200)
  } else if (event.type === 'error') {
    streamStageText.value = String(event.message || '生成失败')
  }
}

async function generateSuggestionWithStream(context: Record<string, any>) {
  const started = await api.start_suggestion_stream(intent.value, context)
  if (!started?.ok || !started.stream_id) {
    return await api.generate_suggestion(intent.value, context)
  }

  let cursor = 0
  let lastResult: any = null
  for (;;) {
    await sleep(220)
    const chunk = await api.get_suggestion_stream(started.stream_id, cursor)
    if (!chunk?.ok) {
      throw new Error(chunk?.error || 'stream 获取失败')
    }
    const events = Array.isArray(chunk.events) ? chunk.events : []
    events.forEach(applyStreamEvent)
    cursor = Number(chunk.next_cursor ?? cursor)
    if (chunk.done) {
      lastResult = chunk.result || { ok: false, error: chunk.error || '生成失败' }
      break
    }
  }
  return lastResult || { ok: false, error: '生成失败' }
}

function appendSuggestionResult(r: any) {
  if (!r?.ok || !r.suggestion) return false
  if (r.suggestion.reply) {
    conversationHistory.value.push({
      role: 'ai',
      content: r.suggestion.reply,
      ts: Math.floor(Date.now() / 1000),
      rag_context: r.suggestion.rag_context,
    })
  }
  manualSuggestion.value = r.suggestion
  if (r.suggestion.summary !== '[PURE_CHAT]' && r.suggestion.summary !== '[SILENT]') {
    const parsedSpeeches = parseSuggestionSpeeches(r.suggestion.speeches)
    pendingSuggestions.value.push({ ...r.suggestion, speeches: parsedSpeeches })
  }
  expandedIds.value.add(String(r.suggestion.id || 'manual'))
  expandedIds.value = new Set(expandedIds.value)
  if (r.context_used?.recent_messages) {
    contextUsed.value = r.context_used.recent_messages
  }
  return true
}

async function manualGenerate() {
  loading.value = true
  __startThinkingTimer()
  resetSuggestionStreamUi()
  llmError.value = ''
  try {
    await bridgeReady()
    const r = await generateSuggestionWithStream({
      user_context: conversationHistory.value.length ? conversationHistory.value : undefined,
      historical_context: buildHistoricalContext(),
    })
    if (r.ok && r.suggestion) {
      appendSuggestionResult(r)
      nextTick(() => scrollToBottom())  // AI 回复入列后滚动
    } else {
      loading.value = false
      __stopThinkingTimer()
      handleLlmError(r.error || '生成失败')
      return
    }
  } catch (e: any) { 
    console.error('手动生成失败:', e) 
    handleLlmError(e.message || '网络错误')
  }
  finally { 
    loading.value = false
    __stopThinkingTimer()
    resetSuggestionStreamUi()
    await nextTick()
    scrollToBottom()
  }
}

/** 自动滚动建议列表到底部 */
function scrollToBottom() {
  // .fp-scroll-area 自身即滚动容器（此前 querySelector 查的类名不存在）
  const listEl = suggestionsRef.value
  if (listEl) {
    listEl.scrollTop = listEl.scrollHeight
  }
}

function toggleSuggestion(s: any) {
  const id = String(s.id || 'manual')
  const wasExpanded = expandedIds.value.has(id)
  if (wasExpanded) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
  // 触发响应式更新
  expandedIds.value = new Set(expandedIds.value)
  // 展开时滚动让卡片可见（内容撑高可能超出视口）
  if (!wasExpanded) {
    nextTick(() => {
      const el = suggestionsRef.value?.querySelector(`[data-sid="${id}"]`)
      if (el) {
        (el as HTMLElement).scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      } else {
        scrollToBottom()
      }
    })
  }
}

function isSuggestionExpanded(s: any): boolean {
  return expandedIds.value.has(String(s.id || 'manual'))
}

const copiedSpeechKey = ref('')
let speechCopyTimer: ReturnType<typeof setTimeout> | null = null

function handleCopySpeech(text: string, s: any, index: number) {
  if (!copyText(text)) return
  copiedSpeechKey.value = `${s.id || s._tempId}-${index}`
  if (speechCopyTimer) clearTimeout(speechCopyTimer)
  speechCopyTimer = setTimeout(() => { copiedSpeechKey.value = '' }, 2000)
}

function getRagBadge(ragContext: RagContextSummary | undefined | null): RagContextSummary | null {
  if (!ragContext || ragContext.state === 'hidden' || !ragContext.label) return null
  const allowedStates = [
    'no_hit', 'referenced', 'not_referenced',
    'fact_hit', 'document_hit', 'relationship_policy', 'hot_context', 'degraded',
  ]
  if (!allowedStates.includes(String(ragContext.state))) return null
  return ragContext
}

// 记忆管理弹窗（直接复用 RagFactDialog 组件）
const ragDetail = reactive<{ visible: boolean; logId: number | null }>({
  visible: false,
  logId: null,
})

const userAvatar = ref('')
const avatarLoadErrors = reactive<Record<string, boolean>>({})

function getBubbleAvatar(isSelf: boolean): string {
  return isSelf ? userAvatar.value : contactAvatar.value
}

async function resolveUserAvatar() {
  try {
    await bridgeReady()
    const uRes = await api.get_current_user_profile(activeAccountWxid.value || '')
    if (uRes?.ok && uRes?.profile?.avatar) {
      userAvatar.value = String(uRes.profile.avatar).trim()
    }
  } catch {}
}

function canOpenRagDetail(rc?: RagContextSummary | null): boolean {
  return !!(rc && rc.log_id)
}

function openRagDetail(rc?: RagContextSummary | null) {
  if (!canOpenRagDetail(rc) || !rc?.log_id) return
  ragDetail.logId = Number(rc.log_id)
  ragDetail.visible = true
}

function closeRagDetail() {
  ragDetail.visible = false
  ragDetail.logId = null
}

const triggerIconComponents: Record<string, any> = {
  negative_streak: AlertCircle,
  emotion_shift: Zap,
  perfunctory: Moon,
  silence: VolumeX,
  positive_window: Sparkles,
  topic_cooling: Snowflake,
}

function getTriggerIconComponent(type: string): any {
  return triggerIconComponents[type] || Pin
}

// ========== 用户交互 ==========
async function sendUserContext() {
  const content = userInput.value.trim()
  if (!content || loading.value || !!llmError.value) return

  conversationHistory.value.push({ role: 'user', content, ts: Math.floor(Date.now() / 1000) })
  userInput.value = ''
  loading.value = true
  nextTick(() => scrollToBottom())  // 用户消息/快速联想入列后立即滚到底
  __startThinkingTimer()
  resetSuggestionStreamUi()
  llmError.value = ''

  try {
    await bridgeReady()
    const r = await generateSuggestionWithStream({
      user_context: conversationHistory.value.map(c => ({ role: c.role, content: c.content })),
      include_history: true,
      historical_context: buildHistoricalContext(),
    })
    if (r.ok && r.suggestion) {
      appendSuggestionResult(r)
      nextTick(() => scrollToBottom())  // AI 回复入列后滚动
    } else {
      conversationHistory.value.push({ role: 'ai', content: `[生成失败] ${r.error || '未知错误'}`, ts: Math.floor(Date.now() / 1000) })
      nextTick(() => scrollToBottom())
      handleLlmError(r.error || '生成失败')
    }
  } catch (e: any) {
    console.error('发送失败:', e)
    conversationHistory.value.push({ role: 'ai', content: `[系统错误] ${e.message || '网络或接口故障'}`, ts: Math.floor(Date.now() / 1000) })
    handleLlmError(e.message || '系统错误')
  } finally {
    loading.value = false
    __stopThinkingTimer()
    resetSuggestionStreamUi()
    // 自动滚动到底部
    await nextTick()
    scrollToBottom()
  }
}

/** 格式化消息时间 */
function formatMsgTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function sendQuickPrompt(prompt: string) {
  userInput.value = prompt
  sendUserContext()
}

/** 断流后重试连接 */
async function retryConnection() {
  connectionLost.value = false
  pollFailCount = 0
  chatError.value = ''
  try {
    await bridgeReady()
    const s = await api.get_realtime_status()
    if (s.ok && s.is_monitoring) {
      realtimeState.isMonitoring = true
      realtimeState.messageCount = s.message_count || 0
      if (s.chat_error) {
        chatError.value = s.chat_error
      }
    } else {
      // 监听已完全停止，退回建议页
      goBackToSuggestions()
    }
  } catch (e) {
    console.error('重试连接失败:', e)
    connectionLost.value = true
  }
}

// ========== 画像 ==========
async function resolveContactAvatar(displayName: string) {
  void resolveUserAvatar()
  const name = String(displayName || '').trim()
  if (!name) {
    contactAvatar.value = ''
    return
  }

  try {
    await bridgeReady()
    const result = await api.get_conversation_list(activeAccountWxid.value || undefined)
    const conversations = result?.conversations || []
    const matched = conversations.find((item: any) => {
      return item?.name === name || item?.username === name
    })
    contactAvatar.value = String(matched?.avatar || '').trim()
  } catch (e) {
    console.error('加载联系人头像失败:', e)
  }
}

async function checkContactProfile(name: string) {
  if (!name) return
  try {
    await bridgeReady()
    const r = await api.get_contact_profile(name, activeAccountWxid.value || undefined)
    if (r.ok && r.has_profile && !r.expired) {
      profile.value = { name, ...r.profile }
    } else {
      profile.value = { name, tags: [] }
    }
  } catch (e) { console.error('检查画像失败:', e) }
}

async function generateProfile() {
  showProfileDialog.value = false
  profileLoading.value = true
  try {
    await bridgeReady()
    const r = await api.generate_contact_profile(
      realtimeState.talkerName,
      'medium',
      0,
      activeAccountWxid.value || undefined,
    )
    if (r.ok && r.profile) {
      profile.value = { name: realtimeState.talkerName, ...r.profile }
    }
  } catch (e) { console.error('生成画像失败:', e) }
  finally { profileLoading.value = false }
}

// ========== 继承上次会话 ==========
async function loadLastThread() {
  if (!lastThread.value) return
  try {
    await bridgeReady()
    const r = await api.load_thread_context(lastThread.value.id)
    // 兼容后端可能返回 r.data 或 r.context
    const threadData = r.data || r.context
    if (r.ok && threadData) {
      if (threadData.suggestions && threadData.suggestions.length > 0) {
        // 分拣
        const loadedSuggs: any[] = []
        const loadedChats: any[] = []
        threadData.suggestions.forEach((s: any) => {
          if (s.id) processedSuggestionIds.add(s.id)
          if (s.summary === '[SILENT]') return
          
          if (s.summary !== '[PURE_CHAT]') {
             // 守护解析（1137 行助手）：裸 parse 一条脏 JSON 即中止整个
             // 继承流程，用户重开会话看不到上次记录且无任何提示
             const parsedSpeeches = parseSuggestionSpeeches(s.speeches)
             loadedSuggs.push({ ...s, speeches: parsedSpeeches, _type: 'suggestion' })
          }
        })
        
        pendingSuggestions.value = loadedSuggs
        // 直接从快照恢复完整的与 AI 聊天气泡记录
        if (threadData.user_chat_history && Array.isArray(threadData.user_chat_history)) {
          conversationHistory.value = threadData.user_chat_history
        } else {
          conversationHistory.value = []
        }
        
        if (threadData.messages && threadData.messages.length > 0) {
          contextUsed.value = threadData.messages
        }
      }
      
      // 取消横幅
      lastThread.value = null
      setTimeout(scrollToBottom, 200)
    } else {
      lastThread.value = null
      console.warn('[loadLastThread] 接口返回失败:', r)
    }
  } catch (e: any) {
    console.error('加载上次会话失败:', e)
    lastThread.value = null
  }
}
</script>

<style scoped>
/* Scoped Reset to prevent any global button/flex hijacking */
.fp-layout, .fp-layout * {
  box-sizing: border-box;
}
.fp-layout button {
  width: auto;
  min-height: unset;
  max-width: 100%;
}

/* Workbench Structural Layout */
.fp-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--ct-bg-app);
  font-family: var(--ct-font-body);
}

.fp-workbench-container {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: 100%;
  overflow: hidden;
}

.fp-main-column {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.fp-main-stack { 
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
  background: var(--ct-bg-sunken);
  width: 100%;
}

/* Base Buttons */
.fp-btn-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  height: 22px;
  border-radius: 999px;
  background: var(--ct-color-primary-muted);
  color: var(--ct-color-primary);
  border: 1px solid color-mix(in srgb, var(--ct-color-primary) 22%, transparent);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  -webkit-app-region: no-drag;
  transition: all 0.15s ease;
}
.fp-btn-back:hover {
  background: var(--ct-color-primary-subtle);
  border-color: color-mix(in srgb, var(--ct-color-primary) 35%, transparent);
}

.fp-btn-icon {
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--ct-text-tertiary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: var(--ct-radius-sm, 6px);
  transition: all 0.15s;
}
.fp-btn-icon:hover {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-primary);
}
.fp-btn-sm {
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: var(--ct-radius-sm, 6px);
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
  border: 1px solid color-mix(in srgb, var(--ct-color-primary) 22%, transparent);
  cursor: pointer;
}
.fp-btn-base {
  font-size: 12.5px;
  font-weight: 500;
  padding: 6px 14px;
  border-radius: var(--ct-radius-md, 8px);
  cursor: pointer;
  border: none;
  transition: all 0.15s;
}
.fp-btn-base.primary {
  background: var(--ct-color-primary);
  color: white;
}
.fp-btn-base.primary:hover {
  background: var(--ct-color-primary-hover);
}
.fp-btn-base.ghost {
  background: transparent;
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
}
.fp-btn-text {
  font-size: 11px;
  font-weight: 500;
  color: var(--ct-color-primary);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
}
.fp-btn-text:hover {
  text-decoration: underline;
}

/* 1. Header (Compact 2-Tier Design) */
.fp-site-header {
  background: var(--ct-bg-card);
  border-bottom: 1px solid var(--ct-border-color);
  flex-shrink: 0;
  position: relative;
  z-index: 10;
  box-shadow: var(--ct-shadow-sm);
}
.fp-header-drag-zone {
  height: 34px;
  padding: 0 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  -webkit-app-region: drag;
  cursor: move;
  user-select: none;
}
.fp-brand {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.fp-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ct-text-tertiary);
  transition: all 0.2s;
}
.fp-status-dot.active {
  background: var(--ct-color-success);
  box-shadow: 0 0 6px color-mix(in srgb, var(--ct-color-success) 60%, transparent);
}
.fp-brand-name {
  font-family: var(--ct-font-body);
  font-size: 12px;
  font-weight: 700;
  color: var(--ct-text-primary, #1e293b);
  white-space: nowrap;
  letter-spacing: -0.2px;
}
.fp-brand-pulse-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ct-color-success-tint);
  color: var(--ct-color-success);
  line-height: 1.1;
}

.fp-contact-bar {
  height: 44px;
  padding: 0 10px 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  -webkit-app-region: no-drag;
  cursor: pointer;
  user-select: none;
}
.fp-avatar {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 8px;
  background: var(--ct-bg-sunken);
  color: var(--ct-color-primary);
  font-weight: 700;
  font-size: 13px;
}
.fp-contact-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 1px;
}
.fp-contact-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.fp-contact-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ct-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: calc(100% - 48px);
  line-height: 1.25;
}
.fp-monitor-tag {
  font-size: 9.5px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
  line-height: 1.15;
}
.fp-monitor-tag.active {
  background: var(--ct-color-success-tint);
  color: var(--ct-color-success);
}
.fp-contact-sub-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.fp-contact-tags {
  display: flex;
  gap: 4px;
  align-items: center;
  overflow: hidden;
}
.fp-tag {
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
  line-height: 1.2;
}
.fp-tag.more {
  color: var(--ct-color-primary);
  border-color: color-mix(in srgb, var(--ct-color-primary) 20%, transparent);
}
.fp-contact-empty-hint {
  font-size: 10px;
  color: var(--ct-text-tertiary);
}
.profile-toggle {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--ct-text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform 0.2s ease, background 0.15s;
}
.profile-toggle:hover {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-primary);
}
.profile-toggle.is-open {
  transform: rotate(180deg);
}

/* Absolute Profile Dropdown */
.fp-profile-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: var(--ct-bg-card);
  border-bottom: 1px solid var(--ct-border-color);
  box-shadow: var(--ct-shadow-lg);
  padding: 12px;
  z-index: 20;
}
.all-tags { margin-bottom: 10px; }
.fp-attr { display: flex; gap: 8px; font-size: 12px; line-height: 1.5; margin-bottom: 6px; }
.fp-attr-lbl { color: var(--ct-text-primary); font-weight: 600; flex-shrink: 0; }
.fp-attr-val { color: var(--ct-text-secondary); word-break: break-word; }
.fp-profile-empty { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-top: 1px dashed var(--ct-border-color); }
.fp-txt-sub { font-size: 11px; color: var(--ct-text-tertiary); }

/* Banners */
.fp-banners { flex-shrink: 0; z-index: 8; position: relative; }
.fp-banner { display: flex; justify-content: space-between; align-items: center; padding: 7px 10px; font-size: 11px; font-weight: 500; }
.fp-banner.error { background: var(--ct-color-error-tint); color: var(--ct-color-error); border-bottom: 1px solid color-mix(in srgb, var(--ct-color-error) 30%, transparent); }
.fp-banner.info { background: var(--ct-color-primary-tint); color: var(--ct-color-primary); border-bottom: 1px solid color-mix(in srgb, var(--ct-color-primary) 30%, transparent); }

/* 2. Compact Insights & Memory Ribbon */
.fp-insights-strip {
  height: 32px;
  padding: 0 10px;
  background: var(--ct-bg-card);
  border-bottom: 1px solid var(--ct-border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
  position: relative;
  z-index: 7;
}
.fp-insight-primary {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  cursor: pointer;
}
.fp-trend-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}
.fp-trend-badge.positive { background: var(--ct-color-success-tint); color: var(--ct-color-success); }
.fp-trend-badge.negative { background: var(--ct-color-error-tint); color: var(--ct-color-error); }
.fp-trend-badge.neutral { background: var(--ct-bg-sunken); color: var(--ct-text-secondary); }
.fp-insight-text {
  font-size: 11px;
  color: var(--ct-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.fp-insight-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.fp-ribbon-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 7px;
  height: 22px;
  border-radius: 5px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-card);
  color: var(--ct-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
  flex-shrink: 0;
}
.fp-ribbon-btn:hover {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-muted);
}
.fp-ribbon-btn.has-rag {
  border-color: color-mix(in srgb, var(--ct-color-primary) 35%, transparent);
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
}
.fp-ribbon-btn.active {
  background: var(--ct-color-primary);
  color: #ffffff;
  border-color: var(--ct-color-primary);
}

/* 3. SHARED INSPECTOR PANEL */
/* 检查器浮层：teleport 到 body，浅色 chrono 主题（遮罩对齐全局 .ct-modal-overlay） */
.fp-inspector-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(27, 25, 36, 0.45);
  backdrop-filter: blur(2px);
  display: flex; align-items: flex-end;
  opacity: 0; pointer-events: none; transition: opacity 0.18s ease;
}
.fp-inspector-overlay.is-visible {
  opacity: 1; pointer-events: auto;
}
/* 分屏模式：teleport 回布局内（在滚动区与交互区之间），不遮挡交互区 */
.fp-inspector-overlay.is-docked {
  position: static;
  background: transparent;
  backdrop-filter: none;
  pointer-events: auto;
  opacity: 1;
  flex-shrink: 0;
  height: clamp(180px, 38%, 260px);
}
.fp-inspector-overlay.is-docked .fp-inspector {
  height: 100%;
  transform: none;
  border-radius: var(--ct-radius-lg);
  border: 1px solid var(--ct-border-color);
}
.fp-inspector {
  width: 100%; height: 72%;
  display: flex; flex-direction: column;
  background: var(--ct-bg-card); color: var(--ct-text-primary);
  border-top: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg) var(--ct-radius-lg) 0 0;
  box-shadow: 0 -8px 24px rgba(27, 25, 36, 0.08);
  transform: translateY(100%); transition: transform 0.22s ease;
}
.fp-inspector-overlay.is-visible .fp-inspector { transform: translateY(0); }
.fp-inspector-header { display: flex; justify-content: space-between; align-items: center; padding: 3px 8px; border-bottom: 1px solid var(--ct-border-color); background: var(--ct-bg-card); gap: 6px; }
.fp-inspector-title { font-size: 13px; font-weight: 600; color: var(--ct-text-secondary); }
.fp-inspector-tabs { display: flex; gap: 6px; min-width: 0; flex: 1; align-items: center; }
.fp-dock-toggle {
  font-size: 11px; font-weight: 600;
  color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
  border: 1px solid color-mix(in srgb, var(--ct-color-primary) 30%, transparent);
  padding: 3px 10px; border-radius: 999px;
  cursor: pointer; white-space: nowrap;
  transition: all 0.15s ease;
}
.fp-dock-toggle:hover {
  background: var(--ct-color-primary-subtle);
  border-color: color-mix(in srgb, var(--ct-color-primary) 50%, transparent);
}
.fp-inspector-close { margin-left: auto; color: var(--ct-text-secondary); }
.fp-inspector-close:hover { color: var(--ct-text-primary); }
.fp-tab-btn { background: var(--ct-bg-sunken); border: 1px solid transparent; font-size: 11px; font-weight: 600; color: var(--ct-text-secondary); cursor: pointer; padding: 2px 8px; border-radius: 4px; transition: all 0.2s; white-space: nowrap; }
.fp-tab-btn.active { color: var(--ct-color-primary); border-color: color-mix(in srgb, var(--ct-color-primary) 22%, transparent); background: var(--ct-color-primary-tint); }
.fp-inspector-body { flex: 1; overflow-y: auto; padding: 0; background: var(--ct-bg-sunken); display: flex; flex-direction: column; }
.fp-inspector-body::-webkit-scrollbar { width: 6px; }
.fp-inspector-body::-webkit-scrollbar-thumb { background: var(--ct-border-color-hover); border-radius: 4px; }
.fp-inspector-tab-content { display: flex; flex-direction: column; height: 100%; }

/* Chart Sub-Tab */
.compact-charts-config { display: flex; flex-wrap: nowrap; gap: 4px; padding: 4px 8px; background: var(--ct-bg-card); border-bottom: 1px solid var(--ct-border-color); overflow-x: auto; scrollbar-width: none; }
.compact-charts-config::-webkit-scrollbar { display: none; }
.fp-chart-toggle { display: inline-flex; align-items: center; gap: 2px; font-size: 10px; color: var(--ct-text-secondary); cursor: pointer; white-space: nowrap; padding: 2px 6px; border: 1px solid var(--ct-border-color); border-radius: 999px; background: var(--ct-bg-sunken); }
.fp-chart-stage { padding: 4px 6px 4px; }
.fp-chart-rail { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(132px, 1fr); gap: 6px; padding: 0 6px 6px; overflow-x: auto; overscroll-behavior-x: contain; }
.fp-chart-rail::-webkit-scrollbar { height: 6px; }
.fp-chart-rail::-webkit-scrollbar-thumb { background: var(--ct-border-color-hover); border-radius: 999px; }
.fp-chart-item { background: var(--ct-bg-card); border-radius: var(--ct-radius-md); display: flex; flex-direction: column; box-shadow: var(--ct-shadow-sm); overflow: hidden; min-height: 0; }
.fp-chart-item.emotion-curve-main { aspect-ratio: auto; }
.fp-chart-item.compact-main { height: 124px; }
.fp-chart-item.compact-secondary { height: 108px; min-width: 132px; }
.fp-chart-lbl { font-size: 10.5px; font-weight: 600; color: var(--ct-text-secondary); padding: 8px 8px 0; flex-shrink: 0; }
.fp-chart-wrap { flex: 1; min-height: 0; padding: 2px 4px 4px; }

.compact-empty { font-size: 11px; color: var(--ct-text-tertiary); text-align: center; padding: 24px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100px; }
/* Context Sub-Tab */
.fp-context-meta { font-size: 10px; color: var(--ct-text-tertiary); padding: 4px 8px 0; text-align: left; }
/* RAG 缺索引提醒横幅：建议只基于近期对话时提示并引导构建 */
.fp-rag-notice {
  display: flex; align-items: flex-start; gap: 8px;
  margin: 8px 8px 2px; padding: 8px 10px;
  border-radius: 8px; text-align: left;
  background: var(--ct-color-warning-tint);
  border: 1px solid color-mix(in srgb, var(--ct-color-warning) 25%, transparent);
  color: var(--ct-color-warning);
}
.fp-rag-notice svg { flex-shrink: 0; margin-top: 1px; }
.fp-rag-notice-body { font-size: 11px; line-height: 1.6; color: var(--ct-text-secondary); }
.fp-rag-notice-btn {
  margin-left: 8px; padding: 2px 10px; border-radius: 6px;
  font-size: 11px; font-weight: 600; cursor: pointer;
  border: 1px solid color-mix(in srgb, var(--ct-color-warning) 40%, transparent); background: var(--ct-color-warning-tint);
  color: var(--ct-color-warning);
}
.fp-rag-notice-btn:hover { background: color-mix(in srgb, var(--ct-color-warning) 20%, transparent); }
.fp-rag-notice-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fp-context-empty { font-size: 12px; color: var(--ct-text-secondary); text-align: center; padding: 24px; }
.stream-layout { padding: 4px 8px 8px; display: flex; flex-direction: column; gap: 6px; }
.fp-ctx-msg { background: var(--ct-bg-card); border-radius: var(--ct-radius-sm); padding: 6px 8px; width: 96%; align-self: flex-start; box-shadow: var(--ct-shadow-sm); }
.fp-ctx-msg.self { align-self: flex-end; background: var(--ct-color-primary-tint); border-color: color-mix(in srgb, var(--ct-color-primary) 20%, transparent); }
.fp-ctx-msg-hd { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 4px; }
.fp-ctx-sender { font-size: 11px; font-weight: 600; color: var(--ct-text-secondary); }
.fp-ctx-msg.self .fp-ctx-sender { color: var(--ct-color-primary); }
.fp-ctx-time { font-size: 10px; color: var(--ct-text-tertiary); }
.fp-ctx-txt { font-size: 11px; line-height: 1.4; color: var(--ct-text-primary); word-break: break-word; white-space: pre-wrap; }

/* 5. Main Suggestion Stack */
.fp-main-stack { position: relative; min-height: 0; display: flex; flex-direction: column; background: var(--ct-bg-sunken); overflow: hidden; }
.fp-scroll-area { flex: 1; overflow-y: auto; padding: 12px 10px; }
.fp-scroll-area::-webkit-scrollbar { width: 6px; }
.fp-scroll-area::-webkit-scrollbar-thumb { background: var(--ct-border-color-hover); border-radius: 4px; }

/* Thread Banner */
.fp-thread-banner { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--ct-bg-card); border-left: 3px solid var(--ct-color-primary); border-radius: var(--ct-radius-md); margin-bottom: 12px; cursor: pointer; box-shadow: var(--ct-shadow-sm); }
.fp-thread-label { font-size: 12px; font-weight: 600; color: var(--ct-text-primary); }

/* Suggestion Cards & Chats */
.fp-empty-slate { text-align: center; padding: 32px; font-size: 12px; color: var(--ct-text-tertiary); }
.fp-sug-list { display: flex; flex-direction: column; gap: 12px; }
.fp-card { background: var(--ct-bg-card); border-radius: var(--ct-radius-lg); box-shadow: var(--ct-shadow-sm); overflow: hidden; }
.fp-card.high { border-left: 3px solid var(--ct-color-error); }
.fp-card.medium { border-left: 3px solid var(--ct-color-warning); }
.fp-card.low { border-left: 3px solid var(--ct-color-success); }
.fp-card-hd { display: flex; align-items: center; gap: 8px; padding: 12px; cursor: pointer; transition: background 0.15s; }
.fp-card-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--ct-color-primary);
}
.fp-card-time { font-size: 10px; color: var(--ct-text-tertiary); }
.fp-card-bd { padding: 0 12px 12px; border-top: 1px solid var(--ct-border-color); padding-top: 12px; background: var(--ct-bg-sunken); }
.fp-cot { background: var(--ct-bg-card); border-radius: var(--ct-radius-md); padding: 10px; margin-bottom: 12px; }
.fp-cot summary { font-size: 11px; color: var(--ct-text-secondary); cursor: pointer; user-select: none; font-weight: 600; outline: none; }
.fp-cot-txt { user-select: text; -webkit-user-select: text; font-size: 12px; line-height: 1.6; color: var(--ct-text-secondary); margin-top: 8px; border-top: 1px dashed var(--ct-border-color); padding-top: 8px; white-space: pre-wrap; }
.fp-speech-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--ct-bg-card); border-radius: var(--ct-radius-md); margin-bottom: 8px; box-shadow: var(--ct-shadow-sm); }
.fp-speech-text { font-size: 13px; line-height: 1.6; color: var(--ct-text-primary); flex: 1; user-select: text; -webkit-user-select: text; }
.fp-btn-copy { font-size: 11px; font-weight: 500; color: var(--ct-text-secondary); background: var(--ct-bg-sunken); border: 1px solid var(--ct-border-color); padding: 4px 10px; border-radius: var(--ct-radius-sm); cursor: pointer; transition: all 0.2s; flex-shrink: 0; }
.fp-btn-copy:hover { color: var(--ct-color-primary); border-color: var(--ct-color-primary); background: var(--ct-color-primary-tint); }
.fp-btn-copy.copied { color: var(--ct-color-success); border-color: var(--ct-color-success); }
.fp-rag-row { display: flex; justify-content: flex-end; margin-top: 8px; min-height: 18px; }
.fp-rag-badge { display: inline-flex; align-items: center; max-width: 100%; min-height: 18px; padding: 2px 7px; border-radius: var(--ct-radius-sm); border: 1px solid var(--ct-border-color); background: var(--ct-bg-sunken); color: var(--ct-text-tertiary); font-size: 10.5px; line-height: 1.2; font-weight: 600; white-space: nowrap; }
.fp-rag-badge.referenced { color: var(--ct-color-primary); border-color: color-mix(in srgb, var(--ct-color-primary) 28%, transparent); background: var(--ct-color-primary-tint); }
.fp-rag-badge.no_hit { color: var(--ct-text-secondary); background: var(--ct-bg-sunken); }
.fp-rag-badge.not_referenced { color: var(--ct-color-warning); border-color: color-mix(in srgb, var(--ct-color-warning) 28%, transparent); background: var(--ct-color-warning-tint); }
.fp-rag-badge.fact_hit { color: var(--ct-color-primary); border-color: color-mix(in srgb, var(--ct-color-primary) 28%, transparent); background: var(--ct-color-primary-tint); }
.fp-rag-badge.document_hit { color: var(--ct-color-primary); border-color: color-mix(in srgb, var(--ct-color-primary) 20%, transparent); background: var(--ct-color-primary-muted); }
.fp-rag-badge.relationship_policy { color: var(--ct-color-success); border-color: color-mix(in srgb, var(--ct-color-success) 28%, transparent); background: var(--ct-color-success-tint); }
.fp-rag-badge.hot_context { color: var(--ct-text-tertiary); background: var(--ct-bg-sunken); }
.fp-rag-badge.degraded { color: var(--ct-color-error); border-color: color-mix(in srgb, var(--ct-color-error) 28%, transparent); background: var(--ct-color-error-tint); }

/* RAG 注入详情弹层（与设置页「记忆管理」视觉对称） */
.fp-rag-detail-mask { position: fixed; inset: 0; z-index: 1000; background: rgba(27, 25, 36, 0.45); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; }
.fp-rag-detail { width: min(440px, calc(100vw - 24px)); max-height: min(560px, 82vh); overflow-y: auto; background: var(--ct-bg-card); border-radius: var(--ct-radius-lg); box-shadow: var(--ct-shadow-lg); padding: 14px 16px; }
.fp-rag-detail-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--ct-border-color); }
.fp-rag-detail-title-wrap { display: flex; align-items: center; gap: 8px; }
.fp-rag-detail-icon { width: 24px; height: 24px; border-radius: 7px; background: var(--ct-color-primary-tint); color: var(--ct-color-primary); display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
.fp-rag-detail-title { font-size: 13.5px; font-weight: 700; color: var(--ct-text-primary); }
.fp-rag-detail-close { border: none; background: transparent; cursor: pointer; font-size: 14px; color: var(--ct-text-tertiary); padding: 3px 7px; border-radius: 6px; transition: background 0.15s; }
.fp-rag-detail-close:hover { background: var(--ct-bg-sunken); color: var(--ct-text-primary); }
.fp-rag-detail-status { font-size: 12px; color: var(--ct-text-secondary); padding: 14px 0; text-align: center; }
.fp-rag-detail-summary-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--ct-bg-sunken); border-radius: 9px; padding: 7px 11px; margin-bottom: 12px; font-size: 11.5px; }
.fp-rag-summary-stat { color: var(--ct-text-secondary); }
.fp-rag-summary-stat strong { color: var(--ct-color-primary); font-weight: 700; }
.fp-rag-summary-meta { display: flex; align-items: center; gap: 8px; color: var(--ct-text-tertiary); font-size: 11px; }
.fp-rag-item { border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; background: var(--ct-bg-sunken); transition: opacity 0.2s, border-color 0.2s; }
.fp-rag-item.is-disabled { opacity: 0.62; background: var(--ct-bg-sunken); border-style: dashed; }
.fp-rag-item-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.fp-rag-item-chip { font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.fp-rag-item-chip.fact { color: var(--ct-color-primary); background: var(--ct-color-primary-tint); }
.fp-rag-item-chip.document { color: var(--ct-color-warning); background: var(--ct-color-warning-tint); }
.fp-rag-item-kind-pill { font-size: 10.5px; font-weight: 500; padding: 1px 7px; border-radius: 6px; background: var(--ct-bg-sunken); color: var(--ct-text-secondary); }
.fp-rag-item-status-pill { font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 6px; }
.fp-rag-item-status-pill.inaccurate { color: var(--ct-color-warning); background: var(--ct-color-warning-tint); }
.fp-rag-item-status-pill.forget { color: var(--ct-color-error); background: var(--ct-color-error-tint); }
.fp-rag-item-time { font-size: 10.5px; color: var(--ct-text-tertiary); margin-left: auto; }
.fp-rag-item-conf { font-size: 10.5px; color: var(--ct-text-tertiary); }
.fp-rag-item-content { font-size: 12.5px; line-height: 1.55; color: var(--ct-text-primary); word-break: break-word; }
.fp-rag-item-evidence { margin-top: 8px; padding-top: 7px; border-top: 1px dashed var(--ct-border-color); }
.fp-rag-item-evidence-title { font-size: 10.5px; font-weight: 600; color: var(--ct-text-tertiary); margin-bottom: 3px; }
.fp-rag-item-evidence-text { font-size: 11.5px; color: var(--ct-text-secondary); line-height: 1.45; margin-bottom: 3px; word-break: break-word; }
.fp-rag-item-actions { display: flex; align-items: center; justify-content: flex-end; gap: 6px; margin-top: 8px; padding-top: 7px; border-top: 1px solid var(--ct-border-color); }
.fp-rag-act-btn { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 6px; border: 1px solid var(--ct-border-color); background: var(--ct-bg-sunken); color: var(--ct-text-secondary); cursor: pointer; transition: all 0.15s; }
.fp-rag-act-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fp-rag-act-btn.warn:hover:not(:disabled) { color: var(--ct-color-warning); border-color: color-mix(in srgb, var(--ct-color-warning) 45%, transparent); background: var(--ct-color-warning-tint); }
.fp-rag-act-btn.danger:hover:not(:disabled) { color: var(--ct-color-error); border-color: color-mix(in srgb, var(--ct-color-error) 45%, transparent); background: var(--ct-color-error-tint); }
.fp-rag-act-btn.restore { color: var(--ct-color-primary); border-color: color-mix(in srgb, var(--ct-color-primary) 35%, transparent); background: var(--ct-color-primary-tint); }
.fp-rag-act-btn.restore:hover:not(:disabled) { background: var(--ct-color-primary-subtle); }

/* Chat Message Row & Avatar — 与 RagFactDialog 保持一致的左右头像气泡布局 */
.fp-msg-row { display: flex; align-items: flex-start; gap: 8px; width: 100%; }
.fp-msg-row.left { flex-direction: row; justify-content: flex-start; }
.fp-msg-row.right { flex-direction: row-reverse; justify-content: flex-start; }
.fp-msg-avatar { width: 32px; height: 32px; border-radius: 6px; overflow: hidden; flex-shrink: 0; background: var(--ct-bg-sunken); box-shadow: var(--ct-shadow-sm); }
.fp-msg-avatar-img, .fp-msg-avatar-svg { width: 100%; height: 100%; object-fit: cover; display: block; }

/* Chat Bubbles — 区分「微信实时消息」与「AI 军师对话」双通道 */
.fp-bubble { max-width: calc(100% - 44px); padding: 10px 13px; border-radius: 12px; background: var(--ct-bg-card); border-top-left-radius: 4px; box-shadow: var(--ct-shadow-sm); }
/* 通道 1：微信抓取消息（对方 = 白底左绿线；我 = 微信浅绿底） */
.fp-bubble.wechat-other { background: #ffffff; border: 1px solid #e2e8f0; border-left: 3px solid #07c160; border-top-left-radius: 4px; color: #1e293b; }
.fp-bubble.wechat-self { background: #e8f8ee; border: 1px solid #bbf0ce; border-top-left-radius: 12px; border-top-right-radius: 4px; color: #14532d; box-shadow: 0 1px 4px rgba(7, 193, 96, 0.08); }
/* 通道 2：用户向 AI 提问 & AI 助手回复（品牌紫体系，全站去渐变） */
.fp-bubble.ai-user { background: var(--ct-color-primary); color: #ffffff; border: none; border-top-left-radius: 12px; border-top-right-radius: 4px; box-shadow: var(--ct-shadow-md); }
.fp-bubble.ai-assistant { background: var(--ct-color-primary-tint); border: 1px solid color-mix(in srgb, var(--ct-color-primary) 28%, transparent); border-left: 3px solid var(--ct-color-primary); border-top-left-radius: 4px; color: var(--ct-text-primary); }

.fp-bubble-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 12px; }
.fp-bubble-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 5px; line-height: 1.2; }
.fp-bubble-badge.wechat-other { color: #059669; background: rgba(7, 193, 96, 0.1); }
.fp-bubble-badge.wechat-self { color: #047857; background: rgba(7, 193, 96, 0.16); }
.fp-bubble-badge.ai-user { color: #ffffff; background: rgba(255, 255, 255, 0.2); }
.fp-bubble-badge.ai-assistant { color: var(--ct-color-primary); background: var(--ct-color-primary-tint); }

.fp-bubble-time { font-size: 10px; color: var(--ct-text-tertiary); opacity: 0.85; }
.fp-bubble.wechat-self .fp-bubble-time { color: #166534; opacity: 0.75; }
.fp-bubble.ai-user .fp-bubble-time { color: rgba(255, 255, 255, 0.82); }
.fp-bubble.ai-assistant .fp-bubble-time { color: var(--ct-color-primary); opacity: 0.7; }

.fp-bubble-txt { font-size: 13.5px; line-height: 1.55; word-break: break-word; white-space: pre-wrap; user-select: text; -webkit-user-select: text; cursor: text; }
.fp-bubble .fp-rag-row { margin-top: 7px; }

/* 仿微信 4.0 引用消息块（左侧竖线 + 浅灰底 + 默认两行省略，点击展开全文） */
.fp-wechat-quote { display: flex; align-items: stretch; gap: 7px; margin-top: 6px; padding: 6px 9px; border-radius: 6px; background: rgba(15, 23, 42, 0.045); cursor: pointer; user-select: none; transition: background 0.15s; }
.fp-bubble.wechat-self .fp-wechat-quote { background: rgba(20, 83, 45, 0.065); }
.fp-wechat-quote:hover { background: rgba(15, 23, 42, 0.075); }
.fp-bubble.wechat-self .fp-wechat-quote:hover { background: rgba(20, 83, 45, 0.1); }
.fp-wechat-quote-bar { width: 2.5px; border-radius: 2px; background: rgba(100, 116, 139, 0.45); flex-shrink: 0; }
.fp-bubble.wechat-self .fp-wechat-quote-bar { background: rgba(22, 101, 52, 0.45); }
.fp-wechat-quote-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.fp-wechat-quote-text { font-size: 11.5px; line-height: 1.45; color: #64748b; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.fp-bubble.wechat-self .fp-wechat-quote-text { color: #3f624d; }
.fp-wechat-quote.is-expanded .fp-wechat-quote-text { display: block; -webkit-line-clamp: unset; overflow: visible; white-space: pre-wrap; }
.fp-wechat-quote-author { font-weight: 600; color: #475569; margin-right: 2px; }
.fp-bubble.wechat-self .fp-wechat-quote-author { color: #166534; }
.fp-wechat-quote-toggle { font-size: 10px; font-weight: 600; color: var(--ct-color-primary); align-self: flex-end; margin-top: 1px; }

/* Loading State */
.fp-loading-state { padding: 18px 20px; display: flex; align-items: flex-start; justify-content: center; gap: 8px; font-size: 12px; color: var(--ct-color-primary); font-weight: 500; }
.fp-spinner { width: 14px; height: 14px; border: 2px solid var(--ct-color-primary-tint); border-top-color: var(--ct-color-primary); border-radius: 50%; animation: fp-spin 0.8s linear infinite; }
.fp-loading-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 8px; }
.fp-stream-preview {
  max-height: 120px;
  margin: 0;
  padding: 8px 10px;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  border-radius: 6px;
  background: var(--ct-bg-hover);
  color: var(--ct-text-secondary);
  font: inherit;
  line-height: 1.45;
}
@keyframes fp-spin { to { transform: rotate(360deg); } }

/* 6. Bottom Composer (Ergonomic Control Console) */
.fp-composer {
  background: var(--ct-bg-card);
  border-top: 1px solid var(--ct-border-color);
  padding: 8px 10px;
  flex-shrink: 0;
  position: relative;
  z-index: 10;
  box-shadow: 0 -2px 10px rgba(27, 25, 36, 0.04);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* Quick Prompts Strip */
.fp-quick-prompts-bar {
  width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
  padding-bottom: 2px;
}
.fp-quick-prompts-bar::-webkit-scrollbar { display: none; }
.fp-quick-prompts { display: flex; gap: 5px; }
.fp-qp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  font-weight: 500;
  padding: 2px 8px;
  height: 22px;
  border-radius: 999px;
  background: var(--ct-bg-sunken);
  border: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 0.15s ease;
}
.fp-qp-chip:hover {
  background: var(--ct-color-primary-muted);
  color: var(--ct-color-primary);
  border-color: color-mix(in srgb, var(--ct-color-primary) 30%, transparent);
}

/* Strategy Bar (Single Row: 触发模式 + 关系方向) */
.fp-strategy-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  height: 28px;
  background: color-mix(in srgb, var(--ct-text-primary) 7%, transparent);
  border: 1px solid transparent;
  border-radius: var(--ct-radius-md);
  padding: 2px;
  box-sizing: border-box;
}
.fp-seg-group {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.fp-seg-btn {
  flex: 1;
  min-width: 0;
  height: 22px;
  padding: 0 4px;
  border: none;
  background: transparent;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 500;
  color: var(--ct-text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  white-space: nowrap;
  transition: all 0.15s ease;
  user-select: none;
}
.fp-seg-btn:hover:not(.active) {
  color: var(--ct-text-primary);
  background: color-mix(in srgb, var(--ct-bg-card) 50%, transparent);
}
.fp-seg-btn.active {
  background: var(--ct-bg-card);
  color: var(--ct-color-primary);
  font-weight: 600;
  box-shadow: var(--ct-shadow-sm);
}
.fp-strategy-divider {
  width: 1px;
  height: 14px;
  background: color-mix(in srgb, var(--ct-text-primary) 12%, transparent);
  flex-shrink: 0;
  margin: 0 2px;
}

/* Input Row (Hero Row: Input protected flex-grow, Buttons flex-shrink 0) */
.fp-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 36px;
}
.fp-composer-input {
  flex: 1 1 auto;
  min-width: 130px;
  height: 36px;
  padding: 0 10px;
  font-size: 12.5px;
  border-radius: 7px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-card);
  color: var(--ct-text-primary);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  box-sizing: border-box;
}
.fp-composer-input:focus {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 2px var(--ct-color-primary-tint);
}
.fp-composer-input:disabled {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-tertiary);
  cursor: not-allowed;
}

.fp-btn-act {
  flex: 0 0 auto;
  height: 36px;
  padding: 0 10px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
  border: none;
  transition: all 0.15s ease;
  user-select: none;
  box-sizing: border-box;
}
.fp-btn-act:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.fp-btn-act.primary {
  background: var(--ct-color-primary);
  color: #ffffff;
}
.fp-btn-act.primary:hover:not(:disabled) {
  background: var(--ct-color-primary-hover);
}
.fp-btn-act.secondary {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
  border: 1px solid var(--ct-border-color);
}
.fp-btn-act.secondary:hover:not(:disabled) {
  background: var(--ct-bg-sunken);
  color: var(--ct-text-primary);
  border-color: var(--ct-border-color-hover);
}
.fp-btn-act.send-btn {
  min-width: 58px;
}
.fp-btn-act.gen-btn {
  min-width: 86px;
}
.fp-btn-act.gen-sub-btn {
  min-width: 56px;
}

/* Footer (Micro Info & Model Selector) */
.fp-composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 16px;
  margin-top: -1px;
}
.fp-model-picker {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  position: relative;
  max-width: 70%;
}
.fp-mini-select {
  font-size: 10px;
  color: var(--ct-text-tertiary);
  background: transparent;
  border: none;
  outline: none;
  cursor: pointer;
  padding: 0 14px 0 0;
  -webkit-appearance: none;
  appearance: none;
  text-overflow: ellipsis;
  white-space: nowrap;
  overflow: hidden;
  max-width: 100%;
}
.fp-mini-select:hover {
  color: var(--ct-color-primary);
}
.fp-select-arrow {
  position: absolute;
  right: 0;
  pointer-events: none;
  color: var(--ct-text-tertiary);
}
.fp-footer-hint {
  font-size: 10px;
  color: var(--ct-text-tertiary);
  white-space: nowrap;
  flex-shrink: 0;
}
.fp-error-txt {
  font-size: 10px;
  color: var(--ct-color-error);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

/* Modals */
.fp-modal-overlay { position: fixed; inset: 0; background: rgba(27, 25, 36, 0.45); display: flex; align-items: center; justify-content: center; z-index: 9999; backdrop-filter: blur(2px); }
.fp-modal { background: var(--ct-bg-card); border-radius: var(--ct-radius-lg); padding: 24px; width: 320px; box-shadow: var(--ct-shadow-lg); }
.fp-modal-title { font-size: 16px; font-weight: 600; color: var(--ct-text-primary); margin: 0 0 8px 0; }
.fp-modal-desc { font-size: 13px; color: var(--ct-text-secondary); margin-bottom: 16px; line-height: 1.5; }
.fp-modal-box { padding: 12px; background: var(--ct-bg-sunken); border-radius: var(--ct-radius-md); font-size: 12px; color: var(--ct-text-secondary); margin-bottom: 20px; border: 1px dashed var(--ct-border-color); line-height: 1.5; word-break: break-word; }
.fp-modal-actions { display: flex; justify-content: flex-end; gap: 8px; }

/* Responsive Media Queries (Never break elements, maintain strict scale) */
@media (max-width: 480px) {
  .fp-header-drag-zone { padding: 0 8px; }
  .fp-contact-bar { padding: 0 8px 6px; }
  .fp-insights-strip { padding: 0 8px; }
  .fp-composer { padding: 7px 8px; gap: 5px; }
  .fp-scroll-area { padding: 8px 8px; }
  .fp-seg-btn { font-size: 10.5px; padding: 0 2px; }
  .fp-input-row { gap: 5px; }
  .fp-composer-input { font-size: 12px; padding: 0 8px; }
}

@media (max-width: 360px) {
  .fp-btn-back span { display: none; }
  .fp-btn-back { padding: 3px 6px; }
  .fp-brand-name { font-size: 11px; }
  .fp-brand-pulse-badge { display: none; }
  .fp-monitor-tag { display: none; }
  .fp-ribbon-btn span { display: none; }
  .fp-ribbon-btn { padding: 2px 5px; }
  .fp-seg-btn span { display: none; }
  .fp-btn-act.send-btn { min-width: 36px; padding: 0 6px; }
  .fp-btn-act.send-btn span { display: none; }
  .fp-btn-act.gen-sub-btn { min-width: 36px; padding: 0 6px; }
  .fp-btn-act.gen-sub-btn span { display: none; }
  .fp-btn-act.gen-btn { min-width: 60px; font-size: 11px; padding: 0 8px; }
}

/* QA Emotion Tab CSS */
.fp-emotion-summary-cards { display: flex; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--ct-border-color); background: var(--ct-bg-sunken); }
.fp-summary-card { flex: 1; display: flex; flex-direction: column; background: var(--ct-bg-card); border-radius: var(--ct-radius-md); padding: 8px 10px; box-shadow: var(--ct-shadow-sm); }
.fp-card-lbl { font-size: 10.5px; color: var(--ct-text-tertiary); margin-bottom: 3px; }
.fp-card-val { font-size: 13px; font-weight: 600; color: var(--ct-text-primary); }
.fp-card-val.positive { color: var(--ct-color-success); }
.fp-card-val.negative { color: var(--ct-color-error); }
.fp-chart-workspace { display: flex; flex-direction: column; flex: 1; min-height: 0; background: var(--ct-bg-sunken); }
.fp-chart-header-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px 4px; }
.tiny-link { font-size: 10px; padding: 2px 6px; }
.tight-stage { padding: 4px 10px; }
.fp-secondary-charts-zone { display: flex; flex-direction: column; background: var(--ct-bg-sunken); padding-bottom: 8px; }
.tight-config { background: transparent; border-bottom: none; padding: 6px 10px 4px; }
.tight-rail { padding: 0 10px; }
.fp-empty-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
  opacity: 0.8;
}

.fp-empty-val { font-size: 10.5px; color: var(--ct-text-tertiary); text-align: center; margin-top: 16px; opacity: 0.6; }
</style>
