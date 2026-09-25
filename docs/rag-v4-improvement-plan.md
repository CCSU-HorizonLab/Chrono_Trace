# Chrono Trace RAG v4 分阶段改造计划

目标是让建议卡片可感知三件事：系统知道“我和这个人是什么关系”、知道“我们聊过什么”，并知道“这个人吃哪一套”。方案沿用 v4 的事实表、768 维向量、影子表、回放门禁和 `inherit/facts/documents` 三档读侧开关，不训练或微调模型，也不拆安全门禁。

## 先固定的验收原则

每个阶段都先在同一脱敏快照跑 no-RAG、document-RAG、fact-path 和新分支，再设阈值；不能用 LLM 自动评分作为唯一验收。每个线上请求必须能关联：

```
suggestion_id -> retrieval_log_id -> injected item/policy IDs -> output version -> feedback event
```

任何新写入都先影子表；新读侧通过联系人级开关逐步启用；异常沿用事实读侧回滚到 `inherit`、`facts` 或 `documents`。继续满足 v4 红线：安全降级不阻塞建议、融合异常只 ADD、向量维度不匹配显式失败、敏感事实不进 prompt、关键路径记录 `degrade_reason/gate_decision`。

## P0：止血与可观测闭环（优先级最高，预期体感收益高、成本中）

P0 的目标是先停止“看见参考 badge 却不知道是否用于建议”的信任损耗，并建立能回答真实触发面的问题。P0 不放宽敏感策略。

### P0.1 统一 provenance 和建议关联

**改动**

- 在 `rag_retrieval_logs` 增加 `run_provenance`（production/replay/eval）、`suggestion_id` 回填、`prompt_context_hash`、`injected_item_ids`、`injected_doc_types`、`policy_ids`、`hot_context_only`。
- 在 `llm_engine.py:507-516` 之后把生成前的 `_rag_log_id` 绑定到创建的 suggestion；流式和手动生成都走同一绑定函数。
- 在 `rag_context_builder.py:458-559` 记录“retrieved candidates”和“actually injected items”两套集合，避免 hit_count 冒充 prompt 使用。
- 在 `suggestion_observer.py` 事件 metadata 保存 RAG mode、policy version 和 badge state；不保存敏感原文。

**验收与度量**

- 新产生的建议中 suggestion_id 回填率 >=99%；检索日志与建议一对一或明确多次尝试原因。
- production 与 replay/eval 可由 SQL 严格分开。
- 每次生成可计算触发→召回→gate→注入→生成五段漏斗；缺字段的请求按 instrumentation failure 计数。

**风险与回滚**

- 风险：旧客户端/旧表迁移；使用 nullable additive migration，不改变现有读路径。
- 回滚：停止写入新字段，读侧回到现有三档开关；保留影子列以便审计。

### P0.2 修正可解释性状态

**改动**

- `llm_engine.py:860-916` 的 badge 按 item type 分层：`fact_hit`、`document_hit`、`relationship_policy`、`hot_context`、`no_hit`、`degraded`。hot_context 只能显示“当前对话上下文”，不得显示“历史参考命中”。
- 前端 `FloatingPanel.vue` 只消费结构化 state，不根据 `hit_count>0` 自己推断“参考命中”。
- badge 同时显示 gate decision、degrade reason 和“已注入/仅候选”；不显示敏感事实文本。

**验收与度量**

