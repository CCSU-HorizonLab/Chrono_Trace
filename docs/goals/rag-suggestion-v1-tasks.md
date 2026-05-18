# RAG v1 实施任务拆分

本文把 [RAG v1 Goal](./rag-suggestion-v1-goal.md) 拆成可执行任务。每个任务完成后都需要对照 [代码质量门禁](./rag-suggestion-v1-quality-gates.md) 验收。

## Task 0: 基线与开关

目标：先把 RAG v1 的配置入口和默认行为定住，不影响现有实时建议。

任务：

- 增加 RAG 总开关，默认关闭。
- 增加远程 RAG 脱敏开关，默认开启。
- 增加远程 embedding 开关，默认关闭。
- 增加默认 embedding 配置：`tingting0514/text2vec-base-chinese`，384 维。
- 设置页展示这些配置，但第一版可以先只做基础表单和风险文案。

验收：

- RAG 关闭时，现有实时建议链路行为不变。
- 关闭远程 RAG 脱敏必须有明确风险提示。
- 远程 embedding 不会被隐式开启。

依赖：无。

## Task 1: 数据结构与迁移

目标：为联系人级 RAG、隐私脱敏、反馈归因和索引状态建立数据基础。

任务：

- 新增 RAG 文档表、向量表、检索日志表。
- 新增联系人级索引状态表，支持 `pending / indexing / ready / stale / failed`。
- 新增通用隐私实体表和脱敏缓存表。
- 新增反馈归因表。
- 所有表都必须包含 `account_wxid`，RAG 相关表必须能关联 `conversation_id`。
- 迁移必须幂等，重复初始化不报错。

验收：

- 新库和旧库启动都能完成 schema 初始化。
- 可按 `account_wxid + conversation_id` 查询某联系人 RAG 状态。
- 不修改原始消息表的 `content` 字段。

依赖：Task 0。

## Task 2: 通用隐私脱敏服务

目标：建立 `privacy_redactor.py`，作为所有远程 AI 上下文的统一隐私处理层。

任务：

- 实现强敏字段识别：手机号、身份证、银行卡、详细地址、API key、密钥类字符串。
- 实现稳定占位符：同一会话内相同实体映射到同一占位符。
- 生成 `redacted_text`、`entity_map_json`、`pii_flags_json`。
- 写入 `privacy_entities` 和 `privacy_redaction_cache`。
- 提供强规则兜底遮罩方法，用于脱敏服务异常时的降级路径。

验收：

- 默认远程 RAG 上下文使用脱敏文本。
- 强敏信息不会进入默认远程上下文。
- 关闭远程 RAG 脱敏后，调用方可以拿到原文或弱脱敏文本，但必须能标记 `redaction_disabled = true`。
- 日志不输出强敏原文。

依赖：Task 1。

## Task 3: RAG Store 与索引状态

目标：建立 RAG 数据读写层，避免业务代码直接拼 SQL。

任务：

- 实现 RAG 文档写入、查找、去重、删除。
- 实现向量写入和按模型版本查询。
- 实现检索日志写入。
- 实现索引状态读写和状态流转。
- 支持将联系人索引标记为 `stale` 或 `failed`。

验收：

- 重复索引同一消息不会产生重复文档。
- embedding 模型、维度、隐私模式变化后能标记 stale。
- 索引失败能保留错误状态，不影响旧索引读取。

依赖：Task 1。

## Task 4: 本地 Embedding 适配

目标：复用现有本地 embedding 模型，为 RAG 生成 384 维向量。

任务：

- 复用现有模型路径和下载状态诊断。
- 封装 RAG embedding 入口，避免直接依赖情感分析服务内部实现。
- 输出固定 384 维向量。
- 模型缺失时返回明确错误，不崩溃。

验收：

- 本地模型存在时可批量生成向量。
- 模型缺失时 RAG 索引任务进入可解释失败或等待状态。
- 不同 `embedding_model + embedding_dim` 不混用。

依赖：Task 3。

## Task 5: 联系人级懒加载索引

目标：首次使用某联系人 RAG 时，只索引该联系人，不全量扫描。

任务：

- 根据 `account_wxid + conversation_id` 读取历史消息。
- 切分 `dialogue_turn`、`self_style_example`。
- 生成基础 `relationship_state` 文档。
- 写入 RAG 文档和向量。
- 更新索引状态为 `ready` 或 `failed`。

验收：

- 首次触发某联系人 RAG 时进入 `pending/indexing/ready` 流程。
- 其他联系人不被自动索引。
- 索引失败不影响实时建议。

依赖：Task 3、Task 4。

## Task 6: 后台增量索引队列

目标：新消息入库后异步更新 RAG，不阻塞导入和监听。

任务：

- 导入或实时监听写入新消息后，标记 dirty conversation。
- 后台按联系人聚合增量任务。
- 短时间内多条消息合并处理。
- 失败任务可重试，并写入失败原因。

验收：

- 导入流程不等待 embedding。
- 实时监听不等待 embedding。
- 增量索引失败不会影响建议生成。

依赖：Task 5。

## Task 7: RAG Retriever 与上下文构造

目标：在建议生成前构建 `retrieval_context`。

任务：

- 构造 query：最近对话、最新对方消息、触发类型、intent、手动需求。
- 支持联系人级过滤。
- 召回 `relationship_state`、`dialogue_turn`、`self_style_example`、`feedback_example`。
- 对结果做去重、敏感过滤、重排和压缩。
- 限制 RAG 检索与上下文构造额外耗时为 800ms。

验收：

