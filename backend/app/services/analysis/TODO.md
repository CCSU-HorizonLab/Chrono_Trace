# 数据分析模块开发 TODO

## 📋 项目目标
按照 `DEV_NEW_PLAN.md` 的需求，完成基础数据分析工作，包括数据清洗、特征提取、情感分析、评分模型和可视化报告生成。

---

## ✅ 已完成

### 模块1: 数据预处理模块 (2025-12-31)
**文件**: `preprocessing_service.py`

**功能**:
- ✅ 消息内容清洗
  - 移除 XML 系统消息 `<msg>...</msg>`
  - 移除表情和媒体标签 `[表情]`、`[图片]`、`[语音]`
  - 规范化空白字符
  - 判断消息有效性（≥2字符）
  
- ✅ 基础统计计算
  - 字符数统计（不含空格）
  - 词数统计（使用 jieba 分词）
  - 标点符号检测
  
- ✅ 批量预处理接口
  - `preprocess_conversation()` - 处理整个对话（支持缓存）
  - `preprocess_message_batch()` - 批量预处理指定消息
  - `get_cleaned_texts()` - 获取纯文本列表
  - 返回详细统计信息（XML数、媒体数、平均字符数、缓存命中率等）

- ✅ 预处理缓存表 `message_preprocessed`
  - 存储清洗后的内容和统计信息
  - 避免重复处理，大幅提升性能
  - 支持增量更新

**集成**:
- ✅ 集成到 `AnalysisService.get_analysis()` - 用户请求分析时调用
- ✅ 集成到 `WeChatIngestService.import_wechat_data()` - 导入完成后自动预处理
- ✅ 更新 `__init__.py` 导出
- ✅ 测试通过，无 linter 错误

**触发时机** ⭐:

1. **自动触发 - 导入时预处理（推荐）**
   - 时机: 微信数据导入完成后
   - 位置: `WeChatIngestService._auto_preprocess_messages()`
   - 优点: 提前准备好数据，分析时直接使用缓存，速度极快
   - 覆盖: 所有新导入的未处理消息

2. **按需触发 - 分析时预处理（兜底）**
   - 时机: 用户请求分析某个会话时
   - 位置: `AnalysisService.get_analysis()` → `PreprocessingService.preprocess_conversation()`
   - 优点: 灵活，支持指定时间范围
   - 场景: 导入前的老数据、增量更新的消息

3. **手动触发 - 批量预处理（可选）**
   - 时机: 管理员手动执行脚本
   - 方法: 调用 `PreprocessingService.preprocess_message_batch()`
   - 场景: 修复历史数据、重新处理特定会话

**性能优化**:
- ✅ 缓存机制：已处理的消息存入 `message_preprocessed` 表
- ✅ 批量写入：使用事务批量插入，减少 I/O
- ✅ 智能跳过：检测到缓存直接读取，避免重复清洗
- ✅ 命中率统计：实时显示缓存命中率（预期 >95%）

**输出示例**:
```json
{
  "total_messages": 1234,
  "valid_messages": 1150,
  "stats": {
    "xml_count": 20,
    "media_count": 84,
    "avg_char_count": 12.5,
    "avg_word_count": 8.3,
    "cache_hit_rate": 0.95
  }
}
```

---

## 🔜 待完成

### 模块2: 特征提取模块 ⭐ (已优化)
**文件**: `feature_extraction_service.py` (待创建)

**功能**:
- [ ] **Session 会话切割** (优化算法 🔴)
  - **阈值调整**: 1800秒 (30分钟) → 新会话 (参考PyWxDump)
    - 原因: 3600秒过长,无法反映真实对话节奏
  - **睡眠时间判断**: 跨越睡眠时间强制切割
    - 睡眠时段: 00:00-07:00 (可配置)
    - 跨越逻辑: 前一消息在 22:00-00:00, 后一消息在 07:00-22:00 → 强制新会话
  - **输出**: 每个会话的起止时间、消息数、时长、是否跨睡眠时间
  
