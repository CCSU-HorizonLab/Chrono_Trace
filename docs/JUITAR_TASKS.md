# Juitar 的任务清单 - 好感度分析功能

**功能**: 002-affinity-analysis
**更新时间**: 2026-01-13
**状态**: 阶段2进行中 (预处理层 85% 完成,会话切分逻辑已合并优化)

---

## 📋 任务概览

| 阶段           | 任务数       | 预计工作量        |
| -------------- | ------------ | ----------------- |
| 1. 数据库设置  | 1            | 简单              |
| 2. 预处理层    | 7            | 中等              |
| 3. 维度分析    | 6            | 中等              |
| 4. 编排器      | 2            | 中等              |
| 5. 后端API     | 3            | 简单              |
| 6. 前端实现    | 4            | 中等              |
| 7. 性能优化    | 3            | 简单              |
| **总计** | **26** | **约2-3周** |

---

## 阶段1: 数据库设置 (简化版)

**说明**: 开发阶段直接重建数据库,不需要迁移脚本

### T001: 添加好感度分析相关表到 schema.sql ✅

- [X] 在 `backend/app/db/schema.sql` 末尾添加6个新表:
  1. `sentiment_cache` - 情感分析缓存表
  2. `speech_units` - 发言单元表
  3. `interaction_pairs` - 交互对表
  4. `affinity_config` - 配置表
  5. `keyword_libraries` - 关键词库表
  6. `affinity_scores` - 评分表
- [X] 删除 `backend/data/chrono_trace.db` (下次初始化时)
- [X] 重新运行数据库初始化脚本 (下次初始化时)

**参考**: `specs/002-affinity-analysis/data-model.md` 第54-338行
**完成时间**: 2026-01-11

---

## 阶段2: 预处理层 (⚠️ 关键路径)

**重要性**: 必须先完成预处理,才能开始任何维度分析
**性能目标**: O(N) 单次遍历收集所有统计信息

### T002: 情感服务测试 ✅

- [X] 创建 `backend/tests/test_sentiment_service.py`
- [X] 测试SnowNLP情感分类准确率 (>85%)
- [X] 测试强度映射 (-1到1)
- [X] 测试向量生成 (384维)

**完成时间**: 2026-01-13

### T003: 交互对测试 ✅

- [X] 创建 `backend/tests/test_interaction_pairs.py`
- [X] 测试发言单元合并 (< 5分钟间隔)
- [X] 测试交互对构建 (双向交替)

**完成时间**: 2026-01-13

### T004: 实现情感服务 ✅

**文件**: `backend/app/services/analysis/sentiment_service.py`

- [X] 实现SentimentService类
- [X] `analyze_sentiment()` 方法
  - 返回: polarity (-1/0/1), intensity (-1到1), embedding (384维向量)
  - 延迟加载SnowNLP和sentence-transformers模型
- [X] `analyze_batch()` 方法
  - 批处理: 32条消息/批次
  - 失败时回退到中性值 (0, 0, 零向量)
- [X] `cache_sentiment_result()` 方法 - 写入缓存
- [X] `get_sentiment_from_cache()` 方法 - 读取缓存
- [X] `batch_cache_sentiments()` 方法 - 批量插入
- [X] LRU缓存 (10,000个句子嵌入)
- [X] `get_cache_stats()` 方法 - 缓存统计

**完成时间**: 2026-01-13

### T005: 实现基础预处理服务 ✅

**文件**: `backend/app/services/analysis/preprocessing_service.py`

- [X] BasicPreprocessingService.collect_message_statistics()
  - total_message_count
  - total_positive_count
  - total_negative_count
  - total_neutral_count
- [X] BasicPreprocessingService.collect_time_statistics()
  - conversation_start_timestamp
  - conversation_end_timestamp
  - conversation_duration_days
  - chat_days_count
- [X] BasicPreprocessingService.collect_length_statistics()
  - total_characters
  - average_message_length

**完成时间**: 2026-01-13

### T006: 实现交互对预处理服务 ✅

**文件**: `backend/app/services/analysis/preprocessing_service.py`

- [X] PairPreprocessingService.build_speech_units()
  - 合并同一发送者的连续消息 (< 5分钟间隔)
- [X] PairPreprocessingService.build_interaction_pairs()
  - 创建发言单元间的双向交替配对
- [X] PairPreprocessingService.collect_pair_statistics()
  - total_interaction_pairs
  - bidirectional_pairs
  - same_parity_pairs
  - avg_time_gap_seconds
  - avg_time_gap_minutes
- [X] PairPreprocessingService.save_speech_units() - 写入数据库
- [X] PairPreprocessingService.save_interaction_pairs() - 写入数据库(含预计算语义相似度)
- [X] PairPreprocessingService.load_cached_pairs() - 从缓存读取

