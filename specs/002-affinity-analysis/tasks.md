# Tasks: Conversation Affinity Analysis System

**Input**: Design documents from `/specs/002-affinity-analysis/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 单元测试和集成测试任务已包含在每个阶段中

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] [Developer] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- **[Developer]**: Primary developer responsible (juitar/ting/joint)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `backend/app/` (Python服务)
- **Frontend**: `frontend/src/` (Vue 3 UI)
- **Database**: `backend/app/db/` (SQLite schema)
- **Tests**: `backend/tests/` (pytest测试)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency setup

- [ ] T001 [P] [Setup] [joint] Add new dependencies to backend/requirements.txt (snownlp>=0.12.3, sentence-transformers>=2.2.0, scikit-learn>=1.3.0, torch>=2.0.0)
- [ ] T002 [P] [Setup] [joint] Install Python dependencies via pip install -r backend/requirements.txt
- [ ] T003 [P] [Setup] [joint] Download sentence-transformers model (paraphrase-multilingual-MiniLM-L12-v2) to cache for faster startup

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Database Schema (Migrates 6 New Tables)

- [ ] T004 [P] [Setup] [juitar] Create migration script backend/app/db/migrations/sentiment_cache.sql for sentiment caching table
- [ ] T005 [P] [Setup] [juitar] Create migration script backend/app/db/migrations/speech_units.sql for speech units table
- [ ] T006 [P] [Setup] [juitar] Create migration script backend/app/db/migrations/interaction_pairs.sql for interaction pairs table
- [ ] T007 [P] [Setup] [juitar] Create migration script backend/app/db/migrations/affinity_config.sql for configuration table
- [ ] T008 [P] [Setup] [ting] Create migration script backend/app/db/migrations/keyword_libraries.sql for keyword libraries table
- [ ] T009 [P] [Setup] [ting] Create migration script backend/app/db/migrations/affinity_scores.sql for scores table
- [ ] T010 [Setup] [joint] Run all migration scripts to create 6 new tables in backend/data/chrono_trace.db

### Keyword Library Seeding

- [ ] T011 [Setup] [ting] Create backend/scripts/populate_default_keywords.py to seed 6 default keyword categories
- [ ] T012 [Setup] [joint] Run populate_default_keywords.py to insert default keywords (10 per category: positive, negative, empathy, soothing, privacy, holiday)

### Test Data Preparation

- [ ] T013 [P] [Setup] [juitar] Create backend/tests/fixtures/conversation_small.json with 1,000 test messages
- [ ] T014 [P] [Setup] [ting] Create backend/tests/fixtures/conversation_medium.json with 10,000 test messages
- [ ] T015 [P] [Setup] [ting] Create backend/tests/fixtures/conversation_labeled.json with manually labeled sentiment data

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 2.5: Preprocessing Layer (⚠️ CRITICAL PATH - BLOCKS ALL DIMENSIONS)

**Purpose**: Extract preprocessing as independent layer - O(N) single-pass collection of all 29 statistics

**⚠️ CRITICAL**: This phase MUST be complete before ANY dimension work (Phase 3-6) can begin

**Performance Target**: Reduce complexity from O(6N) → O(N) for attitude tendency (6x speedup)

### Week 1: Preprocessing Implementation (juitar || ting fully parallel)

#### Preprocessing Core Services (juitar - 19 tasks)

- [ ] T016 [P] [Preprocessing] [juitar] Create backend/tests/test_sentiment_service.py with SnowNLP accuracy tests (polarity classification, intensity mapping)
- [ ] T017 [P] [Preprocessing] [juitar] Create backend/tests/test_interaction_pairs.py with speech unit merging and pair construction tests
- [ ] T018 [Preprocessing] [juitar] Implement SentimentService class in backend/app/services/analysis/sentiment_service.py with SnowNLP integration
  - Lazy load SnowNLP and sentence-transformers models
  - analyze_sentiment() method returning polarity (-1/0/1), intensity (-1 to 1), embedding (384-dim vector)
  - analyze_batch() method for batch processing (32 messages per batch)
  - Fallback to neutral (0, 0, zero vector) on analysis failure

- [ ] T019 [Preprocessing] [juitar] Implement sentiment caching in backend/app/services/analysis/sentiment_service.py
  - cache_sentiment_result() method - write to sentiment_cache table
  - get_sentiment_from_cache() method - read from cache before analysis
  - batch_cache_sentiments() method - bulk insert for performance

- [ ] T020-A [Preprocessing] [juitar] Implement BasicPreprocessingService in backend/app/services/analysis/preprocessing_service.py (Part 1: Basic Statistics)
  - collect_message_statistics() method - collect 4 basic constants: total_message_count, total_positive_count, total_negative_count, total_neutral_count
  - collect_time_statistics() method - collect 4 time constants: conversation_start_timestamp, conversation_end_timestamp, conversation_duration_days, chat_days_count
  - collect_length_statistics() method - collect 2 length constants: total_characters, average_message_length
  - All statistics in O(N) single pass through messages

- [ ] T020-B [Preprocessing] [juitar] Implement PairPreprocessingService in backend/app/services/analysis/preprocessing_service.py (Part 2: Interaction Pairs)
  - build_speech_units() method - merge consecutive messages (< 5 min gap) from same sender
  - build_interaction_pairs() method - create alternating pairs from speech units (bidirectional)
  - collect_pair_statistics() method - collect 3 pair constants: total_interaction_pairs, bidirectional_pairs, same_parity_pairs
  - save_speech_units() method - write to speech_units table
  - save_interaction_pairs() method - write to interaction_pairs table with pre-computed semantic similarities
  - load_cached_pairs() method - read from cache before rebuilding

- [ ] T020-C [Preprocessing] [juitar] Implement SessionManager in backend/app/services/analysis/session_manager.py (Part 3: Sessions)
  - split_sessions() method - split conversations by semantic similarity valleys (sliding window + valley detection algorithm)
  - calculate_semantic_similarity() helper - using cosine similarity on embeddings
  - collect_session_statistics() method - collect 3 session constants: total_sessions, average_session_length, average_session_gap
  - identify_session_initiators() method - mark which person initiated each session (for active initiation calculation)
  - save_sessions() method - write to session_data table for caching
  - load_cached_sessions() method - read from cache before rebuilding

#### Preprocessing Attitude & Integration (ting - 4 tasks)

- [x] T021 [P] [Preprocessing] [ting] Implement KeywordLibraries class in backend/app/services/analysis/keyword_libraries.py ✅
  - get_keywords(category) method - retrieve all keywords for a category
  - add_keywords(category, keywords) method - add custom keywords to library
  - remove_keywords(category, keywords) method - remove keywords from library
  - get_all_keywords() method - retrieve all 6 categories as dict
  - check_keywords_in_text(text, keywords) helper method
  - Memory cache mechanism for performance
  - Database CRUD integration using existing get_db() connection
  - Completed: 2026-01-11

- [ ] T022 [P] [Preprocessing] [ting] Create backend/tests/test_keyword_libraries.py with CRUD operation tests
- [ ] T023 [Preprocessing] [ting] Implement AttitudePreprocessingService in backend/app/services/analysis/preprocessing_service.py (Part 4: Attitude Statistics)
  - collect_attitude_statistics() method - single-pass collection of 6 attitude message counts (O(N) vs O(6N))
  - emoji_message_count - messages containing emoji stickers
  - voice_message_count - voice messages
  - video_message_count - video call messages
  - nickname_message_count - messages with exclusive nicknames
  - privacy_message_count - messages with privacy sharing keywords
  - holiday_message_count - messages with holiday greetings
  - holidays_sent_count - unique holiday dates sent (for accurate coverage calculation)
  - Use keyword_libraries.get_all_keywords() to load all 6 categories
  - Use keyword_libraries.check_keywords_in_text() for pattern matching

- [ ] T024 [Preprocessing] [ting] Create backend/tests/test_attitude_preprocessing.py with single-pass attitude statistics validation

#### Preprocessing Orchestrator & Tests (joint - 1 task)

- [ ] T025 [Preprocessing] [joint] Implement PreprocessingOrchestrator in backend/app/services/analysis/preprocessing_orchestrator.py
  - orchestrate_preprocessing() method - main entry point, coordinates all preprocessing services
  - _validate_cached_data() helper method - check if cached preprocessing data exists and is valid
  - _collect_all_statistics() helper method - call all 4 preprocessing services (basic, pairs, sessions, attitude)
  - _save_preprocessing_results() helper method - write to preprocessed_statistics table
  - _load_cached_statistics() helper method - read from cache before preprocessing
  - invalidate_cache() method - clear preprocessing cache when conversation data changes
  - get_preprocessed_statistics() method - return all 29 constants as PreprocessedStatistics dataclass
  - generate_progress_updates() helper method - emit progress events for UI polling

- [ ] T026 [Preprocessing] [joint] Create backend/tests/test_preprocessing_orchestrator.py with end-to-end preprocessing pipeline tests
  - Test 1: Small conversation (1,000 messages) - all 29 statistics collected correctly
  - Test 2: Cache hit/miss behavior - cached data returned when available
  - Test 3: Cache invalidation - statistics regenerated after conversation data changes
  - Test 4: Performance - single-pass O(N) complexity verified (no multiple iterations)

**Checkpoint**: ⚠️ CRITICAL GATE - Preprocessing complete, ALL 29 statistics available in O(N) time, dimensions can now begin

**Summary of 29 Preprocessed Statistics**:

1. **Message Statistics (4)**: total_message_count, total_positive_count, total_negative_count, total_neutral_count
2. **Time Statistics (4)**: conversation_start_timestamp, conversation_end_timestamp, conversation_duration_days, chat_days_count
3. **Length Statistics (2)**: total_characters, average_message_length
4. **Pair Statistics (3)**: total_interaction_pairs, bidirectional_pairs, same_parity_pairs
5. **Session Statistics (3)**: total_sessions, average_session_length, average_session_gap, session_initiators (array)
6. **Attitude Statistics (6)**: emoji_message_count, voice_message_count, video_message_count, nickname_message_count, privacy_message_count, holiday_message_count, holidays_sent_count
7. **Derived Statistics (7)**: Calculated by orchestrator using above 22 raw statistics

**Week 1 Timeline**:
- Day 1-2: juitar implements SentimentService + BasicPreprocessingService (T016-T020-A)
- Day 1-2: ting implements KeywordLibraries + tests (T021-T022)
- Day 3-4: juitar implements PairPreprocessingService + SessionManager (T020-B, T020-C)
- Day 3-4: ting implements AttitudePreprocessingService + tests (T023-T024)
- Day 5: joint implements PreprocessingOrchestrator + integration tests (T025-T026)

---

## Phase 3: User Story 1 - Emotional Resonance Analysis (Priority: P1) 🎯 MVP

**Goal**: 实现情感共振率维度分析,包括双向积极情感响应率、情感极性一致性、情绪强度匹配度、共情意图识别率、负面情绪协同化解率等5个子维度

**Independent Test**: 使用包含已知情感标签和交互模式的测试数据验证,系统应正确计算所有5个子维度指标并输出综合评分

**Preprocessing Dependency**: ✅ All sentiment data, interaction pairs, and pair statistics available from Phase 2.5

### Tests for User Story 1

- [ ] T027 [P] [US1] [ting] Create backend/tests/test_emotional_resonance.py with all 5 sub-dimensions calculation tests

### Implementation for User Story 1

**Core Services (ting - can now work fully parallel with juitar on other dimensions)**:

- [ ] T028 [US1] [ting] Implement EmotionalResonanceService class in backend/app/services/analysis/emotional_resonance_service.py
  - **CRITICAL**: Use preprocessed_statistics from Phase 2.5 (T025) instead of recalculating
  - calculate_bidirectional_positive_response() method (20% weight) - use total_positive_count, total_interaction_pairs from preprocessing
  - calculate_polarity_consistency() method (15% weight) - use sentiment_cache embeddings from preprocessing
  - calculate_intensity_matching() method (10% weight) - use sentiment_cache intensities from preprocessing
  - calculate_empathy_recognition() method (30% weight) - use keyword_libraries.get_keywords('empathy') from preprocessing
  - calculate_negative_resolution() method (25% weight) - use interaction_pairs from preprocessing
  - calculate_overall_resonance() method - weighted sum of 5 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Checkpoint**: User Story 1完全功能化且可独立测试。情感共振率5个子维度全部实现并能正确计算

---

## Phase 4: User Story 2 - Chat Positivity Analysis (Priority: P1)

**Goal**: 实现聊天积极度维度分析,包括日均消息数、回复及时率、消息长度、话题延续性、主动发起率等5个子维度

**Independent Test**: 使用包含已知时间戳和消息长度的测试数据验证,系统应正确计算及时回复率、主动发起率、话题延续性得分等指标

**Preprocessing Dependency**: ✅ All time statistics, length statistics, session initiators, and sessions available from Phase 2.5

### Tests for User Story 2

- [ ] T029 [P] [US2] [ting] Create backend/tests/test_chat_positivity.py with all 5 sub-dimensions tests
- [ ] T030 [US2] [ting] Add reply timeliness edge case tests (boundary values at threshold, negative gaps, >24 hour gaps)

### Implementation for User Story 2

**Core Services (juitar - fully parallel with ting on US1)**:

- [ ] T031 [US2] [juitar] Implement ChatPositivityService class in backend/app/services/analysis/chat_positivity_service.py
  - **CRITICAL**: Use preprocessed_statistics from Phase 2.5 (T025) instead of recalculating
  - calculate_daily_message_count() method (10% weight) - use total_message_count, conversation_duration_days from preprocessing
  - calculate_reply_timeliness() method (20% weight) - use interaction_pairs from preprocessing
  - calculate_avg_message_length() method (10% weight) - use average_message_length from preprocessing
  - calculate_long_text_ratio() method (15% weight) - use total_message_count, long_text_messages from preprocessing
  - calculate_topic_continuity() method (20% weight) - use sessions from preprocessing (session_manager.split_sessions)
  - calculate_active_initiation() method (25% weight) - **SIMPLIFIED**: use session_initiators array from preprocessing
  - calculate_overall_positivity() method - weighted sum of 5 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Database Integration**:

- [ ] T032 [US2] [juitar] Extend affinity_config table usage in backend/app/services/analysis/affinity_config.py
  - get_config() method - retrieve configuration for conversation (with defaults)
  - update_config() method - save user overrides (weights, thresholds)
  - validate_config() helper method - ensure weights sum to 1.0, thresholds in valid ranges

**Checkpoint**: User Stories 1 AND 2都应独立工作。聊天积极度5个子维度全部实现

---

## Phase 5: User Story 3 - Attitude Tendency Analysis (Priority: P2)

**Goal**: 实现态度倾向维度分析,包括正负面词汇频次、表情包/语音/视频使用、专属称呼、隐私分享、节假日祝福等5个子维度

**Independent Test**: 使用包含特定关键词和消息类型的测试数据验证,系统应正确统计各类指标并计算综合评分

**Preprocessing Dependency**: ✅ All 6 attitude statistics (emoji, voice, video, nickname, privacy, holiday) already collected in O(N) by Phase 2.5

### Tests for User Story 3

- [ ] T033 [P] [US3] [ting] Create backend/tests/test_attitude_tendency.py with all 5 sub-dimensions tests
- [ ] T034 [US3] [ting] Add keyword matching accuracy tests (test edge cases: partial matches, case sensitivity, punctuation)

### Implementation for User Story 3

**Core Services (ting - fully parallel with juitar on US2)**:

- [ ] T035 [US3] [ting] Implement AttitudeTendencyService class in backend/app/services/analysis/attitude_tendency_service.py
  - **CRITICAL**: Use preprocessed_statistics from Phase 2.5 (T025) instead of recalculating (O(N) → O(1) lookup)
  - calculate_positive_word_frequency() method (25% weight) - use total_positive_count, total_message_count from preprocessing
  - calculate_negative_word_frequency() method (-20% weight, reverse scoring) - use total_negative_count, total_message_count from preprocessing
  - calculate_multimedia_usage() method (10% weight) - **OPTIMIZED**: use emoji_message_count, voice_message_count, video_message_count from preprocessing (O(1) vs O(N))
  - calculate_nickname_frequency() method (25% weight) - use nickname_message_count from preprocessing
  - calculate_privacy_sharing() method (20% weight) - use privacy_message_count from preprocessing
  - calculate_holiday_greeting() method (10% weight) - **SIMPLIFIED**: use holidays_sent_count, total_holiday_count from preprocessing
  - calculate_overall_attitude() method - weighted sum of 5 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Integration with Keyword Libraries**:

- [ ] T036 [US3] [ting] Integrate KeywordLibraries in backend/app/services/analysis/attitude_tendency_service.py
  - **Note**: KeywordLibraries already implemented in preprocessing (T021), just import and use
  - Handle missing keyword categories gracefully (skip if empty, redistribute weights)

**Checkpoint**: 所有3个用户故事现在都应独立功能化。态度倾向5个子维度全部实现

---

## Phase 6: User Story 4 - Preference Compatibility Analysis (Priority: P2)

**Goal**: 实现喜好维度分析,包括话题提及频率和喜好话题延续性等2个子维度

**Independent Test**: 通过用户提供喜好关键词列表和包含这些关键词的测试数据验证,系统应正确统计提及频率和计算话题延续性得分

**Preprocessing Dependency**: ✅ All sessions with semantic similarity scores available from Phase 2.5

### Tests for User Story 4

- [ ] T037 [P] [US4] [juitar] Create backend/tests/test_preference_compatibility.py with both sub-dimensions tests
- [ ] T038 [US4] [juitar] Add empty preference keywords test (should return 0 score and handle gracefully)

### Implementation for User Story 4

**Core Services (juitar - fully parallel with ting on US3)**:

- [ ] T039 [US4] [juitar] Implement PreferenceCompatibilityService class in backend/app/services/analysis/preference_compatibility_service.py
  - **CRITICAL**: Use preprocessed_statistics.sessions from Phase 2.5 (T025) instead of recalculating
  - calculate_topic_mention_frequency() method (40% weight) - use total_sessions from preprocessing
  - calculate_preference_topic_continuity() method (60% weight) - **OPTIMIZED**: reuse session semantic similarities from preprocessing
  - identify_preference_sessions() helper method - find sessions containing any preference keywords
  - calculate_session_continuity() helper method - **OPTIMIZED**: reuse semantic similarity logic from preprocessing (session_manager.split_sessions)
  - calculate_overall_compatibility() method - weighted sum of 2 sub-dimensions (0-100 score)
  - generate_interpretation() method - human-readable text based on score ranges

**Configuration Integration**:

- [ ] T040 [US4] [juitar] Add preference keywords to affinity_config in backend/app/services/analysis/affinity_config.py
  - Update get_config() to include preference_keywords_json field
  - Update update_config() to handle preference keywords array
  - Validate preference keywords are non-empty strings

**Checkpoint**: 所有4个用户故事现在都应独立功能化。喜好维度2个子维度全部实现

---

## Phase 7: Orchestrator & Scoring (Joint Responsibility)

**Purpose**: Integrate all 4 dimensions and calculate overall affinity score

### Implementation for Orchestrator

- [ ] T041 [Orchestrator] [juitar] Implement AffinityAnalysisService orchestrator in backend/app/services/analysis/affinity_analysis_service.py
  - **CRITICAL**: Call preprocessing_orchestrator.orchestrate_preprocessing() before any dimension calculations
  - analyze() method - main entry point, triggers full analysis pipeline
  - _preprocess_conversation() helper method - ensure preprocessing orchestrator has completed
  - _calculate_all_dimensions() helper method - call all 4 dimension services (now fully parallel, no serial dependency)
  - _calculate_overall_score() helper method - weighted sum: emotional_resonance×0.3 + chat_positivity×0.3 + attitude_tendency×0.2 + preference_compatibility×0.2
  - _save_results() helper method - write to affinity_scores table
  - get_scores() method - retrieve cached scores from affinity_scores table
  - reanalyze() method - invalidate preprocessing cache and re-run analysis
  - _generate_progress_updates() helper method - emit progress events for UI polling

- [ ] T042 [Orchestrator] [juitar] Implement task tracking and progress reporting in backend/app/services/analysis/affinity_analysis_service.py
  - Generate unique task_id for each analysis run (format: "affinity_{conversation_id}_{timestamp}")
  - Store task progress in memory or backend/data/analysis_tasks.json
  - Update progress_percent (0-100) and current_step description
  - Handle task cancellation and error recovery

- [ ] T043 [Orchestrator] [ting] Add interpretation text generation in backend/app/services/analysis/affinity_analysis_service.py
  - generate_overall_interpretation() method - overall score interpretation (e.g., "总体好感度较高,对方对这段关系较为重视" for scores >70)
  - aggregate_dimension_interpretations() method - combine interpretations from all 4 dimension services
  - format_score_breakdown() method - structure sub-scores JSON for frontend display

**Checkpoint**: 主分析服务完成,能够协调4个维度并生成总分

---

## Phase 8: Backend API Integration

**Purpose**: Expose affinity analysis functionality via Bridge API

### Bridge API Endpoints

- [ ] T044 [P] [API] [juitar] Add POST /affinity/analyze endpoint in backend/app/webview/bridge.py
  - Accept conversation_id, force_reanalyze, config_overrides parameters
  - Call affinity_service.analyze() and return task_id
  - Return estimated_duration_ms based on message count

- [ ] T045 [P] [API] [juitar] Add GET /affinity/progress/{task_id} endpoint in backend/app/webview/bridge.py
  - Query task status from affinity_service
  - Return status (pending/running/completed/failed), progress_percent, current_step, error (if failed), result (if completed)

- [ ] T046 [P] [API] [juitar] Add GET /affinity/scores/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Call affinity_service.get_scores()
  - Return 404 if no analysis exists (suggest analyzing first)

- [ ] T047 [P] [API] [ting] Add GET /affinity/config/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Call affinity_config.get_config()
  - Return default config if no per-conversation override exists

- [ ] T048 [P] [API] [ting] Add PUT /affinity/config/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Validate config (weights sum to 1.0, thresholds in valid ranges)
  - Call affinity_config.update_config()
  - Return 400 if validation fails

- [ ] T049 [P] [API] [ting] Add GET /affinity/keywords endpoint in backend/app/webview/bridge.py
  - Call keyword_service.get_all_keywords()
  - Return all 6 categories as dict

- [ ] T050 [P] [API] [ting] Add POST /affinity/keywords endpoint in backend/app/webview/bridge.py
  - Accept category and keywords array
  - Call keyword_service.add_keywords()
  - Return added_count and updated keyword list

- [ ] T051 [P] [API] [ting] Add DELETE /affinity/keywords endpoint in backend/app/webview/bridge.py
  - Accept category and keywords array
  - Call keyword_service.remove_keywords()
  - Return removed_count

- [ ] T052 [P] [API] [ting] Add GET /affinity/preference-keywords/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Retrieve preference_keywords_json from affinity_config
  - Return empty array if not configured

- [ ] T053 [P] [API] [ting] Add PUT /affinity/preference-keywords/{conversation_id} endpoint in backend/app/webview/bridge.py
  - Accept keywords array
  - Update affinity_config.preference_keywords_json

**Checkpoint**: 所有10个API端点实现并可用,前端可以调用分析功能

---

## Phase 9: Frontend Implementation

**Purpose**: Create Vue 3 UI for affinity analysis visualization and configuration

### API Client

- [ ] T054 [P] [Frontend] [ting] Create frontend/src/api/affinity.ts API client
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

- [ ] T055 [Frontend] [ting] Create frontend/src/views/AffinityView.vue main page
  - Conversation selector dropdown
  - "开始分析" button (triggers analyzeAffinity)
  - Progress bar with percentage display
  - Overall score display (large number 0-100)
  - 4 dimension scores cards (clickable for details)
  - Interpretation text display
  - "重新分析" button (triggers reanalyze)

### Components

- [ ] T056 [P] [Frontend] [ting] Create frontend/src/components/affinity/AffinityScoreCard.vue component
  - Props: title, score, maxScore, interpretation
  - Visual score display (circular progress or bar chart)
  - Color coding: red (0-40), yellow (40-70), green (70-100)

- [ ] T057 [P] [Frontend] [ting] Create frontend/src/components/affinity/DimensionRadar.vue component
  - ECharts radar chart displaying 4 dimensions
  - Props: dimensionScores object (emotional_resonance, chat_positivity, attitude_tendency, preference_compatibility)
  - Responsive sizing and tooltip on hover

- [ ] T058 [P] [Frontend] [ting] Create frontend/src/components/affinity/SubScoreBreakdown.vue component
  - Props: subScores object, dimensionName
  - Table display of sub-dimensions with weights and scores
  - Expandable rows for detailed explanations

- [ ] T059 [P] [Frontend] [juitar] Create frontend/src/components/affinity/ConfigPanel.vue component
  - Dimension weight sliders (4 sliders, must sum to 100%)
  - Threshold inputs (reply timeliness, topic continuity window, similarity threshold, sliding window size)
  - "保存配置" button (calls updateAffinityConfig)
  - Validation error messages (if weights don't sum to 100%)

- [ ] T060 [P] [Frontend] [juitar] Create frontend/src/components/affinity/KeywordEditor.vue component
  - 6 tabs for each keyword category
  - Keyword list display (with delete buttons)
  - "添加关键词" input + button per category
  - Save/cancel buttons
  - Calls addKeywords/removeKeywords APIs

### Integration

- [ ] T061 [Frontend] [juitar] Add AffinityView to router in frontend/src/router/index.ts
  - Route path: /affinity/:id (where :id is conversation_id)
  - Route name: affinity

- [ ] T062 [Frontend] [juitar] Add "好感度分析" tab/link in frontend/src/views/ConversationView.vue
  - Navigate to AffinityView when clicked
  - Pass conversation_id as route parameter

**Checkpoint**: 前端UI完成,用户可以查看分析结果和调整配置

---

## Phase 10: Testing & Validation

**Purpose**: Comprehensive testing of all functionality

### Unit Tests

- [ ] T063 [P] [Tests] [joint] Complete backend/tests/test_sentiment_service.py with SnowNLP accuracy validation (>85% on labeled data)
- [ ] T064 [P] [Tests] [joint] Complete backend/tests/test_interaction_pairs.py with construction algorithm validation
- [ ] T065 [P] [Tests] [joint] Complete backend/tests/test_emotional_resonance.py with all 5 sub-dimensions calculation tests
- [ ] T066 [P] [Tests] [joint] Complete backend/tests/test_chat_positivity.py with all 5 sub-dimensions tests
- [ ] T067 [P] [Tests] [joint] Complete backend/tests/test_attitude_tendency.py with all 5 sub-dimensions tests
- [ ] T068 [P] [Tests] [joint] Complete backend/tests/test_preference_compatibility.py with both sub-dimensions tests
- [ ] T069 [P] [Tests] [joint] Create backend/tests/test_affinity_config.py with config validation and persistence tests
- [ ] T070 [P] [Tests] [joint] Complete backend/tests/test_keyword_libraries.py with CRUD operation tests

### Integration Tests

- [ ] T071 [Tests] [joint] Create backend/tests/test_affinity_analysis_integration.py with full pipeline test
  - Test 1: Small conversation (1,000 messages) - should complete in < 30 seconds
  - Test 2: Medium conversation (10,000 messages) - should complete in < 2 minutes
  - Test 3: Verify preprocessing cache invalidation on config change
  - Test 4: Verify re-analysis correctness
  - Test 5: Verify all 4 dimensions calculate correctly using preprocessed statistics
  - Test 6: Verify overall score formula (weighted sum)
  - Test 7: Verify preprocessing O(N) complexity (single pass through messages)

### Performance Tests

- [ ] T072 [Tests] [joint] Run performance benchmark with backend/tests/fixtures/conversation_medium.json (10,000 messages)
  - Target: < 2 minutes analysis time
  - Measure: preprocessing time, sentiment analysis time, embedding generation time, interaction pair construction time, dimension calculation time
  - Verify: attitude tendency uses preprocessed statistics (O(1) lookup vs O(6N) iteration)
  - Log bottleneck identification

- [ ] T073 [Tests] [joint] Run performance stress test with backend/tests/fixtures/conversation_large.json (100,000 messages if available)
  - Target: < 5 minutes analysis time
  - Monitor: memory usage (<2GB), CPU usage, database size
  - Identify optimization opportunities

### Edge Case Tests

- [ ] T074 [Tests] [joint] Create backend/tests/test_edge_cases.py covering all edge cases from spec.md
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

- [ ] T075 [P] [Polish] [juitar] Implement batch processing optimization in backend/app/services/analysis/sentiment_service.py
  - Increase batch size from 32 to 64 for embeddings
  - Implement parallel processing for large conversations (>10K messages)

- [ ] T076 [P] [Polish] [juitar] Add LRU cache for sentence embeddings in backend/app/services/analysis/sentiment_service.py
  - Cache size: 10,000 most recent embeddings
  - Cache hit rate logging
  - Memory usage monitoring

- [ ] T077 [Polish] [juitar] Implement database query optimization in backend/app/db/connection.py
  - Add indexes on frequently queried columns (if not already present)
  - Use batch inserts for sentiment_cache and interaction_pairs
  - Implement query result caching

### Error Handling & Logging

- [ ] T078 [P] [Polish] [ting] Add comprehensive error handling in backend/app/services/analysis/affinity_analysis_service.py
  - Try-except blocks around all external library calls (SnowNLP, sentence-transformers)
  - 阿澄ful degradation on failures (fallback to neutral/zero values)
  - Detailed error messages for UI display

- [ ] T079 [P] [Polish] [ting] Add structured logging in all service files
  - DEBUG: Algorithm steps, intermediate values
  - INFO: Analysis start/end, cache hits/misses
  - WARNING: Fallbacks activated, missing data
  - ERROR: Critical failures requiring user attention
  - Use Python logging module with proper formatters

### Documentation

- [ ] T080 [P] [Polish] [ting] Update backend/README.md with affinity analysis section
  - Overview of 4-dimensional scoring system
  - Preprocessing architecture explanation (29 statistics in O(N) single pass)
  - Configuration options explanation
  - Performance benchmarks
  - Troubleshooting guide

- [ ] T081 [P] [Polish] [ting] Create frontend/src/views/AffinityView.md component documentation
  - Props reference
  - Event descriptions
  - Usage examples
  - Screenshot placeholders

- [ ] T082 [P] [Polish] [ting] Update CLAUDE.md with 002-affinity-analysis implementation notes
  - Add to "Recent Changes" section
  - Document new preprocessing services and their purposes
  - Document O(N) vs O(6N) performance improvement for attitude tendency

### Code Quality

- [ ] T083 [Polish] [joint] Run linter on all new Python files: `ruff check backend/app/services/analysis/`
- [ ] T084 [Polish] [joint] Run linter on all new Vue files: `eslint --ext .vue frontend/src/components/affinity/ frontend/src/views/`
- [ ] T085 [Polish] [joint] Format all code according to project style guidelines

### Validation

- [ ] T086 [Polish] [joint] Run all backend tests: `cd backend && pytest tests/ -v`
- [ ] T087 [Polish] [joint] Verify all tests pass (target: >90% pass rate)
- [ ] T088 [Polish] [joint] Run quickstart.md validation - follow quickstart guide step-by-step and verify all steps work

**Checkpoint**: 项目完成,准备部署

---

## Dependencies & Execution Order

### Phase Dependencies (Preprocessing-First Architecture)

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **Preprocessing Layer (Phase 2.5)**: ⚠️ **CRITICAL PATH** - Depends on Foundational completion - BLOCKS ALL dimensions
  - T016-T020 (juitar): SentimentService + Basic/Pair/Session preprocessing
  - T021-T024 (ting): KeywordLibraries + Attitude preprocessing
  - T025-T026 (joint): PreprocessingOrchestrator + integration tests
  - **GATE**: All 29 statistics must be collected and cached before ANY dimension work begins
- **User Stories (Phase 3-6)**: **ALL depend on Preprocessing Layer (Phase 2.5) completion**
  - US1 (Emotional Resonance): Depends on T025 (preprocessing orchestrator) - can run in parallel with US2-US4
  - US2 (Chat Positivity): Depends on T025 (preprocessing orchestrator) - can run in parallel with US1/US3/US4
  - US3 (Attitude Tendency): Depends on T025 (preprocessing orchestrator) - can run in parallel with US1/US2/US4
  - US4 (Preference Compatibility): Depends on T025 (preprocessing orchestrator) - can run in parallel with US1-US3
- **Orchestrator (Phase 7)**: Depends on all 4 user stories being complete
- **Backend API (Phase 8)**: Depends on Orchestrator being complete
- **Frontend (Phase 9)**: Depends on Backend API being complete
- **Testing (Phase 10)**: Depends on all implementation being complete
- **Polish (Phase 11)**: Depends on all tests passing

### Week-by-Week Timeline (2-Person Parallel Development)

**Week 1: Preprocessing Layer (⚠️ CRITICAL - blocks all dimensions)**

```
Day 1-2 (juitar || ting fully parallel):
  juitar: T016-T019 (SentimentService + tests + caching)
  ting: T021-T022 (KeywordLibraries + tests)

