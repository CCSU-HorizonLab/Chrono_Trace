<template>
  <div class="poster-studio panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">分享海报</div>
        <div class="panel-sub">竖版长图讲故事，方形称号卡抢眼球；不同模板适合不同的分享对象</div>
      </div>
    </div>

    <div v-if="loading" class="empty-state">正在准备海报素材…</div>
    <div v-else-if="error" class="state-row">
      <span class="error-text">{{ error }}</span>
      <button class="btn" @click="load">重试</button>
    </div>
    <template v-else-if="payload">
      <div class="template-row">
        <button
          v-for="template in templates"
          :key="template.id"
          class="template-card"
          :class="{ active: activeId === template.id, sensitive: template.sensitive }"
          @click="activeId = template.id"
        >
          <span class="template-label">{{ template.label }}</span>
          <span class="template-desc">{{ template.description }}</span>
        </button>
      </div>

      <!-- 预览即所得：导出的就是这块节点（不处于动画/transform 中） -->
      <div class="preview-shell">
        <div ref="posterRef" class="poster-holder">
          <component :is="activeTemplate.component" :payload="activePayload as any" />
        </div>
      </div>

      <div class="export-row">
        <button class="btn primary" :disabled="exporting" @click="exportImage('long')">
          {{ exporting ? '正在合成图片…' : '导出长图' }}
        </button>
        <button class="btn" :disabled="exporting || !squareSpec" @click="exportImage('square')">
          导出方卡
        </button>
        <span v-if="exportResultText" class="export-result">{{ exportResultText }}</span>
        <span v-else-if="exportError" class="error-text">{{ exportError }}</span>
      </div>

      <!-- 方卡离屏渲染台：display:none 会破坏 html2canvas 克隆，固定定位移出视口代替 -->
      <div v-if="squareSpec" class="square-stage" aria-hidden="true">
        <div ref="squareRef">
          <SquareCard :spec="squareSpec" />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { showConfirm } from '@/utils/dialog'
import { toLocalDateKey } from '@/utils/datetime'
import { exportNodeAsPng } from '@/components/deep/poster/exportNode'
import SquareCard, { type SquareCardSpec } from '@/components/deep/poster/SquareCard.vue'
import {
  POSTER_TEMPLATES,
  sanitizeForPublic,
  sanitizeForSelf,
  type IntimatePosterPayload,
  type PosterAudience,
} from '@/components/deep/poster/registry'
import { POSTER_THEMES } from '@/components/deep/poster/theme'
import { formatCount } from '@/components/deep/poster/activityShared'
import {
  badgeInputFromIntimate,
  badgeInputFromPublic,
  badgeInputFromSelf,
  pickPosterBadge,
  posterSubBadges,
} from '@/components/deep/poster/badges'

const props = defineProps<{
  conversationId: number
  dates: { from: string; to: string }
  contactName?: string
}>()

const payload = ref<IntimatePosterPayload | null>(null)
const loading = ref(false)
const error = ref('')
const activeId = ref(POSTER_TEMPLATES[0].id)
const exporting = ref(false)
const exportResultText = ref('')
const exportError = ref('')
const posterRef = ref<HTMLElement | null>(null)
const squareRef = ref<HTMLElement | null>(null)

const templates = POSTER_TEMPLATES
const activeTemplate = computed(
  () => POSTER_TEMPLATES.find((t) => t.id === activeId.value) || POSTER_TEMPLATES[0],
)

// 模板层脱敏：公开/自我版经投影函数消费，拿不到 contact/quotes
const activePayload = computed(() => {
  if (!payload.value) return null
  if (activeTemplate.value.audience === 'intimate') return payload.value
  if (activeTemplate.value.audience === 'self') return sanitizeForSelf(payload.value)
  return sanitizeForPublic(payload.value)
})

// 方卡称号输入与模板同源（同受众投影 → 同一套称号规则，长图与方卡口径一致）
const badgeInputFor = computed(() => {
  const p = payload.value
  if (!p) return null
  if (activeTemplate.value.audience === 'intimate') return badgeInputFromIntimate(p)
  if (activeTemplate.value.audience === 'self') return badgeInputFromSelf(sanitizeForSelf(p))
  return badgeInputFromPublic(sanitizeForPublic(p))
})

