# 实时监听状态说明

## 当前主链路

Chrono Trace 的实时监听已经切到项目内 `native_uia` 主链路。

- 唯一运行时后端：`native_uia`
- 统一入口：`RealtimeProviderFactory`
- 统一消息模型：`runtime_id`、`message_hash`、`sender_attr`、`message_type`、`timestamp`

这意味着当前运行时已经不再保留 `wxauto` provider 兜底。
项目中仍保留 `wxauto4.py` / `backend/wxauto4.py` 名字兼容层，但它们内部也只会创建 `native_uia` provider。

## 当前已验证范围

- 平台：Windows 桌面端微信
- 已验证版本：微信 `4.0.5.23`、`4.1.8.28`
- 已验证窗口形态：微信主窗口单会话监听
- 已验证能力：
  - 切换到目标聊天
  - 实时抓取可见新消息
  - 区分 `self / friend / system`
  - 生成稳定 `message_hash`
  - 启动时跳过当前屏幕上的历史消息
  - `安 -> 停止 -> 妈` 跨会话切换不串上下文
  - `4.1.x` 下部分消息 `sender_attr` 判空修复后复验通过

## 当前运行约束

- 仅支持 Windows
- 仅支持微信 PC 主窗口监听
- 微信主窗口需要保持可见，不能最小化
- 联系人显示名必须与微信内一致
- 同一时间只监听一个聊天

## 处理链路

```text
native_uia provider
        ↓
RealtimeMonitorService
        ↓
realtime_message_buffer
        ↓
实时情感分析 / 触发检测
        ↓
AI 建议 / 悬浮辅助
```

## 当前稳定性修复

- 启动监听时，会先把当前可见消息写入去重基线，避免把历史消息误判成新消息
- 每轮监听使用独立的 `session_token` 和 `stop_event`，避免旧线程把数据写进新会话
- 隐式反馈提取会先抢占 suggestion 状态，避免同一条建议被重复分析多次
- 项目内统一生成 canonical `message_hash`，不依赖底层 provider 自带去重标识

## 下一步

- 继续补单人聊天 `4.1.x` 样本，重点覆盖更多文本 / 图片 / 时间分隔条布局
- 继续观察长时运行下的重复 hash、线程稳定性和聊天切换稳定性
