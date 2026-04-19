# Chrono Trace

> 面向微信聊天记录的本地分析与实时辅助桌面工具。

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3.x-green.svg)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-5.x-646CFF.svg)](https://vitejs.dev/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6.svg)](https://www.microsoft.com/windows)
[![Status](https://img.shields.io/badge/Status-Core%20Flow%20Ready-brightgreen.svg)](#当前限制)

> “镌刻对话年轮，丈量心动间距”

---

## 项目简介

Chrono Trace 是一个基于 `PyWebView + Vue 3 + Python` 的桌面应用，围绕微信聊天数据提供两条核心链路：

- **历史聊天导入与本地分析**：将微信 PC 端聊天记录导入本地数据库，进行多维度可视化分析与关系好感度评估。
- **实时监听与 AI 辅助**：对指定联系人的实时消息进行情绪判断，结合上下文自动生成沟通建议。

历史导入、分析与本地存储默认在本机完成。启用 LLM 建议时，系统会根据所选模型配置发送必要上下文；请按自己的隐私边界配置供应商和模型。

## 核心功能

### 微信数据导入

- 自动扫描微信 4.x 数据目录，支持手动指定路径
- 通过 `wx_key` 获取的密钥进行数据库校验与解密
- 联系人、会话、消息逐步入库，支持增量导入

### 历史分析工作台

分析页面提供完整的本地数据可视化能力，已实现的分析维度包括：

| 分析类别 | 具体内容 |
|---------|---------|
| 情绪分析 | 情绪趋势图、词云 |
| 互动分析 | 会话时间线、响应时间分布、主动率、字数投入比例 |
| 关系评估 | 好感度综合分析（情感共振 / 聊天积极度 / 态度倾向 / 偏好兼容度） |
| 辅助展示 | 活跃日历、关系补充信息、偏好关键词配置 |

详细的指标设计说明见 [历史分析文档](docs/history_analyze.md)。

### 实时建议链路

实时建议覆盖从监听到生成的完整流程：

1. 选择监听对象并启动实时监听
2. 基线去重、断点恢复与 backfill
3. 实时消息展示与情绪判断
4. 根据触发条件调用 LLM 生成沟通建议
5. 支持查看建议生成所用上下文

设计说明见 [实时建议文档](docs/realtime_suggestion.md)。

### 悬浮辅助窗

适用于边聊边参考的场景，支持：

- 联系人摘要与建议卡片查看
- 上下文延续与快捷参考话术
- 模型切换

### 模型配置

通过设置页配置 OpenAI 兼容模型，已适配的供应商与接入形态：

| 供应商 / 形态 | 说明 |
|--------------|------|
| DeepSeek | 在线 API |
| OpenAI | 在线 API |
| 智谱 GLM | 在线 API |
| Moonshot / Kimi | 在线 API |
| MiniMax | 在线 API |
| Ollama / LM Studio | 本地推理 |
| 自定义 | 任意 OpenAI 兼容接口 |

## 技术架构

```text
┌─────────────────────────────┐
│  Frontend                   │
│  Vue 3 + TypeScript + Vite  │
└──────────┬──────────────────┘
           │ PyWebView Bridge
┌──────────▼──────────────────┐
│  Backend                    │
│  Python Services            │
│  ├─ analysis/   历史分析     │
│  ├─ realtime/   实时监听     │
│  └─ wechat/     数据导入     │
└──────────┬──────────────────┘
           │
┌──────────▼──────────────────┐
│  Data Layer                 │
│  SQLite 本地存储             │
│  微信数据库解密 + native_uia │
└─────────────────────────────┘
```

**项目目录概览：**

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

| 依赖项 | 版本要求 |
|-------|---------|
| OS | Windows 10 / 11 |
| Python | 3.8+ |
| Node.js | 16+ |
| 微信 PC | 4.x（已验证 4.1.8.29） |

### 安装与运行

```bash
# 安装后端依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend
npm install
cd ..

# 开发模式（启动 Vite dev server，PyWebView 加载 localhost:5173）
python app_dev.py

# 生产模式（先构建前端静态资源）
cd frontend && npm run build && cd ..
python app.py
```

## 使用流程

### 历史导入与分析

1. 使用 `wx_key` 获取微信数据库密钥
2. 启动应用，在首页输入密钥并校验
3. 自动扫描或手动指定微信数据目录
4. 执行导入，在分析页查看结果

### 实时辅助

1. 在设置页配置并激活可用模型
2. 在建议页选择联系人，启动实时监听
3. 按需切换触发模式和关系意图
4. 如有需要，进入悬浮窗边聊边参考

## 当前限制

- 仅支持 Windows 平台
- 仅面向微信 PC 端
- 实时监听依赖可见的微信主窗口（不能最小化）
- 当前以单对象监听为主，暂不支持多会话并发
- 复杂消息类型以规则识别和占位处理为主
- 群聊不是当前主要目标场景

### 实时监听验证环境

当前实时监听链路使用项目内的 `native_uia` provider。已在以下环境验证通过：

- 微信 `4.1.8.29`
- Windows 微信主窗口可见状态
- 单人聊天场景

更多细节见 [实时监听状态](docs/realtime_listener_status.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [安装说明](docs/SETUP.md) | 环境配置与安装步骤 |
| [开发说明](docs/DEVELOPMENT.md) | 开发环境与调试指南 |
| [历史分析设计](docs/history_analyze.md) | 分析维度与指标定义 |
| [实时建议链路](docs/realtime_suggestion.md) | 实时建议的触发与生成机制 |
| [实时监听状态](docs/realtime_listener_status.md) | 监听能力与兼容性说明 |
| [实时监听总结](docs/realtime_listener_summary.md) | 监听模块设计总结 |
| [监听交接说明](docs/realtime_listener_handoff.md) | 开发交接与上下文说明 |

## 致谢

- [EchoTrace](https://github.com/ycccccccy/echotrace)：微信数据解密参考
- [wx_key](https://github.com/ycccccccy/wx_key)：密钥获取工具

## 免责声明

本项目仅供个人学习、研究和本地数据分析使用。请在遵守相关法律法规、平台规范和隐私边界的前提下使用。项目不对因使用本工具产生的任何后果承担责任。

---

最后更新：2026-04-19 &nbsp;|&nbsp; 项目状态：核心流程可用，持续迭代中
