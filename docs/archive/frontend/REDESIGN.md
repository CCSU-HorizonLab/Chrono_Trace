# Chrono Trace 前端重新设计说明

## 概述

本次重新设计为 Chrono Trace 项目带来了现代化的用户界面，提供了更好的用户体验和数据可视化效果。

## 新增功能

### 1. 数据仪表板 (`/dashboard`)

**文件**: `frontend/src/views/Dashboard.vue`

**功能**:
- 📊 整体统计卡片：总联系人、总消息数、活跃会话、互动天数
- 🔥 最活跃联系人排行榜（Top 10）
- 🔍 快速筛选功能
- 📈 最近活动时间线
- ⚡ 实时数据刷新

**特点**:
- 渐变色统计卡片，支持悬停动画
- 骨架屏加载状态
- 一键跳转到详细分析

**组件**:
- `frontend/src/components/dashboard/StatCard.vue` - 统计卡片组件

---

### 2. 联系人管理页面 (`/contacts`)

**文件**: `frontend/src/views/Contacts.vue`

**功能**:
- 🔍 实时搜索（支持昵称、备注、微信号）
- 📊 多维度排序（消息数、最近互动、名称）
- 🎯 智能筛选（活跃/中等/较少）
- 👁️ 双视图模式（网格/列表）
- 📄 分页加载

**特点**:
- 搜索防抖优化
- 分页导航（自动计算可见页码）
- 骨架屏加载
- 一键跳转到详细分析

---

### 3. 交互式时间线组件

**文件**: `frontend/src/components/timeline/ConversationTimeline.vue`

**功能**:
- 📅 三种视图模式：
  - **按日期**: 按天分组显示会话
  - **按会话**: 以会话为单位展示
  - **统计**: 数据统计和图表
- 💬 可展开/折叠的会话详情
- 📊 简单图表展示每日会话数量

**特点**:
- 支持长列表性能优化
- 响应式布局
- 消息气泡区分发送者

**统计指标**:
- 总会话数、总消息数
- 平均会话时长
- 最活跃时段

---

### 4. 主题切换功能

**文件**:
- `frontend/src/composables/useTheme.ts` - 主题管理 Composable
- `frontend/src/components/base/ThemeToggle.vue` - 主题切换按钮

**功能**:
- 🌓 深色/浅色模式切换
- 💾 自动保存用户偏好
- 🎨 平滑过渡动画

**使用方法**:
```vue
<script setup>
import { useTheme } from '@/composables/useTheme'

const { theme, toggleTheme, setTheme, isDark } = useTheme()
</script>

<template>
  <button @click="toggleTheme">
    {{ isDark() ? '浅色' : '深色' }}
  </button>
</template>
```

---

## 技术实现

### 组件化设计

所有新页面都采用组件化设计：
- ✅ 单一职责原则
- ✅ 可复用性
- ✅ TypeScript 类型支持
- ✅ 响应式布局

### 响应式设计

所有新页面都支持移动端适配：
- 📱 移动端 (< 768px)
- 📱 平板端 (768px - 1024px)
- 🖥️ 桌面端 (> 1024px)

**媒体查询示例**:
```css
@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
```

### 性能优化

1. **虚拟滚动**: 联系人列表采用分页加载
2. **懒加载**: 路由级别的代码分割
3. **防抖**: 搜索输入防抖
4. **骨架屏**: 提升感知性能

---

## 路由结构

```typescript
{
  path: '/dashboard',        // 数据仪表板
  path: '/contacts',         // 联系人管理
  path: '/analytics',        // 详细分析（已有）
  path: '/suggestions',      // AI建议（已有）
  path: '/settings',         // 设置（已有）
}
```

---

## 导航菜单更新

侧边栏菜单现在包含：
1. 首页 - 数据导入
2. **数据概览** ⭐ 新增
3. **联系人** ⭐ 新增
4. 详细分析
5. AI建议
6. 设置（含主题切换）

---

## API 接口需求

### Dashboard 页面

```typescript
// 获取仪表板统计数据
api.get_dashboard_stats(): Promise<{
  ok: boolean
  stats?: {
    totalContacts: number
    totalMessages: number
    activeConversations: number
    activeDays: number
    // ... 其他统计
  }
}>
```

### Contacts 页面

使用现有的 `api.get_conversation_list()` 接口。

### Timeline 组件

需要后端提供会话数据：

```typescript
interface Session {
  id: number
  start_time: string
  end_time: string
  duration: number
  message_count: number
  messages: Message[]
}

interface Message {
  id: number
  sender_name: string
  content: string
  create_time: string
  is_me: boolean
}
```

---

## 样式系统

### CSS 变量

```css
:root {
  --ct-color-primary: rgb(80, 84, 114);
  --ct-color-accent: rgb(181, 172, 212);
  --ct-bg: #F7F7FA;
  --ct-text: #1F2430;
  --ct-radius: 12px;
  --ct-shadow: 0 1px 2px rgba(0,0,0,0.04);
}

.dark-theme {
  --ct-color-primary: rgb(139, 92, 246);
  --ct-bg: #111827;
  --ct-text: #F9FAFB;
}
```

### 使用示例

```css
.my-component {
  background: var(--ct-bg);
  color: var(--ct-text);
  border-radius: var(--ct-radius);
  box-shadow: var(--ct-shadow);
}
```

---

## 浏览器兼容性

- ✅ Chrome 90+
- ✅ Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+

---

## 开发指南

### 本地运行

```bash
cd frontend
npm install
npm run dev
```

### 构建生产版本

```bash
npm run build
```

---

## 未来计划

- [ ] 添加数据导出功能（PDF/Excel）
- [ ] 实现更复杂的图表交互
- [ ] 添加用户标签系统
- [ ] 支持自定义仪表板布局
- [ ] 添加通知中心
- [ ] 实现数据对比功能

---

## 贡献者

本设计由 AI 辅助完成，遵循 Vue 3 最佳实践。

**最后更新**: 2026-01-05
