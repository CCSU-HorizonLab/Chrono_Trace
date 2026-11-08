<template>
  <div class="panel meme-dict">
    <div class="panel-head">
      <div>
        <div class="panel-title">专属梗词典</div>
        <div class="panel-sub">你们反复说起的短语——这段关系最独有的词</div>
      </div>
      <span class="panel-badge">{{ items.length ? `${items.length} 条` : '待挖掘' }}</span>
    </div>

    <div v-if="loading" class="empty-state">正在从聊天记录里挖梗…</div>
    <div v-else-if="error" class="meme-err">
      <span>{{ error }}</span>
      <button class="btn" @click="load">重试</button>
    </div>
    <div v-else-if="!items.length" class="empty-state">
      还没挖出专属梗——复现的短语还太少，你们的暗号还没形成（或还没被聊够 8 次）
    </div>

    <template v-else>
      <div class="legend-row meme-legend">
        <span><span class="swatch" :style="{ background: COLOR_ME }" />我</span>
        <span><span class="swatch" :style="{ background: COLOR_OTHER }" />TA</span>
      </div>
      <ul class="meme-list">
        <li v-for="m in items" :key="m.text" class="meme-item">
          <span class="meme-word">{{ m.text }}</span>
          <span class="meme-split" :title="`共 ${m.count} 次 · 我 ${m.me} / TA ${m.ta}`">
            <i :style="{ width: mePct(m), background: COLOR_ME }" />
            <i :style="{ width: taPct(m), background: COLOR_OTHER }" />
          </span>
          <span class="meme-count">×{{ m.count }}</span>
        </li>
      </ul>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { BIG5_COLOR_ME, BIG5_COLOR_OTHER } from '@/components/deep/big5Shared'

/** 专属梗词典（§4.3）：全会话跨度挖掘的复现短语陈列，分侧比例条示意「谁说得多」。 */
const props = defineProps<{ conversationId: number | null }>()

const COLOR_ME = BIG5_COLOR_ME
const COLOR_OTHER = BIG5_COLOR_OTHER

type MemeItem = { text: string; count: number; me: number; ta: number }
const items = ref<MemeItem[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  const id = props.conversationId
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const res = await api.get_meme_dictionary(id)
    if (!res?.ok) {
      error.value = res?.error || '挖掘失败'
      items.value = []
      return
    }
    items.value = res.items || []
  } catch (e: any) {
    error.value = e?.message || '请求失败'
  } finally {
    loading.value = false
  }
}

const mePct = (m: MemeItem) => `${Math.round((m.me / Math.max(m.count, 1)) * 100)}%`
const taPct = (m: MemeItem) => `${Math.round((m.ta / Math.max(m.count, 1)) * 100)}%`

watch(() => props.conversationId, load)
onMounted(load)
</script>

<style scoped>
.meme-legend {
  margin-bottom: 10px;
}

.meme-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meme-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.meme-word {
  min-width: 96px;
  font-weight: 600;
  color: var(--ct-text-primary);
}

.meme-split {
  flex: 1;
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--ct-bg-sunken);
}

.meme-split i {
  display: block;
  height: 100%;
}

.meme-count {
  min-width: 44px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--ct-text-tertiary);
  font-size: 13px;
}

.meme-err {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--ct-color-error);
  font-size: 13px;
}
</style>
