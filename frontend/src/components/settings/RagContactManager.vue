<template>
  <div class="rag-contact-manager">
    <!-- 顶部状态摘要与控制条 -->
    <div class="rc-header-bar">
      <div class="rc-metric-pills">
        <div class="rc-pill" title="已导入联系人总数">
          <span class="rc-pill-label">总联系人</span>
          <span class="rc-pill-val">{{ items.length }}</span>
        </div>
        <div class="rc-pill success" title="已成功建立索引的联系人">
          <span class="rc-pill-label">已就绪</span>
          <span class="rc-pill-val">{{ readyCount }}</span>
        </div>
        <div class="rc-pill warning" title="待建立索引的联系人">
          <span class="rc-pill-label">待索引</span>
          <span class="rc-pill-val">{{ pendingCount }}</span>
        </div>
        <div v-if="errorCount > 0" class="rc-pill danger" title="索引失败的联系人">
          <span class="rc-pill-label">异常</span>
          <span class="rc-pill-val">{{ errorCount }}</span>
        </div>
      </div>

      <div class="rc-header-actions">
        <button
          v-if="pendingCount > 0"
          class="rc-btn primary outline"
          :disabled="batchIndexing"
          @click.prevent="batchIndexPending"
          title="一键为所有待处理联系人建立 RAG 索引"
        >
          <span v-if="batchIndexing" class="rc-spinner mini"></span>
          <Play v-else :size="13" />
          <span>{{ batchIndexing ? `批量索引中 (${batchIndexCurrent}/${pendingCount})...` : '一键索引待处理' }}</span>
        </button>
        <button
          class="rc-btn ghost"
          :disabled="loading || batchIndexing"
          @click.prevent="$emit('refresh')"
          title="刷新联系人 RAG 索引状态"
        >
          <RotateCw :size="13" :class="{ 'rc-spin': loading }" />
          <span>刷新</span>
        </button>
      </div>
    </div>

    <!-- 搜索与筛选工具栏 -->
    <div class="rc-toolbar">
      <div class="rc-search-wrap">
        <Search :size="14" class="rc-search-icon" />
        <input
          v-model="searchQuery"
          type="text"
          class="rc-search-input"
          placeholder="搜索联系人备注或昵称..."
        />
        <button
          v-if="searchQuery"
          class="rc-search-clear"
          @click="searchQuery = ''"
          title="清空搜索"
        >
          <X :size="12" />
        </button>
      </div>

      <div class="rc-filter-tabs">
        <button
          class="rc-filter-tab"
          :class="{ active: currentFilter === 'all' }"
          @click="currentFilter = 'all'"
        >
          全部 <span class="tab-badge">{{ items.length }}</span>
        </button>
        <button
          class="rc-filter-tab"
          :class="{ active: currentFilter === 'ready' }"
          @click="currentFilter = 'ready'"
        >
          已就绪 <span class="tab-badge green">{{ readyCount }}</span>
        </button>
        <button
          class="rc-filter-tab"
          :class="{ active: currentFilter === 'pending' }"
          @click="currentFilter = 'pending'"
        >
          待索引 <span class="tab-badge amber">{{ pendingCount }}</span>
        </button>
        <button
          class="rc-filter-tab"
          :class="{ active: currentFilter === 'disabled' }"
          @click="currentFilter = 'disabled'"
        >
          已禁用 <span class="tab-badge gray">{{ disabledCount }}</span>
        </button>
        <button
          v-if="errorCount > 0"
          class="rc-filter-tab"
          :class="{ active: currentFilter === 'error' }"
          @click="currentFilter = 'error'"
        >
          异常 <span class="tab-badge red">{{ errorCount }}</span>
        </button>
      </div>

      <div class="rc-sort-wrap">
        <select v-model="currentSort" class="rc-sort-select" title="排序方式">
          <option value="updated">按最近活跃</option>
          <option value="docs_desc">按文档数量</option>
          <option value="name">按联系人姓名</option>
        </select>
      </div>
    </div>

    <!-- 列表展示区 -->
    <div class="rc-list-container">
      <div v-if="loading && !items.length" class="rc-empty-box">
        <span class="rc-spinner"></span>
        <p>正在加载联系人 RAG 索引状态...</p>
      </div>

      <div v-else-if="!items.length" class="rc-empty-box">
        <p>暂无可展示的联系人</p>
        <span class="rc-empty-hint">请确保已在上方配置微信数据库并成功导入微信数据</span>
      </div>

      <div v-else-if="!filteredItems.length" class="rc-empty-box">
        <p>未找到匹配的联系人</p>
        <button class="rc-btn ghost" @click="resetFilters">清除筛选条件</button>
      </div>

      <div v-else class="rc-list">
        <div
          v-for="item in paginatedItems"
          :key="item.conversation_id"
          class="rc-row"
          :class="{ disabled: !item.enabled, errored: item.status === 'failed' || Boolean(item.last_error) }"
        >
          <!-- 左侧：头像与基本信息 -->
          <div class="rc-col-info">
            <CtAvatar
              class="rc-avatar"
              :src="item.avatar"
              :name="item.display_name || item.username"
              :size="36"
            />
            <div class="rc-name-group">
              <div class="rc-name-line">
                <span class="rc-name" :title="item.display_name || item.username">
                  {{ item.display_name || item.username }}
                </span>
                <span
                  class="rc-badge"
                  :class="getBadgeClass(item)"
                  :title="item.last_error ? `异常详情: ${item.last_error}` : ''"
                >
                  <span class="badge-dot"></span>
                  {{ getStatusText(item) }}
                </span>
              </div>
              <div class="rc-sub-line">
                <span class="rc-metric-text">{{ item.document_count || 0 }} 篇文档</span>
                <span v-if="item.storage_bytes" class="rc-dot">·</span>
                <span v-if="item.storage_bytes" class="rc-metric-text">{{ formatBytes(item.storage_bytes) }}</span>
                <span class="rc-dot">·</span>
                <span class="rc-time-text">
                  {{ item.last_indexed_at ? formatTime(item.last_indexed_at) : '未索引' }}
                </span>
              </div>
              <div v-if="item.last_error" class="rc-error-text" :title="item.last_error">
                <AlertCircle :size="12" />
                <span>{{ item.last_error }}</span>
              </div>
            </div>
          </div>

          <!-- 右侧：控制与操作项（杜绝折行） -->
          <div class="rc-col-actions">
            <!-- 事实读侧模式选择 + 悬浮提醒说明 (Teleport 逃逸父容器裁剪) -->
            <div class="rc-mode-group">
              <select
                class="rc-select"
                :value="item.fact_read_mode || 'inherit'"
                title="切换该联系人的记忆读取模式"
                :disabled="rowLoading[item.conversation_id]"
                @change="handleFactReadMode(item, $event)"
              >
                <option value="inherit">跟随全局</option>
                <option value="facts">事实优先</option>
                <option value="documents">文档回退</option>
              </select>
              <CtHelpTip :width="280" :size="13">
                <strong>记忆读取模式说明：</strong><br />
                • <strong>跟随全局</strong>：遵循上方「事实记忆优先」全局开关；<br />
                • <strong>事实优先</strong>：优先读取提炼出的结构化事实（偏好/约定/边界），不足时以原始对话兜底；<br />
                • <strong>文档回退</strong>：仅使用原始聊天记录片段检索，不使用提炼事实（适合单人事实不准时回退）。
              </CtHelpTip>
            </div>

            <!-- 启用/禁用开关（统一文案：已启用 / 已禁用） -->
            <button
              type="button"
              class="rc-switch-btn"
              :class="[item.enabled ? 'on is-on' : 'is-off']"
              :disabled="Boolean(rowLoading[item.conversation_id])"
              @click.prevent="handleToggleEnabled(item)"
              :title="item.enabled ? '点击禁用该联系人的 RAG 检索' : '点击启用该联系人的 RAG 检索'"
            >
              <span class="rc-switch-track"><span class="rc-switch-thumb"></span></span>
              <span class="rc-switch-text">{{ item.enabled ? '已启用' : '已禁用' }}</span>
            </button>

            <!-- 管理记忆 -->
            <button
              class="rc-btn mini"
              :disabled="!item.document_count"
              @click.prevent="openFactDialog(item)"
              title="查看并纠正该联系人的记忆事实（不准确 / 忘记 / 恢复）"
            >
              <BrainIcon :size="12" />
              <span>记忆</span>
            </button>

            <!-- 重建索引 -->
            <button
              class="rc-btn mini primary"
              :disabled="rowLoading[item.conversation_id] || item.status === 'building' || item.status === 'queued'"
              @click.prevent="handleRebuild(item)"
              title="重新为该联系人的历史记录构建向量与记忆索引"
            >
              <span v-if="rowLoading[item.conversation_id] === 'rebuild' || item.status === 'building' || item.status === 'queued'" class="rc-spinner micro"></span>
              <RotateCw v-else :size="12" />
              <span>{{
                (rowLoading[item.conversation_id] === 'rebuild' || item.status === 'building') ? '构建中'
                : item.status === 'queued' ? '排队中'
                : (item.document_count ? '重建' : '索引')
              }}</span>
            </button>

            <!-- 清空索引 -->
            <button
              class="rc-btn mini danger"
              :disabled="rowLoading[item.conversation_id] || !item.document_count"
              @click.prevent="handleClear(item)"
              title="清空该联系人的 RAG 向量和文档数据（不删除原始聊天记录）"
            >
              <Trash2 :size="12" />
              <span>清空</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部：分页控制器与展示量选择 -->
    <div v-if="filteredItems.length > 0" class="rc-pagination-bar">
      <div class="rc-pag-info">
        显示第 <strong>{{ paginationStart + 1 }}</strong> - <strong>{{ paginationEnd }}</strong> 条，
        共 <strong>{{ filteredItems.length }}</strong> 条
        <span v-if="filteredItems.length !== items.length" class="rc-total-hint">
          (全部 {{ items.length }} 位)
        </span>
      </div>

      <div class="rc-pag-controls">
        <div class="rc-page-size-wrap">
          <label>每页</label>
          <select v-model.number="pageSize" class="rc-page-size-select">
            <option :value="10">10 条</option>
            <option :value="20">20 条</option>
            <option :value="50">50 条</option>
          </select>
        </div>

        <div class="rc-page-nav">
          <button
            class="rc-page-btn"
            :disabled="currentPage <= 1"
            @click="currentPage -= 1"
            title="上一页"
          >
            <ChevronLeft :size="14" />
          </button>

          <span class="rc-page-num">{{ currentPage }} / {{ totalPages }}</span>

          <button
            class="rc-page-btn"
            :disabled="currentPage >= totalPages"
            @click="currentPage += 1"
            title="下一页"
          >
            <ChevronRight :size="14" />
          </button>
        </div>
      </div>
    </div>
  </div>
  <!-- 记忆管理弹窗 -->
  <RagFactDialog
    :visible="factDialog.visible"
    :conversation-id="factDialog.conversationId"
    :account-wxid="props.accountWxid"
    :display-name="factDialog.displayName"
    :avatar-url="factDialog.avatarUrl"
    :user-avatar-url="props.userAvatar"
    @close="factDialog.visible = false"
  />
