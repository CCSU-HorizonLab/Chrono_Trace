# 团队分工详解 - Conversation Affinity Analysis System

**项目**: 002-affinity-analysis
**团队**: juitar + ting (2人协作)
**周期**: 5周
**最后更新**: 2026-01-09

---

## 总览

### 任务分配统计

| 开发者 | 任务数量 | 主要负责 |
|--------|---------|---------|
| **juitar** | 38任务 | 预处理核心 + 维度2/4 + 编排器 + API + 前端组件 |
| **ting** | 38任务 | 预处理态度 + 维度1/3 + 前端主视图 + 测试 + 文档 |
| **joint** | 12任务 | 预处理编排器 + 集成测试 + 最终优化 |
| **总计** | 88任务 | - |

---

## Week 1: 预处理层 (⚠️ CRITICAL PATH)

**目标**: 完成预处理层，收集29个统计常量，**阻塞所有维度工作**

### Day 1-2 (juitar || ting 完全并行)

#### juitar (7任务)
- **T016**: 创建 `test_sentiment_service.py` - SnowNLP准确性测试
- **T017**: 创建 `test_interaction_pairs.py` - 发言单位合并和交互对构建测试
- **T018**: 实现 `SentimentService` 类
  - 文件: `backend/app/services/analysis/sentiment_service.py`
  - 功能: SnowNLP集成，批量情感分析（32条/批次）
  - 输出: 极性(-1/0/1)、强度(-1到1)、句向量(384维)
- **T019**: 实现情感缓存
  - 功能: 写入/读取 `sentiment_cache` 表
  - 批量插入优化

#### ting (2任务)
- **T021**: 实现 `KeywordLibraries` 类
  - 文件: `backend/app/services/analysis/keyword_libraries.py`
  - 功能: 关键词CRUD操作
  - 支持6个分类: positive, negative, empathy, soothing, privacy, holiday
- **T022**: 创建 `test_keyword_libraries.py` - CRUD操作测试

### Day 3-4 (juitar || ting 完全并行)

#### juitar (3任务)
- **T020-A**: 实现 `BasicPreprocessingService` (Part 1: 基础统计)
  - 文件: `backend/app/services/analysis/preprocessing_service.py`
  - `collect_message_statistics()` - 4个基础常量
  - `collect_time_statistics()` - 4个时间常量
  - `collect_length_statistics()` - 2个长度常量
  - **O(N) 单次遍历**

- **T020-B**: 实现 `PairPreprocessingService` (Part 2: 交互对)
  - `build_speech_units()` - 合并连续消息 (< 5分钟)
  - `build_interaction_pairs()` - 构建交替交互对
  - `collect_pair_statistics()` - 3个交互对常量
  - 缓存到 `speech_units`, `interaction_pairs` 表

- **T020-C**: 实现 `SessionManager` (Part 3: 会话)
  - 文件: `backend/app/services/analysis/session_manager.py`
  - `split_sessions()` - 语义相似度谷值检测
  - `calculate_semantic_similarity()` - 余弦相似度
  - `collect_session_statistics()` - 3个会话常量
  - `identify_session_initiators()` - 标记会话发起人
  - 缓存到 `session_data` 表

#### ting (2任务)
- **T023**: 实现 `AttitudePreprocessingService` (Part 4: 态度统计)
  - 文件: `backend/app/services/analysis/preprocessing_service.py`
  - `collect_attitude_statistics()` - 单次遍历收集6类态度消息数
  - **O(N) vs O(6N) 复杂度** (6倍加速)
  - 使用 `KeywordLibraries` 进行模式匹配

- **T024**: 创建 `test_attitude_preprocessing.py` - 单次遍历态度统计验证

### Day 5 (joint 协作)

