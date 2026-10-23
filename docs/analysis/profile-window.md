# 画像时间窗与快照（Profile Window & Snapshots）

> 定稿：2026-10-18。本文只记录**口径、版本与责任边界**——改画像相关代码前先读这里。
> KISS 口径：不做兼容迁移，旧结构直接 DROP 重建（详见各 profiler `_ensure_table`）。

## 功能概览

联系人画像（`contact_profiler.py`）与我的画像（`self_profiler.py`，原「自我克隆」）
是**时间窗画像**：LLM 对指定窗口采样对话的分析，不是全时段结论。

- **rolling 滚动窗**：档位锚定 now（low/medium/high = 7/30/90 天），内容不足向更早
  顺延；每次续期产生新窗口键 → 快照自然累积。
- **长期背景块（v2 起）**：rolling 对长关系只覆盖尾部（窗内采样目标填满即
  不再回看更早——2.5 年 5233 条的会话，90 天窗只罩住 8%），画像会丢掉绝大
  部分历史。`profile_baseline.collect_full_period_baseline`（纯 SQL 零 LLM
  成本）给两 profiler 注入【长期背景】块：全时段跨度/分年消息量/活跃天数/
  深夜比 + **本次窗口覆盖比**。LLM 同时看到「窗口内的他」与「全时段的他」，
  同 affinity 的 caliber='full_period' 先例（结论以窗口为主，长期数字对照演变）。
- **长期记忆事实块（v3 起）**：数字层之外的语义补全——`profile_facts
  .collect_profile_facts` 把 RAG 事实层（全时段、supersede 演变链顶端，
  confidence 优先取 top 24）注入【长期记忆事实】块。事实是增量抽取早就
  落库的，注入零新增 LLM 调用。三条门控：`sensitivity='sensitive'` 排除
  （对齐检索通道的隐私红线）、注入前逐条过 `PrivacyRedactor`（无连接
  实例的规则替换，手机号/证件号/卡号/地址换占位符，脱敏异常丢条
  fail-closed——事实层是**全时段**数据，明文注入会把暴露面从窗口期
  扩到全部历史）、`rag_enabled` 关闭即不注入（关记忆的语义
  是记忆内容不参与任何远程交互）；`rag_facts` 表缺失（未跑过 RAG 的库）
  静默降级不注入。与长期背景块分工：背景给**数字**（量的分布），事实给
  **语义**（沉淀的具体记忆），窗口样本给**细节**（近端语气）。
- **关系章节摘要块（v4 起）**：`profile_chapter_digest.collect_chapter_digest`
  把章节摘要金字塔产物（`chapter_summaries` 任务：月摘要→章节归并，
  口径见 `goals/persona-chapters-goal.md`）注入【关系章节摘要】块。
  rolling 注入全部章节（全时段语义坐标，与长期背景同语义），custom
  只注入与窗口交叠的章（画像演变各段聚焦自身时段）。注入前逐条过
  PrivacyRedactor（全时段语义层，纪律同事实块）；表缺失静默降级。
  四块分工：背景给**数字**、事实给**结构化记忆**、章节摘要给**叙事**、
  窗口样本给**细节**。
- **custom 指定窗**：`generate_profile(..., from_ts, to_ts)` 闭区间硬边界，**不顺延**
  （顺延会篡改用户指定窗口的语义）；防呆：非正/起点≥终点/终点晚于 now+1 天/
  窗内无文本消息均直接拒绝。**跨度不设上限**——按调用方切分的时窗如实生成
  （采样量按档位固定，窗口越长画像粒度越粗，由 UI 展示窗口标注，不做硬拦）。
- **origin 来源列（v5 起）**：`generate_profile(..., origin='')` 透传落库——
  滚动续期/手动指定窗为 `''`，画像演变各段为 `'evolution'`。快照列表靠该列
  显示「演变段」徽标，与滚动/指定窗区分来源，不靠窗口形状猜。
- **窗口徽标惯用语三件套（读时组装）**：窗口档位 label（rolling「最近 N 天」/
  custom「起 ~ 止」）+ 覆盖比 + 新鲜度。覆盖比 `_window_coverage`
  （`webview/api/profile.py`，读时 SQL 重算 `窗口文本消息数/全会话文本消息数`，
  3 位小数，查不到返回 None 前端隐藏）——长关系上「最近 30 天」可能只罩住
  个位数百分比，不披露就冒充全貌；新鲜度由前端 `toAgoLabel`
  （`utils/datetime.ts`，N 天前/N 个月前）从 created_at 换算。

## 数据模型（快照结构 v1）

`contact_profiles` / `self_profiles` 单表多快照，DDL 由各 profiler `_ensure_table`
维护（不在 schema.sql），唯一键：

```
UNIQUE(account_wxid, display_name, window_kind, window_from, window_to)
```

- 同窗重试 `INSERT OR REPLACE` 覆盖不堆积；不同窗各自存档。
- **TTL 只作用 rolling**（`expires_at = created_at + 7 天`）；custom 快照是存档品，
  免 TTL（占位一年），仅由数量上限按窗口分组裁剪：rolling `PROFILE_SNAPSHOT_KEEP = 8`、
  custom `PROFILE_SNAPSHOT_KEEP_CUSTOM = 24`（对齐 `list_snapshots` 的 24 条回看上限）。
- **读取语义**：`get_profile` 只取 `window_kind='rolling' ORDER BY created_at DESC,
  id DESC LIMIT 1`（消费方零改动）；custom 历史快照走 `list_snapshots`（24 条上限）。
- **续期保档位**：`generation_context.renew_profiles_in_background` 先读当前 rolling
  行的 `budget_level` 再按原档位续期（读不到默认 medium）。