</template>

<script setup lang="ts">
import { ref, computed, watch, reactive, onUnmounted } from 'vue'
import {
  Search,
  X,
  RotateCw,
  Play,
  Trash2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Brain as BrainIcon,
} from 'lucide-vue-next'
import CtAvatar from '@/components/base/CtAvatar.vue'
import CtHelpTip from '@/components/base/CtHelpTip.vue'
import RagFactDialog from '@/components/settings/RagFactDialog.vue'
import { api } from '@/api/bridge'
import { showDialog, showConfirm } from '@/utils/dialog'

export type RagContactItem = {
  conversation_id: number
  display_name: string
  username: string
  avatar?: string
  status: 'ready' | 'pending' | 'failed' | 'building' | string
  document_count: number
  vector_count?: number
  storage_bytes: number
  enabled: boolean | number
  fact_read_mode: 'inherit' | 'facts' | 'documents'
  last_indexed_at?: number | null
  last_error?: string | null
  updated_at?: number
}

const props = withDefaults(
  defineProps<{
    items: RagContactItem[]
    loading?: boolean
    accountWxid?: string
    userAvatar?: string
  }>(),
  {
    items: () => [],
    loading: false,
    accountWxid: '',
    userAvatar: '',
  }
)

const emit = defineEmits<{
  (e: 'refresh'): void
}>()

