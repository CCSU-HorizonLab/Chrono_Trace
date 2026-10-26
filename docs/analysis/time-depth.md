# 时光深度（Time Depth）：时间窗长期演变分析 + 分享海报

> 方案定稿：2026-10-18（产品调研与决策过程已并入本文口径）；
> 本文只记录**口径、版本与责任边界**——改代码前先读这里。

## 功能概览

Analytics 页签「时光深度」，**单聊专属**（群聊无双方情感演变语义，
切群聊自动回退关系洞察）。页签顶部吸顶工具条：面板锚点导航 + 我/TA
实体图例（C4 起无分段选择器——演变四面板统一按章节切，见下）；六面板
纵向长滚（滚动祖先即页签容器）。日期窗只作用于情绪曲线与好感度落点。
在选定时间窗内提供：

1. **关系章节**：统计变点自动分段（消息密度/TA占比/正向率/回复时延），
   周量柱+章节分界线、周级大五分布带五维五行、章节卡（统计+变化点）。
   **全会话口径**（不受时间窗影响），自取数据不依赖 deep payload。
   面板头部「全量摘要」入口跑摘要金字塔任务（月摘要→章节归并，LLM 增量
   缓存），产物注入画像（`profile-window.md` v4 块）并显示在章节卡
   （摘要叙事+阶段徽标，观察叙事措辞）。
2. **双方情绪曲线**：分桶（周/月/年）聚合 sentiment_cache，双方/我/TA 视角或
   三线同显，滚动窗口加权平滑（默认近 3 桶），消极时段浅红着色、好感度历史
   落点（菱形+虚线）叠加；底部分侧互动柱（我紫/TA 琥珀的全量计数，不依赖
   情感缓存）。
3. **词云演变**：**按关系章节边界切段**（全会话，C4 统一分段语义），双方/我/TA
   三视角；重点词排行流动图（bump）+ 分段词云联动高亮（选词口径见下节）。
   1 章会话诚实降级：词云照给、提示无章间对比可看。
4. **大五人格演变**：与词云共用章节分段，每段一张紧凑雷达小多图（我/TA 双色
   叠加）；本地统计层按段免费演变，每段可选 AI 增强（±15 有界校正）。
5. **里程碑时间线**：首条消息、消息量关口、最长沉默期、情绪拐点 + 章节分界
   栏（≥2 章时穿插「第 N 章」通栏标记）。**全会话口径**（不受日期窗影响）。
6. **画像演变**：**按关系章节边界切段**竖排时间线全段卡（左缘竖线+段间↓，
   段头「第 N 章」+时间区间），见 `docs/analysis/profile-window.md`。
   1 章会话隐藏生成入口并提示无演变可对比。
7. **大五人格印象（全会话档）+ 分享海报**：已随拆页移至「TA 画像」页签，见下两节。

## 版本常量与 bump 规则

| 常量 | 位置 | 当前值 | 何时 +1 |
|---|---|---|---|
| `DEEP_ANALYSIS_VERSION` | `deep_analysis_service.py` | 5 | 桶口径（分桶表达式）或序列点位结构变化。序列实时计算无缓存，版本主要约束前端兼容判断与文档口径记录。v2：词云演变 `halves`→`segments`（2~6 段可配，默认 4）；v3：桶点补 `userMsgCount`/`otherMsgCount` 分侧全量计数、payload 增 `big5_evolution`；v4：词面口径变更（pos 白名单过滤 + 停用词两轮扩表，词云/群摘要词表不兼容）；v5：分段语义换轨——词云/大五/里程碑/画像演变统一按 `chapter_spans` 章节边界切（payload 增 `chapter_spans`/`chapters_ok`，`word_segments` 参数删除，日期窗只剩情绪曲线/好感度落点/海报） |
| `BIG5_PROMPT_VERSION` | `personality_impression_service.py` | 1 | 大五 prompt 或指标权重结构性变化。旧行自动失效重算（`big5_impressions` 表按版本查询，对齐 `CALIBER_VERSION` 惯例） |
| `CHAPTERS_VERSION` | `relationship_chapters.py` | 1 | 章节检测口径变化（特征集/惩罚系数/吸附半径/留白阈值）。纯统计无落库缓存，版本约束前端兼容判断与口径记录（方案与分期见 `goals/persona-chapters-goal.md`） |

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
- **分侧全量计数**（v3）：`_bucketed_message_counts` GROUP BY 加 is_sender，
  桶点出 `userMsgCount`/`otherMsgCount`（不依赖 sentiment_cache，两侧之和恒等
  `msgCount`）——前端分侧互动柱的数据源；缺覆盖桶分侧同样全量。