**完成时间**: 2026-01-13

### T007: 实现会话管理器 ✅

**文件**: `backend/app/services/analysis/preprocessing_service.py`

- [X] SessionManager.split_sessions()
  - 通过语义相似度谷值切分会话
  - 滑动窗口 + 谷值检测算法
- [X] SessionManager.calculate_semantic_similarity() - 余弦相似度
- [X] SessionManager.collect_session_statistics()
  - total_sessions
  - average_session_length
  - average_session_gap
- [X] SessionManager.identify_session_initiators() - 标记会话发起者
- [X] SessionManager.save_sessions() - 写入缓存
- [X] SessionManager.load_cached_sessions() - 读取缓存

**完成时间**: 2026-01-13

**注**: SessionManager 已实现在 preprocessing_service.py 中,而非独立文件 session_manager.py

---

## ✅ 阶段2总结: 预处理层完成情况

### 已完成任务 (6/7)

| 任务 | 状态 | 完成时间 | 说明 |
|------|------|---------|------|
| T002 | ✅ | 2026-01-13 | 情感服务测试 (20+ 测试用例) |
| T003 | ✅ | 2026-01-13 | 交互对测试 (15+ 测试用例) |
| T004 | ✅ | 2026-01-13 | 情感服务 (320行代码) |
| T005 | ✅ | 2026-01-13 | 基础预处理服务 (170行代码) |
| T006 | ✅ | 2026-01-13 | 交互对预处理服务 (340行代码) |
| T007 | ✅ | 2026-01-13 | 会话管理器 (300行代码) |

### 完成度统计

- **代码文件**: 3个核心服务类
  - `sentiment_service.py` (320行)
  - `preprocessing_service.py` (扩展1300行)
  - `__init__.py` (更新导出)

- **测试文件**: 2个测试套件
  - `test_sentiment_service.py` (350行)
  - `test_interaction_pairs.py` (400行)

- **功能覆盖**:
  - ✅ 情感分析 (polarity/intensity/embedding)
  - ✅ 批处理 (32条/批次)
  - ✅ LRU缓存 (10,000个句子)
  - ✅ 基础统计 (消息/时间/长度)
  - ✅ 发言单元合并 (5分钟规则)
  - ✅ 交互对构建 (双向交替)
  - ✅ 会话切分 (睡眠时间+时间间隔+语义相似度，三重切分)

### ⚠️ 缺失功能 (15%)

1. ~~**会话切分缺少时间回退** (history_analyze.md 要求)~~ ✅ 已完成
   - 已添加: 如果时间间隔 > 30分钟,强制切分
   - 完成时间: 2026-01-13

2. ~~**会话切分缺少睡眠时间检测**~~ ✅ 已完成 (2026-01-13)
   - 已合并 FeatureExtractionService 的睡眠时间切分逻辑
   - 跨越午夜或00:00-07:00时段自动切分
   - 与语义+时间切分合并为三重切分规则

3. **态度预处理服务** (T023, ting 负责)
   - 6个态度统计未实现
   - 阻塞: 态度倾向维度分析

4. **预处理编排器** (T025, joint 任务)
   - 需要协调所有预处理服务
   - 阻塞: 所有维度分析

### 与 Spec 符合度

| 模块 | Spec 要求 | 实现状态 | 符合度 |
|------|----------|---------|--------|
| 情感服务 | 100% | ✅ 完全实现 | 100% |
| 基础统计 | 100% | ✅ 完全实现 | 100% |
| 交互对 | 100% | ✅ 完全实现 | 100% |
| 会话管理 | 100% | ✅ 完全实现含时间回退 | 100% |
| **总计** | - | - | **100%** |

### 与 history_analyze.md 符合度

| 步骤 | 要求 | 实现状态 | 符合度 |
|------|------|---------|--------|
| 3. 情感分析 | 批处理+向量+强度 | ✅ 完全实现 | 100% |
| 4. 会话划分 | 睡眠+时间+语义 | ✅ 完全实现 | 100% |
| 5.1 发言单位合并 | 5分钟规则 | ✅ 完全实现 | 100% |
| 5.2 交互对构建 | 双向交替 | ✅ 完全实现 | 100% |
| 5.3 基础统计 | 10项统计 | ✅ 实现7项 | 70% |
| **总计** | - | - | **94%** |

### 🆕 会话切分优化说明 (2026-01-13)

**优化前**:
- FeatureExtractionService: 时间间隔(30分钟) + 睡眠时间切分
- SessionManager: 时间间隔(30分钟) + 语义相似度切分
- 问题：两个版本并存，逻辑重复，功能不完整

