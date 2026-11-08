<template>
  <div class="panel emoji-museum">
    <div class="panel-head">
      <div>
        <div class="panel-title">表情博物馆</div>
        <div class="panel-sub">双方最爱的表情、互发表情的节奏，与那些反复出现的专属表情</div>
      </div>
      <div v-if="scanned" class="panel-badge">扫过 {{ scanned.toLocaleString() }} 条消息</div>
    </div>

    <div v-if="!hasAny" class="empty-state">这段对话里还没有出现过表情。</div>

    <template v-else>
      <!-- 双方 Top 榜：unicode 直接渲染字符，内置词经映射转 Unicode（未收录回退词徽章） -->
      <div class="museum-top">
        <section v-for="side in topSections" :key="side.key" class="top-col">
          <h4 class="top-col-title">{{ side.title }}最爱</h4>
          <div v-if="!side.items.length" class="top-empty">暂无表情</div>
          <ol v-else class="top-list">
            <li v-for="item in side.items" :key="side.key + item.key" class="top-row">
              <span class="top-emoji" :title="item.label">{{ item.char }}</span>
              <span class="top-word">{{ item.label }}</span>
              <span class="top-bar" :style="{ width: barWidth(item.count, side.max) }" />
              <span class="top-count">{{ item.count }}</span>
            </li>
          </ol>
        </section>
      </div>

      <!-- 表情节奏：24 小时分布 + 高峰翻译句 -->
      <section class="museum-rhythm">
        <h4 class="block-title">表情节奏</h4>
        <p v-if="rhythmSentence" class="rhythm-sentence">{{ rhythmSentence }}</p>
        <div class="hour-bars" role="img" :aria-label="'24 小时表情分布，高峰在' + (rhythmLabel || '')">
          <div
            v-for="(n, h) in hourly"
            :key="h"
            class="hour-bar"
            :class="{ peak: h === peakHour }"
            :style="{ height: hourBarHeight(n) }"
            :title="`${h} 点 · ${n} 次`"
          />
        </div>
        <div class="hour-axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>23</span></div>
      </section>

      <!-- 自定义表情墙：md5 聚合卡片（原图在微信私有格式/加密库中，诚实降级为统计卡） -->
      <section class="museum-wall">
        <h4 class="block-title">自定义表情</h4>
        <div v-if="!wall.length && !anonymousTotal" class="wall-empty">
          这段对话没有互发过微信自定义表情。
        </div>
        <template v-else>
          <div v-if="wall.length" class="wall-grid">
            <div v-for="card in wall" :key="card.md5" class="wall-card" :title="wallCardTitle(card)">
              <div class="wall-thumb">{{ card.md5.slice(0, 2).toUpperCase() }}</div>
              <div class="wall-meta">
                <div class="wall-count">{{ card.count }} 次</div>
                <div class="wall-split">你 {{ card.count_me }} · TA {{ card.count_ta }}</div>
                <div v-if="card.first_used" class="wall-first">首次 {{ fmtDate(card.first_used) }}</div>
              </div>
            </div>
          </div>
          <p v-if="anonymousTotal" class="wall-note">
            另有 {{ anonymousTotal }} 次自定义表情因消息原文已不可解析，无法归类到具体款式。
          </p>
        </template>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { emojiCharFor } from '@/utils/wechatEmoji'

type TopItem = { key: string; count: number }
type WallCard = {
  md5: string
  count: number
  count_me: number
  count_ta: number
  first_used: number | null
  last_used: number | null
}

const props = defineProps<{
  stats: {
    ok?: boolean
    scanned_messages?: number
    top_me?: { unicode?: TopItem[]; builtin?: TopItem[] }
    top_ta?: { unicode?: TopItem[]; builtin?: TopItem[] }
    months?: Array<{ month: string; me: number; ta: number }>
    hourly?: number[]
    peak_hour?: number
    peak_count?: number
    rhythm_label?: string
    custom_wall?: WallCard[]
    custom_anonymous?: { me?: number; ta?: number }
  } | null
}>()

const scanned = computed(() => props.stats?.scanned_messages || 0)
const hourly = computed(() => props.stats?.hourly || Array(24).fill(0))
const peakHour = computed(() => props.stats?.peak_hour ?? -1)
const rhythmLabel = computed(() => props.stats?.rhythm_label || '')
const wall = computed(() => props.stats?.custom_wall || [])
const anonymousTotal = computed(
  () => (props.stats?.custom_anonymous?.me || 0) + (props.stats?.custom_anonymous?.ta || 0),
)

