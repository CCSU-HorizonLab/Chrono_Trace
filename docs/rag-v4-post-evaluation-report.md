# Chrono Trace RAG v4 后评估报告

> 评估时间：2026-09-23。运行库是 `backend/data/chrono_trace.db` 的只读 WAL 一致快照；仓库根目录的 `backend/chrono_trace.db` 为 0 字节空壳。脱敏统计与复现脚本见 [运行统计](analysis/rag-v4-post-eval-runtime-stats.json) 和 [audit_rag_v4_post_eval.py](../backend/scripts/audit_rag_v4_post_eval.py)。

## 结论摘要

一句话诊断：v4 已把“联系人事实可检索、可门控、可审计”做成能通过门禁的读侧模块，但用户期待的是“关系策略驱动的建议”；当前关系状态/对方偏好写入很少，建议链没有可归因的 RAG 使用证据，门禁因此没有测到用户最在意的体验。

三个最大的“指标—体感”落差来源：

1. **评测对象错位**：43 条冻结 gold 是运行事实与模型生成问题组成的 memory QA 诊断集；真实建议场景没有纳入。真实库只有 7 条检索日志、1 个会话，无法代表触发面。
2. **关系知识不是可用的关系模型**：运行库只有 2 条 `relationship_state`、2 条 `communication_style`、0 条 `contact_preference`。关系摘要是消息量/最近时间等规则摘要；`communication_style` 记录的是用户表达风格，不是对方“吃哪一套”。
3. **召回到生成没有证据**：fact-path faithfulness=0.3256（95% CI [0.1860, 0.4651]）；7/7 真实检索日志的 `suggestion_id` 为空，5 条建议只有 shown/viewed，feedback attribution 与反馈写回均为 0。检索到了不能推出建议用到了。

## A. 指标本身的局限

| 假设 | 裁决 | 证据与评级 |
|---|---|---|
| A1 gold 与真实问法分布接近 | **已证实 gold 不是人工回归集；分布差距未量化（高风险推断）** | P3 明确 43 条冻结集由运行事实和模型生成问题构成，并标注“冻结诊断基线，不替代人工扩充回归集”。真实库只有 7 条日志、1 个会话、5/7 memory_request，不能估计真实记忆需求分母。 |
| A2 fact-path 胜过 document-RAG 是否只是弱基线胜利 | **已证实是弱基线比较；不能证明绝对体验好** | 冻结报告 fact-path Recall@5=0.6316、MRR=0.4504、faithfulness=0.3256；document-RAG Recall@5/MRR=0。冻结目标文档把 document-RAG 三项记为 0，但同版本 JSON 的 document faithfulness 字段为 0.0465，报告口径需在下一轮统一；无论采用哪一口径，Recall/MRR 比较都接近“有检索 vs 无有效检索”。 |
| A3 faithfulness 低是否是独立残差 | **已证实** | 43 个 fact-path 答案 faithfulness=0.3256，95% CI [0.1860, 0.4651]；13/38 个非敏感、可计分 case 未在 top-5 找到 gold。即使命中，生成答案仍可能没有使用证据。v4 未加入建议生成质量门禁。 |
| A4 memory QA 能否代表 suggestion/ambient | **已证实没有度量；建议贡献未验证** | `llm_engine.py:498-516` 在建议前构造 RAG，`llm_engine.py:1160-1243` 将结果注入 prompt；但当前 7 条日志 `suggestion_id` 全为空。当前 5 条 `realtime_suggestions` 均为 `manual_request`，shown=5、viewed=5，feedback attribution=0、writeback=0。 |

A 组的结论是：门禁回答了“事实检索路径是否优于 document fallback”，没有回答“建议是否更懂关系”；faithfulness 低值还说明检索结果与答案之间存在独立生成残差。

## B. 检索漏斗残差

### B1 触发面

真实运行库 7 条日志中，`memory_intent` 为 `memory_request` 5/7（71.4%）、`none` 2/7（28.6%）；RAG 均 enabled/retrieved；gate inject=5、skip=2，两个 skip 的 reason 都是 `low_score`。index ready=5、pending=2；strategy facts=5、hot_context=2。由于没有“应该记忆但没有触发”的标注分母，真实触发召回率**未验证**，且样本只有一个联系人/会话。

