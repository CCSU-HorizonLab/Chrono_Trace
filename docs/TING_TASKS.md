# Ting 的任务清单 - 好感度分析功能

**功能**: 002-affinity-analysis
**更新时间**: 2026-01-13
**状态**: 进行中 (阶段3: 预处理层)

---

## 📋 任务概览

| 阶段 | 任务数 | 已完成 | 预计工作量 |
|------|--------|--------|------------|
| 1. 数据库设置 | 1 | 1 | - |
| 2. 基础设施 | 4 | 4 | 简单 |
| 3. 预处理层 | 4 | 4 | 中等 |
| 4. 维度分析 | 7 | 7 | 中等 |
| 5. 编排器 | 1 | 0 | 简单 |
| 6. 后端API | 7 | 0 | 中等 |
| 7. 前端实现 | 5 | 0 | 中等 |
| 8. 测试与优化 | 6 | 0 | 简单 |
| **总计** | **35** | **16** | **约2-3周** |

**进度**: 16/35 已完成 (46%)

---

## 阶段1: 数据库设置

**说明**: 数据库表已由juitar在T001中统一添加到schema.sql

### T000: 添加默认关键词到schema.sql ✅
- [x] 在 `backend/app/db/schema.sql` 的 `keyword_libraries` 表创建后添加60条默认关键词
- [x] 每个分类10个关键词 (positive, negative, empathy, soothing, privacy, holiday)
- [x] 所有关键词标记为 `is_custom=0` (不可删除)
- [x] 使用 `strftime('%s', 'now')` 自动生成时间戳

**完成时间**: 2026-01-11

---

## 阶段2: 基础设施 (与juitar并行)

### T001: 添加Python依赖 ✅
- [x] 在 `backend/requirements.txt` 中添加依赖:
  - snownlp>=0.12.3
  - sentence-transformers>=2.2.0
  - scikit-learn>=1.3.0
  - torch>=2.0.0

**完成时间**: 2026-01-11

### T002: 安装Python依赖 ✅
- [x] 运行 `pip install -r backend/requirements.txt`

**完成时间**: 2026-01-11

### T003: 下载sentence-transformers模型 ✅
- [x] 下载模型 paraphrase-multilingual-MiniLM-L12-v2 到本地缓存
- [x] 加快首次启动速度

**完成时间**: 2026-01-11

### T004: 创建测试数据 ✅
- [x] 创建 `backend/tests/fixtures/conversation_medium.json` (4,320条真实文本消息)
- [x] 创建 `backend/tests/fixtures/conversation_labeled.json` (100条手动标注情感数据)
- [x] 创建 `backend/tests/fixtures/conversation_annotation_template.csv` (标注模板)
- [x] 创建 `docs/AFFINITY_TEST_DATA.md` (测试数据说明文档)

**完成时间**: 2026-01-13

**备注**:
- 使用真实对话ID 1773的数据,共4,320条文本消息
- 手工标注100条消息用于验证SnowNLP准确率
- 创建转换脚本(已删除,不保留在代码库中)

---

## 阶段3: 预处理层 (⚠️ 关键路径,与juitar并行)

**重要性**: 必须先完成预处理,才能开始任何维度分析

### T005: 实现关键词库服务 ✅
**文件**: `backend/app/services/analysis/keyword_libraries.py`

- [x] KeywordLibraries.get_keywords(category) - 获取指定分类的关键词
- [x] KeywordLibraries.add_keywords(category, keywords) - 添加自定义关键词
- [x] KeywordLibraries.remove_keywords(category, keywords) - 删除关键词
- [x] KeywordLibraries.get_all_keywords() - 获取全部6个分类的字典
- [x] KeywordLibraries.check_keywords_in_text(text, keywords) - 文本关键词匹配辅助方法
- [x] 内存缓存机制 (首次加载,后续从内存读取)
- [x] 数据库CRUD操作 (使用现有get_db()连接)

**6个关键词分类**:
- positive (正面词)
- negative (负面词)
- empathy (共情词)
- soothing (安抚词)
- privacy (隐私词)
- holiday (节日祝福)

**完成时间**: 2026-01-11

