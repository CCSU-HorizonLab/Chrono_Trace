# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working on in this repository.

## 项目概述

Chrono Trace（时痕）：基于 PyWebView + Vue 3 + Python 的**双平台**（Windows / Linux）桌面应用，面向微信 PC 4.x 聊天数据，提供三条主链路：历史聊天导入与本地分析（好感度四维度评分）、实时监听与 LLM 沟通建议、联系人长期记忆（RAG v4：事实抽取、演变链、纠错闭环）。

本项目所有文档、代码注释、提交信息均使用中文。提交格式：`type：中文描述`（如 `feat：...`、`fix：...`、`docs：...`）。

**分支策略（2026-09 起）**：`os_unified` 为双平台开发主线（单分支同时支持两平台）；`LinuxVersion`、`CodeReview` 已冻结为历史分支，不再双分支同步。

## 平台约束（重要）

- **单分支双平台**：Windows 全功能；Linux 支持导入/分析/RAG/实时监听/悬浮窗（X11 跟随、Wayland 固定档位）。
- Win32 相关导入全部是**函数内延迟导入**；Linux 专属代码走独立模块（`keys/gdb_linux.py`、`db_snapshot.py`、`floating_tracker.py`）。**平台分派收敛点**：密钥提取用 `wechat/keys/__init__.create_key_provider()`，悬浮窗定位用 `floating_tracker.create_tracker()`，Webview 后端用 `webview/gui_backend.py`——不要在业务代码里再写 `sys.platform` 分支。实时监听双平台统一 `providers/db_watch.py`（Linux inotify、Windows 自动降级 stat 轮询），无分派。
- Linux 依赖见 `requirements-linux.txt`（去 pywin32/pywinauto/wx_key wheel）；pywebview 用 Qt 后端（需 qtpy 垫片）。

### 平台组件接缝模式（新增平台能力照此办理）

| 能力 | Windows | Linux | 分派点 |
|---|---|---|---|
| 密钥提取 | `keys/chain_win.py`（只读扫描 `scan_win.py` 优先 → wx_key hook `wx_key_win.py` 回退） | `keys/gdb_linux.py`（GDB 断点，免重启） | `keys/__init__.py` 工厂 |
| 实时监听 | `providers/db_watch.py`（加密库 mtime+WAL 增量解密，stat 轮询） | `providers/db_watch.py`（同源，inotify 触发） | 无分派，双平台统一 |
| 悬浮窗定位 | `floating_window_service.py` 内 win32 分支 | `floating_tracker.py`（X11 EWMH） | `floating_tracker.create_tracker()` |
| Webview 后端 | WebView2（pywebview 默认） | Qt（`gui_backend.py` 显式强制——WebKitGTK 下 storage 为 null 会切页白屏） | `webview/gui_backend.py` |
| 打包 | `build_release.ps1`（PyInstaller+Inno） | `build_release_linux.sh`（PyInstaller onedir+tar.gz） | 各自脚本，互不触碰 |

## 密钥提取子系统（wechat/keys/）

- `base.py`：会话协议（状态字 preparing/hook_ready/captured/failed/timed_out、code 命名空间、密钥类型常量）。
- 密钥类型两种：**passphrase**（32B 口令 hex，按库 salt 经 PBKDF2-HMAC-SHA512(256000) 派生——Linux GDB 与 Windows wx_key 产物）与 **raw**（Windows 只读扫描产物，每库派生密钥 `{salt_hex: enc_key_hex}`，无法反推 passphrase）。
- raw key 消费通道：`db_decryptor_v2.set_raw_key_map()` 在 `derive_keys` 单点按 salt 覆盖，validate/verify/decrypt/ingest/db_snapshot/db_watch 全链自动生效；账号设置存 `key_type` + `raw_keys` 字段。
- Linux 断点地址换算必须走 PT_LOAD 程序头（`keys/gdb_linux.va_to_runtime_addr`）——微信二进制 .text vaddr 从 0x44EC000 起，「映射基址+VA」会偏移 4.5MB。

## 常用命令

```bash
# 开发模式：自动启动 Vite dev server + PyWebView 窗口（双平台）
python app_dev.py

# 仅启动前端（跨平台）
cd frontend && npm run dev

# 构建前端（产物输出到 frontend/webdist/）
cd frontend && npm run build

# 生产模式（需先构建前端）
python app.py

# 后端测试（在仓库根目录运行；两种导入约定都兼容）
pytest backend/tests/

# 运行单个测试文件 / 单个用例
pytest backend/tests/test_preprocessing.py
pytest backend/tests/test_affinity_analysis.py::TestAffinityAnalysisService::test_xxx

# 前端冒烟测试
cd frontend && npm run test:smoke
```

打包：Windows `.\build_release.ps1`（可选 `-Fast`、`-IncludeInstaller`；单变体——onnxruntime-directml 免 CUDA 免 torch 通吃 CPU/GPU，torch 时代 cpu/gpu 双变体与 GPU runtime 下载链已移除）；Linux `./build_release_linux.sh`（可选 `--fast`、`--version`）。详见 `packaging/README.md`。

