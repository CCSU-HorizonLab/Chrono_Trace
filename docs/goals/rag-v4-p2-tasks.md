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
