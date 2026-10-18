# 画像时间窗与快照（Profile Window & Snapshots）

> 定稿：2026-10-18。本文只记录**口径、版本与责任边界**——改画像相关代码前先读这里。
> KISS 口径：不做兼容迁移，旧结构直接 DROP 重建（详见各 profiler `_ensure_table`）。

## 功能概览

联系人画像（`contact_profiler.py`）与我的画像（`self_profiler.py`，原「自我克隆」）
是**时间窗画像**：LLM 对指定窗口采样对话的分析，不是全时段结论。

- **rolling 滚动窗**：档位锚定 now（low/medium/high = 7/30/90 天），内容不足向更早
  顺延；每次续期产生新窗口键 → 快照自然累积。
- **custom 指定窗**：`generate_profile(..., from_ts, to_ts)` 闭区间硬边界，**不顺延**
  （顺延会篡改用户指定窗口的语义）；防呆：非正/起点≥终点/终点晚于 now+1 天/
  窗内无文本消息均直接拒绝。**跨度不设上限**——按调用方切分的时窗如实生成
  （采样量按档位固定，窗口越长画像粒度越粗，由 UI 展示窗口标注，不做硬拦）。

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

prompt【基础信息】块带样本时间范围行（rolling 注明顺延，custom 注明指定窗）。

## 画像演变（ProfileEvolutionService）

切窗与词云演变共用 `split_window_evenly`，**段数独立自选 2~6 默认 2**
（每段是独立 LLM 快照，成本随段数线性涨，故不跟随词云 N 段）：前三段
`[b_i, b_{i+1}-1]`、末段含终点闭区间；payload 键 `segments`（v2 曾为
`halves`+`mid_ts`，破坏性改名与唯一消费方同 commit 收口），标签「第 N 段」。

- 每段每 kind 先查 custom 快照精确键，命中即跳过 LLM（增量续跑）；换段数
  切回旧档因精确键命中而免费；`force=True` 全部重算；bridge 层同会话单飞
  （`_profile_evolution_events`，注册持 `_ONNX_TASK_LOCK`）+ 可取消（取消在
  每次 generate_profile 前生效，已完成段已落缓存）。
- 全窗跨度不设上限（与单次 custom 生成同口径，按切分时窗如实分段）；账号
  解析为空（无活跃账号）直接拒绝，不去掉账号过滤兜底。
- include_self 默认关（单次桥接最长 segments×(1+含我) 次 LLM 调用）。
- 标签对比泛化：该段独有（琥珀）/多段共有（中性）——不再按「前/后半段」
  二分着色。

## 版本常量

| 常量 | 位置 | 当前值 | 何时 +1 |
|---|---|---|---|
| `PROFILE_SNAPSHOT_SCHEMA` | contact_profiler.py / self_profiler.py | 1 | 表结构或画像口径变化——随行落库 `schema_version` 列，读取处过滤；旧结构 DROP 重建，不迁移 |
| `PROFILE_SNAPSHOT_KEEP` | 同上 | 8 | rolling 分组保留条数调整 |
| `PROFILE_SNAPSHOT_KEEP_CUSTOM` | 同上 | 24 | custom 分组保留条数调整（对齐 list_snapshots 上限，裁剪不得逐出回廊可展示的快照） |
| `big5_impressions` 表结构 | personality_impression_service.py | v2（window 档位） | window 档位列或唯一键变化——`_ensure_table` PRAGMA 探查缺列即 DROP 重建不迁移（口径见 `docs/analysis/time-depth.md` 大五节） |

## 脱敏责任边界（现状口径）

画像 LLM 链路（`llm_http.post_json_with_retries` 经 `profile_llm_retry` 包装）
**不过 PrivacyRedactor**——与大五增强层的脱敏红线是两条链路。本期沿用现状并在此
记录；若要收口是独立的安全加固项。

## 相关文件

- 后端：`services/realtime/{contact_profiler, self_profiler, generation_context}.py`、
  `services/realtime/rag/relationship_policy.py`、`services/analysis/profile_evolution_service.py`、
  `webview/api/profile.py`（窗口透传 / window 标注 / `list_profile_snapshots`）、
  `webview/api/deep_analysis.py`（`generate_profile_evolution` / `cancel_profile_evolution`）
- 前端：`components/persona/{PortraitGenerateDialog, PersonaGallery}.vue`（自定义时间窗
  入口、历史快照回看）、`components/deep/ProfileEvolutionPanel.vue`（独立 2~6
  分段选择器，切档重置由快照精确键兜底）
- 测试：`tests/test_profile_snapshots.py`（9 组）、`tests/test_profile_evolution.py`
