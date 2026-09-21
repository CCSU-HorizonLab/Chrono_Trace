# RAG v4 P1：读侧收敛

依赖：P0 全部完成并通过回归。

## P1-1 删除遗留“刚”字时间窗

- [ ] 删除 document fallback 的 `_time_scope` / `_within_time_scope` 硬过滤，并确认事实路径不引入等价时间窗。
- [ ] 保留事实的 `as_of`、时间衰减和 supersede 链作为时间语义来源。
- [ ] 单测：`我刚下班` 不会过滤一周前但与问题直接相关的文档。
- [ ] 完成回归测试、更新勾选并提交 `feat：移除RAG刚字时间硬过滤`。

## P1-2 事实路径单层门控

- [ ] 事实命中跳过 ordinary 双闸与 utterance 专用的 recent-overlap off-topic 合取。
- [ ] 保留一个可配置总分阈值与 `memory_request` 的放行规则；阈值初值及后续修改必须由评测报告记录。
- [ ] document fallback 的 `MIN_VECTOR_SCORE_WITHOUT_KEYWORDS` 过渡到 0.30，记录为待 P3 校准项。
- [ ] 单测：摄影展事实面对“加班”近聊，仍能回答“她之前提过啥想去的”。
- [ ] 完成回归测试、更新勾选并提交 `feat：收敛事实读侧门控`。

## P1-3 检索 query 瘦身

- [ ] 使检索 query 只包含 `memory_intent.query` 与最新用户输入；展示上下文继续由 hot context 承载。
- [ ] 删除 expanded terms 的领域硬编码词表。
- [ ] 单测：四条近聊不会污染检索 query，query 不含“我：”“对方：”前缀串。
- [ ] 仓库检索确认通用 RAG 逻辑不再含“杀戮尖塔”等具体评测语料。
- [ ] 完成回归测试、更新勾选并提交 `feat：瘦身长期记忆检索查询`。
