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

const getOption = (): EChartsOption => {
  const scores = [
    props.dimensionScores.emotional_resonance?.score || 0,
    props.dimensionScores.chat_positivity?.score || 0,
    props.dimensionScores.preference_compatibility?.score || 0,
    props.dimensionScores.attitude_tendency?.score || 0
  ]

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.9)',
      borderColor: '#eee',
      textStyle: {
        color: '#333'
      }
    },
    radar: {
      indicator: [
        { name: '情感\n共振率', max: 100 },
        { name: '聊天\n积极度', max: 100 },
        { name: '喜好\n兼容度', max: 100 },
        { name: '态度\n倾向', max: 100 }
      ],
      center: ['50%', '50%'],
      radius: '65%',
      splitNumber: 4,
      axisName: {
        color: '#6b7280',
        fontSize: 13,
        fontWeight: 600,
        fontFamily: 'Inter, system-ui, sans-serif'
      },
      splitArea: {
        areaStyle: {
          color: ['#f9fafb', '#f3f4f6', '#f9fafb', '#f3f4f6'],
          shadowColor: 'rgba(0, 0, 0, 0.02)',
          shadowBlur: 5
        }
      },
      axisLine: {
        lineStyle: {
          color: '#e5e7eb'
        }
      },
      splitLine: {
        lineStyle: {
          color: '#e5e7eb',
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
              color: '#3b82f6',
              borderColor: '#fff',
              borderWidth: 2,
              shadowColor: 'rgba(59, 130, 246, 0.5)',
              shadowBlur: 5
            },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(59, 130, 246, 0.4)' },
                { offset: 1, color: 'rgba(59, 130, 246, 0.1)' }
              ])
            },
            lineStyle: {
              width: 3,
              color: '#3b82f6'
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
  
  // Use ResizeObserver for better responsiveness
  const resizeObserver = new ResizeObserver(() => {
    chartInstance?.resize()
  })
  resizeObserver.observe(chartRef.value)
}

// ... (keep handleResize if needed or rely on observer)

watch(() => props.dimensionScores, () => {
  chartInstance?.setOption(getOption())
}, { deep: true })

onMounted(() => {
  nextTick(() => {
    initChart()
  })
})

onUnmounted(() => {
  chartInstance?.dispose()
})
</script>

<style scoped>
.radar-chart {
  width: 100%;
  height: 320px;
}
</style>
