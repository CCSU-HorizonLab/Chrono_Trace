<template>
  <article
    class="milestone-frame"
    :class="{ clickable }"
    :style="{ '--frame-accent': accent }"
    :role="clickable ? 'button' : undefined"
    :tabindex="clickable ? 0 : undefined"
    @click="clickable && emit('open')"
    @keyup.enter="clickable && emit('open')"
  >
    <div class="milestone-date">{{ dateLabel }}</div>
    <h4>{{ title }}</h4>
    <p>{{ body }}</p>
    <span v-if="clickable" class="milestone-hint">
      <MessageCircle :size="13" style="flex-shrink: 0;" /> 点击回顾当时的对话
    </span>
  </article>
</template>

<script setup lang="ts">
import { MessageCircle } from 'lucide-vue-next'

withDefaults(defineProps<{
  title: string
  dateLabel: string
  body: string
  accent?: string
  clickable?: boolean
}>(), {
  accent: '#E8656F',
  clickable: false
})

const emit = defineEmits<{ open: [] }>()
</script>

<style scoped>
.milestone-frame {
  position: relative;
  padding: 18px;
  min-height: 176px;
  border-radius: 22px;
  overflow: hidden;
  background:
    #FBF7EE;
  border: 1px solid rgba(251, 191, 36, 0.22);
  box-shadow: 0 18px 36px rgba(146, 64, 14, 0.12);
}

.milestone-frame.clickable {
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.milestone-frame.clickable:hover,
.milestone-frame.clickable:focus-visible {
  transform: translateY(-3px);
  box-shadow: 0 22px 44px rgba(146, 64, 14, 0.2);
  outline: none;
}

.milestone-date {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  margin-bottom: 14px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--frame-accent) 10%, white);
  color: color-mix(in srgb, var(--frame-accent) 72%, black 18%);
  font-size: 11px;
  font-weight: 700;
}

.milestone-frame h4 {
  margin: 0 0 10px;
  font-size: 18px;
  line-height: 1.3;
  color: #7c2d12;
}

.milestone-frame p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #9a3412;
}

.milestone-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 12px;
  font-size: 11.5px;
  font-weight: 600;
  color: color-mix(in srgb, var(--frame-accent) 62%, #9a3412 38%);
  opacity: 0.85;
}

.milestone-frame.clickable:hover .milestone-hint {
  opacity: 1;
}
</style>
