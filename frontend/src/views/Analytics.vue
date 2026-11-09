<template>
<section class="analytics-page ct-page">
  <!-- Brand Header：对象工作台页头，选人器常驻（未选中也可先选人） -->
  <header class="analytics-header">
    <div v-if="hasConversations" class="user-profile-header fade-in">
      <div class="profile-main">
        <div class="profile-avatar-wrap">
          <CtAvatar class="profile-avatar" :src="headerAvatarSrc" :name="currentContactName || '？'" :size="48" />
        </div>
        <div class="profile-info">
          <div class="name-row">
            <h1 class="profile-name">{{ currentContactName || '选择一位联系人' }}</h1>
            <div class="contact-selector-wrap">
              <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId"
                @update:conversation-id="onConversationChange" />
            </div>
          </div>
        </div>
      </div>

      <div v-if="selectedConversationId" class="header-actions-group">
        <CtButton variant="ghost" @click="handleExport">导出聊天记录</CtButton>
      </div>
    </div>
  </header>

  <div v-if="!hasConversations" class="page-empty-state fade-in">
    <div class="page-empty-hero">
      <div class="page-empty-badge">历史分析</div>

      <div class="page-empty-illustration" aria-hidden="true">
        <div class="empty-orb empty-orb-main"><FolderArchive :size="36" style="color: var(--ct-color-primary);" /></div>
        <div class="empty-orb empty-orb-small empty-orb-chat"><MessageSquare :size="20" style="color: var(--ct-chart-3);" /></div>
        <div class="empty-orb empty-orb-small empty-orb-star"><Sparkles :size="18" style="color: var(--ct-chart-4);" /></div>
      </div>

      <h2>还没有历史记录</h2>
      <p class="page-empty-lead">当前还没有可分析的聊天会话，但这个页面不该再是空白的。</p>
      <p class="page-empty-hint">先在<button type="button" style="color: var(--ct-color-primary); text-decoration: underline; background: none; border: none; padding: 0; cursor: pointer;" @click="openSettingsTab('account')">设置 · 数据</button>中导入微信数据，完成后这里会自动显示联系人、分析入口和时间线内容。</p>
    </div>

    <div class="page-empty-grid">
      <div class="page-empty-card">
        <span class="page-empty-card-label">下一步</span>
        <strong>去<button type="button" style="color: var(--ct-color-primary); text-decoration: underline; background: none; border: none; padding: 0; cursor: pointer;" @click="openSettingsTab('account')">设置 · 数据</button>导入聊天数据</strong>
        <p>导入完成后，历史记录页会自动恢复完整展示。</p>
      </div>

      <div class="page-empty-card">
        <span class="page-empty-card-label">导入后可查看</span>
        <strong>关系分析、互动特征、时间线</strong>
        <p>包括联系人切换、趋势图、词云和画像档案等内容。</p>
      </div>

      <div class="page-empty-card page-empty-card-accent">
        <span class="page-empty-card-label">当前状态</span>
        <strong>暂无可分析会话</strong>
        <p>页面已保持可见，并提供明确的下一步引导。</p>
      </div>
    </div>
  </div>

  <!-- 单聊：分析工作台（关系洞察 + 互动特征 + 触发/进度/配置，自包含） -->
  <AnalysisWorkbench v-if="selectedConversationId && !isGroupConversation"
    :conversation-id="selectedConversationId" />

  <!-- 群聊：群聊工作台（发言统计 + 日报，四维好感度对群聊意义有限） -->
  <div v-if="selectedConversationId && isGroupConversation" class="group-workbench fade-in">
    <CtCard class="group-stats-card" title="群聊发言统计">
      <div v-if="groupStatsLoading" class="group-empty">统计加载中...</div>
      <template v-else-if="groupStats && groupStats.members && groupStats.members.length">
        <div class="group-overview">
          <span>文本消息 <strong>{{ groupStats.total_messages }}</strong> 条</span>
          <span>发言成员 <strong>{{ groupStats.members.length }}</strong> 人</span>
          <span v-if="groupStats.my_rank">我的发言排名 <strong>第 {{ groupStats.my_rank }}</strong></span>
          <span v-else>我未在统计范围内发言</span>
        </div>
        <div class="group-member-table">
          <div class="group-member-row group-member-head">
            <span class="gm-name">成员</span>
            <span class="gm-count">消息数</span>
            <span class="gm-share">占比</span>
            <span class="gm-chars">字数</span>
          </div>
          <div v-for="m in groupStats.members.slice(0, 20)" :key="m.name" class="group-member-row" :class="{ me: m.name === '我' }">
            <span class="gm-name">{{ m.name }}</span>
            <span class="gm-count">{{ m.message_count }}</span>
            <span class="gm-share">
              <span class="gm-share-bar"><i :style="{ width: (m.share * 100).toFixed(1) + '%' }"></i></span>
              <em>{{ (m.share * 100).toFixed(1) }}%</em>
            </span>
            <span class="gm-chars">{{ m.char_count }}</span>
          </div>
        </div>
        <div v-if="groupStats.top_words && groupStats.top_words.length" class="group-top-words">
          <span class="gtw-title">高频词</span>
          <span v-for="w in groupStats.top_words.slice(0, 15)" :key="w.word" class="gtw-chip">{{ w.word }} ×{{ w.count }}</span>
        </div>
        <p class="group-note">成员名为导入时解析的显示短名；群聊暂不提供成员关系分析。</p>
      </template>
      <p v-else class="group-empty">暂无群聊消息或统计失败。</p>
    </CtCard>

    <CtCard class="group-summary-card" title="群聊日报">
      <div class="group-summary-controls">
        <select v-model.number="groupSummaryDays" class="group-days-select" :disabled="groupSummaryLoading">
          <option :value="1">近 1 天</option>
          <option :value="7">近 7 天</option>
          <option :value="30">近 30 天</option>
        </select>
        <CtButton variant="primary" :loading="groupSummaryLoading" :disabled="groupSummaryLoading" @click="handleGenerateGroupSummary">
          {{ groupSummaryLoading ? '生成中...' : '生成日报' }}
        </CtButton>
        <CtButton v-if="groupSummaryLoading" variant="ghost" @click="handleCancelGroupSummary">取消</CtButton>
      </div>
      <div v-if="groupSummary" class="group-summary-body">
        <p v-if="groupSummary.degraded" class="group-summary-degraded">{{ groupSummary.degraded_reason }}</p>
        <p v-else class="group-summary-text">{{ groupSummary.summary }}</p>
      </div>
      <p v-else class="group-summary-hint">
        由 LLM 汇总近期主要话题、群氛围与值得注意的互动；未配置模型时仅提供左侧统计。
      </p>
    </CtCard>
  </div>

  <!-- 导出聊天记录弹窗 -->
  <Teleport to="body">
    <div v-if="exportDialogVisible" class="ct-modal-overlay" @click.self="exportDialogVisible = false">
      <div class="export-dialog">
        <div class="pd-header">
          <h3 class="pd-title">导出聊天记录</h3>
          <button class="pd-close" @click="exportDialogVisible = false">✕</button>
        </div>
        <div v-if="!exportResult" class="export-body">
          <div class="export-formats">
            <label v-for="opt in [
              { value: 'txt', label: 'TXT 纯文本', tip: '打印/备忘录' },
              { value: 'csv', label: 'CSV 表格', tip: 'Excel/分析' },
              { value: 'html', label: 'HTML 聊天页', tip: '分享/存档' },
            ]" :key="opt.value" class="export-fmt" :class="{ active: exportFormat === opt.value }">
              <input type="radio" :value="opt.value" v-model="exportFormat" class="sr-only" />
              <span class="export-fmt-label">{{ opt.label }}</span>
              <span class="export-fmt-tip">{{ opt.tip }}</span>
            </label>
          </div>
          <div class="export-hint">导出当前选中联系人的全部聊天记录（含日期范围筛选）。</div>
        </div>
        <div v-else class="export-body">
          <div class="export-success">
            <p>✅ 已导出 {{ exportResult.count }} 条消息</p>
            <p class="export-path">{{ exportResult.path }}</p>
            <button class="ct-btn secondary ct-btn-sm" @click="openExportFolder">打开所在文件夹</button>
          </div>
        </div>
        <div class="pd-footer">
          <button v-if="!exportResult" class="ct-btn ghost" @click="exportDialogVisible = false">取消</button>
          <button v-if="!exportResult" class="ct-btn primary" :disabled="exporting" @click="confirmExport">
            {{ exporting ? '导出中…' : '导出' }}
          </button>
          <button v-else class="ct-btn primary" @click="exportDialogVisible = false">完成</button>
        </div>
      </div>
    </div>
  </Teleport>