// 构建中/排队中的服务端真值轮询：有活动任务时 3s 刷新，无则停
let livePollTimer: ReturnType<typeof setInterval> | null = null
const hasLiveWork = computed(() => props.items.some((item) => isLive(item)))
watch(
  hasLiveWork,
  (live) => {
    if (live && livePollTimer === null) {
      livePollTimer = setInterval(() => emit('refresh'), 3000)
    } else if (!live && livePollTimer !== null) {
      clearInterval(livePollTimer)
      livePollTimer = null
    }
  },
  { immediate: true }
)
onUnmounted(() => {
  if (livePollTimer !== null) {
    clearInterval(livePollTimer)
    livePollTimer = null
  }
})

// 记忆管理弹窗
const factDialog = reactive({
  visible: false,
  conversationId: null as number | null,
  displayName: '',
  avatarUrl: '',
})

function openFactDialog(item: RagContactItem) {
  factDialog.conversationId = Number(item.conversation_id)
  factDialog.displayName = item.display_name || item.username || ''
  factDialog.avatarUrl = item.avatar || (item as any).avatar_url || (item as any).avatar_path || ''
  factDialog.visible = true
}

// 检索、筛选与排序状态
const searchQuery = ref('')
const currentFilter = ref<'all' | 'ready' | 'pending' | 'disabled' | 'error'>('all')
const currentSort = ref<'updated' | 'docs_desc' | 'name'>('updated')