#### joint (1任务)
- **T025**: 实现 `PreprocessingOrchestrator` - 预处理编排器
  - 文件: `backend/app/services/analysis/preprocessing_orchestrator.py`
  - `orchestrate_preprocessing()` - 主入口，协调所有预处理服务
  - `_validate_cached_data()` - 验证缓存有效性
  - `_collect_all_statistics()` - 调用4个预处理服务
  - `invalidate_cache()` - 配置/关键词变更时失效缓存
  - `get_preprocessed_statistics()` - 返回29个常量

- **T026**: 创建 `test_preprocessing_orchestrator.py` - 端到端预处理管道测试
  - 测试1: 小对话(1,000消息) - 所有29个统计正确收集
  - 测试2: 缓存命中/未命中行为
  - 测试3: 缓存失效
  - 测试4: O(N)复杂度验证

---

## Week 2-3: 四个维度 (完全并行)

**目标**: 所有4个维度同时开发，**无协作瓶颈**

### Week 2 (juitar || ting 完全并行)

#### juitar (5任务) - 维度1 + 维度2

**维度1: 情感共振率 (30%权重)**
- **T027**: 创建 `test_emotional_resonance.py` - 5个子维度测试
- **T028**: 实现 `EmotionalResonanceService` 类
  - 文件: `backend/app/services/analysis/emotional_resonance_service.py`
  - **使用预处理统计** (O(1)查找)
  - `calculate_bidirectional_positive_response()` (20%) - 使用 `total_positive_count`, `total_interaction_pairs`
  - `calculate_polarity_consistency()` (15%) - 使用 `sentiment_cache` 嵌入
  - `calculate_intensity_matching()` (10%) - 使用 `sentiment_cache` 强度
  - `calculate_empathy_recognition()` (30%) - 使用关键词库
  - `calculate_negative_resolution()` (25%) - 使用 `interaction_pairs`

**维度2: 聊天积极度 (30%权重)**
- **T029**: 创建 `test_chat_positivity.py` - 5个子维度测试
- **T030**: 添加回复及时率边界案例测试
- **T031**: 实现 `ChatPositivityService` 类
  - 文件: `backend/app/services/analysis/chat_positivity_service.py`
  - **使用预处理统计** (O(1)查找)
  - `calculate_daily_message_count()` (10%) - 使用 `total_message_count`, `conversation_duration_days`
  - `calculate_reply_timeliness()` (20%) - 使用 `interaction_pairs`
  - `calculate_avg_message_length()` (10%) - 使用 `average_message_length`
  - `calculate_long_text_ratio()` (15%) - 使用 `long_text_message_count`
  - `calculate_topic_continuity()` (20%) - 使用 `sessions` (session_manager.split_sessions)
  - `calculate_active_initiation()` (25%) - **简化**: 使用 `session_initiators` 数组

- **T032**: 扩展 `affinity_config` 表使用
  - 文件: `backend/app/services/analysis/affinity_config.py`
  - `get_config()` - 获取配置
  - `update_config()` - 保存用户覆盖
  - `validate_config()` - 验证权重和为1.0

#### ting (4任务) - 维度3

**维度3: 态度倾向 (20%权重)**
- **T033**: 创建 `test_attitude_tendency.py` - 5个子维度测试
- **T034**: 添加关键词匹配准确性测试
- **T035**: 实现 `AttitudeTendencyService` 类
  - 文件: `backend/app/services/analysis/attitude_tendency_service.py`
  - **使用预处理统计** (O(1)查找 vs O(6N)遍历)
  - `calculate_positive_word_frequency()` (25%) - 使用 `total_positive_count`, `total_message_count`
  - `calculate_negative_word_frequency()` (-20%) - 使用 `total_negative_count`, `total_message_count`
  - `calculate_multimedia_usage()` (10%) - **优化**: 使用 `emoji_message_count`, `voice_message_count`, `video_message_count`
  - `calculate_nickname_frequency()` (25%) - 使用 `nickname_message_count`
  - `calculate_privacy_sharing()` (20%) - 使用 `privacy_message_count`
  - `calculate_holiday_greeting()` (10%) - **简化**: 使用 `holidays_sent_count`, `total_holiday_count`