### T006: 关键词库测试 ✅
- [x] 创建 `backend/tests/test_keyword_libraries.py`
- [x] 测试CRUD操作 (增删改查)
- [x] 测试关键词匹配功能

**完成时间**: 2026-01-13

**备注**:
- 修改 remove_keywords() 允许删除默认关键词(is_custom=0)
- 添加 nickname 分类(第7个关键词分类)
- 测试数量: 26个测试用例

### T007: 实现态度预处理服务 ✅
**文件**: `backend/app/services/analysis/preprocessing_service.py`

- [x] AttitudePreprocessingService.collect_attitude_statistics()
  - 单次遍历收集6种态度消息计数 (O(N) vs O(6N))
  - emoji_message_count - 表情包消息数
  - voice_message_count - 语音消息数
  - video_message_count - 视频通话消息数
  - nickname_message_count - 专属称呼消息数
  - privacy_message_count - 隐私分享消息数
  - holiday_message_count - 节日祝福消息数
  - holidays_sent_count - 独立节日日期数(去重)

**实现要点**:
- 使用 keyword_libraries.get_all_keywords() 加载所有7个分类
- 使用 keyword_libraries.check_keywords_in_text() 进行模式匹配
- 新增 AttitudeStatistics 数据类

**完成时间**: 2026-01-13

### T008: 态度预处理测试 ✅
- [x] 创建 `backend/tests/test_attitude_preprocessing.py`
- [x] 测试单次遍历统计验证 (12个测试用例)
- [x] 验证O(N)复杂度 (不重复遍历)

**完成时间**: 2026-01-13

---

## 阶段4: 维度分析 (与juitar并行)

**依赖**: 必须完成阶段3 (预处理层)

### T009: 情感共振率测试 ✅
- [x] 创建 `backend/tests/test_emotional_resonance.py`
- [x] 测试5个子维度计算正确性

**完成时间**: 2026-01-22

### T010: 实现情感共振率服务 ✅
**文件**: `backend/app/services/analysis/emotional_resonance_service.py`

- [x] calculate_bidirectional_positive_response() (20%权重)
  - 使用预处理的 total_positive_count, total_interaction_pairs
- [x] calculate_polarity_consistency() (15%权重)
  - 使用预处理的 sentiment_cache embeddings
- [x] calculate_intensity_matching() (10%权重)
  - 使用预处理的 sentiment_cache intensities
- [x] calculate_empathy_recognition() (30%权重)
  - 使用 keyword_libraries.get_keywords('empathy')
- [x] calculate_negative_resolution() (25%权重)
  - 使用预处理的 interaction_pairs
- [x] calculate_overall_resonance() - 加权总分 (0-100)
- [x] generate_interpretation() - 生成解释文本

**关键**: 使用预处理的统计信息,不要重新计算!

**完成时间**: 2026-01-22

### T011: 态度倾向测试 ✅
- [x] 创建 `backend/tests/test_attitude_tendency.py`
- [x] 测试6个子维度计算

**完成时间**: 2026-01-25

### T012: 关键词匹配边界测试 ✅
- [x] 添加关键词匹配准确率测试
- [x] 测试边界情况 (部分匹配、大小写、标点符号)
- [x] 添加13个边界测试用例到 `test_keyword_libraries.py`

**完成时间**: 2026-01-25

### T013: 实现态度倾向服务 ✅
**文件**: `backend/app/services/analysis/attitude_tendency_service.py`

- [x] calculate_positive_word_frequency() (25%权重)
  - 使用预处理的 total_positive_count, total_message_count
- [x] calculate_negative_word_frequency() (-20%权重,反向计分)
  - 使用预处理的 total_negative_count, total_message_count
- [x] calculate_multimedia_usage() (15%权重) **权重已调整**
  - **优化**: 使用预处理的 emoji_message_count, voice_message_count, video_message_count (O(1) vs O(N))
- [x] calculate_nickname_frequency() (25%权重)
  - 使用预处理的 nickname_message_count
- [x] calculate_privacy_sharing() (20%权重)
  - 使用预处理的 privacy_message_count
- [x] calculate_holiday_greeting() (15%权重) **权重已调整**
  - **简化**: 使用预处理的 holidays_sent_count, chat_days_count