- [ ] **响应时间计算** (优化算法 🔴)
  - **基础计算**: 我发消息 → 对方首次回复的时间差
  - **异常值过滤**:
    - 排除负数响应时间 (时间乱序)
    - 排除超过 24 小时的响应 (跨天回复)
  - **睡眠时间处理 (核心改进)**:
    - 如果发送时间在 00:00-07:00 → 跳过不计算
    - 如果回复时间在 00:00-07:00 → 调整到次日 07:00 计算
    - 确保响应时间不受睡眠影响
  - **统计**: 平均响应时间、中位数、最快/最慢响应、有效样本数
  
- [ ] **主动率统计** (增强版 🟡)
  - **基础指标**: 对方主动发起的 Session 数 / 总 Session 数
  - **连续主动指标 (新增)**:
    - 统计对方连续发送多条消息的次数
    - 计算平均连续消息数
    - 解释: 连续发送表示更强的沟通意愿
  - **判断**: 每个 Session 的首条消息发送者
  
- [ ] **字数投入比**
  - 计算: 对方总字数 / 我的总字数
  - 按 Session 分别统计

**配置参数** (可调整):
```python
SESSION_GAP_THRESHOLD = 1800  # 30分钟
SLEEP_START_HOUR = 0         # 00:00
SLEEP_END_HOUR = 7           # 07:00
MAX_RESPONSE_TIME = 86400    # 24小时
```

**依赖**: `PreprocessingService` (已完成)

**预期输出** (优化后):
```json
{
  "sessions": [
    {
      "session_id": 1,
      "start_time": "2025-01-01 09:00:00",
      "end_time": "2025-01-01 10:30:00",
      "message_count": 23,
      "duration_minutes": 90,
      "initiator": "me|target",
      "crosses_sleep_time": false
    }
  ],
  "response_time": {
    "avg": 180.5,
    "median": 120,
    "max": 3600,
    "min": 10,
    "valid_count": 45,
    "filtered_count": 3
  },
  "initiative_rate": 0.45,
  "continuous_initiative": {
    "avg_continuous_msgs": 2.3,
    "max_continuous_msgs": 5
  },
  "word_ratio": 1.2
}
```

---


### 模块3: 语言风格匹配模块 ⭐ (已优化)
**文件**: `language_style_matcher.py` (待创建)

**功能**:
- [ ] **虚词提取 (词性分析版 🟡)**
  - **使用 jieba.posseg 词性标注**
    - 助词 (x): 的、地、得、着、了、过
    - 语气词 (y): 吗、呢、吧、啊、呀、哦、哈
    - 副词 (d): 就、都、也、还、又、再、才
    - 代词 (r): 我、你、他、咱、我们、你们
    - 连词 (c): 和、与、或、但、可是、不过
  - **TF (词频) 计算**:
    - 虚词数 / 总词数 → 归一化频率
    - 避免长文本主导结果
  
- [ ] **余弦相似度计算**
  - 使用 `sklearn.metrics.pairwise.cosine_similarity`
  - 构建词向量: 取双方并集的虚词作为维度
  - 计算双方虚词使用的相似度（0-1）

**配置参数**:
```python
# 虚词分类权重 (可选,用于加权相似度)
FUNCTION_WORD_WEIGHTS = {
    "助词": 1.0,
    "语气词": 1.2,  # 语气词更能体现风格
    "副词": 0.8,
    "代词": 0.6,
    "连词": 0.6
}
```

**依赖**: `PreprocessingService`, `scikit-learn`, `jieba.posseg`

**预期输出** (优化后):
```json
{
  "lsm_score": 0.75,
  "my_function_words": {
    "的": 0.045, "了": 0.032, "吧": 0.028,
    "就": 0.021, "也": 0.018
  },
  "target_function_words": {
    "的": 0.052, "了": 0.038, "呢": 0.025,
    "就": 0.019, "也": 0.020
  },
  "similarity": 0.75,
  "word_category_stats": {
    "助词": {"my": 0.12, "target": 0.15},
    "语气词": {"my": 0.05, "target": 0.08}
  }
}
```

---

### 模块4: 情感分析模块
**文件**: `sentiment_service.py` (待创建)

**功能**:
- [ ] **集成 SnowNLP**
  - 对每条消息计算情感分值（0-1）
  - 0 = 负面，1 = 正面
  
- [ ] **滑动窗口分析**
  - 计算最近 N 条消息的平均情感
  - 支持按时间窗口分段
  
