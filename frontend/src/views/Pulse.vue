<template>
<section class="pulse-page ct-page">
  <!-- 页头：对象工作台同款选人器（未选中也可先选人） -->
  <header v-if="conversations.length" class="pulse-header fade-in">
    <CtAvatar class="pulse-avatar" :src="currentConversation?.avatar" :name="currentConversation?.name || currentConversation?.username || '？'" :size="44" />
    <div class="pulse-title-block">
      <h1 class="pulse-title">{{ currentConversation?.name || currentConversation?.username || '选择一位联系人' }}</h1>
      <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId" :loading="loading"
        @update:conversation-id="onConversationChange" />
    </div>
    <router-link v-if="selectedConversationId" to="/analytics" class="btn pulse-goto-analytics">分析工作台 →</router-link>
  </header>

  <!-- 无数据空态：指路数据页（不再是控制台首屏） -->
  <div v-else-if="!loading" class="panel pulse-empty">
    <div class="panel-head"><span class="panel-title">关系脉搏</span></div>
    <p class="pulse-empty-text">还没有可分析的聊天记录。</p>
    <router-link to="/import" class="btn primary pulse-empty-cta">去导入微信数据</router-link>
  </div>

  <template v-if="selectedConversationId && !isGroup">
    <div v-if="loadingOverview && !overview" class="panel pulse-loading-panel">
      <Loader2 :size="18" class="spin-icon" /> 正在读取关系脉搏…
    </div>

    <template v-if="overview">
      <!-- 未分析：第一次分析的引导（P1 答案优先，先给入口再谈指标） -->
      <div v-if="!overview.analyzed" class="panel pulse-empty-analysis">
        <div class="panel-head"><span class="panel-title">关系判读</span></div>
        <p class="pulse-empty-text">还没有分析过你们的聊天记录，先跑一次全面分析，脉搏页才有话可说。</p>
        <router-link to="/analytics" class="btn primary pulse-empty-cta">开始全面分析</router-link>
      </div>

      <template v-else>
        <!-- 关系判读横幅：一句话先给答案（P1），LLM 优先本地兜底 -->
        <div class="panel pulse-verdict">
          <div class="panel-head">
            <span class="panel-title">关系判读</span>
            <span class="panel-badge" :class="overview.verdict?.source === 'llm' ? 'enhanced' : ''">
              {{ overview.verdict?.source === 'llm' ? 'AI 判读' : '本地判读' }}
            </span>
            <span v-if="overview.professional.analysis_stale" class="pulse-stale-badge"
              :title="overview.professional.pending_message_count ? `有 ${overview.professional.pending_message_count} 条新消息未纳入当前指标` : '消息集已变化，建议重新分析'">
              {{ overview.professional.pending_message_count ? `${overview.professional.pending_message_count} 条新消息待分析` : '结果待更新' }}
            </span>
          </div>
          <p class="verdict-text">{{ overview.verdict?.text }}</p>
        </div>

        <!-- 三联直白指标卡（P2 门面） -->
        <div class="pulse-metrics">
          <!-- 关系温度：分数环 + 分段话术 + 较上次 + 历史微线 -->
          <div class="panel metric-card">
            <div class="panel-head"><span class="panel-title">关系温度</span></div>
            <div class="metric-body metric-temp">
              <div class="ct-score-ring metric-ring">
                <svg viewBox="0 0 120 120" class="circular-chart">
                  <circle class="circle-bg" cx="60" cy="60" r="50" fill="none" stroke="var(--ct-bg-sunken)" stroke-width="10" />
                  <circle class="circle-fill" cx="60" cy="60" r="50" fill="none" stroke="var(--ct-color-primary)" stroke-width="10"
                    stroke-linecap="round" :stroke-dasharray="314.159"
                    :stroke-dashoffset="314.159 * (1 - (overview.temperature?.score || 0) / 100)" />
                </svg>
                <div class="ct-score-text">
                  <span class="ct-score-num">{{ Math.round(overview.temperature?.score || 0) }}</span>
                </div>
              </div>
              <div class="temp-copy">
                <span class="temp-label">{{ overview.temperature?.label }}</span>
                <span v-if="overview.temperature?.delta != null" class="temp-delta"
                  :class="(overview.temperature.delta || 0) >= 0 ? 'up' : 'down'">
                  {{ (overview.temperature.delta || 0) >= 0 ? '↑' : '↓' }}{{ Math.abs(overview.temperature.delta || 0).toFixed(1) }} 较上次
                </span>
                <!-- 趋势微线至少两个点才有意义：单点不渲染（避免游离圆点） -->
                <div v-if="(overview.temperature?.trend_line?.length || 0) >= 2" ref="sparkRef" class="temp-spark"></div>
              </div>
            </div>
          </div>

          <!-- 主动天平：谁在推动这段关系 -->
          <div class="panel metric-card">
            <div class="panel-head"><span class="panel-title">主动天平</span></div>
            <div class="metric-body">
              <template v-if="overview.initiative && overview.initiative.me_pct != null">
                <div class="balance-bar" role="img"
                  :aria-label="`你发起 ${overview.initiative.me_pct}%，TA 发起 ${(100 - overview.initiative.me_pct).toFixed(1)}%`">
                  <div class="balance-me" :style="{ width: (overview.initiative.me_pct || 0) + '%' }"></div>
                </div>
                <div class="balance-legend">
                  <span class="legend-me"><i class="swatch"></i>你发起 {{ overview.initiative.me_pct }}%（{{ overview.initiative.user_initiated }} 次）</span>
                  <span class="legend-ta"><i class="swatch"></i>TA 发起 {{ (100 - (overview.initiative.me_pct || 0)).toFixed(1) }}%（{{ overview.initiative.other_initiated }} 次）</span>
                </div>
              </template>
              <p v-else class="metric-empty">暂无会话发起统计</p>
            </div>
          </div>

          <!-- 回应温度：双向中位回复时长 + 前窗对照 -->
          <div class="panel metric-card">
            <div class="panel-head"><span class="panel-title">回应温度</span></div>
            <div class="metric-body">
              <template v-if="overview.response?.recent || overview.response?.prev">
                <div class="reply-row">
                  <span class="reply-who">TA → 你</span>
                  <span class="reply-val">{{ fmtMin(overview.response?.recent?.ta_to_me_median_min) }}</span>
                  <span v-if="deltaPct(overview.response?.recent?.ta_to_me_median_min, overview.response?.prev?.ta_to_me_median_min) != null"
                    class="reply-delta" :class="deltaClass(overview.response?.recent?.ta_to_me_median_min, overview.response?.prev?.ta_to_me_median_min, true)">
                    {{ deltaText(overview.response?.recent?.ta_to_me_median_min, overview.response?.prev?.ta_to_me_median_min) }}
                  </span>
                </div>
                <div class="reply-row">
                  <span class="reply-who">你 → TA</span>
                  <span class="reply-val">{{ fmtMin(overview.response?.recent?.me_to_ta_median_min) }}</span>
                  <span v-if="deltaPct(overview.response?.recent?.me_to_ta_median_min, overview.response?.prev?.me_to_ta_median_min) != null"
                    class="reply-delta" :class="deltaClass(overview.response?.recent?.me_to_ta_median_min, overview.response?.prev?.me_to_ta_median_min, false)">
                    {{ deltaText(overview.response?.recent?.me_to_ta_median_min, overview.response?.prev?.me_to_ta_median_min) }}
                  </span>
                </div>
                <p class="reply-note">近 30 天中位回复时长，括号外为与前 30 天对照</p>
              </template>
              <p v-else class="metric-empty">近 60 天没有可统计的回复对</p>
            </div>
          </div>
        </div>

        <!-- 本月速览 -->
        <div class="panel pulse-monthly">
          <div class="panel-head"><span class="panel-title">本月速览</span></div>
          <p class="monthly-line">
            <strong>{{ overview.monthly.messages.toLocaleString() }}</strong> 条消息 ·
            <strong>{{ fmtChars(overview.monthly.chars) }}</strong> 字
            <template v-if="overview.monthly.late_night > 0"> · 深夜对话 <strong>{{ overview.monthly.late_night }}</strong> 次<span
              v-if="overview.monthly.late_night_by_me > 0">（你发起 {{ overview.monthly.late_night_by_me }} 次）</span></template>
          </p>
        </div>

        <!-- 冷淡预警：无信号整条隐藏（不占焦虑空间） -->
        <div v-if="overview.warning" class="pulse-warning" role="alert">
          <div class="warning-head">
            <AlertTriangle :size="16" />
            <strong>冷淡预警 · {{ overview.warning.level }}</strong>
          </div>
          <ul class="warning-items">
            <li v-for="(item, i) in overview.warning.items" :key="i">
              <span class="warning-label">{{ item.label }}（{{ item.level }}）</span>{{ item.note }}
            </li>
          </ul>
        </div>

        <!-- 专业视图折叠（P2：深度内里降一屏，不删） -->
        <div class="panel pulse-pro">
          <button class="btn pulse-pro-toggle" :aria-expanded="showPro" @click="showPro = !showPro">
            专业视图 {{ showPro ? '▴' : '▾' }}
          </button>
          <div v-show="showPro" class="pulse-pro-body">
            <div class="pulse-pro-grid">
              <div class="pro-main">
                <DimensionRadar :dimension-scores="allDimensions" />
                <div class="dimension-cards-grid">
                  <AffinityScoreCard v-if="pro.interaction_investment" title="互动投入"
                    :score="pro.interaction_investment.score" :max-score="100"
                    :weight="pro.interaction_investment.weight"
                    :interpretation="pro.interaction_investment.interpretation" />
                  <AffinityScoreCard v-if="pro.emotional_resonance" title="情感共鸣"
                    :score="pro.emotional_resonance.score" :max-score="100"
                    :weight="pro.emotional_resonance.weight"
                    :interpretation="pro.emotional_resonance.interpretation" />
                  <AffinityScoreCard v-if="pro.closeness_signals" title="亲近信号"
                    :score="pro.closeness_signals.score" :max-score="100"
                    :weight="pro.closeness_signals.weight"
                    :interpretation="pro.closeness_signals.interpretation" />
                  <AffinityScoreCard v-if="pro.preference_compatibility" title="喜好兼容度"
                    :score="pro.preference_compatibility.score" :max-score="100"
                    :weight="pro.preference_compatibility.weight"
                    :interpretation="pro.preference_compatibility.interpretation"
                    :is-bonus="!(pro.preference_compatibility.weight > 0)"
                    :bonus-value="pro.preference_compatibility.bonus_scores?.preference_bonus" />
                  <AffinityScoreCard v-if="pro.llm_relationship" class="span-full" title="AI 关系评估"
                    :score="pro.llm_relationship.score" :max-score="100"
                    :weight="pro.llm_relationship.weight"
                    :interpretation="pro.llm_relationship.interpretation" />
                </div>
                <p v-if="overview.professional.absent_reason" class="pro-absent-note">
                  AI 关系评估未参与本次评分：{{ overview.professional.absent_reason }}
                </p>
              </div>
              <div class="pro-side">
                <RiskSignalCard :assessment="pro.risk_assessment" />
              </div>
            </div>
            <router-link to="/analytics" class="btn pulse-goto-analytics pro-link">权重配置 · 重试 AI 评估 · 维度拆解，去分析工作台 →</router-link>
          </div>
        </div>
      </template>
    </template>
  </template>

  <!-- 群聊：好感引擎口径外，指路群摘要 -->
  <div v-else-if="selectedConversationId && isGroup" class="panel pulse-hint">
    <p>群聊不在关系脉搏的口径内。去分析工作台查看群聊摘要与互动统计。</p>
    <router-link to="/analytics" class="btn">去分析工作台 →</router-link>
  </div>
