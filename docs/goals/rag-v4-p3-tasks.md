# RAG v4 P3：评测数轴与发布门禁

依赖：P0、P1、P2 全部完成并通过回归。

## P3-1 指标、三路对照与门禁

- [x] 扩展冻结 gold 集到 36 个问题→事实对，覆盖共同记忆、偏好、计划、承诺、冲突降温、敏感阻断、无命中和最新对话。
- [x] 脚本输出 Recall@5、MRR、分层 bootstrap CI、门控 skip/no-hit 率、误拒/正确拒答和 reason 分布，并保留逐 case 明细。
- [x] 支持对脱敏答案与注入 evidence 的外部 NLI 判定输入，输出 faithfulness 分数、judge 版本与 prompt 版本；缺少 judge 数据时明确 pending。
- [x] 生成 no-RAG、document-RAG、fact-path 三路报告 JSON，保存到 `docs/goals/rag-v4-eval-report.json`；当前因无运行数据库指标为 pending_runtime_data。
- [ ] 设定门禁：fact-path 三项指标均不低于 document-RAG；安全和身份隔离不得回退。
- [ ] 运行真实回放评测、冻结 baseline 后设定门禁并提交 `feat：建立长期记忆评测门禁`。

运行记录：`backend/tests/test_evaluate_rag_retrieval.py` 2 passed；完整 backend 回归 610 passed、21 skipped、24 warnings。当前工作区没有可用的线上/回放 SQLite 日志和答案 judge 文件，因此不提前宣称发布门禁通过。