- [x] calculate_overall_attitude() - 加权总分 (0-100)
- [x] generate_interpretation() - 生成解释文本

**关键**: 使用预处理的统计信息,O(1)查找 vs O(6N)遍历 (6倍提速)
**权重调整**: 多媒体使用率和节日祝福频率各增加5%,确保正向权重总和为100%

**完成时间**: 2026-01-25

### T014: 关键词库集成 ✅
**文件**: `backend/app/services/analysis/attitude_tendency_service.py`

- [x] 集成KeywordLibraries (预处理中已实现,直接导入使用)
- [x] 优雅处理缺失关键词分类 (跳过该维度,重新分配权重)

**完成时间**: 2026-01-25

### T015: 聊天积极度测试 ✅
- [x] 创建 `backend/tests/test_chat_positivity.py`
- [x] 测试5个子维度计算

**完成时间**: 2026-01-25

**备注**:
- 测试文件包含400行代码
- 覆盖日均消息数、回复及时性、消息长度、话题连续性、主动发起等5个子维度

### T016: 回复及时性边界测试
- [ ] 添加边界值测试 (阈值边界、负间隔、>24小时间隔)

---

## 阶段5: 编排器

### T017: 添加解释文本生成
**文件**: `backend/app/services/analysis/affinity_analysis_service.py`

- [ ] generate_overall_interpretation() 方法
  - 总体评分解释 (如 "总体好感度较高,对方对这段关系较为重视")
- [ ] aggregate_dimension_interpretations() 方法
  - 汇总所有4个维度的解释
- [ ] format_score_breakdown() 方法
  - 格式化子分数JSON供前端展示

---

## 阶段6: 后端API

### T018: 添加配置查询端点
**文件**: `backend/app/webview/bridge.py`

- [ ] GET /affinity/config/{conversation_id}
  - 调用 affinity_config.get_config()
  - 无配置时返回默认配置

### T019: 添加配置更新端点
**文件**: `backend/app/webview/bridge.py`

- [ ] PUT /affinity/config/{conversation_id}
  - 验证配置 (权重和为1.0, 阈值在有效范围)
  - 调用 affinity_config.update_config()
  - 验证失败返回400

### T020: 添加获取关键词端点
**文件**: `backend/app/webview/bridge.py`

- [ ] GET /affinity/keywords
  - 调用 keyword_service.get_all_keywords()
  - 返回全部6个分类的字典

### T021: 添加关键词添加端点
**文件**: `backend/app/webview/bridge.py`

- [ ] POST /affinity/keywords
  - 接受 category 和 keywords 数组
  - 调用 keyword_service.add_keywords()
  - 返回 added_count 和更新后的关键词列表

### T022: 添加关键词删除端点
**文件**: `backend/app/webview/bridge.py`

- [ ] DELETE /affinity/keywords
  - 接受 category 和 keywords 数组
  - 调用 keyword_service.remove_keywords()
  - 返回 removed_count

### T023: 添加喜好关键词查询端点
**文件**: `backend/app/webview/bridge.py`

- [ ] GET /affinity/preference-keywords/{conversation_id}
  - 从 affinity_config 检索 preference_keywords_json
  - 未配置时返回空数组

### T024: 添加喜好关键词更新端点
**文件**: `backend/app/webview/bridge.py`

- [ ] PUT /affinity/preference-keywords/{conversation_id}
  - 接受 keywords 数组
  - 更新 affinity_config.preference_keywords_json

---

## 阶段7: 前端实现

### T025: 创建API客户端
**文件**: `frontend/src/api/affinity.ts`

- [ ] analyzeAffinity(conversationId, forceReanalyze, configOverrides)
- [ ] getAffinityProgress(taskId) - 轮询函数
- [ ] getAffinityScores(conversationId)
- [ ] getAffinityConfig(conversationId)
- [ ] updateAffinityConfig(conversationId, config)
- [ ] getKeywords()
- [ ] addKeywords(category, keywords)
- [ ] removeKeywords(category, keywords)
- [ ] getPreferenceKeywords(conversationId)
- [ ] updatePreferenceKeywords(conversationId, keywords)

