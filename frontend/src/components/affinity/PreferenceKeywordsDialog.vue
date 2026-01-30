<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="modelValue" class="dialog-overlay" @click="handleClose">
        <div class="dialog-container" @click.stop>
          <div class="dialog-header">
            <h3>配置喜好关键词</h3>
            <button class="close-btn" @click="handleClose">×</button>
          </div>
          
          <div class="dialog-body">
            <!-- 当前权重预览 -->
            <div class="weight-preview">
              <div class="preview-title">
                <span class="icon">⚖️</span>
                当前权重配置
              </div>
              <div class="weight-grid">
                <div v-for="item in currentWeights" :key="item.name" class="weight-item">
                  <span class="weight-name">{{ item.name }}</span>
                  <span class="weight-value" :style="{ color: item.color }">{{ item.weight }}</span>
                </div>
              </div>
            </div>
            
            <!-- 关键词列表 -->
            <div class="keywords-section">
              <div class="section-header">
                <label class="section-label">喜好关键词列表</label>
                <span class="keyword-count">{{ keywords.length }} 个关键词</span>
              </div>
              
              <div v-if="keywords.length > 0" class="keywords-list">
                <div v-for="(keyword, index) in keywords" :key="index" class="keyword-tag">
                  <span class="keyword-text">{{ keyword }}</span>
                  <button class="remove-btn" @click="removeKeyword(index)" title="删除">×</button>
                </div>
              </div>
              
              <div v-else class="empty-state">
                <span class="empty-icon">📝</span>
                <p>还没有添加喜好关键词</p>
                <p class="empty-hint">添加关键词后,喜好维度将参与好感度评分</p>
              </div>
            </div>
            
            <!-- 添加关键词 -->
            <div class="add-section">
              <input
                v-model="newKeyword"
                type="text"
                class="keyword-input"
                placeholder="输入关键词,如:篮球、电影、旅行..."
                @keyup.enter="addKeyword"
              />
              <button class="add-btn" @click="addKeyword" :disabled="!newKeyword.trim()">
                添加
              </button>
            </div>
            
            <!-- 提示信息 -->
            <div class="hint-box">
              <p>💡 <strong>提示:</strong></p>
              <ul>
                <li>关键词用于识别聊天中提及的共同喜好话题</li>
                <li>设置关键词后,喜好维度权重为 <strong>10%</strong></li>
                <li>未设置时,其他维度权重会自动调整</li>
              </ul>
            </div>
          </div>
          
          <div class="dialog-footer">
            <button class="btn btn-secondary" @click="handleClose">取消</button>
            <button class="btn btn-primary" @click="handleSave" :disabled="isSaving">
              {{ isSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { getPreferenceKeywords, updatePreferenceKeywords } from '../../api/affinity'

const props = defineProps<{
  modelValue: boolean
  conversationId: number
}>()

const emit = defineEmits(['update:modelValue', 'updated'])

const keywords = ref<string[]>([])
const newKeyword = ref('')
const isSaving = ref(false)

const currentWeights = computed(() => {
  const hasKeywords = keywords.value.length > 0
  if (hasKeywords) {
    return [
      { name: '情感共振率', weight: '35%', color: '#3b82f6' },
      { name: '聊天积极度', weight: '35%', color: '#3b82f6' },
      { name: '态度倾向', weight: '20%', color: '#10b981' },
      { name: '喜好维度', weight: '10%', color: '#10b981' },
    ]
  } else {
    return [
      { name: '情感共振率', weight: '40%', color: '#3b82f6' },
      { name: '聊天积极度', weight: '35%', color: '#3b82f6' },
      { name: '态度倾向', weight: '25%', color: '#10b981' },
      { name: '喜好维度', weight: '0%', color: '#9ca3af' },
    ]
  }
})

// 加载关键词
watch(() => props.modelValue, async (show) => {
  if (show) {
    try {
      keywords.value = await getPreferenceKeywords(props.conversationId)
    } catch (e) {
      console.error('Failed to load preference keywords', e)
      keywords.value = []
    }
  }
}, { immediate: true })

const addKeyword = () => {
  const keyword = newKeyword.value.trim()
  if (keyword && !keywords.value.includes(keyword)) {
    keywords.value.push(keyword)
    newKeyword.value = ''
  }
}

const removeKeyword = (index: number) => {
  keywords.value.splice(index, 1)
}

const handleSave = async () => {
  isSaving.value = true
  try {
    await updatePreferenceKeywords(props.conversationId, keywords.value)
    emit('updated')
    handleClose()
  } catch (e) {
    console.error('Failed to update preference keywords', e)
    alert('保存失败: ' + (e instanceof Error ? e.message : String(e)))
  } finally {
    isSaving.value = false
  }
}

const handleClose = () => {
  emit('update:modelValue', false)
  newKeyword.value = ''
}
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
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
  max-width: 560px;
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
  width: 32px;
  height: 32px;
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

/* 权重预览 */
.weight-preview {
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-md);
  border: 1px solid var(--ct-border-color);
}

.preview-title {
  display: flex;
  align-items: center;
  gap: var(--ct-space-xs);
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-text-secondary);
  margin-bottom: var(--ct-space-sm);
}

