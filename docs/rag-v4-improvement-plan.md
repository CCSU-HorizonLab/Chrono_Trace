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

### P1.1 联系人关系状态影子表

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

### P1.2 `contact_preference` 与安全关系策略

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

### P1.3 关系策略注入与生成约束

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
