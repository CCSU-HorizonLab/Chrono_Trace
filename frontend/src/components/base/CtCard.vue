<template>
  <section class="ct-card">
    <header v-if="hasHeader" class="ct-card-hd">
      <slot name="header">
        <span>{{ title }}</span>
        <div class="_actions"><slot name="actions" /></div>
      </slot>
    </header>
    <div class="ct-card-bd">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="ct-card-ft">
      <slot name="footer" />
    </footer>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ title?: string }>()
const hasHeader = computed(() => !!props.title || !!useSlots().header || !!useSlots().actions)
</script>
<style scoped>
.ct-card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-sm);
  color: var(--ct-text-primary);
  padding: var(--ct-space-lg);
  transition: transform var(--ct-transition-normal) var(--ct-ease-out),
              box-shadow var(--ct-transition-normal) var(--ct-ease-out),
              border-color var(--ct-transition-normal) var(--ct-ease-out);
}

.ct-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--ct-shadow-lg);
  border-color: var(--ct-border-color-hover);
}

.ct-card-hd {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  padding-bottom: var(--ct-space-md);
  margin-bottom: var(--ct-space-md);
  border-bottom: 1px solid var(--ct-border-color);
  font-family: var(--ct-font-display);
  font-size: var(--ct-text-lg);
  font-weight: var(--ct-font-semibold);
  color: var(--ct-text-primary);
}

.ct-card-bd {
  flex: 1;
  color: var(--ct-text-secondary);
  line-height: var(--ct-leading-normal);
}

.ct-card-ft {
  padding: var(--ct-space-md) 0;
  border-top: 1px solid var(--ct-border-color);
  margin-top: var(--ct-space-md);
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
}

._actions {
  margin-left: auto;
  display: inline-flex;
  gap: var(--ct-space-sm);
}
</style>
