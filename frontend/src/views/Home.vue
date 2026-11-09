<template>
  <section class="home-page">
    <!-- 数据页薄壳：导入管线已抽为 ImportPanel（首次引导向导与设置抽屉共用） -->
    <ImportPanel />
  </section>
</template>

<script setup lang="ts">
import ImportPanel from '@/components/data/ImportPanel.vue'
</script>

<style scoped>
.home-page {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
</style>
