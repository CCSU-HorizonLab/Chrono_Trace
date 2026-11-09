<template>
<section class="timeline-page ct-page">
  <!-- 页头：与脉搏页同款选人器（选人一次贯通） -->
  <header v-if="conversations.length" class="tl-header fade-in">
    <CtAvatar class="tl-avatar" :src="currentConversation?.avatar" :name="currentConversation?.name || currentConversation?.username || '？'" :size="44" />
    <div class="tl-title-block">
      <h1 class="tl-title">我们的时光</h1>
      <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId" :loading="loading"
        @update:conversation-id="onConversationChange" />
    </div>
    <router-link v-if="selectedConversationId" to="/analytics" class="btn tl-goto-analytics">分析工作台 →</router-link>
  </header>

  <div v-else-if="!loading" class="panel tl-empty">
    <div class="panel-head"><span class="panel-title">我们的时光</span></div>
    <p class="tl-empty-text">还没有可回味的聊天记录。</p>
    <router-link to="/import" class="btn primary tl-empty-cta">去导入微信数据</router-link>
  </div>

  <template v-if="selectedConversationId && !isGroup">
    <!-- 全局年份轴：会话跨度按年分格 + 章节色块（时间轴叙事的视觉锚）；
         拖选轴段生成区间纪念册（§6.2 产线入口），页脚一键年度报告 -->
    <div v-if="chaptersPayload?.ok && years.length" class="panel tl-year-axis" aria-label="年份总览">
      <div
        ref="axisTrackRef"
        class="axis-track"
        :class="{ selecting: isSelecting }"
        @pointerdown="onAxisPointerDown"
        @pointermove="onAxisPointerMove"
        @pointerup="onAxisPointerUp"
        @pointercancel="clearSelection"
      >
        <template v-for="year in years" :key="year.label">
          <div class="axis-year" :style="{ flexGrow: Math.max(1, year.spanDays) }">
            <span class="axis-year-label">{{ year.label }}</span>
          </div>
        </template>
        <div v-for="(blk, i) in chapterBlocks" :key="'b' + i" class="axis-block"
          :style="{ left: blk.leftPct + '%', width: blk.widthPct + '%', background: blk.color }"
          :title="`第 ${blk.index + 1} 章 · ${blk.range} · ${blk.weeks} 周`" />
        <!-- 拖选高亮：左右压暗 + 选区亮带 -->
        <template v-if="selBand">
          <div class="axis-mask" :style="{ right: 100 - selBand.leftPct + '%' }" />
          <div class="axis-mask" :style="{ left: selBand.leftPct + selBand.widthPct + '%' }" />
          <div class="axis-sel" :style="{ left: selBand.leftPct + '%', width: selBand.widthPct + '%' }" />
        </template>
      </div>
      <div class="axis-caption">现在 →</div>

      <!-- 框选确认浮层：区间 + 天数 + 生成纪念册 -->
      <div v-if="pendingRange && !isSelecting" class="axis-popover">
        <span class="axis-popover-range">{{ pendingRange.from }} ~ {{ pendingRange.to }} · {{ pendingRange.days }} 天</span>
        <button class="btn primary" @click="confirmAlbum">生成纪念册</button>
        <button class="btn" @click="clearSelection">取消</button>
      </div>

      <div class="axis-foot">
        <button class="btn tl-report-btn" :disabled="!spanRange" @click="openYearReport">生成年度报告</button>
        <span class="axis-hint">或在轴上横向拖选一段，生成任意时段的纪念册</span>
      </div>
    </div>

    <!-- 吸顶锚点工具条（沿时光深度口径：章节为叙事骨架） -->
    <div class="tl-toolbar">
      <nav class="anchor-nav" aria-label="时光页导航">
        <button v-for="a in anchors" :key="a.id" class="btn" @click="scrollTo(a.id)">{{ a.label }}</button>
      </nav>
    </div>

    <!-- 叙事骨架：关系章节（章卡 + 过渡 + 弧线；摘要任务在内） -->
    <div :id="anchors[0].id" class="anchor-target">
      <RelationshipChaptersPanel
        :conversation-id="selectedConversationId"
        :view-epoch="viewEpoch"
        :word-segments="wordSegments"
        @chapters-loaded="onChaptersLoaded"
      />
    </div>

    <div v-if="deepError" class="panel state-card">
      <div class="state-text">深度数据加载失败：{{ deepError }}</div>
      <button class="btn" @click="loadDeep">重试</button>
    </div>
    <div v-else-if="deepLoading && !deepPayload" class="skeleton-stack" aria-label="加载中">
      <div class="panel"><div class="skeleton sk-line" /></div>
      <div class="panel"><div class="skeleton sk-line" /></div>
    </div>

    <template v-else-if="deepPayload">
      <!-- 情绪演变：全期周桶 + 好感落点（演变价值在跨章对比，不做章内切片） -->
      <div :id="anchors[1].id" class="anchor-target">
        <DeepEmotionPanel
          :buckets="deepPayload.buckets || []"
          granularity="week"
          :affinity="deepPayload.affinity_history || null"
        />
      </div>

      <!-- 词云演变：重点词排行流动图（全局视角） -->
      <div :id="anchors[2].id" class="anchor-target">
        <WordEvolutionPanel
          :evolution="deepPayload.wordcloud_evolution || { caliber: 'none', coverage_ratio: 0, segments: [] }"
        />
      </div>

      <!-- 表情博物馆：双方 Top 榜 + 节奏 + 自定义表情墙（§6.1） -->
      <div :id="anchors[3].id" class="anchor-target">
        <div v-if="emojiLoading && !emojiStats" class="panel"><div class="skeleton sk-line" /></div>
        <EmojiMuseumPanel v-else :stats="emojiStats" />
      </div>

      <!-- 里程碑：首条/关口/最长沉默 + 情绪拐点（章分界栏） -->
      <div :id="anchors[4].id" class="anchor-target">
        <MilestoneTimeline
          :milestones="deepPayload.milestones || []"
          :turning-points="deepPayload.turning_points || []"
          granularity="week"
          :chapter-spans="deepPayload.chapter_spans || []"
        />
      </div>

      <!-- 深钻折叠：大五演变 / 画像演变（批2 从页签降为折叠入口，工程层保留） -->
      <div :id="anchors[5].id" class="panel tl-drill anchor-target">
        <button class="btn tl-drill-toggle" :aria-expanded="showDrill" @click="showDrill = !showDrill">
          深钻：大五人格演变 · 画像分段演变 {{ showDrill ? '▴' : '▾' }}
        </button>
        <div v-show="showDrill" class="tl-drill-body">
          <Big5EvolutionPanel
            :conversation-id="selectedConversationId"
            :evolution="deepPayload.big5_evolution"
            :view-epoch="viewEpoch"
          />
          <ProfileEvolutionPanel
            :conversation-id="selectedConversationId"
            :view-epoch="viewEpoch"
            :chapter-spans="deepPayload.chapter_spans || []"
            :contact-name="currentConversation?.name || currentConversation?.username"
          />
        </div>
      </div>
    </template>
  </template>

  <!-- 群聊：时光叙事是单聊主视角，群聊指路群摘要 -->
  <div v-else-if="selectedConversationId && isGroup" class="panel tl-hint">
    <p>时光叙事按单聊口径组织。群聊请去分析工作台查看群聊摘要与互动统计。</p>
    <router-link to="/analytics" class="btn">去分析工作台 →</router-link>
  </div>

  <!-- 年度报告/纪念册工坊（§6.2 传播产线） -->
  <ReportStudio
    v-if="reportRange && selectedConversationId"
    :conversation-id="selectedConversationId"
    :contact-name="currentConversation?.name || currentConversation?.username"
    :from="reportRange.from"
    :to="reportRange.to"
    :kind="reportRange.kind"
    @close="reportRange = null"
  />