- **T036**: 集成 `KeywordLibraries`
  - **注意**: KeywordLibraries已在预处理中实现(T021)，直接导入使用
  - 缺失关键词分类时优雅处理

### Week 3 (juitar || ting 完全并行)

#### juitar (4任务) - 维度4 + 编排器

**维度4: 喜好兼容度 (20%权重)**
- **T037**: 创建 `test_preference_compatibility.py` - 2个子维度测试
- **T038**: 添加空喜好关键词测试
- **T039**: 实现 `PreferenceCompatibilityService` 类
  - 文件: `backend/app/services/analysis/preference_compatibility_service.py`
  - **使用预处理统计** (O(1)查找)
  - `calculate_topic_mention_frequency()` (40%) - 使用 `total_sessions`
  - `calculate_preference_topic_continuity()` (60%) - **优化**: 重用会话语义相似度
  - `identify_preference_sessions()` - 查找包含喜好关键词的会话
  - `calculate_session_continuity()` - **优化**: 重用语义相似度逻辑

- **T040**: 添加喜好关键词到 `affinity_config`
  - 更新 `get_config()` 包含 `preference_keywords_json` 字段
  - 更新 `update_config()` 处理喜好关键词数组
  - 验证喜好关键词为非空字符串

**编排器**
- **T041**: 实现 `AffinityAnalysisService` 编排器
  - 文件: `backend/app/services/analysis/affinity_analysis_service.py`
  - **关键**: 调用 `preprocessing_orchestrator.orchestrate_preprocessing()` 在任何维度计算之前
  - `analyze()` - 主入口，触发完整分析管道
  - `_preprocess_conversation()` - 确保预处理编排器完成
  - `_calculate_all_dimensions()` - 调用所有4个维度服务（现在完全并行，无串行依赖）
  - `_calculate_overall_score()` - 加权求和
  - `reanalyze()` - 失效预处理缓存并重新分析
  - `_generate_progress_updates()` - 发出进度事件

- **T042**: 实现任务跟踪和进度报告
  - 生成唯一 `task_id`
  - 存储任务进度到内存或 `backend/data/analysis_tasks.json`
  - 处理任务取消和错误恢复

#### ting (10任务) - 后端API

**Bridge API 端点**
- **T047**: 添加 `GET /affinity/config/{conversation_id}` 端点
  - 调用 `affinity_config.get_config()`
  - 返回默认配置（如无覆盖）

- **T048**: 添加 `PUT /affinity/config/{conversation_id}` 端点
  - 验证配置（权重和为1.0）
  - 调用 `affinity_config.update_config()`
  - 返回400如果验证失败

- **T049**: 添加 `GET /affinity/keywords` 端点
  - 调用 `keyword_service.get_all_keywords()`
  - 返回所有6个分类

- **T050**: 添加 `POST /affinity/keywords` 端点
  - 接受分类和关键词数组
  - 调用 `keyword_service.add_keywords()`
  - 返回添加数量和更新后的关键词列表

- **T051**: 添加 `DELETE /affinity/keywords` 端点
  - 接受分类和关键词数组
  - 调用 `keyword_service.remove_keywords()`
  - 返回删除数量

- **T052**: 添加 `GET /affinity/preference-keywords/{conversation_id}` 端点
  - 从 `affinity_config` 检索 `preference_keywords_json`
  - 返回空数组（如未配置）

- **T053**: 添加 `PUT /affinity/preference-keywords/{conversation_id}` 端点
  - 接受关键词数组
  - 更新 `affinity_config.preference_keywords_json`

**文本生成**
- **T043**: 添加解释文本生成
  - `generate_overall_interpretation()` - 总分解释
  - `aggregate_dimension_interpretations()` - 组合所有维度的解释
  - `format_score_breakdown()` - 结构化子分数JSON

---

## Week 4: 前端 (juitar || ting 完全并行)