// 分页状态
const currentPage = ref(1)
const pageSize = ref(10)

// 单行加载状态
const rowLoading = reactive<Record<number, string | boolean>>({})
// 批量索引状态
const batchIndexing = ref(false)
const batchIndexCurrent = ref(0)

// 各种状态计数
const readyCount = computed(() => {
  return props.items.filter((item) => Boolean(item.enabled) && item.status === 'ready').length
})

const pendingCount = computed(() => {
  return props.items.filter((item) => {
    return Boolean(item.enabled) && (item.status === 'pending' || !item.document_count)
  }).length
})

const disabledCount = computed(() => {
  return props.items.filter((item) => !Boolean(item.enabled)).length
})

const errorCount = computed(() => {
  return props.items.filter((item) => item.status === 'failed' || Boolean(item.last_error)).length
})

// 过滤后的列表
const filteredItems = computed(() => {
  let list = [...props.items]

  // 1. 状态筛选
  if (currentFilter.value === 'ready') {
    list = list.filter((i) => Boolean(i.enabled) && i.status === 'ready')
  } else if (currentFilter.value === 'pending') {
    list = list.filter((i) => Boolean(i.enabled) && (i.status === 'pending' || !i.document_count))
  } else if (currentFilter.value === 'disabled') {
    list = list.filter((i) => !Boolean(i.enabled))
  } else if (currentFilter.value === 'error') {
    list = list.filter((i) => i.status === 'failed' || Boolean(i.last_error))
  }

  // 2. 关键词搜索 (匹配 display_name, username)
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((i) => {
      const name = (i.display_name || '').toLowerCase()
      const uname = (i.username || '').toLowerCase()
      return name.includes(q) || uname.includes(q)
    })
  }

  // 3. 排序
  if (currentSort.value === 'docs_desc') {
    list.sort((a, b) => (b.document_count || 0) - (a.document_count || 0))
  } else if (currentSort.value === 'name') {
    list.sort((a, b) => (a.display_name || a.username || '').localeCompare(b.display_name || b.username || '', 'zh'))
  } else {
    // 默认按 updated_at 倒序
    list.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))
  }

  return list
})

// 分页计算
const totalPages = computed(() => {
  return Math.max(1, Math.ceil(filteredItems.value.length / pageSize.value))
})

const paginationStart = computed(() => {
  return (currentPage.value - 1) * pageSize.value
})

const paginationEnd = computed(() => {
  return Math.min(paginationStart.value + pageSize.value, filteredItems.value.length)
})

const paginatedItems = computed(() => {
  return filteredItems.value.slice(paginationStart.value, paginationEnd.value)
})