- **滑动平均权重保持 cachedCount/userCount/otherCount 不改**：平滑对象是
  分数，权重应等于分数背后的样本量（已缓存消息数）；换全量计数会让低覆盖桶
  权重虚高。全量互动量的展示由分侧双色柱承担，两套数字分工不混用。
- 拐点门槛：参与涨跌幅判定的桶需 `msgCount ≥ 30` 且 `coverage ≥ 0.8`。

### 词云演变（双口径陷阱）

`message_preprocessed` 只有跑过分析的会话有行。规则：**整个模块按清洗覆盖率
二选一**（≥0.9 用清洗缓存文本，否则统一用原始 content），绝不各段混用。
分段自 v5 起 = **`relationship_chapters.chapter_spans` 章节边界**（全会话，
段 from_ts/to_ts 为段内首末消息时间戳，相邻章允许有缝；检测不可用降级
全会话单段，无文本消息返回空段列表）；每段上限 15000 条，超出等距抽样并
标记 `truncated`；空段列表时返回 `caliber:"none"` 诚实降级。v4 之前的
`split_window_evenly` 均分切段已删除——均分把真转折劈成两半，演变叙事的
段就是行为变点切出的自然章。

**前端 bump 流动图选词口径**：各段 words 数组顺序即排名（后端 most_common
序）；`weight` 是段内归一化 1-100、**跨段不可比，选词一律用排名**。取
「≥2 段出现且排名有变化」按**排名方差** top 8——泛高频词各段恒居前列、
方差趋 0 自然沉底，回答的是「什么词起来了、什么沉下去了」。点击折线或
词云中的词双向联动）。词面干净度两层过滤（`stopwords.py`，词云与群统计
共用）：**词性白名单**（jieba.posseg 只留实词词性）结构性消灭代词（我们/
他们/这儿）、时间指示词（上午/下午/周末）、副词整类——标准停用词表不收
时间词（新闻语域里是内容词），白名单比整表搬运对症；**停用词表**只兜词性
挡不住的泛聊天空转实词（东西/时候/不能/处理）。情感实词（好/喜欢）与
日程词（吃饭/上班）是信号两层都不收——docstring 红线。

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

### 时间窗档位（big5_impressions 表 v2）

- 唯一键加 `window_kind`（'full'=全会话，存 0/0 保确定性）+
  `window_from`/`window_to`（custom 档秒级闭区间）；full 与 custom 互不污染。
- 旧表（PRAGMA 探查缺 `window_kind` 列）DROP 重建不迁移：本地层重算免费，
  增强层需重新点按钮（KISS，沿画像三表先例）。
- 窗口化全链：`get_impressions`/`_local_base`/`enhance`/`_fetch_conversation_rows`/
  `_collect_raw_indicators`（含情感/正向回应/分享密度三查询）/
  `_sample_conversation` 全部穿窗；`EngagementMetricsService.compute` 加可选
  from_ts/to_ts（默认 None 时 SQL 与历史逐字节一致——好感度六维链路的
  回归守卫，`tests/test_engagement_metrics.py` 锁死）。
