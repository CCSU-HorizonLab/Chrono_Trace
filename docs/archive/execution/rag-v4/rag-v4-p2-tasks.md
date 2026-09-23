# RAG v4 P2：泛化与事实注入

依赖：P0、P1 全部完成并通过回归。

## P2-1 去除事实 kind 硬编码

- [x] 使用外部 `fact_kind_hints.json` 配置 kind→同义词映射；通用检索代码不写具体领域词。
- [x] 单测：`上次她想吃什么来的？` 能选择 `preference` / `event` 类事实。
- [x] 补齐历史事实表具体 kind（`hobby_or_game`、`preference_like` 等）映射，并覆盖游戏/习惯问句回归单测。
- [x] 仓库检索确认 `rag_retriever.py` 不含具体业务语料判断。
- [x] 完成回归测试（RAG 定向 79 passed；全量 620 passed、21 skipped），更新勾选并提交 `feat：补齐事实类别映射`。

## P2-2 事实注入预算与呈现

- [x] 将事实通道调整为最多 8 条、1600 字总预算；500 字以内事实不截断半句。
- [x] prompt 注入带 subject、截至时间、状态、置信度与 evidence ID。
- [x] 单测：6–8 条相关事实全部进入 prompt；500 字事实全文保留。
- [x] 完成回归测试（120 passed、2 warnings）、更新勾选并提交 `feat：扩展事实记忆注入上下文`。

## P2-3 证据辅助的泛化召回

- [x] 对历史事实的读侧排序使用绑定 evidence 消息作为辅助检索文本；不替换事实正文，也不绕过敏感过滤。
- [x] 事实向量回填支持 `force` 重建，后台任务会刷新旧的乱码/过期向量；维度校验和联系人范围保持不变。
- [x] 单测覆盖 UTF-8 evidence 恢复和乱码事实的主题召回（RAG 定向 `83 passed`）。
- [x] 当前运行库已重建联系人 `7191` 的 799 条 768 维事实向量；修正版 smoke 回放报告见 [归档评测产物](../../evaluations/rag-v4/rag-v4-runtime-smoke-v6-report.json)。
- [x] smoke 泛化问句 gold 已扩展为同联系人、同主题且 evidence 明确包含游戏/游玩语义的事实集合；v7 回放 Recall@5=`1.0`、MRR=`0.7778`。正式 36 条发布集仍需独立人工复核，不能用 smoke 结果替代。
