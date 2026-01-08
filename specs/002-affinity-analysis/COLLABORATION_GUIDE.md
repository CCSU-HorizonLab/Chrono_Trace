# 好感度分析系统 - 合作开发指南

**项目**: Chrono Trace - Feature 002
**功能**: Conversation Affinity Analysis System
**开发者**: juitar & ting
**创建日期**: 2026-01-08
**分支**: `002-affinity-analysis`

---

## 📋 项目概述

本功能实现了基于4个维度的微信聊天记录好感度分析系统:
- **情感共振率** (30%): 双向情感响应、极性一致性、情绪强度匹配、共情意图、负面化解
- **聊天积极度** (30%): 日均消息、回复及时率、消息长度、话题延续性、主动发起率
- **态度倾向** (20%): 正负面词汇、多媒体使用、专属称呼、隐私分享、节假日祝福
- **喜好维度** (20%): 话题提及频率、喜好话题延续性

---

## 🎯 Git 合作工作流

### 分支策略

```
master (主分支)
  ↓
002-affinity-analysis (功能分支)
  ↓
  ├── juitar-emotional-resonance (juitar的工作分支)
  ├── juitar-preprocessing (juitar的工作分支)
  ├── ting-chat-positivity (ting的工作分支)
  └── ting-attitude-preference (ting的工作分支)
```

### 工作流程

#### 1. **克隆项目并设置上游**
```bash
# 两位开发者都需要执行
git clone <repository-url>
cd Chrono\ Trace
git checkout 002-affinity-analysis
```

#### 2. **创建个人工作分支**
```bash
# juitar 创建工作分支
git checkout -b juitar-emotional-resonance

# ting 创建工作分支
git checkout -b ting-chat-positivity
```

#### 3. **日常开发流程**
```bash
# 1. 拉取最新代码
git fetch origin
git rebase origin/002-affinity-analysis

# 2. 开发功能
# ... 编写代码 ...

# 3. 提交代码
git add .
git commit -m "[US1] 实现情感共振率分析 - 双向积极情感响应率计算"

# 4. 推送到远程
git push origin juitar-emotional-resonance

# 5. 创建 Pull Request 到 002-affinity-analysis
```

#### 4. **提交规范**

使用以下格式:
```
[type]: [brief description]

[optional detailed explanation]

Co-Authored-By: [Partner Name] <email>
```

**Type类型**:
- `feat`: 新功能
- `fix`: Bug修复
- `refactor`: 重构
- `test`: 测试
- `docs`: 文档
- `config`: 配置

**示例**:
```
feat: 实现交互对构建算法

完成了发言单位合并(5分钟阈值)和交互对识别功能。
使用滑动窗口算法构建交互对序列。

Co-Authored-By: ting <ting@example.com>
```

---

## 📊 任务分工建议

### **juitar 负责** (后端核心算法)

#### User Story 1: Emotional Resonance Analysis (P1)
- ✅ 情感分析集成 (SnowNLP + sentence-transformers)
- ✅ 交互对构建算法
- ✅ 双向积极情感响应率计算
- ✅ 情感极性一致性得分
- ✅ 情绪强度匹配度计算
- ✅ 共情意图识别率
- ✅ 负面情绪协同化解率

**关键文件**:
- `backend/app/services/analysis/sentiment_service.py` (创建)
- `backend/app/services/analysis/interaction_pair_builder.py` (创建)
- `backend/app/services/analysis/emotional_resonance_service.py` (创建)

---

### **ting 负责** (后端评分 + 前端可视化)

#### User Story 2: Chat Positivity Analysis (P1)
- ✅ 日均消息数统计
- ✅ 回复及时率计算
- ✅ 消息长度统计
- ✅ 话题延续性得分(基于juitar的语义相似度)
- ✅ 主动发起率计算(基于juitar的交互对)

#### User Story 3: Attitude Tendency Analysis (P2)
- ✅ 正负面词汇频次统计
- ✅ 多媒体使用占比
- ✅ 专属称呼频率
- ✅ 隐私分享比例
- ✅ 节假日祝福统计

#### User Story 4: Preference Compatibility Analysis (P2)
- ✅ 话题提及频率
- ✅ 喜好话题延续性得分

**关键文件**:
- `backend/app/services/analysis/chat_positivity_service.py` (创建)
- `backend/app/services/analysis/attitude_tendency_service.py` (创建)
- `backend/app/services/analysis/preference_compatibility_service.py` (创建)
- `backend/app/services/analysis/affinity_config.py` (创建 - 配置管理)
- `backend/app/services/analysis/keyword_libraries.py` (创建 - 关键词库)
- `frontend/src/views/AffinityView.vue` (创建 - 可视化界面)

---

### **共同协作** (系统集成)

#### 综合评分与API
- ✅ 总好感度分数计算 (加权汇总)
- ✅ Bridge API端点 (`bridge.py`)
- ✅ 数据库Schema设计 (新表)
- ✅ 前后端联调
- ✅ 集成测试

**关键文件**:
- `backend/app/services/analysis/affinity_analysis_service.py` (创建 - 主服务)
- `backend/app/webview/bridge.py` (更新 - 添加API端点)
- `backend/app/db/schema.sql` (更新 - 新增表)
- `frontend/src/api/affinity.ts` (创建 - API调用)

---

## 🔧 依赖关系与协作点

### 1. **预处理阶段** (juitar先实现)
```
juitar: sentiment_service.py
  ↓ 生成: 情感极性、强度、句向量
  ↓
juitar: interaction_pair_builder.py
  ↓ 生成: 交互对序列
  ↓
ting: 使用交互对计算积极度、主动性
```

