# 文档导航

这里保留当前仍需维护的说明、计划与发布证据。已完结的目标/方案文档以原文留存（内含 superseded 标记，引用数字前注意甄别）；一次性施工单完成后移入 `archive/`（本地目录，不入库）。

## 发布说明

历次发布说明见本目录 `release-notes-v*.md`（最新：[v2.3.1](release-notes-v2.3.1.md)）。

## 当前文档

- [RAG v4 分阶段改造计划](rag-v4-improvement-plan.md)：产品和工程改造项与口径（P0.3 人工回归集仍在待办，前置是使用数据积累）。
- [RAG v4 后评估报告](rag-v4-post-evaluation-report.md)：运行数据、已验证结论和未验证风险。
- [RAG v4 发布摘要](goals/rag-v4-soul-restoration-goal.md)：P0–P3 发布门禁和冻结基线摘要（注意其中 superseded 标记）。
- [G1 生成目标与契约](goals/g1-generation-goal.md)：生成链路设计约束（`generation_context`/`task_router` 的上游引用）。
- [画像分段目标](goals/persona-chapters-goal.md)：画像分段与章节摘要契约（`chapter_summaries`/`relationship_chapters` 的上游引用）。
- [前端视觉规范](frontend-visual-system.md)：墨痕暖白令牌与惯用语速查（改样式先读它）。
- [推理优化路线图](inference-optimization-roadmap.md)：已验证结论与待实施优化项（含已证伪项，勿重复试错）。
- [P0.3 回归标注流程](p0.3-regression-labeling-guide.md)：挖掘脚本产出的脱敏 JSONL 两轮标注流程（数据到量后建人工回归集）。
- [情感蒸馏 v2 验收](analysis/sentiment-v2-acceptance.md)：情感引擎 v2（LLM 教师蒸馏 RBT3 学生）的验收数据与已知限制。

## 当前评测产物

`goals/` 中保留 v4 冻结集与 G1 运行评测数据；`analysis/` 中保留口径文档（time-depth / profile-window / incremental_analysis）与后评估脚本生成的脱敏运行统计。JSON 是脚本输入或输出，修改前请先确认对应脚本的默认路径（`backend/scripts/g1_*.py`、`backend/scripts/audit_rag_v4_post_eval.py` 等）。

## 其他项目文档

- [项目说明](../README.md)
- [打包说明](../packaging/README.md)
- [微信数据库适配层说明](../backend/app/services/wechat/db/README.md)
