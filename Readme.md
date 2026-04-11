# Chrono Trace

> 面向微信聊天记录的本地分析与实时辅助桌面工具。

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3.x-green.svg)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-5.x-646CFF.svg)](https://vitejs.dev/)

Chrono Trace 是一个基于 `PyWebView + Vue 3 + Python` 的桌面应用，围绕微信聊天数据提供两条主链路：

- 历史聊天导入与本地分析
- 实时监听、情绪判断与 AI 建议辅助

项目当前已经具备可运行的主流程，重点能力集中在：

- 微信 4.x 数据目录扫描、密钥校验、聊天记录导入
- 历史分析页可视化展示
- 关系/好感度分析
- 单对象实时监听
- 基于触发条件的 AI 建议生成
- 悬浮辅助窗
- 多模型配置与切换

## 当前状态

### 已支持

- Windows 10/11 桌面环境
- 微信 PC 4.x 聊天数据库导入
- SQLite 本地存储
- 分析页基础统计与图表展示
- 好感度分析四维评分
- 单聊天对象的实时监听
- 实时情绪分析与触发式建议
- OpenAI 兼容 LLM 接入
- 悬浮窗辅助查看建议和上下文

### 当前限制

- 仅支持 Windows
- 仅面向微信 PC 端
- 实时监听依赖可见的微信主窗口，不能最小化
- 当前以单对象监听为主，不是多会话并发监听
- 复杂消息类型仍以规则识别和占位处理为主
- 群聊不是当前主要目标场景

### 已验证的实时监听形态

当前实时监听链路统一使用项目内的 `native_uia` provider，兼容入口 `wxauto4.py` 仍然保留，但不再是独立后端。

已在文档中记录的当前验证环境包括：

- 微信 `4.1.8.29`
- Windows 微信主窗口可见状态
- 单人聊天场景

更细的监听说明见 [docs/realtime_listener_status.md](docs/realtime_listener_status.md)。

## 核心能力

### 1. 微信数据导入

- 自动扫描微信 4.x 数据目录
- 支持 `wx_key` 获取的密钥进行校验
- 支持联系人、会话、消息入库
- 支持增量导入，避免重复写入
- 支持手动指定微信目录

### 2. 历史分析

分析页当前已经不是单纯的导入结果页，而是一个本地分析工作台，包含：

- 情绪趋势
- 词云
- 会话时间线
- 响应时间分布
- 主动率分析
- 字数投入比例
- 活跃日历
- 关系补充信息
- 偏好关键词配置
- 好感度综合分析

好感度分析当前包含四个维度：

- 情感共振
- 聊天积极度
- 态度倾向
- 偏好兼容度

更详细的指标设计见 [docs/history_analyze.md](docs/history_analyze.md)。

### 3. 实时建议

实时建议页目前已经覆盖一条完整链路：

- 选择监听对象
- 启动/停止监听
- 监听状态轮询
- 启动基线去重
- 断点恢复与 backfill
- 实时消息展示
- 实时情绪判断
- 触发条件解析
- 调用 LLM 生成建议
- 查看建议生成所用上下文

相关设计说明见 [docs/realtime_suggestion.md](docs/realtime_suggestion.md)。

### 4. 悬浮辅助窗

悬浮窗模式适合边聊边参考，当前已落地的方向包括：

- 联系人摘要展示
- 建议卡片查看
- 上下文延续
- 快捷参考话术
- 模型切换辅助

### 5. 模型配置

设置页支持 OpenAI 兼容模型配置与切换，当前界面和后端已覆盖这些供应商或接入形态：

- DeepSeek
- OpenAI
- 智谱 GLM
- Moonshot / Kimi
- MiniMax
- Ollama
- 自定义 OpenAI 兼容接口

运行时说明里也明确支持本地推理接入，例如 Ollama / LM Studio。

## 技术架构

```text
Vue 3 + TypeScript + Vite
        |
    PyWebView Bridge
        |
Python Backend Services
        |
SQLite / 本地数据存储
        |
微信数据库导入 + native_uia 实时监听
```

主要目录：

```text
backend/
  app/
    db/              # SQLite schema、连接、迁移
    services/
      analysis/      # 历史分析、好感度分析
      realtime/      # 实时监听、情绪分析、AI 建议
      wechat/        # 微信数据库扫描、解密、导入
    webview/         # 前后端桥接

frontend/
  src/
    views/           # Home / Analytics / Suggestions / Settings / FloatingPanel
    components/      # 图表、分析组件、基础组件

docs/                # 补充设计和开发文档
```

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.8+
- Node.js 16+
- 微信 PC 4.x

### 1. 安装依赖

```bash
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### 2. 开发模式启动

```bash
python app_dev.py
```

开发模式会启动前端 Vite dev server，并通过 PyWebView 加载 `http://localhost:5173`。

### 3. 生产模式启动

先构建前端：

```bash
cd frontend
npm run build
cd ..
python app.py
```

## 使用流程

### 历史导入

1. 使用 `wx_key` 获取微信数据库密钥
2. 启动应用，在首页输入密钥并校验
3. 自动扫描或手动指定微信目录
4. 执行导入
5. 在分析页查看历史分析与好感度结果

### 实时辅助

1. 在设置页配置并激活一个可用模型
2. 打开建议页选择联系人
3. 开始实时监听
4. 按需切换触发模式和关系意图
5. 如有需要进入悬浮窗边聊边参考

## 文档导航

- [安装说明](docs/SETUP.md)
- [开发说明](docs/DEVELOPMENT.md)
- [历史分析设计](docs/history_analyze.md)
- [实时建议链路](docs/realtime_suggestion.md)
- [实时监听状态](docs/realtime_listener_status.md)
- [实时监听总结](docs/realtime_listener_summary.md)
- [实时监听交接说明](docs/realtime_listener_handoff.md)

## 适合怎样理解这个项目

现在的 Chrono Trace 更适合被理解成：

- 一个已经跑通主流程的微信聊天本地分析桌面原型
- 一个以本地数据整理、关系分析和实时辅助为核心的工具
- 一个仍在持续迭代、但主链路已经比较清晰的项目

## 致谢

- [EchoTrace](https://github.com/ycccccccy/echotrace)
- [wx_key](https://github.com/ycccccccy/wx_key)

## 免责声明

本项目仅供个人学习、研究和本地数据分析使用。请在遵守相关法律法规、平台规范和隐私边界的前提下使用。

---

最后更新：2026-04-11
项目状态：核心流程可用，持续迭代中
