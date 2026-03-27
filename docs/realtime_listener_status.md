# 实时监听状态说明

最后更新：2026-03-24

## 当前状态

Chrono Trace 的 realtime listener 运行时已经统一到项目内 `native_uia`。

- 唯一运行时后端：`native_uia`
- 兼容入口仍保留：`wxauto4.py` / `backend/wxauto4.py`
- `wxauto` provider 已移除
- 当前现场验证机：微信 `4.1.8.29` / `Weixin.exe` / `wechat_41x`

## 当前已验证范围

- Windows 微信 PC 单人聊天
- 打开目标聊天
- 实时抓取增量消息
- 区分 `self / friend / system`
- 启动时跳过当前屏幕历史消息
- 同屏重复消息不会反复入库或反复喂给 LLM
- 跨聊天切换不串上下文
- `4.1.x` 下 sender 判定修复后复验通过
- backfill 断点恢复通过

## 当前关键保护

- 基线跳过：启动监听时先把当前可见消息写入去重基线
- 监听去重：按稳定消息身份去重，减少 Qt 重绘带来的重复抓取
- LLM 去重：进入上下文前再折叠同 sender / 同内容 / 同时间的重复项
- checkpoint 上下文：回溯时不再只靠单条短文本锚点
- 自适应滚动：远离断点时快滚，接近锚点时慢滚

## 当前运行约束

- 仅支持 Windows
- 仅支持微信 PC 主窗口
- 微信窗口需要保持可见，不能最小化
- 同一时间只监听一个聊天
- 当前真机结论以单人聊天为主

## 当前验证参考

- `docs/realtime_listener_summary.md`
- `docs/realtime_listener_handoff.md`
- `backend/data/logs/realtime_listener_validation_1774269854.json`
- `backend/data/logs/realtime_listener_soak_1774270008.json`
- `backend/data/logs/realtime_cross_chat_regression_1774270207.json`
- `backend/data/logs/realtime_backfill_anchor_validation_1774332989.json`

## 当前仍需注意

- `4.0.5.23` 目前主要靠测试保链路，没有现场机器继续复验
- 若换机器或微信版本，优先重跑 smoke + soak + backfill validation