</section>
</template>

<script lang="ts">
import { openSettingsTab } from '@/utils/settingsBus'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { bridgeReady, api } from '@/api/bridge'

import FiltersBar from '@/components/analytics/FiltersBar.vue'
import AnalysisWorkbench from '@/components/analytics/AnalysisWorkbench.vue'
import CtCard from '@/components/base/CtCard.vue'
import CtButton from '@/components/base/CtButton.vue'
import { showDialog } from '@/utils/dialog'
import { toLocalDateKey } from '@/utils/datetime'
import CtAvatar from '@/components/base/CtAvatar.vue'
import {
  FolderArchive,
  MessageSquare,
  Sparkles
} from 'lucide-vue-next'
import { sharedContactId as selectedConversationId } from '@/utils/contactScope'

type Conversation = { id: number; name: string; username: string; message_count: number; last_message_time: string; avatar?: string; conversation_type?: 'private' | 'group' }

export default {
    components: {
        FiltersBar, AnalysisWorkbench, CtCard, CtButton, CtAvatar,
        FolderArchive, MessageSquare, Sparkles
    },
    setup() {
        const activeAccountWxid = ref('')

        // Core State
        const conversations = ref<Conversation[]>([])

        const dates = reactive({ from: '', to: '' })

        const hasConversations = computed(() => conversations.value.length > 0)
        const currentConversation = computed(() => {
            if (!selectedConversationId.value) return undefined
            return conversations.value.find(c => c.id === selectedConversationId.value)
        })

        const currentContactName = computed(() => {
            return currentConversation.value?.name || '选择联系人'
        })
        const isGroupConversation = computed(() => {
            return currentConversation.value?.conversation_type === 'group'
        })

        // ===== 群聊工作台（发言统计 + 日报）=====
        type GroupMemberStat = { name: string; message_count: number; char_count: number; share: number }
        type GroupStats = { total_messages: number; members: GroupMemberStat[]; my_rank: number | null; top_words: Array<{ word: string; count: number }> }
        const groupStats = ref<GroupStats | null>(null)
        const groupStatsLoading = ref(false)
        const groupSummary = ref<{ summary: string; degraded: boolean; degraded_reason?: string } | null>(null)
        const groupSummaryLoading = ref(false)
        const groupSummaryDays = ref(7)

        async function loadGroupStats() {
            if (!isGroupConversation.value || !selectedConversationId.value) {
                groupStats.value = null
                return
            }
            const conversationId = selectedConversationId.value
            groupStatsLoading.value = true
            try {
                await bridgeReady()
                const res = await api.get_group_stats(conversationId)
                if (conversationId !== selectedConversationId.value) return // 已切换联系人（F1）
                groupStats.value = res?.ok ? res : null
            } catch (e) {
                groupStats.value = null
            } finally {
                groupStatsLoading.value = false
            }
        }

        async function handleGenerateGroupSummary() {
            if (!selectedConversationId.value || groupSummaryLoading.value) return
            groupSummaryLoading.value = true
            const conversationId = selectedConversationId.value
            try {
                await bridgeReady()
                const res = await api.generate_group_summary(conversationId, groupSummaryDays.value)
                if (conversationId !== selectedConversationId.value) return // 已切换联系人（F1）
                if (res?.ok) {
                    groupSummary.value = res
                } else {
                    const msg = String(res?.error || '日报生成失败，请重试')
                    if (!msg.includes('已取消')) showDialog(msg) // 主动取消不弹错误
                }
            } catch (e: any) {
                showDialog(e?.message || '日报生成异常')
            } finally {
                groupSummaryLoading.value = false
            }
        }

        async function handleCancelGroupSummary() {
            if (!groupSummaryLoading.value || !selectedConversationId.value) return
            try {
                await bridgeReady()
                await api.cancel_group_summary(selectedConversationId.value)
            } catch {
                // 取消失败不打断（后端请求会自行超时返回）
            }
        }
        const headerAvatarSrc = computed(() => currentConversation.value?.avatar || '')

        function getConversationAnchorDate(conversationId?: number | null): Date {
            const conversation = conversations.value.find(c => c.id === conversationId)
            const rawLastMessageTime = conversation?.last_message_time?.trim()
            if (rawLastMessageTime) {
                const normalized = rawLastMessageTime.replace(' ', 'T')
                const parsed = new Date(normalized)
                if (!Number.isNaN(parsed.getTime())) {
                    return parsed
                }
            }
            return new Date()
        }

        function setDefaultDates(days = 7, anchorDate?: Date) {
            const to = anchorDate ? new Date(anchorDate) : new Date()
            const from = new Date(to)
            from.setDate(to.getDate() - (days - 1))
            // 用本地时区日期键，避免 toISOString() 的 UTC 日期在东八区凌晨少一天
            dates.from = toLocalDateKey(from)
            dates.to = toLocalDateKey(to)
        }

        async function loadConversations() {
            try {
                await bridgeReady()
                const res = await api.get_conversation_list(activeAccountWxid.value || undefined)
                if (res.ok) {
                    conversations.value = res.conversations
                    if (selectedConversationId.value && !conversations.value.some((item) => item.id === selectedConversationId.value)) {
                        selectedConversationId.value = null
                    }
                    if (conversations.value.length > 0 && !selectedConversationId.value) {
                        // 程序性默认选中列表第一个（用户未显式选择时）
                        onConversationChange(conversations.value[0].id)
                    } else if (conversations.value.length === 0) {
                        selectedConversationId.value = null
                    } else {
                        // 跨页共享选人：带着已有选中进入本页，驱动首次加载
                        onConversationChange(selectedConversationId.value)
                    }
                }
            } catch (e: any) { console.error('加载联系人失败', e) }
        }

        function resetAccountScopedState() {
            selectedConversationId.value = null
            conversations.value = []
            groupSummary.value = null
            groupStats.value = null
        }

        async function refreshAccountContext() {
            try {
                const result = await api.get_wechat_accounts()
                if (result?.ok) {
                    activeAccountWxid.value = result.active_account_wxid || ''
                }
            } catch (e) {
                console.error('刷新微信账号上下文失败', e)
            }
        }

        async function onConversationChange(id: number) {
            if (groupSummaryLoading.value && selectedConversationId.value) {
                api.cancel_group_summary(selectedConversationId.value).catch(() => {})
            }
            selectedConversationId.value = id
            setDefaultDates(30, getConversationAnchorDate(id))
            groupSummary.value = null
            loadGroupStats()
        }

        const exportDialogVisible = ref(false)
        const exportFormat = ref<'txt' | 'csv' | 'html'>('txt')
        const exporting = ref(false)
        const exportResult = ref<{ path: string; count: number } | null>(null)

        const handleExport = () => {
            if (!selectedConversationId.value) {
                showDialog('请先选择联系人。')
                return
            }
            exportResult.value = null
            exportDialogVisible.value = true
        }

        async function confirmExport() {
            if (exporting.value || !selectedConversationId.value) return
            exporting.value = true
            try {
                await bridgeReady()
                const res = await api.export_chat_records(
                    selectedConversationId.value,
                    exportFormat.value,
                    dates.from || undefined,
                    dates.to || undefined,
                )
                if (res.ok) {
                    exportResult.value = { path: res.file_path, count: res.record_count }
                } else {
                    showDialog(res.error || '导出失败')
                }
            } catch (e: any) {
                showDialog(e?.message || '导出异常')
            } finally {
                exporting.value = false
            }
        }

        function openExportFolder() {
            if (!exportResult.value) return
            // open_external_url 只放行 http/https（目录会被静默拒绝），走专用目录打开
            api.open_export_folder()
                .catch(() => {})
        }

        async function handleAccountChanged() {
            resetAccountScopedState()
            await refreshAccountContext()
            await loadConversations()
        }

        onMounted(async () => {
            if (!dates.from || !dates.to) setDefaultDates(30)
            await refreshAccountContext()
            await loadConversations()
            window.addEventListener('chrono:wechat-account-changed', handleAccountChanged)
        })

        onUnmounted(() => {
            window.removeEventListener('chrono:wechat-account-changed', handleAccountChanged)
        })

        return {
            conversations, selectedConversationId, dates,
            hasConversations, currentContactName, headerAvatarSrc, isGroupConversation,
            onConversationChange, activeAccountWxid,
            groupStats, groupStatsLoading, groupSummary, groupSummaryLoading, groupSummaryDays,
            handleGenerateGroupSummary, handleCancelGroupSummary,
            exportDialogVisible, exportFormat, exporting, exportResult, handleExport, confirmExport, openExportFolder,
        }
    }
}

