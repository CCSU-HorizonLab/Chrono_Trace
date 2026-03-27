# Realtime Listener Handoff

最后更新：2026-03-24

## 当前结论

Chrono Trace 的微信 realtime 监听运行时已经统一收口到项目内 `native_uia`。

- 唯一运行时实现：`native_uia`
- `wxauto` provider 已移除
- `wxauto4.py` / `backend/wxauto4.py` 仅保留兼容导入名
- 当前现场验证机：微信 `4.1.8.29`
- 当前现场验证机进程：`D:\Program files\Weixin\Weixin.exe`
- 当前探测 profile：`wechat_41x`

针对当前目标场景“Windows 微信 PC 单人聊天 realtime 监听”，这条链路已经不是“迁移中”，而是“已跑通并有真机验证”的状态。

## 已确认通过的能力

- 打开目标聊天
- 主窗口单会话实时监听
- 区分 `self / friend / system`
- 文本、图片占位、系统时间分隔条识别
- 启动时跳过当前屏幕上的历史消息
- 同屏旧气泡重复渲染时不会反复入库
- 喂给 LLM 前会再做一层保守去重
- `安 -> 停止 -> 妈` 跨会话切换不串上下文
- `4.1.x` 下历史消息 `sender_attr` 判空问题已修复
- backfill 断点命中已升级为“上下文滑窗 + 自适应滚动”，真机已成功补回历史消息

## 这轮最终收口的关键问题

### 1. 运行时统一为 native_uia

`RealtimeProviderFactory` 现在只会创建 `native_uia`。

保留项：

- `wxauto4.py`
- `backend/wxauto4.py`

它们当前只是兼容 shim，不再承担运行时兜底。

### 2. 启动历史消息不会再误喂给 LLM

监听启动后，先读取当前屏幕上的可见消息并建立基线，再开始处理增量消息。

这解决了：

- 一打开聊天就把可见历史消息当成新消息
- 历史消息误触发情感分析
- 历史消息误触发实时建议

### 3. 同屏重复抓取与 LLM 重复上下文已收紧

当前链路有两层去重：

- 监听阶段按“内容 + 稳定时间锚点 + 同屏次序”去重
- LLM 上下文阶段再按 `sender/content/time` 做保守折叠

这解决了：

- Qt 重绘后同一屏旧消息被当成新消息反复入库
- 旧脏消息被重复喂给 LLM，导致建议错位

### 4. 4.1.x sender 判定修复

`4.1.x` 某些消息项 descendants 很少，旧截图回退算法容易把整行噪声当成主气泡。

当前做法：

- 先按列活跃度聚类
- 取主活跃簇
- 再按加权中心判定 `self / friend`

这批真实样本已恢复正常：

- `图片` -> `self`
- `[捂脸]` -> `self`
- `唉、` -> `self`
- `妈能打电话不` -> `self`
- `打呗` -> `friend`

### 5. backfill 断点恢复已从弱锚点升级

旧逻辑的问题：

- `runtime_id` 不能跨会话稳定
- `怎么了` 这类短文本锚点不唯一
- `21:20` / `昨天 21:20` 会因为文案变化错失命中
- 固定小步长回溯在远离断点时很慢

当前做法：

- checkpoint 保存 `last_message_context`
- 命中时优先用“前后邻居消息滑窗”而不是只看单条文案
- 系统时间条归一到稳定 token，避免跨天文案漂移
- 回溯时先对齐到最新，再按时间差做自适应快滚
- 远离断点时会批量做多次小步快滚，接近候选锚点后自动降速

## 当前架构

```text
Suggestions.vue / Floating Panel
            ↓
      PyWebView Bridge
            ↓
 RealtimeMonitorService
            ↓
 RealtimeProviderFactory
       └─ native_uia
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
- `backend/tests/test_monitor_service_message_dedupe.py`
- `backend/tests/test_native_uia_scroll.py`
- `wxauto4.py`
- `backend/wxauto4.py`

## 现场验证记录

推荐优先看这些日志：

- `backend/data/logs/realtime_listener_validation_1774269854.json`
- `backend/data/logs/realtime_listener_soak_1774270008.json`
- `backend/data/logs/realtime_cross_chat_regression_1774270207.json`
- `backend/data/logs/realtime_listener_validation_1774273300.json`
- `backend/data/logs/realtime_backfill_anchor_validation_1774332989.json`

它们分别覆盖：

- smoke validation
- 短时 soak
- 跨聊天切换
- 启动历史消息基线 / 去重
- backfill 断点恢复成功

## 当前测试状态

本轮相关测试命令：

```bash
python -m pytest backend/tests/test_monitor_service_message_dedupe.py backend/tests/test_native_uia_scroll.py backend/tests/test_realtime_provider_factory.py backend/tests/test_local_wxauto_shim.py backend/tests/test_soak_realtime_listener.py
```

结果：`34 passed`

## 当前适用范围

- Windows
- 微信 PC 主窗口
- 单人聊天
- 微信窗口需要保持可见，不能最小化

## 当前边界

- 当前真机结论主要针对单人聊天，不覆盖群聊/文件/语音等非目标场景
- `4.0.5.23` 的 code path 仍在测试里保着，但目前没有现场 `4.0.5` 机器继续复验
- 如果更换机器或微信版本，优先重跑 smoke + soak + backfill validation

## pywechat 可借鉴结论

参考仓库：`https://github.com/Hello-Mr-Crab/pywechat`

当前仍然有效的借鉴点：

- `4.1+` 客户端主进程口径是 `Weixin.exe`
- 顶层窗口类名通常匹配 `Qt\d+QWindowIcon`
- 真正可用于 UIA 识别的主窗口 class 是 `mmui::MainWindow`
- 如果某台机器抓不到内部 UIA 树，可以尝试 Narrator 预激活路径

当前这台机器不需要 Narrator，UIA 树可直接读取。

## 接手时建议

如果后续继续维护这条链路，推荐顺序是：

1. 先看 `docs/realtime_listener_summary.md`
2. 再看 `monitor_service.py` 里的 checkpoint / backfill 相关逻辑
3. 若换机器或升级微信，先跑 smoke、再跑 backfill
4. 若现场问题是“抓到但错判”，优先看 context/window 匹配
5. 若现场问题是“迟迟滚不到”，优先看 time-gap 自适应滚动
