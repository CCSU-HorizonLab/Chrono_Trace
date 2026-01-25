<template>
  <div ref="chartRef" class="radar-chart"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

const props = defineProps<{
  dimensionScores: {
    emotional_resonance?: { score: number }
    chat_positivity?: { score: number }
    attitude_tendency?: { score: number }
    preference_compatibility?: { score: number }
  }
}>()

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// Helper to get CSS variable value
const getCssVar = (name: string) => {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const getOption = (): EChartsOption => {
  const scores = [
    props.dimensionScores.emotional_resonance?.score || 0,
    props.dimensionScores.chat_positivity?.score || 0,
    props.dimensionScores.preference_compatibility?.score || 0,
    props.dimensionScores.attitude_tendency?.score || 0
  ]

  const primaryColor = getCssVar('--ct-color-primary') || '#5b6be0'
  const textColor = getCssVar('--ct-text-secondary') || '#666'
  const splitLineColor = getCssVar('--ct-border-color') || '#eee'
  const splitAreaColor1 = getCssVar('--ct-bg-secondary') || '#f9fafb'
  const splitAreaColor2 = getCssVar('--ct-bg-tertiary') || '#f3f4f6'
  const tooltipBg = getCssVar('--ct-bg-elevated') || 'rgba(255, 255, 255, 0.9)'
  const tooltipBorder = getCssVar('--ct-border-color') || '#eee'
  const tooltipText = getCssVar('--ct-text-primary') || '#333'

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      textStyle: {
        color: tooltipText
      }
    },
    radar: {
      indicator: [
        { name: '情感\n共振率', max: 100 },
        { name: '聊天\n积极度', max: 100 },
        { name: '喜好\n兼容度', max: 100 },
        { name: '态度\n倾向', max: 100 }
      ],
      center: ['50%', '55%'],
      radius: '65%',
      splitNumber: 4,
      axisName: {
        color: textColor,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'var(--ct-font-body)'
      },
      splitArea: {
        areaStyle: {
          color: [splitAreaColor1, splitAreaColor2, splitAreaColor1, splitAreaColor2],
          shadowColor: 'rgba(0, 0, 0, 0.02)',
          shadowBlur: 5
        }
      },
      axisLine: {
        lineStyle: {
          color: splitLineColor
        }
      },
      splitLine: {
        lineStyle: {
          color: splitLineColor,
          type: 'dashed'
        }
      }
    },
    series: [
      {
        name: '维度评分',
        type: 'radar',
        data: [
          {
            value: scores,
            name: '当前会话',
            symbol: 'circle',
            symbolSize: 6,
            itemStyle: {
              color: primaryColor,
              borderColor: '#fff',
              borderWidth: 2,
              shadowColor: primaryColor,
              shadowBlur: 5
            },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: primaryColor },
                { offset: 1, color: 'rgba(255,255,255,0.1)' }
              ]),
              opacity: 0.4
            },
            lineStyle: {
              width: 3,
              color: primaryColor
            }
          }
        ]
      }
    ]
  }
}

const initChart = () => {
  if (!chartRef.value) return
  
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(getOption())
  
  const resizeObserver = new ResizeObserver(() => {
    chartInstance?.resize()
  })
  resizeObserver.observe(chartRef.value)
}

watch(() => props.dimensionScores, () => {
  chartInstance?.setOption(getOption())
}, { deep: true })

onMounted(() => {
  nextTick(() => {
    initChart()
    // Listen for theme changes or window resize if needed
    window.addEventListener('resize', () => chartInstance?.resize())
  })
})

onUnmounted(() => {
  chartInstance?.dispose()
  window.removeEventListener('resize', () => chartInstance?.resize())
})
</script>

<style scoped>
.radar-chart {
  width: 100%;
  height: 320px;
}
</style>
