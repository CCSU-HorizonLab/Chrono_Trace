# Quickstart: Conversation Affinity Analysis System

**Feature**: 002-affinity-analysis
**Developers**: juitar & ting
**Last Updated**: 2026-01-08

## Prerequisites

### System Requirements
- Python 3.8+
- Node.js 16+
- 8GB RAM minimum (16GB recommended for 100K message analysis)
- 2GB free disk space for dependencies

### Existing Dependencies
Already installed in Chrono Trace:
```bash
pywebview>=4.0.0
pycryptodome>=3.20.0
jieba>=0.42.1
numpy>=1.24.0
```

### New Dependencies to Add
Add to `requirements.txt`:
```txt
# Sentiment analysis
snownlp>=0.12.3

# Sentence embeddings
sentence-transformers>=2.2.0
torch>=2.0.0  # Required by sentence-transformers

# Similarity calculation
scikit-learn>=1.3.0

# Testing
pytest>=7.0.0
pytest-asyncio>=0.21.0
```

Install dependencies:
```bash
cd backend
pip install -r requirements.txt
```

---

## Database Setup

### 1. Run Migration Script

Create `backend/migrate_affinity_tables.py`:
```python
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'chrono_trace.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create tables in order (respecting foreign keys)
    tables = [
        # From data-model.md
        'sentiment_cache',
        'speech_units',
        'interaction_pairs',
        'affinity_config',
        'keyword_libraries',
        'affinity_scores'
    ]

    for table in tables:
        sql_path = os.path.join(os.path.dirname(__file__), 'db', 'migrations', f'{table}.sql')
        if os.path.exists(sql_path):
            with open(sql_path, 'r', encoding='utf-8') as f:
                cursor.executescript(f.read())
            print(f"✅ Created table: {table}")

    conn.commit()
    conn.close()
    print("✅ Migration complete")

if __name__ == '__main__':
    migrate()
```

Run migration:
```bash
cd backend
python migrate_affinity_tables.py
```

### 2. Populate Default Keywords

```python
# backend/scripts/populate_default_keywords.py
DEFAULT_KEYWORDS = {
    'positive_words': ["哈哈", "谢谢", "谢谢你", "太好了", "棒", "优秀", "喜欢你", "爱你", "想你", "期待"],
    'negative_words': ["讨厌", "恨", "烦", "糟糕", "不好", "差", "失望", "难过", "生气"],
    'empathy_words': ["理解", "明白", "感同身受", "懂你", "心疼", "担心"],
    'soothing_words': ["别难过", "没事的", "会好的", "加油", "支持你", "陪着你"],
    'privacy_keywords': ["秘密", "私密", "只告诉你", "别说出去", "保密"],
    'holiday_greetings': ["新年快乐", "春节快乐", "节日快乐", "元宵节快乐", "中秋节快乐"]
}

def populate_keywords():
    import sqlite3
    import os
    from datetime import datetime

    DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'chrono_trace.db')
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    timestamp = int(datetime.now().timestamp())

    for category, keywords in DEFAULT_KEYWORDS.items():
        for keyword in keywords:
            cursor.execute('''
                INSERT OR IGNORE INTO keyword_libraries (category, keyword, is_custom, created_at)
                VALUES (?, ?, 0, ?)
            ''', (category, keyword, timestamp))

    conn.commit()
    conn.close()
    print("✅ Default keywords populated")

if __name__ == '__main__':
    populate_keywords()
```

Run:
```bash
python backend/scripts/populate_default_keywords.py
```

---

## Project Structure

### Backend Files to Create

```
backend/
  app/
    services/
      analysis/
        sentiment_service.py           # NEW - SnowNLP integration
        interaction_pair_builder.py    # NEW - Speech unit + pair construction
        emotional_resonance_service.py # NEW - Dimension 1
        chat_positivity_service.py     # NEW - Dimension 2
        attitude_tendency_service.py   # NEW - Dimension 3
        preference_compatibility_service.py # NEW - Dimension 4
        affinity_analysis_service.py   # NEW - Main orchestrator
        affinity_config.py             # NEW - Config management
        keyword_libraries.py           # NEW - Keyword CRUD
    webview/
      bridge.py                        # UPDATE - Add affinity endpoints
  db/
    migrations/
      sentiment_cache.sql              # NEW
      speech_units.sql                 # NEW
      interaction_pairs.sql            # NEW
      affinity_config.sql              # NEW
      keyword_libraries.sql            # NEW
      affinity_scores.sql              # NEW
  scripts/
    populate_default_keywords.py       # NEW
  tests/
    test_sentiment_service.py          # NEW
    test_interaction_pairs.py          # NEW
    test_affinity_analysis.py          # NEW
```

