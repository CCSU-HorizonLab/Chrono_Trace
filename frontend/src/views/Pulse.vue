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
  </header>

  <!-- 无数据空态：指路数据页（不再是控制台首屏） -->
  <div v-else-if="!loading" class="panel pulse-empty">
    <div class="panel-head"><span class="panel-title">关系脉搏</span></div>
    <p class="pulse-empty-text">还没有可分析的聊天记录。</p>
    <button type="button" class="btn primary pulse-empty-cta" @click="openSettingsTab('account')">去导入微信数据</button>
  </div>

  <template v-if="conversationResolved && !isGroup">
    <div v-if="loadingOverview && !overview" class="panel pulse-loading-panel">
      <Loader2 :size="18" class="spin-icon" /> 正在读取关系脉搏…
    </div>

    <template v-if="overview">
      <!-- 未分析：第一次分析的引导（P1 答案优先，先给入口再谈指标）。
           CTA 直投分析工作台（常驻专业视图内），进度由顶部细条全程可见 -->
      <div v-if="!overview.analyzed" class="panel pulse-empty-analysis">
        <div class="panel-head"><span class="panel-title">关系判读</span></div>
        <p class="pulse-empty-text">还没有分析过你们的聊天记录，先跑一次全面分析，脉搏页才有话可说。</p>
        <button type="button" class="btn primary pulse-empty-cta" @click="runAnalysisNow">开始全面分析</button>
      </div>

      <template v-else>
        <!-- 关系判读横幅：一句话先给答案（P1），周报（AI）＞上次 AI 评估＞本地周报＞本地判读 -->
        <div class="panel pulse-verdict">
          <div class="panel-head">
            <span class="panel-title">关系判读</span>
            <span class="panel-badge" :class="bannerVerdict.isAi ? 'enhanced' : ''">
              {{ bannerVerdict.label }}
              <template v-if="llmUpgrading">· 生成中…</template>
            </span>
            <button v-if="overview.professional.analysis_stale" type="button" class="pulse-stale-badge"
              :title="overview.professional.pending_message_count ? `有 ${overview.professional.pending_message_count} 条新消息未纳入当前指标，点击重新分析` : '消息集已变化，点击重新分析'"
              @click="runAnalysisNow">
              {{ overview.professional.pending_message_count ? `${overview.professional.pending_message_count} 条新消息待分析` : '结果待更新' }}
            </button>
            <button v-if="weekly" class="btn weekly-toggle" :aria-expanded="showWeekly" @click="showWeekly = !showWeekly">
              展开周报 {{ showWeekly ? '▴' : '▾' }}
            </button>
          </div>
          <p class="verdict-text">{{ bannerVerdict.text }}</p>
          <div v-if="showWeekly && weekly" class="weekly-detail">
            <p class="weekly-verdict">{{ weekly.verdict }}</p>
            <p class="weekly-meta">
              {{ weekly.source === 'llm' ? 'AI 周报' : '本地周报' }} · {{ weekly.week_start }} 那周 · 更新于 {{ fmtDate(weekly.updated_at) }}
              <button v-if="llmConfigured && weekly.source === 'template' && !llmUpgrading"
                class="btn weekly-regen" @click="upgradeWeekly()">AI 解读本周</button>
              <span v-if="llmUpgrading" class="weekly-upgrading">AI 周报生成中，稍后自动更新…</span>
            </p>
          </div>
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
            <template v-if="(overview.monthly.morning_days || 0) > 0"> · 早安 <strong>{{ overview.monthly.morning_days }}</strong> 天</template>
            <template v-if="(overview.monthly.night_days || 0) > 0"> · 晚安 <strong>{{ overview.monthly.night_days }}</strong> 天</template>
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

      </template>

      <!-- 专业视图折叠（P2 深度内里降一屏）：分析工作台常驻挂载（v-show 保
           轮询/接续活性），未分析时也可由引导卡 CTA / 新鲜度徽标直接触发 -->
      <div class="panel pulse-pro">
        <button class="btn pulse-pro-toggle" :aria-expanded="showPro" @click="showPro = !showPro">
          专业视图 {{ showPro ? '▴' : '▾' }}
        </button>
        <div v-show="showPro" class="pulse-pro-body">
          <AnalysisWorkbench :conversation-id="selectedConversationId" @analysis-completed="onAnalysisCompleted" />
        </div>
      </div>
    </template>
  </template>

  <!-- 群聊：好感引擎口径外，指路群摘要 -->
  <div v-else-if="conversationResolved && isGroup" class="panel pulse-hint">
    <p>群聊不在关系脉搏的口径内。去时光页查看群聊摘要与互动统计。</p>
    <router-link to="/timeline" class="btn">去时光页 →</router-link>
  </div>
</section>
</template>

<script setup lang="ts">
import { openSettingsTab } from '@/utils/settingsBus'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { AlertTriangle, Loader2 } from 'lucide-vue-next'
import { bridgeReady, api } from '@/api/bridge'
import { getPulseOverview, getWeeklyReport, requestWeeklyLlm, type PulseOverview, type WeeklyReport } from '@/api/pulse'
import { chartPalette } from '@/components/charts/chartTheme'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import AnalysisWorkbench from '@/components/analytics/AnalysisWorkbench.vue'
import { sharedContactId as selectedConversationId } from '@/utils/contactScope'
import CtAvatar from '@/components/base/CtAvatar.vue'

type Conversation = { id: number; name: string; username: string; avatar?: string; conversation_type?: 'private' | 'group' }

