# RAG v4 发布后修复：热上下文伪命中

问题：索引处于 `pending` 时，系统把实时缓冲中的临时 `hot_context` 计为历史记忆命中；仅含当前用户问题或缺少可靠时间戳的消息也可能进入该通道，导致前端显示“参考命中”，但模型没有可回答的历史证据。

## 修复与验收

- [x] 根据 `rag_retrieval_logs` 复现：请求日志为 `strategy=hot_context`、`document_id=-1`、`index_status=pending`，不是事实记忆命中。
- [x] 热上下文只接受真实、正数时间戳；缺失时间戳的历史行不再伪装成当前消息。
- [x] 热上下文至少包含一条对方消息；当前用户自己的查询不能作为它自己的历史证据。
- [x] 增加单测覆盖“仅自己当前提问”和“无时间戳旧消息”两种伪命中；`backend/tests/test_rag_v1.py` 通过 `47 passed`。
- [x] 用实际联系人库复验“我们一起玩过什么游戏”：索引 ready 后命中 `strategy=facts` 的 4 条非空 `fact_memory`，每条均附 3 个 evidence ID。
- [x] 完整后端回归通过：`660 passed, 21 skipped, 20 warnings`。

回归约束：`hot_context` 仅是正在进行的双方对话辅助，不得替代联系人历史事实，也不得在 UI 上作为历史检索命中误导用户。
