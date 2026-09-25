<template>
  <span
    ref="triggerRef"
    class="ct-help-trigger"
    tabindex="0"
    @mouseenter="show"
    @mouseleave="hide"
    @focus="show"
    @blur="hide"
  >
    <svg
      viewBox="0 0 24 24"
      :width="size"
      :height="size"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>

    <Teleport to="body">
      <div
        v-if="visible"
        ref="tipRef"
        class="ct-help-floating-tip"
        :class="[placement]"
        :style="{
          top: `${coords.top}px`,
          left: `${coords.left}px`,
          width: `${width}px`,
          '--arrow-left': `${coords.arrowLeft}px`,
        }"
      >
        <slot>{{ content }}</slot>
      </div>
    </Teleport>
  </span>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, reactive, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    content?: string
    width?: number
    size?: number
  }>(),
  {
    content: '',
    width: 268,
    size: 14,
  },
)

const triggerRef = ref<HTMLElement | null>(null)
const tipRef = ref<HTMLElement | null>(null)
const visible = ref(false)
const placement = ref<'top' | 'bottom'>('top')
const coords = reactive({
  top: 0,
  left: 0,
  arrowLeft: 20,
})

function updatePosition() {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const tipW = props.width
  const tipH = tipRef.value?.offsetHeight || 96
  const margin = 12
  const gap = 8

  const triggerCenterX = rect.left + rect.width / 2
  // 水平方向居中，并严格限制在视口左右安全边距内，绝不超出右边界或左边界
  let left = triggerCenterX - tipW / 2
  if (left + tipW > vw - margin) {
    left = vw - margin - tipW
  }
  if (left < margin) {
    left = margin
  }

  // 计算小三角箭头对准触发图标中心的位置
  const arrowLeft = Math.max(14, Math.min(tipW - 14, triggerCenterX - left))

  // 垂直方向优先向上弹出；如果顶部空间不足则自动向下翻转
  let top = rect.top - tipH - gap
  if (top < margin && rect.bottom + tipH + gap < vh) {
    placement.value = 'bottom'
    top = rect.bottom + gap
  } else {
    placement.value = 'top'
  }

  coords.left = Math.round(left)
  coords.top = Math.round(top)
  coords.arrowLeft = Math.round(arrowLeft)
}

async function show() {
  visible.value = true
  updatePosition()
  await nextTick()
  updatePosition()
  window.addEventListener('scroll', hide, true)
  window.addEventListener('resize', hide)
}

function hide() {
  visible.value = false
  window.removeEventListener('scroll', hide, true)
  window.removeEventListener('resize', hide)
}

onBeforeUnmount(() => {
  hide()
})
</script>

<style scoped>
.ct-help-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--ct-text-muted, #94a3b8);
  cursor: help;
  transition: color 0.18s ease, background 0.18s ease;
  outline: none;
  flex-shrink: 0;
  vertical-align: middle;
}

.ct-help-trigger:hover,
.ct-help-trigger:focus {
  color: var(--ct-color-primary, #7c4dff);
  background: rgba(124, 77, 255, 0.12);
}

.ct-help-floating-tip {
  position: fixed;
  z-index: 99999;
  padding: 10px 13px;
  border-radius: 10px;
  background: #1e293b;
  color: #f8fafc;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
  word-break: break-word;
  box-shadow:
    0 12px 28px rgba(15, 23, 42, 0.32),
    0 0 0 1px rgba(255, 255, 255, 0.08);
  pointer-events: none;
  animation: ct-tip-fade 0.15s ease-out;
}

.ct-help-floating-tip :deep(strong) {
  color: #ffffff;
  font-weight: 600;
}

.ct-help-floating-tip::after {
  content: '';
  position: absolute;
  left: var(--arrow-left, 20px);
  transform: translateX(-50%);
  border: 5px solid transparent;
}

.ct-help-floating-tip.top::after {
  top: 100%;
  border-top-color: #1e293b;
}

.ct-help-floating-tip.bottom::after {
  bottom: 100%;
  border-bottom-color: #1e293b;
}

@keyframes ct-tip-fade {
  from {
    opacity: 0;
    transform: translateY(3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