</script>

<style scoped>
/* ========================================
   Analytics 页壳（单聊分析已内嵌 AnalysisWorkbench，群聊工作台在批4迁时光页）
   ======================================== */
.analytics-page {
  display: flex;
  flex-direction: column;
  padding: var(--ct-space-md) var(--ct-space-xl) 0 var(--ct-space-xl);
  gap: var(--ct-space-md);
  height: 100%; /* Will only work if App.vue restricts it, but helps elasticity */
}

/* --- Header Section --- */
.analytics-header {
  flex-shrink: 0; /* Prevent header squishing */
  position: relative;
  z-index: 50;
}

/* 空态：白卡安静铺陈，插画用 tint 圆，不再用渐变光斑 */
.page-empty-state {
  position: relative;
  flex: 1;
  min-height: 520px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 28px;
  padding: clamp(32px, 6vw, 72px);
  border-radius: var(--ct-radius-lg);
  background: var(--ct-bg-card);
  box-shadow: var(--ct-shadow-sm);
  overflow: hidden;
}

.page-empty-hero {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 720px;
}

.page-empty-badge {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  margin-bottom: 18px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.page-empty-illustration {
  position: relative;
  width: 180px;
  height: 140px;
  margin-bottom: 10px;
}

.empty-orb {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
}

.empty-orb-main {
  left: 50%;
  top: 18px;
  width: 92px;
  height: 92px;
  transform: translateX(-50%);
  background: var(--ct-color-primary-tint);
}

.empty-orb-small {
  width: 44px;
  height: 44px;
  font-size: 18px;
}

.empty-orb-chat {
  left: 28px;
  top: 72px;
  background: var(--ct-color-success-tint);
}

.empty-orb-star {
  right: 28px;
  top: 34px;
  background: var(--ct-color-warning-tint);
}

.page-empty-state h2 {
  margin: 0 0 12px;
  font-size: clamp(30px, 4.2vw, 42px);
  color: var(--ct-text-primary);
}

.page-empty-state p {
  margin: 0 0 8px;
  font-size: var(--ct-text-lg);
  color: var(--ct-text-secondary);
}

.page-empty-lead {
  max-width: 560px;
  line-height: 1.7;
}

.page-empty-state .page-empty-hint {
  font-size: var(--ct-text-sm);
  color: var(--ct-text-tertiary);
}

.page-empty-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  width: 100%;
  max-width: 960px;
}

