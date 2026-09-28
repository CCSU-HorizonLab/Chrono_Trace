# G1-00 基线冻结(G0)

- **上游文档**:`docs/goals/g1-generation-goal.md` 第三节 G0
- **状态**:工具与样例已落地(dry-run 回放 0 失败);预期任务的人工判定与 live 输出归档待做
- **原则**:先冻结验收依据再动生成链路;所有失败必须能归类为路由、选择、脱敏、生成或安全降级问题。

## 任务清单

- [x] 诊断样例装载器 `backend/scripts/g1_baseline_loader.py`:从真实 `rag_retrieval_logs` / `realtime_suggestions` 抽取样例,落盘 `docs/goals/g1-baseline-samples.json`(真实日志 3 条 + authored 21 条 = 24 条)。
- [x] 样例字段:`sample_id`、输入原文、`account_wxid + conversation_id`、预期任务(task/output/knowledge_needs,authored 由当前路由器自动给出 `auto_pending_human`,真实日志 `human_required`)、必须使用/禁止使用的数据、安全边界、改造前判定(旧二分任务、召回 fact_ids、prompt hash、模型输出)。
- [x] 覆盖维度:任务切换(6)、联系人绑定(3)、通知污染(3)、脱敏误伤(6)、策略适配(3)、缺失降级(3)。
- [x] 冻结模型版本、数据库指纹、代码 commit、装载器版本(写入样例文件 `meta`)。
- [x] 回放命令可重复:`python backend/scripts/g1_baseline_replay.py --chain no_rag|legacy|g1 [--sample <id>] [--live]`。
- [x] 预期标注 `backend/scripts/g1_annotate_expected.py`:24 条全部给出 task/output/knowledge_needs/must_use/forbidden/safety 与判定依据(`ai_first_pass_pending_human`,人工终审前不作门禁)。
- [ ] 每条样例的预期任务经人工终审(确认前不作为发布门禁依据)。
- [x] 三路 live 输出已完成并归档(`g1-replay-results.json`,72+15 条 live 结果 0 失败)。

## 验收

- 同一输入可重复回放,输出差异只来自链路变量(回放在 DB 临时副本上运行,真实库零写入)。
- 所有失败样例可归因到固定五类:路由 / 选择 / 脱敏 / 生成 / 安全降级。
- 首轮 dry-run:72 条链路结果(24 样例 × 3 链路)0 失败,见 `docs/goals/g1-replay-results.json`。

## 冻结记录

- 代码 commit:`653d99ff`(样例生成时)+ 后续 G0/G7 工具 commit
- 数据库:`backend/data/chrono_trace.db`(167 会话 / 569 事实 / 7657 文档 / 3 检索日志,指纹见样例文件 meta.db)
- 模型:deepseek / deepseek-flash(live 调用需 `--live`,产生 API 费用)
- 装载器:`g1-baseline-loader-v1`;回放器:`g1-baseline-replay-v1`
- legacy 链路说明:行为等价重建(旧二分关键词路由 + 未净化窗口),不是逐字节复刻
