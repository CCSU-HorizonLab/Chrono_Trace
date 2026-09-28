# G1-00 基线冻结(G0)

- **上游文档**：`docs/goals/g1-generation-goal.md` 第三节 G0
- **状态**：施工中
- **原则**：先冻结验收依据再动生成链路；所有失败必须能归类为路由、选择、脱敏、生成或安全降级问题。

## 任务清单

- [ ] 诊断样例装载器 `backend/scripts/g1_baseline_loader.py`：从真实 `rag_retrieval_logs` / `realtime_suggestions` 抽取首批 24 条样例,落盘 `docs/goals/g1-baseline-samples.json`。
- [ ] 样例字段：`sample_id`、输入原文、`account_wxid + conversation_id`、预期任务(task/output/knowledge_needs)、必须使用/禁止使用的数据、安全边界、改造前判定(任务判定、召回 ID、最终脱敏 prompt hash、模型输出、人工判定)。
- [ ] 覆盖维度:任务切换、联系人绑定、通知污染、脱敏误伤、策略适配、缺失降级(每类至少 3 条)。
- [ ] 冻结模型版本、prompt 版本、数据库快照号、代码 commit、评测版本号(记录在本文件底部"冻结记录")。
- [ ] 回放命令可重复:`python -m backend.scripts.g1_baseline_replay --sample <id> --chain no_rag|legacy|g1`。

## 验收

- 同一输入可重复回放,输出差异只来自链路变量。
- 所有失败样例可归因到固定五类:路由 / 选择 / 脱敏 / 生成 / 安全降级。

## 冻结记录

(待回填:模型、配置、DB 快照、代码版本、评测版本)