`memory_intent.py` 只产出辅助标签；是否检索仍由 `RagContextBuilder.enrich_context` 执行（`rag_context_builder.py:115-181`）。因此要单独测建议触发面，不能用 intent 分布代替。

### B2 召回残差

冻结 fact-path 的 38 个非敏感、可计分 case 中，Recall@5=24/38=0.6316，13 个未命中 top-5。未命中类别：`personal_profile` 3、`purchase_or_price` 3、`relationship_boundary` 2、`plan_or_appointment` 1、`preference_dislike` 1、`recurring_habit` 1、`food_or_place` 1、`hobby_or_game` 1。38 条的 gate reason 全是 `memory_request_match`，所以这些首先是排序/表示/事实覆盖残差，不是被门控拒绝。

真实日志的 2/7 `low_score` skip 是可观察漏斗残差，但不能与 13/38 gold miss 混成同一分母。后续要记录 `retrieval_attempted`、`gold_like_need` 和 `miss_stage`，分开统计触发、召回、门控、注入、生成五段漏斗。

### B3 敏感策略代价

运行库有 1,051 条 active/enabled 事实，其中 sensitive=10、normal=1,041；冻结集 5 条敏感查询全部阻断，precision/recall=1.0。敏感事实不进 prompt 是红线，不能为体感直接拆门。

代价目前只能定性，**高价值关系记忆被挡的数量未验证**：现有日志没有“被阻断事实是否可安全抽象”的标签，也没有用户授权/安全摘要的反事实。改造应增加“原文阻断但安全策略摘要可用”的独立标注与审计，继续保持原文不入 prompt。

## C. 关系理解层专项分析

### C1 写入内容与生命力

`rag_indexer.py:434-455` 生成 `relationship_state`，内容只有累计消息数、最近对话时间和“最近对话优先”的规则摘要；`rag_indexer.py:603-631` 生成 `communication_style`，统计的是用户消息平均长度、问句/emoji/重复标点和用户样例。代码没有生成 `contact_preference` 文档。

脱敏统计：

- `rag_documents` 2,271 行：`fact_memory` 1,062、`shared_memory` 619、`evidence_excerpt` 269、`topic_segment` 269、`self_style_example` 48。
- 关系相关文档：`relationship_state` 2、`communication_style` 2、`contact_preference` 0；`superseded_by` 非空为 0。
- `rag_facts` 1,051 行全部 active/enabled；`supersedes_fact_id` 非空为 0。1,048 条 confidence 在 [0.50, 0.70)，仅 3 条在 [0.70, 0.90)，没有 >=0.90 的事实。

`RagRelevanceGate.RELATIONSHIP_TYPES` 已存在（`rag_relevance_gate.py:45`），也有 weak relationship 分支（:195-215），但可供选择的 `contact_preference` 为 0；`relationship_boundary` facts 还没有形成阶段/亲密度/边界的可解释状态对象。C1 **已证实是主要体感缺口**。

### C2 生成是否真正使用关系上下文

已证实的链路是：`RagContextBuilder` 记录 gate、selected doc types、fact/evidence IDs 并将 item 放入 `retrieval_context`（`rag_context_builder.py:458-559`）；`llm_engine.py:1160-1243` 把 fact/relationship/style 内容加入 prompt，并写入“仅作辅助/不强行带入”的边界。

“模型因此改变了建议”仍**未验证**。当前没有 prompt 中的 item-use 标记、输出中的关系策略引用/禁忌遵守标签，也没有同一触发窗口的 no-RAG/fact-path 成对建议。应记录 `candidate_id`、`retrieval_log_id`、`injected_doc_types`、`relationship_policy_ids`，再由盲评和用户行为验证；“参考命中” badge 不能代替因果证据。

### C3 反馈闭环

现有机制分两条：

