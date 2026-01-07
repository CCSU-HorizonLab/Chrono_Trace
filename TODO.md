# Chrono Trace - 开发待办清单

> 项目开发进度跟踪与任务规划

---

## 目录

- [已完成功能](#已完成功能)
- [数据分析模块](#数据分析模块)
- [AI 策略建议模块](#ai-策略建议模块)
- [前端功能优化](#前端功能优化)
- [后端架构优化](#后端架构优化)
- [实时监听功能](#实时监听功能)
- [测试与文档](#测试与文档)
- [已知问题](#已知问题)

---

## 已完成功能

### ✅ 微信数据库支持（微信 4.0+）

- [x] SQLCipher 4 解密实现（PBKDF2-HMAC-SHA512）
- [x] 路径自动检测（xwechat_files 结构）
- [x] 多数据库分片支持（11 个文件）
- [x] 联系人数据库解析（354 个联系人）
- [x] 消息数据库解析（47,698 条消息）
- [x] 会话数据库解析（245 个会话）
- [x] 临时文件自动清理
- [x] 前端导入界面与流程

**验证状态**：✅ 生产环境验证通过

**关键文件**：
- `backend/app/services/wechat/db_decryptor_v2.py`
- `backend/app/services/wechat/db/v4/contact.py`
- `backend/app/services/wechat/db/v4/message.py`
- `backend/app/services/wechat/path_finder.py`

### ✅ 数据预处理模块

- [x] 消息内容清洗（移除 XML、表情、媒体标签）
- [x] 字符数和词数统计
- [x] 预处理缓存表（message_preprocessed）
- [x] 批量预处理接口
- [x] 集成到导入流程
- [x] 性能优化（缓存命中率 > 95%）

**触发机制**：
- 导入时自动预处理（推荐）
- 分析时按需预处理（兜底）
- 手动批量预处理（可选）

**关键文件**：
- `backend/app/services/analysis/preprocessing_service.py`

### ✅ 基础架构

- [x] PyWebView 前后端桥接（Bridge）
- [x] 前端四页面布局（首页/分析/建议/设置）
- [x] SQLite 数据库 schema 设计
- [x] 基础数据可视化（情绪曲线、词云）
- [x] 设置管理与持久化

---

## 数据分析模块

### ✅ 模块 2：特征提取服务（已完成）

**文件**：`backend/app/services/analysis/feature_extraction_service.py`

**功能清单**：

- [x] **Session 会话切割**
  - [x] 实现时间间隔判断（1800 秒阈值）
  - [x] 实现睡眠时间判断（00:00-07:00）
  - [x] 跨越睡眠时间强制切割
  - [x] 输出会话起止时间、消息数、时长
  - [x] 自动判断会话发起者
  - [x] 数据持久化到 sessions 表

- [x] **响应时间计算**
  - [x] 计算我发消息 → 对方回复的时间差
  - [x] 排除负数响应时间
  - [x] 排除超过 24 小时的异常值
  - [x] 睡眠时间处理（自动扣除 00:00-07:00）
  - [x] 统计平均值、中位数、最快/最慢响应
  - [x] 异常值标记与统计
  - [x] 数据持久化到 response_times 表

- [x] **主动性统计**
  - [x] 计算对方主动发起的 Session 占比
  - [x] 统计用户/对方发起的会话数
  - [x] 生成主动率指标
  - [x] 数据持久化到 initiative_stats 表

- [x] **字数投入比**
  - [x] 计算对方总字数 / 我的总字数
  - [x] 按整体统计
  - [x] 按会话统计（可选）
  - [x] 生成可读解读文本
  - [x] 数据持久化到 word_counts 表

**配置参数**：
```python
SESSION_GAP_THRESHOLD = 1800  # 30分钟
SLEEP_START_HOUR = 0         # 00:00
SLEEP_END_HOUR = 7           # 07:00
MAX_RESPONSE_TIME = 86400    # 24小时
```

**API 接口**：
- `bridge.extract_features(conversation_id)` - 一键提取所有特征
- `bridge.get_sessions(conversation_id, limit, offset)` - 查询会话列表
- `bridge.get_response_times(conversation_id)` - 获取响应时间统计
- `bridge.get_initiative_stats(conversation_id)` - 获取主动性统计
- `bridge.get_word_counts(conversation_id, by_session)` - 获取字数统计
- `bridge.reanalyze(conversation_id)` - 重新分析

**验证状态**：✅ 生产环境验证通过

**关键文件**：
- `backend/app/services/analysis/feature_extraction_service.py`
- `backend/app/services/analysis/feature_extraction_config.py`
- `backend/app/services/analysis/analysis_service.py`
- `backend/app/db/schema.sql` (sessions, response_times, initiative_stats, word_counts)

---

### 模块 3：语言风格匹配（LSM）🟡 中优先级

**文件**：`backend/app/services/analysis/language_style_matcher.py`

**功能清单**：

- [ ] **虚词提取（词性分析版）**
  - [ ] 使用 jieba.posseg 词性标注
  - [ ] 提取助词（的、地、得、着、了、过）
  - [ ] 提取语气词（吗、呢、吧、啊、呀、哦、哈）
  - [ ] 提取副词（就、都、也、还、又、再、才）
  - [ ] 提取代词（我、你、他、咱、我们、你们）
  - [ ] 提取连词（和、与、或、但、可是、不过）
  - [ ] 计算 TF（词频）并归一化

- [ ] **余弦相似度计算**
  - [ ] 使用 scikit-learn 的 cosine_similarity
  - [ ] 构建词向量（双方虚词并集）
  - [ ] 计算相似度（0-1）

- [ ] **词性分类统计**
  - [ ] 统计各类虚词的频率分布
  - [ ] 输出双方词性对比

**配置参数**：
```python
FUNCTION_WORD_WEIGHTS = {
    "助词": 1.0,
    "语气词": 1.2,
    "副词": 0.8,
    "代词": 0.6,
    "连词": 0.6
}
```

**预期输出**：
```json
{
  "lsm_score": 0.75,
  "similarity": 0.75,
  "word_category_stats": {...}
}
```

**依赖**：`PreprocessingService`, `scikit-learn`, `jieba.posseg`

---

### 模块 4：情感分析服务 🟡 中优先级

**文件**：`backend/app/services/analysis/sentiment_service.py`

**功能清单**：

- [ ] **集成 SnowNLP**
  - [ ] 对每条消息计算情感分值（0-1）
  - [ ] 批量处理优化

- [ ] **滑动窗口分析**
  - [ ] 计算最近 N 条消息的平均情感
  - [ ] 支持自定义窗口大小

- [ ] **情绪趋势分析**
  - [ ] 按天/周/月统计平均情感值
  - [ ] 识别情绪变化趋势（上升/下降/稳定）

- [ ] **情感分段**
  - [ ] 按时间窗口生成情感序列
  - [ ] 识别情感转折点

**预期输出**：
```json
{
  "overall_sentiment": 0.72,
  "recent_sentiment": 0.68,
  "trend": "declining",
  "timeseries": [...]
}
```

**依赖**：`snownlp`, `PreprocessingService`

---

### 模块 5：综合评分服务 🔴 高优先级

**文件**：`backend/app/services/analysis/scoring_service.py`

**功能清单**：

- [ ] **积极度评分**
  - [ ] 响应速度评分（40%权重）
  - [ ] 回复率评分（30%权重）
  - [ ] 字数投入评分（30%权重）
  - [ ] 使用 MinMaxScaler 归一化

- [ ] **共鸣感评分**
  - [ ] LSM 相似度（60%权重）
  - [ ] 表情包重复度（40%权重）
  - [ ] 归一化到 0-100

- [ ] **异常值检测**
  - [ ] 响应时间 > 24 小时警告
  - [ ] 主动率 = 0 警告
  - [ ] 情感值 < 0.3 警告

- [ ] **综合评分**
  - [ ] 加权计算总分
  - [ ] 生成分数拆解报告

**配置参数**：
```python
SCORING_WEIGHTS = {
    "active_score": {"speed": 0.4, "reply_rate": 0.3, "word_investment": 0.3},
    "resonance_score": {"lsm": 0.6, "emoji": 0.4}
}
```

**预期输出**：
```json
{
  "active_score": 85,
  "sentiment_score": 72,
  "resonance_score": 68,
  "overall_score": 75,
  "score_breakdown": {...},
  "warnings": [...]
}
```

**依赖**：`FeatureExtractionService`, `SentimentService`, `LanguageStyleMatcher`, `scikit-learn`

---

### 模块 6：数据可视化增强 🟢 低优先级

**文件**：扩展 `backend/app/services/analysis/analysis_service.py`

**功能清单**：

- [ ] **时间序列数据生成**
  - [ ] 按天/周/月聚合消息数、情感值
  - [ ] 生成 ECharts 可用格式

- [ ] **响应时间分布图**
  - [ ] 统计不同时间段的响应时间
  - [ ] 识别最活跃时段

- [ ] **主动率变化图**
  - [ ] 按时间轴展示主动率变化
  - [ ] 标记关键转折点

**依赖**：所有前置模块

---

### 模块 7：统计报告生成 🟢 低优先级

**文件**：`backend/app/services/analysis/report_generator.py`

**功能清单**：

- [ ] **完整分析报告**
  - [ ] 汇总所有分析结果
  - [ ] 生成可读的文本摘要

- [ ] **策略建议引擎**
  - [ ] 基于评分结果给出建议
  - [ ] Case A（好感度>80）：建议"更亲密"
  - [ ] Case B（好感度<50）：建议"疏远"

- [ ] **导出功能**
  - [ ] JSON 格式导出
  - [ ] Markdown 格式导出（可选）

**预期输出**：
```json
{
  "summary": "分析摘要文本",
  "scores": {...},
  "features": {...},
  "recommendations": [...]
}
```

**依赖**：所有前置模块

---

## AI 策略建议模块

### 模块 8：LLM 提供商抽象层 🟡 中优先级

**文件**：`backend/app/llm/provider_base.py`

**功能清单**：

- [ ] **定义统一接口**
  - [ ] `chat(messages, intent, persona)`
  - [ ] 支持超时/重试
  - [ ] 统一错误处理

- [ ] **实现多个提供商**
  - [ ] OpenAI Provider
  - [ ] Azure Provider
  - [ ] 本地模型 Provider（Ollama）

- [ ] **上下文构建**
  - [ ] 长期画像摘要
  - [ ] 短期上下文（最近 N 条消息）
  - [ ] 目标意图（亲密/维持/疏远）

**依赖**：`openai`, `ollama`（可选）

---

### 模块 9：建议服务 🟡 中优先级

**文件**：`backend/app/services/suggestion_service.py`

**功能清单**：

- [ ] **提示词模板**
  - [ ] 亲密关系模板
  - [ ] 维持关系模板
  - [ ] 疏远关系模板

- [ ] **裁剪与脱敏**
  - [ ] 移除敏感信息
  - [ ] 压缩上下文长度

- [ ] **重试与限流**
  - [ ] API 调用重试机制
  - [ ] 速率限制

- [ ] **缓存机制**
  - [ ] 缓存最近结果
  - [ ] 避免重复调用

**依赖**：`LLMProvider`, `AnalysisService`

---

## 前端功能优化

### 🎨 UI/UX 改进 🟢 低优先级

- [ ] **组件库集成**
  - [ ] 引入 Element Plus / Ant Design Vue
  - [ ] 统一视觉风格

- [ ] **图表库优化**
  - [ ] 完善所有图表的 ECharts 配置
  - [ ] 响应式适配

- [ ] **加载态与错误态**
  - [ ] 添加骨架屏
  - [ ] 错误提示优化

- [ ] **主题系统**
  - [ ] 支持浅色/深色主题切换
  - [ ] 主题配置持久化

---

### 📊 数据展示优化 🔴 高优先级

- [ ] **分析页面 - 特征数据可视化**
  - [ ] 会话分布时间轴（Sessions Timeline）
    - [ ] 展示所有会话的起止时间
    - [ ] 标记会话发起者（用户/对方）
    - [ ] 显示每个会话的消息密度
    - [ ] 时间轴缩放与拖拽

  - [ ] 响应时间分析面板
    - [ ] 响应时间统计卡片（平均值、中位数、最快/最慢）
    - [ ] 响应时间分布直方图
    - [ ] 响应时间趋势折线图
    - [ ] 异常值标记与列表

  - [ ] 主动性统计卡片
    - [ ] 对方主动率仪表盘
    - [ ] 会话发起者对比饼图
    - [ ] 解读文本展示

  - [ ] 字数投入比分析
    - [ ] 字数对比条形图（用户 vs 对方）
    - [ ] 字数投入比指标
    - [ ] 按会话的字数趋势图

  - [ ] 功能按钮
    - [ ] "提取特征"按钮（触发 extract_features）
    - [ ] "重新分析"按钮（触发 reanalyze）
    - [ ] 进度条展示

- [ ] **建议页面**
  - [ ] 实时建议流展示
  - [ ] 意图切换器
  - [ ] 建议卡片交互

- [ ] **设置页面**
  - [ ] API Key 配置表单
  - [ ] 模型选择器
  - [ ] 特征提取参数配置（会话切分阈值、睡眠时间等）
  - [ ] 隐私选项配置

---

### 🔄 实时功能 🟡 中优先级

- [ ] **实时状态轮询**
  - [ ] 定时轮询 `realtime_status()`
  - [ ] 更新监听状态指示器
  - [ ] 展示实时建议流

- [ ] **手动触发建议**
  - [ ] 调用 `generate_suggestion()`
  - [ ] 展示生成结果
  - [ ] 支持参数调整

**依赖**：后端实时监听功能

---

## 后端架构优化

### 🏗️ 服务层重构 🟢 低优先级

- [ ] **服务分离**
  - [ ] `RealtimeService` - 实时监听服务
  - [ ] `SuggestionService` - 建议生成服务
  - [ ] `SettingsService` - 配置管理服务

- [ ] **错误处理统一**
  - [ ] 定义业务异常类
  - [ ] 统一错误码规范
  - [ ] 完善日志记录

- [ ] **事务管理**
  - [ ] 数据库操作事务化
  - [ ] 批量操作优化

---

### 🔐 隐私与安全 🟡 中优先级

- [ ] **数据脱敏**
  - [ ] 消息内容敏感信息识别
  - [ ] 自动替换/移除

- [ ] **密钥管理**
  - [ ] API Key 加密存储
  - [ ] 支持系统密钥环

- [ ] **数据清理**
  - [ ] 一键清空功能
  - [ ] 数据导出功能
  - [ ] 数据备份功能

---

### ⚡ 性能优化 🟢 低优先级

- [ ] **数据库优化**
  - [ ] 添加索引（conversation_id, timestamp）
  - [ ] 查询优化（避免 N+1）
  - [ ] 连接池管理

- [ ] **缓存策略**
  - [ ] Redis 缓存（可选）
  - [ ] 内存缓存优化
  - [ ] 分析结果缓存

- [ ] **增量更新**
  - [ ] 支持增量导入新消息
  - [ ] 增量分析更新

---

## 实时监听功能

### 🔴 Windows 实时监听（实验性）🔴 高优先级

**文件**：`backend/app/services/realtime_service.py`

**功能清单**：

- [ ] **wxauto4 集成**
  - [ ] 封装 wxauto4 API
  - [ ] 启动/停止监听脚本
  - [ ] 错误处理与重连

- [ ] **消息捕获**
  - [ ] 轮询当前聊天窗口
  - [ ] 识别新消息
  - [ ] 写入暂存表（source=realtime）

- [ ] **状态管理**
  - [ ] 监听状态（running/stopped）
  - [ ] 统计信息（已捕获消息数）
  - [ ] 错误日志

- [ ] **实时建议触发**
  - [ ] 检测到新消息后生成上下文
  - [ ] 调用 LLM 生成建议
  - [ ] 推送到前端（evaluate_js 或轮询）

**预期输出**：
```json
{
  "running": true,
  "stats": {
    "captured_messages": 15,
    "suggestions_generated": 3
  },
  "last_error": null
}
```

**依赖**：`wxauto4`, `SuggestionService`

**限制**：仅支持 Windows 微信客户端，一次只能监听一个会话

---

## 测试与文档

### 🧪 测试 🟢 低优先级

- [ ] **单元测试**
  - [ ] `test_preprocessing.py` - 数据清洗测试
  - [ ] `test_feature_extraction.py` - 特征提取测试
  - [ ] `test_sentiment.py` - 情感分析测试
  - [ ] `test_scoring.py` - 评分模块测试
  - [ ] 目标覆盖率：> 80%

- [ ] **集成测试**
  - [ ] 完整分析流程测试
  - [ ] 性能测试（10000+ 消息）
  - [ ] 真实数据验证

- [ ] **E2E 测试**
  - [ ] 前端自动化测试（Playwright）
  - [ ] 关键用户流程测试

---

### 📝 文档完善 🟢 低优先级

- [ ] **API 文档**
  - [ ] Bridge API 完整说明
  - [ ] 服务层接口文档
  - [ ] 数据模型文档

- [ ] **用户文档**
  - [ ] 功能使用指南
  - [ ] 常见问题 FAQ
  - [ ] 视频教程（可选）

- [ ] **开发文档**
  - [ ] 架构设计文档
  - [ ] 数据库 ER 图
  - [ ] 部署指南

---

## 已知问题

### 🔴 高优先级

- 暂无

### 🟡 中优先级

- 前端缺少 echarts 依赖（需手动安装）
- 微信 4.0 以下版本不支持
- 实时监听仅支持 Windows

### 🟢 低优先级

- 大数据集（>100k 消息）导入速度较慢（~1-2 分钟）
- 某些特殊消息类型可能无法正确解析

---

## 依赖管理

### 需要添加到 requirements.txt

```txt
# 已有
jieba>=0.42.1

# 需要添加
snownlp>=0.12.3           # 情感分析
scikit-learn>=1.3.0       # 余弦相似度
numpy>=1.24.0             # 数值计算
pandas>=2.0.0             # 数据处理（可选）
openai>=1.0.0             # LLM（可选）
wxauto4>=0.1.0            # 实时监听（可选）
```

---

## 开发进度总览

### 数据分析模块：28.5% (2/7)

- [x] 模块 1：数据预处理（100%）
- [x] **模块 2：特征提取（100%）** ✅ 新完成
- [ ] 模块 3：语言风格匹配（0%）
- [ ] 模块 4：情感分析（0%）
- [ ] 模块 5：综合评分（0%）
- [ ] 模块 6：数据可视化（0%）
- [ ] 模块 7：统计报告（0%）

### AI 策略建议模块：0% (0/2)

- [ ] 模块 8：LLM 提供商抽象（0%）
- [ ] 模块 9：建议服务（0%）

### 实时监听模块：0% (0/1)

- [ ] Windows 实时监听（0%）

### 前端优化：30% (骨架已完成)

- [x] 四页面布局（100%）
- [ ] 数据展示优化（0%）
- [ ] 实时功能（0%）
- [ ] UI/UX 改进（0%）

---

## 里程碑

- [x] **M1 骨架**：Bridge + 路由页面
- [x] **M2 长期导入**：解析器/入库/基础分析
- [ ] **M3 短期监听**：脚本运行与状态、实时建议推送
- [ ] **M4 LLM 适配**：提示词模板与多提供商
- [ ] **M5 体验与安全**：配置管理、隐私策略与导出

---

**最后更新**：2025-01-05
**维护者**：CAN
**项目状态**：🚧 开发中（V4 数据库支持已完成）
