<template>
  <Teleport to="body">
    <Transition name="ob-fade">
      <div v-if="visible" class="ob-overlay">
        <div class="panel ob-shell">
          <div class="panel-head ob-head">
            <div class="ob-head-copy">
              <h2>欢迎使用 Chrono Trace</h2>
              <p>本地分析微信聊天数据 —— 四步开始：目录、密钥、导入，然后标记对你重要的人。</p>
            </div>
            <button class="btn ghost ob-skip" @click="dismiss">暂时跳过</button>
          </div>

          <ol class="ob-steps">
            <li v-for="(label, i) in stepLabels" :key="label" :class="stepClass(i)">
              <span class="ob-step-num">{{ i + 1 }}</span>
              <span>{{ label }}</span>
            </li>
          </ol>

          <div class="ob-body">
            <!-- 步骤 1-3：复用导入面板全管线（目录确认/密钥捕获/导入进度） -->
            <ImportPanel v-if="step < 4" class="ob-import" @imported="enterPick" />
            <!-- 步骤 4：标记重要的人（消息量前 10 私聊，选中即落脉搏） -->
            <div v-else class="ob-pick">
              <p v-if="loadingList" class="ob-hint">正在加载联系人…</p>
              <p v-else-if="!candidates.length" class="ob-hint">
                未找到私聊联系人。可先跳过，导入更多数据后再来。
              </p>
              <ul v-else class="ob-people">
                <li
                  v-for="conv in candidates"
                  :key="conv.id"
                  :class="{ active: conv.id === pickedId }"
                  @click="pickedId = conv.id"
                >
                  <CtAvatar :src="conv.avatar" :name="conv.name || conv.username || ''" :size="34" />
                  <div class="ob-person-copy">
                    <span class="ob-person-name">{{ conv.name || conv.username || '未知联系人' }}</span>
                    <span class="ob-person-meta">{{ conv.message_count }} 条消息</span>
                  </div>
                </li>
              </ul>
            </div>
          </div>

          <div v-if="step === 4" class="ob-foot">
            <button class="btn primary" :disabled="!pickedId" @click="finish">开始使用</button>
            <p class="ob-foot-note">将进入脉搏页——首次全面分析可在各页顶部的分析入口运行。</p>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ImportPanel from '@/components/data/ImportPanel.vue'
import CtAvatar from '@/components/base/CtAvatar.vue'
import { bridgeReady, api } from '@/api/bridge'
import { sharedContactId } from '@/utils/contactScope'
import { safeSetItem } from '@/utils/safeStorage'

type Conv = {
  id: number
  name: string
  username?: string
  message_count: number
  avatar?: string
  conversation_type?: 'private' | 'group'
}

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const stepLabels = ['数据目录', '获取密钥', '导入数据', '标记重要的人']
const step = ref(1)
const loadingList = ref(false)
const candidates = ref<Conv[]>([])
const pickedId = ref<number | null>(null)

const stepClass = (i: number) => ({
  done: step.value > i + 1 || (step.value === 4 && i === 3 && pickedId.value != null),
  active: step.value === i + 1,
})

// 向导面板内嵌导入中态：ImportPanel 未导出内部状态，以步骤未推进近似（导入成功即进第 4 步）
const enterPick = async () => {
  step.value = 4
  loadingList.value = true
  try {
    await bridgeReady()
    let wxid: string | undefined
    try {
      const acct = await api.get_wechat_accounts()
      if (acct?.ok) wxid = acct.active_account_wxid || undefined
    } catch { /* 账号上下文失败按全量列表兜底 */ }
    const res = await api.get_conversation_list(wxid)
    if (res.ok) {
      candidates.value = (res.conversations || [])
        .filter((c: Conv) => c.conversation_type !== 'group')
        .slice(0, 10)
      pickedId.value = candidates.value[0]?.id ?? null
    }
  } finally {
    loadingList.value = false
  }
}

const dismiss = () => {
  safeSetItem('chrono_onboarding_dismissed', '1', window.sessionStorage)
  emit('close')
}

const finish = () => {
  if (pickedId.value != null) sharedContactId.value = pickedId.value
  safeSetItem('chrono_onboarding_dismissed', '1', window.sessionStorage)
  emit('close')
  void router.push('/')
}

// 每次打开重置到导入步骤（空库重进时从头来）
watch(() => props.visible, (v) => {
  if (v) {
    step.value = 1
    pickedId.value = null
    candidates.value = []
  }
})
</script>

<style scoped>
.ob-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: var(--ct-bg-app);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}

.ob-shell {
  width: min(880px, 100%);
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ob-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.ob-head-copy h2 { margin: 0 0 4px; }
.ob-head-copy p { margin: 0; color: var(--ct-text-secondary); }

.ob-steps {
  list-style: none;
  display: flex;
  gap: 8px;
  margin: 0;
  padding: 12px 0;
  border-bottom: 1px solid var(--ct-border-color);
}

.ob-steps li {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
  color: var(--ct-text-tertiary);
  font-size: 13px;
}

.ob-steps li.active {
  background: var(--ct-color-primary-tint);
  color: var(--ct-color-primary);
  font-weight: var(--ct-font-medium);
}

.ob-steps li.done { color: var(--ct-text-secondary); }

.ob-step-num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  background: var(--ct-bg-card);
  flex-shrink: 0;
}

.ob-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0 12px;
}

.ob-import :deep(.import-section:first-child .section-title) { display: none; }

.ob-pick .ob-hint { color: var(--ct-text-secondary); }

.ob-people {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.ob-people li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-card);
  cursor: pointer;
}

.ob-people li:hover { background: var(--ct-bg-hover); }

.ob-people li.active {
  border-color: var(--ct-color-primary);
  background: var(--ct-color-primary-tint);
}

.ob-person-copy { display: flex; flex-direction: column; min-width: 0; }
.ob-person-name { font-weight: var(--ct-font-medium); }
.ob-person-meta { font-size: 12px; color: var(--ct-text-tertiary); }

.ob-foot {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--ct-border-color);
}

.ob-foot-note { margin: 0; font-size: 12px; color: var(--ct-text-tertiary); }

.ob-fade-enter-active { transition: opacity 0.25s ease; }
.ob-fade-enter-from { opacity: 0; }
</style>
