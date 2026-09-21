# RAG v4 P0：事实维护与向量召回

依赖：无。完成本文件前不启动 P1 之后的实现。

## P0-1 写入侧维护循环

- [x] 为结构化事实定义并实现 kind 归一化：`preference`、`plan`、`promise`、`personal_fact`、`event`、`boundary`、`mood`、`relation_state`。
- [x] 在 `RagStore` 增加按 account、conversation、subject、规范化 kind 查询 active/enabled 事实的方法。
- [x] 定义融合判定 JSON 契约：`ADD`、`UPDATE`、`INVALIDATE`、`MERGE`、`NOOP`，以及每个候选旧事实的判定结果。
- [x] 在 `RagIndexer._write_structured_facts` 中接入 LLM 融合判定；异常、超时或非法 JSON 必须退回 ADD。
- [x] 实现 UPDATE/INVALIDATE：新事实成功入库后调用 `supersede_fact(old_id, new_id)`，保留旧行审计链。
- [x] 实现 MERGE：合并 evidence ID，并以不降低原值的规则更新置信度，且不新增重复事实。
- [x] 单测：虾偏好被过敏事实推翻后，旧事实 superseded/disabled，新事实是唯一 active 结果。
- [x] 单测：语义重复事实只保留一条并合并证据。
- [x] 单测：五种融合结果及 LLM 异常退化 ADD 均通过。
- [x] 完成 P0-1 回归测试、更新勾选并提交 `feat：接通事实维护融合循环`。

## P0-2 事实向量混合召回

- [x] 新建 `rag_fact_embeddings` 及兼容迁移，键为 `fact_id + embedding_model + embedding_dim`。
- [x] 在结构化事实写入/更新后生成事实 embedding，并处理维度不匹配、模型不可用和索引 stale 状态。
- [x] 在 `RagStore` 增加事实向量 upsert 和加载接口。
- [x] 将 `_retrieve_facts` 改为向量为主、关键词和置信度为辅的混合评分；关键词零重合不能淘汰语义候选。
- [x] 将事实 kind 从硬过滤改为软加权，保留 sensitive/空内容过滤。
- [x] 单测：`她有什么忌口？` 能召回“对方对虾过敏”，即使 n-gram 重合为零。
- [x] 单测：相关事实在混合分数中高于“对方在玩杀戮尖塔”等无关事实。
- [x] 单测：维度不匹配和 800ms 超时安全降级，不抛出到建议链。
- [x] 完成 P0-2 回归测试、全套后端回归 603 passed / 21 skipped，并提交 `feat：接通事实向量混合召回`。

## P0-3 历史事实向量回填

- [x] 为历史 active facts 增加批量向量回填，保持 fact 行和 supersede 链不变。
- [x] ready 联系人索引发现缺失向量时异步调度回填；维度/模型失败保留关键词降级。
- [x] 单测：回填幂等、维度校验和 ready 索引调度通过。
- [x] 对现有联系人数据库完成一次真实回填（7191=`799`、628=`252`，768 维均成功）并复跑 smoke；fact-path Recall@5=`0.25`、MRR=`0.25`，结果纳入 P3 报告。
