<template>
  <CtCard class="persona-panel topic-universe-card">
    <template #header>
      <span>话题星系图</span>
    </template>

    <div v-if="topics.length" class="topic-universe">
      <!-- Background subtle orbit tracks -->
      <div v-if="topics.length > 1" class="universe-tracks">
        <div v-for="n in (topics.length - 1)" :key="`track-${n}`" class="orbit-track" :style="{ '--track-radius': `calc(90px + ${n} * 40px)` }"></div>
      </div>

      <div
        v-for="(topic, index) in topics"
        :key="topic.label"
        class="topic-orbit"
        :class="{ 'center-node': index === 0, 'orbit-node': index > 0 }"
        :style="{
          '--topic-size': `${topic.size}px`,
          '--topic-hue': topic.hue,
          '--orbit-index': index,
          '--total-orbits': topics.length - 1
        }"
      >
        <div class="topic-bubble">
          <strong>{{ topic.label }}</strong>
          <span>{{ topic.hint }}</span>
        </div>
      </div>
    </div>

    <div v-else class="persona-empty-mini">暂无可展示的话题轨迹</div>
  </CtCard>
</template>

<script setup lang="ts">
import type { PropType } from 'vue'
import CtCard from '@/components/base/CtCard.vue'

type TopicBubble = {
  label: string
  hint: string
  size: number
  hue: string
}

defineProps({
  topics: {
    type: Array as PropType<TopicBubble[]>,
    default: () => []
  }
})
</script>

<style scoped>
.topic-universe-card {
  min-height: 420px;
}

.topic-universe {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360px;
  overflow: hidden;
  border-radius: var(--ct-radius-xl);
  background: radial-gradient(circle at center, rgba(139, 92, 246, 0.03), transparent 70%);
}

.universe-tracks {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.orbit-track {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: calc(var(--track-radius) * 2);
  height: calc(var(--track-radius) * 2);
  border-radius: 50%;
  border: 1px dashed var(--ct-border-subtle);
  opacity: 0.6;
}

.topic-orbit.center-node {
  position: relative;
  z-index: 10;
}
.topic-orbit.center-node .topic-bubble {
  box-shadow: 0 0 30px color-mix(in srgb, var(--topic-hue) 30%, transparent);
  border: 1.5px solid color-mix(in srgb, var(--topic-hue) 40%, transparent);
  animation: pulse-glow-flat 4s infinite alternate ease-in-out;
}

@keyframes pulse-glow-flat {
  0% { transform: scale(1); box-shadow: 0 0 20px color-mix(in srgb, var(--topic-hue) 20%, transparent); }
  100% { transform: scale(1.05); box-shadow: 0 0 40px color-mix(in srgb, var(--topic-hue) 40%, transparent); }
}

.topic-orbit.orbit-node {
  position: absolute;
  top: 50%;
  left: 50%;
  z-index: 2;
  /* Make orbit nodes significantly smaller */
  --effective-size: calc(var(--topic-size) * 0.65);
  
  /* Adjust radius: 90px for first orbit, increasing by 40px each */
  --orbit-radius: calc(90px + var(--orbit-index) * 40px);
  --orbit-duration: calc(18s + var(--orbit-index) * 12s);
  --start-angle: calc((360deg / var(--total-orbits)) * var(--orbit-index));
  
  width: 0;
  height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  
  /* Apply animation delay to distribute them */
  animation: orbit var(--orbit-duration) linear infinite;
  animation-delay: calc(-1 * var(--orbit-duration) * (var(--orbit-index) / var(--total-orbits)));
}

@keyframes orbit {
  from { transform: rotate(0deg) translateX(var(--orbit-radius)) rotate(0deg); }
  to { transform: rotate(360deg) translateX(var(--orbit-radius)) rotate(-360deg); }
}

/* Pause animations on hover so users can easily read them */
.topic-universe:hover .topic-orbit.orbit-node {
  animation-play-state: paused;
}

.topic-bubble {
  width: var(--effective-size, var(--topic-size));
  height: var(--effective-size, var(--topic-size));
  border-radius: 50%;
  padding: 8px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 2px;
  text-align: center;
  box-sizing: border-box;
  flex-shrink: 0;
  overflow: hidden;

  /* Flat, Light and Clean Aesthetic */
  background: color-mix(in srgb, var(--topic-hue) 12%, #ffffff);
  border: 1px solid color-mix(in srgb, var(--topic-hue) 30%, transparent);
  box-shadow: 0 4px 12px color-mix(in srgb, var(--topic-hue) 15%, rgba(0,0,0,0.05));
  
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s ease;
  cursor: default;
}

.topic-orbit.orbit-node .topic-bubble:hover {
  transform: scale(1.15);
  box-shadow: 0 10px 24px color-mix(in srgb, var(--topic-hue) 30%, transparent);
  z-index: 20;
}

.topic-bubble strong {
  font-size: clamp(10px, calc(var(--effective-size, var(--topic-size)) * 0.15), 15px);
  font-weight: 600;
  line-height: 1.1;
  word-break: break-word;
  white-space: normal;
  color: color-mix(in srgb, var(--topic-hue) 90%, #222); /* Darkened hue for readability */
}

.topic-bubble span {
  font-size: max(8px, calc(var(--effective-size, var(--topic-size)) * 0.09));
  line-height: 1.2;
  color: color-mix(in srgb, var(--topic-hue) 70%, #666);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.persona-empty-mini {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-sm);
}

@media (max-width: 768px) {
  .topic-universe {
    min-height: 300px;
    transform: scale(0.85);
  }
}
</style>