// 当筛选或搜索变化时，将页码重置为 1
watch([searchQuery, currentFilter, currentSort, pageSize], () => {
  currentPage.value = 1
})

// 边界检查：当总页数变小时调整当前页码
watch(totalPages, (newTotal) => {
  if (currentPage.value > newTotal) {
    currentPage.value = newTotal
  }
})

function resetFilters() {
  searchQuery.value = ''
  currentFilter.value = 'all'
  currentSort.value = 'updated'
  currentPage.value = 1
}

function getBadgeClass(item: RagContactItem) {
  if (!item.enabled) return 'badge-gray'
  if (item.status === 'failed' || item.last_error) return 'badge-red'
  if (item.status === 'ready' && item.document_count > 0) return 'badge-green'
  return 'badge-amber'
}

function isLive(item: RagContactItem): boolean {
  return item.status === 'building' || item.status === 'queued'
}

function getStatusText(item: RagContactItem) {
  if (!item.enabled) return '已禁用'
  if (item.status === 'failed' || item.last_error) return '异常'
  if (item.status === 'ready' && item.document_count > 0) return '已就绪'
  if (item.status === 'building') return '构建中'
  if (item.status === 'queued') return '排队中'
  return '待索引'
}

function formatBytes(value: number) {
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(ts: number) {
  if (!ts) return '未索引'
  const date = new Date(Number(ts) * 1000)
  return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

// 单项操作
async function handleToggleEnabled(item: RagContactItem) {
  rowLoading[item.conversation_id] = true
  try {
    const nextEnabled = !Boolean(item.enabled)
    const result = await api.set_rag_conversation_enabled(
      Number(item.conversation_id),
      nextEnabled,
      props.accountWxid,
    )
    if (!result?.ok) {
      await showDialog('更新启用状态失败: ' + (result?.error || '未知错误'))
    } else {
      item.enabled = nextEnabled
      emit('refresh')
    }
  } catch (e: any) {
    await showDialog('操作失败: ' + (e?.message || '未知错误'))
  } finally {
    rowLoading[item.conversation_id] = false
  }
}

async function handleRebuild(item: RagContactItem) {
  rowLoading[item.conversation_id] = 'rebuild'
  try {
    const result = await api.rebuild_rag_index(Number(item.conversation_id), props.accountWxid)
    if (!result?.ok) {
      await showDialog('重建失败: ' + (result?.error || '未知错误'))
    } else if (result?.already && result?.message) {
      await showDialog(result.message)
    }
    emit('refresh')
  } catch (e: any) {
    await showDialog('重建异常: ' + (e?.message || '未知错误'))
  } finally {
    rowLoading[item.conversation_id] = false
  }
}

async function handleClear(item: RagContactItem) {
  const confirmed = await showConfirm(
    `确定清空联系人「${item.display_name || item.username}」的 RAG 索引吗？\n该操作仅清空向量与摘要记忆，原始聊天记录不受影响。`
  )
  if (!confirmed) return

  rowLoading[item.conversation_id] = 'clear'
  try {
    const result = await api.clear_rag_index(Number(item.conversation_id), props.accountWxid)
    if (!result?.ok) {
      await showDialog('清空失败: ' + (result?.error || '未知错误'))
    }
    emit('refresh')
  } catch (e: any) {
    await showDialog('清空异常: ' + (e?.message || '未知错误'))
  } finally {
    rowLoading[item.conversation_id] = false
  }
}

async function handleFactReadMode(item: RagContactItem, event: Event) {
  const target = event.target as HTMLSelectElement
  const mode = target.value as 'inherit' | 'facts' | 'documents'
  rowLoading[item.conversation_id] = true
  try {
    const result = await api.set_rag_fact_read_mode(
      Number(item.conversation_id),
      mode,
      props.accountWxid,
    )
    if (!result?.ok) {
      await showDialog('更新事实模式失败: ' + (result?.error || '未知错误'))
      emit('refresh')
      return
    }
    item.fact_read_mode = mode
  } catch (e: any) {
    await showDialog('设置模式失败: ' + (e?.message || '未知错误'))
  } finally {
    rowLoading[item.conversation_id] = false
  }
}

// 批量索引所有待索引联系人
async function batchIndexPending() {
  const pendingItems = props.items.filter((i) => Boolean(i.enabled) && (i.status === 'pending' || !i.document_count))
  if (!pendingItems.length) return

  const confirmed = await showConfirm(
    `检测到共有 ${pendingItems.length} 位待索引联系人，是否开始批量构建索引？`
  )
  if (!confirmed) return

  batchIndexing.value = true
  batchIndexCurrent.value = 0

  try {
    for (const item of pendingItems) {
      batchIndexCurrent.value += 1
      rowLoading[item.conversation_id] = 'rebuild'
      try {
        await api.rebuild_rag_index(Number(item.conversation_id), props.accountWxid)
      } catch (err) {
        console.error(`索引联系人 ${item.display_name} 失败`, err)
      } finally {
        rowLoading[item.conversation_id] = false
      }
    }
    emit('refresh')
  } finally {
    batchIndexing.value = false
    batchIndexCurrent.value = 0
  }
}
</script>

<style scoped>
.rag-contact-manager {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

/* 顶部状态摘要条 */
.rc-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 12px;
  background: var(--ct-bg-secondary, rgba(0, 0, 0, 0.02));
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.08));
  border-radius: 10px;
}