**优化后**:
- 合并为统一的 SessionManager，实现三重切分规则：
  1. **睡眠时间切分** (优先级最高): 跨越午夜或00:00-07:00时段
  2. **时间间隔切分**: 时间间隔 > 30分钟
  3. **语义相似度切分**: 相似度 < 0.5 且为局部谷值
- 优点：智能识别会话边界，更准确反映真实对话流程

**测试覆盖**:
- ✅ 16个测试用例全部通过
- ✅ 包含睡眠时间切分、时间间隔切分、语义切分的测试
- ✅ 跨越午夜、00:00-07:00时段等边界情况测试

### 🆕 前端自动加载优化 (2026-01-14)

**优化前**:
- 进入分析页面需要手动选择联系人
- 需要点击"提取特征"按钮才能看到特征数据
- 问题：导入时特征已经计算，但界面不自动显示

**优化后**:
- 页面加载时自动选择第一个联系人
- 自动加载并显示特征数据（主动率、响应时间、字数比等）
- "提取特征"按钮仅用于重新提取（算法更新后）
- 优点：用户直接看到分析结果，体验更流畅

**修改文件**: `frontend/src/views/AnalysisPage.vue`
**修改内容**: 在 `onMounted` 钩子中添加自动加载逻辑

---

## 🎯 下一步工作

### 立即需要 (阻塞维度分析)

1. ~~**合并会话切分逻辑**~~ ✅ 已完成
   - 已将 FeatureExtractionService 的睡眠时间切分合并到 SessionManager
   - 完成时间: 2026-01-13

2. **等待 ting 完成**:
   - T022: 关键词库测试
   - T023: 态度预处理服务

3. **联合实现** (T025):
   - PreprocessingOrchestrator
   - 协调所有预处理服务
   - 收集29个统计常量

---

## 阶段3: 维度分析 (与ting并行)

**依赖**: 必须完成阶段2 (预处理层)

### T008: 实现聊天积极度服务

**文件**: `backend/app/services/analysis/chat_positivity_service.py`

- [ ] calculate_daily_message_count() (10%权重)
- [ ] calculate_reply_timeliness() (20%权重)
- [ ] calculate_avg_message_length() (10%权重)
- [ ] calculate_long_text_ratio() (15%权重)
- [ ] calculate_topic_continuity() (20%权重) - 使用会话管理器的sessions
- [ ] calculate_active_initiation() (25%权重) - 简化版:使用预处理层的session_initiators
- [ ] calculate_overall_positivity() - 加权总分 (0-100)
- [ ] generate_interpretation() - 生成解释文本

### T009: 扩展配置表使用

**文件**: `backend/app/services/analysis/affinity_config.py`

- [ ] get_config() - 获取配置(含默认值)
- [ ] update_config() - 保存用户覆盖
- [ ] validate_config() - 验证权重和为1.0, 阈值在有效范围

### T010: 实现喜好兼容度服务

**文件**: `backend/app/services/analysis/preference_compatibility_service.py`

- [ ] calculate_topic_mention_frequency() (40%权重)
- [ ] calculate_preference_topic_continuity() (60%权重) - 优化:复用预处理的语义相似度
- [ ] identify_preference_sessions() - 找到包含喜好关键词的会话
- [ ] calculate_session_continuity() - 优化:复用预处理的相似度逻辑
- [ ] calculate_overall_compatibility() - 加权总分 (0-100)
- [ ] generate_interpretation() - 生成解释文本

### T011: 喜好关键词配置集成

**文件**: `backend/app/services/analysis/affinity_config.py`

- [ ] 更新get_config()包含preference_keywords_json字段
- [ ] 更新update_config()处理喜好关键词数组
- [ ] 验证关键词为非空字符串

### T012: 喜好兼容度测试

- [ ] 创建 `backend/tests/test_preference_compatibility.py`
- [ ] 测试2个子维度计算
- [ ] 测试空喜好关键词场景

---

## 阶段4: 编排器

**依赖**: 所有4个维度服务完成

### T013: 实现主分析服务编排器

**文件**: `backend/app/services/analysis/affinity_analysis_service.py`

- [ ] analyze() 方法 - 主入口点
  - **关键**: 先调用preprocessing_orchestrator.orchestrate_preprocessing()
  - 触发完整分析流程
- [ ] _preprocess_conversation() - 确保预处理完成
- [ ] _calculate_all_dimensions() - 调用4个维度服务(现在完全并行)
- [ ] _calculate_overall_score() - 加权总分
  - emotional_resonance × 0.3
  - chat_positivity × 0.3
  - attitude_tendency × 0.2
  - preference_compatibility × 0.2