- [ ] **情绪趋势分析**
  - 按天/周/月统计平均情感值
  - 识别情绪变化趋势

**依赖**: `snownlp`, `PreprocessingService`

**预期输出**:
```json
{
  "overall_sentiment": 0.72,
  "recent_sentiment": 0.68,
  "trend": "declining",
  "timeseries": [
    {"date": "2025-01-01", "sentiment": 0.75},
    {"date": "2025-01-02", "sentiment": 0.70}
  ]
}
```

---


### 模块5: 综合评分模块 ⭐ (已优化)
**文件**: `scoring_service.py` (待创建)

**功能**:
- [ ] **积极度评分 (Active Score) 🟡**
  - **响应速度评分 (40%)**: 使用指数衰减函数
    ```python
    max_acceptable_time = 1800  # 30分钟
    if avg_response_time > max_acceptable_time:
        speed_score = 20  # 最低20分
    else:
        speed_score = 100 * (1 - avg_response_time / max_acceptable_time)
    ```
  - **回复率评分 (30%)**: valid_messages / total_messages * 100
  - **字数投入评分 (30%)**:
    - 对方字数 > 我的字数 → 高分 (50 + word_ratio * 30)
    - 对方字数 < 我的字数 → 低分 (word_ratio * 50)
  - **输出**: 0-100 分 (使用 MinMaxScaler 归一化)
  
- [ ] **共鸣感评分 (Resonance Score) 🟡**
  - **权重**: LSM 相似度 60% + 表情包重复度 40%
  - **归一化**: 所有分数映射到 0-100
  - **输出**: 0-100 分
  
- [ ] **异常值检测 (新增)**
  - 响应时间 > 24 小时 → 标记为异常
  - 主动率 = 0 → 警告 "对方从不主动"
  - 情感值 < 0.3 → 警告 "消极情绪占主导"

**配置参数** (可调整):
```python
SCORING_WEIGHTS = {
    "active_score": {
        "speed": 0.4,
        "reply_rate": 0.3,
        "word_investment": 0.3
    },
    "resonance_score": {
        "lsm": 0.6,
        "emoji": 0.4
    }
}
```

**依赖**: `FeatureExtractionService`, `SentimentService`, `LanguageStyleMatcher`, `scikit-learn`

**预期输出** (优化后):
```json
{
  "active_score": 85,
  "sentiment_score": 72,
  "resonance_score": 68,
  "overall_score": 75,
  "score_breakdown": {
    "speed_score": 88,
    "reply_score": 90,
    "word_score": 78,
    "lsm_score": 70,
    "emoji_score": 65
  },
  "warnings": [
    "响应时间偶尔超过1小时",
    "主动率较低 (23%)"
  ]
}
```

---

### 模块6: 数据可视化增强
**文件**: 扩展 `analysis_service.py`

**功能**:
- [ ] **时间序列数据生成**
  - 按天/周/月聚合消息数、情感值
  - 生成前端可直接使用的图表数据
  
- [ ] **响应时间分布图**
  - 统计不同时间段的响应时间
  - 识别最活跃时段
  
- [ ] **主动率变化图**
  - 按时间轴展示主动率变化趋势

**依赖**: 所有前置模块

**预期输出**:
```json
{
  "timeseries": [
    {
      "date": "2025-01-01",
      "message_count": 45,
      "sentiment": 0.75,
      "response_time_avg": 120
    }
  ]
}
```

---

### 模块7: 统计报告生成
**文件**: `report_generator.py` (待创建)

**功能**:
- [ ] **完整分析报告**
  - 汇总所有分析结果
  - 生成可读的文本摘要
  
- [ ] **策略建议引擎**
  - 基于评分结果给出建议
  - Case A (好感度>80): 建议"更亲密"
  - Case B (好感度<50): 建议"疏远"
  
- [ ] **导出功能**
  - JSON 格式
  - Markdown 格式（可选）

**依赖**: 所有前置模块

**预期输出**:
```json
{
  "summary": "分析摘要文本",
  "scores": {...},
  "features": {...},
  "recommendations": [
    {
      "type": "intimate",
      "reason": "好感度高且积极",
      "suggestions": ["建议1", "建议2"]
    }
  ]
}
```

