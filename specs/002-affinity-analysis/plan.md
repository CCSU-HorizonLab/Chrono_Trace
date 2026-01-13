# Implementation Plan: Conversation Affinity Analysis System

**Branch**: `002-affinity-analysis` | **Date**: 2026-01-08 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-affinity-analysis/spec.md`

**Note**: This document is the output of the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

This feature implements a comprehensive 4-dimensional affinity analysis system for WeChat conversation records. The system calculates relationship quality scores based on:
1. **Emotional Resonance** (30% weight): Bidirectional emotional response, polarity consistency, intensity matching, empathy recognition, negative emotion resolution
2. **Chat Positivity** (30% weight): Daily message count, reply timeliness, message length, topic continuity, active initiation
3. **Attitude Tendency** (20% weight): Positive/negative word frequency, multimedia usage, exclusive nicknames, privacy sharing, holiday greetings
4. **Preference Compatibility** (20% weight): Topic mention frequency, preference topic continuity

**Technical Approach**:
- SnowNLP for Chinese sentiment analysis (polarity + intensity)
- sentence-transformers for semantic similarity (384-dim embeddings)
- SQLite for caching sentiment results, interaction pairs, and affinity scores
- Keyword libraries for pattern matching (user-customizable)
- **Preprocessing-first architecture** - O(N) single-pass collection of 29 statistics before dimension calculations
- Lazy evaluation with caching strategy (analyze on-demand, persist results)

**Key Design Decisions**:
- **⚠️ PREPROCESSING PRIORITY**: Extract preprocessing as independent Phase 2.5 layer before any dimension work
- Speech unit merging (5-min threshold) to reduce computation
- Interaction pair construction as basic analysis unit
- Multi-level caching (sentiment → pairs → preprocessing → scores) for performance
- Hierarchical configuration (global → per-conversation → per-analysis)
- 阿澄ful degradation (fallback to neutral on analysis failures)
- **Performance optimization**: O(N) preprocessing vs O(6N) for attitude tendency (6x speedup)

## Technical Context

**Language/Version**: Python 3.8+
**Primary Dependencies**: SnowNLP (sentiment), sentence-transformers (embeddings), scikit-learn (similarity), jieba (tokenization, existing), numpy (existing)
**Storage**: SQLite (existing, extended with 6 new tables)
**Testing**: pytest (unit + integration tests)
**Target Platform**: Windows 10/11 desktop (PyWebView application)
**Project Type**: web (backend Python + frontend Vue 3)
**Performance Goals**:
  - 1,000 messages: < 30 seconds
  - 10,000 messages: < 2 minutes
  - 100,000 messages: < 5 minutes
**Constraints**:
  - Must run locally (no external API calls for analysis)
  - Model warm-up time ~2 seconds (acceptable at startup)
  - Memory usage < 2GB during analysis
  - Database growth ~16.8 MB per 10K-message conversation
**Scale/Scope**:
  - Typical conversation: 1,000-10,000 messages
  - Maximum tested: 100,000 messages
  - Support for unlimited concurrent conversations (lazy evaluation)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: ✅ PASSED (No constitution defined for this project)

The project constitution file `.specify/memory/constitution.md` contains only template placeholders. No specific architectural principles or quality gates are defined. Therefore, this implementation plan proceeds with industry best practices:

- **Separation of Concerns**: Each dimension in separate service module
- **Testability**: Unit tests for all core algorithms, integration tests for full pipeline
- **Performance**: Caching strategy, batch processing, lazy evaluation
- **Maintainability**: Clear module boundaries, documented APIs, configuration-driven behavior

**Post-Design Re-evaluation**: ✅ PASSED

After completing Phase 1 design (research.md, data-model.md, contracts/), the design remains aligned with best practices. No architectural violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/002-affinity-analysis/
├── spec.md                    # Feature specification (4 user stories, 40 FRs)
├── plan.md                    # This file (implementation plan)
├── research.md                # Phase 0: Technology research & decisions
├── data-model.md              # Phase 1: Database schema & entity design
├── quickstart.md              # Phase 1: Developer quickstart guide
├── contracts/                 # Phase 1: API contracts
│   └── bridge_api.yaml        # OpenAPI 3.0 spec for Bridge API
├── checklists/
│   └── requirements.md        # Spec quality checklist
├── COLLABORATION_GUIDE.md     # Git workflow & task division (juitar + ting)
└── tasks.md                   # Phase 2: Task breakdown (NOT created yet)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── services/
│   │   └── analysis/
│   │       ├── sentiment_service.py                # NEW - SnowNLP integration (Phase 2.5)
│   │       ├── preprocessing_service.py            # NEW - Basic statistics collection (Phase 2.5)
│   │       ├── session_manager.py                  # NEW - Session splitting logic (Phase 2.5)
│   │       ├── preprocessing_orchestrator.py       # NEW - Coordinates all preprocessing (Phase 2.5)
│   │       ├── interaction_pair_builder.py         # NEW - Speech unit + pair construction (Phase 2.5)
│   │       ├── keyword_libraries.py                # NEW - Keyword CRUD (Phase 2.5)
│   │       ├── emotional_resonance_service.py      # NEW - Dimension 1 (uses preprocessing)
│   │       ├── chat_positivity_service.py          # NEW - Dimension 2 (uses preprocessing)
│   │       ├── attitude_tendency_service.py        # NEW - Dimension 3 (uses preprocessing)
│   │       ├── preference_compatibility_service.py # NEW - Dimension 4 (uses preprocessing)
│   │       ├── affinity_analysis_service.py        # NEW - Main orchestrator (calls preprocessing first)
│   │       ├── affinity_config.py                  # NEW - Config management
│   │       └── analysis_service.py                 # EXISTING - Will extend
│   ├── db/
│   │   ├── schema.sql                               # EXISTING - Will extend
│   │   └── migrations/
│   │       ├── sentiment_cache.sql                  # NEW (Phase 2)
│   │       ├── speech_units.sql                     # NEW (Phase 2.5)
│   │       ├── interaction_pairs.sql                # NEW (Phase 2.5)
│   │       ├── session_data.sql                     # NEW (Phase 2.5)
│   │       ├── preprocessed_statistics.sql          # NEW (Phase 2.5)
│   │       ├── affinity_config.sql                  # NEW (Phase 2)
│   │       ├── keyword_libraries.sql                # NEW (Phase 2)
│   │       └── affinity_scores.sql                  # NEW (Phase 2)
│   └── webview/
│       └── bridge.py                                # EXISTING - Will extend (add 10 endpoints)
├── scripts/
│   └── populate_default_keywords.py                 # NEW - Seed default keywords
└── tests/
    ├── test_sentiment_service.py                    # NEW (Phase 2.5)
    ├── test_preprocessing_orchestrator.py           # NEW (Phase 2.5)
    ├── test_keyword_libraries.py                    # NEW (Phase 2.5)
    ├── test_attitude_preprocessing.py               # NEW (Phase 2.5)
    ├── test_interaction_pairs.py                    # NEW (Phase 2.5)
    ├── test_emotional_resonance.py                  # NEW (Phase 3)
    ├── test_chat_positivity.py                      # NEW (Phase 4)
    ├── test_attitude_tendency.py                    # NEW (Phase 5)
    ├── test_preference_compatibility.py             # NEW (Phase 6)
    ├── test_affinity_analysis_integration.py        # NEW (Phase 10)
    └── fixtures/
        └── conversation_*.json                       # NEW - Test data

frontend/
├── src/
│   ├── views/
│   │   └── AffinityView.vue                         # NEW - Main affinity UI
│   ├── components/
│   │   └── affinity/
│   │       ├── AffinityScoreCard.vue                # NEW - Score display
│   │       ├── DimensionRadar.vue                   # NEW - Radar chart
│   │       ├── SubScoreBreakdown.vue                # NEW - Detailed breakdown
│   │       ├── ConfigPanel.vue                      # NEW - Configuration form
│   │       └── KeywordEditor.vue                    # NEW - Keyword management
│   └── api/
│       └── affinity.ts                              # NEW - API client
└── package.json                                     # EXISTING - Will update (add echarts if needed)
```