</section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { AlertTriangle, Loader2 } from 'lucide-vue-next'
import { bridgeReady, api } from '@/api/bridge'
import { getPulseOverview, type PulseOverview } from '@/api/pulse'
import { chartPalette } from '@/components/charts/chartTheme'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import DimensionRadar from '@/components/affinity/DimensionRadar.vue'
import AffinityScoreCard from '@/components/affinity/AffinityScoreCard.vue'
import RiskSignalCard from '@/components/affinity/RiskSignalCard.vue'
import CtAvatar from '@/components/base/CtAvatar.vue'

type Conversation = { id: number; name: string; username: string; avatar?: string; conversation_type?: 'private' | 'group' }

const conversations = ref<Conversation[]>([])
const selectedConversationId = ref<number | null>(null)
const loading = ref(false)
const loadingOverview = ref(false)
const overview = ref<PulseOverview | null>(null)
const showPro = ref(false)
let viewEpoch = 0 // 切人后丢弃在途异步结果（Analytics 同款代数守卫）

const currentConversation = computed(() => conversations.value.find((c) => c.id === selectedConversationId.value))
const isGroup = computed(() => currentConversation.value?.conversation_type === 'group')
const pro = computed<Record<string, any>>(() => overview.value?.professional?.result ?? {})
const allDimensions = computed(() => ({
    interaction_investment: pro.value.interaction_investment ?? null,
    emotional_resonance: pro.value.emotional_resonance ?? null,
    closeness_signals: pro.value.closeness_signals ?? null,
    preference_compatibility: pro.value.preference_compatibility ?? null,
    llm_relationship: pro.value.llm_relationship ?? null,
}))