Day 3-4 (juitar || ting fully parallel):
  juitar: T020-A/B/C (Basic/Pair/Session preprocessing)
  ting: T023-T024 (Attitude preprocessing + tests)

Day 5 (joint):
  T025-T026 (PreprocessingOrchestrator + integration tests)

⚠️ END OF WEEK 1: Preprocessing complete, ALL 29 statistics available, dimensions can begin
```

**Week 2-3: 4 Dimensions (Fully Parallel)**

```
Week 2 (juitar || ting fully parallel on 2 dimensions each):
  juitar: T027-T028 (US1 Emotional Resonance) + T031-T032 (US2 Chat Positivity)
  ting: T033-T036 (US3 Attitude Tendency)

Week 3 (juitar || ting fully parallel):
  juitar: T037-T040 (US4 Preference Compatibility) + T041-T043 (Orchestrator)
  ting: T044-T053 (Backend API - 10 endpoints)

✅ END OF WEEK 3: All 4 dimensions complete, orchestrator complete, API complete
```

**Week 4: Frontend + Integration**

```
Week 4 (juitar || ting fully parallel):
  juitar: T059-T060, T061-T062 (ConfigPanel + KeywordEditor + Router integration)
  ting: T054-T058 (API client + AffinityView + 4 components)

✅ END OF WEEK 4: Frontend complete, full stack integrated
```

**Week 5: Testing & Polish**

```
Week 5 (joint work):
  Day 1-2: T063-T074 (All unit + integration + performance tests)
  Day 3: T075-T077 (Performance optimization)
  Day 4: T078-T082 (Error handling + logging + documentation)
  Day 5: T083-T088 (Code quality + validation)

