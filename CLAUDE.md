# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Chrono Trace（时痕）：基于 PyWebView + Vue 3 + Python 的 **Windows 专用**桌面应用，面向微信 PC 4.x 聊天数据，提供三条主链路：历史聊天导入与本地分析（好感度四维度评分）、实时监听与 LLM 沟通建议、联系人长期记忆（RAG v4：事实抽取、演变链、纠错闭环）。

本项目所有文档、代码注释、提交信息均使用中文。提交格式：`type：中文描述`（如 `feat：...`、`fix：...`、`docs：...`）。

## 平台约束（重要）

- **双平台支持**（LinuxVersion 分支，2026-09）：Windows 全功能；Linux 支持导入/分析/RAG/实时监听/悬浮窗（X11 跟随、Wayland 固定档位）。
- Windows：微信 PC 4.x 数据目录扫描、wx_key hook 密钥捕获、native_uia 实时监听、win32 悬浮窗。
- Linux：`~/文档/xwechat_files`（XDG 发现）、GDB 断点密钥捕获（`key_capture_linux.py`，免重启、重登触发）、`db_watch` provider 实时监听（加密库 mtime+WAL 增量解密直读）、X11 悬浮窗跟随。
- 密钥格式两平台同构：db_key = 32 字节 passphrase hex，按库 salt 经 PBKDF2-HMAC-SHA512(256000) 派生（`db_decryptor_v2`）。
- Linux 断点地址换算必须走 PT_LOAD 程序头（`va_to_runtime_addr`）——微信二进制 .text vaddr 从 0x44EC000 起，「映射基址+VA」会偏移 4.5MB。
- Win32 相关导入全部是**函数内延迟导入**。新增平台专属代码：Windows 走延迟导入，Linux 走 `sys.platform != "win32"` 分支或独立模块（`key_capture_linux.py`/`db_snapshot.py`/`floating_tracker.py`/`providers/db_watch.py`）。
- Linux 依赖见 `requirements-linux.txt`（去 pywin32/pywinauto/wx_key wheel）；pywebview 用 Qt 后端（需 qtpy 垫片）。

## 常用命令

```bash
# 开发模式（Windows）：自动启动 Vite dev server + PyWebView 窗口
python app_dev.py

# 仅启动前端（跨平台）
cd frontend && npm run dev

# 构建前端（产物输出到 frontend/webdist/）
cd frontend && npm run build

# 生产模式（Windows，需先构建前端）
python app.py

# 后端测试（在仓库根目录运行）
pytest backend/tests/

# 运行单个测试文件 / 单个用例
pytest backend/tests/test_preprocessing.py
pytest backend/tests/test_affinity_analysis.py::TestAffinityAnalysisService::test_xxx

# 前端冒烟测试
cd frontend && npm run test:smoke
```

打包（仅 Windows）：`.\build_release.ps1`（可选 `-Fast`、`-Variant cpu|gpu|both`、`-IncludeInstaller`），详见 `packaging/README.md`。

## 架构

三层结构，前后端通过 PyWebView JS Bridge 通信：

```
Vue 3 + TS + Vite (frontend/src)
        │  window.pywebview.api.*（frontend/src/api/bridge.ts 的 PyWebViewApi 类型）
        ▼
Bridge (backend/app/webview/bridge.py，约 4600 行，所有暴露给前端的方法)
        ▼
Python services (backend/app/services/{wechat,analysis,realtime,gpu})
        ▼
SQLite（线程本地连接 backend/app/db/connection.py）
```

### 关键机制

- **Bridge 是唯一前后端边界**：新增前端可调用的 API 必须同时改 `backend/app/webview/bridge.py`（加方法）和 `frontend/src/api/bridge.ts`（加 `PyWebViewApi` 类型声明），二者需保持同步。
- **数据库**：全新库由 `backend/app/db/schema.sql` 初始化；已有库通过 `db/migrations/*.sql` 和 `connection.py` 内的 Python 兼容迁移（如账号隔离 `account_wxid` 列）升级。开发模式数据写入 `backend/data/chrono_trace.db`（打包后为 `%LOCALAPPDATA%\Chrono Trace\`）。
- **导入 `backend/app/config.py` 有副作用**：模块加载即创建 `backend/data/{logs,models,temp}` 目录并写入 settings 路径。
- **测试导入约定**：测试文件顶部 `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))` 后 `from app...` 导入——即以 `backend/` 为导入根，`app` 指 `backend/app` 包。

### services 分层

- `wechat/`：微信 4.x 数据目录扫描（`path_finder.py`）、密钥获取（`key_provider.py` 延迟导入 wx_key；`key_capture_flow.py` win32 进程注入）、SQLCipher 解密（`db_decryptor*.py`，纯 Python 实现）、V3/V4 数据库适配层（`db/`，V4 消息表为 `Msg_{md5(username)}` 每联系人一表，经 `Name2Id` 映射发送者）、增量导入编排（`ingest_service.py`）。
- `analysis/`：历史分析。`preprocessing_service.py`（清洗/表情/XML 去除）→ `preprocessing_orchestrator.py` → `feature_extraction_service.py`（torch/sentence-transformers，GPU 可选）→ `affinity_analysis_service.py` 编排四维度评分：情感共振率、聊天积极度、态度倾向、偏好兼容度（配置偏好关键词时权重 35/35/20/10，未配置时 40/35/25/0）。
- `realtime/`：核心是 `monitor_service.py`（约 3900 行，监听编排、启动基线、去重、checkpoint backfill）。消息采集经 `providers/`（生产用 `native_uia.py`，pywinauto UIA）。触发判定 `trigger_resolver.py` → `llm_engine.py`（OpenAI 兼容接口，适配 DeepSeek/GLM/Kimi/Ollama 等）。`rag_*` 系列构成联系人级长期记忆（RAG v4）：`rag_store.py`（事实存储+supersede 演变链）、`rag_indexer.py`（分段/嵌入索引）、`rag_retriever.py` + `rag_relevance_gate.py`（混合召回+门控）、`rag_fact_llm.py`/`rag_fact_quality.py`（LLM 结构化抽取+质量门）、`rag_context_builder.py`（分槽注入）。`privacy_redactor.py` 在发送远程 LLM 前做脱敏，失败即阻断。
- `gpu/`：CPU 安装包运行时下载独立 GPU runtime。

### RAG v4 文档

记忆子系统的方案、验收口径与历史基线记录在 `docs/rag-v4-improvement-plan.md` 与 `docs/goals/rag-v4-soul-restoration-goal.md`（注意其中对冻结基线的 superseded 标记，勿引用失效数字宣称"全部通过"）。评测/回放/维护脚本在 `backend/scripts/`。`docs/archive/` 存放已取代的方案文档。

## 前端结构

`frontend/src/views/`：Home / Analytics / Suggestions / Settings / FloatingPanel（悬浮窗独立页面）。`api/bridge.ts` 封装全部 Bridge 调用，图表用 ECharts，路由 vue-router。无独立状态管理库。
