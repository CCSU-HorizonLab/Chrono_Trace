# 好感度分析系统 - 简化协作指南 (推荐)

**项目**: Chrono Trace - Feature 002
**功能**: Conversation Affinity Analysis System
**开发者**: juitar & ting
**创建日期**: 2026-01-08
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
# 查看任务列表
cat specs/002-affinity-analysis/tasks.md

# 查看快速入门指南
cat specs/002-affinity-analysis/quickstart.md

# 查看合作分工
cat specs/002-affinity-analysis/COLLABORATION_GUIDE.md
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

## 📊 任务分工概览

### juitar 的任务 (~36个任务)

**Phase 1-2** (基础, 共同完成):
- T001-T015: 依赖安装、数据库迁移、测试数据

**Phase 3** (情感共振率, 9个任务):
- T016-T021: SnowNLP集成、交互对构建、5个子维度
- 核心算法实现

**Phase 7** (编排服务, 3个任务):
- T037-T039: 主分析服务、总分计算、进度跟踪

**Phase 8** (后端API, 一半端点):
- T040, T041, T043, T045, T047, T049

**Phase 10-11** (测试优化, 共同完成):
- 所有集成测试和性能测试

**预计时间**: 3-4周

### ting 的任务 (~40个任务)

**Phase 1-2** (基础, 共同完成):
- T001-T015: 依赖安装、数据库迁移、测试数据

**Phase 4** (聊天积极度, 4个任务):
- T025-T027: 5个子维度计算

**Phase 5** (态度倾向, 6个任务):
- T029-T032: 5个子维度计算、关键词集成

**Phase 6** (喜好维度, 6个任务):
- T033-T036: 2个子维度计算、配置集成

**Phase 9** (前端UI, 8个任务):
- T050-T058: API客户端、主页面、5个组件、路由集成

**Phase 10-11** (测试优化, 共同完成):
- 所有集成测试和性能测试

**预计时间**: 3-4周

---

## 🗓️ 5周时间表 (简化版)

### Week 1: 基础 + 核心算法

**juitar**:
- T001-T003: 依赖安装
- T004-T015: 数据库迁移(共同)
- T016-T021: 情感共振率实现

**ting**:
- T001-T003: 依赖安装
- T004-T015: 数据库迁移(共同)
- T022: 关键词库实现
- T029-T032: 态度倾向实现(开始)

**目标**: 完成基础设施和US1

### Week 2: 评分系统 + UI基础

**juitar**:
- T037-T039: 编排服务实现

**ting**:
- T033-T036: 喜好维度实现
- T050-T054: 前端API客户端和部分组件

**目标**: 完成US3-US4和前端基础

### Week 3: API集成

**juitar**:
- T040-T049: 后端API实现(一半)

**ting**:
- T025-T027: 聊天积极度实现(US2)
- T055-T058: 前端组件完成

**目标**: 完成US2和所有API

### Week 4: 测试验证

**共同**:
- T059-T069: 单元测试和集成测试
- T070: 边缘案例测试
- 修复发现的bug

**目标**: 所有测试通过

### Week 5: 优化上线

**共同**:
- T071-T084: 性能优化、错误处理、文档编写
- 代码审查和清理
- 最终验证

**目标**: 生产就绪

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

## 🎯 成功标准

### Week 1结束
- ✅ 情感共振率可运行
- ✅ 态度倾向可运行
- ✅ 关键词库可使用

### Week 2结束
- ✅ 喜好维度可运行
- ✅ 编排服务完成
- ✅ 前端UI基础完成

### Week 3结束
- ✅ 聊天积极度可运行
- ✅ 所有API端点完成
- ✅ 前端UI完成

### Week 4结束
- ✅ 所有单元测试通过
- ✅ 集成测试通过
- ✅ 边缘情况处理完善

### Week 5结束
- ✅ 性能优化完成
- ✅ 文档齐全
- ✅ 可以发布v1.0.0

---

**最后更新**: 2026-01-08
**推荐使用**: ✅ 是 (适合2人小团队)
**复杂度**: ⭐⭐ (比功能分支简单得多)

祝开发顺利! 🚀
