# Feature Specification: Real-time AI Suggestion System

**Feature Branch**: `003-ai-suggestion`
**Created**: 2026-03-02
**Status**: Draft
**Input**: 用户需求："实现实时AI建议生成模块，在用户监听微信聊天时根据对方情绪变化推送话术建议。支持三种触发模式（全自动/半自动/手动），建议引擎支持规则模板和LLM切换，前端左右分栏布局。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full-Automatic Mode (Priority: P2)

新手用户希望在聊天时，系统能自动分析每一条对方发来的消息，并立即给出回复建议，以应对不擅长聊天的困境。

**Why this priority**: 全自动模式能最全面地展示系统能力，但由于可能频繁刷屏，在实际日常使用中不如半自动模式常用，因此优先级为 P2。

**Acceptance Scenarios**:
1. **Given** 触发模式设置为"全自动"，**When** 对方发送一条新消息被监听到，**Then** 系统立刻生成并展示当下的建议摘要和具体话术。
2. **Given** 对方连续快速发送多条消息，**When** 系统触发全自动建议，**Then** 受到"更新频率上限"（如10秒）的节流，避免建议面板频繁闪烁变动。

---

### User Story 2 - Semi-Automatic Mode (Priority: P1)

日常使用场景下，用户不希望被频繁打扰，只希望在对方情绪出现明显波动（消极、突变）、或对话陷入僵局（敷衍、冷场）时，系统才推送提示，并由用户自己决定是否查看具体话术。

**Why this priority**: 这是最符合真实对话节奏、用户体验最佳的核心模式。

**Acceptance Scenarios**:
1. **Given** 触发模式设置为"半自动"，**When** 对方连续发出3条情感极性为消极（polarity=-1）的消息，**Then** 侧边栏弹出提示卡片："🔴 对方情绪持续低落"，但不直接霸屏。
2. **Given** 提示卡片已显示，**When** 用户点击提示，**Then** 展开显示针对此场景的 2-3 条建议话术。
3. **Given** 刚触发过"连续消极"警告，此时对方又发了一条消极消息，**When** 系统再次检测，**Then** 由于处于冷却时间（如120秒）内，系统不重复弹出新的提示。

---

### User Story 3 - Manual Mode (Priority: P2)

有经验的用户只需系统作为一个被动的参考工具。用户遇到不知道怎么回的消息时，手动点击请求建议。

**Why this priority**: 提供了最底层的控制权，实现最简单。

**Acceptance Scenarios**:
1. **Given** 触发模式设置为"纯手动"，**When** 对方发送多条消极消息，**Then** 系统不弹出任何提示，仅更新情绪态势指示器。
2. **Given** 此时用户点击"生成建议"，**When** 系统处理请求，**Then** 返回基于当前滑动窗口内情绪状态的建议内容。

---

### User Story 4 - Emotion Tracker & Abstract Engine (Priority: P1)

系统能在后台持续追踪对方最近 N 条消息的情绪走向，并能根据用户设定的"发展走向"（亲密/维持/疏远），通过模板引擎输出截然不同的话术。

**Acceptance Scenarios**:
1. **Given** 系统正在监听，**When** 新消息到来，**Then** `EmotionStateTracker` 正确更新滑动窗口，剔除超出窗口（>5条）的旧消息。
2. **Given** 触发了"感情升温窗口"，当前设定走向为"亲密"，**When** 引擎生成建议，**Then** 返回热情、主动的话术。
3. **Given** 同一触发场景下，当前设定走向为"疏远"，**When** 引擎生成建议，**Then** 返回冷淡、简短、终止话题的话术。

---

### Edge Cases
- **对方只发图片/表情**：RoBERTa 对纯表情或无法解析的长文本分析失效时，极性归 0，需考虑这类消息对滑动窗口连续性检测的打断情况。
- **长时间未产生新消息或中途断网**：情绪滑动窗口内即使存有消息，其时间戳也已过期。超时需适当衰减或清空。

## Requirements *(mandatory)*

### Functional Requirements

