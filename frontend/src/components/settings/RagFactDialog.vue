<template>
  <Teleport to="body">
  <div v-if="visible" class="rfd-mask" @click.self="close">
    <div class="rfd-panel">
      <div class="rfd-head">
        <div class="rfd-title-wrap">
          <span class="rfd-title">记忆管理</span>
          <span class="rfd-sub">{{ displayName || '联系人' }} · {{ loading ? '正在读取记忆…' : `${activeCount} 条参与建议 / 共 ${facts.length} 条` }}</span>
        <span class="rfd-diag">会话 {{ conversationId }} · 账号 {{ resolvedAccount || '-' }} · 库内事实 {{ rawFactCount ?? '-' }} 条</span>
        </div>
        <button class="rfd-close" @click="close">✕</button>
      </div>

      <div class="rfd-toolbar">
        <input v-model="keyword" class="rfd-search" placeholder="搜索记忆内容…" />
        <label class="rfd-filter">
          <input v-model="showDisabled" type="checkbox" />
          <span>只看我禁用的</span>
        </label>
        <button class="rfd-btn ghost" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>

      <div v-if="error" class="rfd-status rfd-error">加载失败：{{ error }}<br /><span class="rfd-hint">若提示接口缺失，请完全退出并重启应用</span></div>
      <div v-else-if="!loading && filtered.length === 0" class="rfd-status">
        <template v-if="facts.length > 0">没有匹配的记忆</template>
        <template v-else-if="documentCount > 0">
          索引包含 {{ documentCount }} 条文档，但没有抽取到结构化记忆事实<br />
          <span class="rfd-hint">该联系人可能只建立了文档索引；记忆事实由建议链路逐步抽取积累</span>
        </template>
        <template v-else>该联系人还没有任何记忆事实</template>
      </div>

      <div class="rfd-list">
        <div
          v-for="fact in filtered"
          :key="fact.id"
          class="rfd-item"
          :class="{ disabled: !fact.enabled, sensitive: fact.sensitive }"
        >
          <div class="rfd-item-head">
            <span class="rfd-chip" :class="fact.enabled ? 'active' : 'off'">
              {{ fact.enabled ? '参与建议' : fact.user_action === 'inaccurate' ? '已标记不准确' : '已忘记' }}
            </span>
            <span v-if="fact.kind" class="rfd-kind">{{ kindLabel(fact.kind) }}</span>
            <span v-if="fact.as_of" class="rfd-time">{{ formatDate(fact.as_of) }}</span>
            <span class="rfd-conf">置信 {{ Math.round((fact.confidence ?? 0) * 100) }}%</span>
            <span v-if="fact.sensitive" class="rfd-sens" title="敏感记忆：默认不参与建议，仅供查看">敏感</span>
          </div>
          <div class="rfd-content" :class="{ masked: fact.sensitive && !revealed[fact.id] }" @click="reveal(fact)">
            {{ fact.sensitive && !revealed[fact.id] ? '敏感记忆，点击查看' : fact.content }}
          </div>
          <div v-if="fact.evidence_excerpts?.length && !fact.sensitive" class="rfd-evidence">
            <span
              v-for="(ev, i) in fact.evidence_excerpts"
              :key="i"
              class="rfd-evidence-text"
            >“{{ ev }}”</span>
          </div>
          <div class="rfd-actions">
            <template v-if="fact.enabled">
              <button class="rfd-btn warn" :disabled="busy[fact.id]" @click="feedback(fact, 'inaccurate')">
                不准确
              </button>
              <button class="rfd-btn danger" :disabled="busy[fact.id]" @click="feedback(fact, 'forget')">
                忘记这条
              </button>
            </template>
            <button v-else class="rfd-btn" :disabled="busy[fact.id]" @click="feedback(fact, 'restore')">
              恢复参与
            </button>
          </div>
        </div>
      </div>

      <div class="rfd-foot">
        「不准确」和「忘记」立即生效且不会被重建索引复活；「不准确」同时会作为高置信修正样本反馈给系统。
      </div>
    </div>
  </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api } from '@/api/bridge'

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
  evidence_excerpts?: string[]
}

