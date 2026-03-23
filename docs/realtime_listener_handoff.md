# Realtime Listener Handoff

最后更新：2026-03-23

## 背景

Chrono Trace 正在把微信 realtime 监听主链路从旧的 `wxauto4` 依赖迁移到项目内自研的 `native_uia` 方案。

当前目标：

- 保持前后端调用方式不变
- 先稳定覆盖微信 `4.0.5`
- 后续继续适配微信 `4.1.x`
- `wxauto` 仅保留为兼容兜底，不再作为主实现

## 当前结论

截至目前，微信 `4.0.5.23` 下的 `native_uia` 主链路已经基本可替代当前 realtime 的 `wxauto` 主路径。

已经确认通过的能力：

- 打开目标聊天
- 主窗口单会话实时监听
- 区分 `self / friend / system`
- 文本、图片占位、系统时间分隔条识别
- 启动时跳过当前屏幕上的历史消息，不再误触发建议
- `安 -> 停止 -> 妈` 快速切换时不再串上下文
- 长稳 start / stop soak test 无重复 hash、无 provider 漂移

尚未完成：

- 微信 `4.1.x` 真机适配验证
- 是否彻底移除 `wxauto` 兼容兜底

## 当前运行环境

- 项目路径：`d:\Project\Chrono Trace`
- 当前机器微信版本：`4.0.5.23`
- 当前主监听后端：`native_uia`
- 当前 profile：`wechat_405`
- 当前设置文件：`backend/data/settings.json`

## 当前架构

```text
Suggestions.vue / Floating Panel
            ↓
      PyWebView Bridge
            ↓
 RealtimeMonitorService
            ↓
  RealtimeProviderFactory
       ├─ native_uia      ← 主链路
       └─ wxauto provider ← 兼容兜底
            ↓
 realtime_message_buffer
            ↓
 实时情感分析 / 触发检测 / AI 建议
```

## 核心文件

- `backend/app/services/realtime/monitor_service.py`
- `backend/app/services/realtime/providers/native_uia.py`
- `backend/app/services/realtime/providers/detector.py`
- `backend/app/services/realtime/providers/factory.py`
- `backend/app/services/realtime/providers/models.py`
- `backend/app/services/realtime/providers/debug_tools.py`
- `backend/wxauto4.py`
- `wxauto4.py`

## 关键实现说明

### 1. 兼容入口还在，但已不是旧主链路

`monitor_service.py` 里仍然通过：

```python
from wxauto4 import WeChat
```

这里导入的已经不是外部库直连，而是项目内 shim：

- `wxauto4.py`
- `backend/wxauto4.py`

shim 会把调用转到 `RealtimeProviderFactory`，默认优先创建 `native_uia`。

### 2. provider 抽象已经落地

统一接口已经收敛到 provider 层，核心能力包括：

- `open_chat(display_name)`
- `activate_main_window()`
- `list_visible_messages()`
- `scroll_up()`
- `scroll_down()`
- `close()`

### 3. 项目内统一生成消息 identity

当前 realtime 不再依赖底层库原生 hash 作为唯一身份。

项目内增加了两层去重：

- `seen_message_keys`：用于同一轮监听内的稳定消息身份去重
- canonical `message_hash`：入库时统一生成，供 buffer / checkpoint / 历史恢复使用

### 4. 启动时历史消息不会再误触发

监听启动后，会先读取当前屏幕上的可见消息，写入基线缓存，再开始正式处理新消息。

这解决了之前的典型问题：

- 刚打开某个聊天就把现有历史消息当成新消息
- 误触发实时情感分析
- 误触发 LLM 建议
- 误触发隐式反馈提取

### 5. 会话隔离已经补上

每轮监听都有自己的：

- `session_token`
- `stop_event`
- 冻结的 `batch_id`
- 冻结的 `display_name`

这样旧线程即使延迟返回，也不会再往新会话写消息、建议或规训。

## 这轮修掉的典型问题

### 误触发建议

现象：

- 监听 `安` 时，一打开已有聊天就基于屏幕历史消息触发 LLM

原因：

- 启动时没有建立“可见消息基线”

现状：

- 已修复

### 串会话

现象：

- 先监听 `安`
- 后切到 `妈`
- suggestion / feedback / recent_messages 串台

原因：

- 旧线程和新线程共享动态状态

现状：

- 已修复

### 连续多条自己消息导致重复 feedback 提取

现象：

- 一条建议后，用户连续发多条消息
- 同一条 suggestion 反复触发 DeepSeek feedback extraction

原因：

- suggestion 状态没有先抢占

现状：

- 已修复，先置为 `feedback_processing`

## 已有调试与验证工具

### UIA 快照导出

- 桥接方法：`debug_dump_wechat_uia(...)`
- 文件：`backend/app/services/realtime/providers/debug_tools.py`

输出内容包括：

- 微信版本
- listener profile
- 聊天区 rect
- 可见消息列表
- UIA 树
- 错误信息

### 验证脚本

- `backend/scripts/validate_realtime_listener.py`
- `backend/scripts/soak_realtime_listener.py`
- `backend/scripts/regress_cross_chat_switch.py`

## 已验证记录

推荐查看这些日志文件：

- `backend/data/logs/realtime_listener_validation_1774243363.json`
- `backend/data/logs/realtime_listener_soak_1774243575.json`
- `backend/data/logs/realtime_listener_soak_1774243617.json`
- `backend/data/logs/realtime_cross_chat_regression_1774267052.json`

## 当前文档状态

与旧 `wxauto` 认知相关的前端和文档提示已经清理：

- `frontend/src/views/Suggestions.vue`
- `Readme.md`
- `docs/realtime_suggestion.md`
- `docs/realtime_listener_status.md`

backend 侧的注释也已同步到 provider / `native_uia` 口径：

- `backend/app/db/schema.sql`
- `backend/app/services/realtime/__init__.py`
- `requirements.txt`
- `specs/003-ai-suggestion/spec.md`
- `specs/003-ai-suggestion/plan.md`

## 仍然保留的 wxauto 相关内容

这些仍然存在是刻意保留，不应误删：

- `backend/app/services/realtime/providers/wxauto_provider.py`
- `backend/app/services/realtime/providers/factory.py` 中的 fallback 分支
- `monitor_service.py` 中通过本地 shim 创建 provider 的兼容入口

它们当前的角色是：

- 兼容兜底
- 调试回退
- 迁移期间降低风险

不是当前主链路。

## 下一步建议

最推荐的下一步是开始做微信 `4.1.x` 真机适配。

建议顺序：

1. 用 `debug_dump_wechat_uia()` 抓 `4.1.x` 的 UIA 树
2. 校准聊天区定位
3. 校准 `self / friend / system` 判定
4. 校准时间分隔条与消息类型识别
5. 跑 smoke test、soak test、cross-chat regression
6. 等 `4.1.x` 通过后，再考虑是否彻底移除 `wxauto` 兼容兜底