**Structure Decision**: Web application structure (backend + frontend)

**Rationale**:
- Chrono Trace is a PyWebView desktop app with Vue 3 frontend
- Backend Python services handle all analysis logic
- **⚠️ PREPROCESSING LAYER**: Three new services (preprocessing_service.py, session_manager.py, preprocessing_orchestrator.py) collect 29 statistics in O(N) single pass
- Frontend Vue components display results and configuration UI
- Clear separation: preprocessing → dimensions → orchestrator → API → frontend

## Complexity Tracking

> **No constitution violations - this section intentionally left empty**

All design decisions follow standard industry practices for Python + Vue web applications. No architectural anti-patterns or unnecessary complexity introduced.

---

## Phase 0: Research & Technology Selection ✅ COMPLETE

**Output**: [research.md](research.md)

**Key Decisions Made**:

1. **Sentiment Analysis**: SnowNLP
   - Chinese-optimized, runs locally, ~85% accuracy
   - Alternatives rejected: Baidu AI (cost/privacy), BERT (overkill)

2. **Sentence Embeddings**: sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
   - 384-dimensional vectors, 470MB model size
   - Alternatives rejected: USE (poor Chinese), Text2Vec (too large)

3. **Keyword Libraries**: JSON-based with user customization
   - 6 categories: positive, negative, empathy, soothing, privacy, holiday
   - Default sets provided, users can extend