### ting (6任务) - 主视图 + 4个组件

- **T054**: 创建 `frontend/src/api/affinity.ts` API客户端
  - `analyzeAffinity(conversationId, forceReanalyze, configOverrides)` 函数
  - `getAffinityProgress(taskId)` 轮询函数
  - `getAffinityScores(conversationId)` 函数
  - `getAffinityConfig(conversationId)` 函数
  - `updateAffinityConfig(conversationId, config)` 函数
  - `getKeywords()` 函数
  - `addKeywords(category, keywords)` 函数
  - `removeKeywords(category, keywords)` 函数
  - `getPreferenceKeywords(conversationId)` 函数
  - `updatePreferenceKeywords(conversationId, keywords)` 函数

- **T055**: 创建 `frontend/src/views/AffinityView.vue` 主页面
  - 会话选择下拉菜单
  - "开始分析" 按钮
  - 进度条（百分比显示）
  - 总分显示（0-100大数字）
  - 4个维度分数卡片（可点击查看详情）
  - 解释文本显示
  - "重新分析" 按钮

- **T056**: 创建 `frontend/src/components/affinity/AffinityScoreCard.vue` 组件
  - Props: title, score, maxScore, interpretation
  - 可视化分数显示（圆形进度或条形图）
  - 颜色编码: 红色(0-40), 黄色(40-70), 绿色(70-100)

- **T057**: 创建 `frontend/src/components/affinity/DimensionRadar.vue` 组件
  - ECharts雷达图显示4个维度
  - Props: dimensionScores对象
  - 响应式尺寸和悬停提示

- **T058**: 创建 `frontend/src/components/affinity/SubScoreBreakdown.vue` 组件
  - Props: subScores对象, dimensionName
  - 子维度表格显示（权重和分数）
  - 可展开行显示详细解释

- **T059**: 创建 `frontend/src/components/affinity/KeywordEditor.vue` 组件
  - 6个标签页对应6个关键词分类
  - 关键词列表显示（带删除按钮）
  - "添加关键词" 输入 + 按钮每个分类
  - 保存/取消按钮
  - 调用 `addKeywords/removeKeywords` APIs

### juitar (3任务) - 配置面板 + 路由集成

- **T060**: 创建 `frontend/src/components/affinity/ConfigPanel.vue` 组件
  - 维度权重滑块（4个滑块，必须和为100%）
  - 阈值输入（回复及时性、话题延续性窗口、相似度阈值、滑动窗口大小）
  - "保存配置" 按钮（调用 `updateAffinityConfig`）
  - 验证错误消息（如果权重和不等于100%）

- **T061**: 添加 `AffinityView` 到路由
  - 文件: `frontend/src/router/index.ts`
  - 路由路径: `/affinity/:id` (其中 :id 是 conversation_id)
  - 路由名称: affinity

- **T062**: 在 `ConversationView.vue` 添加"好感度分析"标签/链接
  - 点击时导航到 `AffinityView`
  - 传递 `conversation_id` 作为路由参数

---

## Week 5: 测试 + 优化 (joint 协作)

### Day 1-2: 所有测试 (joint)

- **T063**: 完成 `test_sentiment_service.py` - SnowNLP准确性验证（>85%）
- **T064**: 完成 `test_interaction_pairs.py` - 构建算法验证
- **T065**: 完成 `test_emotional_resonance.py` - 5个子维度计算测试
- **T066**: 完成 `test_chat_positivity.py` - 5个子维度测试
- **T067**: 完成 `test_attitude_tendency.py` - 5个子维度测试
- **T068**: 完成 `test_preference_compatibility.py` - 2个子维度测试
- **T069**: 创建 `test_affinity_config.py` - 配置验证和持久化测试
- **T070**: 完成 `test_keyword_libraries.py` - CRUD操作测试

