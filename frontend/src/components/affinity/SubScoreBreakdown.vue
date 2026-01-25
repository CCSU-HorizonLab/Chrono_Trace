<template>
  <div class="sub-score-breakdown">
    <h3 class="breakdown-title">{{ title }} 详情</h3>
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
            <td class="score-cell">{{ formatScore(score) }}</td>
            <td>
              <span class="badge" :class="getBadgeClass(score)">
                {{ getRating(score) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">


const props = defineProps<{
  title: string
  subScores: Record<string, number>
}>()

const LABELS: Record<string, string> = {
  // Emotional Resonance
  bidirectional_positive: '双向积极互动',
  polarity_consistency: '情绪一致性',
  intensity_matching: '情绪强度匹配',
  empathy_recognition: '共情识别',
  negative_resolution: '负面情绪化解',

  // Chat Positivity
  daily_message: '日均消息量',
  reply_timeliness: '回复及时性',
  avg_length: '平均消息长度',
  long_text_ratio: '长文比例',
  topic_continuity: '话题连续性',
  active_initiation: '主动发起',

  // Attitude Tendency
  positive_word_frequency: '正面词频率',
  negative_word_frequency: '负面词频率',
  multimedia_usage: '多媒体互动',
  nickname_frequency: '专属昵称',
  privacy_sharing: '隐私分享',
  holiday_greeting: '节日祝福',

  // Preference Compatibility
  topic_mention: '共同话题提及',
}

const getLabel = (key: string): string => {
  return LABELS[key] || key
}

const formatScore = (score: number): string => {
  return score.toFixed(1)
}

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
</script>

<style scoped>
.sub-score-breakdown {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-lg);
  box-shadow: var(--ct-shadow-sm);
}

.breakdown-title {
  margin-top: 0;
  margin-bottom: var(--ct-space-md);
  font-size: var(--ct-text-sm);
  font-weight: 600;
  color: var(--ct-text-primary);
  padding-left: var(--ct-space-sm);
  border-left: 3px solid var(--ct-color-primary);
}

.table-container {
  overflow-x: auto;
}

.score-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ct-text-sm);
}

.score-table th,
.score-table td {
  padding: var(--ct-space-sm) var(--ct-space-md);
  text-align: left;
  border-bottom: 1px solid var(--ct-border-color);
  color: var(--ct-text-secondary);
}

.score-table th {
  color: var(--ct-text-tertiary);
  font-weight: 500;
  border-bottom: 1px solid var(--ct-border-color);
  font-size: var(--ct-text-xs);
}

.score-table tr:last-child td {
  border-bottom: none;
}

.score-cell {
  font-family: var(--ct-font-mono);
  font-weight: 500;
  color: var(--ct-text-primary) !important;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: var(--ct-radius-full);
  font-size: var(--ct-text-xs);
  font-weight: 500;
  line-height: 1.2;
}

.badge-success {
  background: var(--ct-color-success-light);
  color: var(--ct-color-success-dark);
}

.badge-info {
  background: var(--ct-color-info-light);
  color: var(--ct-color-info-dark);
}

.badge-warning {
  background: var(--ct-color-warning-light);
  color: var(--ct-color-warning-dark);
}

.badge-danger {
  background: var(--ct-color-error-light);
  color: var(--ct-color-error-dark);
}
</style>
