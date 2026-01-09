# 好感度分析系统 - 简化协作指南 (推荐)

**项目**: Chrono Trace - Feature 002
**功能**: Conversation Affinity Analysis System
**开发者**: juitar & ting
**创建日期**: 2026-01-08
**最后更新**: 2026-01-09
**架构**: 预处理优先 (Preprocessing-First)
**分支策略**: **直接在master上开发** (适合2人小团队)

---

## 🎯 简化工作流 (推荐)

### 为什么在master上开发?

您说得对! 对于2人小团队,**直接在master上开发更简单**:
- ✅ 无需管理多个分支
- ✅ 实时看到对方代码
- ✅ 避免合并冲突
- ✅ 提交历史更清晰

**唯一要求**:
- ⚠️ 每次提交前确保代码可运行
- ⚠️ 在提交信息中标注作者 `[juitar]` 或 `[ting]`
- ⚠️ 关键里程碑打标签(tag)

---

## 📋 开发流程

### 1. 初始设置 (只需一次)

```bash
# 两人都需要执行
git clone https://github.com/Juitar/Chrono_Trace.git
cd Chrono_Trace
git checkout master
git pull origin master

# 确保在master分支
git branch
# 应显示: * master
```

### 2. 查看文档 (必需!)

```bash
# 查看任务列表 (88个任务，预处理优先架构)
cat specs/002-affinity-analysis/tasks.md

# 查看快速入门指南
cat specs/002-affinity-analysis/quickstart.md

# 查看功能规格 (包含FR-000到FR-025预处理需求)
cat specs/002-affinity-analysis/spec.md

# 查看实施计划 (包含预处理架构设计决策)
cat specs/002-affinity-analysis/plan.md

# 查看技术研究
cat specs/002-affinity-analysis/research.md
```

### 3. 日常开发流程

#### **juitar 的典型工作日**:

```bash
# 1. 拉取最新代码
git pull

# 2. 创建功能文件
# 例如: backend/app/services/analysis/sentiment_service.py

# 3. 编写代码
# ...

# 4. 测试代码
cd backend
pytest tests/test_sentiment_service.py -v

# 5. 提交代码
git add backend/app/services/analysis/sentiment_service.py
git commit -m "[juitar] 实现SnowNLP情感分析服务

- 集成SnowNLP和sentence-transformers
- analyze_sentiment()方法返回极性、强度、句向量
- 批处理支持(batch_size=32)
- 失败时降级到中性(0,0,零向量)

任务: T019"

# 6. 推送到远程
git push
```

#### **ting 的典型工作日**:

```bash
# 1. 拉取最新代码
git pull

# 2. 创建功能文件
# 例如: frontend/src/views/AffinityView.vue

# 3. 编写代码
# ...

# 4. 提交代码
git add frontend/src/views/AffinityView.vue
git commit -m "[ting] 实现好感度分析UI主页面

- 总体评分显示(0-100分)
- 4个维度评分卡片
- 进度条显示
- 配置面板集成
- 调用affinity API获取数据

任务: T051"

# 5. 推送到远程
git push
```

### 4. 提交规范

**格式**:
```
[作者] 简短描述 (不超过50字)

详细说明(可选):
- 功能点1
- 功能点2
- 功能点3

任务编号: TXXX
关联需求: FR-XXX或US# (可选)
```

**示例**:
```bash
git commit -m "[juitar] 实现交互对构建算法

- build_speech_units(): 合并5分钟内连续消息
- build_interaction_pairs(): 构建交替交互对
- calculate_semantic_similarity(): 余弦相似度计算
- 支持批量处理和缓存

任务: T020 | 依赖: T019"
```

### 5. 关键里程碑打标签

当完成重要功能时,打标签记录:

```bash
# 完成情感共振率(US1)
git tag -a us1-emotional-resonance -m "完成US1: 情感共振率分析
- 5个子维度全部实现
- 测试通过
- 可独立演示"
git push origin us1-emotional-resonance

# 完成聊天积极度(US2)
git tag -a us2-chat-positivity -m "完成US2: 聊天积极度分析
- 5个子维度全部实现
- 与US1组成MVP"
git push origin us2-chat-positivity

# MVP完成
git tag -a v0.1.0-mvp -m "MVP版本发布
- 包含情感共振率+聊天积极度(60%权重)
- 可演示核心功能"
git push origin v0.1.0-mvp

# 完整版发布
git tag -a v1.0.0 -m "完整版发布
- 所有4个维度完成
- 前后端完整集成
- 所有测试通过"
git push origin v1.0.0
```

