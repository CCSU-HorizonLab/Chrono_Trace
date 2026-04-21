<template>
  <CtCard class="persona-panel topic-universe-card">
    <template #header>
      <span>话题星系图</span>
    </template>

    <div v-if="layout.nodes.length" ref="universeRef" class="topic-universe">
      <div v-if="layout.tracks.length" class="universe-tracks">
        <div 
          v-for="(radius, idx) in layout.tracks" 
          :key="idx"
          class="orbit-track"
          :style="{ '--track-radius': `${radius}px` }"
        ></div>
      </div>

      <div
        v-for="topic in layout.nodes"
        :key="topic.key"
        class="topic-node"
        :class="{ 'center-node': topic.isCenter, 'satellite-node': !topic.isCenter }"
        :style="topic.style"
      >
        <div class="topic-bubble">
          <strong>{{ topic.label }}</strong>
          <span v-if="topic.hint">{{ topic.hint }}</span>
        </div>
      </div>
    </div>

    <div v-else class="persona-empty-mini">暂无可展示的话题</div>
  </CtCard>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { CSSProperties, PropType } from 'vue'
import CtCard from '@/components/base/CtCard.vue'

type TopicBubble = {
  label: string
  hint: string
  size: number
  hue: string
}

type TopicLayout = {
  key: string
  label: string
  hint: string
  isCenter: boolean
  style: CSSProperties
}

const props = defineProps({
  topics: {
    type: Array as PropType<TopicBubble[]>,
    default: () => []
  }
})

const universeRef = ref<HTMLElement | null>(null)
const universeWidth = ref(0)
const universeHeight = ref(0)

let resizeObserver: ResizeObserver | null = null

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function updateBounds() {
  if (!universeRef.value) return
  const rect = universeRef.value.getBoundingClientRect()
  universeWidth.value = rect.width
  universeHeight.value = rect.height
}

