<template>
  <transition name="ct-dialog-fade">
    <div v-if="visible" class="ct-dialog-overlay" @click.self="handleWrapperClick">
      <div class="ct-dialog">
        <header v-if="title" class="ct-dialog-header">
          <h3 class="ct-dialog-title">{{ title }}</h3>
        </header>
        <div class="ct-dialog-body">
          <slot>{{ message }}</slot>
        </div>
        <footer class="ct-dialog-footer">
          <CtButton v-if="showCancel" variant="secondary" @click="handleCancel" class="cancel-btn">取消</CtButton>
          <CtButton variant="primary" @click="handleConfirm">确定</CtButton>
        </footer>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import CtButton from './CtButton.vue';

const props = defineProps<{
  title?: string;
  message?: string;
  showCancel?: boolean;
}>();
const emit = defineEmits<{
  (e: 'confirm'): void;
  (e: 'cancel'): void;
}>();

const visible = ref(false);

const open = () => {
  visible.value = true;
};

const handleConfirm = () => {
  visible.value = false;
  emit('confirm');
};

const handleCancel = () => {
  visible.value = false;
  emit('cancel');
};

const handleWrapperClick = () => {
  if (props.showCancel) {
    handleCancel();
  } else {
    handleConfirm();
  }
};

defineExpose({
  open,
  close: () => { visible.value = false; }
});
</script>

<style scoped>
.ct-dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 99999;
}

.ct-dialog {
  background: var(--ct-bg-elevated, #ffffff);
  border: 1px solid var(--ct-border-color, #e2e8f0);
  border-radius: var(--ct-radius-lg, 8px);
  box-shadow: var(--ct-shadow-lg, 0 10px 15px -3px rgba(0, 0, 0, 0.1));
  width: 90%;
  max-width: 400px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--ct-text-primary, #1a202c);
  animation: ct-dialog-zoom 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.ct-dialog-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--ct-border-color, #e2e8f0);
}

.ct-dialog-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ct-text-primary, #1a202c);
}

.ct-dialog-body {
  padding: 20px;
  font-size: 14px;
  color: var(--ct-text-secondary, #4a5568);
  overflow-y: auto;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.ct-dialog-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--ct-border-color, #e2e8f0);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.ct-dialog-fade-enter-active,
.ct-dialog-fade-leave-active {
  transition: opacity 0.2s ease;
}

.ct-dialog-fade-enter-from,
.ct-dialog-fade-leave-to {
  opacity: 0;
}

@keyframes ct-dialog-zoom {
  0% {
    transform: scale(0.95);
    opacity: 0;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
