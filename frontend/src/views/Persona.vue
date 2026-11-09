<template>
<section class="persona-page ct-page">
  <!-- 页头：与脉搏/时光同款选人器（选人一次贯通） -->
  <header v-if="conversations.length" class="persona-header fade-in">
    <CtAvatar class="persona-avatar" :src="currentConversation?.avatar" :name="currentConversation?.name || currentConversation?.username || '？'" :size="44" />
    <div class="persona-title-block">
      <h1 class="persona-title">TA 是谁 · 我是谁</h1>
      <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId" :loading="loading"
        @update:conversation-id="onConversationChange" />
    </div>
  </header>

  <div v-else-if="!loading" class="panel persona-empty">
    <div class="panel-head"><span class="panel-title">TA 是谁 · 我是谁</span></div>
    <p class="persona-empty-text">还没有可以画像的聊天记录。</p>
    <button type="button" class="btn primary persona-empty-cta" @click="openSettingsTab('account')">去导入微信数据</button>
  </div>

  <template v-if="selectedConversationId && !isGroup">
    <!-- 镜像双栏：左 TA 的镜像 / 右 我的镜像（同指标同量纲并排） -->
    <div class="mirror-grid">
      <div class="mirror-col">
        <div class="mirror-col-head">
          <span class="mirror-col-dot ta" />TA 的镜像
        </div>
        <PersonaGallery
          :loading="loadingPersonaProfile"
          :contact-name="currentContactName"
          :conversation-id="selectedConversationId"
          :profile="personaProfile"
          :profile-meta="personaProfileMeta"
          :window-info="personaProfileMeta.window"
          :account-wxid="activeAccountWxid || ''"
          :analysis="analysisView"
          :analysis-result="analysisResult"
          :feature-stats="featureStats"
          :sessions="sessions"
          :activity-calendar-summary="activitySummary"
          @generate="showPortraitDialog = true"
        />
        <div class="panel bigfive-slot">
          <BigFivePanel :conversation-id="selectedConversationId" />
        </div>
        <MemeDictionaryPanel :conversation-id="selectedConversationId" />
        <!-- AI 分身入口（§6.3）：画像+语气采样+记忆的 TA 模拟，全屏对话页承接 -->
        <div class="panel avatar-entry">
          <div class="panel-head">
            <div>
              <div class="panel-title">AI 分身</div>
              <div class="panel-sub">以 {{ currentContactName }} 的语气聊聊看——画像缺席时按语气与记忆作答</div>
            </div>
            <div class="panel-actions">
              <router-link class="btn primary" :to="{ path: '/persona/avatar', query: { cid: String(selectedConversationId) } }">开始对话</router-link>
            </div>
          </div>
          <p class="avatar-entry-note">这是基于聊天记录的 AI 模拟，不是本人；模拟止于应用内对话。</p>
        </div>
      </div>

      <div class="mirror-col">
        <div class="mirror-col-head">
          <span class="mirror-col-dot me" />我的镜像
        </div>
        <!-- 我的画像：更新画像默认含自我画像，生成结果在此可见 -->
        <ProfileBriefCard
          kind="self"
          :contact-name="currentContactName"
          :account-wxid="activeAccountWxid || ''"
          :refresh-key="profileRefreshKey"
          @generate="showPortraitDialog = true"
        />
        <MirrorComparePanel :conversation-id="selectedConversationId" />
        <div class="panel persona-footnote">
          「我的镜像」由双方消息统计直出——它是你在这段对话里的样子，
          不等于你在所有人面前的样子。
        </div>
      </div>
    </div>

    <!-- 分享海报工坊（原样迁入，产线模板见 poster/registry.ts） -->
    <PosterStudio :conversation-id="selectedConversationId" :dates="posterDates" :contact-name="currentContactName" />
  </template>

  <!-- 群聊：画像单聊专属（1:1 语义） -->
  <div v-else-if="selectedConversationId && isGroup" class="panel persona-group-hint">
    <p>画像是单聊专属——两个人之间的镜像。群聊发言统计与日报在时光页。</p>
    <div class="persona-group-actions">
      <router-link to="/timeline" class="btn">去时光页 →</router-link>
    </div>
  </div>

  <!-- 画像生成弹窗（画廊头/简卡共用；生成完成刷新画廊与简卡） -->
  <PortraitGenerateDialog
    :visible="showPortraitDialog"
    :display-name="currentContactName"
    :account-wxid="activeAccountWxid || undefined"
    :show-self-panel="true"
    :cancel-key="selectedConversationId || 0"
    @close="showPortraitDialog = false"
    @generated="handlePortraitGenerated"
  />
</section>
</template>

