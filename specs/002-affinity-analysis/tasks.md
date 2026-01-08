# Tasks: Conversation Affinity Analysis System

**Input**: Design documents from `/specs/002-affinity-analysis/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 单元测试和集成测试任务已包含在每个阶段中

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `backend/app/` (Python服务)
- **Frontend**: `frontend/src/` (Vue 3 UI)
- **Database**: `backend/app/db/` (SQLite schema)
- **Tests**: `backend/tests/` (pytest测试)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency setup

- [ ] T001 Add new dependencies to backend/requirements.txt (snownlp>=0.12.3, sentence-transformers>=2.2.0, scikit-learn>=1.3.0, torch>=2.0.0)
- [ ] T002 [P] Install Python dependencies via pip install -r backend/requirements.txt
- [ ] T003 [P] Download sentence-transformers model (paraphrase-multilingual-MiniLM-L12-v2) to cache for faster startup

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Database Schema (Migrates 6 New Tables)

- [ ] T004 Create migration script backend/app/db/migrations/sentiment_cache.sql for sentiment caching table
- [ ] T005 [P] Create migration script backend/app/db/migrations/speech_units.sql for speech units table
- [ ] T006 [P] Create migration script backend/app/db/migrations/interaction_pairs.sql for interaction pairs table
- [ ] T007 [P] Create migration script backend/app/db/migrations/affinity_config.sql for configuration table
- [ ] T008 [P] Create migration script backend/app/db/migrations/keyword_libraries.sql for keyword libraries table
- [ ] T009 [P] Create migration script backend/app/db/migrations/affinity_scores.sql for scores table
- [ ] T010 Run all migration scripts to create 6 new tables in backend/data/chrono_trace.db

### Keyword Library Seeding

- [ ] T011 Create backend/scripts/populate_default_keywords.py to seed 6 default keyword categories
- [ ] T012 Run populate_default_keywords.py to insert default keywords (10 per category: positive, negative, empathy, soothing, privacy, holiday)

### Test Data Preparation

- [ ] T013 [P] Create backend/tests/fixtures/conversation_small.json with 1,000 test messages
- [ ] T014 [P] Create backend/tests/fixtures/conversation_medium.json with 10,000 test messages
- [ ] T015 [P] Create backend/tests/fixtures/conversation_labeled.json with manually labeled sentiment data

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Emotional Resonance Analysis (Priority: P1) 🎯 MVP

**Goal**: 实现情感共振率维度分析,包括双向积极情感响应率、情感极性一致性、情绪强度匹配度、共情意图识别率、负面情绪协同化解率等5个子维度

**Independent Test**: 使用包含已知情感标签和交互模式的测试数据验证,系统应正确计算所有5个子维度指标并输出综合评分

### Tests for User Story 1

- [ ] T016 [P] [US1] Create backend/tests/test_sentiment_service.py with SnowNLP accuracy tests (polarity classification, intensity mapping)
- [ ] T017 [P] [US1] Create backend/tests/test_interaction_pairs.py with speech unit merging and pair construction tests
- [ ] T018 [US1] Create backend/tests/test_emotional_resonance.py with all 5 sub-dimensions calculation tests

### Implementation for User Story 1

**Core Services (juitar primary responsibility)**:

- [ ] T019 [US1] Implement SentimentService class in backend/app/services/analysis/sentiment_service.py with SnowNLP integration
  - Lazy load SnowNLP and sentence-transformers models
  - analyze_sentiment() method returning polarity (-1/0/1), intensity (-1 to 1), embedding (384-dim vector)
  - analyze_batch() method for batch processing (32 messages per batch)
  - Fallback to neutral (0, 0, zero vector) on analysis failure

- [ ] T020 [US1] Implement InteractionPairBuilder class in backend/app/services/analysis/interaction_pair_builder.py
  - build_speech_units() method to merge consecutive messages (< 5 min gap) from same sender
  - build_interaction_pairs() method to create alternating pairs from speech units
  - calculate_semantic_similarity() helper using cosine similarity on embeddings
  - Handle edge cases: single message sessions, empty conversations, odd-numbered speech units

- [ ] T021 [US1] Implement EmotionalResonanceService class in backend/app/services/analysis/emotional_resonance_service.py
  - calculate_bidirectional_positive_response() method (20% weight) - count positive-positive pairs / total positive messages
  - calculate_polarity_consistency() method (15% weight) - (same-polarity ratio) × (average semantic similarity)
  - calculate_intensity_matching() method (10% weight) - reciprocal of mean absolute intensity difference: 1/(mean_diff + 0.1)
  - calculate_empathy_recognition() method (30% weight) - messages with empathy keywords / total messages
  - calculate_negative_resolution() method (25% weight) - empathetic responses / negative-initiated pairs
  - calculate_overall_resonance() method - weighted sum of 5 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

- [ ] T022 [US1] Implement KeywordLibraries class in backend/app/services/analysis/keyword_libraries.py (ting can do this in parallel)
  - get_keywords(category) method - retrieve all keywords for a category
  - add_keywords(category, keywords) method - add custom keywords to library
  - remove_keywords(category, keywords) method - remove keywords from library
  - get_all_keywords() method - retrieve all 6 categories as dict
  - check_keywords_in_text(text, keywords) helper method

**Database Integration**:

- [ ] T023 [US1] Implement sentiment caching in backend/app/services/analysis/sentiment_service.py
  - cache_sentiment_result() method - write to sentiment_cache table
  - get_sentiment_from_cache() method - read from cache before analysis
  - batch_cache_sentiments() method - bulk insert for performance

- [ ] T024 [US1] Implement interaction pair persistence in backend/app/services/analysis/interaction_pair_builder.py
  - save_speech_units() method - write to speech_units table
  - save_interaction_pairs() method - write to interaction_pairs table with pre-computed semantic similarities
  - load_cached_pairs() method - read from cache before rebuilding

**Checkpoint**: 此时,User Story 1应完全功能化且可独立测试。情感共振率5个子维度全部实现并能正确计算

---

## Phase 4: User Story 2 - Chat Positivity Analysis (Priority: P1)

**Goal**: 实现聊天积极度维度分析,包括日均消息数、回复及时率、消息长度、话题延续性、主动发起率等5个子维度

**Independent Test**: 使用包含已知时间戳和消息长度的测试数据验证,系统应正确计算及时回复率、主动发起率、话题延续性得分等指标

### Tests for User Story 2

- [ ] T025 [P] [US2] Create backend/tests/test_chat_positivity.py with all 5 sub-dimensions tests
- [ ] T026 [US2] Add reply timeliness edge case tests (boundary values at threshold, negative gaps, >24 hour gaps)

### Implementation for User Story 2

**Core Services (ting primary responsibility, depends on US1 for interaction pairs)**:

- [ ] T027 [US2] Implement ChatPositivityService class in backend/app/services/analysis/chat_positivity_service.py
  - calculate_daily_message_count() method (10% weight) - total messages / conversation duration in days
  - calculate_reply_timeliness() method (20% weight) - pairs with response time ≤ threshold / total pairs
  - calculate_avg_message_length() method (10% weight) - average character count across all messages
  - calculate_long_text_ratio() method (15% weight) - messages with >100 characters / total messages
  - calculate_topic_continuity() method (20% weight) - average semantic similarity of sessions within time window
  - calculate_active_initiation() method (25% weight) - counterpart-initiated pairs / total initiated pairs
  - determine_initiation_type() helper method - two-step logic: time gap → semantic similarity threshold (0.4)
  - calculate_overall_positivity() method - weighted sum of 5 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Database Integration**:

- [ ] T028 [US2] Extend affinity_config table usage in backend/app/services/analysis/affinity_config.py
  - get_config() method - retrieve configuration for conversation (with defaults)
  - update_config() method - save user overrides (weights, thresholds)
  - validate_config() helper method - ensure weights sum to 1.0, thresholds in valid ranges

**Checkpoint**: 此时,User Stories 1 AND 2都应独立工作。聊天积极度5个子维度全部实现

---

## Phase 5: User Story 3 - Attitude Tendency Analysis (Priority: P2)

**Goal**: 实现态度倾向维度分析,包括正负面词汇频次、表情包/语音/视频使用、专属称呼、隐私分享、节假日祝福等5个子维度

**Independent Test**: 使用包含特定关键词和消息类型的测试数据验证,系统应正确统计各类指标并计算综合评分

### Tests for User Story 3

- [ ] T029 [P] [US3] Create backend/tests/test_attitude_tendency.py with all 5 sub-dimensions tests
- [ ] T030 [US3] Add keyword matching accuracy tests (test edge cases: partial matches, case sensitivity, punctuation)

### Implementation for User Story 3

**Core Services (ting primary responsibility)**:

- [ ] T031 [US3] Implement AttitudeTendencyService class in backend/app/services/analysis/attitude_tendency_service.py
  - calculate_positive_word_frequency() method (25% weight) - messages with positive words / total messages
  - calculate_negative_word_frequency() method (-20% weight, reverse scoring) - messages with negative words / total messages
  - calculate_multimedia_usage() method (10% weight) - (emoji×0.3 + voice×0.2 + video×0.5) / total messages
  - calculate_nickname_frequency() method (25% weight) - messages with exclusive nicknames / total messages
  - calculate_privacy_sharing() method (20% weight) - messages with privacy keywords / total messages
  - calculate_holiday_greeting() method (10% weight) - messages with holiday greetings / total messages
  - detect_message_type() helper method - identify emoji/voice/video messages from message_type field
  - calculate_overall_attitude() method - weighted sum of 5 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Integration with Keyword Libraries**:

- [ ] T032 [US3] Integrate KeywordLibraries in backend/app/services/analysis/attitude_tendency_service.py
  - Use keyword_libraries.get_all_keywords() to load all 6 categories
  - Use keyword_libraries.check_keywords_in_text() for pattern matching
  - Handle missing keyword categories gracefully (skip if empty, redistribute weights)

**Checkpoint**: 所有3个用户故事现在都应独立功能化。态度倾向5个子维度全部实现

---

## Phase 6: User Story 4 - Preference Compatibility Analysis (Priority: P2)

**Goal**: 实现喜好维度分析,包括话题提及频率和喜好话题延续性等2个子维度

**Independent Test**: 通过用户提供喜好关键词列表和包含这些关键词的测试数据验证,系统应正确统计提及频率和计算话题延续性得分

### Tests for User Story 4

- [ ] T033 [P] [US4] Create backend/tests/test_preference_compatibility.py with both sub-dimensions tests
- [ ] T034 [US4] Add empty preference keywords test (should return 0 score and handle gracefully)

### Implementation for User Story 4

**Core Services (ting primary responsibility)**:

- [ ] T035 [US4] Implement PreferenceCompatibilityService class in backend/app/services/analysis/preference_compatibility_service.py
  - calculate_topic_mention_frequency() method (40% weight) - sessions with preference keywords / total sessions
  - calculate_preference_topic_continuity() method (60% weight) - average internal continuity score for preference-mentioning sessions
  - identify_preference_sessions() helper method - find sessions containing any preference keywords
  - calculate_session_continuity() helper method - reuse semantic similarity logic from US1/US2
  - calculate_overall_compatibility() method - weighted sum of 2 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Configuration Integration**:

- [ ] T036 [US4] Add preference keywords to affinity_config in backend/app/services/analysis/affinity_config.py
  - Update get_config() to include preference_keywords_json field
  - Update update_config() to handle preference keywords array
  - Validate preference keywords are non-empty strings

**Checkpoint**: 所有4个用户故事现在都应独立功能化。喜好维度2个子维度全部实现

---

## Phase 7: Orchestrator & Scoring (Joint Responsibility)

**Purpose**: Integrate all 4 dimensions and calculate overall affinity score

### Implementation for Orchestrator

- [ ] T037 Implement AffinityAnalysisService orchestrator in backend/app/services/analysis/affinity_analysis_service.py (juitar lead)
  - analyze() method - main entry point, triggers full analysis pipeline
  - _preprocess_conversation() helper method - ensure sentiment cache and interaction pairs exist
  - _calculate_all_dimensions() helper method - call all 4 dimension services
  - _calculate_overall_score() helper method - weighted sum: emotional_resonance×0.3 + chat_positivity×0.3 + attitude_tendency×0.2 + preference_compatibility×0.2
  - _save_results() helper method - write to affinity_scores table
  - get_scores() method - retrieve cached scores from affinity_scores table
  - reanalyze() method - invalidate cache and re-run analysis
  - _generate_progress_updates() helper method - emit progress events for UI polling

- [ ] T038 Implement task tracking and progress reporting in backend/app/services/analysis/affinity_analysis_service.py
  - Generate unique task_id for each analysis run (format: "affinity_{conversation_id}_{timestamp}")
  - Store task progress in memory or backend/data/analysis_tasks.json
  - Update progress_percent (0-100) and current_step description
  - Handle task cancellation and error recovery

- [ ] T039 Add interpretation text generation in backend/app/services/analysis/affinity_analysis_service.py
  - generate_overall_interpretation() method - overall score interpretation (e.g., "总体好感度较高,对方对这段关系较为重视" for scores >70)
  - aggregate_dimension_interpretations() method - combine interpretations from all 4 dimension services
  - format_score_breakdown() method - structure sub-scores JSON for frontend display

**Checkpoint**: 主分析服务完成,能够协调4个维度并生成总分

---

## Phase 8: Backend API Integration

**Purpose**: Expose affinity analysis functionality via Bridge API

### Bridge API Endpoints

- [ ] T040 [P] Add POST /affinity/analyze endpoint in backend/app/webview/bridge.py
  - Accept conversation_id, force_reanalyze, config_overrides parameters
  - Call affinity_service.analyze() and return task_id
  - Return estimated_duration_ms based on message count

- [ ] T041 [P] Add GET /affinity/progress/{task_id} endpoint in backend/app/webview/bridge.py
  - Query task status from affinity_service
  - Return status (pending/running/completed/failed), progress_percent, current_step, error (if failed), result (if completed)

- [ ] T042 [P] Add GET /affinity/scores/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Call affinity_service.get_scores()
  - Return 404 if no analysis exists (suggest analyzing first)

- [ ] T043 [P] Add GET /affinity/config/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Call affinity_config.get_config()
  - Return default config if no per-conversation override exists

- [ ] T044 [P] Add PUT /affinity/config/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Validate config (weights sum to 1.0, thresholds in valid ranges)
  - Call affinity_config.update_config()
  - Return 400 if validation fails

- [ ] T045 [P] Add GET /affinity/keywords endpoint in backend/app/webview/bridge.py
  - Call keyword_service.get_all_keywords()
  - Return all 6 categories as dict

- [ ] T046 [P] Add POST /affinity/keywords endpoint in backend/app/webview/bridge.py
  - Accept category and keywords array
  - Call keyword_service.add_keywords()
  - Return added_count and updated keyword list

- [ ] T047 [P] Add DELETE /affinity/keywords endpoint in backend/app/webview/bridge.py
  - Accept category and keywords array
  - Call keyword_service.remove_keywords()
  - Return removed_count

- [ ] T048 [P] Add GET /affinity/preference-keywords/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Retrieve preference_keywords_json from affinity_config
  - Return empty array if not configured

- [ ] T049 [P] Add PUT /affinity/preference-keywords/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Accept keywords array
  - Update affinity_config.preference_keywords_json

**Checkpoint**: 所有8个API端点实现并可用,前端可以调用分析功能

---

## Phase 9: Frontend Implementation

**Purpose**: Create Vue 3 UI for affinity analysis visualization and configuration

### API Client

- [ ] T050 [P] Create frontend/src/api/affinity.ts API client
  - analyzeAffinity(conversationId, forceReanalyze, configOverrides) function
  - getAffinityProgress(taskId) polling function
  - getAffinityScores(conversationId) function
  - getAffinityConfig(conversationId) function
  - updateAffinityConfig(conversationId, config) function
  - getKeywords() function
  - addKeywords(category, keywords) function
  - removeKeywords(category, keywords) function
  - getPreferenceKeywords(conversationId) function
  - updatePreferenceKeywords(conversationId, keywords) function

### Main View

- [ ] T051 Create frontend/src/views/AffinityView.vue main page
  - Conversation selector dropdown
  - "开始分析" button (triggers analyzeAffinity)
  - Progress bar with percentage display
  - Overall score display (large number 0-100)
  - 4 dimension scores cards (clickable for details)
  - Interpretation text display
  - "重新分析" button (triggers reanalyze)

### Components

- [ ] T052 [P] Create frontend/src/components/affinity/AffinityScoreCard.vue component
  - Props: title, score, maxScore, interpretation
  - Visual score display (circular progress or bar chart)
  - Color coding: red (0-40), yellow (40-70), green (70-100)

- [ ] T053 [P] Create frontend/src/components/affinity/DimensionRadar.vue component
  - ECharts radar chart displaying 4 dimensions
  - Props: dimensionScores object (emotional_resonance, chat_positivity, attitude_tendency, preference_compatibility)
  - Responsive sizing and tooltip on hover

- [ ] T054 [P] Create frontend/src/components/affinity/SubScoreBreakdown.vue component
  - Props: subScores object, dimensionName
  - Table display of sub-dimensions with weights and scores
  - Expandable rows for detailed explanations

- [ ] T055 [P] Create frontend/src/components/affinity/ConfigPanel.vue component
  - Dimension weight sliders (4 sliders, must sum to 100%)
  - Threshold inputs (reply timeliness, topic continuity window, similarity threshold, sliding window size)
  - "保存配置" button (calls updateAffinityConfig)
  - Validation error messages (if weights don't sum to 100%)

- [ ] T056 [P] Create frontend/src/components/affinity/KeywordEditor.vue component
  - 6 tabs for each keyword category
  - Keyword list display (with delete buttons)
  - "添加关键词" input + button per category
  - Save/cancel buttons
  - Calls addKeywords/removeKeywords APIs

### Integration

- [ ] T057 Add AffinityView to router in frontend/src/router/index.ts
  - Route path: /affinity/:id (where :id is conversation_id)
  - Route name: affinity

- [ ] T058 Add "好感度分析" tab/link in frontend/src/views/ConversationView.vue
  - Navigate to AffinityView when clicked
  - Pass conversation_id as route parameter

**Checkpoint**: 前端UI完成,用户可以查看分析结果和调整配置

---

## Phase 10: Testing & Validation

**Purpose**: Comprehensive testing of all functionality

### Unit Tests

- [ ] T059 [P] Complete backend/tests/test_sentiment_service.py with SnowNLP accuracy validation (>85% on labeled data)
- [ ] T060 [P] Complete backend/tests/test_interaction_pairs.py with construction algorithm validation
- [ ] T061 [P] Complete backend/tests/test_emotional_resonance.py with all 5 sub-dimensions calculation tests
- [ ] T062 [P] Complete backend/tests/test_chat_positivity.py with all 5 sub-dimensions tests
- [ ] T063 [P] Complete backend/tests/test_attitude_tendency.py with all 5 sub-dimensions tests
- [ ] T064 [P] Complete backend/tests/test_preference_compatibility.py with both sub-dimensions tests
- [ ] T065 [P] Create backend/tests/test_affinity_config.py with config validation and persistence tests
- [ ] T066 [P] Create backend/tests/test_keyword_libraries.py with CRUD operation tests

### Integration Tests

- [ ] T067 Create backend/tests/test_affinity_analysis_integration.py with full pipeline test
  - Test 1: Small conversation (1,000 messages) - should complete in < 30 seconds
  - Test 2: Medium conversation (10,000 messages) - should complete in < 2 minutes
  - Test 3: Verify cache invalidation on config change
  - Test 4: Verify re-analysis correctness
  - Test 5: Verify all 4 dimensions calculate correctly
  - Test 6: Verify overall score formula (weighted sum)

### Performance Tests

- [ ] T068 Run performance benchmark with backend/tests/fixtures/conversation_medium.json (10,000 messages)
  - Target: < 2 minutes analysis time
  - Measure: sentiment analysis time, embedding generation time, interaction pair construction time, dimension calculation time
  - Log bottleneck identification

- [ ] T069 Run performance stress test with backend/tests/fixtures/conversation_large.json (100,000 messages if available)
  - Target: < 5 minutes analysis time
  - Monitor: memory usage (<2GB), CPU usage, database size
  - Identify optimization opportunities

### Edge Case Tests

- [ ] T070 Create backend/tests/test_edge_cases.py covering all edge cases from spec.md
  - Empty conversation (0 messages) - should return 0 scores
  - Single message conversation - should handle gracefully
  - No interaction pairs scenario - should set pair-based metrics to 0
  - Sentiment analysis failure - should fallback to neutral
  - Embedding generation failure - should use zero vector
  - Missing keyword categories - should skip dimension and redistribute weights
  - Division by zero scenarios - should return 0 without crashing
  - Extreme config values (1 second threshold, 30 day threshold) - should validate and suggest defaults

**Checkpoint**: 所有测试通过,系统稳定可靠

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Final improvements, optimization, and documentation

### Performance Optimization

- [ ] T071 [P] Implement batch processing optimization in backend/app/services/analysis/sentiment_service.py
  - Increase batch size from 32 to 64 for embeddings
  - Implement parallel processing for large conversations (>10K messages)

- [ ] T072 [P] Add LRU cache for sentence embeddings in backend/app/services/analysis/sentiment_service.py
  - Cache size: 10,000 most recent embeddings
  - Cache hit rate logging
  - Memory usage monitoring

- [ ] T073 Implement database query optimization in backend/app/db/connection.py
  - Add indexes on frequently queried columns (if not already present)
  - Use batch inserts for sentiment_cache and interaction_pairs
  - Implement query result caching

### Error Handling & Logging

- [ ] T074 [P] Add comprehensive error handling in backend/app/services/analysis/affinity_analysis_service.py
  - Try-except blocks around all external library calls (SnowNLP, sentence-transformers)
  - 阿澄ful degradation on failures (fallback to neutral/zero values)
  - Detailed error messages for UI display

- [ ] T075 [P] Add structured logging in all service files
  - DEBUG: Algorithm steps, intermediate values
  - INFO: Analysis start/end, cache hits/misses
  - WARNING: Fallbacks activated, missing data
  - ERROR: Critical failures requiring user attention
  - Use Python logging module with proper formatters

### Documentation

- [ ] T076 [P] Update backend/README.md with affinity analysis section
  - Overview of 4-dimensional scoring system
  - Configuration options explanation
  - Performance benchmarks
  - Troubleshooting guide

- [ ] T077 [P] Create frontend/src/views/AffinityView.md component documentation
  - Props reference
  - Event descriptions
  - Usage examples
  - Screenshot placeholders

- [ ] T078 [P] Update CLAUDE.md with 002-affinity-analysis implementation notes
  - Add to "Recent Changes" section
  - Document new services and their purposes

### Code Quality

- [ ] T079 Run linter on all new Python files: `ruff check backend/app/services/analysis/`
- [ ] T080 Run linter on all new Vue files: `eslint --ext .vue frontend/src/components/affinity/ frontend/src/views/`
- [ ] T081 Format all code according to project style guidelines

### Validation

- [ ] T082 Run all backend tests: `cd backend && pytest tests/ -v`
- [ ] T083 Verify all tests pass (target: >90% pass rate)
- [ ] T084 Run quickstart.md validation - follow quickstart guide step-by-step and verify all steps work

**Checkpoint**: 项目完成,准备部署

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 (Emotional Resonance): No dependencies on other user stories - can start after Foundational
  - US2 (Chat Positivity): Depends on US1 for interaction pair builder and sentiment service
  - US3 (Attitude Tendency): Depends on US1 for sentiment service (optional, for embeddings if needed)
  - US4 (Preference Compatibility): Depends on US1/US2 for semantic similarity calculation (can be parallelized)
- **Orchestrator (Phase 7)**: Depends on all 4 user stories being complete
- **Backend API (Phase 8)**: Depends on Orchestrator being complete
- **Frontend (Phase 9)**: Depends on Backend API being complete
- **Testing (Phase 10)**: Depends on all implementation being complete
- **Polish (Phase 11)**: Depends on all tests passing

### User Story Dependencies

- **User Story 1 (P1 - Emotional Resonance)**: Foundational完成后可开始 - 无其他故事依赖
- **User Story 2 (P1 - Chat Positivity)**: 依赖User Story 1(interaction pairs + sentiment service), 但可独立测试
- **User Story 3 (P2 - Attitude Tendency)**: 可在Foundational完成后开始(主要使用关键词,不依赖其他故事)
- **User Story 4 (P2 - Preference Compatibility)**: 依赖User Story 1或User Story 2的语义相似度函数

### Within Each User Story

- Tests must be written first (TDD approach)
- Core services before database integration
- Database integration before API endpoints
- All tasks complete before moving to next story

### Parallel Opportunities

**Setup Phase (Phase 1)**:
- T002 and T003 can run in parallel (install dependencies + download model)

**Foundational Phase (Phase 2)**:
- T004-T009 (all migration scripts) can run in parallel
- T013-T015 (test data creation) can run in parallel

**User Story 1 (Phase 3)**:
- T016 and T017 (tests) can run in parallel
- T019 and T020 (sentiment service and interaction pair builder) can run partially in parallel (different files, but both need models loaded)

**User Story 2 (Phase 4)**:
- T025 and T026 (tests) can run in parallel

**User Story 3 (Phase 5)**:
- T029 and T030 (tests) can run in parallel

**User Story 4 (Phase 6)**:
- T033 and T034 (tests) can run in parallel

**Backend API (Phase 8)**:
- T040-T049 (all endpoints) can run in parallel (different routes in bridge.py)

**Frontend (Phase 9)**:
- T050-T056 (API client and components) can run in parallel

**Testing (Phase 10)**:
- T059-T066 (unit tests) can run in parallel
- T067-T069 (integration/performance tests) must run sequentially

**Polish (Phase 11)**:
- T071-T073 (optimization) can run in parallel
- T074-T075 (error handling) can run in parallel
- T076-T078 (documentation) can run in parallel

---

## Parallel Example: User Story 1

```bash
# juitar can work on these tasks in parallel:
Task T019: Implement SentimentService
Task T020: Implement InteractionPairBuilder