### 6. 查看任务进度

```bash
# 查看最近的提交
git log --oneline -10

# 查看某个作者的提交
git log --author="[juitar]" --oneline

# 查看标签
git tag -l

# 查看某个标签的详细信息
git show v0.1.0-mvp
```

---

## 📊 任务分工概览 (预处理优先架构)

### 任务分配统计

| 开发者 | 任务数量 | 主要负责 |
|--------|---------|---------|
| **juitar** | 38任务 | 预处理核心 + 维度1/2/4 + 编排器 + API + 前端组件 |
| **ting** | 38任务 | 预处理态度 + 维度3 + 前端主视图 + 测试 + 文档 |
| **joint** | 12任务 | 预处理编排器 + 集成测试 + 最终优化 |
| **总计** | 88任务 | - |

**关键架构**: 预处理优先 - Week 1完成29个统计的O(N)单次遍历收集，Week 2-3四维度完全并行

---

## 📅 详细周计划 (预处理优先架构)

### Week 1: 预处理层 (⚠️ CRITICAL PATH)

**目标**: 完成预处理层，收集29个统计常量，**阻塞所有维度工作**

#### Day 1-2 (juitar || ting 完全并行)

**juitar (7任务)**:
- **T016**: 创建 `test_sentiment_service.py` - SnowNLP准确性测试
- **T017**: 创建 `test_interaction_pairs.py` - 发言单位合并和交互对构建测试
- **T018**: 实现 `SentimentService` 类
  - 文件: `backend/app/services/analysis/sentiment_service.py`
  - 功能: SnowNLP集成，批量情感分析（32条/批次）
  - 输出: 极性(-1/0/1)、强度(-1到1)、句向量(384维)
- **T019**: 实现情感缓存
  - 功能: 写入/读取 `sentiment_cache` 表
  - 批量插入优化

**ting (2任务)**:
- **T021**: 实现 `KeywordLibraries` 类
  - 文件: `backend/app/services/analysis/keyword_libraries.py`
  - 功能: 关键词CRUD操作
  - 支持6个分类: positive, negative, empathy, soothing, privacy, holiday
- **T022**: 创建 `test_keyword_libraries.py` - CRUD操作测试

#### Day 3-4 (juitar || ting 完全并行)

**juitar (3任务)**:
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

**ting (2任务)**:
- **T023**: 实现 `AttitudePreprocessingService` (Part 4: 态度统计)
  - 文件: `backend/app/services/analysis/preprocessing_service.py`
  - `collect_attitude_statistics()` - 单次遍历收集6类态度消息数
  - **O(N) vs O(6N) 复杂度** (6倍加速)
  - 使用 `KeywordLibraries` 进行模式匹配

- **T024**: 创建 `test_attitude_preprocessing.py` - 单次遍历态度统计验证

#### Day 5 (joint 协作)

**joint (1任务)**:
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

**Checkpoint**: ⚠️ CRITICAL GATE - 预处理完成，ALL 29统计可用

---

### Week 2: 四个维度 (完全并行)

**目标**: 所有4个维度同时开发，**无协作瓶颈**

#### juitar (5任务) - 维度1 + 维度2

**维度1: 情感共振率 (30%权重)**:
- **T027**: 创建 `test_emotional_resonance.py` - 5个子维度测试
- **T028**: 实现 `EmotionalResonanceService` 类
  - 文件: `backend/app/services/analysis/emotional_resonance_service.py`
  - **使用预处理统计** (O(1)查找)
  - `calculate_bidirectional_positive_response()` (20%) - 使用 `total_positive_count`, `total_interaction_pairs`
  - `calculate_polarity_consistency()` (15%) - 使用 `sentiment_cache` 嵌入
  - `calculate_intensity_matching()` (10%) - 使用 `sentiment_cache` 强度
  - `calculate_empathy_recognition()` (30%) - 使用关键词库
  - `calculate_negative_resolution()` (25%) - 使用 `interaction_pairs`

**维度2: 聊天积极度 (30%权重)**:
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

**维度3: 态度倾向 (20%权重)**:
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

---

### Week 3: 维度4 + 编排器 + API (完全并行)

#### juitar (4任务) - 维度4 + 编排器

**维度4: 喜好兼容度 (20%权重)**:
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

**编排器**:
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

