# RAG 记忆意图触发优化任务拆分

本文把 [RAG 记忆意图触发优化 Goal](./rag-memory-intent-trigger-goal.md) 拆成可执行任务。

## Task 0: 基线确认与样例固化

目标：先固定当前问题和验收样例，避免后续只凭主观感觉判断。

任务：

- [x] 收集当前误触发、漏触发和 no-hit 幻觉样例。
- [x] 固定最小人工样例集。
- [x] 样例至少覆盖 direct reply、suggestion、连续追问、无关输入、索引无结果。
- [x] 记录当前日志表现：是否能看到 RAG 触发、命中和注入。

验收：

- 至少有 8 条固定样例。
- 每条样例都有预期 `memory_intent_mode`。
- 每条样例都有预期输出形态：reply 或 suggestion。

依赖：无。

## Task 1: MemoryIntent 数据结构

目标：建立统一的记忆意图输出，避免各模块各自判断。

任务：

- [x] 定义 `MemoryIntent` 数据结构。
- [x] 字段包括 `should_retrieve`、`mode`、`confidence`、`query`、`reason`。
- [x] 模式限定为 `none / ambient / memory_request / relationship_context`。
- [x] 提供默认值，确保异常时返回 `none` 而不是中断建议生成。

验收：

- 所有调用方拿到统一结构。
- 空输入、异常输入、缺少上下文时不会崩溃。
- `none` 模式不会触发 RAG。

依赖：Task 0。

## Task 2: 记忆意图检测器

目标：用更自然的方式判断是否需要 RAG，减少关键词硬编码。

任务：

- [x] 新增独立 `memory_intent.py`。
- [x] 保留少量高精度规则作为兜底。
- [x] 增加语义原型匹配，用少量代表性句子判断是否像记忆请求。
- [x] 增加关系策略判断，识别“这个人适不适合”“按我们关系怎么回”等场景。
- [x] 本地 embedding 不可用时，降级到轻量规则和结构化上下文。

验收：

- “她上次说的什么流派我不知道”触发 `memory_request`。
- “这个人现在适合开玩笑吗”触发 `relationship_context`。
- “你好，测试一下”返回 `none`。
- 不需要维护大量关键词也能通过固定样例。

依赖：Task 1。

## Task 3: 上下文继承

目标：支持用户多轮追问时自然延续记忆意图。

任务：

- [x] 在最近 2-4 轮用户与 AI 交互中查找高置信记忆意图。
- [x] 当前输入是追问、补充、要求建议或要求解释时，允许继承上一轮意图。
- [x] 联系人切换或明显话题切换时停止继承。
- [x] 继承时重新生成当前 query，不直接复用旧 query。

验收：

- 用户先问“找一下上次她说杀戮尖塔的记录”，再问“那给我个相关建议”，第二轮仍可使用 RAG。
- 用户切换联系人后不继承旧联系人意图。
- 用户明显换话题后不继承旧意图。

依赖：Task 2。

## Task 4: RAG Context Builder 接入 MemoryIntent

目标：让 RAG 构造由记忆意图驱动，而不是由 reply/suggestion 或关键词直接驱动。

任务：

- [x] `rag_context_builder` 接收 `MemoryIntent`。
- [x] `should_retrieve = true` 时执行联系人级检索。
- [x] `mode = ambient` 时只允许轻量关系背景或低成本检索。
- [x] 检索为空时生成 no-hit guard。
- [x] RAG 超时或异常时保留原降级行为。

验收：

- direct reply 场景也能触发 RAG。
- suggestion 场景也能触发 RAG。
- 检索为空时仍能把 no-hit 状态传给 prompt。
- RAG 异常不影响原建议生成。

依赖：Task 2、Task 3。

## Task 5: 双模式 Prompt 注入

目标：根据输出形态使用不同 RAG 注入方式。

任务：

- direct reply 使用 `【可用历史记忆检索结果】`。
- suggestion 使用 `【联系人级共同记忆 RAG】`。
- no-hit 使用 `【历史记忆检索状态】`。
- prompt 明确要求模型不能编造检索结果之外的历史。
- 最近对话优先级仍高于 RAG。

验收：

- 用户直接问“她上次说的什么流派”时，AI 回答查到或没查到，不强行出建议卡片。
- 用户说“给我个相关建议”时，AI 可以生成话术建议。
- no-hit 场景模型不会编具体流派、店名、事件细节。

依赖：Task 4。

## Task 6: 日志与调试输出

目标：让开发者能清楚判断 RAG 是否真的生效。

任务：

- 增加 `[RAG Intent]` 日志。
- 记录 mode、confidence、query、reason。
- 增加 `[RAG] retrieved` 日志，记录 hit count 和 latency。
- 增加 `[RAG] injected` 日志，记录 injection mode 和 no-hit guard。
- 避免日志输出长篇原始聊天内容和强敏信息。

验收：

- 从日志能判断一次请求是否触发 RAG。
- 从日志能判断模型说“没找到”是不是系统真实检索后的结果。
- no-hit、timeout、disabled、failed 等状态可区分。

依赖：Task 4、Task 5。

## Task 7: 回归样例与人工验收

目标：验证优化确实改善触发自然度，而不是增加误触发。

任务：

- 扩展固定人工样例集。
- 覆盖明确记忆请求、隐含记忆请求、关系策略请求、普通闲聊、普通话术、no-hit。
- 对比优化前后 RAG 触发、命中、输出质量。
- 记录误触发率、漏触发率、no-hit 诚实率。

验收：

- 明确记忆请求召回率达到人工可接受水平。
- 普通闲聊不会频繁触发 RAG。
- no-hit 场景不编造历史。
- RAG 输出不劣于无 RAG 原链路。

依赖：Task 6。

## 推荐实施顺序

1. Task 0: 基线确认与样例固化
2. Task 1: MemoryIntent 数据结构
3. Task 2: 记忆意图检测器
4. Task 3: 上下文继承
5. Task 4: RAG Context Builder 接入 MemoryIntent
6. Task 5: 双模式 Prompt 注入
7. Task 6: 日志与调试输出
8. Task 7: 回归样例与人工验收