function withChar(item: TopItem): { key: string; char: string; label: string; count: number } {
  const mapped = emojiCharFor(item.key)
  // 统计键是 Unicode 簇（已去变体符）或内置中文词：有映射→词，无映射→簇本身
  return {
    key: item.key,
    char: mapped || item.key,
    label: mapped ? `[${item.key}]` : '',
    count: item.count,
  }
}

const topSections = computed(() => {
  const build = (side: 'me' | 'ta', title: string) => {
    const unicode = (side === 'me' ? props.stats?.top_me : props.stats?.top_ta)?.unicode || []
    const builtin = (side === 'me' ? props.stats?.top_me : props.stats?.top_ta)?.builtin || []
    // unicode 与内置词合并按次数排同一榜（取前 8，榜太长失去「最爱」焦点）
    const items = [...unicode, ...builtin]
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
      .map(withChar)
    return { key: side, title, items, max: items[0]?.count || 1 }
  }
  return [build('me', '你'), build('ta', 'TA')]
})

const hasAny = computed(
  () => topSections.value.some((s) => s.items.length) || wall.value.length || anonymousTotal.value,
)

const rhythmSentence = computed(() => {
  if (!props.stats?.peak_count || !rhythmLabel.value) return ''
  return `你们互发表情的高峰在${rhythmLabel.value}。`
})

function barWidth(count: number, max: number): string {
  return `${Math.max(6, Math.round((count / max) * 100))}%`
}

function hourBarHeight(n: number): string {
  const max = Math.max(...hourly.value, 1)
  return `${Math.max(n > 0 ? 8 : 2, Math.round((n / max) * 64))}px`
}

function fmtDate(ts: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function wallCardTitle(card: WallCard): string {
  const range = card.first_used && card.last_used ? `${fmtDate(card.first_used as number)} ~ ${fmtDate(card.last_used as number)}` : ''
  return `md5 ${card.md5}${range ? ' · ' + range : ''}`
}
</script>

<style scoped>
.emoji-museum { display: flex; flex-direction: column; gap: 18px; }

.museum-top { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.top-col-title { margin: 0 0 10px; font-size: 13px; font-weight: 600; color: var(--ct-text-primary); }
.top-empty, .wall-empty { font-size: 13px; color: var(--ct-text-tertiary); }

.top-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.top-row { display: grid; grid-template-columns: 30px 52px 1fr 44px; align-items: center; gap: 8px; }
.top-emoji { font-size: 20px; line-height: 1; text-align: center; }
.top-word { font-size: 11px; color: var(--ct-text-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-bar { height: 8px; border-radius: 4px; background: var(--ct-color-primary-tint); }
.top-count { font-size: 12px; color: var(--ct-text-secondary); text-align: right; font-variant-numeric: tabular-nums; }

.block-title { margin: 0 0 8px; font-size: 13px; font-weight: 600; color: var(--ct-text-primary); }
.rhythm-sentence { margin: 0 0 10px; font-size: 13px; color: var(--ct-text-secondary); }

.hour-bars { display: flex; align-items: flex-end; gap: 3px; height: 68px; padding: 0 2px; }
.hour-bar { flex: 1; min-height: 2px; border-radius: 2px 2px 0 0; background: var(--ct-color-primary-subtle); }
.hour-bar.peak { background: var(--ct-color-primary); }
.hour-axis { display: flex; justify-content: space-between; margin-top: 4px; font-size: 11px; color: var(--ct-text-tertiary); }

.wall-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.wall-card { display: flex; gap: 10px; align-items: center; padding: 10px; border: 1px solid var(--ct-border-color); border-radius: 10px; background: var(--ct-bg-sunken); }
.wall-thumb { width: 40px; height: 40px; border-radius: 8px; background: var(--ct-color-primary-tint); color: var(--ct-color-primary); display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700; flex: none; }
.wall-meta { min-width: 0; }
.wall-count { font-size: 13px; font-weight: 600; color: var(--ct-text-primary); }
.wall-split { font-size: 11px; color: var(--ct-text-secondary); }
.wall-first { font-size: 11px; color: var(--ct-text-tertiary); }
.wall-note { margin: 10px 0 0; font-size: 12px; color: var(--ct-text-tertiary); }

@media (max-width: 720px) {
  .museum-top { grid-template-columns: 1fr; }
}
</style>
