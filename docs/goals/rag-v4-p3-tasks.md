# RAG v4 P3：评测数轴与发布门禁

依赖：P0、P1、P2 全部完成并通过回归。

## P3-1 指标、三路对照与门禁

- [ ] 扩展冻结 gold 集到 30–50 个问题→事实对，覆盖共同记忆、偏好、计划、承诺、冲突降温、敏感阻断。
- [ ] 脚本输出 Recall@5、MRR、门控 skip/no-hit 率和 reason 分布，并保留逐 case 明细。
- [ ] 对脱敏答案与注入 evidence 进行蕴含判定，输出 faithfulness 分数、judge 版本与 prompt 版本。
- [ ] 生成 no-RAG、document-RAG、fact-path 三路报告 JSON，保存到 `docs/goals/`。
- [ ] 设定门禁：fact-path 三项指标均不低于 document-RAG；安全和身份隔离不得回退。
- [ ] 运行完整评测、更新勾选并提交 `feat：建立长期记忆评测门禁`。
