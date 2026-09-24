# Chrono Trace RAG v4 补魂目标

## 状态

**定位修正（2026-09-25，P1.5）**：文首原表述“P0–P3 全部通过测试与量化门禁”已过时。P0.4a 质量门清理后，本文引用的 runtime gold 基线（fact-path Recall@5=`0.6316`/`0.7105`）已标记 **superseded**——该集 38 条 gold 事实中 87% 本身是碎片化单轮记忆，冻结数字不再构成发布依据。

现行验收口径：
- **存活 gold 命中率**：质量门清理后存活 gold 的检索命中（4/5），用于确认检索侧无回退；
- **人工事实质量抽查**：按用户实测反馈对真实库事实逐条核对（拦截/自包含/证据可溯），结果记录于 `docs/rag-v4-improvement-plan.md` 各轮条目；
- **全量后端回归**：当前 726 passed、21 skipped（含 P1.5 新增 15 项）。

新的人工回归集（P0.3 规划的 60–100 条）**尚未建立**，建立前不得以任何冻结数字宣称“全部通过”。v4 时期的三路对照数字（fact-path Recall@5=`0.6316`、MRR=`0.4504`、faithfulness=`0.3256`；敏感阻断 precision/recall=`1.0/1.0`；当时回归 659 passed）保留仅作历史参考。

口径说明（2026-09-23 统一）：上文"高于 document-RAG"中的 document-RAG 指标以 `rag-v4-runtime-gold-eval-report.json` 为准——Recall@5/MRR=`0`，faithfulness=`0.0465`（非 0）；no-RAG faithfulness=`0.0698`。faithfulness 分母统一为每 track 43 cases（含无 evidence 的 no-RAG case），judge 版本 `nli-external-required-v1`。

P0.4 置信度校准后（同 gold 集回放）：fact-path Recall@5=`0.7105`（CI [0.5526, 0.8421]）、MRR=`0.5026`（CI [0.3697, 0.6447]），skip/no-hit 率不变，document 基线不变。校准详情见 `docs/rag-v4-improvement-plan.md` P0.4。

质量门与簇合并（2026-09-24）后，上述 runtime gold 基线**标记失效（superseded）**：抽查证实该集 38 条 gold 事实中 33 条（87%）本身是碎片化单轮记忆（如"我以为你在测试""我都起防了"），被 `rag_fact_quality` 质量门正确隔离。清理后回放 Recall@5=`0.1053` 的暴跌源于目标集失效而非检索回退——存活 5 条 gold 的命中率为 4/5。后续基线待 P0.3 人工回归集从清理后事实池（242 条 active）与 LLM 结构化抽取重建，不再使用模型生成诊断集作为发布依据（与后评估报告结论一致）。

## 目标

把当前联系人级长期记忆从“可写入、可检索”推进到“事实可维护、语义可召回、可验证发布”：

1. 新旧事实出现修正、失效或重复时，保留审计链并只向读侧暴露有效事实。
2. 事实读侧使用 768 维向量混合召回，不能依赖字面 n-gram 重合。
3. 收窄遗留时间窗、门控和查询拼接造成的误拒与污染。
4. 以检索、答案证据忠诚度和三路对照数字决定阈值与发布。

## 施工顺序

1. P0：写入侧维护循环与事实向量召回。
2. P1：删除时间窗、简化事实门控、瘦身检索 query。
3. P2：去除领域硬编码，扩展事实注入预算与呈现。
4. P3：建立可重复的指标、三路对照和发布门禁。

P0、P1 未完成前不实施 P2、P3 的产品逻辑。

## 全局验收红线

- RAG 失败必须安全降级，不能阻塞建议生成。
- 融合判定异常时只 ADD，不误推翻；禁止删除事实行。
- 向量维度不匹配必须显式失败或降级，禁止截断/补零。
- 敏感事实不得进入 prompt 或远程模型。
- 每条关键路径要记录 `degrade_reason` 和 `gate_decision`。

## 任务索引

- [P0：事实维护与向量召回](../archive/execution/rag-v4/rag-v4-p0-tasks.md)
- [P1：读侧收敛](../archive/execution/rag-v4/rag-v4-p1-tasks.md)
- [P2：泛化与注入](../archive/execution/rag-v4/rag-v4-p2-tasks.md)
- [P3：评测与发布门禁](../archive/execution/rag-v4/rag-v4-p3-tasks.md)

## 勾选与提交规则

每个可勾选项必须先完成对应单测或集成测试，再更新本文件与阶段 task 文件；每个完成的可交付单元使用 `feat：中文说明` 创建本地 commit。用户的 `.vscode/settings.json` 变更不纳入提交。
