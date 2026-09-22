# RAG v4 P3：评测数轴与发布门禁

依赖：P0、P1、P2 全部完成并通过回归。

## P3-1 指标、三路对照与门禁

- [x] 扩展冻结 gold 集到 36 个问题→事实对，覆盖共同记忆、偏好、计划、承诺、冲突降温、敏感阻断、无命中和最新对话。
- [x] 脚本输出 Recall@5、MRR、分层 bootstrap CI、门控 skip/no-hit 率、误拒/正确拒答和 reason 分布，并保留逐 case 明细。
- [x] 补充敏感阻断 precision/recall 与可选联系人/会话隔离率；缺少标注时显式输出 `not_applicable` 或 `pending_runtime_data`，不将缺数据当作通过。
- [x] 发布门禁按 Recall@5、MRR、faithfulness 的 bootstrap 下界比较事实路径与 document-RAG，安全/隔离同步执行不回退判断。
- [x] 支持对脱敏答案与注入 evidence 的外部 NLI 判定输入，输出 faithfulness 分数、judge 版本与 prompt 版本；缺少 judge 数据时明确 pending。
- [x] 增加只读脱敏 NLI 输入导出：按三路回放生成 query/evidence 包，敏感证据仅保留 ID，答案与标签留给外部 judge。
- [x] 生成 no-RAG、document-RAG、fact-path 三路报告 JSON，保存到 `docs/goals/rag-v4-eval-report.json`；当前真实库有日志但未匹配冻结 gold，指标为 pending_runtime_data。
- [x] 增加可重复回放入口 `backend/scripts/replay_rag_v4.py`；真实库完成 36 query × 3 track = 108 条日志回放，结果见 `docs/goals/rag-v4-replay-report.json`。
- [x] 增加 `rag-v4-gold-id-map.template.json` 与 `rag-v4-nli-answers.template.json`，并支持 `--gold-map` / `--answers` 解锁可计算 Recall 和 faithfulness。
- [x] 增加 `prepare_rag_v4_gold_mapping.py`：当前联系人已导出 36 条本地候选，默认隐藏敏感事实内容，待人工复核后填入 gold ID 映射。
- [x] 生成当前运行库 4 条 smoke gold 并完成三路量化回放：fact-path Recall@5=`0.25`、MRR=`0.25`，document-RAG Recall@5/MRR=`0`，事实路径联系人/会话隔离率=`1.0`；该结果仅为诊断集，不能替代 36 条发布集。
- [ ] 设定门禁：fact-path 三项指标均不低于 document-RAG；安全和身份隔离不得回退。
- [ ] 运行真实回放评测、冻结 baseline 后设定门禁并提交 `feat：建立长期记忆评测门禁`。

运行记录：评测器、回放、候选导出与 NLI 输入导出单测 `9 passed`（含安全/隔离指标）；完整 backend 回归 `623 passed, 21 skipped, 24 warnings`；已从 36 条回放生成 108 条脱敏 judge 输入。36 条发布 gold 仍使用 `fact_*` 符号 ID，尚未映射到运行库数字 fact ID；同时没有已判定的答案 judge 文件，发布门禁仍未通过。