✅ END OF WEEK 5: Project complete, production ready
```

### Preprocessing Layer Dependencies (Critical Path)

```
T016-T019 (juitar): SentimentService
  ↓
T020-A/B/C (juitar): Basic/Pair/Session preprocessing (depends on SentimentService)
  ↓
T021-T022 (ting): KeywordLibraries (independent, parallel with above)
  ↓
T023-T024 (ting): Attitude preprocessing (depends on KeywordLibraries)
  ↓
T025 (joint): PreprocessingOrchestrator (depends on T020 + T023)
  ↓
⚠️ GATE: T025 MUST be complete before ANY dimension work can begin
  ↓
T027-T040 (juitar || ting fully parallel): All 4 dimensions (US1-US4)
```

### Parallel Opportunities by Phase

**Setup Phase (Phase 1)**:
- T002 and T003 can run in parallel (install dependencies + download model)

**Foundational Phase (Phase 2)**:
- T004-T007 (migration scripts) can run in parallel
- T008-T009 (migration scripts) can run in parallel
- T013-T015 (test data creation) can run in parallel

**Preprocessing Phase (Phase 2.5)**:
- T016-T019 (juitar) || T021-T022 (ting) - fully parallel (Day 1-2)
- T020-A/B/C (juitar) || T023-T024 (ting) - fully parallel (Day 3-4)

**Dimension Phases (Phase 3-6)**:
- **⚠️ CRITICAL**: ALL dimension phases (US1-US4) can run FULLY parallel after T025 complete
- T027-T028 (US1) || T031-T032 (US2) || T033-T036 (US3) || T037-T040 (US4) - all parallel

**Backend API (Phase 8)**:
- T044-T046 (affinity endpoints) can run in parallel
- T047-T053 (config/keywords endpoints) can run in parallel

**Frontend (Phase 9)**:
- T054-T060 (API client + components) can run in parallel
- T061-T062 (router integration) can run in parallel

**Testing (Phase 10)**:
- T063-T070 (unit tests) can run in parallel
- T071-T074 (integration/performance/edge case tests) must run sequentially

**Polish (Phase 11)**:
- T075-T077 (optimization) can run in parallel
- T078-T079 (error handling) can run in parallel
- T080-T082 (documentation) can run in parallel

---

## Implementation Strategy

### Preprocessing-First Architecture (⚠️ NEW)

**Key Innovation**: Extract preprocessing as independent layer before any dimension calculations

**Benefits**:
1. **Performance**: O(N) vs O(6N) for attitude tendency (6x speedup)
2. **Parallel Development**: Week 1 preprocessing enables Week 2-3 fully parallel dimension work
3. **Code Reusability**: All dimensions reuse same 29 preprocessed statistics
4. **Cache Efficiency**: Single preprocessing pass cached for all dimensions

**Implementation Order**:

1. **Week 1**: Preprocessing Layer (Phase 2.5) - ⚠️ CRITICAL PATH
   - juitar: SentimentService + Basic/Pair/Session preprocessing (T016-T020)
   - ting: KeywordLibraries + Attitude preprocessing (T021-T024)
   - joint: PreprocessingOrchestrator + tests (T025-T026)

2. **Week 2-3**: 4 Dimensions (Fully Parallel)
   - juitar: US1 (Emotional Resonance) + US2 (Chat Positivity)
   - ting: US3 (Attitude Tendency) + US4 (Preference Compatibility)

3. **Week 4**: Frontend + API
   - juitar: ConfigPanel + Router integration
   - ting: AffinityView + Components

4. **Week 5**: Testing & Polish
   - joint: All tests + optimization + documentation

### MVP First (User Stories 1+2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 2.5: Preprocessing Layer (⚠️ CRITICAL - blocks all dimensions)
4. Complete Phase 3: User Story 1 (Emotional Resonance)
5. Complete Phase 4: User Story 2 (Chat Positivity)
6. **STOP and VALIDATE**: 独立测试 User Stories 1+2
7. 如果准备就绪,部署/演示MVP

**MVP 价值**: 实现核心的情感共振率和聊天积极度分析,满足最重要的关系评估需求(60%权重)

### Incremental Delivery

1. Complete Setup + Foundational → 基础设施就绪
2. Add Preprocessing Layer → ⚠️ 29 statistics collected in O(N), cache ready
3. Add User Story 1 → 独立测试 → 部署/演示
4. Add User Story 2 → 独立测试 → 部署/演示 (MVP!)
5. Add User Story 3 → 独立测试 → 部署/演示
6. Add User Story 4 → 独立测试 → 部署/演示
7. Complete Orchestrator + API → 集成测试 → 部署/演示
8. Add Frontend → E2E测试 → 最终部署
9. Complete Polish → 生产就绪版本
10. 每个故事都增加价值而不破坏已有功能

### Recommended Execution Order

**双开发者并行执行**(推荐,juitar + ting协作):

```
Week 1: Preprocessing Layer (⚠️ CRITICAL PATH)
  juitar: T016-T020 (SentimentService + Basic/Pair/Session preprocessing)
  ting: T021-T024 (KeywordLibraries + Attitude preprocessing)
  joint: T025-T026 (PreprocessingOrchestrator + tests)
  ↓