const squareSpec = computed<SquareCardSpec | null>(() => {
  const p = payload.value
  const input = badgeInputFor.value
  if (!p || !input) return null
  const audience: PosterAudience = activeTemplate.value.audience
  const theme = POSTER_THEMES[audience]
  // 迷你数字行 + 高频词 chips：受众口径与长图分镜一致（公开联合/自我单侧/定向全量）
  let miniStats: { num: string; label: string }[] = []
  let wordChips: string[] = []
  let wordsLabel = '聊得最多的词'
  if (audience === 'intimate') {
    const chem = p.story?.chemistry
    const rs = chem?.reply_stats
    miniStats = [
      { num: `${formatCount(p.stats.span_days)} 天`, label: '跨度' },
      { num: `${formatCount(p.stats.active_days)} 天`, label: '活跃' },
      ...(rs
        ? [{ num: formatDuration(rs.median ?? rs.avg), label: '中位回复' }]
        : chem?.late_night
          ? [{ num: formatCount(chem.late_night.count), label: '深夜消息' }]
          : []),
    ]
    wordChips = (p.top_words?.all || []).slice(0, 8).map((w) => w.word)
    wordsLabel = '你们聊得最多的词'
  } else if (audience === 'self') {
    const s = sanitizeForSelf(p)
    miniStats = [
      { num: `${formatCount(s.stats.span_days)} 天`, label: '跨度' },
      { num: `${formatCount(s.stats.active_days)} 天`, label: '活跃' },
      ...(s.my_story.reply_self_avg_seconds != null
        ? [{ num: formatDuration(s.my_story.reply_self_avg_seconds), label: '你的平均回复' }]
        : []),
    ]
    wordChips = s.my_words.slice(0, 8).map((w) => w.word)
    wordsLabel = '你的高频词'
  } else {
    const s = sanitizeForPublic(p)
    const streak = s.activity?.insights.streak_days
    const chem = s.story?.chemistry
    miniStats = [
      { num: `${formatCount(s.stats.span_days)} 天`, label: '跨度' },
      { num: `${formatCount(s.stats.active_days)} 天`, label: '活跃' },
      ...(streak != null && streak >= 7
        ? [{ num: `${streak} 天`, label: '最长连续' }]
        : chem?.late_night
          ? [{ num: formatCount(chem.late_night.count), label: '深夜消息' }]
          : []),
    ]
    wordChips = (s.top_words.all || []).slice(0, 8).map((w) => w.word)
  }
  return {
    bg: theme.bgGradient,
    palette: theme.palette,
    eyebrow:
      audience === 'intimate' ? '你们的称号' : audience === 'self' ? '你的称号' : '这段对话的称号',
    badge: pickPosterBadge(input, audience),
    subBadges: posterSubBadges(input, audience),
    heroNum: formatCount(audience === 'self' ? p.stats.self_count : p.stats.total),
    heroUnit: '条消息',
    heroCaption: `跨度 ${formatCount(p.stats.span_days)} 天 · 其中 ${formatCount(p.stats.active_days)} 天有消息`,
    miniStats,
    wordChips,
    wordsLabel,
    names:
      audience === 'intimate'
        ? { left: p.contact.display_name, right: '我' }
        : audience === 'self'
          ? { left: '我' }
          : undefined,
    yearText: String(new Date(p.generated_at * 1000).getFullYear()),
    // 二维码只随公开受众上方卡：定向/自我版不放
    qr: audience === 'public',
  }
})

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

