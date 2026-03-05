<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="modelValue" class="dialog-overlay" @click="handleClose">
        <div class="dialog-container" @click.stop>
          <div class="dialog-header">
            <h3>📋 填写关系信息</h3>
            <button class="close-btn" @click="handleClose">×</button>
          </div>
          
          <div class="dialog-body">
            <p class="dialog-desc">
              请简单描述你与对方的关系，这些信息将帮助系统更准确地理解聊天数据。
            </p>

            <!-- 关系类型 -->
            <div class="form-group">
              <label class="form-label">我与对方的关系</label>
              <div class="radio-group">
                <label
                  v-for="opt in options.relationship_types"
                  :key="opt.value"
                  class="radio-card"
                  :class="{ active: form.relationship_type === opt.value }"
                >
                  <input
                    type="radio"
                    :value="opt.value"
                    v-model="form.relationship_type"
                    class="sr-only"
                  />
                  <span class="radio-icon">{{ getIcon('relationship', opt.value) }}</span>
                  <span class="radio-label">{{ opt.label }}</span>
                </label>
              </div>
            </div>

            <!-- 互动时长 -->
            <div class="form-group">
              <label class="form-label">互动时长</label>
              <div class="radio-group">
                <label
                  v-for="opt in options.interaction_durations"
                  :key="opt.value"
                  class="radio-card"
                  :class="{ active: form.interaction_duration === opt.value }"
                >
                  <input
                    type="radio"
                    :value="opt.value"
                    v-model="form.interaction_duration"
                    class="sr-only"
                  />
                  <span class="radio-icon">{{ getIcon('duration', opt.value) }}</span>
                  <span class="radio-label">{{ opt.label }}</span>
                </label>
              </div>
            </div>

            <!-- 沟通风格 -->
            <div class="form-group">
              <label class="form-label">对方的沟通风格</label>
              <div class="radio-group radio-group-3">
                <label
                  v-for="opt in options.communication_styles"
                  :key="opt.value"
                  class="radio-card"
                  :class="{ active: form.communication_style === opt.value }"
                >
                  <input
                    type="radio"
                    :value="opt.value"
                    v-model="form.communication_style"
                    class="sr-only"
                  />
                  <span class="radio-icon">{{ getIcon('style', opt.value) }}</span>
                  <span class="radio-label">{{ opt.label }}</span>
                </label>
              </div>
            </div>

            <div class="hint-box">
              <p>💡 这些信息仅用于调整分析参数的基线，不会影响原始数据。</p>
            </div>
          </div>
          
          <div class="dialog-footer">
            <button class="btn btn-secondary" @click="handleClose">取消</button>
            <button class="btn btn-primary" @click="handleSave" :disabled="isSaving">
              {{ isSaving ? '保存中...' : '确认并开始分析' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import {
  getRelationshipContext,
  saveRelationshipContext,
  getRelationshipFieldOptions,
  type FieldOptions
} from '../../api/affinity'

const props = defineProps<{
  modelValue: boolean
  conversationId: number
}>()

const emit = defineEmits(['update:modelValue', 'saved'])

const isSaving = ref(false)

const form = reactive({
  relationship_type: 'friend',
  interaction_duration: '1_to_6_months',
  communication_style: 'normal',
})

// 默认选项（硬编码兜底，防止API失败时无法显示）
const options = ref<FieldOptions>({
  relationship_types: [
    { value: 'lover', label: '恋人' },
    { value: 'crush', label: '暧昧对象' },
    { value: 'friend', label: '朋友' },
    { value: 'colleague', label: '同事' },
    { value: 'family', label: '家人' },
    { value: 'other', label: '其他' },
  ],
  interaction_durations: [
    { value: 'less_1_month', label: '不到1个月' },
    { value: '1_to_6_months', label: '1-6个月' },
    { value: '6_to_12_months', label: '6-12个月' },
    { value: 'over_1_year', label: '1年以上' },
  ],
  communication_styles: [
    { value: 'talkative', label: '话多热情' },
    { value: 'normal', label: '正常' },
    { value: 'reserved', label: '话少内敛' },
  ],
})

// 图标映射
function getIcon(type: string, value: string): string {
  const icons: Record<string, Record<string, string>> = {
    relationship: {
      lover: '❤️', crush: '💕', friend: '🤝',
      colleague: '💼', family: '👨‍👩‍👧', other: '🔗',
    },
    duration: {
      less_1_month: '🌱', '1_to_6_months': '🌿',
      '6_to_12_months': '🌳', over_1_year: '🏔️',
    },
    style: {
      talkative: '🗣️', normal: '💬', reserved: '🤫',
    },
  }
  return icons[type]?.[value] || '📌'
}

// 弹窗打开时加载数据
watch(() => props.modelValue, async (show) => {
  if (show && props.conversationId) {
    try {
      // 尝试加载字段选项
      const opts = await getRelationshipFieldOptions()
      options.value = opts
    } catch (e) {
      console.warn('使用默认字段选项', e)
    }
    
    try {
      // 尝试加载已有上下文
      const { context } = await getRelationshipContext(props.conversationId)
      if (context) {
        form.relationship_type = context.relationship_type
        form.interaction_duration = context.interaction_duration
        form.communication_style = context.communication_style
      }
    } catch (e) {
      console.warn('加载关系上下文失败', e)
    }
  }
}, { immediate: true })

const handleSave = async () => {
  isSaving.value = true
  try {
    await saveRelationshipContext(props.conversationId, {
      relationship_type: form.relationship_type,
      interaction_duration: form.interaction_duration,
      communication_style: form.communication_style,
    })
    emit('saved')
    emit('update:modelValue', false)
  } catch (e) {
    console.error('保存关系上下文失败', e)
    alert('保存失败: ' + (e instanceof Error ? e.message : String(e)))
  } finally {
    isSaving.value = false
  }
}

const handleClose = () => {
  emit('update:modelValue', false)
}
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: var(--ct-space-lg);
}

.dialog-container {
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-xl);
  width: 100%;
  max-width: 520px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--ct-space-lg);
  border-bottom: 1px solid var(--ct-border-color);
}

