# G1 端到端验收报告

- 报告版本:`g1-e2e-report-v1`
- 样例:`g1-baseline-samples.json`(24 条,装载器 g1-baseline-loader-v1)
- 预期标注:g1-apply-review-v1(third-review-agent;确认 24/改判 0;**人工终审前不作门禁**)
- 模型:deepseek / deepseek-flash
- 基线代码:`6b2eb4df9fef`

## 门禁检查

| 门禁 | 结果 | 明细 |
| --- | --- | --- |
| 联系人隔离 | ✅ 通过 | 检查 5 条范围受限样例 × 3 链路,违规 0,缺结果 0 |
| 任务契约 | ✅ 通过 | g1 路由与预期一致 24/24;输出契约违规 0(要话术无话术/直答无 reply) |
| 发送清单一致性 | ✅ 通过 | badge=实际发送 24/24,缺结果 0 |
| 隐私红线 | ✅ 通过 | 明文泄漏 0;evidence_redacted_unusable 留痕 0 |
| 质量红线(资金推断) | ✅ 通过 | 检查 24 条 g1 live 输出(窗口含资金事件时,输出不得把资金当态度证据),违规 0,缺结果 0 |

## 任务识别三链对照(g1 live)

| 样例 | 维度 | 预期 | no_rag | legacy | g1 | g1 输出摘要 |
| --- | --- | --- | --- | --- | --- | --- |
| real-1 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| real-2 | redaction_misfire | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 顺着她玩的游戏约，让她带你，别用指挥口气 +3话术 |
| real-3 | redaction_misfire | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | general_qa/direct_answer | reply_suggestion/suggestion_card | 用陪玩杀戮尖塔轻邀约，给她拒绝空间，别问忙不忙 +3话术 |
| authored-task_routing-00 | task_routing | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 趁出门空档轻问一句打游戏，时间让她定，不催。 +3话术 |
| authored-task_routing-01 | task_routing | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 顺着她的节奏确认周末安排，短句应下 +3话术 |
| authored-task_routing-02 | task_routing | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-task_routing-03 | task_routing | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | general_qa/direct_answer | reply_suggestion/suggestion_card | 顺着应下游戏邀约，短句不多问 +3话术 |
| authored-task_routing-04 | task_routing | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | [PURE_CHAT] |
| authored-task_routing-05 | task_routing | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-contact_binding-06 | contact_binding | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 轻松随口问，给时段也留退路 +3话术 |
| authored-contact_binding-07 | contact_binding | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 信息不足，用中性短句顺着对方话头接。 +3话术 |
| authored-contact_binding-08 | contact_binding | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 轻量收尾，不催她，留个随时能接的台阶 +3话术 |
| authored-notification_pollution-09 | notification_pollution | relationship_discussion/direct_answer | relationship_discussion/direct_answer | general_qa/direct_answer | relationship_discussion/direct_answer | [PURE_CHAT] |
| authored-notification_pollution-10 | notification_pollution | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 轻补一句给台阶，不催不施压 +3话术 |
| authored-notification_pollution-11 | notification_pollution | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | [PURE_CHAT] |
| authored-redaction_misfire-12 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-redaction_misfire-13 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-redaction_misfire-14 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-policy_adaptation-15 | policy_adaptation | relationship_discussion/direct_answer | relationship_discussion/direct_answer | general_qa/direct_answer | relationship_discussion/direct_answer | [PURE_CHAT] |
| authored-policy_adaptation-16 | policy_adaptation | relationship_discussion/answer_with_speeches | relationship_discussion/answer_with_speeches | general_qa/direct_answer | relationship_discussion/answer_with_speeches | 别急着定义，先顺今天的见面自然相处 +3话术 |
| authored-policy_adaptation-17 | policy_adaptation | relationship_discussion/answer_with_speeches | relationship_discussion/answer_with_speeches | general_qa/direct_answer | relationship_discussion/answer_with_speeches | 玩笑只自嘲，不碰钱课情绪，她回短就收。 +3话术 |
| authored-missing_scope_degrade-18 | missing_scope_degrade | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 信息不足，先给不冒进的通用接话 +3话术 |
| authored-missing_scope_degrade-19 | missing_scope_degrade | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 信息不足，先补她最后一句再定话术 +3话术 |
| authored-missing_scope_degrade-20 | missing_scope_degrade | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 轻松问有空没，给退路不逼定。 +3话术 |

## 延迟与稳定性(live)

| 链路 | n | 平均 | p50 | 最大 |
| --- | --- | --- | --- | --- |
| no_rag | 24 | 2397ms | 2358ms | 4453ms |
| legacy | 24 | 3229ms | 2747ms | 6013ms |
| g1 | 24 | 3230ms | 3103ms | 5740ms |

- 失败数:0

## 忠实度(NLI 初判,冻结证据)

- judge:g1-nli-judge-v1 / prompt `g1-faithfulness-v1` / 模型 deepseek-flash
- 汇总:**entailed=6, contradicted=0, unknown=74, 解析失败=1(单列,不计入 unknown)**
- 说明:建议话术多为新措辞,unknown 占多数是预期分布;关键红线是 contradicted=0(输出不得与已发送事实冲突)。
- 证据来源:回放结果内冻结的 `context_snapshot.sent_evidence`(不再事后重读数据库)
- 状态:`model_judged_pending_human`

## 结论与限制

- ✅ 通过 联系人隔离(`ok`)
- ✅ 通过 任务契约(`ok`)
- ✅ 通过 发送清单一致性(`ok`)
- ✅ 通过 隐私红线(`ok`)
- ✅ 通过 质量红线(资金推断)(`ok`)

已知限制(不影响门禁判定,但验收时必须知情):

- 回放只覆盖**手动生成入口**(`manual_request`);自动触发、开场、全自动入口的端到端行为尚未回放,待真实环境冒烟验证。
- 窗口与证据快照已随回放冻结(`context_snapshot`);审核包以冻结快照为准。
- 任务契约含输出契约(要话术必须有话术/直答必须有 reply),但**回答质量**(是否切题、可发送)由审核包人工/agent 终审判断。

以上基于 AI 初判预期与模型判定;**人工终审通过前,本报告不作为 G1 完成依据**(上游文档第七节)。