async function load() {
  // 会话一致性守卫：海报 payload 是重查询，慢响应后到时不能覆盖新会话数据
  const requestKey = `${props.conversationId}|${props.dates.from}|${props.dates.to}`
  loading.value = true
  error.value = ''
  exportResultText.value = ''
  exportError.value = ''
  try {
    const result = await api.get_poster_payload(
      props.conversationId, props.dates.from, props.dates.to,
    )
    if (requestKey !== `${props.conversationId}|${props.dates.from}|${props.dates.to}`) return
    if (!result?.ok) {
      error.value = result?.error || '加载失败'
      payload.value = null
      return
    }
    payload.value = result
  } catch (e: any) {
    if (requestKey !== `${props.conversationId}|${props.dates.from}|${props.dates.to}`) return
    error.value = e?.message || '请求失败'
  } finally {
    loading.value = false
  }
}

async function exportImage(kind: 'long' | 'square') {
  const node = kind === 'long' ? posterRef.value : squareRef.value
  if (!node || exporting.value) return

  // 定向版包含姓名、头像与聊天摘录：导出前确认（长图/方卡同守则）
  if (activeTemplate.value.sensitive) {
    const confirmed = await showConfirm(
      '定向版包含对方姓名、头像与聊天摘录，请确认仅发送给对方本人。',
    )
    if (!confirmed) return
  }

  exporting.value = true
  exportError.value = ''
  exportResultText.value = ''
  try {
    const suffix = kind === 'square' ? '方卡' : ''
    const name = `时痕${activeTemplate.value.label}${suffix}_${props.contactName || ''}_${toLocalDateKey(new Date())}.png`
    const result = await exportNodeAsPng(node, name)
    if (!result.ok) {
      exportError.value = result.error
      return
    }
    exportResultText.value = result.copied
      ? `已复制到剪贴板，可直接粘贴发送（文件在 ${result.file_path}）`
      : `已保存到 ${result.file_path}`
    api.open_export_folder().catch(() => {})
  } finally {
    exporting.value = false
  }
}

watch(
  () => [props.conversationId, props.dates.from, props.dates.to],
  () => { payload.value = null; load() },
  { immediate: true },
)
</script>

<style scoped>
/* 卡容器/头/按钮/空态走全局 panels.css（海报模板节点不引 panels 类——
   html2canvas 对 CSS 变量支持不稳，仅外壳接共享样式） */

.template-row {
  display: flex;
  gap: var(--ct-space-sm);
  margin-bottom: var(--ct-space-md);
  flex-wrap: wrap;
}

.template-card {
  flex: 1 1 180px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  padding: 10px 14px;
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-card);
  box-shadow: var(--ct-shadow-sm);
  cursor: pointer;
  transition: all 0.2s ease;
}

.template-card.active {
  background: var(--ct-color-primary-tint);
}

.template-card.sensitive .template-label::after {
  content: '仅给对方';
  margin-left: 6px;
  font-size: 10px;
  color: #8F5B14;
  background: var(--ct-color-warning-tint);
  border-radius: 999px;
  padding: 1px 6px;
}

.template-label {
  color: var(--ct-text-primary);
  font-weight: var(--ct-font-bold);
  font-size: var(--ct-text-sm);
}

.template-desc {
  color: var(--ct-text-tertiary);
  font-size: var(--ct-text-xs);
  line-height: 1.5;
}

.preview-shell {
  border-radius: var(--ct-radius-md);
  background: var(--ct-bg-sunken);
  padding: var(--ct-space-sm);
  max-height: 560px;
  overflow: auto;
}

.poster-holder {
  width: 720px;
  max-width: 100%;
  margin: 0 auto;
}

.export-row {
  margin-top: var(--ct-space-md);
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
  flex-wrap: wrap;
}

.export-result {
  color: var(--ct-text-secondary);
  font-size: var(--ct-text-xs);
  word-break: break-all;
}

.error-text {
  color: var(--ct-color-error, #E8656F);
  font-size: var(--ct-text-xs);
}

.state-row {
  display: flex;
  align-items: center;
  gap: var(--ct-space-md);
}

/* 方卡离屏渲染台：html2canvas 按节点克隆渲染，不能 display:none；
   固定定位移出视口即可（节点本身无 transform） */
.square-stage {
  position: fixed;
  left: -10000px;
  top: 0;
  pointer-events: none;
}
</style>