.rc-metric-pills {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.rc-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--ct-bg-1, #fff);
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.08));
  border-radius: 20px;
  font-size: 12px;
}

.rc-pill-label {
  color: var(--ct-text-tertiary, #888);
}

.rc-pill-val {
  font-weight: 700;
  color: var(--ct-text-primary, #222);
}

.rc-pill.success {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.2);
}
.rc-pill.success .rc-pill-val {
  color: #10b981;
}

.rc-pill.warning {
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.2);
}
.rc-pill.warning .rc-pill-val {
  color: #d97706;
}

.rc-pill.danger {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.2);
}
.rc-pill.danger .rc-pill-val {
  color: #ef4444;
}

.rc-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 工具栏 */
.rc-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.rc-search-wrap {
  position: relative;
  flex: 1;
  min-width: 220px;
  display: flex;
  align-items: center;
}

.rc-search-icon {
  position: absolute;
  left: 10px;
  color: var(--ct-text-tertiary, #999);
  pointer-events: none;
}

.rc-search-input {
  width: 100%;
  padding: 7px 28px 7px 30px;
  border-radius: 8px;
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.12));
  background: var(--ct-bg-1, #fff);
  color: var(--ct-text-primary, #333);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.rc-search-input:focus {
  border-color: var(--ct-color-primary, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

.rc-search-clear {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--ct-text-tertiary, #999);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border-radius: 50%;
}
.rc-search-clear:hover {
  background: rgba(0, 0, 0, 0.08);
  color: var(--ct-text-primary, #333);
}

.rc-filter-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--ct-bg-secondary, rgba(0, 0, 0, 0.03));
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.06));
}

.rc-filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--ct-text-secondary, #666);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.rc-filter-tab:hover {
  color: var(--ct-text-primary, #222);
  background: rgba(0, 0, 0, 0.03);
}

.rc-filter-tab.active {
  background: var(--ct-bg-1, #fff);
  color: var(--ct-color-primary, #6366f1);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.tab-badge {
  display: inline-block;
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.06);
  color: var(--ct-text-secondary, #666);
}

.tab-badge.green {
  background: rgba(16, 185, 129, 0.15);
  color: #0f8f63;
}
.tab-badge.amber {
  background: rgba(245, 158, 11, 0.15);
  color: #b45309;
}
.tab-badge.red {
  background: rgba(239, 68, 68, 0.15);
  color: #dc2626;
}
.tab-badge.gray {
  background: rgba(107, 114, 128, 0.15);
  color: #4b5563;
}

.rc-sort-wrap {
  display: flex;
  align-items: center;
}

.rc-sort-select {
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.12));
  background: var(--ct-bg-1, #fff);
  color: var(--ct-text-secondary, #555);
  border-radius: 8px;
  padding: 5px 8px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
  width: auto !important;
  min-width: 105px !important;
  max-width: 125px !important;
  box-sizing: border-box !important;
}

/* 列表展示区 */
.rc-list-container {
  min-height: 200px;
  border-radius: 12px;
}

.rc-empty-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--ct-text-tertiary, #999);
  gap: 10px;
  text-align: center;
  border: 1px dashed var(--ct-border-color, rgba(0, 0, 0, 0.12));
  border-radius: 10px;
}

.rc-empty-hint {
  font-size: 12px;
  color: var(--ct-text-tertiary, #aaa);
}

.rc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 每一行卡片 */
.rc-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.08));
  border-radius: 10px;
  background: var(--ct-bg-1, #fff);
  transition: all 0.15s ease;
  box-sizing: border-box;
  width: 100%;
  overflow: hidden;
}

