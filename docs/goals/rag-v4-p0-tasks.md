# RAG v4 P0：事实维护与向量召回

依赖：无。完成本文件前不启动 P1 之后的实现。

## P0-1 写入侧维护循环

- [ ] 为结构化事实定义并实现 kind 归一化：`preference`、`plan`、`promise`、`personal_fact`、`event`、`boundary`、`mood`、`relation_state`。
- [ ] 在 `RagStore` 增加按 account、conversation、subject、规范化 kind 查询 active/enabled 事实的方法。
- [ ] 定义融合判定 JSON 契约：`ADD`、`UPDATE`、`INVALIDATE`、`MERGE`、`NOOP`，以及每个候选旧事实的判定结果。
- [ ] 在 `RagIndexer._write_structured_facts` 中接入 LLM 融合判定；异常、超时或非法 JSON 必须退回 ADD。
- [ ] 实现 UPDATE/INVALIDATE：新事实成功入库后调用 `supersede_fact(old_id, new_id)`，保留旧行审计链。
- [ ] 实现 MERGE：合并 evidence ID，并以不降低原值的规则更新置信度，且不新增重复事实。
- [ ] 单测：虾偏好被过敏事实推翻后，旧事实 superseded/disabled，新事实是唯一 active 结果。
- [ ] 单测：语义重复事实只保留一条并合并证据。
- [ ] 单测：五种融合结果及 LLM 异常退化 ADD 均通过。
- [ ] 完成 P0-1 回归测试、更新勾选并提交 `feat：接通事实维护融合循环`。

## P0-2 事实向量混合召回

- [ ] 新建 `rag_fact_embeddings` 及兼容迁移，键为 `fact_id + embedding_model + embedding_dim`。
- [ ] 在结构化事实写入/更新后生成事实 embedding，并处理维度不匹配、模型不可用和索引 stale 状态。
- [ ] 在 `RagStore` 增加事实向量 upsert 和加载接口。
- [ ] 将 `_retrieve_facts` 改为向量为主、关键词和置信度为辅的混合评分；关键词零重合不能淘汰语义候选。
- [ ] 将事实 kind 从硬过滤改为软加权，保留 sensitive/空内容过滤。
- [ ] 单测：`她有什么忌口？` 能召回“对方对虾过敏”，即使 n-gram 重合为零。
- [ ] 单测：相关事实在混合分数中高于“对方在玩杀戮尖塔”等无关事实。
- [ ] 单测：维度不匹配和 800ms 超时安全降级，不抛出到建议链。
- [ ] 完成 P0-2 回归测试、更新勾选并提交 `feat：接通事实向量混合召回`。
