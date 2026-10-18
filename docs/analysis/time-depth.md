# 时光深度（Time Depth）：时间窗长期演变分析 + 分享海报

> 方案定稿：2026-10-18。产品调研与决策过程见 git 历史与 `docs/archive/`；
> 本文只记录**口径、版本与责任边界**——改代码前先读这里。

## 功能概览

Analytics 第六个页签「时光深度」，**单聊专属**（群聊无双方情感演变语义，
切群聊自动回退关系洞察）。在选定时间窗内提供四块：

1. **双方情绪曲线**：分桶（周/月/年）聚合 sentiment_cache，我/TA/双方三视角，
   消极时段浅红着色、好感度历史落点（菱形）叠加。
2. **词云演变**：时间窗均分为 2~6 段（默认 4）对比，双方/我/TA 三视角。
3. **关系阶段叙事**：首条消息、消息量关口、最长沉默期、情绪拐点的时间线。
4. **大五人格印象 + 分享海报**：见下两节。

## 版本常量与 bump 规则

| 常量 | 位置 | 当前值 | 何时 +1 |
|---|---|---|---|
| `DEEP_ANALYSIS_VERSION` | `deep_analysis_service.py` | 2 | 桶口径（分桶表达式）或序列点位结构变化。序列实时计算无缓存，版本主要约束前端兼容判断与文档口径记录。v2：词云演变 `halves`→`segments`（2~6 段可配，默认 4） |
| `BIG5_PROMPT_VERSION` | `personality_impression_service.py` | 1 | 大五 prompt 或指标权重结构性变化。旧行自动失效重算（`big5_impressions` 表按版本查询，对齐 `CALIBER_VERSION` 惯例） |

## 关键口径

### 情绪分桶

- 分桶表达式单点：`analysis_service.sentiment_bucket_expr(bucket)`。
  周桶为 `DATE(ts,'unixepoch','localtime','-6 days','weekday 1')`——直接
  `'weekday N'` 是「下一个周N」语义会漂移，**不要改回简写**。
- 覆盖率合并：`_bucketed_message_counts`（全量文本桶计数）×
  `_bucketed_sentiment`（情感聚合）双查询合并，未覆盖桶 `score=None`、
  `lowConfidence=True`、`msgCount` 仍全量——INNER JOIN 会丢桶，不能用。
- 桶点含每侧已缓存计数 `userCount`/`otherCount`（`_build_sentiment_timeseries`
  加列，与全面分析共用但加键不破坏）——前端情绪曲线滚动窗口加权平滑的权重
  真分母：`近 K 桶滑动均值 = Σ(score×对应侧计数)/Σ计数`，消息多的桶话语权大；
  平滑纯前端派生（默认近 3 桶），计数与低置信底纹保持原桶原值。
- 拐点门槛：参与涨跌幅判定的桶需 `msgCount ≥ 30` 且 `coverage ≥ 0.8`。

### 词云演变（双口径陷阱）

`message_preprocessed` 只有跑过分析的会话有行。规则：**整个模块按清洗覆盖率
二选一**（≥0.9 用清洗缓存文本，否则统一用原始 content），绝不各段混用。
分段由 `split_window_evenly(from, to, segments)` 均分（2~6 段，默认 4；
边界 `b_i = ((n-i)*from + i*to) // n`，N=2 与历史对半公式逐点一致）；
每段上限 15000 条，超出等距抽样并标记 `truncated`；窗口切不出 N 段时返回
空段 + `error`。**画像演变固定对半两段**，与词云共用切窗函数保证同窗同分
（不跟随 N 段——每段是独立 LLM 快照，成本随段数线性涨）。

### 情感补算（sentiment_cache 缺口）

未跑过全面分析的会话在时光深度页先补算逐条情感（ONNX 本地推理，500 条/批），
结果永久缓存、全面分析直接复用。与全面分析**双向互斥**（共用 ONNX 会话）：
`start_sentiment_backfill` 见 affinity 活任务即拒（须查全部历史服务实例——
`analyze_affinity` 每次 reload 重建实例，旧实例任务对最新实例不可见）；
`analyze_affinity` 反向检查。补算自身**全局单飞**（不同会话并发会争抢推理
资源）；取消事件**按任务独立存储**，按 task_id 精确取消。取消保留已写批次，
续跑自动跳过。两侧的「互斥检查 + 任务注册」临界区共用
`webview/api/deep_analysis._ONNX_TASK_LOCK`（放不参与热 reload 的模块），
消除检查-后-注册（TOCTOU）竞态；**终态集合单源于
`services/analysis/task_registry.py`**（running/completed/failed/cancelled），
两侧口径不可各自漂移。

