<template>
  <CtCard class="persona-core-card">
    <div class="persona-core-shell">
      <div class="persona-core-copy">
        <div class="persona-core-kicker">Persona Core Summary</div>
        <h2>{{ title }}</h2>
        <p class="persona-core-summary">{{ summary }}</p>
        <p v-if="note" class="persona-core-note">{{ note }}</p>
      </div>

      <div class="persona-tag-cluster" v-if="tags.length">
        <span v-for="tag in tags" :key="tag" class="persona-tag-pill">{{ tag }}</span>
      </div>

      <div class="persona-meta-row" v-if="metaItems.length">
        <span v-for="item in metaItems" :key="item" class="persona-meta-pill">{{ item }}</span>
      </div>
    </div>
  </CtCard>
</template>

<script setup lang="ts">
import CtCard from '@/components/base/CtCard.vue'

defineProps<{
  title: string
  summary: string
  note?: string
  tags: string[]
  metaItems: string[]
}>()
</script>

<style scoped>
.persona-core-card {
  overflow: hidden;
  background: var(--ct-bg-sunken);
}

.persona-core-shell {
  display: flex;
  flex-direction: column;
  gap: 18px;
  color: var(--ct-text-primary);
}

.persona-core-kicker {
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ct-color-primary);
  opacity: 0.8;
  font-weight: 600;
}

.persona-core-copy h2 {
  margin: 8px 0 12px;
  font-size: clamp(28px, 4vw, 42px);
  line-height: 1.05;
  color: var(--ct-text-primary);
}

.persona-core-summary {
  margin: 0;
  font-size: 15px;
  line-height: 1.8;
  color: var(--ct-text-secondary);
  max-width: 78ch;
}

.persona-core-note {
  margin: 12px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ct-text-tertiary);
}

.persona-tag-cluster {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.persona-tag-pill {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 0 16px;
  border-radius: 999px;
  background: var(--ct-color-primary-tint);
  border: 1px solid color-mix(in srgb, var(--ct-color-primary) 16%, transparent);
  color: var(--ct-color-primary);
  font-size: 13px;
  font-weight: 600;
}

.persona-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.persona-meta-pill {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  background: var(--ct-bg-sunken);
  font-size: 12px;
  color: var(--ct-text-secondary);
}
</style>
