<template>
  <div class="sub-score-breakdown">
    <h3 class="breakdown-title">{{ title }}详情</h3>
    <p
      v-if="showLowConfidenceHint"
      class="confidence-hint"
    >
      互动样本较少，当前分数更偏向积极迹象，不代表稳定关系深度
      <span v-if="confidenceMeta?.low_confidence_reason">
        （{{ confidenceMeta.low_confidence_reason }}）
      </span>
    </p>
    <div class="table-container">
      <table class="score-table">
        <thead>
          <tr>
            <th>子维度</th>
            <th>得分</th>
            <th>评级</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(score, key) in subScores" :key="key">
            <td>{{ getLabel(key as string) }}</td>
            <td class="score-cell">
              <div class="score-bar-container">
                <div class="score-bar-bg">
                  <div
                    class="score-bar-fill"
                    :class="getBarColorClass(score)"
                    :style="{ width: Math.min(100, Math.max(0, score)) + '%' }"
                  ></div>
                </div>
                <span class="score-text">{{ formatScore(score) }}</span>
              </div>
            </td>
            <td>
              <span class="badge" :class="getBadgeClass(score)">
                {{ getRating(score) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="notes && notes.length" class="evidence-notes">
      <div v-for="(note, idx) in notes" :key="idx" class="evidence-note">
        <span class="evidence-month">{{ note.month }}</span>
        <span class="evidence-quote">"{{ note.quote }}"</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ResonanceConfidenceMeta } from '@/api/affinity'

const props = defineProps<{
  title: string
  subScores: Record<string, number>
  confidenceMeta?: ResonanceConfidenceMeta
  /** 证据条目（LLM 关系评估的原文引用），可选 */
  notes?: Array<{ quote: string; month: string }>
}>()

const LOW_CONFIDENCE_THRESHOLD = 0.55

const LABELS: Record<string, string> = {
  // 互动投入
  daily_message: '日均消息量',
  reply_timeliness: '回复及时性',
  topic_continuity: '话题延续性',
  active_initiation: '主动发起',
  reply_symmetry: '回应对称性',
  long_unanswered: '长时未回应',
  burst_unanswered: '连发未回',
  // 情感共鸣
  bidirectional_positive: '双向积极互动',
  polarity_consistency: '情绪一致性',
  intensity_matching: '情绪强度匹配',
  valence_balance: '正负平衡',
  perfunctory_reply: '敷衍回复',
  empathy_recognition: '共情识别',
  negative_resolution: '负面情绪化解',
  // 亲近信号
  address_term_evolution: '称谓演变',
  late_night_engagement: '深夜时段互动',
  active_coverage: '活跃覆盖',
  greeting_initiation: '早晚安发起',
  icebreaking: '主动破冰',
  community_expression: '共同体表达',
  // 喜好兼容度
  topic_mention: '共同话题提及',
  preference_bonus: '喜好加分',
  // LLM 关系评估
  communication_quality: '沟通质量',
  relationship_warmth: '关系温度',
}

const getLabel = (key: string): string => LABELS[key] || key

const formatScore = (score: number): string => score.toFixed(1)

const getRating = (score: number): string => {
  if (score >= 80) return '优'
  if (score >= 60) return '良'
  if (score >= 40) return '中'
  return '差'
}

const getBadgeClass = (score: number): string => {
  if (score >= 80) return 'badge-success'
  if (score >= 60) return 'badge-info'
  if (score >= 40) return 'badge-warning'
  return 'badge-danger'
}

const getBarColorClass = (score: number): string => {
  if (score >= 80) return 'bar-success'
  if (score >= 60) return 'bar-info'
  if (score >= 40) return 'bar-warning'
  return 'bar-danger'
}

const showLowConfidenceHint = computed(() => {
  return (props.confidenceMeta?.relationship_depth_confidence ?? 1) < LOW_CONFIDENCE_THRESHOLD
})
</script>

<style scoped>
.sub-score-breakdown {
  background: var(--ct-bg-card);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm);
  box-shadow: var(--ct-shadow-sm);
}

.breakdown-title {
  margin-top: 0;
  margin-bottom: var(--ct-space-xs);
  font-size: 13px;
  font-weight: 600;
  color: var(--ct-text-primary);
  padding-left: var(--ct-space-xs);
  border-left: 2px solid var(--ct-color-primary);
}

.table-container {
  overflow-x: auto;
}

.confidence-hint {
  margin: 0 0 var(--ct-space-xs);
  padding: 6px 8px;
  border-radius: var(--ct-radius-sm);
  background: var(--ct-color-warning-light);
  color: var(--ct-color-warning);
  font-size: 11px;
  line-height: 1.45;
}

.score-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.score-table th,
.score-table td {
  padding: 4px 6px;
  text-align: left;
  border-bottom: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.score-table th {
  color: var(--ct-text-tertiary);
  font-weight: 500;
  border-bottom: 1px solid var(--ct-border-color);
  font-size: 11px;
}

.score-table th:nth-child(1),
.score-table td:nth-child(1) {
  width: 38%;
}

.score-table th:nth-child(3),
.score-table td:nth-child(3) {
  text-align: right;
  width: 15%;
}

.score-table tr:last-child td {
  border-bottom: none;
}

.score-cell {
  width: 47%;
}

.score-bar-container {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.score-bar-bg {
  flex: 1;
  height: 6px;
  background-color: var(--ct-border-color);
  border-radius: 3px;
  overflow: hidden;
  min-width: 40px;
}

.score-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.score-text {
  font-family: var(--ct-font-mono);
  font-weight: 500;
  color: var(--ct-text-primary);
  min-width: 28px;
  text-align: right;
}

.bar-success {
  background: var(--ct-color-success);
}

.bar-info {
  background: var(--ct-color-info);
}

.bar-warning {
  background: var(--ct-color-warning);
}

.bar-danger {
  background: var(--ct-color-error);
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  border-radius: var(--ct-radius-full);
  font-size: 10px;
  font-weight: 500;
  line-height: 1.2;
}

.badge-success {
  background: var(--ct-color-success-light);
  color: var(--ct-color-success);
}

.badge-info {
  background: var(--ct-color-info-light);
  color: var(--ct-color-info);
}

.badge-warning {
  background: var(--ct-color-warning-light);
  color: var(--ct-color-warning);
}

.badge-danger {
  background: var(--ct-color-error-light);
  color: var(--ct-color-error);
}

/* LLM 关系评估证据条目 */
.evidence-notes {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.evidence-note {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  color: var(--ct-text-secondary, #5A5566);
}

.evidence-month {
  flex-shrink: 0;
  font-size: 11px;
  opacity: 0.8;
}

.evidence-quote {
  font-style: italic;
}
</style>
