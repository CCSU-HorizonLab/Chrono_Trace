# Chrono Trace

> **"镌刻对话年轮,丈量心动间距"**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3.x-green.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Chrono Trace 是一款**桌面级微信聊天记录分析工具**,通过情绪分析、数据可视化和AI建议,帮助用户更好地理解和管理人际关系。

---

## ✨ 特性

- 🔐 **安全可靠**: 全量本地处理,数据不上传
- 📊 **数据可视化**: 情绪曲线、词云、频率分析
- 🤖 **AI建议**: 基于聊天记录生成沟通策略
- 🚀 **快速导入**: 支持微信4.0+数据库自动解密
- 🕒 **实时监听**: 支持单联系人实时抓取新消息(实验功能,仅限 Windows 微信客户端)
- 🎯 **隐私优先**: 支持数据清理与一键导出


---

## 🚀 快速开始

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd Chrono-Trace

# 安装Python依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend && npm install && cd ..

# 启动应用
python app_dev.py
```

应用将在 `http://localhost:5173` 启动。

### 使用流程

1. **获取密钥**: 使用 [wx_key](https://github.com/ycccccccy/wx_key) 获取微信数据库密钥
2. **导入数据**: 在应用中输入密钥,自动检测并导入数据
3. **数据分析**: 查看情绪曲线、词云等可视化图表
4. **AI建议**: 生成个性化沟通策略

详细步骤见 📖 [安装指南](docs/SETUP.md)

---

## 📖 文档导航

### 🚀 快速入门
- 📖 **[本文档](Readme.md)** - 项目介绍和快速开始
- 📖 **[安装指南](docs/SETUP.md)** - 环境搭建和配置步骤
- 🏗️ **[架构说明](docs/DEVELOPMENT.md)** - 技术架构和目录结构

### 👥 开发团队
- 📋 **[协作流程](docs/SIMPLE_WORKFLOW.md)** - Git工作流和提交规范
- 📋 **[juitar的任务](docs/JUITAR_TASKS.md)** - juitar负责的36个任务
- 🤖 **[AI助手上下文](docs/CLAUDE.md)** - Claude Code的配置

### 📊 功能规格 (002-affinity-analysis)
- 📝 **[好感度需求](docs/history_analyze.md)** - 4维度分析算法说明
- 📦 **[规格文档](specs/002-affinity-analysis/spec.md)** - 完整功能规格（40个需求）
- ✅ **[任务清单](specs/002-affinity-analysis/tasks.md)** - 84个开发任务
- 📚 **[开发指南](specs/002-affinity-analysis/quickstart.md)** - 代码示例和数据库设计
- 🔌 **[API规范](specs/002-affinity-analysis/contracts/bridge_api.yaml)** - 8个RESTful端点

### 📝 其他
- **[更新日志](CHANGELOG.md)** - 版本历史与变更记录

---

## 🎯 核心功能

### 1. 聊天记录管理
- ✅ 微信4.0+数据库自动检测
- ✅ SQLCipher 4加密数据库解密
- ✅ 多数据库分片支持 (11个文件)
- ✅ 自动清理临时文件
- 🕒 实时抓取: 通过 wxauto4 + 轮询监听当前聊天窗口消息并写入暂存表,用于实时分析

### 2. 数据可视化
- 📈 **情绪曲线图**: 展示情绪变化趋势
- ☁️ **词云**: 高频词与主题分析
- 📊 **频率图**: 聊天密度与活跃时段
- 🥧 **实时分析**: 当期情绪占比

### 3. AI建议生成
- 🤖 基于聊天上下文生成策略
- 🎯 支持亲密/维持/疏远等目标
- 💬 提供定制化话术建议
- 🔄 支持实时交互微调

### 4. 隐私与安全
- 🔒 全量本地存储与处理
- 🔑 API密钥加密保存
- 🗑️ 支持数据清理
- 📤 一键导出功能

---

## 🏗️ 技术架构

```
┌─────────────┐
│   前端 Vue   │ ← 用户界面
└──────┬──────┘
       │ PyWebView Bridge
┌──────▼──────┐
│  后端 Python │ ← 业务逻辑
├─────────────┤
│   SQLite    │ ← 数据存储
└─────────────┘
       │
┌──────▼──────┐
│ 微信数据库   │ ← 解密读取
└─────────────┘
```

**技术栈**:
- **前端**: Vue 3 + TypeScript + Vite
- **后端**: Python 3.8+ + PyWebView
- **数据库**: SQLite (本地) + SQLCipher 4 (微信)
- **加密**: pycryptodome (AES-256-CBC)

---

## 📊 项目结构

```
Chrono-Trace/
├── backend/              # 后端服务
│   ├── app/
│   │   ├── db/          # 数据库层
│   │   ├── services/    # 业务逻辑
│   │   │   └── wechat/  # 微信数据处理
│   │   └── webview/     # 前端桥接
│   └── data/            # 数据文件
├── frontend/            # 前端应用
│   ├── src/
│   │   ├── api/        # API调用
│   │   ├── components/ # Vue组件
│   │   └── views/      # 页面
│   └── package.json
├── docs/               # 文档
│   ├── SETUP.md
│   └── DEVELOPMENT.md
├── app.py             # 生产入口
├── app_dev.py         # 开发入口
└── CHANGELOG.md       # 变更日志
```

---

## 🔧 配置说明

### 微信数据目录

**自动检测** (推荐):
- 应用会自动查找微信数据目录
- 支持微信4.0+的 `xwechat_files` 结构

**手动配置**:
- 设置页面 → 勾选"使用自定义路径"
- 选择微信数据目录 (如 `C:\Users\xxx\xwechat_files`)

**目录结构**:
```
xwechat_files/
└── wxid_xxx/
    └── db_storage/
        ├── contact/    # 联系人
        ├── message/    # 消息 (多个分片)
        └── session/    # 会话
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request!

### 开发流程

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

详见 [开发文档](docs/DEVELOPMENT.md)

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

- [EchoTrace](https://github.com/ycccccccy/echotrace) - SQLCipher 4解密算法参考
- [wx_key](https://github.com/ycccccccy/wx_key) - 微信数据库密钥提取工具

---

## ⚠️ 免责声明

本工具仅供个人学习和研究使用,请遵守相关法律法规。使用本工具产生的任何后果由使用者自行承担,开发者不承担任何责任。

---

**最后更新**: 2025-11-27  
**状态**: ✅ 已完成微信V4数据库支持  
**版本**: 1.0.0