- **relationship_policy._load_profile_cache 必须带 `window_kind='rolling'` 过滤**——
  custom 快照不得污染实时建议链路（测试锁死）。
- **结构版本随行落库并在所有读取处过滤**（`schema_version` 列，同 big5 的
  prompt_version 机制）：画像 System Prompt 或统计口径变化时
  `PROFILE_SNAPSHOT_SCHEMA` +1，旧口径快照自然失明（get_profile /
  list_snapshots / 演变 `_load_snapshot` / relationship_policy 全部带过滤），
  不再以「历史快照」徽标混入新口径结果；缺列旧表由 `_ensure_table` DROP 重建。

## 特征同窗化的诚实边界

`_collect_features(conn, conversation_id, from_ts, to_ts)` 窗口内统计：

| 特征 | 来源 | 窗口化方式 |
|---|---|---|
| initiative | `sessions` 按 `start_time` | sessions 空则该特征**缺席**（不回退 initiative_stats 冒充窗口口径） |
| response_time | `response_times` JOIN `messages.timestamp` | JOIN 过滤 |
| word_counts | `messages` GROUP BY is_sender | 窗口内推导，ratio=对方/我（我方零字为 None） |
| user_msg_style（仅 self） | `messages` | timestamp 过滤 |
| affinity | `affinity_scores` | **无法窗口化**：保留注入但 `caliber: 'full_period'` 标注，prompt 标注「全时段评分，仅供背景参考」 |
| full_period_baseline | `messages` 全时段 | 不窗口化（这就是它的意义）：【长期背景】块注入，见功能概览 |

prompt【基础信息】块带样本时间范围行（rolling 注明顺延，custom 注明指定窗）。

## 画像演变（ProfileEvolutionService）

切窗自 v5 起 = **`relationship_chapters.chapter_spans` 章节边界**（C4 统一
分段语义，与词云/大五/里程碑同源；均分切段的 `split_window_evenly` 已删）：
每段落为 custom 快照（`origin='evolution'`），标签「第 N 章」；1 章会话
前端隐藏生成入口并提示无演变可对比。段 = 行为变点切出的自然章，均分段
读不出演变。

- 每段每 kind 先查 custom 快照精确键，命中即跳过 LLM（增量续跑）；章节
  边界漂移/升版后旧段快照自然失明重算；`force=True` 全部重算；bridge 层
  同会话单飞（`(conv, account_wxid)` 键，注册持 `_ONNX_TASK_LOCK`）+
  可取消（取消在每次 generate_profile 前生效，已完成段已落缓存）。
- 账号解析为空（无活跃账号）直接拒绝，不去掉账号过滤兜底；查询键与生成侧
  同源解析（`_resolve_account_wxid`），否则生产链路 `account_wxid=""`
  永远查不中缓存。
- include_self 默认关（单次桥接最长 章数×(1+含我) 次 LLM 调用）。
- 标签对比泛化：该段独有（琥珀）/多段共有（中性）。

## 版本常量

| 常量 | 位置 | 当前值 | 何时 +1 |
|---|---|---|---|
| `PROFILE_SNAPSHOT_SCHEMA` | contact_profiler.py / self_profiler.py | 5 | 表结构或画像口径变化——随行落库 `schema_version` 列，读取处过滤；旧结构 DROP 重建，不迁移。v2 = 【长期背景】全时段基线块；v3 = 【长期记忆事实】RAG 事实层注入；v4 = 【关系章节摘要】章节金字塔注入（profile_chapter_digest）；v5 = origin 来源列（演变段/滚动/指定窗区分） |
| `PROFILE_SNAPSHOT_KEEP` | 同上 | 8 | rolling 分组保留条数调整 |
| `PROFILE_SNAPSHOT_KEEP_CUSTOM` | 同上 | 24 | custom 分组保留条数调整（对齐 list_snapshots 上限，裁剪不得逐出回廊可展示的快照） |
| `big5_impressions` 表结构 | personality_impression_service.py | v2（window 档位） | window 档位列或唯一键变化——`_ensure_table` PRAGMA 探查缺列即 DROP 重建不迁移（口径见 `docs/analysis/time-depth.md` 大五节） |

## 脱敏责任边界（现状口径）

画像 LLM 链路（`llm_http.post_json_with_retries` 经 `profile_llm_retry` 包装）
的**窗口样本原文**不过 PrivacyRedactor——与大五增强层的脱敏红线是两条链路。
本期沿用现状并在此记录；若要收口是独立的安全加固项。例外：**事实块逐条过
PrivacyRedactor**（全时段数据 + 事实本来就是结构化短句，规则脱敏无损可读性，
见上节门控）。

## 相关文件

- 后端：`services/realtime/{contact_profiler, self_profiler, generation_context}.py`、
  `services/realtime/rag/relationship_policy.py`、`services/analysis/profile_evolution_service.py`、
  `webview/api/profile.py`（窗口透传 / window 标注 / `list_profile_snapshots`）、
  `webview/api/deep_analysis.py`（`generate_profile_evolution` / `cancel_profile_evolution`）
- 前端：`components/persona/{PortraitGenerateDialog, PersonaGallery}.vue`（自定义时间窗
  入口、历史快照回看含「演变段」徽标、heroMeta 覆盖比+新鲜度口径行）、
  `components/persona/ProfileBriefCard.vue`（窗口行三件套）、
  `components/deep/ProfileEvolutionPanel.vue`（章节分段，切章重置由快照精确键兜底）
- 测试：`tests/test_profile_snapshots.py`（含 origin/覆盖比）、`tests/test_profile_evolution.py`