- **bridge 逐段增强取数用秒级 from_ts/to_ts，须与段边界完全一致**：缓存键含
  窗维，日期粒度换算会造出不同键，增强结果重载即丢。单飞/取消键同样含窗维
  （同会话不同窗可并行）。

### 大五演变（时光深度面板）

- deep payload 键 `big5_evolution = {segments, min_messages, series:
  [{from_ts, to_ts, me, other, error?}]}`；**分段 = payload `chapter_spans`**
  （章节边界，与词云同源）；每段每侧不足 `BIG5_MIN_MESSAGES`(30) →
  None 标样本不足，短窗空段标 error 降级不炸 payload。
- 首开逐段现算 local 并落 custom 缓存（30 天 TTL 缓解二次延迟）。
- 交互：每段「AI 增强本段」+ 头部「全部增强」（顺序逐段、已增强跳过），
  结果覆写回 series[i]；already_running 显 hint。
- 与 TA 画像页静态 `BigFivePanel`（全会话 full 档）**分工不共用组件**：
  `big5Shared.ts` 只共享 DIM_ORDER 与双方色值（我 #7c4dff / TA #d97706）。
- 选型：**分段雷达小多图**（每段一张紧凑雷达，我/TA 双色叠加，`BigFiveRadar`
  compact 档 220px）——形状轮廓对比承担「怎么变」的叙事，卡头只留章号 +
  时间区间 + 状态位（已增强徽标/AI 增强按钮/样本不足/错误）。v1 的 5 维折线
  小倍数已弃（信息密度低、与下方分段条割裂）；当初弃雷达的理由（跨 4~6 张
  认知成本高）由 compact 档小尺寸、卡头状态位与章节分段来补偿，趋势 ↑↓
  文案删除。段序自左向右即时间序，样本不足段不画雷达只在卡头降级标注。

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
- **海报 payload 含 story 纯加性字段**：`{milestones, chemistry}`（chemistry =
  late_night/peak_day/reply_stats/initiator，逐字段独立降级 None）；
  核心分镜（开场/里程碑/深夜/峰值日）零依赖分析产物，未分析库也能出故事。

## 关系章节（时光深度首位面板，C1 纯统计层）

均分切段把真转折劈成两半、rolling 窗采样丢掉长会话的头部语料——章节面板
换时间原语：按行为变点切「自然段落」+ 周级大五分布带。调研依据与 C2-C4
分期见 `goals/persona-chapters-goal.md`。

- **章节检测**（`relationship_chapters.detect_chapters`，纯函数确定性）：
  周粒度四信号——消息密度 `log1p(周文本量)`、TA 占比、正向情绪率（双侧
  合并 sentiment_cache）、回复时延 `log1p(分钟)`（response_times 剔异常、
  封顶 24h）。逐列 z 归一（零方差列剔除）后 DP 精确最优分段，段数由
  「SSE + 惩罚×(段数-1)」择优，惩罚 = 2.0×特征维数×ln(周数)——单特征约
  1.5σ 以上的均值漂移才切一刀，宁缺毋滥。约束：最短 2 周、至多 8 段。
- **边界吸附**：切出的边界若 ±7 天内有关联里程碑（首条/消息量关口/最长
  沉默，复用 deep_analysis 口径），展示时间戳吸附到里程碑；周统计不动。
- **变化归因**：相邻章节各特征均值差按全序列 σ 折算，|Δz| ≥ 0.5 才报
  （label+方向，中性措辞——升降不预设好坏，不做关系诊断）。
- **周级大五分布带**：逐周单侧采集语言风格指标（与大五基础层同口径：
  daily_avg/icebreak_ratio/emoji_exclaim/daily_cv/topic_continuation/
  情感三样/late_night/empathy_density/词汇多样性/分享密度），经
  `big5_proxies` 锚点插值+缺席重归一合成五维。**周内单侧文本 < 10 条该侧
  该周记 None（诚实留白）**；jieba 词指标每侧每周抽样 ≤200 条。分布带只做
  相对演变叙事，不做绝对测评解读（Fleeson：人格是状态的密度分布）。