- **T071**: 创建 `test_affinity_analysis_integration.py` - 完整管道测试
  - 测试1: 小对话(1,000消息) - < 30秒
  - 测试2: 中等对话(10,000消息) - < 2分钟
  - 测试3: 验证预处理缓存失效
  - 测试4: 验证重新分析正确性
  - 测试5: 验证所有4个维度正确计算（使用预处理统计）
  - 测试6: 验证总分公式（加权求和）
  - 测试7: 验证预处理O(N)复杂度（单次遍历）

- **T072**: 运行性能基准测试 (10,000消息)
  - 目标: < 2分钟
  - 测量: 预处理时间、情感分析时间、嵌入生成时间、交互对构建时间、维度计算时间
  - 验证: 态度倾向使用预处理统计（O(1)查找 vs O(6N)遍历）
  - 记录瓶颈识别

- **T073**: 运行性能压力测试 (100,000消息)
  - 目标: < 5分钟
  - 监控: 内存使用(<2GB)、CPU使用、数据库大小
  - 识别优化机会

- **T074**: 创建 `test_edge_cases.py` - 覆盖所有边界案例
  - 空对话(0消息) - 返回0分数
  - 单条消息对话 - 优雅处理
  - 无交互对场景 - 设置基于对的度量为0
  - 情感分析失败 - 回退到中性
  - 嵌入生成失败 - 使用零向量
  - 缺失关键词分类 - 跳过维度并重新分配权重
  - 除零场景 - 返回0不崩溃
  - 极端配置值（1秒阈值、30天阈值） - 验证并建议默认值

### Day 3: 性能优化 (juitar)

- **T075**: 实现批处理优化
  - 增加批大小从32到64用于嵌入
  - 实现大对话(>10K消息)的并行处理

- **T076**: 添加句子嵌入的LRU缓存
  - 缓存大小: 10,000个最近嵌入
  - 缓存命中率日志
  - 内存使用监控

- **T077**: 实现数据库查询优化
  - 添加频繁查询列的索引
  - 对 `sentiment_cache` 和 `interaction_pairs` 使用批量插入
  - 实现查询结果缓存

### Day 4: 错误处理 + 日志 (ting)

- **T078**: 添加全面错误处理
  - 所有外部库调用周围的try-except块（SnowNLP, sentence-transformers）
  - 失败时优雅降级（回退到中性/零值）
  - UI显示的详细错误消息

- **T079**: 添加结构化日志
  - DEBUG: 算法步骤、中间值
  - INFO: 分析开始/结束、缓存命中/未命中
  - WARNING: 激活的回退、缺失数据
  - ERROR: 需要用户注意的关键失败
  - 使用Python logging模块和适当的格式化器

### Day 4: 文档 (ting)

- **T080**: 更新 `backend/README.md` 添加好感度分析部分
  - 4维评分系统概述
  - 预处理架构解释（29个统计O(N)单次遍历）
  - 配置选项解释
  - 性能基准
  - 故障排除指南

- **T081**: 创建 `frontend/src/views/AffinityView.md` 组件文档
  - Props参考
  - 事件描述
  - 使用示例
  - 截图占位符

- **T082**: 更新 `CLAUDE.md` 添加002-affinity-analysis实现注释
  - 添加到"最近更改"部分
  - 记录新预处理服务和用途
  - 记录态度倾向的O(N) vs O(6N)性能改进

### Day 5: 代码质量 + 验证 (joint)

- **T083**: 对所有新Python文件运行linter: `ruff check backend/app/services/analysis/`
- **T084**: 对所有新Vue文件运行linter: `eslint --ext .vue frontend/src/components/affinity/ frontend/src/views/`
- **T085**: 格式化所有代码符合项目风格指南
- **T086**: 运行所有后端测试: `cd backend && pytest tests/ -v`
- **T087**: 验证所有测试通过（目标: >90%通过率）
- **T088**: 运行quickstart.md验证 - 逐步遵循快速入门指南并验证所有步骤工作

---

## 协作点

