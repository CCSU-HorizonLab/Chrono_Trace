# G1-01 上下文路由(G1 联系人范围 + G2 任务识别 + G3 近期窗口)

- **上游文档**：`docs/goals/g1-generation-goal.md` 第三节 G1/G2/G3
- **状态**：代码落地（单测通过；真实回放待 G0/G7）
- **新增模块**：
  - `backend/app/services/realtime/generation_context.py` —— 统一范围解析与上下文装配
  - `backend/app/services/realtime/task_router.py` —— task / output / knowledge_needs 三元路由
  - `backend/app/services/realtime/recent_window.py` —— 生成侧近期对话净化
- **改造点**：`bridge.generate_suggestion`、`monitor_service._handle_trigger_events`、`monitor_service._build_llm_suggestion_context`、`llm_engine.generate/_build_prompt/_classify_manual_request`

## G1 联系人范围

- [x] `resolve_generation_scope`：统一解析 `account_wxid + conversation_id`,后端校验会话属于当前账号(conversations 表 is_deleted=0 且 account 匹配)。
- [x] 显示名只作兼容解析:仅在无 conversation_id 时使用,且同名多联系人命中时返回 `ambiguous_contact`,不自动选取。
- [x] 缺失范围时安全降级:`missing_scope` / `no_contact_scope` / `conversation_not_owned` 记入 `_generation_scope_missing`,同时剥离 contact/self 画像与历史记忆注入,RAG 走既有 missing_scope 跳过。
- [x] 所有入口携带 `request_id`(uuid)与 `entrypoint`(manual / semi_auto_trigger / full_auto / listen_start),写入 context 供审计链使用。
- [x] 自动、手动、开场、全自动入口统一走 `assemble_generation_context` 装配函数(情绪摘要 / 最近消息 / 双画像 / 历史增强 / 会话线程记忆 / RAG 预热)。
- [x] 单测 `test_generation_context.py`:同名联系人、多账号、无效 ID、跨联系人切换、缺失画像、缺失分析结果。

## G2 任务识别拆分

- [x] `route_generation_task` 输出三元组:`task`(memory_qa / reply_suggestion / invitation_planning / relationship_discussion / general_qa)、`output`(direct_answer / suggestion_card / answer_with_speeches)、`knowledge_needs`(facts / contact_profile / user_style / relationship_signals)。
- [x] "我们玩过什么游戏" → memory_qa + direct_answer,只注入事实,不注入用户口头禅与建议风格。
- [x] "我想约她打游戏" → invitation_planning + answer_with_speeches,注入共同游戏/对方游戏偏好/关系信号。
- [x] "没有建议么" 等追问 → 继承上一轮建议任务并修正输出(advice_followup_inherited)。
- [x] 关系讨论即使 direct_answer 也允许画像与关系证据(knowledge_needs 含 contact_profile / relationship_signals)。
- [x] 不确定时保持安全输出:general_qa 只给 direct_answer,不代发话术。
- [x] `llm_engine` 的 `_rag_output_mode`、`_classify_manual_request`、`_build_prompt` 依赖三元组,消除"用户求建议但 speeches 强制为空"的冲突。
- [x] 单测 `test_task_router.py`:三轮任务切换、否定句、建议追问、普通闲聊、直接问 AI、代用户回复区分。

## G3 近期对话净化

- [x] `classify_message_kind` 区分 human_chat / transfer_event / system_notice / unparseable。
- [x] 通知不占用 `RECENT_MESSAGE_LIMIT` 窗口名额;`purify_recent_window` 先净化后选窗。
- [x] 转账渲染为事件行(`【事件】…非聊天发言`),不伪装成对方主动发言;正常文字提及转账保留。
- [x] 纯通知窗口(`notice_only`)时 prompt 追加守卫:不得据此推导冷淡、拒绝、已读不回。
- [x] `compute_chart_stats` 修复配对:回复率改为"我方消息的下一条是对方"的紧邻配对;回复间隔改为 我方→对方回复 的差值;统计排除 transfer_event / system_notice。
- [x] 单测 `test_recent_window.py` + `test_historical_context.py`。

## 验收

- 同一联系人不同入口的 fact / profile / policy 来源一致;跨联系人注入为零。
- 不存在"用户明确求建议但 prompt 强制 speeches 为空"。
- 转账通知密集窗口仍保留有效聊天;模型不再因通知得出错误关系判断。