# Once both are complete, juitar moves to:
Task T021: Implement EmotionalResonanceService (depends on T019, T020)

# Meanwhile, ting can work on:
Task T022: Implement KeywordLibraries (no dependencies on T019-T020)
```

---

## Parallel Example: Backend API (Phase 8)

```bash
# juitar or ting can implement all 8 endpoints in parallel:
Task T040: POST /affinity/analyze
Task T041: GET /affinity/progress
Task T042: GET /affinity/scores
Task T043: GET /affinity/config
Task T044: PUT /affinity/config
Task T045: GET /affinity/keywords
Task T046: POST /affinity/keywords
Task T047: DELETE /affinity/keywords
Task T048: GET /affinity/preference-keywords
Task T049: PUT /affinity/preference-keywords

# All are independent routes in bridge.py
```

---

## Implementation Strategy

### MVP First (User Stories 1+2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (Emotional Resonance)
4. Complete Phase 4: User Story 2 (Chat Positivity)
5. **STOP and VALIDATE**: 独立测试 User Stories 1+2
6. 如果准备就绪,部署/演示MVP

**MVP 价值**: 实现核心的情感共振率和聊天积极度分析,满足最重要的关系评估需求(60%权重)

### Incremental Delivery

1. Complete Setup + Foundational → 基础设施就绪
2. Add User Story 1 → 独立测试 → 部署/演示
3. Add User Story 2 → 独立测试 → 部署/演示 (MVP!)
4. Add User Story 3 → 独立测试 → 部署/演示
5. Add User Story 4 → 独立测试 → 部署/演示
6. Complete Orchestrator + API → 集成测试 → 部署/演示
7. Add Frontend → E2E测试 → 最终部署
8. Complete Polish → 生产就绪版本
9. 每个故事都增加价值而不破坏已有功能

### Recommended Execution Order

**单开发者顺序执行**(推荐,如果juitar和ting协作):

```
Phase 1 (Setup) → Phase 2 (Foundational) →
Phase 3 (US1 - Emotional Resonance) → Phase 4 (US2 - Chat Positivity) →
Phase 5 (US3 - Attitude Tendency) → Phase 6 (US4 - Preference Compatibility) →
Phase 7 (Orchestrator) → Phase 8 (Backend API) → Phase 9 (Frontend) →
Phase 10 (Testing) → Phase 11 (Polish)
```

**双开发者并行执行**(推荐,juitar + ting协作):

```
Phase 1 + 2 (团队一起完成基础)
  ↓
