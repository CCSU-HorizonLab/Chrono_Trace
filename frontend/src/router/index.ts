import { createRouter, createWebHashHistory } from 'vue-router'
import { defineAsyncComponent, h } from 'vue'

const Loading = {
  name: 'RouteLoading',
  render() { return h('div', { style: 'padding:16px;color:#666' }, '正在加载…') }
}

const ErrorComp = {
  name: 'RouteError',
  props: { error: Object, retry: Function },
  setup(props: any) {
    return () => h('div', { style: 'padding:16px;color:#b00020;display:flex;gap:8px;align-items:center' }, [
      h('span', '页面加载失败'),
      h('button', { class: 'ct-btn', onClick: props.retry }, '重试')
    ])
  }
}

// 关键修复：不要使用 @vite-ignore 的字符串路径；改为直接传入静态字符串的动态 import，让 Vite 进行依赖分析与打包。
function lazy(loader: () => Promise<any>) {
  return defineAsyncComponent({
    loader,
    loadingComponent: Loading,
    errorComponent: ErrorComp,
    delay: 200,
    timeout: 15000,
    onError(error, retry, fail, attempts) {
      if (/fetch|network|timeout/i.test(String(error)) && attempts <= 2) retry()
      else fail()
    }
  })
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
    // 智囊页（重设计批4）：对话式统一 AI——问答/陪练/实时三模式
    { path: '/copilot', component: lazy(() => import('@/views/Copilot.vue')) },
    { path: '/import', component: lazy(() => import('@/views/Home.vue')) },
    { path: '/analytics', component: lazy(() => import('@/views/Analytics.vue')) },
    { path: '/settings', component: lazy(() => import('@/views/Settings.vue')) },
    { path: '/floating', component: lazy(() => import('@/views/FloatingPanel.vue')) }
  ]
})

export default router