// ---------- 直白化格式化（口径全部来自后端，这里只做展示层换算） ----------

function fmtMin(min: number | null | undefined): string {
    if (min == null) return '—'
    if (min < 1) return `${Math.round(min * 60)} 秒`
    if (min < 60) return `${Math.round(min)} 分钟`
    return `${(min / 60).toFixed(1)} 小时`
}

function fmtChars(chars: number): string {
    return chars >= 10000 ? `${(chars / 10000).toFixed(1)} 万` : chars.toLocaleString()
}

function deltaPct(recent: number | null | undefined, prev: number | null | undefined): number | null {
    if (recent == null || prev == null || prev <= 0) return null
    return Math.round(((recent - prev) / prev) * 100)
}

function deltaText(recent: number | null | undefined, prev: number | null | undefined): string {
    const pct = deltaPct(recent, prev)
    if (pct == null) return ''
    const faster = pct < 0
    return `${faster ? '变快' : '变慢'} ${Math.abs(pct)}%`
}

function deltaClass(recent: number | null | undefined, prev: number | null | undefined, judge: boolean): string {
    const pct = deltaPct(recent, prev)
    if (pct == null || !judge) return ''
    // 只对 TA→你 一侧给语义色（TA 变快=好，变慢=留意）；自己的节奏不做评判
    return pct < 0 ? 'faster' : 'slower'
}