.page-empty-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 20px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-card);
  text-align: left;
}

.page-empty-card-accent {
  border-color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
}

.page-empty-card-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ct-text-tertiary);
}

.page-empty-card strong {
  font-size: 15px;
  color: var(--ct-text-primary);
}

.page-empty-card p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-text-tertiary);
}

.user-profile-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--ct-space-lg);
  padding: var(--ct-space-lg) var(--ct-space-xl);
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
}

.profile-main {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 1;
}

.profile-avatar-wrap {
  flex-shrink: 0;
}

.profile-avatar {
  flex-shrink: 0;
  border: 2px solid var(--ct-bg-card);
  box-shadow: 0 0 0 1px var(--ct-border-color);
}

.profile-info {
  min-width: 0;
  flex: 1;
}

.name-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-lg);
  min-width: 0;
}

.profile-name {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--ct-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.contact-selector-wrap {
  min-width: 0;
  flex-shrink: 1;
}

.header-actions-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Transitions */
.fade-in {
  animation: fadeIn 0.4s ease-out forwards;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 导出弹窗（白卡解剖：发丝线分区，按钮走 ct-btn 体系） */
.export-dialog {
  width: 420px; max-width: 92vw;
  background: var(--ct-bg-card);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-lg);
  overflow: hidden;
}
.export-body { padding: 16px 20px; }
.export-formats { display: flex; gap: 8px; }
.export-fmt {
  flex: 1; padding: 12px 8px; border-radius: var(--ct-radius-md); cursor: pointer;
  border: 1px solid var(--ct-border-color); background: var(--ct-bg-card);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  transition: border-color 0.15s, background-color 0.15s;
}
.export-fmt:hover { border-color: var(--ct-border-color-hover); }
.export-fmt.active { border-color: var(--ct-color-primary); background: var(--ct-color-primary-tint); }
.export-fmt-label { font-size: 13px; font-weight: 600; }
.export-fmt-tip { font-size: 10px; color: var(--ct-text-tertiary); }
.export-hint { margin-top: 12px; font-size: 11px; color: var(--ct-text-tertiary); line-height: 1.5; }
.export-success { text-align: center; padding: 12px 0; }
.export-success p { margin: 4px 0; font-size: 14px; }
.export-path { font-size: 11px; color: var(--ct-text-tertiary); word-break: break-all; }
.pd-header { display: flex; align-items: center; gap: 12px; padding: 18px 20px; border-bottom: 1px solid var(--ct-border-color); }
.pd-title { margin: 0; font-size: 17px; font-weight: 600; flex: 1; }
.pd-close { background: none; border: none; cursor: pointer; color: var(--ct-text-secondary); font-size: 16px; padding: 4px 8px; border-radius: var(--ct-radius-sm); }
.pd-close:hover { color: var(--ct-text-primary); background: var(--ct-bg-hover); }
.pd-footer { display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid var(--ct-border-color); }
.sr-only { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }


/* --- 群聊工作台 --- */
.group-workbench {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--ct-space-md);
  align-items: start;
}