<script setup lang="ts">
import { openSettingsTab } from '@/utils/settingsBus'
import { computed, onMounted, reactive, ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'
import { getAffinityScores } from '@/api/affinity'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import { sharedContactId as selectedConversationId } from '@/utils/contactScope'
import CtAvatar from '@/components/base/CtAvatar.vue'
import PersonaGallery from '@/components/persona/PersonaGallery.vue'
import ProfileBriefCard from '@/components/persona/ProfileBriefCard.vue'
import MemeDictionaryPanel from '@/components/persona/MemeDictionaryPanel.vue'
import MirrorComparePanel from '@/components/persona/MirrorComparePanel.vue'
import BigFivePanel from '@/components/deep/BigFivePanel.vue'
import PosterStudio from '@/components/deep/PosterStudio.vue'
import PortraitGenerateDialog from '@/components/persona/PortraitGenerateDialog.vue'
import { toLocalDateKey } from '@/utils/datetime'

type Conversation = { id: number; name: string; username: string; avatar?: string; conversation_type?: 'private' | 'group' }

/** 画像页（§4.3）：镜像双栏——左 TA（画像档案/大五印象/专属梗词典），
 * 右我（我的画像/镜像对照/短板提示），底部海报工坊。单聊专属。 */

const conversations = ref<Conversation[]>([])
const loading = ref(false)
let viewEpoch = 0 // 切人后丢弃在途异步结果（Analytics/Pulse 同款代数守卫）

const activeAccountWxid = ref('')
const showPortraitDialog = ref(false)
const profileRefreshKey = ref(0)

const currentConversation = computed(() => conversations.value.find((c) => c.id === selectedConversationId.value) || null)
const currentContactName = computed(() => currentConversation.value?.name || currentConversation.value?.username || '')
const isGroup = computed(() => currentConversation.value?.conversation_type === 'group')

// ---------- 画廊素材（PersonaGallery 消费的同款口径，全会话跨度） ----------

const loadingPersonaProfile = ref(false)
const personaProfile = ref<any>(null)
const personaProfileMeta = reactive<any>({ createdAt: null, expiresAt: null, expired: false, estimatedTokens: 0, window: null })
const analysisView = reactive({ timeseries: [] as any[], wordcloud: [] as any[] })
const analysisResult = ref<any>(null)
const featureStats = reactive({ avgResponseTime: 0, medianResponseTime: 0, initiativeRate: 0, wordRatio: 0 })
const sessions = ref<any[]>([])
const activitySummary = ref<any>(null)
const posterDates = reactive({ from: '', to: '' })

function resetGalleryState() {
  personaProfile.value = null
  Object.assign(personaProfileMeta, { createdAt: null, expiresAt: null, expired: false, estimatedTokens: 0, window: null })
  analysisView.timeseries = []
  analysisView.wordcloud = []
  analysisResult.value = null
  Object.assign(featureStats, { avgResponseTime: 0, medianResponseTime: 0, initiativeRate: 0, wordRatio: 0 })
  sessions.value = []
  activitySummary.value = null
  posterDates.from = ''
  posterDates.to = toLocalDateKey(new Date())
}

async function onConversationChange(id: number, force = false) {
  if (!force && selectedConversationId.value === id) return
  selectedConversationId.value = id
  const epoch = ++viewEpoch
  resetGalleryState()
  const conv = conversations.value.find((c) => c.id === id)
  if (!conv || conv.conversation_type === 'group') return
  void loadPersonaProfile(epoch)
  // 画廊素材的日期窗依赖跨度先落位（词云/时序用全会话口径）
  void loadSpan(epoch).then(() => loadGalleryStats(epoch))
}

async function loadPersonaProfile(epoch: number) {
  const conv = currentConversation.value
  if (!conv) return
  loadingPersonaProfile.value = true
  try {
    const res = await api.get_contact_profile(conv.name, activeAccountWxid.value || undefined)
    if (epoch !== viewEpoch) return
    if (res.ok && res.has_profile) {
      personaProfile.value = res.profile || null
      Object.assign(personaProfileMeta, {
        createdAt: res.created_at || null,
        expiresAt: res.expires_at || null,
        expired: Boolean(res.expired),
        estimatedTokens: Number(res.estimated_tokens || 0),
        window: res.window || null,
      })
    } else {
      personaProfile.value = null
      personaProfileMeta.estimatedTokens = Number(res?.estimated_tokens || 0)
    }
  } catch {
    if (epoch === viewEpoch) personaProfile.value = null
  } finally {
    if (epoch === viewEpoch) loadingPersonaProfile.value = false
  }
}

/** 画廊四件原料：分析词云/时序、好感结果、特征统计、会话与活跃日历。 */
async function loadGalleryStats(epoch: number) {
  const id = selectedConversationId.value
  if (!id) return
  try {
    const [analysisRes, affinityRes, rtRes, iniRes, wcRes, sessRes, calRes] = await Promise.all([
      api.get_analysis({ conversation_id: id, from: posterDates.from || '2000-01-01', to: posterDates.to }),
      getAffinityScores(id).catch(() => null),
      api.get_response_times(id).catch(() => null),
      api.get_initiative_stats(id).catch(() => null),
      api.get_word_counts(id, false).catch(() => null),
      api.get_sessions(id, 50, 0).catch(() => null),
      api.get_activity_calendar(id).catch(() => null),
    ])
    if (epoch !== viewEpoch) return
    if (!analysisRes?.error) {
      analysisView.timeseries = analysisRes?.timeseries ?? []
      analysisView.wordcloud = analysisRes?.wordcloud ?? []
    }
    analysisResult.value = affinityRes || null
    if (rtRes?.success && rtRes.data) {
      featureStats.avgResponseTime = rtRes.data.avg || 0
      featureStats.medianResponseTime = rtRes.data.median || 0
    }
    if (iniRes?.success && iniRes.data) featureStats.initiativeRate = iniRes.data.initiative_rate || 0
    if (wcRes?.success && wcRes.data?.overall) featureStats.wordRatio = wcRes.data.overall.char_ratio || 0
    if (sessRes?.success && sessRes.data?.sessions) {
      // 口径与 Analytics.loadSessions 一致：秒→毫秒，duration 保持秒差（画廊同款）
      sessions.value = sessRes.data.sessions.map((s: any) => ({
        ...s,
        start_time: s.start_time * 1000,
        end_time: s.end_time * 1000,
        duration: (s.end_time || 0) - (s.start_time || 0),
      }))
    }
    if (calRes?.success && calRes.data) activitySummary.value = calRes.data.summary ?? null
  } catch (e) {
    console.error('画像页素材加载失败', e)
  }
}

async function loadSpan(epoch: number) {
  const id = selectedConversationId.value
  if (!id) return
  try {
    const res = await api.get_conversation_span(id)
    if (epoch !== viewEpoch) return
    const data = res?.data
    if (data?.from_date) {
      posterDates.from = data.from_date
      posterDates.to = data.to_date || toLocalDateKey(new Date())
    }
  } catch { /* 跨度失败维持占位，海报工坊自兜底 */ }
}

function handlePortraitGenerated() {
  const epoch = viewEpoch
  void loadPersonaProfile(epoch)
  profileRefreshKey.value++
}

async function loadConversations() {
  try {
    await bridgeReady()
    loading.value = true
    let wxid = ''
    try {
      const acct = await api.get_wechat_accounts()
      if (acct?.ok) {
        wxid = acct.active_account_wxid || ''
        activeAccountWxid.value = wxid
      }
    } catch { /* 账号上下文失败按全量列表兜底 */ }
    const res = await api.get_conversation_list(wxid || undefined)
    if (res.ok) {
      conversations.value = res.conversations
      if (selectedConversationId.value && !conversations.value.some((c) => c.id === selectedConversationId.value)) {
        selectedConversationId.value = null
      }
      if (conversations.value.length && !selectedConversationId.value) {
        // 默认选首个单聊（画像单聊专属，群聊不该是落地态）
        const first = conversations.value.find((c) => c.conversation_type !== 'group')
        if (first) onConversationChange(first.id)
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

onMounted(loadConversations)
</script>

<style scoped>
.persona-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}

.persona-title-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.persona-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

/* 镜像双栏：宽屏并排、窄屏堆叠 */
.mirror-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}

@media (max-width: 1080px) {
  .mirror-grid {
    grid-template-columns: 1fr;
  }
}

.mirror-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.mirror-col-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

.mirror-col-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.mirror-col-dot.ta {
  background: #E0A458;
}

.mirror-col-dot.me {
  background: #5A4BC4;
}

/* 大五印象降为一张卡（§4.3）：卡片化承载，查看演变去时光页 */
.bigfive-slot {
  padding: 0;
  overflow: hidden;
}

.bigfive-slot :deep(.panel.big-five) {
  border: none;
  box-shadow: none;
}

.persona-footnote {
  font-size: 13px;
  line-height: 1.6;
  color: var(--ct-text-secondary);
}

.persona-empty-text {
  margin: 0 0 12px;
  color: var(--ct-text-secondary);
}

.persona-empty-cta {
  align-self: flex-start;
}

.persona-group-hint {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.persona-group-hint p {
  margin: 0;
  color: var(--ct-text-secondary);
}

.persona-group-actions {
  display: flex;
  gap: 10px;
}

/* 分身入口卡：边界说明一行小字（全屏对话页有常驻横幅，这里轻量带过） */
.avatar-entry-note {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-text-tertiary);
}
</style>
