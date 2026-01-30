<template>
  <div ref="chartRef" class="radar-chart"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

const props = defineProps<{
  dimensionScores: {
    emotional_resonance?: { score: number; weight: number }
    chat_positivity?: { score: number; weight: number }
    attitude_tendency?: { score: number; weight: number }
    preference_compatibility?: { score: number; weight: number }
  }
}>()

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// Helper to get CSS variable value
const getCssVar = (name: string) => {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const getOption = (): EChartsOption => {
  // 定义所有维度的配置
  const allDimensions = [
    {
      key: 'emotional_resonance',
      name: '情感\n共振率',
      fullName: '情感共振率',
      score: props.dimensionScores.emotional_resonance?.score || 0,
      weight: props.dimensionScores.emotional_resonance?.weight || 0
    },
    {
      key: 'chat_positivity',
      name: '聊天\n积极度',
      fullName: '聊天积极度',
      score: props.dimensionScores.chat_positivity?.score || 0,
      weight: props.dimensionScores.chat_positivity?.weight || 0
    },
    {
      key: 'preference_compatibility',
      name: '喜好\n兼容度',
      fullName: '喜好兼容度',
      score: props.dimensionScores.preference_compatibility?.score || 0,
      weight: props.dimensionScores.preference_compatibility?.weight || 0
    },
    {
      key: 'attitude_tendency',
      name: '态度\n倾向',
      fullName: '态度倾向',
      score: props.dimensionScores.attitude_tendency?.score || 0,
      weight: props.dimensionScores.attitude_tendency?.weight || 0
    }
  ]

  // 过滤掉权重为0的维度
  const activeDimensions = allDimensions.filter(dim => dim.weight > 0)
  
  // 生成indicator和data
  const indicators = activeDimensions.map(dim => ({
    name: dim.name,
    max: 100
  }))
  
  const scores = activeDimensions.map(dim => dim.score)
  const dimensionNames = activeDimensions.map(dim => dim.fullName)
  const weights = activeDimensions.map(dim => dim.weight)

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
      },
      formatter: (params: any) => {
        const index = params.dataIndex
        const weight = weights[index]
        const weightText = weight !== undefined ? ` (权重: ${Math.round(weight * 100)}%)` : ''
        return `${dimensionNames[index]}${weightText}<br/>分数: ${params.value}`
      }
    },
    radar: {
      indicator: indicators,
      center: ['50%', '50%'],
      radius: '60%',
      splitNumber: 4,
      axisName: {
        color: textColor,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'var(--ct-font-body)'
      },
      splitArea: {
        areaStyle: {
          color: [splitAreaColor1, splitAreaColor2],
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
                { offset: 1, color: 'rgba(91, 107, 224, 0.1)' }
              ])
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
}

const updateChart = () => {
  if (chartInstance) {
    chartInstance.setOption(getOption())
  }
}

onMounted(() => {
  nextTick(() => {
    initChart()
  })
  
  window.addEventListener('resize', () => {
    chartInstance?.resize()
  })
})

onUnmounted(() => {
  chartInstance?.dispose()
  window.removeEventListener('resize', () => {
    chartInstance?.resize()
  })
})

watch(() => props.dimensionScores, () => {
  updateChart()
}, { deep: true })
</script>

<style scoped>
.radar-chart {
  width: 100%;
  height: 400px;
}
</style>