### Week 1 (预处理)
- **juitar 提供 `SentimentService`** → 两人都用于情感分析
- **ting 提供 `KeywordLibraries`** → juitar用于预处理态度统计
- **joint 创建 `PreprocessingOrchestrator`** → 协调所有预处理服务

### Week 2-3 (维度 - 完全并行)
- **✅ 无协作瓶颈** - 所有维度使用预处理统计独立运行
- juitar实现 US1/US2/US4 + Orchestrator
- ting实现 US3 + Backend API

### Week 4 (前端)
- juitar实现 ConfigPanel + Router集成
- ting实现 AffinityView + 4个组件

### Week 5 (测试)
- joint协作进行集成测试、性能验证、最终优化

---

## 关键路径

### ⚠️ CRITICAL PATH: Week 1 预处理层

**Week 1 MUST完成**:
- Day 1-2: juitar (SentimentService) || ting (KeywordLibraries)
- Day 3-4: juitar (Basic/Pair/Session 预处理) || ting (Attitude 预处理)
- Day 5: joint (PreprocessingOrchestrator + 测试)

**Gate**: ⚠️ 所有29个统计必须收集并缓存后，任何维度工作才能开始

### 并行机会

**Week 2-3**: 四个维度完全并行
- juitar: US1 + US2 + US4 + Orchestrator
- ting: US3 + Backend API (10个端点)

**Week 4**: 前端完全并行
- juitar: ConfigPanel + Router集成
- ting: AffinityView + 4个组件

---

## 文件所有权

### juitar 主要负责的文件

**预处理层**:
- `backend/app/services/analysis/sentiment_service.py`
- `backend/app/services/analysis/preprocessing_service.py` (Basic/Pair/Session部分)
- `backend/app/services/analysis/session_manager.py`

**维度服务**:
- `backend/app/services/analysis/emotional_resonance_service.py` (US1)
- `backend/app/services/analysis/chat_positivity_service.py` (US2)
- `backend/app/services/analysis/preference_compatibility_service.py` (US4)
- `backend/app/services/analysis/affinity_analysis_service.py` (Orchestrator)

**前端**:
- `frontend/src/components/affinity/ConfigPanel.vue`
- `frontend/src/components/affinity/KeywordEditor.vue`
- `frontend/src/router/index.ts` (更新)

### ting 主要负责的文件

**预处理层**:
- `backend/app/services/analysis/keyword_libraries.py`
- `backend/app/services/analysis/preprocessing_service.py` (Attitude部分)

**维度服务**:
- `backend/app/services/analysis/attitude_tendency_service.py` (US3)

**API**:
- `backend/app/webview/bridge.py` (添加10个端点)

**前端**:
- `frontend/src/api/affinity.ts`
- `frontend/src/views/AffinityView.vue`
- `frontend/src/components/affinity/AffinityScoreCard.vue`
- `frontend/src/components/affinity/DimensionRadar.vue`
- `frontend/src/components/affinity/SubScoreBreakdown.vue`

### joint 主要负责的文件

**预处理编排**:
- `backend/app/services/analysis/preprocessing_orchestrator.py`

**测试**:
- 所有集成测试
- 性能测试
- 最终验证

---

## 总结

### 关键成功因素

1. **Week 1 预处理优先**: 完成29个统计的O(N)单次遍历收集
2. **Week 2-3 完全并行**: 四个维度无协作瓶颈
3. **清晰的文件所有权**: 避免Git冲突
4. **每日同步**: 确保预处理接口一致

### 风险缓解

1. **串行依赖**: 预处理层消除所有维度的串行依赖
2. **代码重复**: 预处理层统一统计收集
3. **性能退化**: O(N)预处理 + O(1)查找 vs O(6N)遍历

### 性能目标

- 预处理: < 30秒 (10K消息, O(N)单次遍历)
- 态度倾向: O(1)查找 vs O(6N)遍历 (6倍加速)
- 完整分析: < 2分钟 (10K消息, spec SC-001)
