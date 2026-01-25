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
import { defineProps } from 'vue'

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
  // topic_continuity is duplicated, using same label
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
  background: var(--card-bg, #fff);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(0,0,0,0.05);
}

.breakdown-title {
  margin-top: 0;
  margin-bottom: 16px;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary, #333);
  padding-left: 8px;
  border-left: 4px solid var(--primary-color, #1890ff);
}

.table-container {
  overflow-x: auto;
}

.score-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.score-table th,
.score-table td {
  padding: 10px 8px;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
}

.score-table th {
  color: #999;
  font-weight: 500;
  border-bottom: 2px solid #f0f0f0;
}

.score-table tr:last-child td {
  border-bottom: none;
}

.score-cell {
  font-family: monospace;
  font-weight: 600;
}

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
}

.badge-success {
  background: #f6ffed;
  color: #52c41a;
  border: 1px solid #b7eb8f;
}

.badge-info {
  background: #e6f7ff;
  color: #1890ff;
  border: 1px solid #91d5ff;
}

.badge-warning {
  background: #fffbe6;
  color: #faad14;
  border: 1px solid #ffe58f;
}

.badge-danger {
  background: #fff1f0;
  color: #ff4d4f;
  border: 1px solid #ffa39e;
}

/* Dark Mode */
@media (prefers-color-scheme: dark) {
  .sub-score-breakdown {
    background: #1f1f1f;
    border-color: #333;
  }
  .breakdown-title {
    color: #e0e0e0;
  }
  .score-table th {
    color: #666;
    border-bottom-color: #333;
  }
  .score-table td {
    border-bottom-color: #333;
    color: #ccc;
  }
  
  .badge-success { background: #135200; border-color: #237804; color: #52c41a; }
  .badge-info { background: #003a8c; border-color: #096dd9; color: #40a9ff; }
  .badge-warning { background: #614700; border-color: #d4b106; color: #ffc53d; }
  .badge-danger { background: #5c0011; border-color: #a8071a; color: #ff4d4f; }
}
</style>