Developer A (juitar): Phase 3 (US1) → Phase 7 (Orchestrator)
Developer B (ting): Phase 5 (US3) + Phase 6 (US4)
  ↓
Developer A (juitar): Phase 8 (Backend API)
Developer B (ting): Phase 4 (US2) + Phase 9 (Frontend)
  ↓
Phase 10 + 11 (团队一起测试和优化)
```

**更细致的分工**(juitar专注于算法,ting专注于UI和评分):

```
Week 1:
  juitar: Phase 1-3 (Setup + Foundational + US1 Emotional Resonance)
  ting: Phase 5-6 (US3 Attitude + US4 Preference) + Phase 9 (Frontend基础)

Week 2:
  juitar: Phase 7 (Orchestrator)
  ting: Phase 4 (US2 Chat Positivity) + Phase 9 (Frontend完善)

Week 3:
  juitar: Phase 8 (Backend API)
  ting: Phase 9 (Frontend集成)

Week 4:
  团队一起: Phase 10-11 (Testing + Polish)
```

---

## Notes

- [P] 任务 = 不同文件,无依赖,可并行
- [Story] 标签将任务映射到特定用户故事以便追溯
- 每个用户故事应可独立完成和测试
- 在每个检查点停下独立验证故事功能
- 每个任务或逻辑组后提交代码
- 避免模糊任务、同文件冲突、破坏独立性的跨故事依赖

---

## Task Summary

- **Total Tasks**: 84
- **Phase 1 (Setup)**: 3 tasks
- **Phase 2 (Foundational)**: 15 tasks (BLOCKING)
- **Phase 3 (US1 - Emotional Resonance)**: 9 tasks
- **Phase 4 (US2 - Chat Positivity)**: 4 tasks
- **Phase 5 (US3 - Attitude Tendency)**: 6 tasks
- **Phase 6 (US4 - Preference Compatibility)**: 6 tasks
- **Phase 7 (Orchestrator)**: 3 tasks
- **Phase 8 (Backend API)**: 10 tasks
- **Phase 9 (Frontend)**: 8 tasks
- **Phase 10 (Testing)**: 16 tasks
- **Phase 11 (Polish)**: 14 tasks

**Parallel Opportunities Identified**: 50+ 任务可并行执行

**Independent Test Criteria**:
- US1: 验证情感共振率5个子维度计算正确性(双向积极响应、极性一致性、强度匹配、共情识别、负面化解)
- US2: 验证聊天积极度5个子维度计算正确性(日均消息、及时回复、消息长度、话题延续、主动发起)
- US3: 验证态度倾向5个子维度计算正确性(正负面词、多媒体、专属称呼、隐私分享、节假日祝福)
- US4: 验证喜好维度2个子维度计算正确性(话题提及频率、喜好话题延续性)

**Suggested MVP Scope**: User Stories 1+2 (Phase 3+4) - 提供核心情感共振率和聊天积极度分析功能

**Format Validation**: ✅ 所有任务遵循checklist格式(checkbox, ID, 可选P标记, Story标签, 文件路径)

---

**Ready for Implementation**: ✅ YES

所有任务已明确定义,依赖关系清晰,并行机会已标识,可以立即开始实施。

**Estimated Timeline**: 4-5 weeks (see COLLABORATION_GUIDE.md for detailed 5-week schedule)