**Phase 1: 情绪状态追踪器 (Emotion Tracker)**
- **FR-001**: System MUST maintain a sliding window of the last N (default: 5) messages from the conversational partner.
- **FR-002**: System MUST detect 'negative streak' (e.g. 3 consecutive negative messages).
- **FR-003**: System MUST detect 'emotion shift' (positive to negative transition within the window).
- **FR-004**: System MUST detect 'perfunctory replies' (e.g. 3 consecutive short <5 chars messages).
- **FR-005**: System MUST detect 'silence' (no messages for >10 mins while monitoring).
- **FR-006**: System MUST detect 'positive window' (e.g. 3 consecutive positive messages with high intensity).
- **FR-007**: System MUST detect 'topic cooling' (message frequency dropping by >50% in 5 mins).
- **FR-008**: System MUST enforce configurable cooldown periods per trigger type to prevent spam.

**Phase 2: 建议引擎抽象层 (Suggestion Engine)**
- **FR-009**: System MUST define an abstract base class `SuggestionEngine` with a unified `generate` interface.
- **FR-010**: System MUST implement `TemplateSuggestionEngine` providing pre-defined responses based on a 6 (trigger types) × 3 (relationship intents: intimate/maintain/distance) matrix (total 18 sets of templates).
- **FR-011**: System MUST support configuring the active engine type (default: template).

**Phase 3: 触发模式与配置 (Trigger Modes & Control)**
- **FR-012**: System MUST support 'Full-Automatic', 'Semi-Automatic', and 'Manual' trigger modes.
- **FR-013**: In Full-Automatic mode, system MUST attempt to show suggestions for every incoming message, subject to a configurable update rate limit (default 10s).
- **FR-014**: In Semi-Automatic mode, system MUST only present trigger prompts when tracker conditions are met, allowing user to expand them.
- **FR-015**: In Manual mode, system MUST NOT push suggestions automatically.
- **FR-016**: System MUST constantly update the emotion tracking state regardless of active mode.

**Phase 4: 前端重构 (Frontend & UI)**
- **FR-017**: Frontend MUST redesign `Suggestions.vue` into a side-by-side split layout (message stream on the left, suggestion panel on the right) when screen width allows.
- **FR-018**: System MUST provide visual indication of the current emotion state/trend in the suggestion panel.
- **FR-019**: Frontend MUST poll the backend periodically (e.g., every 3s) for pending automated suggestions or triggers.
- **FR-020**: Users MUST be able to switch the desired 'relationship intent' (intimate/maintain/distance) on the fly via the UI.

### Key Entities

- **EmotionStateTracker**: 内部缓存与条件判断器。
- **TriggerEvent**: 触发事件（类别，时间戳，严重度，上下文）。
- **SuggestionResult**: 建议返回结果（摘要，话术列表，置信度等）。
- **realtime_suggestions**: 存放生成的待读和历史建议的数据库表。

## Success Criteria *(mandatory)*

### Measurable Outcomes
- **SC-001**: 延迟测试 - 每条消息经过 Tracker 的更新与判断开销需 < 50ms。
- **SC-002**: 模板引擎生成延迟 < 10ms。
- **SC-003**: 根据给定的各测试特征，所有 6 种半自动触发策略能在特定模拟消息流序列上被 100% 准确命中，且在冷却期内不重复命中。
- **SC-004**: 左右分栏布局在宽度 >1000px 的窗体内能正常并列显示，无元素遮挡；在极窄模式下折叠或堆叠。

## Assumptions
- 用户微信客户端保持正常，且 wxauto4 的抓取无严重延迟。
- 先前已有的 `realtime_sentiment_cache` 和 RoBERTa-small 情感分析结果已经高度可信并且就绪。
- 不修改原有的 `realtime_message_buffer` 和长期分析代码。
- Phase 1 不接入 LLM API，仅依赖本地内置 Template Engine。

## Out of Scope
- 本地或云端 LLM 引擎插件的正式开发（本次仅实现抽象层和由配置指定的路由机制）。
- 多窗口支持或自动随动微信边框悬浮功能。
- 多人聊天/群组模式的实时分析。
