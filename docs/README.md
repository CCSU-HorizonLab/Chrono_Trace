# 文档导航

这里只保留当前仍需要维护的说明、计划和发布证据。已经完成或被 v4 取代的方案、施工单和评测快照统一放在 [`archive/`](archive/README.md)。

## 发布说明

- [Beta 1.1（v1.1.0-beta.1，2026-09-25）](release-notes-v1.1.0-beta.1.md)：记忆系统（RAG v4）集中落地版本。

## 当前文档

- [RAG v4 分阶段改造计划](rag-v4-improvement-plan.md)：当前待实施的产品和工程改造项。
- [RAG v4 后评估报告](rag-v4-post-evaluation-report.md)：最新运行数据、已验证结论和未验证风险。
- [RAG v4 发布摘要](goals/rag-v4-soul-restoration-goal.md)：P0–P3 发布门禁和冻结基线摘要。
- [py_wx_key 接入任务](goals/py-wx-key-chrono-trace-tasks.md)：仍在进行中的独立任务。

## 当前评测产物

`goals/` 中保留 v4 当前冻结集、模板和运行评测结果；`analysis/` 中保留后评估脚本生成的脱敏运行统计。JSON 是脚本输入或输出，修改前请先确认对应脚本的默认路径。

- [运行统计](analysis/rag-v4-post-eval-runtime-stats.json)
- [运行 gold 集](goals/rag-v4-runtime-gold-36.json)
- [运行评测报告](goals/rag-v4-runtime-gold-eval-report.json)
- [NLI 校验报告](goals/rag-v4-runtime-gold-nli-validation.json)
- [gold ID 模板](goals/rag-v4-gold-id-map.template.json)
- [NLI 答案模板](goals/rag-v4-nli-answers.template.json)

## 其他项目文档

- [项目说明](../Readme.md)
- [打包说明](../packaging/README.md)
- [微信数据库适配层说明](../backend/app/services/wechat/db/README.md)