- 检索结果只来自当前 `account_wxid + conversation_id`，除非显式允许全局兜底。
- 超过 800ms 自动降级。
- 检索为空时原建议链路继续工作。

依赖：Task 5、Task 6。

## Task 8: LLM 建议链路接入

目标：把 `retrieval_context` 注入现有 LLM 建议生成，但不破坏原 prompt 逻辑。

任务：

- 在生成建议前调用 RAG context builder。
- `_build_prompt()` 增加 RAG 段落。
- 最近对话优先级高于 RAG。
- RAG 异常时自动丢弃 RAG 上下文。
- 写入 `rag_retrieval_logs`，记录文档 id、耗时、索引状态、脱敏状态、降级状态。

验收：

- RAG 关闭时 prompt 不包含 RAG 段落。
- RAG 开启且 ready 时 prompt 包含压缩 RAG 上下文。
- RAG 超时、索引失败、脱敏失败时仍能生成建议。

依赖：Task 7。

## Task 9: 远程 RAG 脱敏与高级关闭

目标：落实“默认脱敏，高级可关”的远程 RAG 策略。

任务：

- 远程 LLM 默认只接收 `redacted_content`。
- `rag_remote_context_redaction = 0` 时，远程 LLM 可接收未脱敏或弱脱敏 RAG。
- 关闭脱敏必须由用户显式操作。
- 关闭脱敏时设置页展示明确风险提示。
- 检索日志写入 `redaction_disabled = true`。
- 远程 embedding 默认关闭；同时开启远程 embedding 和关闭脱敏时需要再次确认。

验收：

- 默认远程请求不包含未脱敏 RAG。
- 关闭脱敏后远程 RAG 可用。
- 日志能区分脱敏、未脱敏、强遮罩兜底三种状态。

依赖：Task 2、Task 8。

## Task 10: 脱敏异常降级

目标：脱敏服务异常时，避免裸发长历史，同时尽量保证远程建议可用。

任务：

- 正常脱敏失败时，使用现场强规则遮罩压缩摘要。
- 不发送长原文。
- 不发送 `sensitive` 记忆。
- 强遮罩失败时阻断远程 RAG 请求，回退无 RAG 或本地/模板。
- 日志记录 `redaction_fallback = true`。

验收：

- 脱敏异常不会导致未处理长原文发给远程。
- 强遮罩失败时远程 RAG 被阻断。
- 原建议链路仍可继续。

依赖：Task 2、Task 8。

## Task 11: 反馈归因

目标：替换“下一条消息即反馈”的粗糙机制。

任务：

- 建议生成后建立归因窗口。
- 收集 3-10 分钟内同会话候选用户消息。
- 合并连续短句。
- 判断 `accepted / rewritten / preface_then_reply / unrelated / interrupted` 等类型。
- 写入 `suggestion_feedback_attributions`。
- 高置信正向样本写入 `feedback_example`。

验收：

- 用户先铺垫再正式回复不会被误判。
- 对方插话后无法判断时不写入正向样本。
- 低置信反馈不污染 RAG。

依赖：Task 8。

## Task 12: 共同记忆与生命周期

目标：让共同记忆可用但不过度翻旧账。

任务：

- 抽取基础 `shared_memory`。
- 为记忆记录主体、客体、时间、置信度、敏感级别。
- 实现软降权。
- 实现冲突记忆 `superseded` 标记。
- 用户禁用或删除的记忆不得再进入候选。

验收：

- 共同记忆只有在当前话题相关时注入。
- `superseded` 记忆不主动注入。
- 旧记忆不会压过新的高置信记忆。

依赖：Task 7、Task 8。

## Task 13: 前端控制面板

目标：让用户能看到和控制 RAG 状态。

任务：

- 设置页展示 RAG 总开关。
- 展示远程 RAG 脱敏开关和风险确认。
- 展示远程 embedding 开关和风险确认。
- 展示索引状态、索引数量、更新时间、占用空间。
- 支持联系人级启用、禁用、清空、重建索引。

验收：

- 用户能一键关闭 RAG。
- 用户能清除某个联系人的 RAG 数据。
- 关闭远程 RAG 脱敏前必须看到风险提示。

依赖：Task 3、Task 9。

## Task 14: 固定人工样例集

目标：建立 RAG v1 的回归评估基础。

任务：

- 建立匿名/脱敏样例集。
- 覆盖冷场、安抚、邀约、解释、争执降温、共同记忆唤醒、敏感记忆不注入、铺垫后回复。
- 支持无 RAG 与有 RAG 输出对比。
- 记录人工评估维度：策略、记忆、风格、隐私、身份区分。

验收：

- 每次 RAG/prompt/脱敏/反馈归因改动后都能复用样例集。
- RAG 输出不得在关系策略、隐私安全、身份区分上劣于无 RAG。

依赖：Task 8、Task 11、Task 12。

## 推荐实施顺序

1. Task 0: 基线与开关
2. Task 1: 数据结构与迁移
3. Task 2: 通用隐私脱敏服务
4. Task 3: RAG Store 与索引状态
5. Task 4: 本地 Embedding 适配
6. Task 5: 联系人级懒加载索引
7. Task 6: 后台增量索引队列
8. Task 7: RAG Retriever 与上下文构造
9. Task 8: LLM 建议链路接入
10. Task 9: 远程 RAG 脱敏与高级关闭
11. Task 10: 脱敏异常降级
12. Task 11: 反馈归因
13. Task 12: 共同记忆与生命周期
14. Task 13: 前端控制面板
15. Task 14: 固定人工样例集

