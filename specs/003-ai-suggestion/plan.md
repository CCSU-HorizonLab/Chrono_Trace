# Implementation Plan: AI Suggestion Generation Module

**Branch**: `003-ai-suggestion` | **Date**: 2026-03-02 | **Spec**: [spec.md](spec.md)
**Input**: 实时 AI 建议工作流设计与全自动/半自动/手动触发模式需求

## Summary

本功能旨在通过微信消息实时监听反馈，给出聊天干预指示（话术与策略建议）。
技术方案主要包含四部分：
1. **情感状态追踪器**：基于现有实时情感分析结果做时间窗口聚合与条件判断。
2. **多模态建议引擎抽象层**：设计规整的接口层，并实现首个基于预置模板矩阵的生成器。
3. **Bridge API**：为前端暴露配置变更、获取状态与获取待处理建议等接口，扩充 SQLite 新表。
4. **左右分离视图**：前端大幅改造布局以使得通知与聊天流并排呈现而互不干涉。

## Technical Context

- **语言环境**: Python 3.8+ / Vue 3 + TypeScript
- **数据库**: SQLite (`realtime_suggestions`新表，复用`suggestions`)
- **性能预期**: 判断 < 50ms，完全满足 wxauto4 每秒1次的轮询频次而不产生阻塞。

## Project Structure

```text
backend/
├── app/
│   ├── services/
│   │   └── realtime/
│   │       ├── monitor_service.py                # MODIFY (integrate tracker)
│   │       ├── emotion_state_tracker.py          # NEW
│   │       ├── suggestion_engine.py              # NEW
│   │       ├── template_engine.py                # NEW
│   │       ├── suggestion_templates.py           # NEW
│   ├── db/
│   │   ├── schema.sql                            # MODIFY
│   │   └── migrations/
│   │       └── realtime_suggestions.sql          # NEW
│   └── webview/
│       └── bridge.py                             # MODIFY (new API endpoints)
└── tests/
    ├── test_emotion_state_tracker.py             # NEW
    └── test_template_engine.py                   # NEW

frontend/
├── src/
│   └── views/
│       └── Suggestions.vue                       # MODIFY (Dual column UI)
```

## Task Breakdown & Execution Order

### Phase 1: 追踪器 (Emotion State Tracker)
- [ ] `emotion_state_tracker.py`: Implement `EmotionStateTracker` class with `deque` window and memory map for cooldowns. [Backend]
- [ ] `emotion_state_tracker.py`: Implement the 6 detection rules (`_check_negative_streak`, `_check_emotion_shift`, etc.). [Backend]
- [ ] `test_emotion_state_tracker.py`: Create unit tests validating trigger and cooldown logic with mock message attributes. [Backend]
- [ ] `monitor_service.py`: Inject the tracker instance into the message processing loop, store triggered events appropriately. [Backend]

### Phase 2: 建议抽象与模板引擎 (Suggestion Engines)
- [ ] `suggestion_engine.py`: Define `SuggestionEngine` ABC and `SuggestionResult` dataclass. [Backend]
- [ ] `suggestion_templates.py`: Build static Python dict/JSON string embedding 18 sets of data (6 triggers × 3 intents: intimate, maintain, distance). [Backend]
- [ ] `template_engine.py`: Implement `TemplateSuggestionEngine` mapping trigger type & intent to the loaded templates. [Backend]
- [ ] `test_template_engine.py`: Unit tests validating all 18 cases resolve properly and bounds fallback appropriately. [Backend]

### Phase 3: DB & Bridge API (Integration)
- [ ] `schema.sql`: Implement and apply `realtime_suggestions` table schema. [Backend]
- [ ] `bridge.py`: Add endpoint `get_pending_suggestions(batch_id)`. [Backend]
- [ ] `bridge.py`: Add endpoint `dismiss_suggestion(suggestion_id)`. [Backend]
- [ ] `bridge.py`: Add endpoints `get_suggestion_config()` and `set_suggestion_config(config)` handling Automatic / Semi / Manual behaviors. [Backend]
- [ ] `bridge.py`: Rewrite `generate_suggestion` using `SuggestionEngineFactory` to fulfill the Manual interaction. [Backend]

### Phase 4: UI重构 (Frontend)
- [ ] `Suggestions.vue`: Reconstruct grid layout using Flex or CSS Grid for two-column separation. [Frontend]
- [ ] `Suggestions.vue`: Add settings popup or panel to select Trigger Mode (Auto/Semi/Manual) and Intent. [Frontend]
- [ ] `Suggestions.vue`: Integrate a setInterval polling mechanism against `get_pending_suggestions` and render `Trigger Cards`. [Frontend]
- [ ] `Suggestions.vue`: Implement the expansion transition and mark-as-dismissed callback interaction for Trigger Cards. [Frontend]

## Risk Mitigation
- **Constant state persistence limits**: Store trigger states in RAM (`EmotionStateTracker` members) linked to the running `monitor_service` loop to avoid I/O bottlenecks. Only true "AI Suggestions" that need caching are persisted to SQLite.
- **Poll congestion**: Polling in `Suggestions.vue` may pile up if backend is blocked. Ensure frontend limits concurrent polls and honors a non-blocking request loop.

**Ready for Implementation**: YES
**Plan Status**: 📋 DRAFT COMPLETED
