<template>
  <!-- 定向版年度报告/纪念册：完整 payload（封面姓名/头像），仅适合发给对方 -->
  <ReportLong :payload="payload" audience="intimate" />
</template>

<script setup lang="ts">
import ReportLong from './ReportLong.vue'
import type { IntimateReportPayload } from '../registry'

defineProps<{ payload: IntimateReportPayload }>()
</script>
