<template>
  <div class="panel mirror-cmp">
    <div class="panel-head">
      <div>
        <div class="panel-title">镜像对照</div>
        <div class="panel-sub">同指标同量纲——你与 TA 在这段对话里的样子</div>
      </div>
    </div>

    <div v-if="loading" class="empty-state">正在对照你们俩的互动…</div>
    <div v-else-if="error" class="mirror-err">
      <span>{{ error }}</span>
      <button class="btn" @click="load">重试</button>
    </div>
    <div v-else-if="empty" class="empty-state">还没有可对照的互动数据——先导入聊天记录</div>

    <template v-else>
      <!-- 三行同量纲双轨：我（墨紫）/ TA（琥珀） -->
      <div class="mirror-rows">
        <div v-for="row in rows" :key="row.label" class="mirror-row">
          <div class="mirror-row-label">{{ row.label }}</div>
          <div class="mirror-row-track">
            <div class="mirror-cell me">
              <span class="mirror-val">{{ row.me }}</span>
              <i :style="{ width: row.meBar, background: COLOR_ME }" />
            </div>
            <div class="mirror-cell ta">
              <span class="mirror-val">{{ row.ta }}</span>
              <i :style="{ width: row.taBar, background: COLOR_OTHER }" />
            </div>
          </div>
        </div>
      </div>
      <div class="legend-row mirror-legend">
        <span><span class="swatch" :style="{ background: COLOR_ME }" />我</span>
        <span><span class="swatch" :style="{ background: COLOR_OTHER }" />TA</span>
      </div>

      <!-- 对照句：统计直出，不下价值判断 -->
      <ul class="mirror-notes">
        <li v-for="(note, i) in notes" :key="i">{{ note }}</li>
      </ul>

      <!-- 短板提示：我的视角，观察不评判 -->
      <div v-if="weakSpot" class="mirror-weak" role="note">
        <span class="mirror-weak-tag">留意的点</span>
        <span>{{ weakSpot }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/bridge'
import { BIG5_COLOR_ME, BIG5_COLOR_OTHER } from '@/components/deep/big5Shared'

/** 镜像对照（§4.3）：回复速度/开场主动/字数投入的双方并排 + 对照句统计直出。 */
const props = defineProps<{ conversationId: number | null }>()

const COLOR_ME = BIG5_COLOR_ME
const COLOR_OTHER = BIG5_COLOR_OTHER

type Side = { count: number; avg: number | null; median: number | null }
type MirrorStats = {
  reply: { me: Side; ta: Side }
  initiative: { total: number; me: number; ta: number }
  volume: { me_chars: number; ta_chars: number }
}

const stats = ref<MirrorStats | null>(null)
const loading = ref(false)
const error = ref('')

async function load() {
  const id = props.conversationId
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    const res = await api.get_mirror_stats(id)
    if (!res?.ok) {
      error.value = res?.error || '读取失败'
      stats.value = null
      return
    }
    stats.value = res
  } catch (e: any) {
    error.value = e?.message || '请求失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.conversationId, load)
onMounted(load)

const empty = computed(() => {
  const s = stats.value
  return !s || (s.initiative.total === 0 && s.volume.me_chars + s.volume.ta_chars === 0)
})

// ---------- 展示口径 ----------

function fmtSeconds(sec: number | null): string {
  if (sec == null) return '无样本'
  if (sec < 60) return `${Math.round(sec)} 秒`
  if (sec < 3600) return `${(sec / 60).toFixed(sec < 600 ? 1 : 0)} 分钟`
  return `${(sec / 3600).toFixed(1)} 小时`
}

function fmtChars(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万字`
  if (n >= 1000) return `${(n / 1000).toFixed(1)} 千字`
  return `${n} 字`
}

const rows = computed(() => {
  const s = stats.value
  if (!s) return []
  const maxMedian = Math.max(s.reply.me.median || 0, s.reply.ta.median || 0) || 1
  const maxChars = Math.max(s.volume.me_chars, s.volume.ta_chars) || 1
  const maxInit = Math.max(s.initiative.me, s.initiative.ta) || 1
  const pct = (v: number, base: number) => `${Math.max(4, Math.round((v / base) * 100))}%`
  return [
    {
      label: '回复中位数',
      me: s.reply.me.count ? fmtSeconds(s.reply.me.median) : '无样本',
      ta: s.reply.ta.count ? fmtSeconds(s.reply.ta.median) : '无样本',
      meBar: s.reply.me.count ? pct(s.reply.me.median || 0, maxMedian) : '0%',
      taBar: s.reply.ta.count ? pct(s.reply.ta.median || 0, maxMedian) : '0%',
    },
    {
      label: '开场次数',
      me: s.initiative.total ? `${s.initiative.me} 次` : '无会话',
      ta: s.initiative.total ? `${s.initiative.ta} 次` : '无会话',
      meBar: pct(s.initiative.me, maxInit),
      taBar: pct(s.initiative.ta, maxInit),
    },
    {
      label: '字数投入',
      me: fmtChars(s.volume.me_chars),
      ta: fmtChars(s.volume.ta_chars),
      meBar: pct(s.volume.me_chars, maxChars),
      taBar: pct(s.volume.ta_chars, maxChars),
    },
  ]
})

const notes = computed<string[]>(() => {
  const s = stats.value
  if (!s) return []
  const out: string[] = []

  // 回复速度（样本 ≥5 才说话，双侧都在才可比）
  const meM = s.reply.me.median
  const taM = s.reply.ta.median
  if (s.reply.me.count >= 5 && s.reply.ta.count >= 5 && meM && taM) {
    const ratio = meM / taM
    if (ratio <= 0.75) out.push(`你回 TA 比较快——约为 TA 回你速度的 ${ratio.toFixed(1)} 倍`)
    else if (ratio >= 1.33) out.push(`TA 回你比较快——你回复中位数是 TA 的 ${ratio.toFixed(1)} 倍`)
    else out.push('你们的回复节奏基本一致，谁也不让谁等')
  }

  // 开场主动
  if (s.initiative.total >= 5) {
    const meP = s.initiative.me / s.initiative.total
    if (meP >= 0.7) out.push(`${Math.round(meP * 100)}% 的对话由你开场`)
    else if (meP <= 0.3) out.push(`${Math.round((1 - meP) * 100)}% 的对话由 TA 开场`)
    else out.push('开场基本对半，你们都会主动找对方')
  }

  // 字数投入
  if (s.volume.me_chars > 0 && s.volume.ta_chars > 0) {
    const ratio = s.volume.me_chars / s.volume.ta_chars
    if (ratio >= 1.3) out.push(`你打的字是 TA 的 ${ratio.toFixed(1)} 倍`)
    else if (ratio <= 0.77) out.push(`TA 打的字是你的 ${(1 / ratio).toFixed(1)} 倍`)
  }
  return out.slice(0, 3)
})

const weakSpot = computed<string | null>(() => {
  const s = stats.value
  if (!s) return null
  // 我的视角：显著失衡才提示，口径与对照句一致但阈值更保守（少说没有的话）
  if (s.initiative.total >= 10 && s.initiative.me / s.initiative.total >= 0.8) {
    return '对话几乎全靠你开场——TA 主动来找你的次数不多'
  }
  if (s.reply.me.count >= 10 && s.reply.ta.count >= 10 && s.reply.me.median && s.reply.ta.median) {
    if (s.reply.me.median / s.reply.ta.median >= 2) {
      return '你的回复比 TA 慢得多——在意的话可以留意一下回复节奏'
    }
  }
  if (s.volume.me_chars > 0 && s.volume.ta_chars > 0 && s.volume.me_chars / s.volume.ta_chars <= 0.5) {
    return '你的字数投入明显少于 TA——TA 在这段对话里说得更多'
  }
  return null
})
</script>

<style scoped>
.mirror-rows {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 10px;
}

.mirror-row-label {
  font-size: 13px;
  color: var(--ct-text-secondary);
  margin-bottom: 5px;
}

.mirror-row-track {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.mirror-cell {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
}

.mirror-cell i {
  display: block;
  height: 8px;
  border-radius: 4px;
  transition: width 0.2s;
}

.mirror-val {
  min-width: 64px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  color: var(--ct-text-primary);
}

.mirror-legend {
  margin: 2px 0 12px;
}

.mirror-notes {
  list-style: none;
  margin: 0 0 10px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mirror-notes li {
  font-size: 13px;
  line-height: 1.55;
  color: var(--ct-text-primary);
  padding-left: 14px;
  position: relative;
}

.mirror-notes li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ct-color-primary);
}

.mirror-weak {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--ct-color-warning-tint);
  font-size: 13px;
  line-height: 1.55;
  color: var(--ct-text-primary);
}

.mirror-weak-tag {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--ct-color-warning);
}

.mirror-err {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--ct-color-error);
  font-size: 13px;
}
</style>