- pending + `document_id=-1\) 的回放中历史参考 badge=0，hot_context badge=100% 标为临时上下文。
- no-hit、timeout、index_not_ready、redaction_failed 均有可解释状态且不阻塞建议。
- 加入 postrelease 两类伪命中测试，并增加 UI contract test。

**风险与回滚**

- 风险：用户看到的 badge 数量下降；这是修正信任含义，不是放宽检索。
- 回滚：前端按旧 summary 展示，但保留后端新字段；不得回滚到把 hot_context 伪装成历史证据的逻辑。

### P0.3 人工建议回归集与最低质量门

**改动**

建立 60–100 条首批人工样本，至少覆盖每个联系人 2–3 个真实失败案例和以下标签：

- 场景：ambient、手动建议、直接问答、memory lookup；
- 需求：无需记忆、共同记忆、关系状态、对方偏好/雷点、用户风格；
- 关系阶段/亲密度/边界/对方响应模式；
- 允许引用、应避免引用、敏感阻断、无命中应追问；
- gold fact/policy IDs、expected scope、expected safe abstraction。

每条样本保存原始文本的本地受控版本和脱敏评测版本；gold 映射仍用数字 ID，继续校验联系人/会话范围。

**验收与度量**

- 先冻结现有 43 条 QA baseline，再在人工集上建立三路 baseline。单人两轮自一致性（间隔 >=48 小时）一致率 >=0.70 后才设阈值（见“P0 修订说明”）。
- 除 Recall@5/MRR/faithfulness 外，新增：触发 recall、正确注入率、证据使用率、关系状态正确率、偏好/雷点遵守率、误提旧事率、建议可发送率、安全阻断 precision/recall、隔离率。
- faithfulness 不得单独作为通过条件；每条生成至少一项人工关系标签和一项可发送性标签。

**风险与回滚**

- 风险：人工标签偏差；双标、仲裁和版本化，不能用单一 LLM judge。
- 回滚：评测只新增，不改变线上读路径。

### P0.4a 事实质量门与簇合并 ✅（2026-09-24 完成）

后评估遗漏的写入侧缺口：原型匹配把"666/好好好/看一下吧"等单轮碎片全部写成 active 事实，且相邻轮次各自成条。已实施：

- `rag_fact_quality.py`：入库质量门——拒绝过短/通用应答/疑问轮/纯符号/敏感词；kind 信号词必须出现在焦点消息本身（防邻句传染）；hobby/preference/food 要求有宾语。信号词表外置于 `fact_kind_hints.json`（遵循 v4 P2-1 去硬编码决策），敏感词复用 relevance gate 清单＋密码/密钥补充。
- `rag_semantic_memory.py`：`_consolidate_fact_clusters` 同 kind + 600s 内 + 证据消息重叠 >=2 的候选合并为单一记忆（最高分代表 + 证据并集）。
- `rag_store.quarantine_low_quality_shadow_facts`：存量隔离（status='uncertain'，保留审计行；不动 LLM 事实与用户墓碑），挂在 rebuild 完成点。
- 真实库执行结果：active 事实 2439 → 242（隔离 2221 条碎片；其中本轮 1496 + 前轮 725）。
- **基线失效决策**：runtime gold 36 集的 gold 事实 87% 被质量门判为碎片（抽查证实），冻结基线 Recall@5=0.7105 随之 superseded；存活 gold 命中率 4/5 说明检索侧无回退。新基线由 P0.3 人工集从 242 条有效事实重建。

### P0.4 事实置信度分布校准 ✅（2026-09-23 完成）

运行库 1,051 条 active 事实中 1,048 条 confidence 落在 [0.50, 0.70)，无一条 >=0.90：置信度字段近似常数，无法支撑 P1 的“高置信派生策略 / 低置信 quarantine”规则。

**根因**：confidence 直接等于 embedding 余弦相似度（text2vec 短文本天然落在 0.5~0.75），且 `merge_fact_evidence` 用 `max(old, new)` 合并——重复确认不加分。

**已实施**：
- `rag_semantic_memory.calibrate_fact_confidence()`：余弦域 [0.45, 0.80] 线性映射到 [0.30, 0.90] 语义分量 + 证据数加成（≥2 条起 +0.04/条，封顶 +0.10）+ marker_fallback 封顶 0.55，整体 clamp [0.20, 0.95]。
- `merge_fact_evidence` 阶梯递增：每次重复确认 +0.06，封顶 0.95。
- `rag_indexer` 语义抽取路径接入校准；LLM 结构化抽取（llm_shadow）自报置信度透传不校准。
- 存量回填：`backend/scripts/backfill_fact_confidence.py`（默认 dry-run，--apply 写入），真实库已回填 2438 条。

**验收（全部通过）**：
- 影子分布：`shadow_verify_confidence.py` 重算 2439 条——旧分布 2432 条塌缩 [0.50,0.70)；新分布铺满 [0.40,0.90]，高置信 ≥0.80 共 11 条、低置信 <0.45 共 9 条，两集合非空。
- 回放门禁（runtime gold 36 集，43 case × 3 track）：Recall@5 `0.6316 → 0.7105`（+7.9pp）、MRR `0.4504 → 0.5026`（+5.2pp），skip/no-hit 持平，document 基线持平——校准同时改善了检索排序。
- 全量回归 673 passed, 21 skipped。

### P0.4b 质量门增强与断点续抽 ✅（2026-09-24 第二轮）

用户实测反馈"记忆碎片、来源原文拼不上"后的针对性修复（另查明：LLM 抽取当时因开关持久化 bug 未生效，全部产物为原型路径）：

- **系统消息拦截**：11 种微信通知特征（朋友验证请求/红包/拍了拍等）在质量门与候选过滤双层拦截；存量已清理。
- **乱码检测** `looks_corrupted`：替换符/控制字符/高位怪字符（0x80-0xFF 密集，中文语境罕见）占比 >25% 判损坏；事实焦点、上下文窗口、存量三层拦截（偶发西文字符如 café 不误伤）。
- **窗口净化**：候选窗口构造改用 `_is_informative_candidate` 同源过滤，乱码/系统消息不再混入"相关上下文"。
- **疑问句误伤修复**：指代开头（她/你/他）仅在短句（<15 字）时判疑问，"她在深圳一家中小公司做后端开发"类陈述放行。
- **断点续抽**：rebuild 开始时以该联系人 llm_shadow 事实的 max(as_of) 为水位，本轮只抽水位之后的段——多轮重建逐步覆盖全部历史（原设计每轮固定抽前 40 段，永远无法推进）。
- **开关修复**：AI 抽取/关系影子开关此前未接入 Settings 保存链路（点了会丢），已修复持久化并直接写入运行配置。
- 测试 +3（系统消息/乱码/水位跳过），全量回归 709 passed, 21 skipped。

### P0.4c 抽取自包含强化与记忆筛选速查 ✅（2026-09-24 第三轮）

用户实测反馈三类问题（对话拆两段/代指断裂/前端无筛选）的修复：

- **跨段指代消解**：抽取 payload 携带上一段结尾消息（`context_messages`，远程同样脱敏），prompt 标注"仅供理解指代，勿从中抽取或引用"；evidence 过滤仍严格限定本段消息。segment 循环传递 `prev_tail_messages`。
- **prompt 自包含强化**：差/好对照示例（"就买一下下嘛" vs "对方撒娇要求购买之前讨论过的游戏皮肤"），明确"无法确定指代对象就不输出该条；宁可少抽，不可抽含糊的"。
- **质量门 vague_fragment**：<=20 字含"一下下/这个嘛/再说吧"等代指残句直接拦截；用户举的两条真实垃圾（"就买一下下嘛""你什么时候跟我提再说吧"）已验证拦截并从存量清理（本轮隔离 2 条，active 剩 343）。
- **记忆筛选速查**：`get_contact_facts` 支持 `sort`（time_desc/time_asc/conf_desc）与 `kind` 过滤，返回 `kinds` 聚合（类型+计数）；前端记忆弹窗新增类型下拉（带计数）与排序下拉，变更即回第一页重载。
- 测试 +2（vague 拦截/上下文渲染与 evidence 隔离），全量回归 711 passed, 21 skipped。

### P0.5 评测口径统一 ✅（2026-09-23 完成）

goal 文档把 document-RAG faithfulness 记为 0，同版本 JSON 为 0.0465。已在 `rag-v4-soul-restoration-goal.md` 增补口径说明：document-RAG Recall@5/MRR=0、faithfulness=0.0465、no-RAG faithfulness=0.0698，分母统一为每 track 43 cases，以 `rag-v4-runtime-gold-eval-report.json` 为唯一数据源；P0.4 校准后的新回放基线（Recall@5=0.7105 / MRR=0.5026）一并落盘。

### P0 修订说明：单人标注方案

原 P0.3 的“双标 Cohen κ >= 0.70”不适配单人开发。改为：同一标注者隔 >=48 小时两轮独立标注，计算自一致性（两轮标签一致率 >=0.70 为门槛）；不一致样本记录仲裁理由后定标。标注轮次与分歧记录随数据集版本存档。同时新增“场景挖掘”步骤：先从真实聊天与检索日志自动抽取候选场景（引用过去事件/偏好/边界的时刻），标注者只做确认与补标，不从零编写。

## P1：关系理解核心（预期体感收益最高、成本中高，修订版）

P1 把“关系状态、对方偏好、沟通策略”变成联系人级、可版本化、可检索的安全摘要。事实 `rag_facts` 继续保留为事实真相源；新增关系策略派生层，不推翻 v4。

**修订：P1 不从零构建抽取，以现有 `contact_profiler.py` / `self_profiler.py` 为生成引擎。** 运行库已有 4 个联系人的 LLM 画像（性格标签、聊天风格、沟通注意、关系总结、主动性统计），且已注入建议 prompt。当前三个缺陷必须在本阶段修复：

1. **优先级倒置**：prompt 中对方画像标注“低权重参考”，而用户自身风格标注“必须严格模仿、3 条候选至少 2 条沿用句式模板”。P1.3 注入分槽时必须反转为关系策略 > 对方画像 > 用户风格，符合原始蓝图优先级。
2. **7 天 TTL 无声掉线**：画像过期后 `not expired` 分支静默跳过注入，无自动续期。P1.1 增加后台自动刷新（沿用索引队列），过期前续期，失败降级为最近未过期版本并记录 `degrade_reason`。
3. **与事实层脱节**：画像既不消费 `rag_facts` 作为证据，也不产出可追溯版本。P1.1 影子表以画像输出 + 事实派生双通道写入，带 evidence IDs。

### P1.1 联系人关系状态影子表 ✅（2026-09-24 影子层完成；读侧接通排 P1.3）

**已完成（2026-09-24）：**

- 新增 `rag_relationship_policy.py`：从 contact_profiles 画像（personality_tags/chat_style/communication_tips/relationship_note + initiative 统计）与 rag_facts（校准后置信度，仅非敏感）派生结构化状态——stage（亲密度×主动性，如"高频互动/对方更主动"）、closeness_band（conversations.message_count 阈值映射）、initiative_pattern（other_initiated/total_sessions ≥0.6/≤0.4 判定）、boundary_summary（relationship_boundary + preference_dislike 前 3 条聚合）、evidence_fact_ids/evidence_message_ids、confidence（证据事实均值，无证据 0.5）。
- `rag_store.py` 新增 `rag_relationship_state` 表 + upsert（ADD-only 版本链：evidence_hash 相同不产生新版本；新版本关闭旧版本 valid_to 并记 supersedes_state_id）/get_latest/count 方法。
- `rag_config.py` 新增 `rag_relationship_policy_shadow_enabled`（默认关闭）。
- `rag_indexer.rebuild_contact_index` 完成点挂钩影子刷新；失败只 debug 日志，绝不影响索引主链路。
- **画像 TTL 修复**：monitor 两处注入点从"`expired` 即静默跳过"改为"降级注入旧画像 + stale 标记 + 后台防重入续期（ContactProfiler/SelfProfiler generate_profile）"；llm_engine 对方画像段标题在 stale 时显示"（较旧，仅供参考）"。
- **prompt 优先级反转（P1.3 快赢提前落地）**：系统提示词第 2 条从"完美模仿用户风格（逐字逐句）"改为"先适配对方，再贴近自己（冲突时适配对方优先）"；对方画像段从"低权重参考"升级为"策略优先参考 + 使用规则"；用户画像段从"必须严格模仿，不可偏离 + 3 条候选至少 2 条沿用句式"降为"仅约束措辞，不决定策略"。
- 测试：`test_rag_relationship_state.py` 7 用例（派生映射、边界聚合、无输入跳过、版本链与 hash 去重、开关关闭跳过、全链路影子写入）；全量回归 688 passed, 21 skipped。

**待 P1.2/P1.3**：preference facts → contact_preference policy doc；影子状态读侧注入与分槽；人工集验收（阶段/边界 macro-F1 >= baseline + 0.10）。

**涉及模块/文件**

- 新增 `rag_relationship_state.py`（或 `rag_store.py` 的同名表接口）；
- `rag_indexer.py` 在历史重建和增量窗口后写影子状态；
- `rag_store.py` 增加版本、证据 ID、confidence、sensitivity、valid_from/to、supersedes 链；
- `rag_config.py` 增加 `rag_relationship_policy_shadow_enabled`。

**字段**

`stage`、`closeness_band`、`initiative_pattern`、`boundary_summary`、`conflict_deescalation`、`evidence_fact_ids`、`evidence_message_ids`、`confidence`、`policy_version`。值必须是短摘要/枚举，禁止写入敏感原文。

**写入规则**

- 只从 active/enabled、非敏感事实和经隐私层生成的安全摘要派生；
- 每次新版本先 ADD 影子行；融合异常仍 ADD，不能删除旧事实；
- 低置信度进入 quarantine，不默认注入；
- 只在证据发生变化或定期窗口刷新，避免每条消息抖动。

**验收**

- 新鲜度：有足够新证据的联系人，状态更新时间延迟 <= 一个索引窗口；无新证据不生成新版本。
- 版本正确率：人工集阶段/边界标签 macro-F1 >= baseline + 0.10，且低置信度误注入率不高于 baseline。
- 与事实链可追溯率 100%；隔离率 1.0；敏感摘要 prompt 泄漏 0。

**风险/回滚**

- 风险：把暂时情绪误判为关系阶段；用 valid_to、confidence 和“当前触发优先”约束。
- 回滚：relationship policy 读开关关闭，仍读现有 facts/documents；影子行保留。

### P1.2a LLM 结构化抽取接通 ✅（2026-09-24 完成）

P0.4a 质量门清理后事实池仅剩 242 条——原型匹配只够"排坏"不够"抽好"。本项把评估报告指出的"边界已建、LLM 调用未接"补上：

- `rag_fact_llm.py`：激活模型适配器（复用 profiler 的 llm_models 读取与 post_json_with_retries）；远程模型逐条消息脱敏（PrivacyRedactor，脱敏失败的单条宁可不发）；evidence_message_ids 过滤为段内真实消息 ID（防幻觉引用）；reasoning_content JSON 回退。
- `rag_indexer`：配置开启时自动注入适配器（4 个生产构造点零改动）；短段(<4 条消息)跳过、每轮每联系人 40 段预算、连续失败 3 次中止；LLM 事实过宽松质量门（长度/通用应答/疑问/敏感照查，kind 信号词不查——kind 由模型判定）。
- `rag_fact_quality.fact_quality_reason` 新增 `require_kind_signal=False` 宽松模式；补 acknowledgement 变体（"好的好的/好滴"）与"哪"字疑问。
- 配置 `rag_structured_fact_extraction_enabled` 默认关闭，设置页新增「AI 抽取记忆事实」开关（含 Token 消耗提示）。
- 端到端 smoke（deepseek-flash 远程 + 真实对话）：琐事段正确抽 0 条；游戏话题段抽 6 条全部过质量门、evidence 全真实（含 boundary 类"对方介意别人把杀戮尖塔说成垃圾"、relation_state 类等待信号——P1.1 影子层的直接食粮）。
- 测试 `test_rag_fact_llm.py` 7 用例（prompt 契约/evidence 过滤/远程脱敏/推理回退/宽松门/预算与短段跳过/连续失败中止/入库 llm_shadow）；全量回归 699 passed, 21 skipped。

### P1.2 `contact_preference` 与安全关系策略

状态（2026-09-25）：前置 T2 事实融合接通已在 P1.5 完成并验收，**可实施**；分槽/验收要求见下，记账详见 P1.5 映射小节。

**改动**

- 在 `rag_semantic_memory.py`/`rag_indexer.py` 增加对方偏好、雷点、有效沟通方式的结构化候选；候选必须有对方消息 evidence、场景条件和 confidence。
- 将现有 `preference_like/dislike`、`relationship_boundary` facts 映射为策略候选，但不改变原 fact 的 sensitivity 和门控。
- 新增 `contact_preference` policy doc，仅注入“怎么做/避免什么”的最小安全摘要；敏感原文仍过滤。
- `rag_relevance_gate.py` 保留 `DISALLOWED_SENSITIVITY`、敏感 query block、fact threshold=0.30；只新增 policy-specific allowlist 和独立阈值，先 shadow 记录 false accept/false reject。

**验收**

- 人工关系集的偏好/雷点遵守率 >= no-RAG + 10 个百分点；误提无关历史率不增加。
- policy 注入必须携带 evidence IDs、confidence 和 policy version；低于阈值只记录不注入。
- 敏感 precision/recall、隔离率、维度校验与 v4 baseline 不回退。

**风险/回滚**

- 风险：把“用户自己的习惯”误当成“对方偏好”；schema 强制 `subject=contact`，写入单测区分 sender_role。
- 回滚：联系人级 policy mode=inherit；事实读取继续由 `facts/documents` 三档控制。

### P1.3 关系策略注入与生成约束 ✅（2026-09-24 完成，P1 闭环）

- **分槽注入**：`rag_context_builder._inject_relationship_policy`——关系策略独立于检索结果（事实检索 no_hit 时仍注入联系人级背景），不占事实 1600 字预算；敏感影子行深度防御跳过；远程模型对文本字段脱敏（脱敏失败丢弃文本保留枚举）。
- **policy_ids 落库**：注入的 state_id 写入检索日志 policy_ids_json（P0.1 预留列启用）——每条建议可追溯使用了哪个版本的关系策略。
- **结构化 prompt 块**：llm_engine 新增【当前关系策略（联系人级背景，供判断分寸）】段（关系阶段/亲密度/主动性/相处边界/沟通建议/置信度），含防复述约束；位于对方画像段之前。
- **徽章**：注入关系策略时显示"已参考关系画像"（fact_hit 仍优先）。
- **配置**：`rag_relationship_policy_injection_enabled` 默认 True——实际生效前提是影子表有数据（shadow 开关默认 False），即用户只需开启 `rag_relationship_policy_shadow_enabled` 并重建索引，注入自动生效，单一开关控制全链路。
- **优先级反转**（前置快赢已落地）：系统提示词"先适配对方，再贴近自己"；对方画像升级"策略优先参考"；用户风格降为"仅约束措辞"。
- 端到端验证（真实库副本，conversation 7191）：派生 stage=高频互动/对方更主动（closeness=high）、boundary 18 条证据事实支撑、communication_tips 来自画像（"避免命令式、上下级式语气，她对此类措辞极敏感；不要拿她与他人比较"）；注入链路 state_id 完整返回。
- 测试 `test_rag_relationship_injection.py` 7 用例；全量回归 706 passed, 21 skipped。

### P1.3 关系策略注入与生成约束（原计划）

**改动**

- `rag_context_builder.py` 将注入预算分槽：关系策略摘要（小预算、默认）→当前相关 fact→必要 shared memory→风格样本。关系策略不与事实争用 1600 字事实预算。
- `llm_engine.py` 增加结构化块：当前关系阶段、对方偏好、边界、证据/置信度、使用条件；要求模型只在条件满足时影响建议，不强行复述历史。
- 输出解析后记录 `policy_used_ids`（模型自报只能做观测，不能作为通过条件），并由人工盲评确认。

**验收**

- 三臂盲评（no-RAG/fact-only/relationship-policy）中，关系策略正确率、可发送率分别相对 fact-only 提升；误提旧事不升高。
- 生成成功率、延迟、超时降级不劣于当前 baseline；RAG 失败仍安全降级。

**风险/回滚**

- 风险：上下文增多导致模型忽视当前对话；严格槽位预算、最近对话优先和 800ms deadline。
- 回滚：关闭 policy injection，只保留 v4 fact-path。

## P1.5：事实维护接通与抽取质量第三轮（2026-09-25）

P1 闭环后的定位修正：碎片清理和 LLM 抽取已有实质改善，但事实维护、关系派生接线、质量验收仍有缺口。本轮七项修复（测试基线 711 → 726 passed）：

- **T1 远程脱敏红线**：`rag_fact_llm` 适配器在 redactor 构造失败时曾置 None 后继续发原文。现远程模型脱敏器不可用（factory 缺失/抛异常/返回 None）即抛 `FactRedactionUnavailable` 阻断整段发送，由 indexer 按抽取失败计数中止；绝不降级发原文。
- **T2 事实融合协议接通**：生产适配器此前把融合 payload 当抽取 payload（要求 facts 协议），9 月 25 日日志 45 次 "fact fusion response requires decisions" 全部回退 ADD，MERGE/UPDATE/INVALIDATE 从未执行。现适配器按任务特征（`task=maintain_atomic_contact_facts` 或 `new_fact` 键）分流到独立融合 prompt（新事实+候选旧事实→decisions+理由），演变链（“以前不喜欢→现在改观了”）真正走 UPDATE/supersede；融合失败仍安全回退 ADD。决策与理由落 `[RAG Fact Fusion]` 日志。
- **T3 kind 映射统一**：关系派生层只认原型长名（relationship_boundary 等），73 条 LLM 短名事实（boundary/preference/personal_fact/relation_state）全部不在证据范围。现长短名并认；boundary_summary 按 subject 区分“对方的边界/我的边界”（各限 2/1 条，对方优先）。真实库副本重建验证：LLM 事实 20/73 进入证据集，boundary_summary 由 LLM 事实主导（含好例 5371），confidence 0.66→0.88，版本链正常。
- **T4 抽取质量第三轮**：用户实测三类缺口（“有钱了搞一台”“我们后天搬”代指残留；“早餐钱”交易细节；“有点吊”）。prompt 增加自检指令（“删掉这段对话后还能被理解吗”）+ 差/好对照强化 + 交易排除清单；质量门 vague 词表扩充（搞一台/整一台/后天搬等）并新增 `transaction_detail_terms` 词表键——全部进 `fact_quality_patterns.json`（P2-1 纪律），代码只留结构性规则。真实库重放：用户点名 6 条 active 事实全部被拦（vague_fragment 4 + transaction_detail 4，另捕获同类“昨天饭钱”“早饭钱钱”），好例与自包含改写版放行。
- **T5 断点续抽修正**：旧水位 `MAX(as_of)` 三缺陷（零事实段不推进/段失败被越过/prompt 改进不重抽）。现 `rag_index_status` 增段级进度列（fact_extract_watermark_ts + fact_extract_prompt_version），零事实成功段也推进；段失败冻结本轮水位（连续覆盖语义，失败段下轮重试）；prompt 版本变化（`p1.5`）水位失效全量重抽。
- **T6 开关语义与注入护栏**：设置页只写 `rag_relationship_policy_shadow_enabled`，读侧曾只查 `rag_relationship_policy_injection_enabled`（默认 True）——关掉影子开关后历史策略仍注入。现注入前提为两开关同时开启；影子行置信度 <0.55 不注入（留影子层）。真实库副本验证注入链路：state 注入→policy_ids=[3] 落检索日志（此前全库 policy_ids 为空——查实为影子状态创建晚于最后一条检索日志，链路未经真实请求，非代码损坏）。
- **T7 文档定位修正**：goal 文档开头“全部通过”改为如实定位（旧 gold 基线 superseded，现行验收=存活 gold 命中率+人工事实质量抽查，人工回归集待建）。

**遗留观察**（不在本轮范围）：原型路径旧碎片仍可能进入“我的边界”摘要（真实库“不想你嘛”一例，subject=我的 preference_dislike 长名）；边界摘要按置信度排序，待人工回归集建立后校准来源权重。

### P1.5 与原计划的映射（本轮不做的，显式记账）

本轮 T1-T7 均为原 P0/P1 的缺口修复与加固，不含以下原计划项——它们**不是被取消，是有明确前置**：

- **P0.3 人工建议回归集**（场景挖掘脚本+单人两轮自一致性标注+三路 baseline）：前置是用户使用数据积累（建议日志、检索日志、「不准确」点击）。数据达百条量级后应作为独立轮次任务化，同时解决 T7 中“新验收未建立”的长期方案。
- **P1.2 `contact_preference` 独立策略文档**：前置是 T2（融合接通）——偏好/雷点策略对象的生成与维护依赖融合链路。T2 已完成并验收，**前置解除，可实施**：preference facts → 独立预算槽的策略文档（与关系状态分槽）、policy 门控 shadow 校准。不要因 T3 修复了 kind 映射就跳过它——T3 只打通了事实进关系策略的通道，不产生独立的偏好策略注入。
- **P2.1 反馈可验证修正**：T2 是其地基（已验收）；T2 验收后剩余工作为 feedback_policy_signal 影子记录与「不准确」点击接入融合链。
- **P2.2 建议 A/B 与 P2.3 评测集刷新**：依赖 P0.3 完成。在此之前不得以“门禁 pass”宣称系统达标——当前唯一有效验收是存活 gold 命中率 + 人工事实质量抽查。

## P1.6：用户纠错闭环与演变链落地（2026-09-25 第二轮）

用户实测反馈（昕，conversation 7191：标注 22 条不准确——大部分为消费类代指碎片；买“什么”/“哪个”无法从记忆还原；游戏内商店购买被记为消费）+ 外部评估核验后的修复。测试基线 726 → 732 passed。

**核验澄清**（时间线判定）：09-25 00:13–00:16 的 40 次 "fact fusion response requires decisions" 全部产生于 P1.5 修复提交（01:09）**之前**的旧代码进程；新代码时段（01:05 重启后）融合成功 24 次（UPDATE 8 / MERGE 12 / ADD 50——UPDATE 已真实执行），失败 ~10 次（invalid JSON / no JSON object，疑为响应截断）。

- **T8【核心 bug】supersede/隔离防复活**：融合决策日志显示 UPDATE 已执行 8 次，但库里 superseded=0——根因是 `upsert_fact` 的 ON CONFLICT 把 status 改回 active，语义路径每轮重建把演变链退役的旧事实**静默复活**。修复：ON CONFLICT 对 `superseded`/`uncertain` 行保持原 status/enabled；`supersedes_fact_id` 用 COALESCE 保留链（重扫不清空）。副本验证：5383 supersede 后同 content 重扫不复活、链保留。
- **T9 用户纠错触发关系策略刷新（P2.1 最小闭环）**：真实库证实 5385 被用户标 inaccurate 后，01:30 生成的 state 仍引用它。新增 `refresh_after_fact_feedback`（bridge「不准确/忘记」后调用）：刷新关系策略影子，evidence 自动剔除禁用事实；刷新受 shadow 开关保护、失败只日志。副本验证：5385 反馈后 state 升版且 evidence 不再含 5385。
- **T10 融合稳健性**：融合候选按置信度截断（上限 12）+ max_tokens 1024→2048 + 解析失败日志带响应片段（长度/头尾），区分截断与围栏问题。
- **T11 质量第四轮**：疑问结尾扩“多少/几块”（“早餐多少”→question_turn，真实库 2 条）；购买类“……的”结尾代指判 object_missing（“直接买80的”）；新增 `weak_attitude_terms` 词表键（“没那么想要”类残句 ≤8 字拦截，带宾语放行）；敏感词检查提到疑问判定之前（“手机号是多少”应判敏感）。prompt 增加游戏内商店/虚拟物品购买排除与“……的”代词差例；抽取版本 bump p1.6（存量段自动重抽）。副本重放：93 条 active 原型新拦 5 条（没那么想要×2/自己喝完/早餐多少×2），无误伤。
- **学生会场景定位**（未在本轮自动化）：5383（院学生会）与 5385（非校学生会）语义上可并存——是范围（校级/院级）未澄清的 canonical 化问题，属 P1.2 contact_preference 的策略对象统一，T8/T9 保证了纠错生效与引用剔除，范围澄清待对话证据重抽后由融合链完成。

**运行面遗留**（供下轮决策）：旧原型路径仍占 active 事实 53%（93/176），其中 87 条焦点 <20 字；LLM 事实 83 条中 28 条 <20 字、20 条证据不足。原型路径的结构性收紧/退役（LLM 全量覆盖后）待用户确认后实施。

## P2：长期闭环与真实贡献（收益高、成本高）

### P2.1 反馈从“落库”变成“可验证修正”

**涉及模块**

`suggestion_observer.py`、`feedback_attribution.py`、`feedback_rule_extractor.py`、`rag_store.py`、`rag_indexer.py`。

**改动**

- 保留现有 3–10 分钟 attribution 窗口和 accepted/rewritten/preface_then_reply 规则；补写 `feedback_policy_signal` 影子记录，包含旧 policy version、新 policy version、证据和原因。
- accepted/rewritten 不直接改写原事实；生成新的 preference/policy candidate，经过重复、冲突、敏感检查后 ADD/UPDATE，并保留 supersede 链。
- `feedback_example` 只作为示例，不直接提升所有事实分数；在回放中验证它是否改变相关 query 的排序与生成标签。

**验收**

- 每个有终态的建议都有 attribution 或明确 low_confidence；不能把“无消息”当采纳。
- 反馈后同类场景 policy 命中/可发送率提升，且跨联系人污染 0；低置信反馈不改变线上策略。
- 真实库 feedback attribution、writeback、policy version 覆盖率持续可观测。

**回滚**

- policy writeback 开关关闭；停止新 policy 读取；保留 attribution 审计行和旧事实。

### P2.2 建议 A/B 与长期体验指标

采用联系人内随机、按触发场景分层的 A/B：

- A：当前 v4 fact-path；
- B：v4 + relationship policy；
- 可选 C：no-RAG，仅用于离线/小流量基线，不作为安全降级策略。

主要指标：

1. **可感知关系**：阶段/边界/对方偏好正确率、关系策略适配率、用户“像懂这个人”的盲评；
2. **记忆恰当性**：相关历史使用率、无关旧事率、误提率、no-hit 诚实率；
3. **建议价值**：view→adopt、rewrite、dismiss、后续真实发送的自然度/冲突率；
4. **系统质量**：触发 recall、top-5 recall、证据使用率、faithfulness、P95 latency、degrade reason；
5. **安全**：sensitive block precision/recall、跨联系人泄漏率、敏感 prompt 计数。

以现有 v4 数字先做 baseline，再用分层 bootstrap 下界和人工置信区间设阈值；任何安全/隔离回退立即按联系人切换 `inherit` 或 `documents`。

### P2.3 评测集持续刷新

每两周从真实日志抽样脱敏：记忆 QA 30%、关系策略 30%、ambient 建议 30%、安全/无命中 10%。新增样本必须人工标注 gold policy/fact IDs、可引用范围和“应该追问”标签；历史样本不覆盖，保留数据集版本。模型生成问题可以继续用于发现召回回归，但不能单独触发发布通过。

## 全链路验收矩阵

| 链路 | P0 记录什么 | P1/P2 改什么 | 体验指标 |
|---|---|---|---|
| 写入 | provenance、候选/影子状态 | relationship_state/contact_preference/policy 版本、证据和置信度 | 新鲜度、冲突率、可追溯率 |
| 触发 | memory_intent 与是否尝试检索 | 关系策略需要标签、ambient 标注 | trigger recall、漏触发率 |
| query | query、scope、脱敏 hash | 加条件化 policy query，不拼近聊污染 | query 分布、长尾覆盖 |
| 召回 | candidates、fact/evidence IDs | policy 与 fact 分槽召回 | Recall@5、MRR、policy recall |
| 门控 | gate decision/reason | 保留敏感/隔离/维度门禁，shadow 校准新 policy 阈值 | false reject、敏感 precision/recall |
| 注入 | injected item/doc type | 关系策略小预算、条件化注入 | injection precision、误提率 |
| 生成 | prompt/output hash、版本 | 输出 policy 使用观测 + 人工盲评 | faithfulness、关系适配、可发送率 |
| 反馈 | suggestion/event/attribution | policy candidate 写回，版本化回放 | adoption/rewrite、长期提升 |
| 前端 | badge state、hot_context 标记 | 显示“历史事实/关系策略/当前上下文/未命中” | badge 与真实注入一致率 |

## 保留、校准和禁止事项

**保留**：sensitive 原文不入 prompt；sensitive query block；联系人/会话隔离；768 维向量维度显式校验；融合异常 ADD-only；supersede 审计链；800ms 超时和安全降级；关键路径 `degrade_reason/gate_decision`；`inherit/facts/documents` 回滚。

**只允许数据校准**：`rag_fact_score_threshold=0.30` 先保持；用人工集统计 false reject 后再按联系人/策略类型增加 policy shadow 阈值。放宽时必须以非敏感安全摘要、证据 ID、低置信 quarantine 和回放门禁补偿，不能把敏感事实直接放进 prompt，也不能删除原安全门。

**禁止**：用 LLM 自动评分单独验收；把 hot_context 当历史命中；用 feedback 直接覆盖 active fact；跨联系人共享关系策略；为提升 Recall 截断/补零向量；以门禁 pass 代替 suggestion A/B。

## 优先级理由

P0 先解决可观测性和信任：工程成本中等，但能立刻判断用户看到的“参考命中”是否真实、并为 A/B 建立因果链。P1 直接补用户抱怨的关系状态、边界和对方偏好，是预期体感收益最大的产品改造；采用影子表和独立 policy 注入，风险可按联系人回滚。P2 才把反馈变成长期策略和真实行为收益，成本最高，必须等 P0 的关联数据和 P1 的人工关系集通过后实施。