onMounted(() => {
  updateBounds()
  if (typeof ResizeObserver !== 'undefined' && universeRef.value) {
    resizeObserver = new ResizeObserver(() => updateBounds())
    resizeObserver.observe(universeRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})

const layout = computed(() => {
  const topics = props.topics.slice(0, 6)
  if (!topics.length) {
    return { nodes: [] as TopicLayout[], tracks: [] as number[] }
  }

  const containerWidth = universeWidth.value || 520
  const containerHeight = universeHeight.value || 360
  
  const minDimension = Math.min(containerWidth, containerHeight)
  const isMobile = minDimension < 300

  const centerTopic = topics[0]
  const orbitTopics = topics.slice(1)

  const centerMin = isMobile ? 80 : 96
  const centerMax = Math.min(130, minDimension * 0.38)
  const centerSize = clamp(centerTopic.size, centerMin, centerMax)

  const satMin = isMobile ? 60 : 70
  const satMax = Math.min(96, minDimension * 0.24)
  const orbitSizes = orbitTopics.map(t => clamp(t.size * 0.7, satMin, satMax))

  const maxSatSize = orbitSizes.length > 0 ? Math.max(...orbitSizes) : 0
  
  const requiredR = centerSize / 2 + maxSatSize / 2 + 16
  const availableR = minDimension / 2 - maxSatSize / 2 - 12
  
  let scale = 1
  if (requiredR > availableR && availableR > 0) {
    scale = availableR / requiredR
  }
  
  const finalCenterSize = clamp(centerSize * scale, 64, 160)
  const finalSatSizes = orbitSizes.map(s => clamp(s * scale, 50, 120))
  const finalMaxSatSize = finalSatSizes.length > 0 ? Math.max(...finalSatSizes) : 0
  
  const comfortableR = finalCenterSize / 2 + finalMaxSatSize / 2 + Math.min(48, minDimension * 0.1) * scale
  let finalOrbitRadius = Math.min(comfortableR, availableR)
  finalOrbitRadius = Math.max(finalOrbitRadius, finalCenterSize / 2 + finalMaxSatSize / 2 + 8)

  const nodes: TopicLayout[] = []
  const tracks: number[] = []

  nodes.push({
    key: `topic-${centerTopic.label}-center`,
    label: centerTopic.label,
    hint: centerTopic.hint,
    isCenter: true,
    style: {
      '--topic-size': `${Math.round(finalCenterSize)}px`,
      '--topic-hue': centerTopic.hue
    } as CSSProperties
  })

  if (orbitTopics.length > 0) {
    tracks.push(Math.round(finalOrbitRadius))
    const angleStep = 360 / orbitTopics.length
    const startOffset = -90 
    
    orbitTopics.forEach((topic, index) => {
      const size = finalSatSizes[index]
      const angle = startOffset + index * angleStep
      
      nodes.push({
        key: `topic-${topic.label}-${index}`,
        label: topic.label,
        hint: topic.hint,
        isCenter: false,
        style: {
          '--topic-size': `${Math.round(size)}px`,
          '--topic-hue': topic.hue,
          '--orbit-radius': `${Math.round(finalOrbitRadius)}px`,
          '--start-angle': `${angle}deg`
        } as CSSProperties
      })
    })
  }

  return { nodes, tracks }
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
  background: 
    linear-gradient(135deg, rgba(255, 255, 255, 0.4) 0%, transparent 100%),
    radial-gradient(circle at center, rgba(0, 0, 0, 0.015), transparent 75%);
  border-radius: var(--ct-radius-xl);
  overflow: hidden;
}

.universe-tracks {
  position: absolute;
  inset: 0;
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
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.topic-node {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
}

.center-node {
  z-index: 10;
  animation: center-breath 5s ease-in-out infinite alternate;
}

.satellite-node {
  z-index: 5;
  animation: orbit-motion 45s linear infinite;
}

.topic-universe:hover .satellite-node {
  animation-play-state: paused;
}

@keyframes orbit-motion {
  0% { transform: rotate(var(--start-angle)) translateX(var(--orbit-radius)) rotate(calc(-1 * var(--start-angle))); }
  100% { transform: rotate(calc(var(--start-angle) + 360deg)) translateX(var(--orbit-radius)) rotate(calc(-1 * (var(--start-angle) + 360deg))); }
}

@keyframes center-breath {
  0% { transform: scale(1); }
  100% { transform: scale(1.02); }
}

.topic-bubble {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: var(--topic-size);
  height: var(--topic-size);
  border-radius: 50%;
  padding: 10px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 4px;
  text-align: center;
  box-sizing: border-box;
  background: color-mix(in srgb, var(--topic-hue) 4%, rgba(255, 255, 255, 0.95));
  backdrop-filter: blur(12px);
  border: 1px solid color-mix(in srgb, var(--topic-hue) 12%, rgba(0, 0, 0, 0.04));
  box-shadow: 
    0 4px 16px -4px color-mix(in srgb, var(--topic-hue) 10%, rgba(0, 0, 0, 0.04)),
    inset 0 0 8px color-mix(in srgb, var(--topic-hue) 6%, transparent);
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s ease;
  overflow: hidden;
  cursor: default;
}

.center-node .topic-bubble {
  background: #ffffff;
  border: 1px solid color-mix(in srgb, var(--topic-hue) 20%, rgba(0, 0, 0, 0.05));
  box-shadow: 
    0 10px 32px -4px color-mix(in srgb, var(--topic-hue) 20%, rgba(0, 0, 0, 0.06)),
    inset 0 0 20px color-mix(in srgb, var(--topic-hue) 5%, transparent);
}

.satellite-node .topic-bubble:hover {
  transform: translate(-50%, -50%) scale(1.06);
  box-shadow: 0 8px 24px -2px color-mix(in srgb, var(--topic-hue) 25%, rgba(0, 0, 0, 0.1));
  background: #ffffff;
  z-index: 20;
}

.topic-bubble strong {
  font-size: clamp(11px, calc(var(--topic-size) * 0.15), 15px);
  font-weight: 600;
  line-height: 1.15;
  overflow-wrap: break-word;
  word-wrap: break-word;
  word-break: break-word;
  hyphens: auto;
  color: color-mix(in srgb, var(--topic-hue) 80%, #2a2a2a);
}

.topic-bubble span {
  font-size: clamp(10px, calc(var(--topic-size) * 0.11), 12px);
  line-height: 1.25;
  color: color-mix(in srgb, var(--topic-hue) 60%, #666);
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
  .topic-universe-card {
    min-height: 380px;
  }

  .topic-universe {
    min-height: 300px;
  }
}
</style>
