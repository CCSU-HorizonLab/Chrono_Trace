# Data Model: Conversation Affinity Analysis System

**Feature**: 002-affinity-analysis
**Date**: 2026-01-08
**Status**: Complete

## Overview

This document defines the data model for the affinity analysis system, including new tables, entities, and relationships. The design builds upon the existing Chrono Trace database schema (conversations, messages, contacts) and extends it with affinity-specific tables.

---

## Entity Relationship Diagram

```
┌─────────────────┐
│  conversations  │
│   (existing)    │
└────────┬────────┘
         │
         ├──1:N──┬──────────────────┐
         │       │                  │
    ┌────▼─────┐│           ┌──────▼──────┐
    │ messages ││           │affinity_config│
    │(existing)││           │   (new)     │
    └────┬─────┘│           └─────────────┘
         │      │
         │      └────1:1────┐
         │                  │
    ┌────▼──────────────────▼─────┐
    │   sentiment_cache            │
    │      (new)                   │
    └──────────────┬───────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
    ┌────▼─────┐      ┌──────▼──────┐
    │speech_units│     │interaction_pairs│
    │  (new)    │     │    (new)     │
    └───────────┘     └──────┬───────┘
                             │
                      ┌──────┴────────┐
                      │               │
                 ┌────▼────┐    ┌────▼────┐
                 │keyword_ │    │affinity_│
                 │libraries│    │ scores  │
                 │ (new)   │    │ (new)   │
                 └─────────┘    └─────────┘
```

---

## New Tables

### 1. sentiment_cache

**Purpose**: Cache sentiment analysis results to avoid re-computation

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS sentiment_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE,      -- Link to messages.id
    polarity INTEGER NOT NULL,               -- -1 (negative), 0 (neutral), 1 (positive)
    intensity REAL NOT NULL,                 -- -1.0 to 1.0
    embedding_vector BLOB,                   -- 384-dimensional vector (serialized as bytes)
    created_at INTEGER NOT NULL,             -- Cache timestamp
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sentiment_cache_message ON sentiment_cache(message_id);
```

**Fields**:
- `polarity`: Three-way classification (-1, 0, 1)
- `intensity`: Fine-grained sentiment score (-1.0 to 1.0)
- `embedding_vector`: Sentence embedding (384 floats stored as bytes, ~1.5KB per message)

**Validation Rules**:
- `polarity` must be in {-1, 0, 1}
- `intensity` must be in range [-1.0, 1.0]
- `embedding_vector` must be 384 * 4 bytes = 1536 bytes (if float32)

**Example**:
```python
{
    "message_id": 12345,
    "polarity": 1,
    "intensity": 0.87,
    "embedding_vector": b'\x00\x00\x80?' ... (1536 bytes)
}
```

---

### 2. speech_units

**Purpose**: Store merged speech units (consecutive messages from same sender < 5 min apart)

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS speech_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    message_ids TEXT NOT NULL,              -- Comma-separated message IDs
    sender TEXT NOT NULL,                   -- 'user' or 'other'
    first_message_timestamp INTEGER NOT NULL,
    last_message_timestamp INTEGER NOT NULL,
    message_count INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_speech_units_conversation ON speech_units(conversation_id, first_message_timestamp);
```

**Fields**:
- `message_ids`: Comma-separated list (e.g., "123,124,125")
- `sender`: Either 'user' (juitar/ting) or 'other' (contact)
- `message_count`: Number of messages in this speech unit

**Validation Rules**:
- `message_count` >= 1
- `first_message_timestamp` <= `last_message_timestamp`
- `sender` must be in {'user', 'other'}

**Example**:
```python
{
    "conversation_id": 42,
    "message_ids": "123,124,125",
    "sender": "user",
    "first_message_timestamp": 1704662400,
    "last_message_timestamp": 1704662690,
    "message_count": 3
}
```

---

### 3. interaction_pairs

