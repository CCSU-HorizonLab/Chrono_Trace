# Chrono Trace

> 面向微信聊天记录的本地分析与实时辅助桌面工具。

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3.x-green.svg)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite-5.x-646CFF.svg)](https://vitejs.dev/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6.svg)](https://www.microsoft.com/windows)
[![Status](https://img.shields.io/badge/Status-Core%20Flow%20Ready-brightgreen.svg)](#当前边界)

> 镌刻对话年轮，丈量心动间距

---

## 项目简介

Chrono Trace 是一个基于 `PyWebView + Vue 3 + Python` 的 Windows 桌面应用，围绕微信聊天数据提供两条主链路：

- 历史聊天导入与本地分析
- 实时监听与 AI 沟通建议

默认情况下，聊天数据解密、导入、存储和分析都在本机完成。只有在你启用 LLM 建议时，系统才会把生成建议所需的必要上下文发送到你配置的模型接口。

本地数据默认写入：

```text
%LOCALAPPDATA%\Chrono Trace\chrono_trace.db
```

## 核心能力

### 微信数据导入

- 自动扫描微信 `4.x` 数据目录
- 支持手动指定微信数据路径
- 使用 `wx_key` 获取的密钥做数据库校验与解密
- 联系人、会话、消息逐步入库，支持增量导入

### 历史分析工作台

分析页当前聚焦这几类结果：

| 类别     | 内容                                   |
| -------- | -------------------------------------- |
| 情绪分析 | 情绪趋势、词云、情绪分布               |
| 互动分析 | 时间线、响应时间、主动率、字数投入比例 |
| 关系评估 | 好感度总分与分维度结果                 |
| 辅助信息 | 活跃日历、关系补充信息、偏好关键词配置 |

好感度分析目前采用四个维度：

| 维度       | 默认权重   | 说明                                       |
| ---------- | ---------- | ------------------------------------------ |
| 情感共振率 | 35% 或 40% | 情绪响应、极性一致性、强度匹配、共情信号   |
| 聊天积极度 | 35%        | 日均消息、回复及时性、话题延续性、主动发起 |
| 态度倾向   | 20% 或 25% | 正负向表达、称呼、隐私分享、节假日互动等   |
| 偏好兼容度 | 10%        | 用户配置喜好关键词后参与评分               |

说明：

- 配置了喜好关键词时，权重为 `35 / 35 / 20 / 10`
- 未配置喜好关键词时，偏好维度不参与，权重调整为 `40 / 35 / 25 / 0`

### 实时监听与 AI 建议

实时建议链路当前是：

1. 选择联系人并启动监听
2. 建立启动基线，避免把屏幕上已有旧消息当成新增消息
3. 对增量消息做去重、情绪判断和上下文整理
4. 按触发条件调用 LLM 生成建议
5. 在建议页和悬浮窗中查看结果

当前已落地的关键保护：

- 启动基线，降低旧消息误触发概率
- 监听阶段去重，结合内容、时间锚点和同屏次序识别重复消息
- LLM 上下文去重，减少重复上下文污染
- 会话隔离，避免旧线程把消息写进新会话
- checkpoint backfill，尽量补回连续上下文而不是断裂片段

### 悬浮辅助窗

适合边聊边参考的场景，支持：

- 联系人摘要与建议卡片
- 最近上下文与参考话术
- 模型切换

### 模型配置

通过设置页配置 OpenAI 兼容模型，当前已适配：

| 供应商 / 形态      | 说明                 |
| ------------------ | -------------------- |
| DeepSeek           | 在线 API             |
| OpenAI             | 在线 API             |
| 智谱 GLM           | 在线 API             |
| Moonshot / Kimi    | 在线 API             |
| MiniMax            | 在线 API             |
| Ollama / LM Studio | 本地推理<br />       |
| 自定义             | 任意 OpenAI 兼容接口 |

## 技术架构

```text
┌─────────────────────────────┐
│ Frontend                    │
│ Vue 3 + TypeScript + Vite   │
└──────────┬──────────────────┘
           │ PyWebView Bridge
┌──────────▼──────────────────┐
│ Backend                     │
│ Python Services             │
│ ├─ analysis/   历史分析      │
│ ├─ realtime/   实时监听      │
│ └─ wechat/     数据导入      │
└──────────┬──────────────────┘
           │
┌──────────▼──────────────────┐
│ Data Layer                  │
│ SQLite 本地存储              │
│ 微信数据库解密 + native_uia  │
└─────────────────────────────┘
```

项目目录概览：

```text
backend/
  app/
    db/              # SQLite schema、连接、迁移
    services/
      analysis/      # 历史分析、好感度分析
      realtime/      # 实时监听、情绪分析、AI 建议
      wechat/        # 微信数据库扫描、解密、导入
    webview/         # 前后端桥接
  tests/             # 后端测试

frontend/
  src/
    views/           # Home / Analytics / Suggestions / Settings / FloatingPanel
    components/      # 图表、分析组件、基础组件
    api/             # Bridge API 封装

app.py               # 生产入口
app_dev.py           # 开发入口
requirements.txt
```

## 环境要求

| 项目    | 要求            |
| ------- | --------------- |
| OS      | Windows 10 / 11 |
| Python  | 3.8+            |
| Node.js | 16+             |
| 微信 PC | 4.x             |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### 2. 启动应用

开发模式：

```bash
python app_dev.py
```

生产模式：

```bash
cd frontend
npm run build
cd ..
python app.py
```

开发模式下，前端会由 Vite 提供在 `http://localhost:5173`。

### 3. 获取微信数据库密钥

推荐使用 `wx_key`：

- 仓库：[https://github.com/ycccccccy/wx_key](https://github.com/ycccccccy/wx_key)
- 结果应为 `64` 位十六进制字符串

示例：

```text
1a2b3c4d5e6f7890abcdef1234567890abcdef1234567890abcdef1234567890
```

### 4. 导入聊天数据

1. 启动应用并输入微信数据库密钥
2. 让应用自动扫描微信目录
3. 若自动扫描失败，在界面里手动指定微信数据路径
4. 验证成功后开始导入
5. 在分析页查看结果

微信 `4.x` 常见目录形态：

```text
C:\Users\<用户名>\xwechat_files\wxid_xxx\db_storage\
├── contact\
├── message\
└── session\
```

### 5. 配置实时建议

1. 在设置页填写模型接口信息
2. 选择联系人并启动实时监听
3. 保持微信主窗口可见
4. 在建议页或悬浮窗查看输出

## 当前边界

- 仅支持 Windows
- 仅面向微信 PC 端
- 实时监听运行时统一使用项目内 `native_uia`
- 监听依赖微信主窗口可见，最小化或后台不可见时不保证有效
- 当前以单人聊天为主，不支持多会话并发监听
- 群聊不是当前主目标
- 文件、语音、视频、小程序卡片等复杂消息类型仍以规则识别和占位处理为主

## 开发

### 常用命令

```bash
# 启动桌面开发模式（推荐）
python app_dev.py
```

```bash
# 单独启动前端
cd frontend
npm run dev
cd ..
```

```bash
# 构建前端
cd frontend
npm run build
cd ..
```

```bash
# 运行后端测试
pytest backend/tests/
```

### 推荐先看的模块

- `backend/app/services/wechat/`：微信路径扫描、解密、导入
- `backend/app/services/analysis/`：历史分析与好感度计算
- `backend/app/services/realtime/`：实时监听、触发、LLM 建议
- `backend/app/webview/bridge.py`：前后端桥接接口
- `frontend/src/views/`：主要页面入口

### 打包发布

项目当前已经接入 Windows 安装包打包链路。

一键打包：

```powershell
.\build_release.ps1
```

或直接双击：

```text
build_release.bat
```

核心打包脚本位于：

```text
packaging\build_release.ps1
```

仓库会自动复用或初始化 `.venv-packaging` 作为打包专用环境，减少系统 Python 杂项依赖对 PyInstaller 的影响。

可选打包变体：

```powershell
.\build_release.ps1 -Variant cpu
.\build_release.ps1 -Variant gpu
.\build_release.ps1 -Variant both
```

生产环境测试回归推荐使用快速模式：

```powershell
.\build_release.ps1 -Fast
```

如果快速模式也要生成安装包：

```powershell
.\build_release.ps1 -Fast -IncludeInstaller
.\build_release.ps1 -Fast -Variant both -IncludeInstaller
```

打包产物位置：

```text
release\pyinstaller\Chrono Trace\
release\pyinstaller-gpu\Chrono Trace\
release\installer\
```

其中安装包用于正式分发：

```text
release\installer\ChronoTraceSetup-版本号.exe
release\installer\ChronoTraceSetup-版本号-GPU.exe
```

说明：

- `CPU` 安装包默认内置 CPU 版 PyTorch
- `GPU` 安装包在构建时直接带入 CUDA 版 PyTorch
- `CPU` 包内如果检测到 NVIDIA GPU，可额外下载独立 GPU runtime 到 `%LOCALAPPDATA%\Chrono Trace\runtime\gpu`，重启应用后生效

### 调试建议

- 导入问题优先看路径扫描、密钥校验和数据库解密日志
- 实时监听问题优先确认微信窗口可见，再看 `realtime` 相关日志
- 如果导入成功但结果异常，先直接检查本地用户数据目录中的 SQLite 数据库

## 常见问题

### 未找到微信数据目录

- 确认微信已安装并登录
- 确认版本是 `4.x`
- 改为手动指定路径

### 密钥验证失败

- 确认密钥是 `64` 位十六进制字符串
- 重新运行 `wx_key`

### 导入成功但数据为 0

- 检查是否选错了微信数据目录
- 检查解密后的数据库是否可正常读取
- 检查导入日志和本地 SQLite 数据

### 实时监听没有反应

- 确认当前是单人聊天窗口
- 确认微信主窗口没有最小化
- 确认模型配置可用

## 隐私与安全

- 聊天数据默认只保存在本地
- 解密过程中产生的临时文件应由程序自行清理
- 启用在线模型前，请自行评估上下文发送范围和隐私边界

## 致谢

- [EchoTrace](https://github.com/ycccccccy/echotrace)：微信数据解密参考
- [wx_key](https://github.com/ycccccccy/wx_key)：微信数据库密钥获取工具

## 免责声明

本项目仅供个人学习、研究和本地数据分析使用。请在遵守相关法律法规、平台规范和隐私边界的前提下使用。项目不对因使用本工具产生的任何后果承担责任。

---

最后更新：2026-04-19
