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
- Lazy evaluation with caching strategy (analyze on-demand, persist results)

**Key Design Decisions**:
- Speech unit merging (5-min threshold) to reduce computation
- Interaction pair construction as basic analysis unit
- Multi-level caching (sentiment → pairs → scores) for performance
- Hierarchical configuration (global → per-conversation → per-analysis)
- 阿澄ful degradation (fallback to neutral on analysis failures)

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
│   │       ├── sentiment_service.py                # NEW - SnowNLP integration
│   │       ├── interaction_pair_builder.py         # NEW - Speech unit + pair construction
│   │       ├── emotional_resonance_service.py      # NEW - Dimension 1
│   │       ├── chat_positivity_service.py          # NEW - Dimension 2
│   │       ├── attitude_tendency_service.py        # NEW - Dimension 3
│   │       ├── preference_compatibility_service.py # NEW - Dimension 4
│   │       ├── affinity_analysis_service.py        # NEW - Main orchestrator
│   │       ├── affinity_config.py                  # NEW - Config management
│   │       ├── keyword_libraries.py                # NEW - Keyword CRUD
│   │       ├── preprocessing_service.py            # EXISTING - Will use
│   │       └── analysis_service.py                 # EXISTING - Will extend
│   ├── db/
│   │   ├── schema.sql                               # EXISTING - Will extend
│   │   └── migrations/
│   │       ├── sentiment_cache.sql                  # NEW
│   │       ├── speech_units.sql                     # NEW
│   │       ├── interaction_pairs.sql                # NEW
│   │       ├── affinity_config.sql                  # NEW
│   │       ├── keyword_libraries.sql                # NEW
│   │       └── affinity_scores.sql                  # NEW
│   └── webview/
│       └── bridge.py                                # EXISTING - Will extend (add 8 endpoints)
├── scripts/
│   └── populate_default_keywords.py                 # NEW - Seed default keywords
└── tests/
    ├── test_sentiment_service.py                    # NEW
    ├── test_interaction_pairs.py                    # NEW
    ├── test_affinity_analysis.py                    # NEW
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
- Frontend Vue components display results and configuration UI
- Clear separation: analysis in backend, presentation in frontend

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

6. **Database Schema**: 6 new tables
   - sentiment_cache, speech_units, interaction_pairs
   - affinity_config, keyword_libraries, affinity_scores
   - Estimated storage: ~16.8 MB per 10K-message conversation

7. **Performance Optimization**: Multi-level caching
   - Sentence embeddings: LRU cache (max 10K entries)
   - Sentiment results: Database cache (persisted)
   - Interaction pairs: Database cache (rebuild on config change)
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

## Phase 2: Task Breakdown (NEXT STEP)

**Command**: Run `/speckit.tasks` to generate detailed task list

**Expected Output**: [tasks.md](tasks.md)

**Task Categories**:
1. **Database Migration** (3 tasks)
   - Create migration scripts for 6 tables
   - Populate default keywords
   - Test migration on fresh database

2. **Backend Core Services** (12 tasks)
   - juitar: sentiment_service.py, interaction_pair_builder.py
   - juitar: emotional_resonance_service.py (Dimension 1)
   - ting: keyword_libraries.py, affinity_config.py
   - ting: chat_positivity_service.py (Dimension 2)
   - ting: attitude_tendency_service.py (Dimension 3)
   - ting: preference_compatibility_service.py (Dimension 4)
   - joint: affinity_analysis_service.py (orchestrator)

3. **Backend API Integration** (2 tasks)
   - Update bridge.py with 8 endpoints
   - Add error handling and validation

4. **Frontend Implementation** (5 tasks)
   - ting: AffinityView.vue (main page)
   - ting: AffinityScoreCard.vue, DimensionRadar.vue
   - ting: ConfigPanel.vue, KeywordEditor.vue
   - ting: affinity.ts (API client)

5. **Testing** (4 tasks)
   - Unit tests for all services
   - Integration test for full pipeline
   - E2E test for UI workflow
   - Performance test (100K messages)

6. **Documentation & Polish** (2 tasks)
   - Update user documentation
   - Performance optimization & profiling

**Total Estimated Tasks**: ~28 tasks over 5 weeks (see COLLABORATION_GUIDE.md for timeline)

**Developer Assignment**:
- **juitar**: ~12 tasks (sentiment, interaction pairs, Dimension 1, orchestration, testing)
- **ting**: ~14 tasks (Dimensions 2-4, keywords, config, frontend UI, docs)
- **joint**: ~2 tasks (API integration, integration testing, final polish)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 0 (Research) ✅ COMPLETE
  ↓
Phase 1 (Design) ✅ COMPLETE
  ↓
Phase 2 (Tasks) ← NEXT STEP
  ↓
Phase 3 (Implementation)
  ↓
Phase 4 (Testing & Polish)
```

### Within Phase 2 (Task Level)

**Critical Path** (must be sequential):
1. Database migration (blocks all analysis code)
2. sentiment_service.py (blocks interaction_pair_builder, all dimensions)
3. interaction_pair_builder.py (blocks all dimensions)
4. affinity_analysis_service.py (orchestrator, requires all dimensions)
5. Bridge API integration (blocks frontend)
6. Frontend UI (depends on API)

**Parallel Opportunities**:
- ting can implement keyword_libraries.py while juitar implements sentiment_service.py
- ting can implement Dimensions 2-4 in parallel (after dependencies ready)
- Frontend components can be built in parallel (after API contracts defined)

**Collaboration Points**:
- juitar provides semantic similarity function → ting uses for topic continuity
- ting provides keyword libraries → juitar uses for emotional resonance
- ting provides config management → joint uses for all dimensions
- Both work on integration testing → verify end-to-end pipeline

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

## Next Steps

1. **Immediate**: Run `/speckit.tasks` to generate detailed task breakdown
2. **Week 1**: juitar - sentiment service + interaction pairs
   ting - keyword libraries + config management
3. **Week 2-3**: juitar - Dimension 1 (emotional resonance)
   ting - Dimension 2 (chat positivity)
4. **Week 4**: ting - Dimensions 3-4 (attitude + preference)
   juitar - Orchestrator service
5. **Week 5**: Joint - Integration testing, frontend UI, polish

**Ready for Implementation**: ✅ YES

All planning artifacts complete, technology decisions finalized, contracts defined, developer onboarding materials ready. Proceed to Phase 2 (task breakdown) and begin implementation.

---

**Plan Status**: ✅ COMPLETE (Phase 0 + Phase 1)
**Last Updated**: 2026-01-08
**Next Command**: `/speckit.tasks` (generate task list)
