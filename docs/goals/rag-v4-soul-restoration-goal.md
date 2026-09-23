# Chrono Trace RAG v4 补魂目标

## 状态

已完成。P0–P3 全部通过测试与量化门禁。最终冻结集包含 38 条运行事实数字 ID 样例和 5 条敏感安全样例；fact-path Recall@5=`0.6316`、MRR=`0.4504`、faithfulness=`0.3256`，对应 bootstrap 下界均高于 document-RAG；敏感阻断 precision/recall=`1.0/1.0`，联系人/会话隔离率=`1.0`，发布门禁为 `pass`。全量后端回归：659 passed、21 skipped、24 warnings；前端构建与 smoke 在 P3 前序阶段通过。

口径说明（2026-09-23 统一）：上文"高于 document-RAG"中的 document-RAG 指标以 `rag-v4-runtime-gold-eval-report.json` 为准——Recall@5/MRR=`0`，faithfulness=`0.0465`（非 0）；no-RAG faithfulness=`0.0698`。faithfulness 分母统一为每 track 43 cases（含无 evidence 的 no-RAG case），judge 版本 `nli-external-required-v1`。

P0.4 置信度校准后（同 gold 集回放）：fact-path Recall@5=`0.7105`（CI [0.5526, 0.8421]）、MRR=`0.5026`（CI [0.3697, 0.6447]），skip/no-hit 率不变，document 基线不变。校准详情见 `docs/rag-v4-improvement-plan.md` P0.4。

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
