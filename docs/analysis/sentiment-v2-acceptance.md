# 情感引擎 v2 验收记录（v2-ctx-20261107）

> 本文归档 v2 上线时的验收事实与已知限制（此前唯一存档是 model_version.json
> 的 lineage 一行，验收决定无处可查——本文件补齐，后续换代照此归档）。

## 代际事实

- **tag**：`v2-ctx-20261107`（`model_paths.SENTIMENT_MODEL_TAG`，缓存重置与
  ensure 代际门的锚点）
- **教师**：Qwen3.5-9B（内网 llama-server /v1，enable_thinking 必须关），
  打标 68000 条（含 839 补齐）；标签数据 `backend/data/distill/v2_labels.jsonl`
  本地留档不进仓库
- **学生**：hfl/rbt3（3 层×768，38M 参数），ctx 口径 = 前 3 条同会话上文拼接
- **产物**：fp16 ONNX 74MB 随 git 仓库分发（cdbab23），训练脚本
  `backend/scripts/distill_sentiment_v2.py`，换代一条龙 `regen_sentiment_model.py`

## 验收数据（留出 8000 条，对 LLM 教师标签）

| 指标 | 数值 | 门槛 | 结果 |
|---|---|---|---|
| 学生对 LLM 标签一致率 | **0.8616** | ≥0.98 | ❌ 未达 |
| 模型加速比（同 ctx 输入对旧教师） | 未归档（门槛 ≥3.0） | ≥3.0 | 未存档 |
| neg 召回 | **0.531** | — | 偏弱 |

脚本走了「未达标 → 保守采纳记录在案」出口（`distill_sentiment_v2.py`
gate 段，exit 1 不自动 export）；**用户拍板保守采纳上线**（2026-11-07，
cdbab23 入库分发）。

## 与 v1 先例的关系（数字不可直接比较）

v1 蒸馏留出一致率 97.34% 但被弃用——v1 是单条输入无 ctx，教师换人后
高一致率只说明复读了旧教师的中性化偏差。v2 的 0.8616 是对新教师（ctx
口径）的复现率，两数分母不同，不能得出「v2 比 v1 差」；也不能反推真实
准确率——**gold 本身是 LLM 教师标签，无独立人工标注**。

## 已知限制与缓解

- **约 14% 分流**：单条极性噪声大。缓解：下游消费全部聚合化——情感共鸣
  维 5 子项按单元/会话聚合、时光深度按日/周/月分桶、画像取强度方差与
  占比，趋势类指标对单条翻转不敏感。
- **neg 召回 0.531**：负面信号捕获偏弱（对「情感共鸣/负面信号」类下游
  最关键的类别）。**待办：neg 类人工抽查**——对留出集学生↔教师分歧且
  真值为 neg 的样本做一次人工判定，若抽查不达标，走 neg 过采样/类别
  阈值调整重训（regen 一条龙）。
- **ctx 口径三处微差**（训练「恰好 3 条非空」vs 生产「至多 3」；
  orchestrator/backfill 空内容消息入窗 vs monitor 不入）：短会话输入分布
  偏离训练分布。若后续统一口径，按 CLAUDE.md 约定须 bump MODEL_TAG 重训
  重导出，不可只改推理侧。
- **换代失效链**已于 e9dcb63 补全：CALIBER_VERSION 6 / PREPROCESSING_ALGO_VERSION 3 /
  DEEP_ANALYSIS_VERSION 6 + 实时缓存 purge 收敛单点，v1/v2 跨代不混口径。

## 复跑

```bash
cd backend && python scripts/distill_sentiment_v2.py eval   # 门槛复验
python scripts/regen_sentiment_model.py                      # 本机数据重蒸馏换代
```