.group-stats-card,
.group-summary-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group-overview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-lg);
  font-size: 12px;
  color: var(--ct-text-secondary);
}

.group-overview strong {
  color: var(--ct-text-primary);
  font-family: var(--ct-font-mono);
}

.group-member-table {
  display: flex;
  flex-direction: column;
  font-size: 12px;
}

.group-member-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) 70px minmax(0, 2fr) 70px;
  gap: 8px;
  align-items: center;
  padding: 5px 6px;
  border-bottom: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
}

.group-member-row:last-child {
  border-bottom: none;
}

.group-member-head {
  color: var(--ct-text-tertiary);
  font-size: 11px;
  font-weight: 500;
}

.group-member-row.me .gm-name {
  color: var(--ct-color-primary);
  font-weight: 600;
}

.gm-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gm-count,
.gm-chars {
  text-align: right;
  font-family: var(--ct-font-mono);
}

.gm-share {
  display: flex;
  align-items: center;
  gap: 6px;
}

.gm-share-bar {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: var(--ct-bg-sunken);
  overflow: hidden;
}

.gm-share-bar i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--ct-color-primary);
}

.gm-share em {
  font-style: normal;
  font-size: 11px;
  font-family: var(--ct-font-mono);
  color: var(--ct-text-tertiary);
  min-width: 44px;
  text-align: right;
}