// ---------- 加载 ----------

async function loadConversations() {
    try {
        await bridgeReady()
        loading.value = true
        let wxid = ''
        try {
            const acct = await api.get_wechat_accounts()
            if (acct?.ok) wxid = acct.active_account_wxid || ''
        } catch { /* 账号上下文失败按全量列表兜底 */ }
        const res = await api.get_conversation_list(wxid || undefined)
        if (res.ok) {
            conversations.value = res.conversations
            if (selectedConversationId.value && !conversations.value.some((c) => c.id === selectedConversationId.value)) {
                selectedConversationId.value = null
            }
            if (conversations.value.length && !selectedConversationId.value) {
                onConversationChange(conversations.value[0].id)
            } else if (!conversations.value.length) {
                selectedConversationId.value = null
            }
        }
    } catch (e) {
        console.error('加载联系人失败', e)
    } finally {
        loading.value = false
    }
}

function onConversationChange(id: number) {
    if (selectedConversationId.value === id) return
    selectedConversationId.value = id
    showPro.value = false
    void loadOverview(id)
}

async function loadOverview(id: number) {
    const epoch = ++viewEpoch
    overview.value = null
    loadingOverview.value = true
    try {
        await bridgeReady()
        const res = await getPulseOverview(id)
        if (epoch !== viewEpoch) return // 已切人，丢弃
        overview.value = res
        await nextTick()
        renderSpark()
    } catch (e) {
        if (epoch === viewEpoch) console.error('脉搏概览加载失败', e)
    } finally {
        if (epoch === viewEpoch) loadingOverview.value = false
    }
}