**Bridge API 端点**:
- **T047**: 添加 `GET /affinity/config/{conversation_id}` 端点
- **T048**: 添加 `PUT /affinity/config/{conversation_id}` 端点
- **T049**: 添加 `GET /affinity/keywords` 端点
- **T050**: 添加 `POST /affinity/keywords` 端点
- **T051**: 添加 `DELETE /affinity/keywords` 端点
- **T052**: 添加 `GET /affinity/preference-keywords/{conversation_id}` 端点
- **T053**: 添加 `PUT /affinity/preference-keywords/{conversation_id}` 端点

**文本生成**:
- **T043**: 添加解释文本生成
  - `generate_overall_interpretation()` - 总分解释
  - `aggregate_dimension_interpretations()` - 组合所有维度的解释
  - `format_score_breakdown()` - 结构化子分数JSON

---

### Week 4: 前端 (juitar || ting 完全并行)

#### ting (6任务) - 主视图 + 4个组件

- **T054**: 创建 `frontend/src/api/affinity.ts` API客户端
- **T055**: 创建 `frontend/src/views/AffinityView.vue` 主页面
- **T056**: 创建 `frontend/src/components/affinity/AffinityScoreCard.vue` 组件
- **T057**: 创建 `frontend/src/components/affinity/DimensionRadar.vue` 组件
- **T058**: 创建 `frontend/src/components/affinity/SubScoreBreakdown.vue` 组件
- **T059**: 创建 `frontend/src/components/affinity/KeywordEditor.vue` 组件

#### juitar (3任务) - 配置面板 + 路由集成

- **T060**: 创建 `frontend/src/components/affinity/ConfigPanel.vue` 组件
- **T061**: 添加 `AffinityView` 到路由
- **T062**: 在 `ConversationView.vue` 添加"好感度分析"标签/链接

---

### Week 5: 测试 + 优化 (joint 协作)

#### Day 1-2: 所有测试 (joint)

- **T063-T070**: 完成所有单元测试
- **T071**: 创建 `test_affinity_analysis_integration.py` - 完整管道测试
- **T072**: 运行性能基准测试 (10,000消息) - 目标: < 2分钟
- **T073**: 运行性能压力测试 (100,000消息) - 目标: < 5分钟
- **T074**: 创建 `test_edge_cases.py` - 覆盖所有边界案例

#### Day 3: 性能优化 (juitar)

- **T075**: 实现批处理优化
- **T076**: 添加句子嵌入的LRU缓存
- **T077**: 实现数据库查询优化

#### Day 4: 错误处理 + 日志 (ting)

- **T078**: 添加全面错误处理
- **T079**: 添加结构化日志

#### Day 4: 文档 (ting)

- **T080**: 更新 `backend/README.md` 添加好感度分析部分
- **T081**: 创建 `frontend/src/views/AffinityView.md` 组件文档
- **T082**: 更新 `CLAUDE.md` 添加002-affinity-analysis实现注释

#### Day 5: 代码质量 + 验证 (joint)

- **T083-T088**: Linter、格式化、测试验证、quickstart验证

---

## 📦 文档位置

所有规划文档都在 `specs/002-affinity-analysis/` 目录:

- [tasks.md](specs/002-affinity-analysis/tasks.md) - **必读! 88个任务列表 (预处理优先架构)**
- [quickstart.md](specs/002-affinity-analysis/quickstart.md) - 快速入门指南
- [spec.md](specs/002-affinity-analysis/spec.md) - 功能规格 (包含FR-000到FR-025预处理需求)
- [plan.md](specs/002-affinity-analysis/plan.md) - 实施计划 (包含预处理架构设计决策)
- [research.md](specs/002-affinity-analysis/research.md) - 技术研究 (SnowNLP、sentence-transformers选择)

**当前工作流文档**:
- [SIMPLE_WORKFLOW.md](docs/SIMPLE_WORKFLOW.md) - **本文档! 2人协作Git工作流 + 详细周计划 (预处理优先)**

---

## 💬 沟通机制

### 每日同步

**时间**: 每天晚上9:00
**方式**: 微信语音或文字
**内容**:
- 今天完成了哪些任务
- 遇到了什么问题
- 明天计划做什么
- 需要对方协助吗

### 代码审查

虽然直接在master开发,**但仍需互相查看对方的代码**:

```bash
# 每天至少一次
git pull

# 查看对方最近的改动
git log --author="[ting]" --oneline -5
git log --author="[juitar]" --oneline -5

# 查看具体改动
git show <commit-hash>

# 或直接看文件
git diff HEAD~1 backend/app/services/analysis/
```

### 冲突预防

