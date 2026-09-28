# G1-04 端到端验收(G7 发布门禁)

- **上游文档**:`docs/goals/g1-generation-goal.md` 第三节 G7、第七节阶段完成定义
- **状态**:三路 live 对照 + NLI 初判 + 报告已完成,四项门禁全绿(基于 AI 初判预期);人工终审与真实环境冒烟待做

## 任务清单

- [x] 对 G0 冻结样例运行 no-RAG、旧链路、G1 链路三路对照(`backend/scripts/g1_baseline_replay.py`,dry-run 与 live 双轮,0 失败)。
- [x] live 三路对照(真实调用 deepseek-flash,87 条 live 结果 0 失败,输出已归档)。
- [ ] 人工评估维度:任务识别、联系人隔离、证据使用、边界遵守、无关旧事、可发送性、隐私(待人工终审)。
- [x] 延迟、失败与降级记录:`docs/goals/g1-e2e-report.md`(no_rag p50≈2.4s / legacy≈2.7s / g1≈2.7s,失败 0)。
- [x] 对模型输出用脱敏 evidence 做 `entailed / contradicted / unknown` 判定(`backend/scripts/g1_nli_judge.py`,78 条判定:entailed=1 / contradicted=0 / unknown=77,`model_judged_pending_human`)。
- [x] 结果保存模型版本、prompt 版本、评测版本和原始判定(判定文件含 judge_raw_response 全文)。
- [ ] 安全指标回退时按联系人切回旧读侧或 `inherit`(fact_read_mode 已有开关,补充切换脚本)。

## 首轮门禁结论(g1-e2e-report.md)

- ✅ 联系人隔离(5 条范围受限样例 × 3 链路,违规 0——回放曾发现 relationship_signal 块泄漏,已修复并有回归测试)
- ✅ 任务契约(g1 路由与 AI 初判预期一致 24/24)
- ✅ 发送清单一致性(badge=实际发送 24/24)
- ✅ 隐私红线(结果与判定文件无明文电话/身份证;contradicted=0)
- 回放过程中发现并修复的路由缺口:显式建议追问继承、电话号码查询、无主语边界求助、"不想理我"关系讨论、邀约意图被记忆追问吞掉(均有单测锁定)

## 发布条件(全部满足才可标记 G1 完成)

- [ ] 任务契约、联系人隔离、隐私红线、最终发送清单一致性全部通过。
- [ ] 效果指标以冻结人工集基线为准,不用旧 9/10 自洽性数字替代。
- [ ] 24 条诊断样例通过安全和契约门禁。
- [ ] 失败时可按联系人回滚,事实与审计数据保留。

## 回滚与安全规则(与上游文档第五节一致)

- RAG、画像或好感分析失败不阻塞建议生成。
- 联系人范围不确定时不注入历史知识。
- 脱敏失败不发送远程原文;敏感事实不进 prompt。
- 事实冲突保留审计链,不覆盖历史证据。