// ---------- 温度微线（好感历史，同口径） ----------

const sparkRef = ref<HTMLDivElement | null>(null)
let sparkChart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

function renderSpark() {
    const line = overview.value?.temperature?.trend_line || []
    // v-if 卸载容器后旧实例悬空：先回收再判断
    if (!sparkRef.value) {
        if (sparkChart) disposeSpark()
        return
    }
    if (line.length < 2) return
    const sparkColor = chartPalette()[0]
    if (!sparkChart) {
        sparkChart = echarts.init(sparkRef.value)
        resizeObserver = new ResizeObserver(() => sparkChart?.resize())
        resizeObserver.observe(sparkRef.value)
    }
    sparkChart.setOption({
        grid: { left: 0, right: 0, top: 4, bottom: 0 },
        xAxis: { type: 'category', show: false, data: line.map(([ts]) => ts) },
        yAxis: { type: 'value', show: false, min: (v: { min: number }) => Math.max(0, Math.floor(v.min - 5)), max: (v: { max: number }) => Math.min(100, Math.ceil(v.max + 5)) },
        tooltip: {
            trigger: 'axis',
            formatter: (params: any) => {
                const p = Array.isArray(params) ? params[0] : params
                const d = new Date(p.name * 1000)
                const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
                return `${date}<br/>好感 ${Number(p.value).toFixed(1)}`
            },
        },
        series: [{
            type: 'line',
            data: line.map(([, s]) => s),
            showSymbol: false,
            lineStyle: { width: 2, color: sparkColor },
            itemStyle: { color: sparkColor },
            areaStyle: { color: `${sparkColor}14`, silent: true },
        }],
    })
}

function disposeSpark() {
    resizeObserver?.disconnect()
    resizeObserver = null
    sparkChart?.dispose()
    sparkChart = null
}

watch(() => overview.value?.temperature?.trend_line, () => { nextTick(renderSpark) })

onMounted(() => { void loadConversations() })
onUnmounted(disposeSpark)
</script>

<style scoped>
.pulse-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
    max-width: 1080px;
    margin: 0 auto;
    width: 100%;
}

/* ---------- 页头 ---------- */
.pulse-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 18px 20px;
    background: var(--ct-bg-card);
    border: 1px solid var(--ct-border-color);
    border-radius: var(--ct-radius-lg, 14px);
}

.pulse-title-block {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    flex: 1;
}

.pulse-title {
    margin: 0;
    font-size: var(--ct-text-xl);
    font-weight: var(--ct-font-bold);
    color: var(--ct-text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.pulse-goto-analytics {
    flex-shrink: 0;
    text-decoration: none;
}

/* ---------- 判读横幅 ---------- */
.pulse-verdict .verdict-text {
    margin: 2px 0 0;
    font-size: var(--ct-text-base);
    line-height: 1.75;
    color: var(--ct-text-primary);
}

.pulse-stale-badge {
    font-size: var(--ct-text-xs);
    color: var(--ct-color-warning);
    background: var(--ct-color-warning-tint);
    border-radius: 999px;
    padding: 2px 10px;
}

/* ---------- 三联指标卡 ---------- */
.pulse-metrics {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
}

.metric-card {
    display: flex;
    flex-direction: column;
}

.metric-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 10px;
    padding-top: 4px;
}

.metric-empty {
    margin: 0;
    color: var(--ct-text-tertiary);
    font-size: var(--ct-text-sm);
}

/* 关系温度 */
.metric-temp {
    flex-direction: row;
    align-items: center;
    gap: 18px;
}

.metric-ring {
    width: 108px;
    height: 108px;
    flex-shrink: 0;
}

.metric-ring .circular-chart {
    width: 100%;
    height: 100%;
}

.metric-ring .ct-score-num {
    font-size: var(--ct-text-2xl);
}

.temp-copy {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    flex: 1;
    align-self: stretch;
    justify-content: center;
}

.temp-label {
    font-size: var(--ct-text-lg, 17px);
    font-weight: var(--ct-font-bold);
    color: var(--ct-text-primary);
}

.temp-delta {
    font-size: var(--ct-text-xs);
}

.temp-delta.up { color: var(--ct-color-success); }
.temp-delta.down { color: var(--ct-color-warning); }

.temp-spark {
    width: 100%;
    height: 44px;
}

/* 主动天平 */
.balance-bar {
    display: flex;
    height: 14px;
    border-radius: 7px;
    background: var(--ct-bg-sunken);
    overflow: hidden;
}

.balance-me {
    background: var(--ct-color-primary);
    border-radius: 7px 0 0 7px;
    transition: width 0.4s ease;
}

.balance-legend {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: var(--ct-text-sm);
    color: var(--ct-text-secondary);
}

.balance-legend .swatch {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    margin-right: 6px;
}

.legend-me .swatch { background: var(--ct-color-primary); }
.legend-ta .swatch { background: var(--ct-bg-sunken); border: 1px solid var(--ct-border-color); }

/* 回应温度 */
.reply-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
}