- **周桶锚点**：本地时区周一 00:00；首末之间的空周补零保留（冷却期本身
  是信号）。`_aggregate_weeks` 的周桶两侧必须各自独立（工厂函数建桶——
  dict 浅拷贝会让双侧共享 texts 列表，已有测试锁死）。
- 全会话口径（不收日期窗）；文本总量 < 40 条返回 `insufficient_data`。
  纯统计零 LLM 无落库缓存，同库重跑结果一致（服务实例内按
  「消息数+最新时间戳+版本」指纹缓存，新消息自动失效——13 万条整算
  ~7s 不该每次切页签重付）。
- **`chapter_spans(conversation_id)`（C4 统一分段源）**：把章节检测产物转成
  `{ok, spans: [(from_ts, to_ts) 闭区间...], full_from, full_to}`，供词云/
  大五/画像演变/里程碑分界栏共用。段边界 = 段内首末消息时间戳（里程碑吸附
  后相邻章可共享边界点，章间允许有缝）；检测不可用（<40 条/缺表抛错被吞）
  降级全会话单段，无文本消息返回空 spans。进程级共享实例
  `get_shared_chapter_service()` 让跨面板调用方共享指纹缓存。

### 章节摘要金字塔（`chapter_summaries.py`，C2/C3）

月摘要（`chapter_month_summaries`，本地时区 'YYYY-MM'，单月条数 3000/
字符 24k 双预算等距抽稀）→ 章节归并（`chapter_summaries`，指纹 =
`v{CHAPTERS_VERSION}:{from}-{to}`，边界漂移/升版即失明重算，月摘要
不浪费）。任务三件套仿 sentiment_backfill：全局单飞（LLM 串行）、按
任务独立取消事件、取消保留已落库月、增量跳过已就绪月。远程模型逐条
过 PrivacyRedactor（全月原文暴露面大于画像窗口样本），构造失败整任务
阻断（fail-closed）；单条脱敏异常丢条继续。版本分层
`MONTHLY_SUMMARY_VERSION` / `CHAPTER_SUMMARY_VERSION`（月与章互不牵连
重算）。C3 叙事层：相邻章过渡卡（`chapter_transitions`，指纹 = 前后章
指纹拼接；evidence 逐字子串校验，回溯不到输入叙事即丢弃）+ 全局弧线
（`chapter_arcs`，全部章摘要就绪才生成，转折点带「第N章→第M章」）。
消费方：画像【关系章节摘要】块（rolling 全部章 / custom 窗口交叠章）
+ 章节面板（章卡 summary/phase、过渡卡穿插、弧线块、「最初→现在」hero）。

## 分享海报

前端 `html2canvas`（唯一为此新增的前端依赖）合成竖版 720px 长图，
`save_share_image` 落盘 `chrono_trace_export`（PNG magic 校验、≤20MB、
文件名白名单化）。

三模板统一为**故事分镜叙事**（Spotify Wrapped 式：开场 → 编号幕（大数字/
时间线/默契数字格/作息热力格/年历/细节格/曲线/词云/雷达）→ 称号幕（无序号）→ 落款），
公共幕骨架在 `poster/sections/`（StorySection/StoryBigNumber/StoryTimeline/StoryStatGrid/
StoryHeatGrid/StoryCalendar，palette 纯色 token 经 props 传入），受众差异内容
（双人头像/金句卡/单侧词云）留各模板。称号规则是前端纯函数 `poster/badges.ts`
（主称号 8 规则按序首中 + 兜底；副称号 `posterSubBadges` 极值触发全列出、
★三档分级；稀有度话术 `posterRarityLines` 全部锚定会话内相对事实——本地
单机无跨用户基准，不编造百分位。文案随受众变，后端下发等于把展示细节塞
payload）。三模板调色板/底渐变/热力色带统一在 `poster/theme.ts`（方卡共用
同一份，防两处漂移）；activity 分镜共用纯函数在 `poster/activityShared.ts`。

