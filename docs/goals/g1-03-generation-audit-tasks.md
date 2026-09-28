# G1-03 生成审计(G6 最终发送清单)

- **上游文档**:`docs/goals/g1-generation-goal.md` 第三节 G6、第 2.6 节
- **状态**:代码落地（单测通过；真实回放待 G0/G7）
- **改造点**:`llm_engine._build_prompt`(发送清单收集)、`rag/store.py`(`rag_retrieval_logs` 新增列)、`_build_rag_context_summary`(badge 依据实际发送)

## 任务清单

- [x] `request_id → suggestion_id → retrieval_log_id` 关联:request_id 由 `generation_context` 生成并写入 context 与检索日志 run_provenance。
- [x] `_build_prompt` 收集 `_rag_sent_manifest`:实际渲染的块名、fact_ids、document_ids、policy_ids、偏好 ID、因任务不需要/预算/脱敏失真被排除的候选及原因。
- [x] 脱敏完成后计算最终 prompt hash(sha256)并记录。
- [x] `rag_retrieval_logs` 新增列:`sent_manifest_json`、`final_prompt_hash`、`excluded_reasons_json`、`final_prompt_snapshot`(仅诊断模式写入)。
- [x] `store.update_retrieval_log_sent_manifest` 在建议生成后回填。
- [x] 普通日志只记录 ID、版本、hash 和原因;`rag_prompt_snapshot_enabled`(默认关)开启时才保存脱敏 prompt 快照。
- [x] 前端 badge 只依据实际发送清单:候选命中但未注入/未渲染时 UI 显示"未参考命中记录",不显示"已参考"。

## 验收

- 每条"已参考"都能定位到最终 prompt 中的具体块;候选命中但未注入时 UI 不得显示已参考。
