# 实时 AI 建议链路说明

最后更新：2026-03-24

## 目标

在用户监听微信单人聊天时，根据实时消息、情绪走势和触发条件生成建议，并尽量避免“旧消息误触发”和“重复上下文污染”。

## 当前实现口径

- 监听后端统一为项目内 `native_uia`
- `wxauto4` 仅保留兼容导入名，不再是独立后端
- 目标场景是 Windows 微信 PC 主窗口单人聊天

## 当前处理链路

```text
native_uia provider
    ↓
RealtimeMonitorService
    ↓
realtime_message_buffer
    ↓
实时情感分析 / 情绪状态追踪 / 触发检测
    ↓
LLM 建议生成
    ↓
realtime_suggestions / 前端 Suggestions.vue
```

## 当前已落地的关键保护

### 1. 启动基线

监听开始时先读取当前屏幕上的可见消息，写入去重基线，再开始处理增量消息。

作用：

- 避免一打开聊天就把屏幕历史消息当成新消息
- 避免历史消息误触发情感分析和建议

### 2. 监听阶段去重

当前监听不再直接相信 provider 的原始 hash / runtime_id。

实际会结合：

- 内容
- 稳定时间锚点
- 同屏次序

来生成更稳定的消息身份，尽量抵抗 Qt 重绘带来的重复抓取。

### 3. LLM 上下文去重

在拼接“最近对话”之前，还会对同 sender、同内容、同时间的重复消息再做一层折叠。

作用：

- 降低旧脏数据被重复送入 LLM 的概率
- 减少角色错位和上下文重复放大

### 4. 会话隔离

每次监听都有独立的：

- `session_token`
- `stop_event`
- `batch_id`
- `display_name`

作用：

- 旧线程不会把消息写进新会话
- suggestion / feedback / recent_messages 不会串台

## 当前与建议质量强相关的链路

### sender 判定

`4.1.x` 的历史消息 sender 判定已经修复，当前依赖：

- UIA 可见结构
- 截图活跃列聚类回退

如果这块错，后续建议的人称和语气都会被带偏。

### backfill 断点恢复

当前 checkpoint 恢复不再只靠单条短文本，而是：

- 保存 `last_message_context`
- 用上下文滑窗命中锚点
- 对系统时间条做稳定化归一
- 结合自适应滚动快速回到目标区间

这决定了历史补回后，建议看到的是不是连续对话而不是断裂片段。

## 当前适用范围

- 单人聊天
- 文本 / 图片占位 / 系统时间分隔条
- 微信 PC 主窗口可见状态

## 不在当前主目标内

- 群聊
- 文件 / 语音 / 视频 / 小程序卡片等复杂消息类型
- 最小化或后台不可见窗口

## 相关文档

- `docs/realtime_listener_summary.md`
- `docs/realtime_listener_handoff.md`
- `docs/realtime_listener_status.md`
