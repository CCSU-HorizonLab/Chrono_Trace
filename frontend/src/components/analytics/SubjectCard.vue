<template>
  <div class="subject-card">
    <div class="card">
      <div class="header">
        <img v-if="subject?.avatar" :src="subject!.avatar" alt="avatar" />
        <div v-else class="avatar-fallback">{{ subject?.name?.[0] || '?' }}</div>
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
      <div v-else class="empty">暂无统计</div>
    </div>
  </div>
</template>

<script setup lang="ts">
type SubjectStats = { msgCount: number; avgScore: number; maxDay?: string; minDay?: string }
export type Subject = { id?: string | number; name: string; avatar?: string; stats?: SubjectStats }

defineProps<{ subject?: Subject }>()
</script>

<style scoped>
.card {
  background: var(--ct-bg-elevated);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-lg);
  box-shadow: var(--ct-shadow-md);
  padding: var(--ct-space-lg);
  transition: transform var(--ct-transition-normal) var(--ct-ease-out),
              box-shadow var(--ct-transition-normal) var(--ct-ease-out),
              border-color var(--ct-transition-normal) var(--ct-ease-out);
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: var(--ct-shadow-lg);
  border-color: var(--ct-border-color-hover);
}

.header { display: flex; align-items: center; gap: var(--ct-space-md); }
.header img { width: 44px; height: 44px; border-radius: 50%; object-fit: cover; }
.avatar-fallback {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--ct-color-primary-light);
  color: var(--ct-color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--ct-font-bold);
}
.title .name { font-size: var(--ct-text-base); font-weight: var(--ct-font-bold); color: var(--ct-text-primary); }
.title .sub { color: var(--ct-text-secondary); font-size: var(--ct-text-xs); }
.stats { margin-top: var(--ct-space-md); display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--ct-space-sm); }
.stat {
  background: var(--ct-bg-secondary);
  border: 1px solid var(--ct-border-color);
  border-radius: var(--ct-radius-md);
  padding: var(--ct-space-sm) var(--ct-space-md);
  display: flex;
  flex-direction: column;
  gap: var(--ct-space-xs);
}
.stat .k { color: var(--ct-text-secondary); font-size: var(--ct-text-xs); }
.stat .v { font-weight: var(--ct-font-bold); color: var(--ct-text-primary); }
.empty { color: var(--ct-text-secondary); margin-top: var(--ct-space-sm); }
</style>