.group-top-words {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.gtw-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--ct-text-tertiary);
}

.gtw-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--ct-radius-full);
  background: var(--ct-bg-sunken);
  color: var(--ct-text-secondary);
}

.group-note,
.group-empty,
.group-summary-hint {
  margin: 0;
  font-size: 11px;
  color: var(--ct-text-tertiary);
}

.group-summary-controls {
  display: flex;
  gap: 10px;
  align-items: center;
}

.group-days-select {
  padding: 7px 10px;
  padding-right: 28px;
  font-size: 12px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background-color: var(--ct-bg-card);
  color: var(--ct-text-primary);
  outline: none;
}

.group-summary-body {
  padding: var(--ct-space-md);
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
}

.group-summary-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--ct-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.group-summary-degraded {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-color-warning);
}

/* --- Responsive --- */
@media (max-width: 768px) {
  .analytics-page {
    padding: var(--ct-space-lg) var(--ct-space-md);
  }

  .page-empty-state {
    min-height: 460px;
    gap: 22px;
  }

  .page-empty-grid {
    grid-template-columns: 1fr;
  }

  .page-empty-illustration {
    transform: scale(0.92);
  }

  .user-profile-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--ct-space-lg);
  }

  .header-actions-group {
    width: 100%;
  }

  .group-workbench {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .page-empty-badge {
    font-size: 11px;
    letter-spacing: 0.06em;
  }

  .page-empty-state h2 {
    font-size: 28px;
  }

  .page-empty-card {
    padding: 16px;
  }
}
</style>