.reply-who {
    width: 64px;
    flex-shrink: 0;
    color: var(--ct-text-secondary);
    font-size: var(--ct-text-sm);
}

.reply-val {
    font-size: var(--ct-text-lg, 17px);
    font-weight: var(--ct-font-bold);
    color: var(--ct-text-primary);
}

.reply-delta { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); }
.reply-delta.faster { color: var(--ct-color-success); }
.reply-delta.slower { color: var(--ct-color-warning); }

.reply-note {
    margin: 0;
    font-size: var(--ct-text-xs);
    color: var(--ct-text-tertiary);
}

/* ---------- 本月速览 ---------- */
.monthly-line {
    margin: 2px 0 0;
    color: var(--ct-text-secondary);
    font-size: var(--ct-text-base);
}

.monthly-line strong {
    color: var(--ct-text-primary);
    font-weight: var(--ct-font-bold);
}

/* ---------- 冷淡预警（语义色 tint 底 + 本色字） ---------- */
.pulse-warning {
    border-radius: var(--ct-radius-lg, 14px);
    background: var(--ct-color-warning-tint);
    color: var(--ct-color-warning);
    padding: 14px 18px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.warning-head {
    display: flex;
    align-items: center;
    gap: 8px;
}

.warning-items {
    margin: 0;
    padding-left: 18px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: var(--ct-text-sm);
    color: var(--ct-text-secondary);
}

.warning-label {
    font-weight: var(--ct-font-bold);
    margin-right: 8px;
    color: var(--ct-color-warning);
}

/* ---------- 专业视图折叠 ---------- */
.pulse-pro-toggle { width: 100%; }

.pulse-pro-body {
    margin-top: 12px;
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.pulse-pro-grid {
    display: grid;
    grid-template-columns: 1fr 320px;
    gap: 16px;
    align-items: start;
}

.pro-main {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.dimension-cards-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
}

.span-full { grid-column: 1 / -1; }

.pro-absent-note {
    margin: 0;
    font-size: var(--ct-text-sm);
    color: var(--ct-text-tertiary);
}

.pro-link { align-self: flex-start; text-decoration: none; }

/* ---------- 空态 / 提示 ---------- */
.pulse-empty,
.pulse-empty-analysis,
.pulse-loading-panel,
.pulse-hint {
    display: flex;
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
}

.pulse-loading-panel {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--ct-text-secondary);
}

.pulse-empty-text {
    margin: 0;
    color: var(--ct-text-secondary);
    line-height: 1.7;
}

.pulse-empty-cta { text-decoration: none; }

.spin-icon { animation: pulse-spin 1s linear infinite; }

@keyframes pulse-spin { to { transform: rotate(360deg); } }

@media (max-width: 960px) {
    .pulse-metrics { grid-template-columns: 1fr; }
    .pulse-pro-grid { grid-template-columns: 1fr; }
}
</style>