```bash
# 开始工作前一定要先pull
git pull

# 如果对方有新提交,先看再改
git log --oneline -5

# 完成工作后立即push
git push

# 如果push失败,说明对方也提交了
# 先pull再push
git pull --rebase
git push
```

---

## 🚨 紧急情况处理

### 如果代码有问题

```bash
# 回退到上一个稳定版本
git revert HEAD

# 或回退到某个标签
git reset --hard v0.1.0-mvp

# 强制推送(谨慎使用!)
git push --force
```

### 如果需要实验性功能

```bash
# 临时创建分支实验
git checkout -b experiment-xxx

# 实验失败,删除分支
git checkout master
git branch -D experiment-xxx

# 实验成功,合并回master
git checkout master
git merge experiment-xxx
git branch -d experiment-xxx
```

---

## 📦 文档位置

所有规划文档都在 `specs/002-affinity-analysis/` 目录:

- [tasks.md](specs/002-affinity-analysis/tasks.md) - **必读! 84个任务列表**
- [quickstart.md](specs/002-affinity-analysis/quickstart.md) - 快速入门指南
- [spec.md](specs/002-affinity-analysis/spec.md) - 功能规格
- [plan.md](specs/002-affinity-analysis/plan.md) - 实施计划
- [COLLABORATION_GUIDE.md](specs/002-affinity-analysis/COLLABORATION_GUIDE.md) - 原始详细指南

---

## ✅ 开始第一步

### juitar 的第一个任务

```bash
# 1. 拉取最新代码
git pull

# 2. 安装依赖
cd backend
# 编辑 requirements.txt,添加:
# snownlp>=0.12.3
# sentence-transformers>=2.2.0
# scikit-learn>=1.3.0
# torch>=2.0.0

pip install -r requirements.txt

# 3. 创建sentiment_service.py
# 参考 quickstart.md 中的代码示例

# 4. 提交
git add backend/requirements.txt backend/app/services/analysis/sentiment_service.py
git commit -m "[juitar] 添加SnowNLP依赖并实现情感分析服务骨架

任务: T001, T019"
git push
```

### ting 的第一个任务

```bash
# 1. 拉取最新代码
git pull

# 2. 创建keyword_libraries.py
# 参考 quickstart.md 中的代码示例

# 3. 提交
git add backend/app/services/analysis/keyword_libraries.py
git commit -m "[ting] 实现关键词库管理服务

- get_keywords(): 按类别获取关键词
- add_keywords(): 添加自定义关键词
- remove_keywords(): 删除关键词
- get_all_keywords(): 获取所有6个类别

任务: T022"
git push
```

---

## 🎯 成功标准 (预处理优先架构)

### Week 1结束 (预处理层)
- ✅ 所有29个预处理统计收集完成
- ✅ SentimentService + KeywordLibraries可用
- ✅ BasicPreprocessingService + PairPreprocessingService + SessionManager + AttitudePreprocessingService完成
- ✅ PreprocessingOrchestrator集成测试通过
- ⚠️ **关键检查点**: 预处理缓存可用，所有维度可开始

### Week 2结束 (维度并行)
- ✅ 维度1(情感共振率)可运行 - 使用预处理统计O(1)查找
- ✅ 维度2(聊天积极度)可运行 - 使用预处理统计O(1)查找
- ✅ 维度3(态度倾向)可运行 - O(1)查找 vs O(6N)遍历 (6倍加速)
- ✅ AffinityConfig配置管理完成

### Week 3结束 (编排器 + API)
- ✅ 维度4(喜好兼容度)可运行 - 使用预处理统计O(1)查找
- ✅ AffinityAnalysisService编排器完成 - 调用预处理编排器
- ✅ 所有Bridge API端点完成 (7个端点)

### Week 4结束 (前端)
- ✅ 前端API客户端完成
- ✅ AffinityView主页面 + 5个组件完成
- ✅ 路由集成完成

### Week 5结束 (测试优化)
- ✅ 所有单元测试通过 (>90%通过率)
- ✅ 集成测试通过 - 验证预处理O(N)复杂度
- ✅ 性能目标达成: < 2分钟(10K消息), < 5分钟(100K消息)
- ✅ 边缘情况处理完善
- ✅ 文档齐全
- ✅ 可以发布v1.0.0

---

**最后更新**: 2026-01-09
**推荐使用**: ✅ 是 (适合2人小团队)
**复杂度**: ⭐⭐ (比功能分支简单得多)
**架构**: 预处理优先 - Week 1收集29个统计，Week 2-3四维度完全并行

祝开发顺利! 🚀
