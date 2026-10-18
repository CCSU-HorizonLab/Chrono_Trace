<template>
  <div class="milestone-timeline card">
    <div class="panel-header">
      <div class="panel-title">这段关系走过的时间线</div>
      <div class="panel-sub">首条消息、消息量关口、最长沉默期与情绪拐点，按时间排开</div>
    </div>

    <div v-if="!items.length" class="empty">所选区间暂无可提取的事件</div>
    <ol v-else class="timeline">
      <li v-for="(item, index) in items" :key="item.key" class="timeline-item" :class="`kind-${item.kind}`">
        <span class="dot" :class="`dot-${item.kind}`" />
        <div class="item-body">
          <div class="item-title">{{ item.title }}</div>
          <div class="item-meta">
            <span>{{ item.when }}</span>
            <span v-if="item.detail" class="item-detail">{{ item.detail }}</span>
          </div>
        </div>
        <span v-if="index === 0 && items.length > 1" class="first-flag">起点</span>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { toLocalDateKey } from '@/utils/datetime'

type Milestone = {
  kind: 'first_message' | 'count_mark' | 'longest_silence' | string
  scope?: 'global' | 'window'
  mark?: number
  days?: number
  from_ts?: number
  to_ts?: number
  ts: number
}

type TurningPoint = {
  direction: 'drop' | 'rise'
  from_ts: string // 桶标签（周=周一日期 / YYYY-MM / YYYY）
  to_ts: string
  from_score: number
  to_score: number
  delta: number
}

const props = defineProps<{
  milestones: Milestone[]
  turningPoints: TurningPoint[]
  granularity: string
}>()

function fmtTs(ts: number): string {
  return toLocalDateKey(new Date(ts * 1000))
}

function fmtMark(mark: number): string {
  return mark >= 10000 ? `${Math.round(mark / 10000)} 万` : String(mark)
}

// 桶标签（YYYY-MM-DD 周一 / YYYY-MM / YYYY）→ 可比较的秒级时刻（桶起点）
function parseBucketLabel(label: string): number {
  const parts = label.split('-').map(Number)
  if (parts.length >= 3 && Number.isFinite(parts[0]) && Number.isFinite(parts[1]) && Number.isFinite(parts[2])) {
    return Math.floor(new Date(parts[0], parts[1] - 1, parts[2]).getTime() / 1000)
  }
  if (parts.length === 2 && Number.isFinite(parts[0]) && Number.isFinite(parts[1])) {
    return Math.floor(new Date(parts[0], parts[1] - 1, 1).getTime() / 1000)
  }
  const year = Number(label)
  return Number.isFinite(year) ? Math.floor(new Date(year, 0, 1).getTime() / 1000) : 0
}

const unitLabel = computed(
  () => ({ week: '周', month: '月', year: '年', day: '天' } as Record<string, string>)[props.granularity] || props.granularity,
)

interface TimelineItem {
  key: string
  kind: string
  title: string
  when: string
  detail?: string
  sortTs: number
}

const items = computed<TimelineItem[]>(() => {
  const list: TimelineItem[] = []

  for (const event of props.milestones || []) {
    if (event.kind === 'first_message') {
      list.push({
        key: `fm-${event.scope}-${event.ts}`,
        kind: 'first_message',
        title: event.scope === 'global' ? '你们的第一条消息' : '时间窗内的第一条消息',
        when: fmtTs(event.ts),
        sortTs: event.ts,
      })
    } else if (event.kind === 'count_mark') {
      list.push({
        key: `cm-${event.mark}`,
        kind: 'count_mark',
        title: `累计第 ${fmtMark(event.mark!)} 条消息`,
        when: fmtTs(event.ts),
        sortTs: event.ts,
      })
    } else if (event.kind === 'longest_silence') {
      list.push({
        key: `ls-${event.ts}`,
        kind: 'longest_silence',
        title: `最长沉默期：${event.days} 天`,
        when: `${fmtTs(event.from_ts || event.ts)} ~ ${fmtTs(event.to_ts || event.ts)}`,
        sortTs: event.ts,
      })
    }
  }

  // 拐点的 from_ts/to_ts 是桶标签；按「到桶」的起点时刻参与排序
  for (const point of props.turningPoints || []) {
    const deltaText = `${point.delta > 0 ? '+' : ''}${point.delta.toFixed(2)}`
    list.push({
      key: `tp-${point.direction}-${point.to_ts}`,
      kind: 'turning',
      title: point.direction === 'drop' ? '情绪明显回落' : '情绪明显回暖',
      when: `${point.from_ts} → ${point.to_ts}（按${unitLabel.value}）`,
      detail: `${point.from_score.toFixed(2)} → ${point.to_score.toFixed(2)}（${deltaText}）`,
      sortTs: parseBucketLabel(point.to_ts),
    })
  }

  list.sort((a, b) => a.sortTs - b.sortTs)
  return list
})
</script>

<style scoped>
.card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: var(--ct-space-lg);
  margin-bottom: var(--ct-space-lg);
}

.panel-header {
  margin-bottom: var(--ct-space-md);
}

.panel-title {
  font-size: var(--ct-text-base);
  font-weight: var(--ct-font-bold);
  color: var(--ct-text-primary);
}

.panel-sub {
  margin-top: 2px;
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  position: relative;
}

.timeline::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--ct-border-color);
  border-radius: 999px;
}

.timeline-item {
  position: relative;
  display: flex;
  align-items: baseline;
  gap: var(--ct-space-md);
  padding: var(--ct-space-sm) 0 var(--ct-space-sm) var(--ct-space-lg);
}

.dot {
  position: absolute;
  left: 0;
  top: 14px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--ct-color-primary);
  background: var(--ct-bg-elevated);
}

.dot-longest_silence {
  border-color: var(--ct-text-tertiary);
}

.dot-turning {
  border-radius: 3px; /* 拐点用方点区分 */
}

.item-body {
  flex: 1;
  min-width: 0;
}

.item-title {
  color: var(--ct-text-primary);
  font-size: var(--ct-text-sm);
  font-weight: var(--ct-font-bold);
}

.item-meta {
  margin-top: 2px;
  display: flex;
  flex-wrap: wrap;
  gap: var(--ct-space-md);
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
}

.item-detail {
  color: var(--ct-text-tertiary);
}

.first-flag {
  align-self: center;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  font-size: var(--ct-text-xs);
  flex-shrink: 0;
}

.empty {
  color: var(--ct-text-tertiary);
  padding: var(--ct-space-xl) 0;
  text-align: center;
}
</style>