1. `feedback_attribution.py:285-321` 只有 accepted/rewritten/preface_then_reply 且 confidence>=0.65 才写 `feedback_example` 并尝试 embedding。
2. `feedback_rule_extractor.py:439-512` 将规则写到 `contact_rules`，confidence>=0.5 才读取；`llm_engine.py:1289-1303` 又把它收敛成“表达偏好参考（仅影响措辞，不决定话题）”。

当前库 feedback attribution=0、feedback writeback=0，且没有 `contact_rules` 表。故“采纳/改写是否修正记忆权重”在生产数据上**已证实未发生/无法观察**；即便机制被调用，它当前影响的是措辞，不是关系阶段、对方偏好或建议策略。

## D. 信任损伤

postrelease 文档记录并修复了真实问题：index pending 时 `hot_context`（`document_id=-1`）被显示成历史参考命中；修复要求正时间戳、至少一条对方消息，并覆盖“仅当前用户问题/无时间戳”两种伪命名单测。问题曾发生**已证实**。

只读运行库仍有 2 条 `document_id=-1`、`strategy=hot_context`、`index_status=pending`、`degrade_reason=hot_context_only` 候选记录；它们不能证明修复后仍向用户显示，也不能证明来自生产而非回放，因为 schema 没有 eval/test provenance，且 `suggestion_id` 为空。修复前受影响次数、答非所问次数、信任下降幅度均**未验证**，评级为“高影响、可观测性不足”。

## 与原始蓝图的差距

蓝图主线是“一个聊天对象 = 共同记忆 + 沟通方式 + 关系状态 + 建议策略”（[历史增量计划](archive/plans/incremental-plan-rag-suggestions.md)），并要求关系状态默认注入、对方偏好高置信注入、反馈样本回写。

- **共同记忆**已有 `fact_memory/shared_memory` 和 768 维召回，但 13/38 gold miss、faithfulness=0.3256，不能把“有库”当成“建议能使用”。
- **关系状态**只有 2 条规则摘要，未表达阶段、亲密度、主动模式、边界置信度。
- **对方偏好/雷点**为 0 条 `contact_preference`；`preference_like/dislike` 事实尚未成为联系人策略对象。
- **沟通方式**现有文档是用户自身风格，缺少对方响应模式和场景条件。
- **建议策略**没有独立策略对象；relationship weak inject 只能提供背景，不能给生成器明确约束。
- **反馈样本**有写回路径但当前为 0；规则读取只影响措辞，不更新关系/偏好权重。
- **评测**已有三路 memory QA 门禁，缺 suggestion A/B、关系理解人工标签、时间连续性、采纳/改写质量和“误提旧事”指标。
- **可解释性**有 hit/no-hit badge 和 log ID，但没有区分 fact/document/hot context，也没有说明关系策略如何影响建议。

## 已验证、推断、未验证

**已验证**：冻结指标与 CI；5/5 敏感阻断与 1.0 隔离率；真实库 7 条日志、1 会话、intent/gate/strategy 分布；1,051 条事实的 active/sensitive/confidence 分布；关系文档 2/2/0；7/7 suggestion_id NULL；5 条建议 shown/viewed；反馈 attribution/writeback=0；hot_context 伪命中问题和修复条件。

**推断（验证方法）**：真实问法与模型生成 gold 分布差距大（人工标注“记忆需要/关系策略需要/无需记忆”后分层比较）；关系知识不足是体感主因（同窗口 no-RAG/fact-only/relationship-policy 三臂盲评）；faithfulness 残差伤害建议（保存脱敏 prompt/item/output 做证据使用标注）；反馈若只写 feedback_example/contact_rules 不会改变排序（前后回放比较 score、policy version）。

**未验证**：真实聊天需要记忆的总体比例和触发漏检率；敏感阻断中可安全抽象的高价值比例；模型是否使用关系上下文及有 RAG 的因果增益；hot_context 修复前受影响次数；采纳/改写对长期建议质量的提升。

没有收到可公开纳入的匿名失败对话，报告不虚构案例；应在 P0 人工回归集建立时补入 2–3 个真实失败案例。