### Frontend Files to Create

```
frontend/
  src/
    views/
      AffinityView.vue                 # NEW - Main affinity analysis UI
    components/
      affinity/
        AffinityScoreCard.vue          # NEW - Score display card
        DimensionRadar.vue             # NEW - Radar chart for 4 dimensions
        ConfigPanel.vue                # NEW - Configuration form
        KeywordEditor.vue              # NEW - Keyword management
    api/
      affinity.ts                       # NEW - API client
```

---

## Development Workflow

### 1. juitar's First Task: Sentiment Analysis

**Branch**: `juitar-sentiment-analysis`

Create `backend/app/services/analysis/sentiment_service.py`:
```python
import logging
from snownlp import SnowNLP
from sentence_transformers import SentenceTransformer
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

class SentimentService:
    def __init__(self):
        # Lazy load models
        self._snownlp = None
        self._embedding_model = None

    @property
    def snownlp(self):
        if self._snownlp is None:
            logger.info("Loading SnowNLP...")
            self._snownlp = SnowNLP('')
        return self._snownlp

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            logger.info("Loading sentence-transformers model...")
            self._embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        return self._embedding_model

    def analyze_sentiment(self, text: str) -> Dict:
        """
        Analyze sentiment for a single message.

        Returns:
            {
                'polarity': -1 | 0 | 1,
                'intensity': float (-1.0 to 1.0),
                'embedding': numpy.ndarray (384-dim)
            }
        """
        try:
            # SnowNLP sentiment (0-1 range)
            s = SnowNLP(text)
            sentiment_score = s.sentiments

            # Map to polarity (-1, 0, 1)
            if sentiment_score > 0.6:
                polarity = 1
            elif sentiment_score < 0.4:
                polarity = -1
            else:
                polarity = 0

            # Map to intensity (-1.0 to 1.0)
            intensity = (sentiment_score * 2) - 1

            # Generate embedding
            embedding = self.embedding_model.encode(text)

            return {
                'polarity': polarity,
                'intensity': intensity,
                'embedding': embedding
            }

        except Exception as e:
            logger.error(f"Sentiment analysis failed for text: {text[:50]}..., error: {e}")
            # Fallback to neutral
            return {
                'polarity': 0,
                'intensity': 0.0,
                'embedding': np.zeros(384, dtype=np.float32)
            }

    def analyze_batch(self, texts: List[str]) -> List[Dict]:
        """
        Analyze sentiment for multiple messages (batch processing for performance).

        Args:
            texts: List of message contents

        Returns:
            List of sentiment analysis results
        """
        results = []

        # Batch embeddings
        embeddings = self.embedding_model.encode(texts, batch_size=32)

        for i, text in enumerate(texts):
            try:
                s = SnowNLP(text)
                sentiment_score = s.sentiments

                if sentiment_score > 0.6:
                    polarity = 1
                elif sentiment_score < 0.4:
                    polarity = -1
                else:
                    polarity = 0

                intensity = (sentiment_score * 2) - 1

                results.append({
                    'polarity': polarity,
                    'intensity': intensity,
                    'embedding': embeddings[i]
                })

            except Exception as e:
                logger.error(f"Batch sentiment analysis failed: {e}")
                results.append({
                    'polarity': 0,
                    'intensity': 0.0,
                    'embedding': np.zeros(384, dtype=np.float32)
                })

        return results
```

**Test**:
```python
# backend/tests/test_sentiment_service.py
import pytest
from app.services.analysis.sentiment_service import SentimentService

def test_positive_sentiment():
    service = SentimentService()
    result = service.analyze_sentiment("今天天气真好,太开心了!")
    assert result['polarity'] == 1
    assert result['intensity'] > 0.5
    assert result['embedding'].shape == (384,)

def test_negative_sentiment():
    service = SentimentService()
    result = service.analyze_sentiment("今天真倒霉,烦死了")
    assert result['polarity'] == -1
    assert result['intensity'] < 0

def test_batch_analysis():
    service = SentimentService()
    texts = ["哈哈", "谢谢", "难过"]
    results = service.analyze_batch(texts)
    assert len(results) == 3
    assert all(r['embedding'].shape == (384,) for r in results)
```

Run tests:
```bash
cd backend
pytest tests/test_sentiment_service.py -v
```

---

