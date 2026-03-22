<template>
  <article class="milestone-frame" :style="{ '--frame-accent': accent }">
    <div class="milestone-date">{{ dateLabel }}</div>
    <h4>{{ title }}</h4>
    <p>{{ body }}</p>
  </article>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  dateLabel: string
  body: string
  accent?: string
}>(), {
  accent: '#fb7185'
})
</script>

<style scoped>
.milestone-frame {
  position: relative;
  padding: 18px;
  min-height: 176px;
  border-radius: 22px;
  overflow: hidden;
  background:
    linear-gradient(145deg, rgba(255, 252, 245, 0.98), rgba(255, 247, 237, 0.94)),
    linear-gradient(180deg, rgba(255, 255, 255, 0.4), transparent);
  border: 1px solid rgba(251, 191, 36, 0.22);
  box-shadow: 0 18px 36px rgba(146, 64, 14, 0.12);
}

.milestone-frame::before {
  content: '';
  position: absolute;
  inset: 10px;
  border: 1px solid color-mix(in srgb, var(--frame-accent) 30%, white 40%);
  border-radius: 16px;
  pointer-events: none;
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
</style>