**Purpose**: Store constructed interaction pairs (speech_unit_A → speech_unit_B)

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS interaction_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    from_speech_unit_id INTEGER NOT NULL,
    to_speech_unit_id INTEGER NOT NULL,
    time_gap INTEGER NOT NULL,              -- Seconds between speech units
    semantic_similarity REAL,               -- Cosine similarity (optional, computed later)
    from_polarity INTEGER NOT NULL,         -- -1, 0, 1
    to_polarity INTEGER NOT NULL,           -- -1, 0, 1
    from_intensity REAL NOT NULL,
    to_intensity REAL NOT NULL,
    is_negative_initiation INTEGER DEFAULT 0, -- 1 if 'from' polarity = -1
    is_empathetic_response INTEGER DEFAULT 0, -- 1 if 'to' polarity = 1 + soothing keywords
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (from_speech_unit_id) REFERENCES speech_units(id) ON DELETE CASCADE,
    FOREIGN KEY (to_speech_unit_id) REFERENCES speech_units(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_conversation ON interaction_pairs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_from_unit ON interaction_pairs(from_speech_unit_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_to_unit ON interaction_pairs(to_speech_unit_id);
```

**Fields**:
- `time_gap`: Seconds between speech units (used for timeliness calculation)
- `semantic_similarity`: Cosine similarity [0.0, 1.0], NULL if not computed
- `is_negative_initiation`: Flag for negative emotion collaborative resolution
- `is_empathetic_response`: Flag for negative emotion collaborative resolution

**Validation Rules**:
- `time_gap` >= 0
- `semantic_similarity` in [0.0, 1.0] if not NULL
- `from_polarity`, `to_polarity` in {-1, 0, 1}
- `from_intensity`, `to_intensity` in [-1.0, 1.0]

**Example**:
```python
{
    "conversation_id": 42,
    "from_speech_unit_id": 101,
    "to_speech_unit_id": 102,
    "time_gap": 180,
    "semantic_similarity": 0.75,
    "from_polarity": 1,
    "to_polarity": 1,
    "from_intensity": 0.82,
    "to_intensity": 0.91,
    "is_negative_initiation": 0,
    "is_empathetic_response": 0
}
```

---

### 4. affinity_config

**Purpose**: Store user configuration per conversation (weights, thresholds, keywords)

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS affinity_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL UNIQUE,
    config_version INTEGER DEFAULT 1,
    -- Dimension weights (must sum to 100)
    weight_emotional_resonance REAL DEFAULT 0.30,
    weight_chat_positivity REAL DEFAULT 0.30,
    weight_attitude_tendency REAL DEFAULT 0.20,
    weight_preference_compatibility REAL DEFAULT 0.20,
    -- Thresholds
    reply_timeliness_threshold INTEGER DEFAULT 3600,  -- Seconds (1 hour)
    topic_continuity_time_window INTEGER DEFAULT 604800,  -- Seconds (7 days)
    similarity_threshold_initiation REAL DEFAULT 0.40,
    sliding_window_size INTEGER DEFAULT 5,
    -- Keyword customization (JSON)
    custom_keywords_json TEXT,
    preference_keywords_json TEXT,            -- User-provided preference keywords
    -- Metadata
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_affinity_config_conversation ON affinity_config(conversation_id);
```

**Fields**:
- `weight_*`: Dimension weights (must sum to 1.0)
- `*_threshold`: User-configurable thresholds
- `custom_keywords_json`: JSON object with keyword overrides
- `preference_keywords_json`: JSON array of preference keywords

**Validation Rules**:
- Sum of weights = 1.0 (enforced at application level)
- `reply_timeliness_threshold` > 0
- `topic_continuity_time_window` >= 86400 (min 1 day)
- `similarity_threshold_initiation` in [0.0, 1.0]
- `sliding_window_size` >= 3

**Example**:
```python
{
    "conversation_id": 42,
    "weight_emotional_resonance": 0.30,
    "weight_chat_positivity": 0.30,
    "weight_attitude_tendency": 0.20,
    "weight_preference_compatibility": 0.20,
    "reply_timeliness_threshold": 3600,
    "topic_continuity_time_window": 604800,
    "similarity_threshold_initiation": 0.40,
    "sliding_window_size": 5,
    "custom_keywords_json": '{"positive_words": ["哈哈", "谢谢", "宝贝"]}',
    "preference_keywords_json": '["篮球", "电影", "旅行"]'
}
```

---

### 5. keyword_libraries

**Purpose**: Store global keyword libraries (default sets + user extensions)

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS keyword_libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,                 -- 'positive', 'negative', 'empathy', 'soothing', 'privacy', 'holiday'
    keyword TEXT NOT NULL,
    is_custom INTEGER DEFAULT 0,            -- 1 if user-added, 0 if default
    created_at INTEGER NOT NULL,
    UNIQUE(category, keyword)
);

CREATE INDEX IF NOT EXISTS idx_keyword_libraries_category ON keyword_libraries(category);
```

**Fields**:
- `category`: Keyword category (6 categories total)
- `keyword`: Single keyword or phrase
- `is_custom`: Distinguish default vs user-added

**Validation Rules**:
- `category` must be in {'positive', 'negative', 'empathy', 'soothing', 'privacy', 'holiday'}
- `keyword` must be non-empty
- (category, keyword) unique

**Example Data**:
```sql
INSERT INTO keyword_libraries (category, keyword, is_custom) VALUES
('positive', '哈哈', 0),
('positive', '谢谢', 0),
('empathy', '理解', 0),
('soothing', '别难过', 0),
('privacy', '秘密', 0),
('holiday', '新年快乐', 0),
-- User-added
('positive', '宝贝', 1);
```

---

### 6. affinity_scores

**Purpose**: Store computed dimension scores and overall affinity score

**Schema**:
```sql
CREATE TABLE IF NOT EXISTS affinity_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    analysis_version INTEGER DEFAULT 1,     -- Increment on re-analysis
    -- Overall score
    overall_score REAL NOT NULL,            -- 0.0 to 100.0
    -- Dimension scores
    emotional_resonance_score REAL NOT NULL,
    chat_positivity_score REAL NOT NULL,
    attitude_tendency_score REAL NOT NULL,
    preference_compatibility_score REAL NOT NULL,
    -- Sub-dimension scores (JSON for flexibility)
    sub_scores_json TEXT,                   -- Detailed breakdown
    -- Metadata
    message_count INTEGER NOT NULL,
    interaction_pair_count INTEGER NOT NULL,
    config_snapshot TEXT,                   -- Config hash or JSON
    analysis_duration_ms INTEGER,           -- Performance tracking
    created_at INTEGER NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_affinity_scores_conversation ON affinity_scores(conversation_id, created_at DESC);
```

**Fields**:
- `overall_score`: Weighted sum of 4 dimensions (0-100)
- `*_score`: Individual dimension scores (0-100)
- `sub_scores_json`: Detailed breakdown of all sub-dimensions
- `config_snapshot`: Hash of config used (detects when re-analysis needed)

**Validation Rules**:
- All scores in range [0.0, 100.0]
- `message_count` >= 0
- `interaction_pair_count` >= 0

**Example**:
```python
{
    "conversation_id": 42,
    "overall_score": 78.5,
    "emotional_resonance_score": 82.3,
    "chat_positivity_score": 75.1,
    "attitude_tendency_score": 68.9,
    "preference_compatibility_score": 85.0,
    "sub_scores_json": '{
        "emotional_resonance": {
            "bidirectional_positive_response": 85.0,
            "polarity_consistency": 78.5,
            "intensity_matching": 72.0,
            "empathy_recognition": 80.0,
            "negative_resolution": 90.0
        },
        ...
    }',
    "message_count": 1523,
    "interaction_pair_count": 425,
    "config_snapshot": "a1b2c3d4",
    "analysis_duration_ms": 45000
}
```

---

## Existing Tables (Extended)

### messages

**No schema changes**, but affinity analysis uses:
- `id`: Link to sentiment_cache
- `conversation_id`: Grouping
- `is_sender`: Distinguish user vs other
- `timestamp`: Time-based calculations
- `content`: Sentiment analysis input

### conversations

**No schema changes**, but affinity analysis uses:
- `id`: Link to affinity_config, affinity_scores
- `username`: Unique identifier
- `display_name`: UI display
- `message_count`: Cache invalidation check

---

## Data Flow

### 1. Import → Preprocess → Analyze

```
messages (raw)
  ↓
