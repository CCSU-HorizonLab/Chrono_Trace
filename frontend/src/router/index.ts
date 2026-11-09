import { createRouter, createWebHashHistory } from 'vue-router'

// 关键修复：路由组件必须是裸 () => import()（返回 Promise）——Vue Router
// 对 defineAsyncComponent 包装有明确警告，且 dev 下导航解析不可靠：
// 组件 chunk 已加载但视图停在旧页（实测同文档 hash 导航可复现）。
// loading/error 兜底组件不进路由层（router 不支持），页面级加载态由
// 各视图自持；vite 依赖分析要求静态字符串的动态 import。
function lazy(loader: () => Promise<any>) {
  return () => loader()
}

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    // 脉搏页 = 新首页（重设计批1）：一屏回答「我们现在怎么样」；数据导入挪至 /import
    { path: '/', component: lazy(() => import('@/views/Pulse.vue')) },
    // 时光页（重设计批2）：一条滚动时间轴的叙事——章节骨架 + 情绪/词云/里程碑 + 深钻折叠
    { path: '/timeline', component: lazy(() => import('@/views/Timeline.vue')) },
    // 画像页（重设计批6）：镜像双栏——TA 画像/大五/专属梗词典 ↔ 我的画像/镜像对照，底部海报工坊
    { path: '/persona', component: lazy(() => import('@/views/Persona.vue')) },
    // 分身对话页（重设计批7）：画像页入口 → 全屏对话（画像+语气采样+记忆的 TA 模拟）
    { path: '/persona/avatar', component: lazy(() => import('@/views/PersonaAvatar.vue')) },
    // 智囊页（重设计批4）：对话式统一 AI——问答/陪练/实时三模式
    { path: '/copilot', component: lazy(() => import('@/views/Copilot.vue')) },
    // 数据导入已收进设置抽屉（导航收敛批2）、设置不再是路由页；/import /settings 已删除
    { path: '/analytics', component: lazy(() => import('@/views/Analytics.vue')) },
    { path: '/floating', component: lazy(() => import('@/views/FloatingPanel.vue')) }
  ]
})

export default router
