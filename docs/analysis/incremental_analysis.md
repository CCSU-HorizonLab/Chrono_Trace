# 增量分析：设计与已知限制

## 机制概述

2026-09 落地的增量分析方案 = **嵌入持久缓存（L2）+ 全算法重算 + stale 状态机**。

成本勘察结论：历史分析 99% 耗时在嵌入（text2vec-base-chinese CPU）。因此增量化的核心
是把 `text→vector` 落库复用（`embedding_cache` 表，键 = `content_sha1 + model + device`），
算法本身保持全量重算语义——乱序到达、回填、撤回后重导等任何消息集变化都天然正确，
无需行级增量的守卫与回退路径。

三级缓存：L1 内存 dict（进程内，4000 FIFO）→ L2 `embedding_cache` 表（跨进程）→ 模型
encode。统一入口 `SentimentService._get_embeddings_batch`；会话切分 / 交互对相似度 /
话题延续兜底三条路径全部经此入口（此前后两条直调 encode 绕过缓存，冷跑双倍编码）。

新鲜度状态机：导入/监听回溯写入新消息 → `conversations.analysis_stale=1`（同时删除
`preprocessing_stats_v2_{id}` 统计缓存行）→ 前端「待更新」徽标 → 重新分析（此时只嵌
新文本，秒级）→ 完成点写 `analysis_stale=0` + 消息数快照。

验证：`backend/tests/test_incremental_analysis_equivalence.py`（10 场景金标准对照）+
`backend/tests/test_ingest_idempotency.py`（导入幂等与对账）+
`backend/scripts/verify_incremental_analysis.py`（真实库冷/暖/增量/金标准计时对照）。

**等价性口径**（真实库实测 590 条消息，2026-09）：
- 同一初始编码的**暖跑/增量路径 bit 级一致**（暖跑 diff 恒为空）——L2 往返无损；
- 两次**独立冷跑**之间的相似度有 ≤1e-6 的 torch 批组合噪声（编码结果随
  batch 分组在 float32 epsilon 级漂移，实测 ~1.2e-7）——金标准对照用 1e-6
  容差，非缓存缺陷；
- 实测加速：冷跑 110s → 暖跑 5.2s（21x）、增量 30 条后重跑 9.1s（12x）。

## 关键不变量

1. **`text→vector` 是模型的纯函数**：`PREPROCESSING_ALGO_VERSION` bump 只失效统计缓存，
   **不需要**清 embedding_cache。算法变化不改变向量本身。
2. **键含 model + device**：换模型 repo id / cpu↔cuda 自动隔离。GPU 与 CPU 的浮点噪声
   (~1e-3) 足以在相似度阈值边界翻转会话切分结果，故设备入键（代价：每设备各存一份）。
3. **零向量禁止写 L2**：模型缺失时的兜底产物只在内存中流转，绝不持久化。
4. **stale 的真源是写入钩子**（touched_conversations），不是 max(timestamp) 对比——
   重复导入（OR IGNORE 全跳过）不产生 touched，不误报。

## 已知限制

| 限制 | 现状 | 后续方向 |
|---|---|---|
| **撤回消息永不修正** | `INSERT OR IGNORE` 不更新已入库内容；微信库里被撤回消息 local_id 不变，本地保留撤回前文本 | 冲突时 content 不同则 UPSERT（需谨慎：编辑/撤回与重导的区分） |
| **24h 安全窗外的迟到消息会漏**（导入水位） | 水位增量只读 `[水位-24h, now+24h]`；更早到达的乱序消息不在窗内（微信 create_time 实际单调、WAL 延迟秒级，风险极低） | `force_full` 选项兜底全量重扫（UI 暂未暴露） |
| realtime↔long 对账窗口 ±59s | UIA 实时时间戳为分钟级截断；超出 59s 的同一物理消息会双份留存 | 以微信库 sort_seq 为权威做二次对账 |
| cpu/cuda 各存一份嵌入 | 键隔离的必然代价（正确性优先） | 接受；可跑 `clear_embedding_cache.py --clear` 回收 |
| 模型文件原地替换但 repo id 不变 | 会读到旧向量（脏缓存） | 换模型必须改 `EMBEDDING_MODEL_REPO_ID` 或跑 clear 脚本 |
| sentiment_cache 仅按维度校验 | 无模型身份字段（既有债务，本方案未扩大） | 迁移加 model 列 |
| word_counts 按会话行 | 恒为全零占位（既有问题） | 修 `calculate_word_counts` 的 session_id 传递 |
| 中途取消的分析 | delete-first 语义下中间态允许存在（四表已删未重建），stale 不会误清 | 可接受：重跑即恢复 |
| 预载判重集合内存 ~30MB | 导入时一次性加载 (conversation_id, local_id) 全集 | 换掉 20 万次逐条 execute，值得 |

## 维护

```bash
# 嵌入缓存容量报告（只读）
python backend/scripts/clear_embedding_cache.py

# 全部清空（换模型后 / 磁盘回收）
python backend/scripts/clear_embedding_cache.py --clear

# 真实库增量等价性实测（复制库上执行，不碰原库）
python backend/scripts/verify_incremental_analysis.py \
    --db-source backend/data/chrono_trace.db --conversation-id <id>
```

关闭开关：settings.json `feature_extraction.embedding_persistent_cache: false` 或环境变量
`CHRONO_DISABLE_EMBEDDING_CACHE=1`（L2 读写全停，回到纯内存缓存行为；残留行无害）。