</section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import { chartPalette } from '@/components/charts/chartTheme'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import { sharedContactId as selectedConversationId } from '@/utils/contactScope'
import CtAvatar from '@/components/base/CtAvatar.vue'
import RelationshipChaptersPanel from '@/components/deep/RelationshipChaptersPanel.vue'
import DeepEmotionPanel from '@/components/deep/DeepEmotionPanel.vue'
import WordEvolutionPanel from '@/components/deep/WordEvolutionPanel.vue'
import MilestoneTimeline from '@/components/deep/MilestoneTimeline.vue'
import Big5EvolutionPanel from '@/components/deep/Big5EvolutionPanel.vue'
import ProfileEvolutionPanel from '@/components/deep/ProfileEvolutionPanel.vue'
import EmojiMuseumPanel from '@/components/deep/EmojiMuseumPanel.vue'
import ReportStudio from '@/components/deep/ReportStudio.vue'
import { toCompactRange, toLocalDateKey } from '@/utils/datetime'

type Conversation = { id: number; name: string; username: string; avatar?: string; conversation_type?: 'private' | 'group' }

const conversations = ref<Conversation[]>([])
const loading = ref(false)
let viewEpoch = 0 // 切人后代数守卫（丢弃在途异步）

// 深度数据（情绪/词云/里程碑/大五/画像共用一次 get_deep_analysis，周桶与章节对齐）
const deepPayload = ref<any>(null)
const deepLoading = ref(false)
const deepError = ref('')
// 章节 payload（年份轴需要 span 与 chapters；由面板 load 后经 emit 回传）
const chaptersPayload = ref<any>(null)
const showDrill = ref(false)
// 表情博物馆（§6.1）：独立快照接口，首算秒级/后续走缓存
const emojiStats = ref<any>(null)
const emojiLoading = ref(false)

