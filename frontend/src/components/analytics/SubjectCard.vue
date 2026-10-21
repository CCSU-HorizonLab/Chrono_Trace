<template>
  <div class="subject-card">
    <div class="panel">
      <div class="header">
        <CtAvatar class="subject-avatar" :src="subject?.avatar" :name="subject?.name" :size="44" />
        <div class="title">
          <div class="name">{{ subject?.name || '未选择对象' }}</div>
          <div class="sub">对象信息</div>
        </div>
      </div>
      <div class="stats" v-if="subject?.stats">
        <div class="stat"><span class="k">消息数</span><span class="v">{{ subject!.stats!.msgCount }}</span></div>
        <div class="stat"><span class="k">平均情绪</span><span class="v">{{ (subject!.stats!.avgScore ?? 0).toFixed(2) }}</span></div>
        <div class="stat"><span class="k">最高日</span><span class="v">{{ subject!.stats!.maxDay || '-' }}</span></div>
        <div class="stat"><span class="k">最低日</span><span class="v">{{ subject!.stats!.minDay || '-' }}</span></div>
      </div>
      <div v-if="subject?.stats && !hasAnalysis" class="empty-hint">当前时间范围无分析数据</div>
      <div v-else-if="!subject" class="empty">暂无统计</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import CtAvatar from '@/components/base/CtAvatar.vue'

type SubjectStats = { msgCount: number; avgScore: number; maxDay?: string; minDay?: string }
export type Subject = { id?: string | number; name: string; avatar?: string; stats?: SubjectStats }

defineProps<{ subject?: Subject; hasAnalysis?: boolean }>()
</script>

<style scoped>
.subject-card .panel { margin-bottom: 0; }
.header { display: flex; align-items: center; gap: var(--ct-space-md); }
.subject-avatar { flex-shrink: 0; }
.title .name { font-size: var(--ct-text-base); font-weight: var(--ct-font-bold); color: var(--ct-text-primary); }
.title .sub { color: var(--ct-text-secondary); font-size: var(--ct-text-xs); }
.stats { margin-top: var(--ct-space-md); display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--ct-space-sm); }
.stat {
  background: var(--ct-bg-sunken);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm) var(--ct-space-md);
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xs);
}
.stat .k { color: var(--ct-text-secondary); font-size: var(--ct-text-xs); }
.stat .v { font-weight: var(--ct-font-bold); color: var(--ct-text-primary); }
.empty { color: var(--ct-text-secondary); margin-top: var(--ct-space-sm); }
.empty-hint { color: var(--ct-text-tertiary); margin-top: var(--ct-space-md); font-size: var(--ct-text-sm); }
</style>