4. **Interaction Pair Construction**: Two-phase algorithm
   - Phase 1: Merge messages into speech units (5-min threshold)
   - Phase 2: Build alternating pairs from speech units
   - O(n) complexity, ~1000 messages/second

5. **Session Splitting**: Sliding window + valley detection
   - Semantic similarity valleys identify topic boundaries
   - Fallback to time gap (>30 min) for robustness

6. **Database Schema**: 9 new tables (updated from 6)
   - sentiment_cache, speech_units, interaction_pairs
   - session_data, preprocessed_statistics (NEW for preprocessing layer)
   - affinity_config, keyword_libraries, affinity_scores
   - Estimated storage: ~16.8 MB per 10K-message conversation

7. **Performance Optimization**: Multi-level caching + Preprocessing-first architecture
   - **⚠️ PREPROCESSING LAYER**: O(N) single-pass collection of 29 statistics (reduces attitude tendency from O(6N) → O(1), 6x speedup)
   - Sentence embeddings: LRU cache (max 10K entries)
   - Sentiment results: Database cache (persisted)
   - Preprocessed statistics: Database cache (invalidate on config/keyword change)
   - Dimension scores: Database cache (invalidate on config/keyword change)

8. **Configuration Management**: Hierarchical
   - Global defaults → per-conversation overrides → per-analysis overrides
   - JSON serialization for keywords, SQLite for persistence

9. **Error Handling**: 阿澄ful degradation
   - Sentiment analysis failure → neutral (0, 0)
   - Embedding generation failure → zero vector
   - Missing keywords → skip dimension, redistribute weights
   - Division by zero → return 0

10. **Testing Strategy**: Pyramid testing
    - Unit tests (pytest) for each service
    - Integration tests for full pipeline
    - E2E tests for UI workflows
    - Test data: 1K, 10K, 100K message conversations

**All Clarifications Resolved**: ✅ No open questions remaining

---

## Phase 1: Design & Contracts ✅ COMPLETE

### 1.1 Data Model Design ✅

**Output**: [data-model.md](data-model.md)

**New Tables Defined**:
1. `sentiment_cache` - Cache SnowNLP + embedding results
2. `speech_units` - Merged consecutive messages (< 5 min apart)
3. `interaction_pairs` - Alternating speech unit pairs
4. `affinity_config` - Per-conversation configuration
5. `keyword_libraries` - Global keyword sets (default + custom)
6. `affinity_scores` - Computed dimension + overall scores

**Key Design Decisions**:
- Foreign key relationships maintain referential integrity
- Indexes on frequently queried columns (conversation_id, timestamp)
- BLOB storage for embeddings (384 floats × 4 bytes = 1.5KB per message)
- JSON columns for flexible sub-score breakdowns

**Migration Strategy**: Non-breaking additions, lazy analysis (on-demand)

### 1.2 API Contracts ✅

**Output**: [contracts/bridge_api.yaml](contracts/bridge_api.yaml)