const currentConversation = computed(() => conversations.value.find((c) => c.id === selectedConversationId.value))
const isGroup = computed(() => currentConversation.value?.conversation_type === 'group')

const anchors = [
  { id: 'tl-anchor-chapters', label: '章节' },
  { id: 'tl-anchor-emotion', label: '情绪' },
  { id: 'tl-anchor-words', label: '词云' },
  { id: 'tl-anchor-emoji', label: '表情' },
  { id: 'tl-anchor-milestones', label: '里程碑' },
  { id: 'tl-anchor-drill', label: '深钻' },
]

const wordSegments = computed(() => deepPayload.value?.wordcloud_evolution?.segments || [])

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ---------- 年份轴（纯展示总览：年份刻度 + 章节色块） ----------

const spanRange = computed<{ from: number; to: number } | null>(() => {
  const p = chaptersPayload.value
  if (!p?.ok || !p.span?.from_ts || !p.span?.to_ts) return null
  return { from: Number(p.span.from_ts), to: Number(p.span.to_ts) }
})

const years = computed(() => {
  const r = spanRange.value
  if (!r) return []
  const out: Array<{ label: string; spanDays: number }> = []
  const start = new Date(r.from * 1000)
  const end = new Date(r.to * 1000)
  let y = start.getFullYear()
  while (y <= end.getFullYear()) {
    const yStart = new Date(y, 0, 1).getTime() / 1000
    const yEnd = new Date(y + 1, 0, 1).getTime() / 1000
    const from = Math.max(r.from, yStart)
    const to = Math.min(r.to, yEnd)
    out.push({ label: String(y), spanDays: Math.max(1, (to - from) / 86400) })
    y++
  }
  return out
})

const chapterBlocks = computed(() => {
  const r = spanRange.value
  const chapters: Array<any> = chaptersPayload.value?.chapters || []
  if (!r || !chapters.length) return []
  const total = r.to - r.from || 1
  const palette = chartPalette()
  return chapters.map((ch) => ({
    index: ch.index,
    weeks: ch.stats?.weeks ?? 0,
    range: toCompactRange(ch.from_ts, ch.to_ts),
    leftPct: ((ch.from_ts - r.from) / total) * 100,
    widthPct: Math.max(1.5, ((ch.to_ts - ch.from_ts) / total) * 100),
    color: palette[ch.index % palette.length],
  }))
})