const conversations = ref<Conversation[]>([])
const loading = ref(false)
const loadingOverview = ref(false)
const overview = ref<PulseOverview | null>(null)
const showPro = ref(false)
let viewEpoch = 0 // 切人后丢弃在途异步结果（Analytics 同款代数守卫）

// ---------- 关系周报（判读横幅正源：AI 周报 > 上次 AI 评估 > 本地周报 > 本地判读） ----------

const weekly = ref<WeeklyReport | null>(null)
const llmConfigured = ref(false)
const llmUpgrading = ref(false)
const showWeekly = ref(false)

const currentConversation = computed(() => conversations.value.find((c) => c.id === selectedConversationId.value))
const isGroup = computed(() => currentConversation.value?.conversation_type === 'group')
// 选人是跨页共享 ref，切页瞬间即有值；会话列表异步返回前类型未知——
// 未解析窗口不渲染任何选人分支，避免群聊被误判成单聊、单聊区闪现一瞬
const conversationResolved = computed(() => currentConversation.value != null)

const bannerVerdict = computed(() => {
    const w = weekly.value
    const v = overview.value?.verdict
    if (w?.source === 'llm') return { text: w.verdict, label: 'AI 周报', isAi: true }
    if (v?.source === 'llm') return { text: v.text, label: 'AI 判读', isAi: true }
    if (w) return { text: w.verdict, label: '本地周报', isAi: false }
    if (v) return { text: v.text, label: '本地判读', isAi: false }
    return { text: '', label: '', isAi: false }
})

function fmtDate(ts: number): string {
    const d = new Date(ts * 1000)
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// ---------- 分析触发（引导卡 CTA / 新鲜度徽标 → 常驻专业视图内的工作台） ----------

function runAnalysisNow() {
    if (!selectedConversationId.value) return
    window.dispatchEvent(new CustomEvent('chrono:run-analysis', { detail: { conversationId: selectedConversationId.value } }))
}

function onAnalysisCompleted() {
    // 工作台终态（完成/部分结果/补评完成）：刷新门面层概览与周报
    if (selectedConversationId.value) void loadOverview(selectedConversationId.value)
}

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
            } else {
                // 跨页共享选人：绕过同 id 早退，驱动本页首次加载
                onConversationChange(selectedConversationId.value, true)
            }
        }
    } catch (e) {
        console.error('加载联系人失败', e)
    } finally {
        loading.value = false
    }
}

function onConversationChange(id: number, force = false) {
    if (!force && selectedConversationId.value === id) return
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
    void loadWeekly(id, epoch) // 周报不阻塞首屏（无基线会话无周报）
}

async function loadWeekly(id: number, epoch: number) {
    weekly.value = null
    showWeekly.value = false
    llmUpgrading.value = false
    try {
        const res = await getWeeklyReport(id)
        if (epoch !== viewEpoch) return
        llmConfigured.value = !!res.llm_configured
        if (!res.ok || !res.report) return
        weekly.value = res.report
        // 本地周报 + 已配 LLM → 自动后台升级一次（轮询直到 AI 版或超时）
        if (res.report.source === 'template' && res.llm_configured) {
            void upgradeWeekly(id, epoch)
        }
    } catch { /* 周报缺位不阻塞脉搏 */ }
}

async function upgradeWeekly(id: number = selectedConversationId.value!, epoch: number = viewEpoch) {
    if (!id || llmUpgrading.value) return
    llmUpgrading.value = true
    try {
        await requestWeeklyLlm(id)
    } catch {
        llmUpgrading.value = false
        return
    }
    for (let i = 0; i < 9; i++) {
        await new Promise((r) => setTimeout(r, 10000))
        if (epoch !== viewEpoch) return // 已切人/卸载，放弃轮询
        try {
            const res = await getWeeklyReport(id)
            if (epoch !== viewEpoch) return
            if (res.ok && res.report) {
                weekly.value = res.report
                if (res.report.source === 'llm') break
            }
        } catch { /* 继续等 */ }
    }
    if (epoch === viewEpoch) llmUpgrading.value = false
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
onUnmounted(() => {
    viewEpoch++ // 让周报轮询等在途循环失效
    disposeSpark()
})
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
    border: none;
    border-radius: 999px;
    padding: 2px 10px;
    cursor: pointer;
}

.pulse-stale-badge:hover {
    background: var(--ct-color-warning);
    color: #FFFFFF;
}

.weekly-toggle {
    margin-left: auto;
    font-size: var(--ct-text-xs);
    padding: 3px 10px;
}

.weekly-detail {
    margin-top: 10px;
    padding: 10px 12px;
    background: var(--ct-bg-sunken);
    border-radius: var(--ct-radius-md);
}

.weekly-verdict {
    margin: 0;
    font-size: var(--ct-text-sm);
    line-height: 1.75;
    color: var(--ct-text-primary);
}

.weekly-meta {
    margin: 8px 0 0;
    font-size: var(--ct-text-xs);
    color: var(--ct-text-tertiary);
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.weekly-regen {
    font-size: var(--ct-text-xs);
    padding: 2px 10px;
}

.weekly-upgrading {
    color: var(--ct-text-tertiary);
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

/* ---------- 专业视图折叠（内嵌分析工作台，样式随组件自包含） ---------- */
.pulse-pro-toggle { width: 100%; }

.pulse-pro-body {
    margin-top: 12px;
    display: flex;
    flex-direction: column;
    gap: 14px;
}

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
}
</style>