- [ ] _save_results() - 写入affinity_scores表
- [ ] get_scores() - 获取缓存分数
- [ ] reanalyze() - 使缓存失效并重新分析
- [ ] _generate_progress_updates() - 发送进度事件

### T014: 实现任务跟踪和进度报告

**文件**: `backend/app/services/analysis/affinity_analysis_service.py`

- [ ] 为每次分析生成唯一task_id (格式: "affinity_{conversation_id}_{timestamp}")
- [ ] 存储任务进度到内存或 `backend/data/analysis_tasks.json`
- [ ] 更新progress_percent (0-100) 和current_step描述
- [ ] 处理任务取消和错误恢复

---

## 阶段5: 后端API

### T015: 添加分析触发端点

**文件**: `backend/app/webview/bridge.py`

- [ ] POST /affinity/analyze
  - 接受: conversation_id, force_reanalyze, config_overrides
  - 返回: task_id, estimated_duration_ms

### T016: 添加进度查询端点

**文件**: `backend/app/webview/bridge.py`

- [ ] GET /affinity/progress/{task_id}
  - 返回: status, progress_percent, current_step, error, result

### T017: 添加分数查询端点

**文件**: `backend/app/webview/bridge.py`

- [ ] GET /affinity/scores/{conversation_id}
  - 调用affinity_service.get_scores()
  - 未分析时返回404

---

## 阶段6: 前端实现

### T018: 创建配置面板组件

**文件**: `frontend/src/components/affinity/ConfigPanel.vue`

- [ ] 4个维度权重滑块 (必须总和100%)
- [ ] 阈值输入 (回复及时阈值、话题延续窗口、相似度阈值、滑动窗口大小)
- [ ] "保存配置"按钮
- [ ] 验证错误提示

### T019: 创建关键词编辑器组件

**文件**: `frontend/src/components/affinity/KeywordEditor.vue`

- [ ] 6个标签页对应6个关键词分类
- [ ] 关键词列表显示 (带删除按钮)
- [ ] 每个分类的"添加关键词"输入框+按钮
- [ ] 保存/取消按钮
- [ ] 调用addKeywords/removeKeywords API

### T020: 添加路由

**文件**: `frontend/src/router/index.ts`

- [ ] 路由路径: /affinity/:id
- [ ] 路由名称: affinity
- [ ] 参数: id为conversation_id

### T021: 添加导航入口

**文件**: `frontend/src/views/ConversationView.vue`

- [ ] 添加"好感度分析"标签/链接
- [ ] 点击跳转到AffinityView
- [ ] 传递conversation_id

---

## 阶段7: 性能优化

### T022: 批处理优化

**文件**: `backend/app/services/analysis/sentiment_service.py`

- [ ] 将embedding批处理大小从32增加到64
- [ ] 对大对话(>10K条消息)实现并行处理

### T023: LRU缓存

**文件**: `backend/app/services/analysis/sentiment_service.py`

- [ ] 缓存10,000个最近的句子嵌入
- [ ] 缓存命中率日志
- [ ] 内存使用监控

### T024: 数据库查询优化

**文件**: `backend/app/db/connection.py`

- [ ] 为频繁查询的列添加索引
- [ ] 批量插入sentiment_cache和interaction_pairs
- [ ] 实现查询结果缓存

---

## 📅 建议执行顺序

### 第1周: 预处理层 (与ting并行)

```
Day 1-2: T002-T004 (情感服务 + 测试)
Day 3-4: T005-T007 (基础/交互对/会话预处理)
Day 5: 联合调试 (与ting的预处理集成)
```

### 第2周: 维度分析 (与ting完全并行)

```
Day 1-2: T008-T009 (聊天积极度)
Day 3-4: T010-T012 (喜好兼容度)
Day 5: T013-T014 (编排器)
```

### 第3周: API + 前端 (与ting并行)

```
Day 1-2: T015-T017 (后端API)
Day 3-5: T018-T021 (前端组件)
```

### 第4周: 优化

```
Day 1-3: T022-T024 (性能优化)
```

---

## ✅ 验收标准

每个阶段完成后:

- [ ] 所有单元测试通过 (>90%覆盖率)
- [ ] 与ting的代码集成测试通过
- [ ] 代码符合项目规范 (ruff lint通过)

---

## 📚 相关文档

- **数据模型**: `specs/002-affinity-analysis/data-model.md`
- **完整任务**: `specs/002-affinity-analysis/tasks.md`
- **API契约**: `specs/002-affinity-analysis/contracts/`
- **开发指南**: `docs/DEVELOPMENT.md`

---

**准备就绪!** 🚀

从T001开始,按顺序执行即可。遇到问题随时询问。