.rc-row:hover {
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
}

.rc-row.disabled {
  opacity: 0.65;
  background: var(--ct-bg-secondary, rgba(0, 0, 0, 0.02));
}

.rc-row.errored {
  border-color: rgba(239, 68, 68, 0.3);
}

/* 左侧：信息列 */
.rc-col-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
}

.rc-avatar {
  flex-shrink: 0;
}

.rc-name-group {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.rc-name-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.rc-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ct-text-primary, #1e293b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rc-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.badge-green {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}
.badge-green .badge-dot {
  background: #10b981;
}

.badge-amber {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}
.badge-amber .badge-dot {
  background: #f59e0b;
}

.badge-red {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}
.badge-red .badge-dot {
  background: #ef4444;
}

.badge-gray {
  background: rgba(107, 114, 128, 0.12);
  color: #4b5563;
}
.badge-gray .badge-dot {
  background: #9ca3af;
}

.rc-sub-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
  color: var(--ct-text-tertiary, #888);
  line-height: 1.3;
}

.rc-dot {
  color: var(--ct-text-tertiary, #bbb);
}

.rc-metric-text {
  color: var(--ct-text-secondary, #555);
}

.rc-time-text {
  color: var(--ct-text-tertiary, #999);
}

.rc-error-text {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #dc2626;
  font-size: 11px;
  margin-top: 2px;
}

/* 右侧操作按钮组（杜绝任何折行与溢出） */
.rc-col-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: auto;
}

.rc-mode-group {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  position: relative;
  flex-shrink: 0;
}

.rc-select {
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.12));
  background: var(--ct-bg-secondary, rgba(0, 0, 0, 0.02));
  color: var(--ct-text-secondary, #555);
  border-radius: 6px;
  padding: 4px 6px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
  white-space: nowrap !important;
  word-break: keep-all;
  flex-shrink: 0 !important;
  width: 86px !important;
  min-width: 86px !important;
  max-width: 86px !important;
  box-sizing: border-box !important;
  transition: border-color 0.15s;
}

.rc-select:hover,
.rc-select:focus {
  border-color: var(--ct-color-primary, #7c4dff);
}

.rc-help-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  color: var(--ct-text-tertiary, #9ca3af);
  cursor: help;
  outline: none;
  transition: color 0.15s, background 0.15s;
}

.rc-help-icon:hover,
.rc-help-icon:focus-visible {
  color: var(--ct-color-primary, #7c4dff);
  background: rgba(124, 77, 255, 0.12);
}

.rc-help-tooltip {
  position: absolute;
  bottom: calc(100% + 9px);
  right: -8px;
  width: 280px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #1e1b4b;
  color: #f8fafc;
  font-size: 11.5px;
  font-weight: 400;
  line-height: 1.55;
  box-shadow: 0 10px 28px rgba(30, 27, 75, 0.28);
  opacity: 0;
  visibility: hidden;
  transform: translateY(4px);
  transition: opacity 0.18s ease, transform 0.18s ease, visibility 0.18s;
  pointer-events: none;
  z-index: 400;
  text-align: left;
  white-space: normal;
}

.rc-help-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  right: 11px;
  border: 5px solid transparent;
  border-top-color: #1e1b4b;
}

.rc-help-icon:hover .rc-help-tooltip,
.rc-help-icon:focus-visible .rc-help-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

/* 直观的联系人启用/禁用拨动开关 */
.rc-switch-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 5px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.1);
  background: var(--ct-bg-secondary, rgba(0, 0, 0, 0.04));
  color: var(--ct-text-secondary, #555);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
  white-space: nowrap !important;
  flex-shrink: 0 !important;
}

.rc-switch-btn.is-on {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.28);
  color: #059669;
}

.rc-switch-btn.is-off {
  background: rgba(107, 114, 128, 0.12);
  border-color: rgba(107, 114, 128, 0.24);
  color: #6b7280;
}

.rc-switch-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

.rc-switch-track {
  position: relative;
  width: 24px;
  height: 14px;
  border-radius: 999px;
  background: #9ca3af;
  transition: background 0.2s ease;
  display: inline-flex;
  align-items: center;
}

.rc-switch-btn.is-on .rc-switch-track {
  background: #10b981;
}

.rc-switch-thumb {
  position: absolute;
  left: 2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.rc-switch-btn.is-on .rc-switch-thumb {
  transform: translateX(10px);
}

.rc-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: none;
  background: var(--ct-bg-secondary, rgba(0, 0, 0, 0.04));
  color: var(--ct-text-secondary, #555);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap !important;
  word-break: keep-all;
  flex-shrink: 0 !important;
  box-sizing: border-box;
}

.rc-btn:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.08);
  color: var(--ct-text-primary, #111);
}

.rc-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rc-btn.mini {
  padding: 4px 8px;
  font-size: 12px;
}

.rc-btn.primary {
  background: var(--ct-color-primary, #6366f1);
  color: #fff;
}
.rc-btn.primary:hover:not(:disabled) {
  opacity: 0.9;
}

.rc-btn.primary.outline {
  background: transparent;
  border: 1px solid var(--ct-color-primary, #6366f1);
  color: var(--ct-color-primary, #6366f1);
}
.rc-btn.primary.outline:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.08);
}

.rc-btn.ghost {
  background: transparent;
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.12));
}
.rc-btn.ghost:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.04);
}