### 2. ting's First Task: Keyword Libraries

**Branch**: `ting-keyword-libraries`

Create `backend/app/services/analysis/keyword_libraries.py`:
```python
import sqlite3
import json
import logging
from typing import Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

class KeywordLibraries:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_keywords(self, category: str) -> List[str]:
        """Get all keywords for a category."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT keyword FROM keyword_libraries
            WHERE category = ?
            ORDER BY keyword
        ''', (category,))

        keywords = [row[0] for row in cursor.fetchall()]
        conn.close()

        return keywords

    def add_keywords(self, category: str, keywords: List[str]) -> int:
        """Add custom keywords to a category."""
        from datetime import datetime

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        timestamp = int(datetime.now().timestamp())
        added_count = 0

        for keyword in keywords:
            try:
                cursor.execute('''
                    INSERT INTO keyword_libraries (category, keyword, is_custom, created_at)
                    VALUES (?, ?, 1, ?)
                ''', (category, keyword, timestamp))
                added_count += 1
            except sqlite3.IntegrityError:
                # Keyword already exists, skip
                pass

        conn.commit()
        conn.close()

        logger.info(f"Added {added_count} keywords to {category}")
        return added_count

    def remove_keywords(self, category: str, keywords: List[str]) -> int:
        """Remove keywords from a category."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        placeholders = ','.join(['?' for _ in keywords])
        cursor.execute(f'''
            DELETE FROM keyword_libraries
            WHERE category = ? AND keyword IN ({placeholders})
        ''', (category, *keywords))

        removed_count = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Removed {removed_count} keywords from {category}")
        return removed_count

    def get_all_keywords(self) -> Dict[str, List[str]]:
        """Get all keywords grouped by category."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT category, keyword FROM keyword_libraries
            ORDER BY category, keyword
        ''')

        result = {
            'positive_words': [],
            'negative_words': [],
            'empathy_words': [],
            'soothing_words': [],
            'privacy_keywords': [],
            'holiday_greetings': []
        }

        for category, keyword in cursor.fetchall():
            if category in result:
                result[category].append(keyword)

        conn.close()
        return result

    def check_keywords_in_text(self, text: str, keywords: List[str]) -> bool:
        """Check if any keyword appears in text."""
        for keyword in keywords:
            if keyword in text:
                return True
        return False
```

---

## API Integration

### Update Bridge API

Edit `backend/app/webview/bridge.py`:
```python
# Add imports
from app.services.analysis.sentiment_service import SentimentService
from app.services.analysis.affinity_analysis_service import AffinityAnalysisService
from app.services.analysis.keyword_libraries import KeywordLibraries

# Initialize services
sentiment_service = SentimentService()
affinity_service = AffinityAnalysisService()
keyword_service = KeywordLibraries(DB_PATH)

# Add endpoints
@bridge.expose
def analyze_affinity(conversation_id: int, force_reanalyze: bool = False, config_overrides: dict = None):
    """Trigger affinity analysis for a conversation."""
    return affinity_service.analyze(conversation_id, force_reanalyze, config_overrides)

@bridge.expose
def get_affinity_scores(conversation_id: int):
    """Get cached affinity scores."""
    return affinity_service.get_scores(conversation_id)

@bridge.expose
def get_affinity_config(conversation_id: int):
    """Get affinity configuration."""
    return affinity_service.get_config(conversation_id)

@bridge.expose
def update_affinity_config(conversation_id: int, config: dict):
    """Update affinity configuration."""
    return affinity_service.update_config(conversation_id, config)

@bridge.expose
def get_keywords():
    """Get all keyword libraries."""
    return keyword_service.get_all_keywords()

@bridge.expose
def add_keywords(category: str, keywords: list):
    """Add custom keywords."""
    return {
        'success': True,
        'added_count': keyword_service.add_keywords(category, keywords)
    }

@bridge.expose
def remove_keywords(category: str, keywords: list):
    """Remove keywords."""
    return {
        'success': True,
        'removed_count': keyword_service.remove_keywords(category, keywords)
    }
```

---

## Frontend Integration

### Create Affinity View