## 架构

三层结构，前后端通过 PyWebView JS Bridge 通信：

```
Vue 3 + TS + Vite (frontend/src)
        │  window.pywebview.api.*（frontend/src/api/bridge.ts 的 PyWebViewApi 类型）
        ▼
Bridge (backend/app/webview/bridge.py 组合 webview/api/ 下 10 个域 mixin，
        所有暴露给前端的方法)
        ▼
Python services (backend/app/services/{wechat,analysis,realtime,gpu})
        ▼
SQLite（线程本地连接 backend/app/db/connection.py）
```

### 关键机制

- **后端→前端推送通道**：实时消息回显不走前端轮询——monitor 落库即经 `webview/push.py`（入队 + sender 线程聚合）`evaluate_js` 调 `window.__chronoRealtimePush`（App.vue 挂载，转投 `chrono:realtime-push` CustomEvent），FloatingPanel 按批次匹配合并；3s 轮询保留作对账兜底。evaluate_js 只能在后台线程调（GUI 线程同步调死锁，见 close_guard 实录）。
- **Bridge 是唯一前后端边界**：新增前端可调用的 API 必须同时改后端（按 API 域加到 `backend/app/webview/api/*.py` 对应 mixin；导入/监听桥接/建议流等核心域仍在 `bridge.py`）和 `frontend/src/api/bridge.ts`（加 `PyWebViewApi` 类型声明），二者需保持同步。
- **数据库**：`backend/app/db/schema.sql` 是唯一建表源，`connection.py` 只执行建表——**不维护历史库兼容迁移**，结构变更以版本常量记录（如画像 `PROFILE_SNAPSHOT_SCHEMA`），旧库不做升级（缺列报错，删除重导即可）。唯一例外是画像三表（contact_profiles/self_profiles/big5_impressions）：DDL 内联在各服务 `_ensure_table` 懒建（口径见 `docs/analysis/profile-window.md`）。开发模式数据写入 `backend/data/chrono_trace.db`（打包后 Windows 为 `%LOCALAPPDATA%\ChronoTrace\`，Linux 为 `$XDG_DATA_HOME/ChronoTrace/`，显示名 `APP_NAME` 仍带空格）。
- **导入 `backend/app/config.py` 有副作用**：模块加载即创建 `backend/data/{logs,models,temp}` 目录并写入 settings 路径。
- **测试导入约定**：部分测试文件以 `backend/` 为导入根（`sys.path.insert` 后 `from app...`），部分以仓库根（`from backend.app...`，需在仓库根运行 pytest）——新测试优先用前者。

### services 分层

- `wechat/`：微信 4.x 数据目录扫描（`path_finder.py`）、密钥提取（`keys/` 包，见上节）、SQLCipher 解密（`db_decryptor_v2.py`，纯 Python，raw key 通道见上节）、V4 数据库适配层（`db/`，消息表为 `Msg_{md5(username)}` 每联系人一表，经 `Name2Id` 映射发送者）、增量导入编排（`ingest_service.py`）、增量解密快照（`db_snapshot.py`，db_watch 的地基）。
- `analysis/`：历史分析。`preprocessing_service.py`（清洗/表情/XML 去除/会话切分）→ `preprocessing_orchestrator.py` → `feature_extraction_service.py`（嵌入/分类推理走 `onnx_inference.py`：fp16 ONNX + onnxruntime，单后端无 torch 回退）→ `affinity_analysis_service.py` 编排六维度评分：情感共振率、聊天积极度、态度倾向、喜好兼容度（配关键词时启用）、亲密度信号、LLM 关系评估（配模型且开关开时启用）。权重为点数制（默认 0.40/0.35/0.25/0.10/0.12/0.08），由 `affinity_weights.py` 按在场维度归一，缺席自动剔除；用户可在关系信息弹窗配置各维权重。模型 fp16 产物由 `backend/scripts/export_models_onnx.py` 生成（需独立 export 环境，build 脚本已自动处理），安装包内置 `models/<name>/onnx/`。
- `analysis/` 时光深度三件套：`deep_analysis_service.py`（分桶情绪序列/词云演变/里程碑/海报 payload）、`sentiment_backfill_service.py`（情感缓存缺口补算任务，与全面分析双向互斥）、`personality_impression_service.py` + `big5_proxies.py`（大五印象双层：本地统计基础层永远可用，LLM 增强层 ±15 有界校正附证据，远程脱敏红线）。口径与版本规则见 `docs/analysis/time-depth.md`。
- `realtime/`：核心是 `monitor_service.py`（监听编排、启动基线、去重、checkpoint backfill；断点匹配/回溯落库/建议管线拆为 3 个 mixin：`backfill_matcher.py`、`backfill_store.py`、`suggestion_pipeline.py`；画像后台续期在 `generation_context.py`）。消息采集双平台统一 `providers/db_watch.py`（加密库 mtime+WAL 增量解密；Linux inotify、Windows stat 轮询）。触发判定 `trigger_resolver.py` → `llm_engine.py`（OpenAI 兼容接口，适配 DeepSeek/GLM/Kimi/Ollama 等；API 客户端层与响应解析拆为 `llm_client.py`、`suggestion_parsing.py`）。`rag_*` 系列构成联系人级长期记忆（RAG v4）：`rag_store.py`（事实存储+supersede 演变链）、`rag_indexer.py`（分段/嵌入索引）、`rag_retriever.py` + `rag_relevance_gate.py`（混合召回+门控）、`rag_fact_llm.py`/`rag_fact_quality.py`（LLM 结构化抽取+质量门）、`rag_context_builder.py`（分槽注入）。`privacy_redactor.py` 在发送远程 LLM 前做脱敏，失败即阻断。

### RAG v4 文档

记忆子系统的方案、验收口径与历史基线记录在 `docs/rag-v4-improvement-plan.md` 与 `docs/goals/rag-v4-soul-restoration-goal.md`（注意其中对冻结基线的 superseded 标记，勿引用失效数字宣称"全部通过"）。评测/回放/维护脚本在 `backend/scripts/`。

## 前端结构

`frontend/src/views/`：Home / Analytics（对象工作台，页头 FiltersBar 选人一次贯通全页）/ Settings / FloatingPanel（悬浮窗独立页面）。`api/bridge.ts` 封装全部 Bridge 调用，图表用 ECharts，路由 vue-router。无独立状态管理库。面板解剖统一走 `styles/panels.css`（`.panel`/`.panel-head`/`.btn`/`.panel-badge` 等，分析面板不得再自写卡片按钮样式；hover 建议 `:not(:disabled)` 守卫禁用语义）。Analytics 七个页签：关系洞察 / 互动特征 / 内容时间线 / 智能问答 / 时光深度（单聊专属，吸顶工具条锚点导航+全局分段选择器：情绪曲线含分侧互动柱与好感度趋势线/词云分段演变（重点词排行流动图+词云联动高亮，选词按排名方差见 `docs/analysis/time-depth.md`）/大五人格演变（共用分段，分段雷达小多图，逐段可选 AI 增强）/画像分段演变（2~6 段独立选择器，竖排时间线全段卡）/里程碑，组件在 `frontend/src/components/deep/`）/ TA 画像（单聊专属：画像档案（生成入口在画廊头）/我的画像/大五印象（全会话档，与演变面板分工）/分享海报，海报模板注册表 `poster/registry.ts`——公开/自我版经 `sanitizeForPublic`/`sanitizeForSelf` 投影消费，类型上拿不到敏感字段；海报模板节点不引 panels.css 类，html2canvas 对 CSS 变量支持不稳）/ 实时助手（`components/realtime/MonitorControlCard.vue` + 双方画像速览 `persona/ProfileBriefCard.vue`，建议配置按联系人存储）。

### 前端视觉规范（墨痕暖白，2026-10 重做）

全局视觉语言只有一套令牌与惯用语，速查与色值见 `docs/frontend-visual-system.md`（改样式先读它）：

- **令牌唯一来源** `styles/theme.css` `:root`：画布暖纸 `--ct-bg-app` / 卡面白 / 沉底 `--ct-bg-sunken`；主色墨紫 `--ct-color-primary`（hover/-tint/-muted/-subtle 成套）；语义色 success 青绿 / warning 琥珀 / error 珊瑚 / info=primary，各配 `-tint`。**样式里不写裸 hex**，例外仅四类：微信拟物与品牌绿、script 内数据色板（chartTheme/词云/热力色带）、tint 底上的可访问性深字、poster 海报群（整区豁免，不引任何 `var(--ct`）。
- **确立惯用语**（勿自造变体）：状态徽标 = tint 底+语义色字；输入焦点 = border primary + 3px primary-tint 光圈；分段器 = 7% 墨色凹槽 + 白色激活胶囊 + primary 字；开关 ON = primary（非绿）；hover 只变底色/边色**不上浮**；全站零渐变、零彩色投影。
- **图表单一来源** `components/charts/chartTheme.ts`：数据色板 `CHART_PALETTE`、热力色带 `HEAT_RAMP`、`chrono` 主题与 `chronoAxisBase()`，ECharts 配置一律接它，不散写轴色。
- **历史别名已清零**：`--ct-bg-secondary`/`--ct-text-muted` 等旧名已删，`tests/tokens.smoke.test.mjs` 守门（未定义令牌/别名回潮/元素选择器皮肤/海报区引变量，四类违规直接红）。
- **!important 禁用**：全库合法存量仅 3 处（theme.css reduced-motion ×2、WordEvolutionPanel 行内网格覆盖 ×1），新代码零配额。
