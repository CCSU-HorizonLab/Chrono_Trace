<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="modelValue" class="dialog-overlay" @click="handleClose">
        <div class="dialog-container" @click.stop>
          <div class="dialog-header">
            <h3 style="display: flex; align-items: center; gap: 8px;">
              <ClipboardList :size="18" style="color: var(--ct-color-primary);" />
              <span>填写关系信息</span>
            </h3>
            <button class="close-btn" @click="handleClose" title="关闭"><X :size="18" /></button>
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
                  <span class="radio-icon">
                    <component :is="getIconComponent('relationship', opt.value)" :size="18" />
                  </span>
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
                  <span class="radio-icon">
                    <component :is="getIconComponent('duration', opt.value)" :size="18" />
                  </span>
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
                  <span class="radio-icon">
                    <component :is="getIconComponent('style', opt.value)" :size="18" />
                  </span>
                  <span class="radio-label">{{ opt.label }}</span>
                </label>
              </div>
            </div>

            <!-- 维度权重（点数制：不需要凑成 100，系统按在场维度自动归一） -->
            <div class="form-group">
              <label class="form-label">评分维度权重 <span class="weight-hint">（点数制，按比例折算；某维设 0 即不参与）</span></label>
              <div class="weight-rows">
                <div v-for="dim in weightDims" :key="dim.field" class="weight-row">
                  <span class="weight-name">{{ dim.label }}</span>
                  <input
                    type="number" min="0" max="100" step="1"
                    class="weight-input"
                    v-model.number="weightForm[dim.field]"
                  />
                  <span class="weight-pct">{{ weightPercent(dim.field) }}</span>
                </div>
                <label class="weight-llm-toggle">
                  <input type="checkbox" v-model="weightForm.llm_relationship_enabled" />
                  启用 AI 关系评估维度（需先在设置中配置 LLM 模型）
                </label>
              </div>
            </div>

            <div class="hint-box">
              <p style="display: flex; align-items: center; gap: 6px;">
                <Lightbulb :size="14" style="color: var(--ct-color-info); flex-shrink: 0;" />
                <span>这些信息仅用于调整分析参数的基线，不会影响原始数据。</span>
              </p>
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
import { ref, reactive, watch, computed } from 'vue'
import {
  ClipboardList,
  Heart,
  Sparkles,
  Users,
  Briefcase,
  Home,
  Link2,
  Sprout,
  Calendar,
  CalendarDays,
  History,
  MessageCircle,
  MessageSquare,
  VolumeX,
  Lightbulb,
  X
} from 'lucide-vue-next'
import {
  getRelationshipContext,
  saveRelationshipContext,
  getRelationshipFieldOptions,
  getAffinityConfig,
  updateAffinityConfig,
  type FieldOptions
} from '../../api/affinity'
import { showDialog } from '../../utils/dialog'

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

// 六维权重（0-100 点数制；保存为 0-1 的小数权重）
const weightDims = [
  { field: 'weight_emotional_resonance', label: '情感共振率', default: 40 },
  { field: 'weight_chat_positivity', label: '聊天积极度', default: 35 },
  { field: 'weight_attitude_tendency', label: '态度倾向', default: 25 },
  { field: 'weight_preference_compatibility', label: '喜好兼容度', default: 10 },
  { field: 'weight_intimacy_signals', label: '亲密度信号', default: 12 },
  { field: 'weight_llm_relationship', label: 'AI 关系评估', default: 8 },
] as const

const weightForm = reactive({
  weight_emotional_resonance: 40,
  weight_chat_positivity: 35,
  weight_attitude_tendency: 25,
  weight_preference_compatibility: 10,
  weight_intimacy_signals: 12,
  weight_llm_relationship: 8,
  llm_relationship_enabled: true,
})

const weightTotal = computed(() =>
  weightDims.reduce((sum, d) => sum + Math.max(0, Number(weightForm[d.field]) || 0), 0)
)

function weightPercent(field: string): string {
  const value = Math.max(0, Number((weightForm as any)[field]) || 0)
  if (weightTotal.value <= 0) return '—'
  return `${(value / weightTotal.value * 100).toFixed(0)}%`
}

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

