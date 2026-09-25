<template>
  <Teleport to="body">
    <div v-if="visible" class="rfd-mask" @click.self="close" @wheel="handleMaskWheel">
      <div class="rfd-panel">
        <!-- 弹窗顶栏：干净无重复徽章、显式关闭图标 -->
        <div class="rfd-head">
          <div class="rfd-head-left-box">
            <div class="rfd-head-avatar">
              <img
                v-if="effectiveContactAvatar && !avatarLoadErrors[effectiveContactAvatar]"
                :src="effectiveContactAvatar"
                class="rfd-head-avatar-img"
                referrerpolicy="no-referrer"
                alt=""
                @error="avatarLoadErrors[effectiveContactAvatar] = true"
              />
              <svg v-else class="rfd-head-avatar-svg" viewBox="0 0 36 36" fill="none">
                <rect width="36" height="36" rx="8" fill="#ede9fe" />
                <circle cx="18" cy="13" r="5.5" fill="#7c4dff" />
                <path d="M7 29C7 24.0294 11.0294 20 16 20H20C24.9706 20 29 24.0294 29 29V31C29 32.1046 28.1046 33 27 33H9C7.89543 33 7 32.1046 7 31V29Z" fill="#7c4dff" />
              </svg>
            </div>
            <div class="rfd-title-wrap">
              <div class="rfd-title-row">
                <span class="rfd-title">记忆管理</span>
                <span class="rfd-name-tag">{{ displayName || '联系人' }}</span>
              </div>
              <div class="rfd-sub">
                <template v-if="loading">正在同步联系人结构化记忆与对话溯源…</template>
                <template v-else>
                  共 {{ factCount }} 条记忆（<strong>{{ enabledFactCount }} 条已启用</strong> · {{ Math.max(0, factCount - enabledFactCount) }} 条已停用） · 会话 ID {{ conversationId }}
                </template>
              </div>
            </div>
          </div>
          <button type="button" class="rfd-close-btn" title="关闭" @click="close">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- 顶部检索与过滤栏：严格单行、图标不压字、浅灰底槽分段器、横向刷新按钮 -->
        <div class="rfd-toolbar">
          <div class="rfd-search-box">
            <svg class="rfd-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              v-model="keyword"
              type="text"
              class="rfd-search-input"
              placeholder="搜索当前页的记忆或对话内容…"
            />
            <button
              v-if="keyword"
              type="button"
              class="rfd-search-clear"
              title="清空搜索"
              @click="keyword = ''"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="rfd-seg">
            <button
              type="button"
              class="rfd-seg-btn"
              :class="{ active: !showDisabled }"
              @click="showDisabled = false"
            >
              已启用 <span class="rfd-seg-count">{{ enabledFactCount }}</span>
            </button>
            <button
              type="button"
              class="rfd-seg-btn"
              :class="{ active: showDisabled }"
              @click="showDisabled = true"
            >
              已停用 <span class="rfd-seg-count">{{ Math.max(0, factCount - enabledFactCount) }}</span>
            </button>
          </div>

          <select v-model="kindFilter" class="rfd-select" title="按记忆类型筛选">
            <option value="">全部类型</option>
            <option v-for="k in kinds" :key="k.kind" :value="k.kind">
              {{ kindLabel(k.kind) }} ({{ k.count }})
            </option>
          </select>

          <select v-model="sortBy" class="rfd-select" title="排序方式">
            <option value="time_desc">时间 新→旧</option>
            <option value="time_asc">时间 旧→新</option>
            <option value="conf_desc">置信度 高→低</option>
          </select>

          <button
            type="button"
            class="rfd-refresh-btn"
            :disabled="loading"
            title="刷新当前记忆列表"
            @click="load(page)"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
              stroke-linecap="round"
              stroke-linejoin="round"
              :class="{ 'rfd-spin': loading }"
            >
              <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
            <span>{{ loading ? '刷新中' : '刷新' }}</span>
          </button>
        </div>

        <!-- 状态提示 -->
        <div v-if="error" class="rfd-status rfd-error">
          加载失败：{{ error }}<br />
          <span class="rfd-hint">若提示接口缺失，请完全退出并重启应用</span>
        </div>
        <div v-else-if="!loading && filtered.length === 0" class="rfd-status">
          <template v-if="facts.length > 0">没有匹配的记忆条目</template>
          <template v-else-if="documentCount > 0">
            索引包含 {{ documentCount }} 条文档，但尚未抽取到结构化记忆事实<br />
            <span class="rfd-hint">该联系人可能只建立了文档索引；记忆事实会在回复与建议链路中逐步沉淀</span>
          </template>
          <template v-else>该联系人还没有任何记忆事实</template>
        </div>

        <!-- 记忆卡片列表 -->
        <div ref="listElement" class="rfd-list">
          <div
            v-for="fact in filtered"
            :key="fact.id"
            class="rfd-item"
            :class="{ disabled: !fact.enabled, sensitive: fact.sensitive }"
          >
            <!-- 记忆单元元信息头部 -->
            <div class="rfd-item-head">
              <div class="rfd-head-left">
                <!-- 说话人身份勋章 -->
                <span class="rfd-speaker-badge" :class="parseFact(fact).isSelf ? 'self' : 'contact'">
                  <div class="rfd-badge-avatar">
                    <img
                      v-if="getBubbleAvatar(parseFact(fact).isSelf) && !avatarLoadErrors[getBubbleAvatar(parseFact(fact).isSelf)]"
                      :src="getBubbleAvatar(parseFact(fact).isSelf)"
                      class="rfd-avatar-img"
                      referrerpolicy="no-referrer"
                      alt=""
                      @error="avatarLoadErrors[getBubbleAvatar(parseFact(fact).isSelf)] = true"
                    />
                    <svg v-else class="rfd-avatar-svg" viewBox="0 0 36 36" fill="none">
                      <rect width="36" height="36" rx="3" :fill="parseFact(fact).isSelf ? '#7c4dff' : '#059669'" />
                      <circle cx="18" cy="13" r="5.5" fill="#ffffff" />
                      <path d="M7 29C7 24.0294 11.0294 20 16 20H20C24.9706 20 29 24.0294 29 29V31C29 32.1046 28.1046 33 27 33H9C7.89543 33 7 32.1046 7 31V29Z" fill="#ffffff" />
                    </svg>
                  </div>
                  <span class="rfd-speaker-name">{{ parseFact(fact).isSelf ? '我提到' : `${displayName || '对方'} 提到` }}</span>
                </span>

                <!-- 状态与分类标签 -->
                <span class="rfd-chip" :class="fact.enabled ? 'active' : 'off'">
                  {{ fact.enabled ? '已启用' : fact.user_action === 'inaccurate' ? '已标记不准确' : '已忘记' }}
                </span>
                <span v-if="fact.kind" class="rfd-kind">{{ kindLabel(fact.kind) }}</span>
              </div>

              <div class="rfd-head-right">
                <span v-if="fact.as_of" class="rfd-time">{{ formatDate(fact.as_of) }}</span>
                <span class="rfd-conf" :class="confClass(fact.confidence)">置信 {{ Math.round((fact.confidence ?? 0) * 100) }}%</span>
                <span v-if="fact.sensitive" class="rfd-sens" title="敏感记忆：默认不参与建议，仅供查看">敏感</span>
              </div>
            </div>

            <!-- 核心记忆事实陈述（大字直观重点突出） -->
            <div class="rfd-statement-box">
              <span class="rfd-quote-mark">“</span>
              <span class="rfd-statement-text">{{ parseFact(fact).statement }}</span>
              <span class="rfd-quote-mark">”</span>
            </div>

            <!-- 微信对话现场还原窗口 -->
            <div v-if="!fact.sensitive || revealed[fact.id]" class="rfd-wechat-window">
              <div class="rfd-wechat-header">
                <span class="rfd-chat-title">💬 微信对话现场还原</span>
              </div>

              <div class="rfd-wechat-body">
                <template v-for="(bubble, idx) in parseFact(fact).bubbles" :key="bubble.id || idx">
                  <!-- 时间标签 -->
                  <div
                    v-if="bubble.timeText && (idx === 0 || bubble.timeText !== parseFact(fact).bubbles[idx - 1]?.timeText)"
                    class="rfd-chat-time"
                  >
                    {{ bubble.timeText }}
                  </div>

                  <!-- 消息行（左侧对方，右侧我方） -->
                  <div class="rfd-msg-row" :class="bubble.isSelf ? 'right' : 'left'">
                    <!-- 消息头像 (带微信默认头像兜底，彻底杜绝大字文字头像) -->
                    <div class="rfd-msg-avatar" :class="bubble.isSelf ? 'self' : 'contact'">
                      <img
                        v-if="getBubbleAvatar(bubble.isSelf) && !avatarLoadErrors[getBubbleAvatar(bubble.isSelf)]"
                        :src="getBubbleAvatar(bubble.isSelf)"
                        class="rfd-avatar-img"
                        referrerpolicy="no-referrer"
                        :alt="bubble.isSelf ? '我' : (displayName || '对方')"
                        @error="avatarLoadErrors[getBubbleAvatar(bubble.isSelf)] = true"
                      />
                      <!-- 微信经典灰色头像 SVG 兜底 -->
                      <svg v-else class="rfd-avatar-svg" viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <rect width="36" height="36" rx="4" :fill="bubble.isSelf ? '#10b981' : '#dfdfdf'" />
                        <circle cx="18" cy="13" r="5.5" fill="#ffffff" />
                        <path d="M7 29C7 24.0294 11.0294 20 16 20H20C24.9706 20 29 24.0294 29 29V31C29 32.1046 28.1046 33 27 33H9C7.89543 33 7 32.1046 7 31V29Z" fill="#ffffff" />
                      </svg>
                    </div>

                    <div class="rfd-bubble" :class="[bubble.isSelf ? 'right' : 'left', { anchor: bubble.isAnchor }]">
                      <span class="rfd-bubble-text">{{ bubble.text }}</span>
                      <span v-if="bubble.isAnchor" class="rfd-anchor-badge" title="此条消息是触发该记忆抽取的关键锚点">
                        ★ 记忆锚点
                      </span>
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <!-- 敏感记忆遮罩 -->
            <div v-else class="rfd-sensitive-mask" @click="reveal(fact)">
              <Lock :size="15" />
              <span>敏感记忆对话现场已脱敏保护，点击解锁查看现场</span>
            </div>

            <!-- 操作按钮栏 -->
            <div class="rfd-actions">
              <template v-if="fact.enabled">
                <button
                  class="rfd-btn warn"
                  :disabled="busy[fact.id]"
                  title="标记为不准确，退出建议并修正权重"
                  @click="feedback(fact, 'inaccurate')"
                >
                  不准确
                </button>
                <button
                  class="rfd-btn danger"
                  :disabled="busy[fact.id]"
                  title="让系统彻底忘记此条记忆"
                  @click="feedback(fact, 'forget')"
                >
                  忘记这条
                </button>
              </template>
              <button
                v-else
                class="rfd-btn restore"
                :disabled="busy[fact.id]"
                title="重新启用该记忆参与建议"
                @click="feedback(fact, 'restore')"
              >
                恢复参与
              </button>
            </div>
          </div>
        </div>

        <div v-if="!loading && !error && factCount > 0" class="rfd-pagination">
          <span class="rfd-page-info">显示第 {{ pageStart }}–{{ pageEnd }} 条 · 共 {{ factCount }} 条</span>
          <div class="rfd-page-actions">
            <button class="rfd-page-btn" :disabled="page <= 1" @click="goToPage(page - 1)">
              <ChevronLeft :size="14" />
              <span>上一页</span>
            </button>
            <span class="rfd-page-num">{{ page }} <span class="rfd-page-slash">/</span> {{ totalPages }}</span>
            <button class="rfd-page-btn" :disabled="page >= totalPages" @click="goToPage(page + 1)">
              <span>下一页</span>
              <ChevronRight :size="14" />
            </button>
          </div>
        </div>

        <!-- 弹窗底栏提示 -->
        <div class="rfd-foot">
          <span class="rfd-foot-dot"></span>
          <span>「不准确」和「忘记」立即生效且不会被重建索引复活；「不准确」同时会作为高置信修正样本反馈给系统。</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { Lock, Search, X, RotateCw, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { api } from '@/api/bridge'
import { showConfirm, showDialog } from '@/utils/dialog'

type EvidenceMessage = {
  id: number
  is_sender: boolean
  timestamp: number
  text: string
}

type RagFact = {
  id: number
  subject?: string | null
  kind?: string | null
  content: string
  as_of?: number | null
  confidence?: number | null
  sensitive: boolean
  enabled: boolean
  user_action?: string | null
  evidence_messages?: EvidenceMessage[]
  evidence_excerpts?: string[]
}

type ChatBubbleItem = {
  id?: number | string
  isSelf: boolean
  senderName: string
  avatar: string
  timeText?: string
  text: string
  isAnchor: boolean
}

const props = defineProps<{
  visible: boolean
  conversationId: number | null
  accountWxid?: string
  displayName?: string
  avatarUrl?: string
  userAvatarUrl?: string
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const facts = ref<RagFact[]>([])
const listElement = ref<HTMLElement | null>(null)
const documentCount = ref(0)
const factCount = ref(0)
const enabledFactCount = ref(0)
const page = ref(1)
const pageSize = 50
const totalPages = computed(() => Math.max(1, Math.ceil(factCount.value / pageSize)))
const pageStart = computed(() => (page.value - 1) * pageSize + 1)
const pageEnd = computed(() => Math.min(page.value * pageSize, factCount.value))
const resolvedAccount = ref('')
const contactAvatar = ref('')
const userAvatar = ref('')
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const showDisabled = ref(false)
const sortBy = ref<'time_desc' | 'time_asc' | 'conf_desc'>('time_desc')
const kindFilter = ref('')
const kinds = ref<{ kind: string; count: number }[]>([])
const busy = reactive<Record<number, boolean>>({})
const revealed = reactive<Record<number, boolean>>({})
const avatarLoadErrors = reactive<Record<string, boolean>>({})
let loadSequence = 0

const effectiveContactAvatar = computed(() => contactAvatar.value || props.avatarUrl || '')
const effectiveUserAvatar = computed(() => userAvatar.value || props.userAvatarUrl || '')

function getBubbleAvatar(isSelf: boolean): string {
  return isSelf ? effectiveUserAvatar.value : effectiveContactAvatar.value
}

/**
 * 拦截遮罩层及弹窗边界的滚轮穿透，确保底层被遮罩的页面绝对不会滚动
 */
function handleMaskWheel(e: WheelEvent) {
  const listEl = listElement.value
  const target = e.target as Node | null
  if (!listEl || !target || !listEl.contains(target)) {
    e.preventDefault()
    return
  }
  const { scrollTop, scrollHeight, clientHeight } = listEl
  if (scrollHeight <= clientHeight) {
    e.preventDefault()
    return
  }
  const isAtTop = scrollTop <= 0 && e.deltaY < 0
  const isAtBottom = scrollTop + clientHeight >= scrollHeight - 1 && e.deltaY > 0
  if (isAtTop || isAtBottom) {
    e.preventDefault()
  }
}

function lockBodyScroll(lock: boolean) {
  const targets = [
    document.documentElement,
    document.body,
    document.querySelector('.settings-page') as HTMLElement | null,
    document.querySelector('.ct-content') as HTMLElement | null,
  ]
  for (const el of targets) {
    if (!el) continue
    if (lock) {
      if (el.dataset.rfdPrevOverflow === undefined) {
        el.dataset.rfdPrevOverflow = el.style.overflow || ''
      }
      el.style.overflow = 'hidden'
    } else if (el.dataset.rfdPrevOverflow !== undefined) {
      el.style.overflow = el.dataset.rfdPrevOverflow
      delete el.dataset.rfdPrevOverflow
    }
  }
}

const filtered = computed(() =>
  facts.value.filter((f) => {
    if (showDisabled.value && f.enabled) return false
    if (!showDisabled.value && !f.enabled) return false
    if (keyword.value.trim()) {
      const q = keyword.value.trim().toLowerCase()
      return (
        f.content.toLowerCase().includes(q) ||
        (f.evidence_messages || []).some((m) => m.text.toLowerCase().includes(q))
      )
    }
    return true
  }),
)

function kindLabel(kind: string): string {
  const map: Record<string, string> = {
    preference_like: '偏好·喜欢',
    preference_dislike: '偏好·不喜欢',
    health: '健康',
    plan_or_appointment: '计划/约定',
    promise_or_commitment: '承诺/约定',
    hobby_or_game: '兴趣/游戏',
    food_or_place: '饮食/地点',
    personal_profile: '个人情况',
    relationship_boundary: '关系边界',
    recurring_habit: '习惯',
    purchase_or_price: '消费',
    event: '事件',
    preference: '偏好',
    personal_fact: '个人事实',
    relation_state: '关系状态',
    boundary: '边界',
    plan: '计划',
    promise: '承诺',
  }
  return map[kind] || kind
}

function formatDate(ts?: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatMessageTime(ts?: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const date = String(d.getDate()).padStart(2, '0')
  const hours = String(d.getHours()).padStart(2, '0')
  const minutes = String(d.getMinutes()).padStart(2, '0')
  return `${month}-${date} ${hours}:${minutes}`
}

function confClass(conf?: number | null): string {
  const c = conf ?? 0
  if (c >= 0.8) return 'high'
  if (c >= 0.5) return 'med'
  return 'low'
}

function reveal(fact: RagFact) {
  if (fact.sensitive) revealed[fact.id] = true
}

/**
 * 将混杂的记忆内容解析为主体角色、核心陈述以及高保真的微信气泡列表
 */
function parseFact(fact: RagFact) {
  const content = (fact.content || '').trim()
  const match = content.match(/^(我|对方)提到[：:]([\s\S]*?)(?:\n相关上下文[：:]([\s\S]*))?$/)

  let speakerLabel = fact.subject === '我' ? '我' : fact.subject === '对方' ? '对方' : ''
  let statement = content
  let contextRaw = ''

  if (match) {
    speakerLabel = match[1]
    statement = match[2].trim()
    contextRaw = (match[3] || '').trim()
  }

  const isSelf = speakerLabel === '我'
  const bubbles: ChatBubbleItem[] = []

  // 1. 优先使用后端查出的结构化消息证据
  if (fact.evidence_messages && fact.evidence_messages.length > 0) {
    let hasAnchor = false
    for (const em of fact.evidence_messages) {
      const isAnchor =
        !hasAnchor &&
        Boolean(
          statement &&
            (em.text.includes(statement) ||
              statement.includes(em.text) ||
              fact.evidence_messages.length === 1),
        )
      if (isAnchor) hasAnchor = true

      bubbles.push({
        id: em.id,
        isSelf: em.is_sender,
        senderName: em.is_sender ? '我' : (props.displayName || '对方'),
        avatar: getBubbleAvatar(em.is_sender),
        timeText: formatMessageTime(em.timestamp),
        text: em.text,
        isAnchor,
      })
    }
  } else if (contextRaw) {
    // 2. 降级：从“相关上下文：我: xxx / 对方: yyy”中拆解微型对话流
    const turns = contextRaw.split(/\s+\/\s+/).filter(Boolean)
    let foundAnchor = false

    for (let i = 0; i < turns.length; i++) {
      const turn = turns[i]
      const turnMatch = turn.match(/^(我|对方)[：:]([\s\S]*)$/)
      const turnIsSelf = turnMatch ? turnMatch[1] === '我' : false
      const turnText = turnMatch ? turnMatch[2].trim() : turn.trim()
      const isAnchor =
        !foundAnchor &&
        Boolean(statement && (turnText.includes(statement) || statement.includes(turnText)))
      if (isAnchor) foundAnchor = true

      bubbles.push({
        id: `turn-${i}`,
        isSelf: turnIsSelf,
        senderName: turnIsSelf ? '我' : (props.displayName || '对方'),
        avatar: getBubbleAvatar(turnIsSelf),
        text: turnText,
        isAnchor,
      })
    }

    // 若对话中未完全匹配核心语句，将核心语句作为锚点气泡插入
    if (!foundAnchor && statement) {
      bubbles.push({
        id: 'anchor-statement',
        isSelf,
        senderName: isSelf ? '我' : (props.displayName || '对方'),
        avatar: getBubbleAvatar(isSelf),
        text: statement,
        isAnchor: true,
      })
    }
  } else {
    // 3. 兜底单条气泡
    bubbles.push({
      id: 'statement',
      isSelf,
      senderName: isSelf ? '我' : (props.displayName || '对方'),
      avatar: getBubbleAvatar(isSelf),
      text: statement,
      isAnchor: true,
    })
  }

  return {
    isSelf,
    speakerLabel,
    statement,
    bubbles,
  }
}

watch([sortBy, kindFilter], () => {
  page.value = 1
  load(1)
})

async function load(targetPage = page.value) {
  if (!props.conversationId) return
  const requestId = ++loadSequence
  loading.value = true
  error.value = ''
  try {
    // 若当前未获取到用户头像，主动调用当前用户 profile
    if (!userAvatar.value && !props.userAvatarUrl) {
      try {
        const uRes = await api.get_current_user_profile(props.accountWxid || '')
        if (uRes?.ok && uRes?.profile?.avatar) {
          userAvatar.value = String(uRes.profile.avatar).trim()
        }
      } catch {}
    }

    const res = await api.get_contact_facts(
      props.conversationId, props.accountWxid || '', pageSize, (targetPage - 1) * pageSize,
      sortBy.value, kindFilter.value,
    )
    if (requestId !== loadSequence || !props.visible) return
    if (res?.ok) {
      if (res.contact_avatar) contactAvatar.value = String(res.contact_avatar).trim()
      if (res.user_avatar) userAvatar.value = String(res.user_avatar).trim()

      facts.value = (res.facts || []).map((fact: RagFact) => ({
        ...fact,
        enabled: Boolean(fact.enabled),
      }))
      documentCount.value = Number(res.document_count || 0)
      factCount.value = Number(res.fact_count ?? res.raw_fact_count ?? facts.value.length)
      enabledFactCount.value = Number(res.enabled_fact_count ?? 0)
      kinds.value = (res.kinds || []) as { kind: string; count: number }[]
      resolvedAccount.value = String(res.resolved_account_wxid || '')
      page.value = targetPage
      if (listElement.value) listElement.value.scrollTop = 0
    } else {
      error.value = String(res?.error || '未知错误')
    }
  } catch (e: any) {
    if (requestId !== loadSequence || !props.visible) return
    const msg = String(e?.message || e)
    error.value = msg.includes('get_contact_facts')
      ? '后端缺少该接口，请完全退出并重启应用（新功能需要后端进程重启后生效）'
      : msg
  } finally {
    if (requestId === loadSequence) loading.value = false
  }
}

function goToPage(targetPage: number) {
  if (loading.value || targetPage < 1 || targetPage > totalPages.value) return
  keyword.value = ''
  load(targetPage)
}

async function feedback(fact: RagFact, action: 'inaccurate' | 'forget' | 'restore') {
  if (action === 'forget') {
    const ok = await showConfirm({
      title: '忘记这条记忆',
      message: '确定让系统忘记这条记忆吗？\n它将立即退出所有回复建议，且重建索引不会恢复。',
      type: 'warning',
      confirmText: '确认忘记',
      cancelText: '取消',
    })
    if (!ok) return
  }
  busy[fact.id] = true
  try {
    const res = await api.set_fact_feedback(fact.id, action)
    if (res?.ok) {
      await load()
    } else {
      await showDialog({
        title: '操作失败',
        message: String(res?.error || '未知错误'),
        type: 'error',
      })
    }
  } catch (e: any) {
    await showDialog({
      title: '操作异常',
      message: String(e?.message || e),
      type: 'error',
    })
  } finally {
    busy[fact.id] = false
  }
}

function close() {
  emit('close')
}

watch(
  [() => props.visible, () => props.conversationId, () => props.accountWxid],
  ([visible]) => {
    lockBodyScroll(Boolean(visible))
    if (visible) {
      page.value = 1
      facts.value = []
      factCount.value = 0
      enabledFactCount.value = 0
      keyword.value = ''
      showDisabled.value = false
      Object.keys(revealed).forEach((k) => delete revealed[Number(k)])
      load(1)
    } else {
      loadSequence++
      loading.value = false
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  lockBodyScroll(false)
})
</script>

<style scoped>
.rfd-mask {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(15, 23, 42, 0.48);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  overscroll-behavior: contain;
}

.rfd-panel {
  width: min(820px, calc(100vw - 36px));
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--ct-bg-card, #ffffff);
  border: 1px solid var(--ct-border, rgba(148, 163, 184, 0.24));
  border-radius: 16px;
  box-shadow:
    0 24px 60px rgba(15, 23, 42, 0.28),
    0 4px 16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
  overscroll-behavior: contain;
}

/* 顶栏：干净无重复胶囊、显式关闭图标 */
.rfd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  background: var(--ct-bg-card, #ffffff);
  border-bottom: 1px solid var(--ct-border, #f1f5f9);
}
.rfd-head-left-box {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.rfd-head-avatar {
  width: 38px;
  height: 38px;
  border-radius: 9px;
  overflow: hidden;
  flex-shrink: 0;
  border: 1px solid rgba(124, 77, 255, 0.18);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
}
.rfd-head-avatar-img,
.rfd-head-avatar-svg {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.rfd-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.rfd-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rfd-title {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--ct-text-primary, #0f172a);
}
.rfd-name-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 6px;
  background: #f3f0ff;
  color: #6d28d9;
}
.rfd-sub {
  font-size: 12px;
  color: var(--ct-text-secondary, #64748b);
  line-height: 1.4;
}
.rfd-sub strong {
  color: #059669;
  font-weight: 600;
}
.rfd-close-btn {
  width: 32px !important;
  height: 32px !important;
  padding: 0 !important;
  border-radius: 8px !important;
  border: 1px solid #e2e8f0 !important;
  background: #f8fafc !important;
  color: #64748b !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s ease;
}
.rfd-close-btn:hover {
  background: #fef2f2 !important;
  color: #ef4444 !important;
  border-color: #fecaca !important;
}

/* 顶部过滤搜索条：严格单行、图标不压字、浅灰底槽分段器、横向刷新按钮 */
.rfd-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--ct-bg-surface, #f8fafc);
  border-bottom: 1px solid var(--ct-border, #e2e8f0);
  flex-wrap: nowrap;
}
.rfd-search-box {
  position: relative;
  flex: 1;
  min-width: 150px;
  display: flex;
  align-items: center;
}
.rfd-search-icon {
  position: absolute;
  left: 10px;
  color: #94a3b8;
  pointer-events: none;
  z-index: 1;
}
.rfd-search-input {
  width: 100% !important;
  height: 32px !important;
  padding: 0 28px 0 32px !important;
  font-size: 12.5px !important;
  color: var(--ct-text-primary, #0f172a) !important;
  background: var(--ct-bg-card, #ffffff) !important;
  border: 1px solid #cbd5e1 !important;
  border-radius: 8px !important;
  outline: none !important;
  box-sizing: border-box !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.rfd-search-input:hover {
  border-color: rgba(124, 77, 255, 0.45) !important;
}
.rfd-search-input:focus {
  border-color: #7c4dff !important;
  box-shadow: 0 0 0 2px rgba(124, 77, 255, 0.12) !important;
}
.rfd-search-clear {
  position: absolute;
  right: 8px;
  width: 18px !important;
  height: 18px !important;
  padding: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  border: none !important;
  border-radius: 50% !important;
  background: rgba(148, 163, 184, 0.22) !important;
  color: #64748b !important;
  cursor: pointer;
}
.rfd-search-clear:hover {
  background: rgba(148, 163, 184, 0.38) !important;
  color: #0f172a !important;
}

/* 浅灰底槽分段器（绝不会两个按钮同时变紫） */
.rfd-seg {
  display: inline-flex;
  align-items: center;
  padding: 3px;
  height: 32px;
  background: #e2e8f0;
  border-radius: 8px;
  flex-shrink: 0;
  box-sizing: border-box;
}
.rfd-seg-btn {
  height: 26px !important;
  padding: 0 10px !important;
  border-radius: 6px !important;
  border: none !important;
  background: transparent !important;
  color: #475569 !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 5px !important;
  cursor: pointer;
  white-space: nowrap !important;
  box-shadow: none !important;
  transition: all 0.15s ease;
}
.rfd-seg-btn:hover:not(.active) {
  color: #0f172a !important;
}
.rfd-seg-btn.active {
  background: #ffffff !important;
  color: #6d28d9 !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.1) !important;
}
.rfd-seg-count {
  font-size: 11px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.16);
  color: #475569;
  line-height: 1.4;
}
.rfd-seg-btn.active .rfd-seg-count {
  background: rgba(109, 40, 217, 0.12);
  color: #6d28d9;
}

.rfd-select {
  height: 32px !important;
  padding: 0 24px 0 10px !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  color: #334155 !important;
  background-color: #ffffff !important;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") !important;
  background-repeat: no-repeat !important;
  background-position: right 7px center !important;
  appearance: none !important;
  -webkit-appearance: none !important;
  border: 1px solid #cbd5e1 !important;
  border-radius: 8px !important;
  outline: none !important;
  cursor: pointer;
  flex-shrink: 0;
  width: auto !important;
  max-width: 132px;
  box-sizing: border-box !important;
}
.rfd-select:hover {
  border-color: rgba(124, 77, 255, 0.45) !important;
}
.rfd-select:focus {
  border-color: #7c4dff !important;
  box-shadow: 0 0 0 2px rgba(124, 77, 255, 0.12) !important;
}

.rfd-refresh-btn {
  width: auto !important;
  height: 32px !important;
  padding: 0 12px !important;
  border-radius: 8px !important;
  border: 1px solid #cbd5e1 !important;
  background: #ffffff !important;
  color: #334155 !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 5px !important;
  cursor: pointer;
  white-space: nowrap !important;
  flex-shrink: 0 !important;
  transition: all 0.15s ease;
}
.rfd-refresh-btn:hover:not(:disabled) {
  border-color: #7c4dff !important;
  color: #7c4dff !important;
  background: rgba(124, 77, 255, 0.04) !important;
}
.rfd-refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rfd-spin {
  animation: rfd-rotate 0.9s linear infinite;
}
@keyframes rfd-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 状态提示 */
.rfd-status {
  font-size: 13px;
  color: var(--ct-text-secondary, #64748b);
  text-align: center;
  padding: 44px 20px;
  line-height: 1.6;
}
.rfd-status.rfd-error {
  color: #b91c1c;
  background: rgba(239, 68, 68, 0.05);
}
.rfd-hint {
  font-size: 11.5px;
  color: var(--ct-text-muted, #94a3b8);
}

/* 记忆列表区 */
.rfd-list {
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 14px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rfd-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 22px;
  background: var(--ct-bg-surface, #f8fafc);
  border-top: 1px solid var(--ct-border, #e2e8f0);
  color: var(--ct-text-secondary, #64748b);
  font-size: 12px;
}
.rfd-page-info {
  font-weight: 500;
}
.rfd-page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rfd-page-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--ct-border, #cbd5e1);
  border-radius: 7px;
  background: var(--ct-bg-card, #ffffff);
  color: var(--ct-text-primary, #0f172a);
  cursor: pointer;
  transition: all 0.15s ease;
}
.rfd-page-btn:hover:not(:disabled) {
  border-color: var(--ct-color-primary, #7c4dff);
  color: var(--ct-color-primary, #7c4dff);
}
.rfd-page-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
.rfd-page-num {
  font-size: 12px;
  font-weight: 600;
  color: var(--ct-text-primary, #0f172a);
  padding: 0 4px;
}
.rfd-page-slash {
  color: var(--ct-text-muted, #94a3b8);
  margin: 0 2px;
}

/* 单个记忆卡片 */
.rfd-item {
  border: 1px solid var(--ct-border-color, #e5e7eb);
  background: var(--ct-bg-elevated, #ffffff);
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
  transition: all 0.15s ease-in-out;
}
.rfd-item:hover {
  border-color: rgba(124, 77, 255, 0.35);
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.05);
}
.rfd-item.disabled {
  opacity: 0.65;
  background: var(--ct-bg-secondary, #fafafa);
}

/* 卡片元信息头 */
.rfd-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.rfd-head-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.rfd-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 发言人勋章 */
.rfd-speaker-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px 2px 4px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.rfd-speaker-badge.self {
  background: rgba(124, 77, 255, 0.1);
  color: #6d28d9;
  border: 1px solid rgba(124, 77, 255, 0.25);
}
.rfd-speaker-badge.contact {
  background: rgba(16, 185, 129, 0.1);
  color: #047857;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.rfd-badge-avatar {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* 状态标签 */
.rfd-chip {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 999px;
}
.rfd-chip.active {
  color: #059669;
  background: rgba(16, 185, 129, 0.08);
}
.rfd-chip.off {
  color: #b91c1c;
  background: rgba(239, 68, 68, 0.08);
}

.rfd-kind {
  font-size: 11px;
  color: var(--ct-text-secondary, #4b5563);
  background: var(--ct-bg-secondary, #f3f4f6);
  padding: 1px 6px;
  border-radius: 4px;
}
.rfd-time {
  font-size: 11px;
  color: var(--ct-text-tertiary, #9ca3af);
}
.rfd-conf {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 5px;
  border-radius: 4px;
}
.rfd-conf.high {
  color: #059669;
  background: rgba(16, 185, 129, 0.08);
}
.rfd-conf.med {
  color: #d97706;
  background: rgba(245, 158, 11, 0.08);
}
.rfd-conf.low {
  color: #6b7280;
  background: rgba(107, 114, 128, 0.08);
}
.rfd-sens {
  font-size: 10px;
  font-weight: 600;
  color: #b45309;
  background: rgba(245, 158, 11, 0.12);
  padding: 1px 6px;
  border-radius: 999px;
}

/* 核心陈述卡片 */
.rfd-statement-box {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-left: 3px solid var(--ct-color-primary, #7c4dff);
  background: var(--ct-bg-secondary, #f9fafb);
  border-radius: 0 6px 6px 0;
  display: flex;
  align-items: baseline;
  gap: 2px;
}
.rfd-quote-mark {
  font-size: 15px;
  font-family: Georgia, serif;
  font-weight: bold;
  color: var(--ct-color-primary, #7c4dff);
  opacity: 0.6;
}
.rfd-statement-text {
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--ct-text-primary, #111827);
  word-break: break-word;
}

/* 原生微信聊天现场还原窗口 */
.rfd-wechat-window {
  margin-top: 8px;
  background: #ededed;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
}
:global(.dark) .rfd-wechat-window,
:global([data-theme="dark"]) .rfd-wechat-window {
  background: #191919;
  border-color: #2e2e2e;
}

.rfd-wechat-header {
  padding: 5px 12px;
  background: rgba(0, 0, 0, 0.03);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}
:global(.dark) .rfd-wechat-header,
:global([data-theme="dark"]) .rfd-wechat-header {
  background: rgba(255, 255, 255, 0.03);
  border-bottom-color: rgba(255, 255, 255, 0.05);
}

.rfd-chat-title {
  font-size: 10.5px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: 0.2px;
}
:global(.dark) .rfd-chat-title,
:global([data-theme="dark"]) .rfd-chat-title {
  color: #9ca3af;
}

.rfd-wechat-body {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 时间标签 */
.rfd-chat-time {
  align-self: center;
  font-size: 10.5px;
  color: rgba(0, 0, 0, 0.42);
  background: rgba(0, 0, 0, 0.05);
  padding: 1px 7px;
  border-radius: 4px;
  margin-bottom: 2px;
}
:global(.dark) .rfd-chat-time,
:global([data-theme="dark"]) .rfd-chat-time {
  color: rgba(255, 255, 255, 0.45);
  background: rgba(255, 255, 255, 0.08);
}

/* 消息行 */
.rfd-msg-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
}
.rfd-msg-row.left {
  flex-direction: row;
  justify-content: flex-start;
}
.rfd-msg-row.right {
  flex-direction: row-reverse;
  justify-content: flex-start;
}

/* 微信头像容器与图片/SVG兜底 */
.rfd-msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  background: #dfdfdf;
}
.rfd-msg-avatar.self {
  background: #10b981;
}
.rfd-avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.rfd-avatar-svg {
  width: 100%;
  height: 100%;
  display: block;
}

/* 微信气泡 */
.rfd-bubble {
  position: relative;
  max-width: min(78%, 480px);
  padding: 7px 11px;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

/* 左侧对方气泡（白色） */
.rfd-bubble.left {
  background: #ffffff;
  color: #111827;
}
:global(.dark) .rfd-bubble.left,
:global([data-theme="dark"]) .rfd-bubble.left {
  background: #2a2a2a;
  color: #f3f4f6;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}
/* 左侧小三角形尖角 */
.rfd-bubble.left::before {
  content: '';
  position: absolute;
  left: -5px;
  top: 10px;
  width: 0;
  height: 0;
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-right: 5px solid #ffffff;
}
:global(.dark) .rfd-bubble.left::before,
:global([data-theme="dark"]) .rfd-bubble.left::before {
  border-right-color: #2a2a2a;
}

/* 右侧我方气泡（微信绿） */
.rfd-bubble.right {
  background: #95ec69;
  color: #111827;
}
:global(.dark) .rfd-bubble.right,
:global([data-theme="dark"]) .rfd-bubble.right {
  background: #2e6638;
  color: #f3f4f6;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
}
/* 右侧小三角形尖角 */
.rfd-bubble.right::before {
  content: '';
  position: absolute;
  right: -5px;
  top: 10px;
  width: 0;
  height: 0;
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-left: 5px solid #95ec69;
}
:global(.dark) .rfd-bubble.right::before,
:global([data-theme="dark"]) .rfd-bubble.right::before {
  border-left-color: #2e6638;
}

/* 记忆锚点高亮 */
.rfd-bubble.anchor {
  outline: 1.5px solid #f59e0b;
}
.rfd-anchor-badge {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: 6px;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(245, 158, 11, 0.22);
  color: #b45309;
  vertical-align: middle;
  white-space: nowrap;
}
:global(.dark) .rfd-anchor-badge,
:global([data-theme="dark"]) .rfd-anchor-badge {
  background: rgba(245, 158, 11, 0.3);
  color: #fbbf24;
}

/* 敏感记忆遮罩交互 */
.rfd-sensitive-mask {
  margin-top: 8px;
  padding: 12px;
  background: var(--ct-bg-secondary, #f9fafb);
  border: 1px dashed var(--ct-border-color, #e5e7eb);
  border-radius: 8px;
  color: var(--ct-text-tertiary, #9ca3af);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.rfd-sensitive-mask:hover {
  background: rgba(124, 77, 255, 0.04);
  color: var(--ct-color-primary, #7c4dff);
  border-color: var(--ct-color-primary, #7c4dff);
}

/* 底部操作区 */
.rfd-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
.rfd-btn {
  border: 1px solid var(--ct-border-color, #e5e7eb);
  background: var(--ct-bg-secondary, #f9fafb);
  color: var(--ct-text-secondary, #4b5563);
  font-size: 11.5px;
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.rfd-btn:hover:not(:disabled) {
  border-color: var(--ct-color-primary, #7c4dff);
  color: var(--ct-color-primary, #7c4dff);
}
.rfd-btn.warn {
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.05);
}
.rfd-btn.warn:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.12);
}
.rfd-btn.danger {
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.05);
}
.rfd-btn.danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.12);
}
.rfd-btn.restore {
  color: #059669;
  border-color: rgba(16, 185, 129, 0.35);
  background: rgba(16, 185, 129, 0.05);
}
.rfd-btn.restore:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.12);
}
.rfd-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 弹窗底部说明条 */
.rfd-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 22px 12px;
  font-size: 11.5px;
  color: var(--ct-text-secondary, #64748b);
  border-top: 1px solid var(--ct-border, #e2e8f0);
  background: var(--ct-bg-card, #ffffff);
}
.rfd-foot-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ct-color-primary, #7c4dff);
  flex-shrink: 0;
}
</style>
