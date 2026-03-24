# Realtime Listener Handoff

最后更新：2026-03-23

## 背景

Chrono Trace 正在把微信 realtime 监听主链路从旧的 `wxauto4` 依赖迁移到项目内自研的 `native_uia` 方案。

当前目标：

- 保持前后端调用方式不变
- 先稳定覆盖微信 `4.0.5`
- 后续继续适配微信 `4.1.x`
- 运行时统一收口到项目内 `native_uia`
- 仅保留 `wxauto4` 名字兼容层，不再保留 `wxauto` provider 兜底

## 当前结论

截至目前，微信 `4.0.5.23` 下的 `native_uia` 主链路已经基本可替代当前 realtime 的 `wxauto` 主路径。

2026-03-23 已在当前机器补做了一轮微信 `4.1.8.28` 现场确认，结论是：

- 主进程已变为 `Weixin.exe`
- 顶层窗口类名为 `Qt51514QWindowIcon`
- UIA 连接后的主窗口类名为 `mmui::MainWindow`
- 项目内 `detect_running_wechat()` 已可识别为 `wechat_41x`
- `debug_dump_wechat_uia()` 已能读取可见消息与消息项 class
- 当前机器上的 `smoke / soak / cross-chat regression` 已跑通
- `4.1.x` 下部分文本消息 `sender_attr` 判空问题已修复

已经确认通过的能力：

- 打开目标聊天
- 主窗口单会话实时监听
- 区分 `self / friend / system`
- 文本、图片占位、系统时间分隔条识别
- 启动时跳过当前屏幕上的历史消息，不再误触发建议
- `安 -> 停止 -> 妈` 快速切换时不再串上下文
- 长稳 start / stop soak test 无重复 hash、无 provider 漂移

尚未完成：

- 扩大 `4.1.x` 单人聊天样本覆盖到更多文本 / 图片 / 时间分隔条布局
- 跑更长时长的 soak test
- 是否进一步收口遗留的兼容命名与配置字段

## 当前运行环境

- 项目路径：`d:\Project\Chrono Trace`
- 当前稳定基线微信版本：`4.0.5.23`
- 当前现场验证机微信版本：`4.1.8.28`
- 当前现场验证机可执行文件：`D:\Program files\Weixin\Weixin.exe`
- 当前现场验证机顶层窗口类名：`Qt51514QWindowIcon`
- 当前主监听后端：`native_uia`
- 当前探测 profile：`wechat_41x`
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
       └─ native_uia      ← 唯一运行时实现
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

### 1. 兼容入口还在，但底层只剩 native_uia

`monitor_service.py` 里仍然通过：

```python
from wxauto4 import WeChat
```

这里导入的已经不是外部库直连，而是项目内 shim：

- `wxauto4.py`
- `backend/wxauto4.py`

shim 会把调用转到 `RealtimeProviderFactory`，而 factory 现在只会创建 `native_uia`。

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

### 6. 微信 4.1.x 现场观察补充

当前机器实测结果：

- `detect_running_wechat()` 返回版本：`4.1.8.28`
- `detect_running_wechat()` 返回 exe path：`D:\Program files\Weixin\Weixin.exe`
- `debug_dump_wechat_uia()` 已成功输出：`backend/data/logs/wechat_uia_dump_1774269467.json`
- dump 中可见主窗口 class：`mmui::MainWindow`
- dump 中可见消息项 class：`mmui::ChatTextItemView`、`mmui::ChatItemView`、`mmui::ChatBubbleReferItemView`
- dump 中已成功识别 `friend / system / image`

这说明当前项目内 `native_uia` 路线在 `4.1.8` 上并不是“完全不可用”，而是已经具备继续校准的基础。

当天继续补做的验证结果：

- smoke validation 已通过：`backend/data/logs/realtime_listener_validation_1774269854.json`
- soak test 已通过：`backend/data/logs/realtime_listener_soak_1774270008.json`
- cross-chat regression 已通过：`backend/data/logs/realtime_cross_chat_regression_1774270207.json`
- sender 判定修复后的 validation 已通过：`backend/data/logs/realtime_listener_validation_1774270741.json`
- sender 判定修复后的 dump：`backend/data/logs/wechat_uia_dump_1774270724.json`

截至这一版文档，当前机器上的 `4.1.8.28` 已不是“待验证”状态，而是“单机主链路已跑通，仍待扩大样本”状态。

### 7. pywechat 可借鉴结论

参考仓库：`https://github.com/Hello-Mr-Crab/pywechat`

对当前适配最有价值的结论是：

- `4.1+` 客户端主进程口径是 `Weixin.exe`
- 顶层 Win32 窗口类名通常匹配 `Qt\d+QWindowIcon`
- 真正可用于 UIA 识别的主窗口 class 是 `mmui::MainWindow`
- 会话列表 / 聊天列表 / 聊天气泡 class 仍然大量使用 `mmui::...` 命名

`pywechat` 还提到一个重要经验：

- 若某台机器上微信 `4.1+` UIA 树不可见，可尝试“登录前开启讲述人（Narrator），保持一段时间后关闭”这一可访问性激活路径

当前这台机器上不需要额外做这一步，项目内 dump 已能直接抓到 UIA 树；但如果后续换机器出现“只能看到 Qt 壳，抓不到内部控件”的情况，可以把它作为排查项。

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

### 4.1.x 下部分消息 sender_attr 判空

现象：

- 微信上可见的历史消息中，部分 `mmui::ChatTextItemView` / `mmui::ChatBubbleReferItemView` 被识别到内容
- 但 `sender_attr` 返回空字符串

原因：

- `4.1.x` 某些消息项几乎没有可用 descendants
- 旧截图回退算法按“整行活跃范围 midpoint”判定，容易被左边缘单列噪声拖成近似全宽

现状：

- 已修复
- 当前改为先按列活跃度聚类，提取主活跃簇，再按加权中心判定 `self / friend`
- 修复后已在聊天 `妈` 的真实样本上确认恢复：
  - `图片` -> `self`
  - `[捂脸]` -> `self`
  - `唉、` -> `self`
  - `妈能打电话不` -> `self`
  - `打呗` -> `friend`

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

- `backend/data/logs/realtime_listener_validation_1774269854.json`
- `backend/data/logs/realtime_listener_soak_1774270008.json`
- `backend/data/logs/realtime_cross_chat_regression_1774270207.json`
- `backend/data/logs/realtime_listener_validation_1774270741.json`
- `backend/data/logs/realtime_listener_validation_1774271274.json`
- `backend/data/logs/wechat_uia_dump_1774270724.json`

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

- `monitor_service.py` 中通过本地 shim 创建 provider 的兼容入口
- `wxauto4.py`
- `backend/wxauto4.py`

它们当前的角色是：

- 兼容旧导入路径
- 降低上层改名成本

它们已经不是独立后端，也不再承担运行时兜底。

## 下一步建议

最推荐的下一步是继续扩大微信 `4.1.x` 单人聊天真机样本覆盖。

建议顺序：

1. 继续覆盖更多单聊样本，优先补长文本、连续多条文本、更多图片样本、更多时间分隔条样本
2. 在不同窗口尺寸下复查聊天区定位和 `self / friend / system` 判定
3. 跑更长时长的 soak test，重点观察 start / stop 与重复 hash
4. 如果换机器后 `4.1.x` UIA 树不可见，再尝试 `pywechat` 提到的 Narrator 预激活路径
5. 等 `4.1.x` 在多样本、多时长下都稳定后，再考虑是否继续收口 `wxauto4` 兼容命名