### T026: 创建主页面
**文件**: `frontend/src/views/AffinityView.vue`

- [ ] 会话选择下拉框
- [ ] "开始分析" 按钮 (触发 analyzeAffinity)
- [ ] 进度条带百分比显示
- [ ] 总体评分大数字显示 (0-100)
- [ ] 4个维度评分卡片 (可点击查看详情)
- [ ] 解释文本显示
- [ ] "重新分析" 按钮 (触发 reanalyze)

### T027: 创建评分卡片组件
**文件**: `frontend/src/components/affinity/AffinityScoreCard.vue`

- [ ] Props: title, score, maxScore, interpretation
- [ ] 可视化评分显示 (圆形进度或条形图)
- [ ] 颜色编码: 红色 (0-40), 黄色 (40-70), 绿色 (70-100)

### T028: 创建雷达图组件
**文件**: `frontend/src/components/affinity/DimensionRadar.vue`

- [ ] ECharts雷达图显示4个维度
- [ ] Props: dimensionScores 对象
- [ ] 响应式大小调整和悬停提示

### T029: 创建子分数详情组件
**文件**: `frontend/src/components/affinity/SubScoreBreakdown.vue`

- [ ] Props: subScores 对象, dimensionName
- [ ] 表格显示子维度分数和权重
- [ ] 可展开行显示详细解释

---

## 阶段8: 测试与优化

### T030: 添加错误处理
**文件**: `backend/app/services/analysis/affinity_analysis_service.py`

- [ ] 所有外部库调用周围添加try-except块 (SnowNLP, sentence-transformers)
- [ ] 失败时优雅降级 (回退到中性/零值)
- [ ] 为UI显示提供详细错误消息

### T031: 添加结构化日志
- [ ] 在所有服务文件中添加结构化日志
- [ ] DEBUG: 算法步骤, 中间值
- [ ] INFO: 分析开始/结束, 缓存命中/未命中
- [ ] WARNING: 激活的回退, 缺失数据
- [ ] ERROR: 需要用户注意的关键失败
- [ ] 使用Python logging模块和正确的格式化器

### T032: 更新README
**文件**: `backend/README.md`

- [ ] 添加好感度分析部分
- [ ] 4维评分系统概述
- [ ] 预处理架构说明 (O(N)单次遍历收集29个统计)
- [ ] 配置选项说明
- [ ] 性能基准测试
- [ ] 故障排除指南

### T033: 组件文档
**文件**: `frontend/src/views/AffinityView.md`

- [ ] Props参考
- [ ] 事件描述
- [ ] 使用示例
- [ ] 截图占位符

### T034: 更新CLAUDE.md
**文件**: `docs/CLAUDE.md`

- [ ] 添加到"最近更改"部分
- [ ] 记录002-affinity-analysis实现说明
- [ ] 记录新预处理服务和用途
- [ ] 记录O(N) vs O(6N)性能改进

---

## 📅 建议执行顺序

### 第1周: 预处理层 (与juitar并行)
```
Day 1-2: T001-T004 (依赖安装 + 测试数据)
Day 1-2: T005-T006 (关键词库服务)
Day 3-4: T007-T008 (态度预处理)
Day 5: 联合调试 (与juitar的预处理集成)
```

### 第2周: 维度分析 (与juitar完全并行)
```
Day 1-2: T009-T010 (情感共振率)
Day 3-4: T011-T014 (态度倾向)
Day 5: T015-T016 (聊天积极度测试)
```

### 第3周: 编排器 + API + 前端 (与juitar并行)
```
Day 1: T017 (编排器解释文本)
Day 2-3: T018-T024 (后端API - 7个端点)
Day 4-5: T025-T029 (前端 - API客户端 + 主页面 + 3个组件)
```

### 第4周: 测试与优化
```
Day 1-2: T030-T031 (错误处理 + 日志)
Day 3-4: T032-T034 (文档)
Day 5: 联合调试和集成测试
```

---

## ✅ 验收标准

每个阶段完成后:
- [ ] 所有单元测试通过 (>90%覆盖率)
- [ ] 与juitar的代码集成测试通过
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