除长图外另有**方形称号卡**（`poster/SquareCard.vue`，720×720 → 导出
1440×1440）：主称号+副称号 chips+一条大数字为唯一焦点，朋友圈信息流/
缩略图友好；与长图共用受众投影与称号输入（口径一致），经 PosterStudio
「导出方卡」按钮离屏渲染（固定定位移出视口，display:none 会破坏
html2canvas 克隆）。

### 三模板基调

| 模板 | 基调 | 分镜 |
|---|---|---|
| 定向版（PosterIntimateDuo） | 暗色星夜（#0b1026→#221540，金 #e8c47a） | 双人头像开场 → 大数字 → 时光机 → 默契格 → 作息热力格 → 最热闹的一年（年历）→ 细节格 → 金句（衬线）→ 双人词云 → 雷达 → 称号 |
| 自我版（PosterSelfPortrait） | 暖米（#fdf8f2→#f3e2c8，橘 #d97706） | 「我」头像开场 → 你的大数字 → 日常痕迹格 → 你的作息（我的格）→ 你的 N 年（我的年历）→ 细节格 → 语气曲线（橘线）→ 你的词 → 语言风格（雷达+条形）→ 称号 |
| 公开版（PosterPublicMinimal） | 浅靛（#ffffff→#eef1f7，靛 #4f5d9e，中性措辞） | 开场句 → 大数字 → 时间线 → 默契格（「有人先开口」不指认）→ 两个人的作息（合并格，无日期）→ 细节格 → 曲线 → 词云 → 雷达 → 称号 |

### story 口径（与 _poster_stats 同源）

`message_type=1 AND TRIM(content)!=''`、窗内、本地时区；深夜 = `CAST(strftime
('%H',...,'localtime') AS INTEGER) BETWEEN 0 AND 5`（字符串 BETWEEN 会把
'23' 错配进 0-5 档）；回复中位数无 MEDIAN 用 `LIMIT 2 OFFSET (n-1)/2` 取均值；
reply_stats 三重剔除（is_abnormal=1 / response_time_seconds NULL / 回消息窗外）。

### activity 口径（作息热力格 / 年历 / 衍生判据）

`_poster_activity` 同窗同文本口径，纯加性字段（不 bump `DEEP_ANALYSIS_VERSION`）：

- **grid**：7×24「周几×时辰」计数（SQLite `%w` 周日=0，Python 端换算周一为
  第 0 行），`all`/`me` 分侧 + 各自 max；不含绝对日期，公开版可消费。分档
  阈值（前端）：峰值比例 ≥0.75/0.5/0.3/0.12 → 5~1 档（聊天作息长尾尖峰，
  低档收得紧才不至糊成一片）；
- **calendar**：窗内逐日计数（`DATE(...,'localtime')` 分组），Python 端取
  最活跃年（并列取更早）——「最热闹的一年」；带绝对日期，**公开版投影
  剥离**，自我版映射为 self_count 单侧；
- **insights**：最长连续活跃天数（distinct 日期上 gaps-and-islands：连续
  日期减行号落同锚点，组大小即长度；`self_streak_days` 过滤 `is_sender=1`）
  + 提问数（`？`/`?` LIKE 命中近似，分侧）——副称号（不缺席者/夜行者/
  秒回选手/破冰人/长跑搭档/笔耕不辍）与「没意识到的细节」分镜的判据。

### 脱敏责任边界（模板层硬约束）

三个模板对应三类受众，**公开/自我版在类型层面拿不到敏感字段**
（`sanitizeForPublic` / `sanitizeForSelf` 白名单投影是唯一构造入口），
不靠用户自觉：