const relationshipIcons: Record<string, any> = {
  lover: Heart,
  crush: Sparkles,
  friend: Users,
  colleague: Briefcase,
  family: Home,
  other: Link2,
}

const durationIcons: Record<string, any> = {
  less_1_month: Sprout,
  '1_to_6_months': Calendar,
  '6_to_12_months': CalendarDays,
  over_1_year: History,
}

const styleIcons: Record<string, any> = {
  talkative: MessageCircle,
  normal: MessageSquare,
  reserved: VolumeX,
}

function getIconComponent(category: 'relationship' | 'duration' | 'style', value: string) {
  if (category === 'relationship') return relationshipIcons[value] || Users
  if (category === 'duration') return durationIcons[value] || Calendar
  if (category === 'style') return styleIcons[value] || MessageSquare
  return Users
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

    // 回填已保存的维度权重
    try {
      const cfg = await getAffinityConfig(props.conversationId)
      for (const dim of weightDims) {
        const saved = (cfg as any)[dim.field]
        if (typeof saved === 'number' && saved >= 0) {
          ;(weightForm as any)[dim.field] = Math.round(saved * 100)
        }
      }
      if (typeof cfg.llm_relationship_enabled === 'boolean') {
        weightForm.llm_relationship_enabled = cfg.llm_relationship_enabled
      }
    } catch (e) {
      console.warn('加载维度权重失败（沿用默认）', e)
    }
  }
}, { immediate: true })

const handleSave = async () => {
  // 全零预校验（后端 validate 同款口径）
  if (weightTotal.value <= 0) {
    showDialog('至少一个维度权重要大于 0')
    return
  }
  isSaving.value = true
  try {
    await saveRelationshipContext(props.conversationId, {
      relationship_type: form.relationship_type,
      interaction_duration: form.interaction_duration,
      communication_style: form.communication_style,
    })
    // 权重并联保存（点数 → 0-1 小数；触发缓存失效自动重算）
    await updateAffinityConfig(props.conversationId, {
      weight_emotional_resonance: Math.max(0, Number(weightForm.weight_emotional_resonance) || 0) / 100,
      weight_chat_positivity: Math.max(0, Number(weightForm.weight_chat_positivity) || 0) / 100,
      weight_attitude_tendency: Math.max(0, Number(weightForm.weight_attitude_tendency) || 0) / 100,
      weight_preference_compatibility: Math.max(0, Number(weightForm.weight_preference_compatibility) || 0) / 100,
      weight_intimacy_signals: Math.max(0, Number(weightForm.weight_intimacy_signals) || 0) / 100,
      weight_llm_relationship: Math.max(0, Number(weightForm.weight_llm_relationship) || 0) / 100,
      llm_relationship_enabled: weightForm.llm_relationship_enabled,
    })
    emit('saved')
    emit('update:modelValue', false)
  } catch (e) {
    console.error('保存关系上下文失败', e)
    showDialog('保存失败: ' + (e instanceof Error ? e.message : String(e)))
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ct-color-primary);
  height: 22px;
}

.radio-label {
  font-size: var(--ct-text-xs);
  color: var(--ct-text-primary);
  font-weight: 500;
  line-height: 1.2;
}

/* 提示框 */
/* 维度权重（点数制编辑：名称 + 0-100 输入 + 实时归一百分比） */
.weight-hint {
  font-size: 12px;
  font-weight: normal;
  color: var(--ct-text-secondary, #64748b);
}

.weight-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.weight-row {
  display: grid;
  grid-template-columns: 1fr 76px 48px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.weight-name {
  color: var(--ct-text-primary);
}

.weight-input {
  width: 100%;
  padding: 4px 8px;
  border: 1px solid var(--ct-border-color);
  border-radius: 6px;
  background: var(--ct-bg-input, transparent);
  color: var(--ct-text-primary);
  font-size: 13px;
  text-align: right;
}

.weight-pct {
  text-align: right;
  color: var(--ct-text-secondary, #64748b);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.weight-llm-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ct-text-secondary, #64748b);
  cursor: pointer;
  margin-top: 2px;
}

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
