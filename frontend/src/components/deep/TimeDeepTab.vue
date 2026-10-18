<template>
  <div class="time-deep-tab">
    <SentimentCoverageBar :conversation-id="conversationId" @backfilled="load()" />

    <div v-if="error" class="state-card">
      <div class="state-text">加载失败：{{ error }}</div>
      <button class="btn" @click="load">重试</button>
    </div>
    <div v-else-if="loading && !payload" class="state-card state-text">正在汇总这段时光…</div>

    <template v-else-if="payload">
      <DeepEmotionPanel
        :buckets="payload.buckets || []"
        :granularity="granularity"
        :affinity="payload.affinity_history || null"
      />
      <WordEvolutionPanel :evolution="payload.wordcloud_evolution || { caliber: 'none', coverage_ratio: 0, halves: [] }" />
      <MilestoneTimeline
        :milestones="payload.milestones || []"
        :turning-points="payload.turning_points || []"
        :granularity="granularity"
      />
      <BigFivePanel :conversation-id="conversationId" />
      <PosterStudio :conversation-id="conversationId" :dates="dates" :contact-name="contactName" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api/bridge'
import SentimentCoverageBar from '@/components/deep/SentimentCoverageBar.vue'
import DeepEmotionPanel from '@/components/deep/DeepEmotionPanel.vue'
import WordEvolutionPanel from '@/components/deep/WordEvolutionPanel.vue'
import MilestoneTimeline from '@/components/deep/MilestoneTimeline.vue'
import BigFivePanel from '@/components/deep/BigFivePanel.vue'
import PosterStudio from '@/components/deep/PosterStudio.vue'

const props = defineProps<{
  conversationId: number
  dates: { from: string; to: string }
  granularity: string
  /** 父页视图纪元：切换会话/账号时 +1，用于丢弃过期响应 */
  viewEpoch: number
  /** 联系人名（海报文件名用） */
  contactName?: string
}>()

const payload = ref<any>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  const epoch = props.viewEpoch
  loading.value = true
  error.value = ''
  try {
    const result = await api.get_deep_analysis(
      props.conversationId, props.dates.from, props.dates.to, props.granularity,
    )
    if (epoch !== props.viewEpoch) return // 已切走，丢弃过期响应
    if (!result?.ok) {
      error.value = result?.error || '未知错误'
      payload.value = null
      return
    }
    payload.value = result
  } catch (e: any) {
    if (epoch !== props.viewEpoch) return
    error.value = e?.message || '请求失败'
    payload.value = null
  } finally {
    if (epoch === props.viewEpoch) loading.value = false
  }
}

watch(
  () => [props.conversationId, props.dates.from, props.dates.to, props.granularity, props.viewEpoch],
  () => { payload.value = null; load() },
  { immediate: true },
)
</script>

<style scoped>
.time-deep-tab {
  display: flex;
  flex-direction: column;
}

.state-card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  padding: var(--ct-space-xl);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--ct-space-md);
}

.state-text {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.btn {
  padding: 6px 14px;
  border: 1px solid var(--ct-border-color);
  background: var(--ct-bg-surface);
  color: var(--ct-text-secondary);
  border-radius: 999px;
  cursor: pointer;
  font-size: var(--ct-text-sm);
}

.btn:hover {
  border-color: var(--ct-color-primary);
  color: var(--ct-color-primary);
}
</style>
