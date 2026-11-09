<template>
<section class="avatar-page ct-page">
  <!-- 页头：返回画像 + 选人器（与画像页同款，选人一次贯通） -->
  <header v-if="conversations.length" class="avatar-header fade-in">
    <router-link to="/persona" class="avatar-back text-link" title="回到画像页">← 画像</router-link>
    <div class="avatar-title-block">
      <h1 class="avatar-title">AI 分身 · 和 {{ currentContactName || 'TA' }} 聊聊</h1>
      <FiltersBar :conversations="conversations" :selected-conversation-id="selectedConversationId" :loading="loading"
        @update:conversation-id="onConversationChange" />
    </div>
  </header>

  <div v-else-if="!loading" class="panel avatar-empty">
    <div class="panel-head"><span class="panel-title">AI 分身</span></div>
    <p class="avatar-empty-text">还没有可以对话的聊天记录。</p>
    <button type="button" class="btn primary" @click="openSettingsTab('account')">去导入微信数据</button>
  </div>

  <template v-if="selectedConversationId && !isGroup">
    <!-- 边界横幅（§6.3）：常驻明示模拟性质——怀念与复盘演练的用途下，
         这行字是产品边界，不是可关闭的提示 -->
    <div class="avatar-boundary fade-in" role="note">
      <span class="avatar-boundary-mark" aria-hidden="true">🕯</span>
      <p>这是基于聊天记录的 AI 模拟，不是 {{ currentContactName || 'TA' }} 本人。可以用来怀念、或复盘「当时要是那样回会怎样」；模拟止于本应用内的对话，不会代发任何消息。</p>
    </div>

    <AvatarChat
      :key="selectedConversationId"
      :conversation-id="selectedConversationId"
      :contact-name="currentContactName"
    />
  </template>

  <!-- 群聊：分身是 1:1 语气模拟，群聊没有单一「TA」 -->
  <div v-else-if="selectedConversationId && isGroup" class="panel avatar-group-hint">
    <p>分身是两个人之间的语气模拟，群聊里没有单一的「TA」。换个单聊联系人，或回画像页看看群聊的时光与分析。</p>
    <div class="avatar-group-actions">
      <router-link to="/persona" class="btn">回画像页</router-link>
      <router-link to="/timeline" class="btn">去时光页 →</router-link>
    </div>
  </div>
</section>
</template>

<script setup lang="ts">
import { openSettingsTab } from '@/utils/settingsBus'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { bridgeReady, api } from '@/api/bridge'
import FiltersBar from '@/components/analytics/FiltersBar.vue'
import AvatarChat from '@/components/persona/AvatarChat.vue'

type Conversation = { id: number; name: string; username: string; avatar?: string; conversation_type?: 'private' | 'group' }

/** 分身对话页（§6.3）：画像页入口 → 独立全屏对话（FiltersBar 选人 +
 * 边界横幅 + AvatarChat）。入口常开：画像缺席时后端降级为语气+记忆。 */

const route = useRoute()
const conversations = ref<Conversation[]>([])
const selectedConversationId = ref<number | null>(null)
const loading = ref(false)

const currentConversation = computed(() => conversations.value.find((c) => c.id === selectedConversationId.value) || null)
const currentContactName = computed(() => currentConversation.value?.name || currentConversation.value?.username || '')
const isGroup = computed(() => currentConversation.value?.conversation_type === 'group')

function onConversationChange(id: number) {
  selectedConversationId.value = id
}

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
      // 画像页入口带 query.cid 预选；无效则回落首个单聊
      const fromQuery = Number(route.query.cid || 0)
      const preset = conversations.value.find((c) => c.id === fromQuery && c.conversation_type !== 'group')
      const first = preset || conversations.value.find((c) => c.conversation_type !== 'group')
      if (first) onConversationChange(first.id)
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
.avatar-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}

.avatar-back {
  flex-shrink: 0;
  font-size: 13px;
}

.avatar-title-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.avatar-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

/* 边界横幅：warning tint 底 + 琥珀字（语义色惯用语） */
.avatar-boundary {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: var(--ct-space-md);
  background: var(--ct-color-warning-tint);
  border-radius: var(--ct-radius-md);
}

.avatar-boundary-mark {
  flex-shrink: 0;
  font-size: 15px;
  line-height: 1.6;
}

.avatar-boundary p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ct-color-warning);
}

.avatar-empty {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
  align-items: flex-start;
}

.avatar-empty-text {
  margin: 0;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.avatar-group-hint {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-md);
}

.avatar-group-hint p {
  margin: 0;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
  line-height: 1.7;
}

.avatar-group-actions {
  display: flex;
  gap: var(--ct-space-sm);
}
</style>
