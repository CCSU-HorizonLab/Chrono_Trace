<template>
  <section class="pbc-card" :class="`is-${kind}`">
    <div class="pbc-accent"></div>
    <div class="pbc-hd">
      <component :is="config.icon" :size="20" />
      <span>{{ config.title }}</span>
      <span v-if="contactName" class="pbc-hd-name">{{ contactName }}</span>
    </div>
    <div class="pbc-bd">
      <!-- 窗口与时效：徽标惯用语三件套（窗口档位 + 覆盖比 + 新鲜度） -->
      <div v-if="meta.createdAt || meta.expiresAt || meta.window" class="pbc-date-meta">
        <span v-if="meta.window?.label">窗口: {{ meta.window.label }}{{ coverageText }}</span>
        <span v-if="meta.createdAt">{{ toAgoLabel(meta.createdAt) }}</span>
        <span v-if="meta.expiresAt">过期: {{ formatDate(meta.expiresAt) }}</span>
        <span v-if="meta.expired" class="is-expired">已过期</span>
      </div>

      <!-- 画像详情 -->
      <template v-if="hasProfile">
        <div v-if="config.tags && tags.length" class="pbc-tag-row">
          <span v-for="t in tags" :key="t" class="pbc-tag">{{ t }}</span>
        </div>
        <div class="pbc-detail-list">
          <div v-for="row in detailRows" :key="row.label" class="pbc-detail-row">
            <component :is="row.icon" :size="14" class="pbc-detail-icon" />
            <div class="pbc-detail-main">
              <span class="pbc-detail-label">{{ row.label }}</span>
              <span class="pbc-detail-text">{{ row.text }}</span>
            </div>
          </div>
        </div>
        <div class="pbc-actions">
          <button class="pbc-action" @click="$emit('generate', kind)">
            {{ meta.expired ? config.renewAction : config.refreshAction }}
          </button>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-else-if="!loading" class="pbc-empty">
        <span>{{ config.emptyText }}</span>
        <button v-if="contactName" class="pbc-action" @click="$emit('generate', kind)">
          {{ config.emptyAction }}
        </button>
      </div>

      <div v-if="loading" class="pbc-loading">{{ loadingText }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  Lightbulb, ListChecks, MessageCircle, MessageSquare, PenTool,
  Pin, Smile, Target, Type, User, UserPlus,
} from 'lucide-vue-next'
import { api } from '@/api/bridge'
import { toAgoLabel } from '@/utils/datetime'

/**
 * 双方画像简卡：TA 画像 / 我的画像 的紧凑展示（实时助手页双卡、TA 画像页我的画像卡）。
 * 自取数（get_contact_profile / get_self_profile 查缓存），生成动作经 generate 事件
 * 交给父级（Analytics 共用一个 PortraitGenerateDialog）。
 */
const props = withDefaults(defineProps<{
  kind: 'contact' | 'self'
  contactName: string
  accountWxid?: string
  /** 父级生成完成后 +1 触发重取 */
  refreshKey?: number
}>(), {
  accountWxid: '',
  refreshKey: 0,
})

defineEmits<{
  (e: 'generate', kind: 'contact' | 'self'): void
}>()

const profile = ref<any>(null)
const meta = ref<{ createdAt: number | null; expiresAt: number | null; expired: boolean; window: any }>({
  createdAt: null, expiresAt: null, expired: false, window: null,
})
const loading = ref(false)

interface DetailRow { icon: any; label: string; text: string }

const config = computed(() => {
  if (props.kind === 'self') {
    return {
      title: '我的画像',
      icon: UserPlus,
      tags: false,
      emptyText: '尚未生成你对 TA 的专属画像（供建议与模仿你的语气使用）',
      emptyAction: '生成我的画像',
      renewAction: '更新我的画像',
      refreshAction: '重新生成',
      loadingText: '画像读取中...',
      fields: [
        { key: 'typing_style', label: '排版风格', icon: PenTool },
        { key: 'frequent_catchphrases', label: '常用词汇', icon: MessageCircle, join: true },
        { key: 'sentence_patterns', label: '句式模板', icon: Type, join: true },
        { key: 'attitude_and_role', label: '我的态度', icon: Smile },
        { key: 'do_and_donts', label: '模仿要诀', icon: ListChecks },
      ] as any[],
    }
  }
  return {
    title: 'TA 画像',
    icon: User,
    tags: true,
    emptyText: '暂无 AI 画像',
    emptyAction: '生成画像',
    renewAction: '更新画像',
    refreshAction: '重生成像',
    loadingText: '画像读取中...',
    fields: [
      { key: 'chat_style', label: '聊天风格', icon: MessageSquare },
      { key: 'interests', label: '兴趣话题', icon: Target, join: true },
      { key: 'communication_tips', label: '沟通注意', icon: Pin },
      { key: 'relationship_note', label: '关系状态', icon: Lightbulb },
    ] as any[],
  }
})

const hasProfile = computed(() => Boolean(profile.value))
const tags = computed<string[]>(() => (profile.value?.personality_tags || profile.value?.tags || []))