const props = defineProps<{
  visible: boolean
  conversationId: number | null
  accountWxid?: string
  displayName?: string
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const facts = ref<RagFact[]>([])
const documentCount = ref(0)
const rawFactCount = ref<number | null>(null)
const resolvedAccount = ref('')
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const showDisabled = ref(false)
const busy = reactive<Record<number, boolean>>({})
const revealed = reactive<Record<number, boolean>>({})

const filtered = computed(() =>
  facts.value.filter((f) => {
    if (showDisabled.value && f.enabled) return false
    if (!showDisabled.value && !f.enabled) return false
    if (keyword.value.trim()) {
      return f.content.toLowerCase().includes(keyword.value.trim().toLowerCase())
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
    hobby_or_game: '兴趣/游戏',
    food_or_place: '饮食/地点',
    personal_profile: '个人情况',
    relationship_boundary: '关系边界',
    recurring_habit: '习惯',
    purchase_or_price: '消费',
    event: '事件',
    preference: '偏好',
  }
  return map[kind] || kind
}

function formatDate(ts?: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function reveal(fact: RagFact) {
  if (fact.sensitive) revealed[fact.id] = true
}

async function load() {
  if (!props.conversationId) return
  loading.value = true
  error.value = ''
  try {
    // Pass concrete values through pywebview. `undefined` in an argument array
    // is converted to `null` by JSON serialization in some WebView2 versions.
    const res = await api.get_contact_facts(props.conversationId, props.accountWxid || '', 200)
    if (res?.ok) {
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
.rfd-mask { position: fixed; inset: 0; z-index: 1100; background: rgba(0, 0, 0, 0.24); display: flex; align-items: center; justify-content: center; }
.rfd-panel { width: min(760px, calc(100vw - 32px)); max-height: 84vh; display: flex; flex-direction: column; background: var(--ct-bg-elevated, #fff); border: 1px solid var(--ct-border-color, #e5e7eb); border-radius: 14px; box-shadow: 0 16px 48px rgba(0, 0, 0, 0.18); overflow: hidden; }
.rfd-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.rfd-title-wrap { display: flex; flex-direction: column; gap: 2px; }
.rfd-title { font-size: 15px; font-weight: 700; color: var(--ct-text-primary, #1f2937); }
.rfd-sub { font-size: 11.5px; color: var(--ct-text-tertiary, #9ca3af); }
.rfd-diag { font-size: 10px; color: var(--ct-text-tertiary, #9ca3af); opacity: 0.75; }
.rfd-close { border: none; background: transparent; cursor: pointer; font-size: 15px; color: var(--ct-text-tertiary, #9ca3af); padding: 4px 8px; border-radius: 8px; }
.rfd-close:hover { background: var(--ct-bg-secondary, #f3f4f6); }
.rfd-toolbar { display: flex; align-items: center; gap: 10px; padding: 0 16px 10px; }
.rfd-search { flex: 1; min-width: 0; padding: 6px 10px; font-size: 12px; border: 1px solid var(--ct-border-color, #e5e7eb); border-radius: 8px; outline: none; background: var(--ct-bg-secondary, #f9fafb); color: var(--ct-text-primary, #1f2937); }
.rfd-search:focus { border-color: var(--ct-color-primary, #7c4dff); }
.rfd-filter { display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--ct-text-secondary, #6b7280); white-space: nowrap; cursor: pointer; }
.rfd-status { font-size: 12px; color: var(--ct-text-secondary, #6b7280); text-align: center; padding: 24px 0; }
.rfd-status.rfd-error { color: #8a2b2b; padding: 20px 16px; line-height: 1.6; }
.rfd-hint { font-size: 10.5px; color: var(--ct-text-tertiary, #9ca3af); }
.rfd-list { flex: 1; overflow-y: auto; padding: 0 16px; }
.rfd-item { border: 1px solid var(--ct-border-color, #e5e7eb); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; }
.rfd-item.disabled { opacity: 0.72; background: var(--ct-bg-secondary, #f9fafb); }
.rfd-item-head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px; margin-bottom: 5px; }
.rfd-chip { font-size: 10px; font-weight: 600; padding: 1px 8px; border-radius: 999px; }
.rfd-chip.active { color: var(--ct-color-primary, #7c4dff); background: rgba(124, 77, 255, 0.08); }
.rfd-chip.off { color: #8a2b2b; background: rgba(178, 58, 58, 0.08); }
.rfd-kind, .rfd-time, .rfd-conf { font-size: 10.5px; color: var(--ct-text-tertiary, #9ca3af); }
.rfd-sens { font-size: 10px; font-weight: 600; color: #8a5a00; background: rgba(180, 125, 20, 0.1); padding: 1px 6px; border-radius: 999px; }
.rfd-content { font-size: 12.5px; line-height: 1.55; color: var(--ct-text-primary, #1f2937); word-break: break-word; }
.rfd-content.masked { color: var(--ct-text-tertiary, #9ca3af); cursor: pointer; font-size: 11.5px; }
.rfd-evidence { margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--ct-border-color, #e5e7eb); display: flex; flex-direction: column; gap: 3px; }
.rfd-evidence-text { font-size: 11px; color: var(--ct-text-secondary, #6b7280); line-height: 1.45; word-break: break-word; }
.rfd-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 8px; }
.rfd-btn { border: 1px solid var(--ct-border-color, #e5e7eb); background: var(--ct-bg-secondary, #f9fafb); color: var(--ct-text-secondary, #6b7280); font-size: 11px; padding: 3px 10px; border-radius: 7px; cursor: pointer; }
.rfd-btn:hover:not(:disabled) { border-color: var(--ct-color-primary, #7c4dff); color: var(--ct-color-primary, #7c4dff); }
.rfd-btn.warn { color: #8a5a00; border-color: rgba(180, 125, 20, 0.35); background: rgba(180, 125, 20, 0.06); }
.rfd-btn.danger { color: #8a2b2b; border-color: rgba(178, 58, 58, 0.35); background: rgba(178, 58, 58, 0.05); }
.rfd-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rfd-foot { padding: 10px 16px 12px; font-size: 10.5px; color: var(--ct-text-tertiary, #9ca3af); border-top: 1px solid var(--ct-border-color, #e5e7eb); margin-top: 8px; }
</style>
