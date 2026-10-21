# 前端视觉系统速查（墨痕暖白）

2026-10 全站视觉重做的规范速查。令牌唯一来源是 `frontend/src/styles/theme.css` 的 `:root`；本文是导览，色值以 theme.css 为准。改任何样式前先过一遍本文；`tests/tokens.smoke.test.mjs` 机器守门（未定义令牌 / 别名回潮 / 元素选择器皮肤 / 海报区引变量）。

## 色彩令牌

| 令牌 | 值 | 用途 |
|---|---|---|
| `--ct-bg-app` | `#FAF9F7` | 画布：暖纸底 |
| `--ct-bg-card` | `#FFFFFF` | 卡面 |
| `--ct-bg-sunken` / `--ct-bg-hover` | `#F3F1ED` | 沉底区 / 通用 hover 底 |
| `--ct-color-primary` | `#5A4BC4` | 主色：墨紫 |
| `--ct-color-primary-hover` | `#4A3DB0` | 主色 hover |
| `--ct-color-primary-tint` | `#EEEBFA` | 主色淡底（徽标/选中态底） |
| `--ct-color-primary-muted` | `rgba(90,75,196,.08)` | 极淡主色底（hover 过渡） |
| `--ct-color-primary-subtle` | `rgba(90,75,196,.12)` | 淡主色底 |
| `--ct-color-success` / `-tint` | `#2FA39A` / `#E7F4F2` | 青绿（激活/正向） |
| `--ct-color-warning` / `-tint` | `#E0A458` / `#FAF0E1` | 琥珀（提醒/中间态） |
| `--ct-color-error` / `-tint` | `#E8656F` / `#FDEEEE` | 珊瑚（错误/负向） |
| `--ct-color-info` | = primary | info 不单设色 |
| `--ct-border-color` / `-hover` | `#E9E5DF` / `#DCD6CC` | 发丝线（hover 仅语义处） |
| `--ct-text-primary/secondary/tertiary` | `#1B1924` / `#5A5566` / `#9B95A5` | 三级墨字 |

圆角四档 `--ct-radius-sm/md/lg/full` = 6 / 10 / 14 / 999；阴影三档 `--ct-shadow-sm/md/lg` 暖调低透明；过渡 `--ct-transition-fast/normal`。数据色板与热力色带在 `components/charts/chartTheme.ts`（`CHART_PALETTE` 墨紫+珊瑚+青绿+琥珀+石板，`HEAT_RAMP` 墨紫 5 步），ECharts 一律接它。

## 确立惯用语（不自造变体）

- **状态徽标**：tint 底 + 语义色字（`background: var(--ct-color-success-tint); color: var(--ct-color-success)`）。
- **输入焦点**：`border-color: var(--ct-color-primary)` + `box-shadow: 0 0 0 3px var(--ct-color-primary-tint)`。
- **分段器**：凹槽 `color-mix(in srgb, var(--ct-text-primary) 7%, transparent)` 底 + 激活白色胶囊 + primary 字 + `--ct-shadow-sm`。
- **开关 ON**：primary 墨紫（不是绿）；knob 白。
- **hover**：只变底色/边色，不上浮、无彩色投影；按钮 hover 建议 `:not(:disabled)` 守卫。
- **零渐变、零彩色投影**：全站没有 linear-gradient 装饰（poster 海报模板除外）。

## 裸 hex 白名单（仅此四类）

1. **微信拟物与品牌绿**：聊天还原窗（`#ededed` 窗底、`#95ec69` 我方气泡、`#07c160` 品牌绿、引用灰 `#64748b/#475569` 等）——RagFactDialog 聊天窗、FloatingPanel wechat 通道、CtDialog 微信引导。
2. **script 内数据色板**：chartTheme、词云 palette、Analytics 热力 legend（与 HEAT_RAMP 同源）。
3. **可访问性深字**：tint 底上主色对比不足时的加深字（如 warning-tint 底上 `#8F5B14`）。
4. **poster 海报群**：`components/deep/poster/` 整区豁免——html2canvas 对 CSS 变量支持不稳，不引任何 `var(--ct`，模板节点不挂 panels.css 类。

## 架构纪律

- **三层样式**：`theme.css`（令牌+全局 reset，button 元素选择器只剩 `font: inherit; cursor: pointer` 中性 reset）→ `panels.css`（`.panel`/`.ct-modal-overlay`/`.ct-modal-dialog`/`.btn` 卡片与弹窗解剖）→ 组件 scoped（只写布局与私有小件，卡片/按钮/弹窗 chrome 用全局类不自写）。
- **历史别名已清零**：`--ct-bg-secondary`、`--ct-text-muted`、`--ct-color-primary-light` 等 23 个旧名已删除，用规范名；冒烟测试对回潮直接红。
- **!important 全库仅 3 处合法存量**（theme.css reduced-motion ×2、WordEvolutionPanel 行内网格覆盖 ×1），新代码零配额。
- **poster 分工**：公开/自我版经 `sanitizeForPublic`/`sanitizeForSelf` 投影，类型上拿不到敏感字段。