.icon {
  font-size: 1.2rem;
}

.weight-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ct-space-sm);
}

.weight-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--ct-space-xs);
  background: var(--ct-bg-elevated);
  border-radius: var(--ct-radius-sm);
}

.weight-name {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-primary);
}

.weight-value {
  font-size: var(--ct-text-sm);
  font-weight: 700;
  font-family: var(--ct-font-display);
}

/* 关键词部分 */
.keywords-section {
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-sm);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-label {
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-text-primary);
}

.keyword-count {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-tertiary);
}

.keywords-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-xs);
  padding: var(--ct-space-md);
  background: var(--ct-bg-secondary);
  border-radius: var(--ct-radius-md);
  min-height: 60px;
}

.keyword-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--ct-space-xs);
  padding: 6px 12px;
  background: var(--ct-color-primary);
  color: white;
  border-radius: var(--ct-radius-full);
  font-size: var(--ct-text-sm);
  font-weight: 500;
}

.keyword-text {
  line-height: 1;
}

.remove-btn {
  background: rgba(255, 255, 255, 0.2);
  border: none;
  color: white;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  line-height: 1;
  transition: background var(--ct-transition-fast);
}

.remove-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.empty-state {
  text-align: center;
  padding: var(--ct-space-xl);
  color: var(--ct-text-tertiary);
}

.empty-icon {
  font-size: 3rem;
  display: block;
  margin-bottom: var(--ct-space-sm);
  opacity: 0.5;
}

.empty-state p {
  margin: var(--ct-space-xs) 0;
  font-size: var(--ct-text-sm);
}

.empty-hint {
  font-size: var(--ct-text-xs) !important;
  color: var(--ct-text-tertiary);
}

/* 添加部分 */
.add-section {
  display: flex;
  gap: var(--ct-space-sm);
}

.keyword-input {
  flex: 1;
  padding: var(--ct-space-sm) var(--ct-space-md);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-elevated);
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
  outline: none;
  transition: border-color var(--ct-transition-fast);
}

.keyword-input:focus {
  border-color: var(--ct-color-primary);
  box-shadow: 0 0 0 2px var(--ct-color-primary-muted);
}

.add-btn {
  padding: var(--ct-space-sm) var(--ct-space-lg);
  background: var(--ct-color-primary);
  color: white;
  border: none;
  border-radius: var(--ct-radius-md);
  font-size: var(--ct-text-sm);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--ct-transition-fast);
  white-space: nowrap;
}

.add-btn:hover:not(:disabled) {
  background: var(--ct-color-primary-hover);
  transform: translateY(-1px);
}

.add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 提示框 */
.hint-box {
  background: var(--ct-color-info-muted);
  border-left: 3px solid var(--ct-color-info);
  border-radius: var(--ct-radius-sm);
  padding: var(--ct-space-md);
  font-size: var(--ct-text-xs);
  color: var(--ct-text-secondary);
}

.hint-box p {
  margin: 0 0 var(--ct-space-xs) 0;
}

.hint-box ul {
  margin: 0;
  padding-left: var(--ct-space-lg);
}

.hint-box li {
  margin: var(--ct-space-xs) 0;
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
