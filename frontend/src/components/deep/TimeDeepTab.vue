<template>
  <div class="time-deep-tab">
    <SentimentCoverageBar :conversation-id="conversationId" @backfilled="load()" />

    <!-- 页签工具条：锚点导航 + 全局分段选择器（驱动词云/大五）+ 实体图例。
         分段从词云面板上移至此——五面板共用的时间维度不该藏在某个面板头里 -->
    <div class="deep-toolbar">
      <nav class="anchor-nav" aria-label="时光深度面板导航">
        <button v-for="a in anchors" :key="a.id" class="btn" @click="scrollTo(a.id)">
          {{ a.label }}
        </button>
      </nav>
      <div class="toolbar-right">
        <div class="seg-picker" role="group" aria-label="分段数">
          <span class="picker-label">分段</span>
          <button
            v-for="n in segmentOptions"
            :key="n"
            class="btn"
            :class="{ active: wordSegments === n }"
            @click="wordSegments = n"
          >{{ n }}</button>
        </div>
        <div class="legend-row">
          <span><span class="swatch" :style="{ background: BIG5_COLOR_ME }" />我</span>
          <span><span class="swatch" :style="{ background: BIG5_COLOR_OTHER }" />TA</span>
        </div>
      </div>
    </div>

    <!-- 章节面板自取数据（不依赖 deep payload）：deep 加载失败时照常可用 -->
    <div :id="anchors[0].id" class="anchor-target">
      <RelationshipChaptersPanel
        :conversation-id="conversationId"
        :view-epoch="viewEpoch"
      />
    </div>

    <div v-if="error" class="panel state-card">
      <div class="state-text">加载失败：{{ error }}</div>
      <button class="btn" @click="load">重试</button>
    </div>
    <div v-else-if="loading && !payload" class="skeleton-stack" aria-label="加载中">
      <div class="panel"><div class="skeleton sk-emotion" /></div>
      <div class="panel"><div class="skeleton sk-words" /></div>
      <div class="panel"><div class="skeleton sk-big5" /></div>
    </div>

    <template v-else-if="payload">
      <div :id="anchors[1].id" class="anchor-target">
        <DeepEmotionPanel
          :buckets="payload.buckets || []"
          :granularity="granularity"
          :affinity="payload.affinity_history || null"
        />
      </div>
      <div :id="anchors[2].id" class="anchor-target">
        <WordEvolutionPanel
          :evolution="payload.wordcloud_evolution || { caliber: 'none', coverage_ratio: 0, segments: [] }"
        />
      </div>
      <div :id="anchors[3].id" class="anchor-target">
        <Big5EvolutionPanel
          :conversation-id="conversationId"
          :evolution="payload.big5_evolution"
          :view-epoch="viewEpoch"
        />
      </div>
      <div :id="anchors[4].id" class="anchor-target">
        <ProfileEvolutionPanel
          :conversation-id="conversationId"
          :dates="dates"
          :view-epoch="viewEpoch"
          :contact-name="contactName"
        />
      </div>
      <div :id="anchors[5].id" class="anchor-target">
        <MilestoneTimeline
          :milestones="payload.milestones || []"
          :turning-points="payload.turning_points || []"
          :granularity="granularity"
        />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { BIG5_COLOR_ME, BIG5_COLOR_OTHER } from '@/components/deep/big5Shared'
import SentimentCoverageBar from '@/components/deep/SentimentCoverageBar.vue'
import RelationshipChaptersPanel from '@/components/deep/RelationshipChaptersPanel.vue'
import DeepEmotionPanel from '@/components/deep/DeepEmotionPanel.vue'
import WordEvolutionPanel from '@/components/deep/WordEvolutionPanel.vue'
import Big5EvolutionPanel from '@/components/deep/Big5EvolutionPanel.vue'
import ProfileEvolutionPanel from '@/components/deep/ProfileEvolutionPanel.vue'
import MilestoneTimeline from '@/components/deep/MilestoneTimeline.vue'

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
// 词云演变分段数（2~6，默认 4）；工具条选择器改它触发整 payload 重拉（词云与大五共用）
const wordSegments = ref(4)
const segmentOptions = [2, 3, 4, 5, 6]

const anchors = [
  { id: 'deep-anchor-chapters', label: '章节' },
  { id: 'deep-anchor-emotion', label: '情绪' },
  { id: 'deep-anchor-words', label: '词云' },
  { id: 'deep-anchor-big5', label: '大五' },
  { id: 'deep-anchor-profile', label: '画像' },
  { id: 'deep-anchor-milestones', label: '里程碑' },
]

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function load() {
  const epoch = props.viewEpoch
  loading.value = true
  error.value = ''
  try {
    const result = await api.get_deep_analysis(
      props.conversationId, props.dates.from, props.dates.to, props.granularity, wordSegments.value,
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
  () => [props.conversationId, props.dates.from, props.dates.to, props.granularity, props.viewEpoch, wordSegments.value],
  () => { payload.value = null; load() },
  { immediate: true },
)
</script>

<style scoped>
.time-deep-tab {
  display: flex;
  flex-direction: column;
}

/* 工具条吸顶（滚动祖先为 .tab-content.deep-tab）：白底压住滚过的内容 */
.deep-toolbar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
  padding: var(--ct-space-sm) 0;
  margin-bottom: var(--ct-space-sm);
  background: var(--ct-bg-card);
  border-bottom: 1px solid var(--ct-border-color);
}

.anchor-nav {
  display: flex;
  gap: var(--ct-space-xs);
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--ct-space-lg);
  flex-wrap: wrap;
}

.seg-picker {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
}

.picker-label {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  margin-right: 2px;
}

/* 锚点目标预留吸顶工具条高度，标题不被遮 */
.anchor-target {
  scroll-margin-top: 52px;
}

.state-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--ct-space-md);
}

.state-text {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-sm);
}

.skeleton-stack .sk-emotion { height: 300px; }
.skeleton-stack .sk-words { height: 200px; }
.skeleton-stack .sk-big5 { height: 150px; }
</style>
