<template>
  <div class="ct-avatar" :style="avatarStyle">
    <img v-if="showImage" :src="normalizedSrc" :alt="altText" @error="handleError" />
    <span v-else>{{ initial }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getAvatarInitial, normalizeAvatarSrc, shouldRenderAvatar } from '@/utils/avatar.js'

const props = withDefaults(defineProps<{
  src?: string | null
  name?: string | null
  alt?: string
  size?: number | string
  radius?: string
}>(), {
  src: '',
  name: '',
  alt: '',
  size: 40,
  radius: '50%',
})

const errored = ref(false)

watch(() => props.src, () => {
  errored.value = false
})

const normalizedSrc = computed(() => normalizeAvatarSrc(props.src))
const showImage = computed(() => shouldRenderAvatar(normalizedSrc.value, errored.value))
const initial = computed(() => getAvatarInitial(props.name))
const altText = computed(() => props.alt || `${(props.name ?? '').trim() || 'avatar'} avatar`)
const avatarStyle = computed(() => {
  const size = typeof props.size === 'number' ? `${props.size}px` : props.size
  return {
    width: size,
    height: size,
    borderRadius: props.radius,
  }
})

function handleError() {
  errored.value = true
}
</script>

<style scoped>
.ct-avatar {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  vertical-align: middle;
  background: linear-gradient(135deg, var(--ct-color-primary-light), var(--ct-color-primary-muted));
  color: var(--ct-color-primary);
  font-weight: 700;
  border: 1px solid var(--ct-color-primary-subtle);
  box-sizing: border-box;
}

.ct-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.ct-avatar span {
  line-height: 1;
  font-size: 0.9rem;
}
</style>
