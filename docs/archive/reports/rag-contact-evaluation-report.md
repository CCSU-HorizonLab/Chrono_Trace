# Chrono Trace 联系人级 RAG 评估报告

## 结论摘要

当前系统的存储、索引状态机、隐私处理和检索日志具备复用价值。主要风险集中在写入侧事实维护和读侧门控复杂度：系统更接近文档 RAG，写入侧事实维护不足，读侧通过复杂门控补偿，导致召回、命中和忠诚度存在共同风险。

这是一份代码审查结论，不是线上效果报告。仓库当前没有真实运行数据，因此 Recall@5、MRR、faithfulness、误拒率、延迟和用户采纳率均标记为“未验证”。

## 证据矩阵

| 结论 | 类型 | 代码/文档依据 |
|---|---|---|
| embedding 适配器默认 384 维，并对超长向量截断、短向量补零 | 已证实 | `backend/app/services/realtime/rag_embedding.py` 的 `RagEmbeddingService` |
| 配置维度可以独立于模型输出维度变化，旧实现可能产生索引语义不一致 | 推断 | `rag_config.py` 的 `rag_embedding_dim` 与 embedding 适配器分离 |
| “刚/刚才”映射为最近 24 小时 | 已证实 | `rag_retriever.py::_time_scope` 和 `_within_time_scope` |
| 旧 query 会拼接 trigger、intent、上下文及最多 8 条最近消息 | 已证实 | `rag_retriever.py::build_query` |
| query 过长可能污染当前问题表示 | 推断 | 由上述拼接策略推导，需离线对照验证 |
| 当前事实抽取主要是 embedding 原型匹配和阈值判断，不是 LLM 结构化抽取 | 已证实 | `rag_semantic_memory.py::SemanticFactExtractor` |
| 门控包含多种 doc_type、分数、时间和意图条件 | 已证实 | `rag_relevance_gate.py`、`rag_retriever.py`、`rag_context_builder.py` |
| 多层门控可能把可召回事实变成 skip/no-hit | 推断 | 需要通过 `rag_retrieval_logs` 聚合验证 |
| 当前评测样例为 8 条，主要是人工检查字段 | 已证实 | `docs/archive/evaluations/rag-v1/rag-v1-eval-samples.json` 和评测模板 |
| 真实 Recall@5、MRR、faithfulness、门控 skip 基线 | 未验证 | 仓库没有已产出的运行结果 |

“不可救药”“F”等措辞应保留为评审评级，不应写成运行时事实。

## 已实施的迁移基础

- 新增 `rag_query_scope`，默认 `latest_turn`，保留 `recent_window`/`all` 作为可比较模式。
- embedding 服务记录模型原始维度；索引构建时发现与配置维度不一致会进入 failed 状态，不再无声通过。
- 新增联系人级 `rag_facts` 影子表，保存 subject、kind、status、时间范围、置信度、敏感级别和证据消息 ID。
- 新增默认关闭的 `rag_fact_read_enabled`；开启后事实检索命中才切读，空结果自动回退旧文档通道。
- 现有 `rag_retrieval_logs` 增加 retrieval source、fact/evidence IDs、query scope 和 supersession decision 字段。
- 现有文档读侧保持不变，事实表暂不参与注入，支持回滚。

## 评测方法

使用 `backend/scripts/evaluate_rag_retrieval.py` 对标注的“query → gold document/fact IDs”计算 Recall@5、MRR、skip/no-hit 率，并按类别聚合。第一批数据扩展到 30–50 个问题—事实对，覆盖共同记忆、偏好、计划、承诺、冲突降温和敏感阻断。

端到端评测同时保留 no-RAG、现有 RAG 和新方案输出；对脱敏后的答案与 evidence 做 `entailed / contradicted / unknown` 判断，并记录 judge/prompt 版本。

门禁采用“先基线、后定阈值”：冻结 no-RAG 与现有 RAG 基线后，用分层 bootstrap 下界确定阈值。新方案不得降低记忆命中、Recall@5、MRR、faithfulness、身份隔离或敏感阻断质量；关键安全指标回退时按联系人切回旧读侧。

## 后续迁移顺序

1. 用 30–50 条 gold 对建立 no-RAG/旧 RAG/止血版基线。
2. 使用已新增的可注入结构化 LLM 抽取边界；实际 LLM 调用接入后，解析失败、低置信度和敏感事实进入 quarantine。
3. 影子双写稳定后，切换为事实过滤 → 一次重排 → evidence fallback 的读侧。
4. 完成回放、门禁和回滚演练后，再清理不可达旧门控分支。