Create `frontend/src/views/AffinityView.vue`:
```vue
<template>
  <div class="affinity-view">
    <h2>好感度分析</h2>

    <!-- Score Display -->
    <div class="score-overview" v-if="scores">
      <div class="overall-score">
        <h3>总体好感度</h3>
        <div class="score-value">{{ scores.overall_score.toFixed(1) }}</div>
        <p class="interpretation">{{ scores.interpretation.overall }}</p>
      </div>

      <DimensionRadar :scores="scores.dimension_scores" />
    </div>

    <!-- Analysis Button -->
    <button
      v-if="!scores && !analyzing"
      @click="startAnalysis"
      class="btn-primary"
    >
      开始分析
    </button>

    <!-- Progress -->
    <div v-if="analyzing" class="progress">
      <p>分析中... {{ progress }}%</p>
      <div class="progress-bar">
        <div class="fill" :style="{width: progress + '%'}"></div>
      </div>
    </div>

    <!-- Configuration -->
    <ConfigPanel
      :config="config"
      @update="updateConfig"
    />

    <!-- Keyword Editor -->
    <KeywordEditor
      :keywords="keywords"
      @add="addKeywords"
      @remove="removeKeywords"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { analyzeAffinity, getAffinityScores, getAffinityConfig } from '@/api/affinity';
import DimensionRadar from '@/components/affinity/DimensionRadar.vue';
import ConfigPanel from '@/components/affinity/ConfigPanel.vue';
import KeywordEditor from '@/components/affinity/KeywordEditor.vue';

const route = useRoute();
const conversationId = parseInt(route.params.id);

const scores = ref(null);
const config = ref(null);
const keywords = ref(null);
const analyzing = ref(false);
const progress = ref(0);

onMounted(async () => {
  // Load existing scores
  const result = await getAffinityScores(conversationId);
  if (result.success) {
    scores.value = result.data;
  }

  // Load config
  const configResult = await getAffinityConfig(conversationId);
  if (configResult.success) {
    config.value = configResult.data;
  }
});

async function startAnalysis() {
  analyzing.value = true;
  progress.value = 0;

  const result = await analyzeAffinity(conversationId);
  if (result.success) {
    const taskId = result.task_id;

    // Poll progress
    const interval = setInterval(async () => {
      const progressResult = await getAffinityProgress(taskId);
      progress.value = progressResult.progress_percent;

      if (progressResult.status === 'completed') {
        clearInterval(interval);
        scores.value = progressResult.result;
        analyzing.value = false;
      } else if (progressResult.status === 'failed') {
        clearInterval(interval);
        analyzing.value = false;
        alert('分析失败: ' + progressResult.error);
      }
    }, 1000);
  }
}

async function updateConfig(newConfig) {
  const result = await updateAffinityConfig(conversationId, newConfig);
  if (result.success) {
    config.value = result.data;
  }
}

async function addKeywords(category, keywords) {
  await addKeywordsAPI(category, keywords);
  // Reload keywords
  keywords.value = await getKeywordsAPI();
}
</script>
```

---

## Running the Application

### Development Mode

1. **Start Backend**:
```bash
cd backend
python app_dev.py
```

2. **Start Frontend** (separate terminal):
```bash
cd frontend
npm run dev
```

3. **Access Application**:
```
http://localhost:5173
```

### Testing Analysis

1. Navigate to a conversation
2. Click "好感度分析" tab
3. Click "开始分析" button
4. Wait for analysis to complete (30s - 5min depending on message count)
5. View scores and interpretations

---

## Troubleshooting

### Issue: Model Loading Slow

**Solution**: Pre-load models on startup
```python
# In app_dev.py
from app.services.analysis.sentiment_service import SentimentService

# Warm up models
print("Warming up sentiment analysis models...")
sentiment_service = SentimentService()
_ = sentiment_service.snownlp
_ = sentiment_service.embedding_model
print("✅ Models loaded")
```

### Issue: Out of Memory

**Solution**: Reduce batch size
```python
# In sentiment_service.py
embeddings = self.embedding_model.encode(texts, batch_size=16)  # Reduce from 32
```

### Issue: Analysis Too Slow

**Solution**: Enable caching
```python
# Check cache before analyzing
cached = get_sentiment_from_cache(message_id)
if cached:
    return cached
```

---

## Next Steps

1. ✅ Install dependencies
2. ✅ Run database migration
3. ✅ Populate default keywords
4. ⬜ Implement sentiment service (juitar)
5. ⬜ Implement interaction pair builder (juitar)
6. ⬜ Implement keyword libraries (ting)
7. ⬜ Implement affinity analysis orchestrator (joint)
8. ⬜ Implement frontend UI (ting)
9. ⬜ Integration testing
10. ⬜ Performance optimization

**Estimated Timeline**: 5 weeks (see COLLABORATION_GUIDE.md)

---

**Last Updated**: 2026-01-08
**Status**: Ready for development
