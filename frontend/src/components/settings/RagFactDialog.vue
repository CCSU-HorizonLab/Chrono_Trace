<template>
  <Teleport to="body">
    <div v-if="visible" class="rfd-mask" @click.self="close">
      <div class="rfd-panel">
        <!-- 弹窗顶栏 -->
        <div class="rfd-head">
          <div class="rfd-title-wrap">
            <div class="rfd-title-row">
              <span class="rfd-title">记忆管理</span>
              <span class="rfd-badge">{{ displayName || '联系人' }}</span>
            </div>
            <span class="rfd-sub">
              {{ loading ? '正在读取记忆…' : `${activeCount} 条参与建议 / 共 ${facts.length} 条` }}
              <span class="rfd-diag-inline">· 会话 {{ conversationId }} · 库内事实 {{ rawFactCount ?? '-' }} 条</span>
            </span>
          </div>
          <button class="rfd-close" title="关闭" @click="close">✕</button>
        </div>

        <!-- 顶部检索与过滤栏 -->
        <div class="rfd-toolbar">
          <input v-model="keyword" class="rfd-search" placeholder="搜索记忆内容与对话关键词…" />
          <label class="rfd-filter">
            <input v-model="showDisabled" type="checkbox" />
            <span>只看已停用/忘记</span>
          </label>
          <button class="rfd-btn ghost" :disabled="loading" @click="load">
            {{ loading ? '加载中…' : '刷新' }}
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
        <div class="rfd-list">
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
                  {{ fact.enabled ? '参与建议' : fact.user_action === 'inaccurate' ? '已标记不准确' : '已忘记' }}
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

        <!-- 弹窗底栏提示 -->
        <div class="rfd-foot">
          「不准确」和「忘记」立即生效且不会被重建索引复活；「不准确」同时会作为高置信修正样本反馈给系统。
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Lock } from 'lucide-vue-next'
import { api } from '@/api/bridge'

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
const documentCount = ref(0)
const rawFactCount = ref<number | null>(null)
const resolvedAccount = ref('')
const contactAvatar = ref('')
const userAvatar = ref('')
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const showDisabled = ref(false)
const busy = reactive<Record<number, boolean>>({})
const revealed = reactive<Record<number, boolean>>({})
const avatarLoadErrors = reactive<Record<string, boolean>>({})

const effectiveContactAvatar = computed(() => contactAvatar.value || props.avatarUrl || '')
const effectiveUserAvatar = computed(() => userAvatar.value || props.userAvatarUrl || '')

function getBubbleAvatar(isSelf: boolean): string {
  return isSelf ? effectiveUserAvatar.value : effectiveContactAvatar.value
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
const activeCount = computed(() => facts.value.filter((f) => f.enabled).length)

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

async function load() {
  if (!props.conversationId) return
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

    const res = await api.get_contact_facts(props.conversationId, props.accountWxid || '', 200)
    if (res?.ok) {
      if (res.contact_avatar) contactAvatar.value = String(res.contact_avatar).trim()
      if (res.user_avatar) userAvatar.value = String(res.user_avatar).trim()

      facts.value = (res.facts || []).map((fact: RagFact) => ({
        ...fact,
        enabled: Boolean(fact.enabled),
      }))
      documentCount.value = Number(res.document_count || 0)
      rawFactCount.value = res.raw_fact_count ?? null
      resolvedAccount.value = String(res.resolved_account_wxid || '')
      showDisabled.value = facts.value.some((f: RagFact) => !f.enabled)
    } else {
      error.value = String(res?.error || '未知错误')
    }
  } catch (e: any) {
    const msg = String(e?.message || e)
    error.value = msg.includes('get_contact_facts')
      ? '后端缺少该接口，请完全退出并重启应用（新功能需要后端进程重启后生效）'
      : msg
  } finally {
    loading.value = false
  }
}

async function feedback(fact: RagFact, action: 'inaccurate' | 'forget' | 'restore') {
  if (action === 'forget') {
    const ok = window.confirm('确定让系统忘记这条记忆吗？\n它将立即退出所有建议，且重建索引不会恢复。')
    if (!ok) return
  }
  busy[fact.id] = true
  try {
    const res = await api.set_fact_feedback(fact.id, action)
    if (res?.ok) {
      await load()
    } else {
      window.alert('操作失败: ' + (res?.error || '未知错误'))
    }
  } catch (e: any) {
    window.alert('操作异常: ' + (e?.message || e))
  } finally {
    busy[fact.id] = false
  }
}

function close() {
  emit('close')
}

watch(
  [() => props.visible, () => props.conversationId],
  ([visible]) => {
    if (visible) {
      keyword.value = ''
      showDisabled.value = false
      Object.keys(revealed).forEach((k) => delete revealed[Number(k)])
      load()
    }
  },
)
</script>

<style scoped>
.rfd-mask {
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.rfd-panel {
  width: min(780px, calc(100vw - 32px));
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--ct-bg-elevated, #ffffff);
  border: 1px solid var(--ct-border-color, #e5e7eb);
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.22);
  overflow: hidden;
}

/* 顶栏 */
.rfd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 10px;
  border-bottom: 1px solid var(--ct-border-color, #f0f0f0);
}
.rfd-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.rfd-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rfd-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ct-text-primary, #111827);
}
.rfd-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--ct-bg-secondary, #f3f4f6);
  color: var(--ct-text-secondary, #4b5563);
}
.rfd-sub {
  font-size: 11.5px;
  color: var(--ct-text-tertiary, #9ca3af);
}
.rfd-diag-inline {
  opacity: 0.75;
}
.rfd-close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
  color: var(--ct-text-tertiary, #9ca3af);
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.15s;
}
.rfd-close:hover {
  background: var(--ct-bg-secondary, #f3f4f6);
  color: var(--ct-text-primary, #111827);
}

/* 过滤搜索条 */
.rfd-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  background: var(--ct-bg-secondary, #fafafa);
  border-bottom: 1px solid var(--ct-border-color, #f0f0f0);
}
.rfd-search {
  flex: 1;
  min-width: 0;
  padding: 6px 12px;
  font-size: 12.5px;
  border: 1px solid var(--ct-border-color, #e5e7eb);
  border-radius: 8px;
  outline: none;
  background: var(--ct-bg-elevated, #ffffff);
  color: var(--ct-text-primary, #111827);
  transition: border-color 0.15s;
}
.rfd-search:focus {
  border-color: var(--ct-color-primary, #7c4dff);
}
.rfd-filter {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ct-text-secondary, #6b7280);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
}

/* 状态提示 */
.rfd-status {
  font-size: 13px;
  color: var(--ct-text-secondary, #6b7280);
  text-align: center;
  padding: 36px 16px;
  line-height: 1.6;
}
.rfd-status.rfd-error {
  color: #b91c1c;
  background: rgba(239, 68, 68, 0.05);
}
.rfd-hint {
  font-size: 11px;
  color: var(--ct-text-tertiary, #9ca3af);
}

/* 记忆列表区 */
.rfd-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  padding: 10px 18px 12px;
  font-size: 11px;
  color: var(--ct-text-tertiary, #9ca3af);
  border-top: 1px solid var(--ct-border-color, #f0f0f0);
  background: var(--ct-bg-elevated, #ffffff);
}
</style>
