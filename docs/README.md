# 文档导航

这里只保留当前仍需要维护的说明、计划和发布证据。已经完成或被取代的方案、施工单和评测快照统一放在 [`archive/`](archive/README.md)。

## 发布说明

历次发布说明见本目录 `release-notes-v*.md`（最新：[v2.2.0](release-notes-v2.2.0.md)）。

## 当前文档

- [RAG v4 分阶段改造计划](rag-v4-improvement-plan.md)：产品和工程改造项与口径。
- [RAG v4 后评估报告](rag-v4-post-evaluation-report.md)：运行数据、已验证结论和未验证风险。
- [RAG v4 发布摘要](goals/rag-v4-soul-restoration-goal.md)：P0–P3 发布门禁和冻结基线摘要（注意其中 superseded 标记）。
- [G1 生成目标与契约](goals/g1-generation-goal.md)：生成链路设计约束（`generation_context`/`task_router` 的上游引用），验收证据见 [G1 端到端验收报告](goals/g1-e2e-report.md)。
- [前端视觉规范](frontend-visual-system.md)：墨痕暖白令牌与惯用语速查（改样式先读它）。
- [推理优化路线图](inference-optimization-roadmap.md)：已验证结论与待实施优化项（含已证伪项，勿重复试错）。
- [P0.3 回归标注流程](p0.3-regression-labeling-guide.md)：挖掘脚本产出的脱敏 JSONL 两轮标注流程。

## 当前评测产物

`goals/` 中保留 v4 冻结集与 G1 运行评测数据；`analysis/` 中保留后评估脚本生成的脱敏运行统计与口径文档（time-depth / profile-window / incremental_analysis）。JSON 是脚本输入或输出，修改前请先确认对应脚本的默认路径（`backend/scripts/g1_*.py`、`backend/scripts/audit_rag_v4_post_eval.py` 等）。

## 其他项目文档

- [项目说明](../Readme.md)
- [打包说明](../packaging/README.md)
- [微信数据库适配层说明](../backend/app/services/wechat/db/README.md)