const detailRows = computed<DetailRow[]>(() => {
  const rows: DetailRow[] = []
  for (const field of config.value.fields) {
    const value = profile.value?.[field.key]
    const text = field.join ? (Array.isArray(value) ? value.join('、') : '') : (value || '')
    if (text) rows.push({ icon: field.icon, label: field.label, text })
  }
  return rows
})

const loadingText = computed(() => config.value.loadingText)

/** 窗口覆盖比：窗口文本量占全会话比例——长关系上「最近 30 天」可能只盖住个位数百分比，不披露就冒充全貌 */
const coverageText = computed(() => {
  const ratio = meta.value?.window?.coverage_ratio
  if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) return ''
  return `（覆盖 ${Math.round(ratio * 100)}%）`
})

function formatDate(seconds: number | null): string {
  if (!seconds) return ''
  return new Date(seconds * 1000).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function reset() {
  profile.value = null
  meta.value = { createdAt: null, expiresAt: null, expired: false, window: null }
}

async function load() {
  if (!props.contactName) {
    reset()
    return
  }
  loading.value = true
  try {
    const res = props.kind === 'self'
      ? await api.get_self_profile(props.contactName, props.accountWxid || undefined)
      : await api.get_contact_profile(props.contactName, props.accountWxid || undefined)
    if (res.ok && res.has_profile) {
      profile.value = res.profile || null
      meta.value = {
        createdAt: res.created_at || null,
        expiresAt: res.expires_at || null,
        expired: Boolean(res.expired),
        window: res.window || null,
      }
    } else {
      reset()
    }
  } catch {
    reset()
  } finally {
    loading.value = false
  }
}

watch(() => [props.contactName, props.accountWxid, props.refreshKey], load)
onMounted(load)
</script>

<style scoped>
.pbc-card {
  position: relative; background: var(--ct-bg-card);
  overflow: hidden; display: flex; flex-direction: column;
  transition: transform var(--ct-transition-normal) var(--ct-ease-out),
              box-shadow var(--ct-transition-normal) var(--ct-ease-out),
              border-color var(--ct-transition-normal);
}
.pbc-card:hover { transform: translateY(-3px); box-shadow: var(--ct-shadow-lg); border-color: var(--ct-border-color-hover); }

.pbc-accent { height: 3px; width: 100%; flex-shrink: 0; }
.is-contact .pbc-accent { background: var(--ct-color-primary); }
.is-self .pbc-accent { background: var(--ct-color-success); }

.pbc-hd {
  display: flex; align-items: center; gap: var(--ct-space-sm);
  padding: var(--ct-space-md) var(--ct-space-lg); font-weight: 600;
  font-size: var(--ct-text-sm); color: var(--ct-text-primary);
  border-bottom: 1px solid var(--ct-border-color);
}
.pbc-hd svg { color: var(--ct-text-tertiary); }
.pbc-hd-name {
  margin-left: auto; font-weight: 500; font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; max-width: 40%;
}

.pbc-bd { padding: var(--ct-space-lg); flex: 1; display: flex; flex-direction: column; gap: var(--ct-space-md); }

.pbc-date-meta {
  display: flex; flex-wrap: wrap; gap: var(--ct-space-sm);
  font-size: var(--ct-text-xs); color: var(--ct-text-tertiary);
}
.pbc-date-meta .is-expired { color: var(--ct-color-error); font-weight: 600; }

.pbc-tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.pbc-tag {
  padding: 3px 10px; border-radius: 999px; font-size: var(--ct-text-xs);
  background: var(--ct-color-primary-tint); color: var(--ct-color-primary);
  border: 1px solid color-mix(in srgb, var(--ct-color-primary) 18%, transparent);
}

.pbc-detail-list { display: flex; flex-direction: column; gap: var(--ct-space-sm); }
.pbc-detail-row {
  display: flex; align-items: flex-start; gap: var(--ct-space-sm);
  padding: var(--ct-space-sm); border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
}
.pbc-detail-icon { color: var(--ct-text-tertiary); flex-shrink: 0; margin-top: 3px; }
.pbc-detail-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pbc-detail-label { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); font-weight: 600; }
.pbc-detail-text { font-size: var(--ct-text-sm); color: var(--ct-text-primary); line-height: 1.6; word-break: break-word; }

.pbc-actions { display: flex; justify-content: flex-end; }

.pbc-empty {
  display: flex; flex-direction: column; align-items: center; gap: var(--ct-space-sm);
  padding: var(--ct-space-lg) var(--ct-space-md);
  color: var(--ct-text-tertiary); font-size: var(--ct-text-sm);
  text-align: center;
}

.pbc-action {
  padding: 6px 18px; border: none; border-radius: var(--ct-radius-lg);
  font-weight: 600; font-size: var(--ct-text-xs); cursor: pointer;
  background: var(--ct-color-primary); color: white;
  transition: all var(--ct-transition-fast);
}
.pbc-action:hover:not(:disabled) { background: var(--ct-color-primary-hover); }

.pbc-loading { font-size: var(--ct-text-xs); color: var(--ct-text-tertiary); text-align: center; }
</style>
