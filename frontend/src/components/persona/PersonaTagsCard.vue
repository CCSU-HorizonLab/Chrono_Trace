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
  background:
    radial-gradient(circle at top right, rgba(168, 85, 247, 0.12), transparent 45%),
    radial-gradient(circle at bottom left, rgba(99, 102, 241, 0.1), transparent 45%),
    var(--ct-bg-secondary);
  border: 1px solid rgba(139, 92, 246, 0.15); /* primary-subtle */
  box-shadow: 0 8px 32px rgba(139, 92, 246, 0.06);
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
  background: rgba(139, 92, 246, 0.08); /* light primary tint */
  border: 1px solid rgba(139, 92, 246, 0.12);
  color: var(--ct-color-primary);
  font-size: 13px;
  font-weight: 600;
  backdrop-filter: blur(8px);
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
  background: var(--ct-bg-tertiary);
  border: 1px solid var(--ct-border-subtle);
  font-size: 12px;
  color: var(--ct-text-secondary);
}
</style>
