# Realtime Listener 总结

更新时间：2026-03-24

## 一句话结论

当前这台机器上的微信 realtime listener 已经统一到 `native_uia`，并且在“单人聊天”目标场景下把实时监听、去重、sender 判定和 backfill 断点恢复都跑通了。

## 当前现场环境

- 项目路径：`d:\Project\Chrono Trace`
- 微信版本：`4.1.8.29`
- 可执行文件：`D:\Program files\Weixin\Weixin.exe`
- listener profile：`wechat_41x`
- 目标场景：Windows 微信 PC 单人聊天

## 这轮最终落地的点

### 1. 运行时只剩 native_uia

- `RealtimeProviderFactory` 只创建 `native_uia`
- `wxauto` provider 已移除
- `wxauto4.py` / `backend/wxauto4.py` 仅保留兼容入口

### 2. 实时监听不会再把同屏旧消息反复喂给 LLM

- 启动时先建立可见消息基线
- 轮询阶段使用稳定消息身份去重
- 进入 LLM 上下文前再做一层保守去重

### 3. 4.1.x sender 判定修复

截图回退从“整行 midpoint”改成“活跃列聚类 + 主簇中心”，`self / friend` 判定稳定性明显提升。

### 4. backfill 已从弱锚点升级

- checkpoint 会保存 `last_message_context`
- 命中时用上下文滑窗，不再只靠短文本
- `21:20` / `昨天 21:20` 会先归一再匹配
- 回溯滚动采用“先到最新，再按时间差快滚，接近锚点减速”的策略

## 当前真机验证

### 已通过

- smoke validation
- soak test
- cross-chat regression
- 启动历史消息基线 / 去重
- backfill 断点恢复

### 代表日志

- `backend/data/logs/realtime_listener_validation_1774269854.json`
- `backend/data/logs/realtime_listener_soak_1774270008.json`
- `backend/data/logs/realtime_cross_chat_regression_1774270207.json`
- `backend/data/logs/realtime_listener_validation_1774273300.json`
- `backend/data/logs/realtime_backfill_anchor_validation_1774332989.json`

其中 `realtime_backfill_anchor_validation_1774332989.json` 的结果是：

- `success=true`
- `reason=context_window`
- `inserted_count=21`
- `need_reimport=false`

## 当前代码落点

- `backend/app/services/realtime/monitor_service.py`
- `backend/app/services/realtime/providers/native_uia.py`
- `backend/app/services/realtime/providers/detector.py`
- `backend/tests/test_monitor_service_message_dedupe.py`
- `backend/tests/test_native_uia_scroll.py`

## 当前测试结果

本轮相关测试：

```bash
python -m pytest backend/tests/test_monitor_service_message_dedupe.py backend/tests/test_native_uia_scroll.py backend/tests/test_realtime_provider_factory.py backend/tests/test_local_wxauto_shim.py backend/tests/test_soak_realtime_listener.py
```

结果：`34 passed`

## 当前边界

- 当前真机结论以“单人聊天”为主
- 微信窗口必须保持可见，不能最小化
- 如果换机器或升级微信版本，需要重跑验证
- `4.0.5.23` 目前主要靠测试保链路，没有现场机器继续复验

## 建议阅读顺序

1. `docs/realtime_listener_summary.md`
2. `docs/realtime_listener_status.md`
3. `docs/realtime_listener_handoff.md`
4. `backend/app/services/realtime/monitor_service.py`