---

## 📦 依赖管理

### 需要添加到 `requirements.txt`:
```txt
# 已有
jieba>=0.42.1

# 需要添加
snownlp>=0.12.3           # 情感分析
scikit-learn>=1.3.0       # 余弦相似度
numpy>=1.24.0             # 数值计算
pandas>=2.0.0             # 数据处理（可选）
```

---

## 🧪 测试计划

### 单元测试
- [ ] `test_preprocessing.py` - 数据清洗测试
- [ ] `test_feature_extraction.py` - 特征提取测试
- [ ] `test_sentiment.py` - 情感分析测试
- [ ] `test_scoring.py` - 评分模块测试

### 集成测试
- [ ] 完整分析流程测试（需要真实数据）
- [ ] 性能测试（处理10000+消息）

---

## 📊 开发进度

- [x] 模块1: 数据预处理 (100%)
- [ ] 模块2: 特征提取 (0%)
- [ ] 模块3: 语言风格匹配 (0%)
- [ ] 模块4: 情感分析 (0%)
- [ ] 模块5: 综合评分 (0%)
- [ ] 模块6: 数据可视化 (0%)
- [ ] 模块7: 统计报告 (0%)

**总体进度**: 14% (1/7)

---

## 📝 注意事项

1. **数据库为空**: 当前数据库大小为 0 字节，需要先导入测试数据才能完整测试
2. **预处理缓存**: 导入时自动预处理,分析时使用缓存,无需担心性能问题
3. **Session 切割**: ⚠️ 已优化为 **30分钟阈值** + **睡眠时间判断**
4. **性能优化**: 缓存命中率预期 >95%,大量消息时分析速度提升 10-20 倍
5. **配置化**: ⭐ 评分权重、时间阈值等参数应可配置(已添加配置参数示例)
6. **错误处理**: 每个模块都要有完善的异常处理
7. **增量更新**: 新导入的消息会自动预处理,无需手动干预
8. **参考项目**: 核心算法参考 **PyWxDump** (Session切割) 和 **QQchatlog_Analysis** (情感分析)

---

## 🔗 相关文档

- `backend/DEV_NEW_PLAN.md` - 完整需求说明
- `backend/DEV_PLAN.md` - 项目架构设计
- `backend/app/db/schema.sql` - 数据库表结构

---

## 🎯 本次优化总结 (2026-01-02)

基于 GitHub 开源项目 (PyWxDump, QQchatlog_Analysis) 的深度研究,完成以下优化:

### 🔴 高优先级改进

1. **模块2 - Session切割算法**
   - ❌ 旧方案: 3600秒固定阈值 (过长)
   - ✅ 新方案: 1800秒 (30分钟) + 跨睡眠时间强制切割
   - 📚 参考: PyWxDump 的时间处理逻辑

2. **模块2 - 响应时间计算**
   - ❌ 旧方案: 简单排除睡眠时间
   - ✅ 新方案: 过滤异常值 (>24h) + 睡眠时间调整到次日7点
   - 📚 参考: 学术论文中的响应时间标准化方法

### 🟡 中优先级改进

3. **模块3 - 语言风格匹配 (LSM)**
   - ❌ 旧方案: 只统计简单虚词频率
   - ✅ 新方案: 使用 jieba.posseg 词性标注 + TF归一化
   - 📚 参考: LSM学术论文的标准实现

4. **模块5 - 综合评分**
   - ❌ 旧方案: 固定权重,无归一化
   - ✅ 新方案: MinMaxScaler归一化 + 异常值检测 + 详细分数拆解
   - 📚 参考: QQchatlog_Analysis 的评分体系

5. **模块2 - 主动率增强**
   - 新增指标: 连续主动发送消息数
   - 更准确反映沟通意愿

### 🟢 低优先级改进

6. **模块4 - 情感分析**
   - 已使用 SnowNLP (主流方案)
   - 可考虑滑动窗口平滑(已在TODO中)

---

**最后更新**: 2026-01-02
**当前状态**: 已完成算法优化评估,准备开始模块2实现

**优化历史**:
- **2026-01-02**: 基于GitHub项目研究,优化模块2/3/5算法设计
- **2025-12-31**: 完成模块1预处理 + 缓存机制