Week 2-3: 4 Dimensions (Fully Parallel)
  juitar: T027-T028 (US1) + T031-T032 (US2) + T037-T040 (US4) + T041-T043 (Orchestrator)
  ting: T033-T036 (US3) + T044-T053 (Backend API)
  ↓
Week 4: Frontend (Parallel)
  juitar: T059-T062 (ConfigPanel + Router integration)
  ting: T054-T058 (API client + AffinityView + Components)
  ↓
Week 5: Testing + Polish (Joint)
  All: T063-T088 (Tests + Optimization + Documentation)
```

---

## Notes

- [P] 任务 = 不同文件,无依赖,可并行
- [Story] 标签将任务映射到特定用户故事以便追溯
- [Developer] 标签标识主要开发者(juitar/ting/joint)
- ⚠️ **CRITICAL**: Preprocessing Layer (Phase 2.5) must be complete before ANY dimension work
- 每个用户故事应可独立完成和测试
- 在每个检查点停下独立验证故事功能
- 每个任务或逻辑组后提交代码
- 避免模糊任务、同文件冲突、破坏独立性的跨故事依赖
- **Performance Gain**: Preprocessing reduces attitude tendency from O(6N) → O(1) lookup (6x speedup)

---

## Task Summary

- **Total Tasks**: 88
- **Phase 1 (Setup)**: 3 tasks
- **Phase 2 (Foundational)**: 15 tasks (BLOCKING)
- **Phase 2.5 (Preprocessing Layer)**: 11 tasks (⚠️ CRITICAL PATH - BLOCKS ALL DIMENSIONS)
  - juitar: 7 tasks (T016-T020)
  - ting: 3 tasks (T021-T024)
  - joint: 1 task (T025-T026)
- **Phase 3 (US1 - Emotional Resonance)**: 2 tasks
- **Phase 4 (US2 - Chat Positivity)**: 4 tasks
- **Phase 5 (US3 - Attitude Tendency)**: 4 tasks
- **Phase 6 (US4 - Preference Compatibility)**: 4 tasks
- **Phase 7 (Orchestrator)**: 3 tasks
- **Phase 8 (Backend API)**: 10 tasks
- **Phase 9 (Frontend)**: 9 tasks
- **Phase 10 (Testing)**: 12 tasks
- **Phase 11 (Polish)**: 14 tasks

**Parallel Opportunities Identified**: 60+ 任务可并行执行

**Independent Test Criteria**:
- US1: 验证情感共振率5个子维度计算正确性(双向积极响应、极性一致性、强度匹配、共情识别、负面化解)
- US2: 验证聊天积极度5个子维度计算正确性(日均消息、及时回复、消息长度、话题延续、主动发起)
- US3: 验证态度倾向5个子维度计算正确性(正负面词、多媒体、专属称呼、隐私分享、节假日祝福)
- US4: 验证喜好维度2个子维度计算正确性(话题提及频率、喜好话题延续性)

**Suggested MVP Scope**: User Stories 1+2 (Phase 3+4) - 提供核心情感共振率和聊天积极度分析功能

**Format Validation**: ✅ 所有任务遵循checklist格式(checkbox, ID, 可选P标记, Story标签, Developer标签, 文件路径)

---

**Ready for Implementation**: ✅ YES

所有任务已明确定义,依赖关系清晰,并行机会已标识,预处理优先架构已优化,可以立即开始实施。

**Estimated Timeline**: 5 weeks (2-person parallel development with preprocessing-first architecture)

**Key Milestones**:
- Week 1: Preprocessing Layer (T016-T026) - ⚠️ CRITICAL GATE
- Week 2-3: 4 Dimensions (T027-T040) - Fully parallel after preprocessing
- Week 4: Frontend + API Integration (T041-T062)
- Week 5: Testing + Polish (T063-T088)

**Performance Targets**:
- Preprocessing: < 30 seconds for 10K messages (O(N) single pass)
- Attitude tendency: O(1) lookup vs O(6N) iteration (6x speedup)
- Full analysis: < 2 minutes for 10K messages (spec SC-001)