## 大五人格印象（双层架构）

**基础层**（`big5_proxies.py`，纯统计，无 LLM 永远可用）× **增强层**
（LLM 有界校正）。这是「语言风格印象」而非心理测评，UI 必须带免责脚注。

### 指标权重表（锚点插值 + 点数制，缺席指标重归一）

| 维度 | 子指标（权重%） |
|---|---|
| 外向性 | 活跃日均消息量 40 · 主动破冰占比 30 · 表情/感叹/叠词密度 30 |
| 尽责性 | 未回应事件率 50（反向）· 日消息量 CV 30（反向）· 话题延续 20 |
| 神经质 | intensity 方差 40 · 负面占比 30 · 深夜活跃 15 · 撤回率 15 |
| 宜人性 | 正负比 40 · 正向回应率 30 · empathy/soothing 词密度 30 |
| 开放性 | type-token 比 40 · 词频分布熵 30 · 图片/链接分享密度 30 |

改权重表或锚点 = 结构性变化，`BIG5_PROMPT_VERSION` +1。

### 增强层纪律

- **双重钳制**：`final = clamp(clamp(base + adjustment, base ± 15), 0, 100)`；
- **基点永远取 local 层**（`_local_base`），绝不从 llm_enhanced 缓存复合——
  否则重复点击 ±15 逐次叠加漂移；
- **证据子串校验**：`evidence_quote` 必须是（脱敏后）采样语料的子串，
  否则证据置空（分数保留）；
- **脱敏红线**：远程模型必经 `PrivacyRedactor`，脱敏器构造失败 = 整次增强
  阻断（不落任何 `llm_enhanced` 行）；本地 loopback 模型免脱敏；
- **采样等距稀释**：抽样超 12000 字符预算时对抽样序列再等距抽稀，保持
  时间分布（从头截断会让语料偏向早期消息，校正作用于过时画像）；
- **单飞 + 可取消**：bridge 层同会话增强单飞（LLM 请求最长 90s），
  `cancel_big5_impressions` 置取消事件，`should_abort` 走请求尝试边界；
- **海报 payload 不含 milestones**：三模板均不渲染，下发只诱发误用。

## 分享海报

前端 `html2canvas`（唯一为此新增的前端依赖）合成竖版 720px 长图，
`save_share_image` 落盘 `chrono_trace_export`（PNG magic 校验、≤20MB、
文件名白名单化）。

### 脱敏责任边界（模板层硬约束）

三个模板对应三类受众，**公开/自我版在类型层面拿不到敏感字段**
（`sanitizeForPublic` / `sanitizeForSelf` 白名单投影是唯一构造入口），
不靠用户自觉：

| 模板 | 受众 | 可用字段 | 不可见字段 |
|---|---|---|---|
| 公开分享（PosterPublicMinimal） | 朋友圈等公开场景 | 聚合数字、合并情绪曲线、双方大五分数、top 词 | 对方姓名/头像/金句原文 |
| 自我画像（PosterSelfPortrait） | 想了解自己的人 | 我的消息数、我的曲线/词/大五 | 对方一切数据、金句 |
| 定向发送（PosterIntimateDuo） | 仅对方本人 | 全量（姓名、头像、双方曲线、金句卡） | —（导出前强制确认弹窗） |

### html2canvas 约束（模板 CSS 纪律）

- 图片必须 base64 data URL（`file://` 会污染画布致导出失败）——头像由后端
  `build_poster_payload` 转 base64，失败返回 null 前端首字母占位；
- 只用纯色 + 简单 linear-gradient；**不用** radial/conic-gradient、
  box-shadow、backdrop-filter（渲染不可靠）；
- 导出节点不得处于 CSS 动画/transform 中；
- Windows（WebView2）为主验证平台，Linux（Qt WebKit）异常降级提示不阻塞。

## 相关文件

- 后端：`services/analysis/{deep_analysis_service, sentiment_backfill_service,
  personality_impression_service, big5_proxies, task_registry}.py`、
  `webview/api/deep_analysis.py`（mixin，11 个方法）
- 前端：`components/deep/`（TimeDeepTab 及各面板、PosterStudio、
  `poster/registry.ts` 与三模板）、`charts/EmotionLineChart.vue`（扩展
  perspective/negativeShade/affinityPoints 可选 props，默认行为不变）
- 测试：`tests/test_deep_analysis.py`、`test_sentiment_backfill.py`、
  `test_big5_impression.py`、`test_share_poster_export.py`