| 模板 | 受众 | 可用字段 | 不可见字段 |
|---|---|---|---|
| 公开分享（PosterPublicMinimal） | 朋友圈等公开场景 | 聚合数字、合并情绪曲线、双方大五分数、top 词、story 聚合（无身份统计、**零绝对日期**）、activity 合并作息格+联合判据（周几×时辰与连续天数/提问占比均无日历日期） | 对方姓名/头像/金句原文、story 全部日历日期（里程碑 ts/from_ts/to_ts 与峰值日 date 在投影层剥除——首条消息等里程碑是全会话口径，日期会突破用户所选导出窗）、activity 年历与 me 单侧格 |
| 自我画像（PosterSelfPortrait） | 想了解自己的人 | 我的消息数、我的曲线/词/大五、my_story 单侧切片（late_night_self/reply_self_avg）、my_activity（我的作息格/我的年历——日期属我本人数据可保留，count 已映射 self_count/单侧判据） | 对方一切数据、金句、story 联合口径 |
| 定向发送（PosterIntimateDuo） | 仅对方本人 | 全量（姓名、头像、双方曲线、金句卡、story 全量含日期、activity 全量含年历） | —（导出前强制确认弹窗） |

### 字体

显示字体捆绑 **Smiley Sans（得意黑）Oblique v2.0.1**（OFL-1.1，
`assets/fonts/SmileySans-Oblique.woff2` + `OFL.txt`；OFL 的 Reserved Font
Name 条款=改名再改字体，原样分发只需附带许可），`styles/fonts.css` 声明
`font-display: block`。大数字/幕题/称号用 `'Smiley Sans', 'PingFang SC',
'Microsoft YaHei', sans-serif` 栈；金句用系统衬线 `Georgia, 'Songti SC',
'Noto Serif CJK SC', serif`。GB2312 外字符靠回退栈吸收。

### html2canvas 约束（模板 CSS 纪律）

- 图片必须 base64 data URL（`file://` 会污染画布致导出失败）——头像由后端
  `build_poster_payload` 转 base64，失败返回 null 前端首字母占位；
- 只用纯色 + 简单 linear-gradient；**不用** radial/conic-gradient、
  box-shadow、backdrop-filter（渲染不可靠）；
- 「光感」用 1px 亮色 border 模拟，不用 shadow；rgba() 颜色值可用；
- 导出前 `await document.fonts?.ready`（try/catch 老引擎跳过）——堵住
  「首次切模板即导出烘焙回退字体」的竞态，与 font-display:block 双保险；
- 导出节点不得处于 CSS 动画/transform 中；
- Windows（WebView2）为主验证平台，Linux（Qt WebKit）异常降级提示不阻塞。

## 相关文件

- 后端：`services/analysis/{deep_analysis_service, engagement_metrics,
  sentiment_backfill_service, personality_impression_service, big5_proxies,
  relationship_chapters, chapter_summaries, task_registry}.py`、
  `services/realtime/profile_chapter_digest.py`、`webview/api/deep_analysis.py`（mixin）
- 前端：`components/deep/`（TimeDeepTab 及各面板、RelationshipChaptersPanel、
  Big5EvolutionPanel + big5Shared、PosterStudio、`poster/registry.ts`、
  `poster/badges.ts`、`poster/theme.ts`（三受众调色板/底渐变/热力色带）、
  `poster/activityShared.ts`、`poster/SquareCard.vue`（方形称号卡）、
  `poster/sections/`（分镜骨架：Section/BigNumber/Timeline/StatGrid/HeatGrid/Calendar）、
  三模板、`styles/fonts.css`）、
  `charts/EmotionLineChart.vue`（扩展 perspective/negativeShade/affinityPoints
  与 userMsgCount/otherMsgCount 可选 props，无分侧数回退单柱）
- 测试：`tests/test_deep_analysis.py`、`test_engagement_metrics.py`、
  `test_sentiment_backfill.py`、`test_big5_impression.py`、
  `test_relationship_chapters.py`、`test_chapter_summaries.py`、`test_share_poster_export.py`