function onChaptersLoaded(payload: any) {
  chaptersPayload.value = payload
}

// ---------- 产线入口：年度报告一键 + 轴段拖选纪念册（§6.2） ----------

const axisTrackRef = ref<HTMLElement | null>(null)
const isSelecting = ref(false)
let dragFromPct = 0
let dragToPct = 0
// 已松手的框选区间（浮层确认态）：null = 无选区
const pendingRange = ref<{ from: string; to: string; days: number } | null>(null)
// 工坊打开窗口（kind: year 一键年度报告 / album 框选纪念册）
const reportRange = ref<{ from: string; to: string; kind: 'year' | 'album' } | null>(null)

const selBand = computed(() => {
  if (!isSelecting.value && !pendingRange.value) return null
  const left = Math.min(dragFromPct, dragToPct)
  const right = Math.max(dragFromPct, dragToPct)
  if (right - left <= 0.2) return null
  return { leftPct: left, widthPct: right - left }
})

function axisPctOf(e: PointerEvent): number {
  const track = axisTrackRef.value
  if (!track) return 0
  const rect = track.getBoundingClientRect()
  return Math.min(100, Math.max(0, ((e.clientX - rect.left) / rect.width) * 100))
}

function pctToTs(pct: number): number {
  const r = spanRange.value!
  return Math.round(r.from + (pct / 100) * (r.to - r.from))
}

function onAxisPointerDown(e: PointerEvent) {
  if (!spanRange.value || e.button !== 0) return
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  isSelecting.value = true
  pendingRange.value = null
  dragFromPct = dragToPct = axisPctOf(e)
}

function onAxisPointerMove(e: PointerEvent) {
  if (!isSelecting.value) return
  dragToPct = axisPctOf(e)
}

function onAxisPointerUp() {
  if (!isSelecting.value) return
  isSelecting.value = false
  const r = spanRange.value
  if (!r) return
  const fromTs = pctToTs(Math.min(dragFromPct, dragToPct))
  const toTs = pctToTs(Math.max(dragFromPct, dragToPct))
  const days = Math.round((toTs - fromTs) / 86400)
  // 轻点（<14 天）视为误触不清浮层直接清选区
  if (days < 14) {
    clearSelection()
    return
  }
  pendingRange.value = {
    from: toLocalDateKey(new Date(fromTs * 1000)),
    to: toLocalDateKey(new Date(toTs * 1000)),
    days,
  }
}

function clearSelection() {
  isSelecting.value = false
  pendingRange.value = null
}

function confirmAlbum() {
  const pending = pendingRange.value
  if (!pending) return
  reportRange.value = { from: pending.from, to: pending.to, kind: 'album' }
  clearSelection()
}

// 一键年度报告：跨度内最晚的一个自然年（交集不足整年也如实按交集出）
function openYearReport() {
  const r = spanRange.value
  if (!r) return
  const year = new Date(r.to * 1000).getFullYear()
  const yearStart = Math.round(new Date(year, 0, 1).getTime() / 1000)
  const yearEnd = Math.round(new Date(year + 1, 0, 1).getTime() / 1000) - 1
  const fromTs = Math.max(r.from, yearStart)
  const toTs = Math.min(r.to, yearEnd)
  if (toTs - fromTs < 14 * 86400) return
  reportRange.value = {
    from: toLocalDateKey(new Date(fromTs * 1000)),
    to: toLocalDateKey(new Date(toTs * 1000)),
    kind: 'year',
  }
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
      } else if (selectedConversationId.value) {
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
  showDrill.value = false
  chaptersPayload.value = null
  clearSelection()
  reportRange.value = null
  const epoch = ++viewEpoch
  deepPayload.value = null
  emojiStats.value = null
  void loadDeep(epoch)
  void loadEmoji(epoch)
}