.dialog-header h3 {
  margin: 0;
  font-size: var(--ct-text-lg);
  font-weight: 600;
  color: var(--ct-text-primary);
}

.close-btn {
  background: none;
  border: none;
  font-size: 2rem;
  color: var(--ct-text-secondary);
  cursor: pointer;
  padding: 0;
  width: 32px; height: 32px;
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

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--ct-space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-lg);
}

.dialog-desc {
  margin: 0;
  font-size: var(--ct-text-sm);
  color: var(--ct-text-secondary);
  line-height: var(--ct-leading-relaxed);
}

/* 表单组 */
.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.form-label {
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-text-primary);
}

/* 单选卡片组 */
.radio-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--ct-space-xs);
}

.radio-group-3 {
  grid-template-columns: repeat(3, 1fr);
}

.sr-only {
  position: absolute;
  width: 1px; height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.radio-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 6px;
  border: 1.5px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  cursor: pointer;
  transition: all var(--ct-transition-fast);
  background: var(--ct-bg-elevated);
  text-align: center;
}

.radio-card:hover {
  border-color: var(--ct-color-primary);
  background: var(--ct-color-primary-muted);
}

.radio-card.active {
  border-color: var(--ct-color-primary);
  background: var(--ct-color-primary-muted);
  box-shadow: 0 0 0 1px var(--ct-color-primary);
}

.radio-icon {
  font-size: 1.3rem;
  line-height: 1;
}

.radio-label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-primary);
  font-weight: 500;
  line-height: 1.2;
}

/* 提示框 */
.hint-box {
  background: var(--ct-color-info-muted);
  border-left: 3px solid var(--ct-color-info);
  border-radius: var(--ct-radius-sm);
  padding: var(--ct-space-sm) var(--ct-space-md);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.hint-box p {
  margin: 0;
  line-height: var(--ct-leading-relaxed);
}

/* 底部按钮 */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--ct-space-sm);
  padding: var(--ct-space-lg);
  border-top: 1px solid var(--ct-border-color);
}

.btn {
  padding: var(--ct-space-sm) var(--ct-space-lg);
  border: none;
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--ct-transition-fast);
}

.btn-secondary {
  background: var(--ct-bg-tertiary);
  color: var(--ct-text-primary);
}

.btn-secondary:hover {
  background: var(--ct-bg-secondary);
}

.btn-primary {
  background: var(--ct-color-primary);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--ct-color-primary-hover);
  transform: translateY(-1px);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 动画 */
.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity 0.3s ease;
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}

.dialog-fade-enter-active .dialog-container,
.dialog-fade-leave-active .dialog-container {
  transition: transform 0.3s ease;
}

.dialog-fade-enter-from .dialog-container,
.dialog-fade-leave-to .dialog-container {
  transform: scale(0.9);
}
</style>