### 2. **语义相似度** (juitar提供工具函数)
```
juitar: 提供 calculate_semantic_similarity(vec1, vec2)
  ↓
ting: 调用该函数计算话题延续性
```

### 3. **关键词库** (ting实现,juitar调用)
```
ting: keyword_libraries.py (管理所有关键词)
  ↓
juitar: emotional_resonance_service.py (使用共情/安抚关键词)
ting: attitude_tendency_service.py (使用正/负面关键词)
```

### 4. **配置管理** (ting实现)
```
ting: affinity_config.py (权重、阈值配置)
  ↓
juitar: 读取配置调整计算参数
ting: 读取配置生成报告
```

---

## 📅 里程碑与时间表

### Phase 1: 基础设施 (Week 1)
- [ ] juitar: 情感分析集成 (SnowNLP + sentence-transformers)
- [ ] juitar: 交互对构建算法
- [ ] ting: 关键词库设计与默认值
- [ ] ting: 配置管理服务
- [ ] 共同: 数据库Schema设计

**Checkpoint**: 能够对消息进行情感分析并构建交互对

### Phase 2: 核心维度 (Week 2-3)
- [ ] juitar: 情感共振率5个子维度 (US1)
- [ ] ting: 聊天积极度5个子维度 (US2)
- [ ] 共同: API端点定义与前后端联调

**Checkpoint**: P1用户故事完全实现,可以演示MVP

### Phase 3: 辅助维度 (Week 4)
- [ ] ting: 态度倾向5个子维度 (US3)
- [ ] ting: 喜好维度2个子维度 (US4)
- [ ] juitar: 综合评分算法

**Checkpoint**: 所有4个维度完成,总分可计算

### Phase 4: 优化与测试 (Week 5)
- [ ] ting: 前端可视化界面
- [ ] juitar: 性能优化(缓存、批处理)
- [ ] 共同: 集成测试、文档编写

**Checkpoint**: 功能完整,可合并到master

---

## 💬 协作沟通

### 每日同步
- 时间: 每天晚上9:00
- 内容: 进度汇报、遇到的问题、明天计划
- 方式: 微信语音/文字

### 代码审查
- **必须审查**: Pull Request必须由另一位开发者review后才能合并
- **审查要点**:
  - 代码逻辑正确性
  - 命名规范(snake_case/PascalCase)
  - 注释是否清晰
  - 是否有潜在bug

### 冲突解决
```bash
# 1. 发现冲突时,先沟通
# 2. 拉取最新代码
git fetch origin
git rebase origin/002-affinity-analysis

# 3. 解决冲突
# ... 编辑冲突文件 ...

# 4. 标记解决
git add .
git rebase --continue

# 5. 推送
git push origin <branch-name> --force-with-lease
```

---

## 🧪 测试策略

### 单元测试 (每位开发者负责自己的模块)
```python
# tests/test_sentiment_service.py (juitar)
# tests/test_chat_positivity_service.py (ting)
# tests/test_interaction_pair_builder.py (juitar)
# tests/test_keyword_libraries.py (ting)
```

### 集成测试 (共同编写)
```python
# tests/test_affinity_analysis_integration.py
# - 完整的分析流程测试
# - 端到端测试
# - 性能测试(10万条消息)
```

### 测试数据
- 准备3个测试对话集:
  - 小型(1000条): 快速验证
  - 中型(10000条): 常规测试
  - 大型(100000条): 性能测试

---

## 📁 项目结构

```
backend/
  app/
    services/
      analysis/
        sentiment_service.py                # juitar - 情感分析
        interaction_pair_builder.py         # juitar - 交互对构建
        emotional_resonance_service.py      # juitar - 情感共振率
        chat_positivity_service.py          # ting - 聊天积极度
        attitude_tendency_service.py        # ting - 态度倾向
        preference_compatibility_service.py # ting - 喜好维度
        affinity_analysis_service.py        # 共同 - 主服务
        affinity_config.py                  # ting - 配置管理
        keyword_libraries.py                # ting - 关键词库
    db/
      schema.sql                            # 共同 - 数据库表
    webview/
      bridge.py                             # 共同 - API端点

frontend/
  src/
    views/
      AffinityView.vue                     # ting - 可视化界面
    api/
      affinity.ts                           # ting - API调用

tests/
  test_sentiment_service.py                # juitar
  test_interaction_pair_builder.py         # juitar
  test_chat_positivity_service.py          # ting
  test_affinity_analysis_integration.py    # 共同
```

---

## ✅ 质量标准

### 代码规范
- Python: PEP 8, snake_case命名
- Vue: TypeScript, camelCase命名
- 注释: 关键算法必须添加注释说明

### 提交标准
- 每个功能点提交一次
- 提交信息清晰描述改动
- 不得提交调试代码(print等)

### 测试标准
- 单元测试覆盖率 > 80%
- 所有核心算法必须有测试
- 性能测试必须通过

---

## 🚀 快速开始

### juitar 的第一个任务
```bash
git checkout -b juitar-sentiment-analysis
# 实现 SnowNLP 情感分析集成
# 实现 sentence-transformers 句向量生成
```

### ting 的第一个任务
```bash
git checkout -b ting-keyword-libraries
# 设计关键词库结构
# 实现默认关键词集
# 实现配置管理服务
```

---

## 📞 联系方式

- **juitar**: [微信/邮箱]
- **ting**: [微信/邮箱]

---

**最后更新**: 2026-01-08
**状态**: ✅ 规格书已完成,开始实施阶段

**下一步**: 运行 `/speckit.plan` 生成详细实施计划