[sentiment analysis]
  ↓
sentiment_cache (polarity, intensity, embedding)
  ↓
[speech unit construction]
  ↓
speech_units
  ↓
[interaction pair construction]
  ↓
interaction_pairs (with sentiment data)
  ↓
[dimension calculation]
  ↓
affinity_scores
```

### 2. Configuration Change

```
user updates config (UI/API)
  ↓
affinity_config.updated_at = NOW()
  ↓
[invalidate cache]
  ↓
DELETE FROM affinity_scores WHERE conversation_id = ?
DELETE FROM interaction_pairs WHERE conversation_id = ?
DELETE FROM speech_units WHERE conversation_id = ?
  ↓
[re-analyze on next request]
```

---

## Storage Estimates

### Per Conversation (10,000 messages)

| Table | Records | Size per Record | Total Size |
|-------|---------|-----------------|------------|
| sentiment_cache | 10,000 | ~1.6 KB | ~16 MB |
| speech_units | ~4,000 | ~100 bytes | ~400 KB |
| interaction_pairs | ~2,000 | ~200 bytes | ~400 KB |
| affinity_config | 1 | ~500 bytes | ~500 bytes |
| affinity_scores | 1 | ~2 KB | ~2 KB |
| **Total** | | | **~16.8 MB** |

### Scaling

- 100 conversations × 10,000 messages = ~1.68 GB
- Acceptable for local SQLite database
- Recommend periodic cleanup for old conversations

---

## Migration Strategy

### Phase 1: Add Tables (Non-Breaking)

```sql
-- Run migration script
-- Create new tables without affecting existing data
```

### Phase 2: Lazy Analysis

- Analyze conversations on-demand (when user views affinity page)
- No background migration needed
- Gradual population of new tables

### Phase 3: Background Pre-computation (Optional)

- Background task to analyze recent conversations (last 30 days)
- Improves perceived performance

---

## Data Retention Policy

### Cache Invalidation

- **Affinity scores**: Invalidate on config change or new messages
- **Interaction pairs**: Rebuild on config change
- **Sentiment cache**: Keep indefinitely (only changes if message content changes)

### Cleanup Strategy

- Delete affinity_scores for conversations deleted > 30 days ago
- Archive interaction_pairs for conversations not viewed in > 90 days
- Keep sentiment_cache forever (reference data)

---

## State Transitions

### Conversation Analysis State

```
[NOT_ANALYZED]
  ↓ user requests analysis
[ANALYZING]
  ↓ analysis complete
[ANALYZED]
  ↓ config change OR new messages
[NEEDS_REANALYSIS]
  ↓ re-analysis triggered
[ANALYZED]
```

**Implementation**:
- Add `analysis_state` column to conversations (optional)
- Or derive from existence of affinity_scores record + config comparison

---

## Summary

**Total New Tables**: 6
**Total New Indices**: 12
**Estimated Storage**: ~16.8 MB per 10K-message conversation
**Migration Complexity**: Low (non-breaking additions)
**Performance Impact**: Minimal (indexed foreign keys)

**Next Steps**:
1. Review and approve data model
2. Generate migration scripts
3. Implement ORM models (if using SQLAlchemy)
4. Write unit tests for each table
5. Integration testing with analysis pipeline
