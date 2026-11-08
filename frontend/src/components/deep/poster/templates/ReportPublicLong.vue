<template>
  <!-- 公开版年度报告/纪念册：经 sanitizeReportForPublic 投影消费，
       类型上拿不到 contact（姓名/头像）——与海报公开版同一红线 -->
  <ReportLong :payload="sanitized" audience="public" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ReportLong from './ReportLong.vue'
import { sanitizeReportForPublic, type IntimateReportPayload } from '../registry'

const props = defineProps<{ payload: IntimateReportPayload }>()
const sanitized = computed(() => sanitizeReportForPublic(props.payload))
</script>
