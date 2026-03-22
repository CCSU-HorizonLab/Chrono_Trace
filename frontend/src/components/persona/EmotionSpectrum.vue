<template>
  <CtCard class="persona-panel">
    <template #header>
      <span>情绪光谱墙</span>
    </template>

    <div v-if="items.length" class="emotion-spectrum">
      <div
        v-for="item in items"
        :key="item.label"
        class="emotion-band"
        :style="{ '--emotion-color': item.color, '--emotion-value': `${Math.max(item.value, 0.08) * 100}%` }"
      >
        <div class="emotion-band-head">
          <strong>{{ item.label }}</strong>
          <span>{{ Math.round(item.value * 100) }}%</span>
        </div>
        <div class="emotion-band-track">
          <div class="emotion-band-fill"></div>
        </div>
        <p>{{ item.description }}</p>
      </div>
    </div>

    <div v-else class="persona-empty-mini">暂无足够的情绪样本</div>
  </CtCard>
</template>

<script setup lang="ts">
import type { PropType } from 'vue'
import CtCard from '@/components/base/CtCard.vue'

type EmotionBand = {
  label: string
  value: number
  color: string
  description: string
}

defineProps({
  items: {
    type: Array as PropType<EmotionBand[]>,
    default: () => []
  }
})
</script>

<style scoped>
.emotion-spectrum {
  display: grid;
  gap: 16px;
}

.emotion-band {
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.94), rgba(241, 245, 249, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.emotion-band-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.emotion-band-head strong {
  font-size: 14px;
  color: var(--ct-text-primary);
}

.emotion-band-head span {
  font-size: 12px;
  font-weight: 700;
  color: color-mix(in srgb, var(--emotion-color) 72%, black 16%);
}

.emotion-band-track {
  height: 12px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(148, 163, 184, 0.14);
}

.emotion-band-fill {
  width: var(--emotion-value);
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, color-mix(in srgb, var(--emotion-color) 72%, white 14%), var(--emotion-color));
}

.emotion-band p {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--ct-text-secondary);
}

.persona-empty-mini {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
}
</style>
