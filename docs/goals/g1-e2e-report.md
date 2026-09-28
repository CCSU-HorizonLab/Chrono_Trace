# G1 端到端验收报告

- 报告版本:`g1-e2e-report-v1`
- 样例:`g1-baseline-samples.json`(24 条,装载器 g1-baseline-loader-v1)
- 预期标注:g1-expected-annotate-v1(**AI 初判,人工终审前不作门禁**)
- 模型:deepseek / deepseek-flash
- 基线代码:`8b614b64cf19`

## 门禁检查

| 门禁 | 结果 | 明细 |
| --- | --- | --- |
| 联系人隔离 | ✅ 通过 | 检查 5 条范围受限样例 × 3 链路,违规 0 |
| 任务契约 | ✅ 通过 | g1 路由与预期一致 24/24 |
| 发送清单一致性 | ✅ 通过 | badge=实际发送 24/24 |
| 隐私红线 | ✅ 通过 | 明文泄漏 0;evidence_redacted_unusable 留痕 0 |

## 任务识别三链对照(g1 live)

| 样例 | 维度 | 预期 | no_rag | legacy | g1 | g1 输出摘要 |
| --- | --- | --- | --- | --- | --- | --- |
| real-1 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| real-2 | redaction_misfire | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 顺着她正在玩的游戏轻问一次，不定死时间 +3话术 |
| real-3 | redaction_misfire | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | general_qa/direct_answer | reply_suggestion/suggestion_card | 别追问忙不忙，发一句低压力游戏邀请，把选择权给她 +3话术 |
| authored-task_routing-00 | task_routing | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 趁她上地铁的节点随口约，别用邀约腔。 +3话术 |
| authored-task_routing-01 | task_routing | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 简单确认出发，别拖沓。 +5话术 |
| authored-task_routing-02 | task_routing | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-task_routing-03 | task_routing | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | general_qa/direct_answer | reply_suggestion/suggestion_card | 先确认出发碰面，游戏等见面再顺势提 +3话术 |
| authored-task_routing-04 | task_routing | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | [PURE_CHAT] |
| authored-task_routing-05 | task_routing | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-contact_binding-06 | contact_binding | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 轻松开口约游戏，留余地不施压 +3话术 |
| authored-contact_binding-07 | contact_binding | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | [PURE_CHAT] |
| authored-contact_binding-08 | contact_binding | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 撒娇续话题，继续约游戏，别碰钱 +3话术 |
| authored-notification_pollution-09 | notification_pollution | relationship_discussion/direct_answer | relationship_discussion/direct_answer | general_qa/direct_answer | relationship_discussion/direct_answer | [PURE_CHAT] |
| authored-notification_pollution-10 | notification_pollution | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | 轻松接游戏邀约，不追问不施压 +3话术 |
| authored-notification_pollution-11 | notification_pollution | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | general_qa/direct_answer | [PURE_CHAT] |
| authored-redaction_misfire-12 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-redaction_misfire-13 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-redaction_misfire-14 | redaction_misfire | memory_qa/direct_answer | memory_qa/direct_answer | general_qa/direct_answer | memory_qa/direct_answer | [PURE_CHAT] |
| authored-policy_adaptation-15 | policy_adaptation | relationship_discussion/direct_answer | relationship_discussion/direct_answer | general_qa/direct_answer | relationship_discussion/direct_answer | [PURE_CHAT] |
| authored-policy_adaptation-16 | policy_adaptation | relationship_discussion/answer_with_speeches | relationship_discussion/answer_with_speeches | general_qa/direct_answer | relationship_discussion/answer_with_speeches | 先接住出发话题，别急着定义关系 +3话术 |
| authored-policy_adaptation-17 | policy_adaptation | relationship_discussion/answer_with_speeches | relationship_discussion/answer_with_speeches | general_qa/direct_answer | relationship_discussion/answer_with_speeches | 开玩笑只自嘲或宠她，别碰钱、比较和说教。 +3话术 |
| authored-missing_scope_degrade-18 | missing_scope_degrade | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | [PURE_CHAT] |
| authored-missing_scope_degrade-19 | missing_scope_degrade | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | reply_suggestion/suggestion_card | [PURE_CHAT] |
| authored-missing_scope_degrade-20 | missing_scope_degrade | invitation_planning/answer_with_speeches | invitation_planning/answer_with_speeches | general_qa/direct_answer | invitation_planning/answer_with_speeches | 约具体的事，别说有空吗，给退路 +4话术 |

## 延迟与稳定性(live)

| 链路 | n | 平均 | p50 | 最大 |
| --- | --- | --- | --- | --- |
| no_rag | 24 | 2592ms | 2411ms | 5697ms |
| legacy | 24 | 3108ms | 2949ms | 7014ms |
| g1 | 24 | 3144ms | 2692ms | 11072ms |

- 失败数:0

## 忠实度(NLI 初判,脱敏证据)

- judge:g1-nli-judge-v1 / prompt `g1-faithfulness-v1` / 模型 deepseek-flash
- 汇总:**entailed=1, contradicted=0, unknown=77**
- 说明:建议话术多为新措辞,unknown 占多数是预期分布;关键红线是 contradicted=0(输出不得与已发送事实冲突)。
- 状态:`model_judged_pending_human`

## 结论

- ✅ 联系人隔离
- ✅ 任务契约
- ✅ 发送清单一致性
- ✅ 隐私红线

以上基于 AI 初判预期与模型判定;**人工终审通过前,本报告不作为 G1 完成依据**(上游文档第七节)。
