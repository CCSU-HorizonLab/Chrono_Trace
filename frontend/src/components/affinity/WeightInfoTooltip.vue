<template>
  <div class="weight-info-tooltip">
    <button class="info-button" @click="showTooltip = !showTooltip" title="查看权重说明">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4M12 8h.01" />
      </svg>
    </button>

    <Transition name="tooltip-fade">
      <div v-if="showTooltip" class="tooltip-panel" @click.stop>
        <div class="tooltip-header">
          <h4>维度权重说明</h4>
          <button class="close-btn" @click="showTooltip = false">×</button>
        </div>

        <div class="tooltip-content">
          <div class="weight-section active">
            <div class="section-title">
              <span class="status-icon">📊</span>
              维度权重分配
            </div>
            <ul class="weight-list">
              <li v-for="item in currentWeights" :key="item.name">
                <span class="dimension-name">{{ item.name }}</span>
                <span class="dimension-weight" :style="{ color: item.color }">{{ item.weight }}</span>
              </li>
            </ul>
          </div>

          <div class="tooltip-footer">
            <p>喜好兼容度为额外加分项，配置喜好关键词后可获得额外好感度加分，不会压缩前三个维度的权重。</p>
          </div>
        </div>
      </div>
    </Transition>

    <div v-if="showTooltip" class="tooltip-backdrop" @click="showTooltip = false"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  hasPreferenceKeywords: boolean
}>()

const showTooltip = ref(false)

const currentWeights = computed(() => {
  const base = [
    { name: '情感共振率', weight: '40%', color: '#3b82f6' },
    { name: '聊天积极度', weight: '35%', color: '#3b82f6' },
    { name: '态度倾向', weight: '25%', color: '#10b981' },
  ]

  if (props.hasPreferenceKeywords) {
    base.push({ name: '喜好兼容度', weight: '额外加分', color: '#f59e0b' })
  }

  return base
})
</script>

<style scoped>
.weight-info-tooltip {
  position: relative;
  display: inline-block;
}

.info-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-full);
  color: var(--ct-text-secondary);
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}

.info-button:hover {
  background: var(--ct-color-primary-muted);
  color: var(--ct-color-primary);
  transform: scale(1.1);
}

.tooltip-backdrop {
  position: fixed;
  inset: 0;
  background: transparent;
  z-index: 999;
}

.tooltip-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 320px;
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-lg);
  z-index: 1000;
  overflow: hidden;
}

.tooltip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--ct-space-md);
  border-bottom: 1px solid var(--ct-border-color);
  background: var(--ct-bg-secondary);
}

.tooltip-header h4 {
  margin: 0;
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-text-primary);
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: var(--ct-text-secondary);
  cursor: pointer;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--ct-radius-sm);
  transition: all var(--ct-transition-fast);
}

.close-btn:hover {
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-primary);
}

.tooltip-content {
  padding: var(--ct-space-md);
  max-height: 400px;
  overflow-y: auto;
}

.weight-section {
  margin-bottom: var(--ct-space-md);
  padding: var(--ct-space-sm);
  border-radius: var(--ct-radius-md);
  border: 2px solid transparent;
}

.weight-section.active {
  background: var(--ct-color-primary-muted);
  border-color: var(--ct-color-primary);
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
  font-size: var(--ct-text-xs);
  font-weight: 600;
  color: var(--ct-text-secondary);
  margin-bottom: var(--ct-space-sm);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.weight-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.weight-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--ct-space-xs) 0;
  font-size: var(--ct-text-sm);
}

.dimension-name {
  color: var(--ct-text-primary);
}

.dimension-weight {
  font-weight: 600;
  font-family: var(--ct-font-display);
  color: var(--ct-text-secondary);
}

.tooltip-footer {
  padding-top: var(--ct-space-sm);
  border-top: 1px solid var(--ct-border-color);
  margin-top: var(--ct-space-sm);
}

.tooltip-footer p {
  margin: 0;
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
  line-height: var(--ct-leading-relaxed);
}

.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
