<template>
  <section class="copilot-page">
    <!-- 页头：联系人选择贯通 + 模式分段器（单聊全模式；群聊只有问答——
         陪练/实时都是 1:1 语义） -->
    <div class="copilot-head">
      <FiltersBar
        :conversations="conversations"
        :selected-conversation-id="selectedConversationId"
        :loading="loadingConversations"
        @update:conversation-id="onConversationChange"
      />
      <div class="ct-tabs-capsule copilot-modes" role="tablist" aria-label="智囊模式">
        <button
          v-for="m in modes"
          :key="m.key"
          class="menu-item"
          :class="{ active: mode === m.key }"
          :disabled="m.singleChat && isGroupConversation"
          :title="m.singleChat && isGroupConversation ? '单聊专属' : ''"
          @click="switchMode(m.key)"
        >{{ m.label }}</button>
      </div>
    </div>

    <!-- 主体：未选人引导 / 三模式面板 -->
    <div v-if="!selectedConversationId" class="copilot-empty">
      <p class="copilot-empty-title">先在右上角选一个联系人</p>
      <p class="copilot-empty-sub">问问微信翻聊天记录答问题，陪练帮你拿捏怎么回，实时监听盯着新消息给建议。</p>
    </div>
    <div v-else class="copilot-body">
      <QaChat
        v-show="mode === 'qa'"
        :conversation-id="selectedConversationId"
        :contact-name="currentContactName"
      />
      <RehearsePanel
        v-if="mode === 'rehearse' && !isGroupConversation"
        :conversation-id="selectedConversationId"
        :contact-name="currentContactName"
      />
      <div v-show="mode === 'realtime' && !isGroupConversation" class="copilot-realtime">
        <MonitorControlCard
          :conversation-id="selectedConversationId"
          :contact-name="currentContactName"
          :account-wxid="activeAccountWxid || ''"
        />
        <div class="realtime-profiles">
          <ProfileBriefCard
            kind="contact"
            :contact-name="currentContactName"
            :account-wxid="activeAccountWxid || ''"
            :refresh-key="profileRefreshKey"
          />
          <ProfileBriefCard
            kind="self"
            :contact-name="currentContactName"
            :account-wxid="activeAccountWxid || ''"
            :refresh-key="profileRefreshKey"
          />
        </div>
      </div>
    </div>

    <!-- 常驻隐私徽标（重设计 P4）：对话式 AI 的信任底线一句话 -->
    <footer class="copilot-privacy">
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M8 1.5l5 2v4c0 3.2-2.1 5.6-5 7-2.9-1.4-5-3.8-5-7v-4l5-2z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
        <path d="M5.5 8l1.7 1.7L10.5 6.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      全部本地分析 · 远程仅发送脱敏摘要
    </footer>
  </section>
</template>

<script setup lang="ts">
/**
 * 智囊页（重设计 §4.4「我该怎么办」）：对话式统一 AI。
 * 三模式分段器——问答（问问微信迁入）/ 陪练（贴消息出三温度档）/
 * 实时（监听控制 + 双方画像速览，自 Analytics 实时助手页签迁入）。
 * 选人沿用 FiltersBar「选人一次贯通」；隐私徽标常驻页脚（P4）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import MonitorControlCard from '@/components/realtime/MonitorControlCard.vue'
import ProfileBriefCard from '@/components/persona/ProfileBriefCard.vue'
import QaChat from '@/components/copilot/QaChat.vue'
import RehearsePanel from '@/components/copilot/RehearsePanel.vue'

type Mode = 'qa' | 'rehearse' | 'realtime'

const modes: Array<{ key: Mode; label: string; singleChat?: boolean }> = [
  { key: 'qa', label: '问答' },
  { key: 'rehearse', label: '陪练', singleChat: true },
  { key: 'realtime', label: '实时', singleChat: true },
]

const mode = ref<Mode>('qa')
const conversations = ref<any[]>([])
const loadingConversations = ref(false)
const selectedConversationId = ref<number | null>(null)
const activeAccountWxid = ref('')
const profileRefreshKey = ref(0) // 画像简卡刷新键（预留：实时页生成完成后 +1

const currentContactName = computed(
  () => conversations.value.find((c: any) => c.id === selectedConversationId.value)?.name
    || conversations.value.find((c: any) => c.id === selectedConversationId.value)?.username
    || '',
)
const isGroupConversation = computed(
  () => conversations.value.find((c: any) => c.id === selectedConversationId.value)?.conversation_type === 'group',
)

function switchMode(m: Mode) {
  mode.value = m
}

async function loadConversations() {
  loadingConversations.value = true
  try {
    const res = await api.get_conversation_list(activeAccountWxid.value || undefined)
    if (res?.ok) {
      conversations.value = res.conversations || []
      // 选中人不在了（换账号/删库）先清位；未显式选过则默认列表第一个
      if (selectedConversationId.value && !conversations.value.some((c: any) => c.id === selectedConversationId.value)) {
        selectedConversationId.value = null
      }
      if (!selectedConversationId.value && conversations.value.length > 0) {
        selectedConversationId.value = conversations.value[0].id
      }
    }
  } catch {
    // 列表加载失败保持空态引导
  } finally {
    loadingConversations.value = false
  }
}

function onConversationChange(id: number) {
  selectedConversationId.value = id
}

async function refreshAccountContext() {
  try {
    const result = await api.get_wechat_accounts()
    if (result?.ok) {
      activeAccountWxid.value = result.active_account_wxid || ''
    }
  } catch {
    activeAccountWxid.value = ''
  }
}

async function handleAccountChanged() {
  selectedConversationId.value = null
  conversations.value = []
  await refreshAccountContext()
  await loadConversations()
}

// 群聊没有陪练/实时：处于这两模式时回退问答（对齐 Analytics 旧守卫语义）
watch(isGroupConversation, (isGroup) => {
  if (isGroup && mode.value !== 'qa') mode.value = 'qa'
})

onMounted(async () => {
  await refreshAccountContext()
  await loadConversations()
  window.addEventListener('chrono:wechat-account-changed', handleAccountChanged)
})

onUnmounted(() => {
  window.removeEventListener('chrono:wechat-account-changed', handleAccountChanged)
})
</script>

<style scoped>
.copilot-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: var(--ct-space-md);
}

.copilot-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
}

.copilot-modes { flex: none; }

.copilot-modes .menu-item:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.copilot-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.copilot-realtime {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.realtime-profiles {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ct-space-md);
}

.copilot-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.copilot-empty-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--ct-text-primary); }
.copilot-empty-sub { margin: 0; font-size: 13px; color: var(--ct-text-tertiary); }

/* 隐私徽标：右下常驻（对话式 AI 信任底线） */
.copilot-privacy {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  font-size: 11px;
  color: var(--ct-text-tertiary);
}

@media (max-width: 720px) {
  .realtime-profiles { grid-template-columns: 1fr; }
}
</style>