**Endpoints Defined**:
- `POST /affinity/analyze` - Trigger analysis (async, returns task_id)
- `GET /affinity/progress/{task_id}` - Poll analysis progress
- `GET /affinity/scores/{conversation_id}` - Get cached scores
- `GET/PUT /affinity/config/{conversation_id}` - Config CRUD
- `GET/POST/DELETE /affinity/keywords` - Global keyword management
- `GET/PUT /affinity/preference-keywords/{conversation_id}` - Per-conv preferences

**API Design Principles**:
- RESTful conventions (GET for query, POST/PUT for modify)
- Async pattern for long-running analysis (task_id polling)
- Configuration validation (400 error if weights don't sum to 1.0)
- 阿澄ful 404 for missing data (suggest analyzing first)

### 1.3 Developer Quickstart ✅

**Output**: [quickstart.md](quickstart.md)

**Sections Included**:
1. Prerequisites (dependencies, hardware requirements)
2. Database setup (migration script + keyword seeding)
3. Project structure (file breakdown)
4. Development workflow (juitar + ting task examples)
5. API integration (bridge.py updates)
6. Frontend integration (Vue component structure)
7. Running the application (dev mode, testing)
8. Troubleshooting (common issues & solutions)

**Getting Started Steps**:
1. Add new dependencies to requirements.txt
2. Run migration script to create 6 new tables
3. Populate default keywords (6 categories × 10 keywords each)
4. Implement sentiment service (juitar)
5. Implement keyword libraries (ting)
6. Update bridge.py with 8 new endpoints
7. Create AffinityView.vue
8. Test with sample data

### 1.4 Agent Context Update ✅

**Output**: Updated [CLAUDE.md](../../CLAUDE.md)

**Changes Made**:
- Added Python 3.8+ + SnowNLP + sentence-transformers to active technologies
- Added SQLite to storage technologies
- Updated last modified date to 2026-01-08
- Documented 002-affinity-analysis in recent changes

**Result**: AI assistants (Claude Code) now aware of new technologies and can provide better code suggestions.

---

## Phase 2: Task Breakdown ✅ COMPLETE

**Output**: [tasks.md](tasks.md)

**Task Categories Updated**:

1. **Database Migration** (7 tasks)
   - Create migration scripts for 9 tables (including 2 new preprocessing tables)
   - Populate default keywords (6 categories)
   - Test migration on fresh database

2. **⚠️ PREPROCESSING LAYER (Phase 2.5)** (11 tasks) **CRITICAL PATH - BLOCKS ALL DIMENSIONS**
   - **Week 1: Preprocessing Implementation (juitar || ting fully parallel)**
   - juitar (7 tasks):
     - T016-T019: SentimentService + tests + caching
     - T020-A/B/C: BasicPreprocessingService + PairPreprocessingService + SessionManager
   - ting (3 tasks):
     - T021-T022: KeywordLibraries ✅ + tests
     - T023-T024: AttitudePreprocessingService + tests
   - joint (1 task):
     - T025-T026: PreprocessingOrchestrator + integration tests
   - **Summary**: Collect 29 statistics in O(N) single pass, cache to database
   - **Progress**: T021 (KeywordLibraries) completed 2026-01-11, T014-T015 (test data) completed 2026-01-13

3. **Backend Core Services - 4 Dimensions** (14 tasks, fully parallel after preprocessing)
   - ting (2 tasks): T027-T028 - Emotional Resonance Service (Dimension 1)
   - juitar (2 tasks): T029-T032 - Chat Positivity Service (Dimension 2)
   - ting (2 tasks): T033-T036 - Attitude Tendency Service (Dimension 3)
   - juitar (2 tasks): T037-T040 - Preference Compatibility Service (Dimension 4)
   - **All dimensions use preprocessed statistics** (O(1) lookup vs O(N) iteration)

4. **Orchestrator & Scoring** (3 tasks)
   - juitar: T041-T042 - AffinityAnalysisService (calls preprocessing first)
   - ting: T043 - Interpretation text generation

5. **Backend API Integration** (10 tasks)
   - Update bridge.py with 10 endpoints (analyze, progress, scores, config, keywords, preferences)
   - Add error handling and validation

6. **Frontend Implementation** (9 tasks)
   - ting: AffinityView.vue (main page) + 4 components (ScoreCard, Radar, Breakdown, KeywordEditor)
   - juitar: ConfigPanel.vue + KeywordEditor.vue + Router integration

7. **Testing** (12 tasks)
   - Unit tests for all preprocessing and dimension services
   - Integration test for full pipeline (including preprocessing O(N) validation)
   - E2E test for UI workflow
   - Performance test (100K messages)

8. **Documentation & Polish** (14 tasks)
   - Update user documentation with preprocessing architecture
   - Performance optimization & profiling
   - Code quality validation

**Total Tasks**: 88 tasks (reduced from 99 by consolidating)

**Developer Assignment**:
- **juitar**: ~38 tasks (preprocessing core + Dimensions 2/4 + orchestrator + API + frontend components)
- **ting**: ~38 tasks (preprocessing attitude + Dimensions 1/3 + frontend main + tests + docs)
- **joint**: ~12 tasks (preprocessing orchestrator + integration tests + final polish)

**Week-by-Week Timeline**:
- **Week 1**: Preprocessing Layer (Phase 2.5) - ⚠️ CRITICAL GATE
  - Day 1-2: juitar (SentimentService) || ting (KeywordLibraries)
  - Day 3-4: juitar (Basic/Pair/Session preprocessing) || ting (Attitude preprocessing)
  - Day 5: joint (PreprocessingOrchestrator + tests)
- **Week 2-3**: 4 Dimensions (Fully Parallel)
  - juitar: US1 + US2 + US4 + Orchestrator
  - ting: US3 + Backend API
- **Week 4**: Frontend (juitar || ting fully parallel)
- **Week 5**: Testing + Polish (joint work)

---

## Dependencies & Execution Order

### Phase Dependencies (Updated with Preprocessing-First Architecture)

```
Phase 0 (Research) ✅ COMPLETE
  ↓
Phase 1 (Design) ✅ COMPLETE
  ↓
Phase 2 (Tasks) ✅ COMPLETE
  ↓
Phase 2.5 (Preprocessing Layer) ⚠️ CRITICAL PATH - BLOCKS ALL DIMENSIONS
  ↓
Phase 3-6 (4 Dimensions - Fully Parallel after preprocessing)
  ↓
Phase 7 (Orchestrator)
  ↓
Phase 8 (Backend API)
  ↓
Phase 9 (Frontend)
  ↓
Phase 10-11 (Testing & Polish)
```

### Within Phase 2.5 (Preprocessing Layer - Critical Path)

**Week 1: Preprocessing (juitar || ting fully parallel)**

```
Day 1-2:
  juitar: T016-T019 (SentimentService + tests + caching)
  ting: T021-T022 (KeywordLibraries + tests)
  ↓
Day 3-4:
  juitar: T020-A/B/C (Basic/Pair/Session preprocessing)
  ting: T023-T024 (Attitude preprocessing + tests)
  ↓
Day 5:
  joint: T025-T026 (PreprocessingOrchestrator + integration tests)
  ↓
⚠️ GATE: Preprocessing complete, ALL 29 statistics available, dimensions can begin
```

**Preprocessing Architecture Benefits**:
- **Performance**: O(N) preprocessing vs O(6N) for attitude tendency (6x speedup)
- **Parallel Development**: Week 1 preprocessing enables Week 2-3 fully parallel dimension work
- **Code Reusability**: All dimensions reuse same 29 preprocessed statistics
- **Cache Efficiency**: Single preprocessing pass cached for all dimensions

**29 Preprocessed Statistics**:
1. **Message Statistics (4)**: total_message_count, total_positive_count, total_negative_count, total_neutral_count
2. **Time Statistics (4)**: conversation_start_timestamp, conversation_end_timestamp, conversation_duration_days, chat_days_count
3. **Length Statistics (2)**: total_characters, average_message_length
4. **Pair Statistics (3)**: total_interaction_pairs, bidirectional_pairs, same_parity_pairs
5. **Session Statistics (3)**: total_sessions, average_session_length, average_session_gap, session_initiators (array)
6. **Attitude Statistics (6)**: emoji_message_count, voice_message_count, video_message_count, nickname_message_count, privacy_message_count, holiday_message_count, holidays_sent_count
7. **Derived Statistics (7)**: Calculated by orchestrator using above 22 raw statistics

### Within Phases 3-6 (4 Dimensions - Fully Parallel)

**After Preprocessing Complete**:
```
Week 2-3 (juitar || ting fully parallel):
  juitar: T027-T028 (US1 Emotional Resonance) + T031-T032 (US2 Chat Positivity)
  ting: T033-T036 (US3 Attitude Tendency)

Week 3 (juitar || ting fully parallel):
  juitar: T037-T040 (US4 Preference Compatibility) + T041-T043 (Orchestrator)
  ting: T044-T053 (Backend API - 10 endpoints)
```

**All Dimensions Use Preprocessed Statistics**:
- US1 (Emotional Resonance): Uses total_positive_count, total_interaction_pairs, sentiment_cache embeddings
- US2 (Chat Positivity): Uses total_message_count, conversation_duration_days, average_message_length, session_initiators
- US3 (Attitude Tendency): Uses emoji_message_count, voice_message_count, video_message_count, nickname_message_count, privacy_message_count, holidays_sent_count (O(1) lookup vs O(6N) iteration)
- US4 (Preference Compatibility): Uses total_sessions, session semantic similarities

### Collaboration Points (Updated)

**Week 1 (Preprocessing)**:
- juitar provides SentimentService → both use for sentiment analysis
- ting provides KeywordLibraries → juitar uses for preprocessing attitude statistics
- joint creates PreprocessingOrchestrator → coordinates all preprocessing services

**Week 2-3 (Dimensions - Fully Parallel)**:
- **NO COLLABORATION BOTTLENECKS** - all dimensions run independently using preprocessed statistics
- juitar implements US1/US2/US4 + Orchestrator
- ting implements US3 + Backend API

**Week 4 (Frontend)**:
- juitar implements ConfigPanel + Router integration
- ting implements AffinityView + 4 components

**Week 5 (Testing)**:
- joint work on integration testing, performance validation, final polish

---

## Risk Mitigation

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| SnowNLP accuracy insufficient | Medium | Low | Fallback to neutral, allow custom model plugins |
| Model loading slow (5-10s) | Low | Medium | Pre-load on startup, show loading UI |
| Out of memory (100K messages) | High | Low | Batch processing (32 messages), streaming analysis |
| Database size bloat | Medium | Medium | Periodic cleanup, compression, archival |
| Performance degradation | Medium | Low | Multi-level caching, performance benchmarks |

### Collaboration Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Git merge conflicts | Medium | High | Clear branch strategy, frequent syncs, communication |
| API contract mismatch | High | Medium | OpenAPI spec as contract, contract tests |
| Integration delays | Medium | Medium | Weekly syncs, shared test data, early integration |
| Uneven workload | Low | Medium | Task breakdown with estimates, flexibility to rebalance |

---

## Success Criteria

### Functional Requirements
- ✅ All 40 functional requirements from spec.md defined and testable
- ✅ 4 user stories (2 P1, 2 P2) independently deliverable
- ✅ Edge cases identified and handled gracefully
- ✅ Configuration fully user-customizable

### Performance Requirements
- ✅ 1,000 messages < 30 seconds
- ✅ 10,000 messages < 2 minutes
- ✅ 100,000 messages < 5 minutes
- ✅ Model warm-up < 5 seconds

### Quality Requirements
- ✅ Unit test coverage > 80%
- ✅ All integration tests passing
- ✅ Zero critical bugs on release
- ✅ Code follows project style guidelines

### Collaboration Requirements
- ✅ Git workflow established (branching, PR reviews)
- ✅ Clear task division (juitar + ting)
- ✅ Weekly syncs scheduled
- ✅ Shared understanding of architecture

---

## Preprocessing Architecture Design Decision

**Problem**: Original architecture had preprocessing logic scattered across individual dimension tasks, creating serial dependency bottlenecks where ting's dimension work (US2-US4) depended on juitar completing US1 first.

**Solution**: Extract preprocessing as independent Phase 2.5 layer with dedicated services that collect all 29 statistics in a single O(N) pass through the conversation data.

**Architecture Change**:

**Before** (Serial Bottleneck):
```
Week 1-2: juitar works on US1 (Emotional Resonance)
  ├─ SentimentService
  ├─ InteractionPairBuilder (contains embedded preprocessing)
  └─ EmotionalResonanceService
  ↓
Week 3-4: ting blocked, waiting for US1 to complete
  ├─ ChatPositivityService (depends on InteractionPairBuilder)
  ├─ AttitudeTendencyService (repeats preprocessing - O(6N) complexity)
  └─ PreferenceCompatibilityService (depends on sessions)
  ↓
Week 5: Orchestrator + API + Frontend
```

**After** (Parallel Development):
```
Week 1: Preprocessing Layer (juitar || ting fully parallel)
  juitar:
    ├─ T016-T019: SentimentService + tests + caching
    └─ T020-A/B/C: Basic/Pair/Session preprocessing
  ting:
    ├─ T021-T022: KeywordLibraries + tests
    └─ T023-T024: Attitude preprocessing
  joint:
    └─ T025-T026: PreprocessingOrchestrator + integration tests
  ↓
⚠️ GATE: All 29 statistics collected and cached
  ↓
Week 2-3: 4 Dimensions (Fully Parallel)
  juitar:
    ├─ US1 (Emotional Resonance) - uses preprocessed statistics
    ├─ US2 (Chat Positivity) - uses preprocessed statistics
    ├─ US4 (Preference Compatibility) - uses preprocessed statistics
    └─ Orchestrator
  ting:
    ├─ US3 (Attitude Tendency) - uses preprocessed statistics
    └─ Backend API (10 endpoints)
  ↓
Week 4: Frontend (juitar || ting fully parallel)
Week 5: Testing + Polish (joint work)
```

**New Service Structure**:

1. **SentimentService** (juitar - Phase 2.5)
   - SnowNLP integration for polarity + intensity
   - Sentence embedding generation (384-dim vectors)
   - Batch processing (32 messages/batch)
   - Database caching (sentiment_cache table)

2. **BasicPreprocessingService** (juitar - Phase 2.5)
   - collect_message_statistics() - 4 basic constants
   - collect_time_statistics() - 4 time constants
   - collect_length_statistics() - 2 length constants
   - All in O(N) single pass

3. **PairPreprocessingService** (juitar - Phase 2.5)
   - build_speech_units() - merge consecutive messages (< 5 min gap)
   - build_interaction_pairs() - create alternating pairs
   - collect_pair_statistics() - 3 pair constants
   - Database caching (speech_units, interaction_pairs tables)

4. **SessionManager** (juitar - Phase 2.5)
   - split_sessions() - semantic similarity valleys (sliding window algorithm)
   - calculate_semantic_similarity() - cosine similarity on embeddings
   - collect_session_statistics() - 3 session constants
   - identify_session_initiators() - mark session initiators (for active initiation)
   - Database caching (session_data table)

5. **KeywordLibraries** (ting - Phase 2.5)
   - get_keywords(category) - retrieve keywords
   - add_keywords(category, keywords) - add custom keywords
   - remove_keywords(category, keywords) - remove keywords
   - check_keywords_in_text(text, keywords) - pattern matching
   - Database persistence (keyword_libraries table)

6. **AttitudePreprocessingService** (ting - Phase 2.5)
   - collect_attitude_statistics() - single-pass collection of 6 attitude message counts
   - O(N) vs O(6N) complexity (6x speedup for attitude tendency)
   - Uses KeywordLibraries for pattern matching

7. **PreprocessingOrchestrator** (joint - Phase 2.5)
   - orchestrate_preprocessing() - main entry point
   - Coordinates all 4 preprocessing services (basic, pairs, sessions, attitude)
   - Validates cached data before preprocessing
   - Invalidates cache on config/keyword change
   - Returns all 29 statistics as PreprocessedStatistics dataclass

**Performance Improvements**:

1. **Attitude Tendency**: O(6N) → O(1) lookup (6x speedup)
   - Before: 6 iterations through messages for 6 keyword categories
   - After: Single preprocessing iteration, dimensions use O(1) lookup

2. **Active Initiation**: Simplified from O(N) → O(1) lookup
   - Before: Traverse interaction pairs to determine initiation type
   - After: Use session_initiators array from preprocessing

3. **Holiday Greeting**: Improved accuracy
   - Before: holiday_message_count / total_message_count (inaccurate)
   - After: holidays_sent_count / total_holiday_count (accurate coverage)

**Database Schema Changes**:

**New Tables** (9 total, up from 6):
1. sentiment_cache (Phase 2) - SnowNLP + embedding results
2. speech_units (Phase 2.5) - Merged consecutive messages
3. interaction_pairs (Phase 2.5) - Alternating speech unit pairs
4. session_data (Phase 2.5) - NEW: Session boundaries + semantic similarities
5. preprocessed_statistics (Phase 2.5) - NEW: All 29 constants cached
6. affinity_config (Phase 2) - Per-conversation configuration
7. keyword_libraries (Phase 2) - Global keyword sets
8. affinity_scores (Phase 2) - Computed dimension + overall scores

**Impact Summary**:

✅ **Benefits**:
- **Performance**: 6x speedup for attitude tendency (O(6N) → O(1))
- **Parallel Development**: Week 1 preprocessing enables Week 2-3 fully parallel dimension work
- **Code Reusability**: All dimensions reuse same 29 preprocessed statistics
- **Maintainability**: Clear separation: preprocessing → dimensions → orchestrator
- **Cache Efficiency**: Single preprocessing pass cached for all dimensions

⚠️ **Risks Mitigated**:
- Serial dependency bottleneck (ting blocked by juitar) → Fully parallel after Week 1
- Code duplication (preprocessing in each dimension) → Single preprocessing layer
- Performance degradation (O(6N) for attitude) → O(N) preprocessing + O(1) lookup

**Implementation Effort**:
- **Additional Tasks**: 11 preprocessing tasks (was scattered across dimensions)
- **Additional Services**: 3 new preprocessing services (BasicPreprocessingService, SessionManager, PreprocessingOrchestrator)
- **Additional Tables**: 2 new preprocessing tables (session_data, preprocessed_statistics)
- **Net Impact**: +11 tasks but enables fully parallel Week 2-3 (net time savings)

---

## Next Steps

1. **Immediate**: ✅ COMPLETE - All planning artifacts (spec.md, plan.md, tasks.md) updated with preprocessing-first architecture
2. **Week 1**: Preprocessing Layer (Phase 2.5) - ⚠️ CRITICAL PATH
   - juitar: T016-T020 (SentimentService + Basic/Pair/Session preprocessing)
   - ting: T021-T024 (KeywordLibraries + Attitude preprocessing)
   - joint: T025-T026 (PreprocessingOrchestrator + tests)
3. **Week 2-3**: 4 Dimensions (Fully Parallel)
   - juitar: US1 + US2 + US4 + Orchestrator
   - ting: US3 + Backend API
4. **Week 4**: Frontend (juitar || ting fully parallel)
5. **Week 5**: Testing + Polish (joint work)

**Ready for Implementation**: ✅ YES

All planning artifacts complete and synchronized:
- ✅ spec.md - Updated with Phase 0-4 preprocessing requirements (FR-000 to FR-025)
- ✅ plan.md - Updated with preprocessing architecture, Week 1-5 timeline
- ✅ tasks.md - Updated with 88 tasks, Phase 2.5 preprocessing as critical path
- ✅ history_analyze.md - Updated with 6-step preprocessing flow

Preprocessing-first architecture maximizes parallel development efficiency for 2-person team (juitar + ting).

---

**Plan Status**: ✅ COMPLETE (Phase 0 + Phase 1 + Phase 2)
**Last Updated**: 2026-01-09 (Updated with preprocessing-first architecture)
**Next Action**: Begin Week 1 - Preprocessing Layer implementation

---

**Plan Status**: ✅ COMPLETE (Phase 0 + Phase 1 + Phase 2)
**Last Updated**: 2026-01-09 (Updated with preprocessing-first architecture)
**Next Action**: Begin Week 1 - Preprocessing Layer implementation