async function loadEmoji(epoch: number = viewEpoch) {
  const id = selectedConversationId.value
  if (!id) return
  emojiLoading.value = true
  try {
    await bridgeReady()
    const res = await api.get_emoji_stats(id)
    if (epoch !== viewEpoch) return
    emojiStats.value = res?.ok ? res : null
  } catch {
    if (epoch === viewEpoch) emojiStats.value = null
  } finally {
    if (epoch === viewEpoch) emojiLoading.value = false
  }
}

async function loadDeep(epoch: number = viewEpoch) {
  const id = selectedConversationId.value
  if (!id) return
  deepLoading.value = true
  deepError.value = ''
  try {
    await bridgeReady()
    // 时光页 = 全会话叙事：日期窗留空（后端全会话口径），周桶与章节边界对齐
    const res = await api.get_deep_analysis(id, '', '', 'week')
    if (epoch !== viewEpoch) return
    if (!res?.ok) {
      deepError.value = res?.error || '未知错误'
      deepPayload.value = null
      return
    }
    deepPayload.value = res
  } catch (e: any) {
    if (epoch === viewEpoch) {
      deepError.value = e?.message || '请求失败'
      deepPayload.value = null
    }
  } finally {
    if (epoch === viewEpoch) deepLoading.value = false
  }
}

onMounted(() => { void loadConversations() })
</script>

<style scoped>
.tl-header {
  display: flex;
  align-items: center;
  gap: 14px;
}

.tl-avatar {
  flex-shrink: 0;
}

.tl-title-block {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.tl-title {
  font-size: var(--ct-text-xl);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
  white-space: nowrap;
}

.tl-goto-analytics {
  flex-shrink: 0;
  text-decoration: none;
}

.tl-empty-text, .tl-hint p {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-base);
}

.tl-empty-cta {
  display: inline-block;
  margin-top: 8px;
  text-decoration: none;
}

/* ---------- 年份轴 ---------- */
.tl-year-axis {
  padding-bottom: 10px;
}

.axis-track {
  position: relative;
  display: flex;
  height: 40px;
  margin: 14px 12px 4px;
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
  overflow: hidden;
  cursor: ew-resize;
  touch-action: none;
  user-select: none;
}

.axis-track.selecting {
  cursor: grabbing;
}

.axis-year {
  position: relative;
  border-left: 1px solid var(--ct-border-color);
  min-width: 0;
}

.axis-year:first-child {
  border-left: none;
}

.axis-year-label {
  position: absolute;
  top: 3px;
  left: 6px;
  font-size: 10px;
  color: var(--ct-text-tertiary);
}

.axis-block {
  position: absolute;
  bottom: 3px;
  height: 12px;
  border-radius: 3px;
  opacity: 0.85;
  cursor: default;
  pointer-events: none;
}

/* 拖选高亮：选区亮带 + 两侧压暗（指针交互期间即时反馈） */
.axis-mask {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  background: var(--ct-color-primary-tint);
  opacity: 0.55;
  pointer-events: none;
}

.axis-sel {
  position: absolute;
  top: 0;
  bottom: 0;
  border-left: 2px solid var(--ct-color-primary);
  border-right: 2px solid var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
  pointer-events: none;
}

.axis-caption {
  text-align: right;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  padding-right: 14px;
}

/* 框选确认浮层：骑在选区上方（锚定面板右侧，避免溢出屏幕） */
.axis-popover {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin: 6px 12px 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.axis-popover-range {
  font-variant-numeric: tabular-nums;
}

.axis-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 12px 0;
}

.tl-report-btn {
  flex: none;
}

.axis-hint {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
}

/* ---------- 吸顶工具条 ---------- */
.tl-toolbar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: 6px 10px;
  margin-bottom: 14px;
}

.anchor-nav {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.anchor-target {
  scroll-margin-top: 64px;
}

/* ---------- 深钻折叠 ---------- */
.tl-drill-toggle {
  width: 100%;
}

.tl-drill-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 12px;
}

.skeleton-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sk-line {
  height: 180px;
  border-radius: var(--ct-radius-md);
}

.state-card {
  display: flex;
  align-items: center;
  gap: 12px;
}

.state-text {
  color: var(--ct-color-error);
}
</style>