.rc-btn.danger {
  color: #dc2626;
  background: rgba(239, 68, 68, 0.06);
}
.rc-btn.danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.15);
  color: #b91c1c;
}

.rc-btn.mini.active {
  color: var(--ct-color-primary, #6366f1);
  background: rgba(99, 102, 241, 0.1);
}

/* 底部状态与分页条 */
.rc-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 4px 4px 4px;
  border-top: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.06));
}

.rc-pag-info {
  font-size: 12px;
  color: var(--ct-text-tertiary, #888);
}
.rc-pag-info strong {
  color: var(--ct-text-primary, #333);
}
.rc-total-hint {
  color: var(--ct-text-tertiary, #aaa);
}

.rc-pag-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.rc-page-size-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ct-text-secondary, #666);
}

.rc-page-size-select {
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.12));
  background: var(--ct-bg-1, #fff);
  color: var(--ct-text-secondary, #555);
  border-radius: 6px;
  padding: 4px 6px;
  font-size: 12px;
  outline: none;
  cursor: pointer;
  width: auto !important;
  box-sizing: border-box !important;
}

.rc-page-nav {
  display: flex;
  align-items: center;
  gap: 6px;
}

.rc-page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--ct-border-color, rgba(0, 0, 0, 0.12));
  background: var(--ct-bg-1, #fff);
  color: var(--ct-text-secondary, #555);
  cursor: pointer;
  transition: all 0.15s;
}

.rc-page-btn:hover:not(:disabled) {
  border-color: var(--ct-color-primary, #6366f1);
  color: var(--ct-color-primary, #6366f1);
}

.rc-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.rc-page-num {
  font-size: 12px;
  color: var(--ct-text-secondary, #666);
  padding: 0 6px;
  min-width: 48px;
  text-align: center;
}

/* 旋转动画与微型 Spinner */
.rc-spin {
  animation: rc-spin-frames 1s linear infinite;
}

.rc-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(0, 0, 0, 0.15);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: rc-spin-frames 0.8s linear infinite;
}

.rc-spinner.mini {
  width: 12px;
  height: 12px;
  border-width: 1.5px;
}

.rc-spinner.micro {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
}

@keyframes rc-spin-frames {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .rc-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .rc-col-actions {
    width: 100%;
    justify-content: flex-end;
    margin-top: 6px;
  }
}
</style>

