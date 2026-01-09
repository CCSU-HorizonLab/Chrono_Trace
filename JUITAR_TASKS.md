# Juitar 的任务清单 - 好感度分析系统

**项目**: 002-affinity-analysis | **开发者**: juitar | **合作伙伴**: ting
**开始日期**: 2026-01-09 | **预计完成**: 4-5 周

---

## 📋 任务概览

**你的任务总数**: ~36 个任务
**核心职责**: 算法和后端服务实现
**并行策略**: 与 ting 同时工作，避免文件冲突

### 任务分工概览

| Phase | 内容 | 你的任务 | ting 的任务 |
|-------|------|----------|-------------|
| Week 1 | Phase 1-2 | ✅ 一起完成 | ✅ 一起完成 |
| Week 1-2 | Phase 3 | ✅ **US1 情感共振** (9 任务) | Phase 5-6 |
| Week 2-3 | Phase 7 | ✅ **Orchestrator** (3 任务) | Phase 4 |
| Week 3 | Phase 8 | ✅ **Backend API** (10 任务) | Phase 9 |
| Week 4-5 | Phase 10-11 | ✅ **测试和优化** (联合) | ✅ **测试和优化** (联合) |

---

## 🎯 Week 1: 基础 + 情感共振分析

### Phase 1: Setup (3 任务) - **与 ting 一起完成**

#### T001: 添加依赖
**文件**: `backend/requirements.txt`

**操作**:
```bash
# 添加以下依赖到 backend/requirements.txt
snownlp>=0.12.3
sentence-transformers>=2.2.0
scikit-learn>=1.3.0
torch>=2.0.0
pytest>=7.0.0
```

**上下文文档**:
- [research.md#L10-L50](specs/002-affinity-analysis/research.md#L10-L50) - 技术选型理由
- [quickstart.md#L20-L40](specs/002-affinity-analysis/quickstart.md#L20-L40) - 依赖说明

#### T002: 安装依赖
**操作**:
```bash
cd backend
pip install -r requirements.txt
```

#### T003: 下载模型
**操作**:
```bash
# 下载 sentence-transformers 模型到缓存
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
```

---

### Phase 2: Foundational (15 任务) - **与 ting 一起完成**

#### T004-T009: 数据库迁移脚本
**文件**:
- `backend/app/db/migrations/sentiment_cache.sql`
- `backend/app/db/migrations/speech_units.sql`
- `backend/app/db/migrations/interaction_pairs.sql`
- `backend/app/db/migrations/affinity_config.sql`
- `backend/app/db/migrations/keyword_libraries.sql`
- `backend/app/db/migrations/affinity_scores.sql`

**上下文文档**:
- [data-model.md#L50-L400](specs/002-affinity-analysis/data-model.md#L50-L400) - 6 个表的完整定义
- [data-model.md#L400-L450](specs/002-affinity-analysis/data-model.md#L400-L450) - 迁移策略

**每个迁移脚本格式**:
```sql
-- 文件: backend/app/db/migrations/sentiment_cache.sql
CREATE TABLE IF NOT EXISTS sentiment_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL UNIQUE,
    conversation_id INTEGER NOT NULL,
    polarity INTEGER NOT NULL CHECK(polarity IN (-1, 0, 1)),
    intensity REAL NOT NULL CHECK(intensity >= -1 AND intensity <= 1),
    embedding BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES messages(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_cache_message_id ON sentiment_cache(message_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_cache_conversation_id ON sentiment_cache(conversation_id);
```

#### T010: 运行迁移
**操作**:
```bash
cd backend
python -c "from app.db.connection import get_connection; conn = get_connection(); [exec(open(f'app/db/migrations/{f}').read()) for f in ['sentiment_cache.sql', 'speech_units.sql', 'interaction_pairs.sql', 'affinity_config.sql', 'keyword_libraries.sql', 'affinity_scores.sql']]"
```

#### T011-T012: 关键词库初始化
**文件**: `backend/scripts/populate_default_keywords.py`

**上下文文档**:
- [research.md#L100-L150](specs/002-affinity-analysis/research.md#L100-L150) - 关键词库设计
- [data-model.md#L250-L300](specs/002-affinity-analysis/data-model.md#L250-L300) - keyword_libraries 表结构

**代码示例**:
```python
# backend/scripts/populate_default_keywords.py
import sys
sys.path.insert(0, '.')

from app.db.connection import get_connection

def populate_default_keywords():
    """填充默认关键词库 (每个类别 10 个关键词)"""

    keywords = {
        'positive': ['开心', '快乐', '幸福', '喜欢', '爱', '棒', '好', '赞', '感谢', '期待'],
        'negative': ['难过', '伤心', '讨厌', '烦', '气', '失望', '痛苦', '糟糕', '恨', '怨'],
        'empathy': ['理解', '心疼', '抱歉', '没关系', '抱抱', '加油', '支持', '辛苦', '不容易', '懂'],
        'soothing': ['乖', '别难过', '会好的', '没事的', '放轻松', '慢慢来', '休息一下', '早点睡', '别担心', '有我'],
        'privacy': ['秘密', '只告诉你', '私密', '悄悄说', '别外传', '保密', '真心话', '坦诚', '信任', '分享'],
        'holiday': ['新年快乐', '春节快乐', '节日快乐', '假期愉快', '度假', '节日', '假期', '祝福', '庆祝', '礼物']
    }

    conn = get_connection()
    cursor = conn.cursor()

    for category, words in keywords.items():
        for word in words:
            cursor.execute('''
                INSERT OR IGNORE INTO keyword_libraries (category, keyword, is_default)
                VALUES (?, ?, 1)
            ''', (category, word))

    conn.commit()
    print(f"✅ 已插入 {sum(len(words) for words in keywords.values())} 个默认关键词")

if __name__ == '__main__':
    populate_default_keywords()
```

#### T013-T015: 测试数据准备 - **跳过** (ting 会做)

---

### Phase 3: User Story 1 - Emotional Resonance Analysis (9 任务) - **你单独负责**

#### 🔥 T016: 编写情感分析测试
**文件**: `backend/tests/test_sentiment_service.py`

**上下文文档**:
- [spec.md#L30-L50](specs/002-affinity-analysis/spec.md#L30-L50) - FR-001 到 FR-010 情感分析需求
- [research.md#L30-L80](specs/002-affinity-analysis/research.md#L30-L80) - SnowNLP 准确率目标

**测试要求**:
```python
# backend/tests/test_sentiment_service.py
import pytest
from app.services.analysis.sentiment_service import SentimentService

class TestSentimentService:
    """SnowNLP 情感分析准确率测试"""

    def test_positive_sentiment_classification(self):
        """测试: 正面情感文本应被识别为 polarity=1"""
        service = SentimentService()
        result = service.analyze_sentiment("今天真开心！")
        assert result['polarity'] == 1
        assert result['intensity'] > 0.5

    def test_negative_sentiment_classification(self):
        """测试: 负面情感文本应被识别为 polarity=-1"""
        service = SentimentService()
        result = service.analyze_sentiment("太难过了，心情不好。")
        assert result['polarity'] == -1
        assert result['intensity'] < 0

    def test_neutral_sentiment_classification(self):
        """测试: 中性情感文本应被识别为 polarity=0"""
        service = SentimentService()
        result = service.analyze_sentiment("明天开会。")
        assert result['polarity'] == 0

    def test_embedding_dimension(self):
        """测试: 句向量维度应为 384"""
        service = SentimentService()
        result = service.analyze_sentiment("测试文本")
        assert len(result['embedding']) == 384

    def test_batch_processing_performance(self):
        """测试: 批处理 32 条消息应在合理时间内完成"""
        import time
        service = SentimentService()
        messages = ["测试消息"] * 32
        start = time.time()
        results = service.analyze_batch(messages)
        duration = time.time() - start
        assert len(results) == 32
        assert duration < 5  # 应在 5 秒内完成
```

#### 🔥 T017: 编写交互对测试
**文件**: `backend/tests/test_interaction_pairs.py`

**上下文文档**:
- [spec.md#L50-L70](specs/002-affinity-analysis/spec.md#L50-L70) - 发言单位和交互对定义
- [research.md#L150-L200](specs/002-affinity-analysis/research.md#L150-L200) - 两阶段算法

#### 🔥 T018: 编写情感共振测试
**文件**: `backend/tests/test_emotional_resonance.py`

**上下文文档**:
- [spec.md#L70-L90](specs/002-affinity-analysis/spec.md#L70-L90) - FR-011 到 FR-020 情感共振需求

#### 🔥 T019: 实现 SentimentService 类
**文件**: `backend/app/services/analysis/sentiment_service.py`

**上下文文档**:
- [spec.md](specs/002-affinity-analysis/spec.md) - 完整功能规格
- [research.md#L30-L100](specs/002-affinity-analysis/research.md#L30-L100) - SnowNLP 集成方案
- [quickstart.md#L100-L200](specs/002-affinity-analysis/quickstart.md#L100-L200) - 完整代码示例
- [data-model.md#L50-L100](specs/002-affinity-analysis/data-model.md#L50-L100) - sentiment_cache 表

**完整实现要求**:
```python
# backend/app/services/analysis/sentiment_service.py
"""
SnowNLP 情感分析服务

功能:
- 情感极性分类 (-1: 负面, 0: 中性, 1: 正面)
- 情感强度计算 (-1 到 1)
- 句向量生成 (384 维)
- 批处理优化 (32 消息/批次)
- 结果缓存 (sentiment_cache 表)
"""

from typing import List, Dict, Optional
import pickle
import logging
from snownlp import SnowNLP
from sentence_transformers import SentenceTransformer
import numpy as np

from app.db.connection import get_connection

logger = logging.getLogger(__name__)

class SentimentService:
    """SnowNLP 情感分析服务"""

    def __init__(self):
        self._snownlp: Optional[SnowNLP] = None
        self._embedding_model: Optional[SentenceTransformer] = None
        self._cache = {}  # LRU 缓存: {message_text: sentiment_result}

    def _load_models(self):
        """懒加载模型 (首次使用时加载)"""
        if self._snownlp is None:
            logger.info("Loading SnowNLP model...")
            # SnowNLP 无需显式加载

        if self._embedding_model is None:
            logger.info("Loading sentence-transformers model...")
            self._embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            logger.info("Model loaded successfully")

    def analyze_sentiment(self, text: str) -> Dict:
        """
        分析单条消息的情感

        Args:
            text: 消息文本

        Returns:
            {
                'polarity': int,  # -1 (负面), 0 (中性), 1 (正面)
                'intensity': float,  # -1 到 1
                'embedding': List[float]  # 384 维向量
            }
        """
        try:
            self._load_models()

            # 检查缓存
            if text in self._cache:
                return self._cache[text]

            # SnowNLP 情感分析
            s = SnowNLP(text)
            sentiment_score = s.sentiments  # 0 到 1

            # 极性分类
            polarity = 1 if sentiment_score > 0.6 else (-1 if sentiment_score < 0.4 else 0)

            # 强度映射 (-1 到 1)
            intensity = (sentiment_score * 2) - 1

            # 句向量生成
            embedding = self._embedding_model.encode(text, show_progress_bar=False)

            result = {
                'polarity': polarity,
                'intensity': intensity,
                'embedding': embedding.tolist()  # 转为列表以便 JSON 序列化
            }

            # 缓存结果
            self._cache[text] = result

            return result

        except Exception as e:
            logger.error(f"Sentiment analysis failed for text: {text[:50]}, error: {e}")
            # 降级处理: 返回中性情感
            return {
                'polarity': 0,
                'intensity': 0.0,
                'embedding': [0.0] * 384
            }

    def analyze_batch(self, messages: List[str]) -> List[Dict]:
        """
        批量分析消息情感 (32 消息/批次)

        Args:
            messages: 消息文本列表

        Returns:
            情感分析结果列表
        """
        results = []
        for msg in messages:
            result = self.analyze_sentiment(msg)
            results.append(result)
        return results

    def cache_sentiment_result(self, message_id: int, conversation_id: int, sentiment_result: Dict):
        """缓存情感分析结果到数据库"""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            embedding_bytes = pickle.dumps(sentiment_result['embedding'])

            cursor.execute('''
                INSERT OR REPLACE INTO sentiment_cache
                (message_id, conversation_id, polarity, intensity, embedding)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                message_id,
                conversation_id,
                sentiment_result['polarity'],
                sentiment_result['intensity'],
                embedding_bytes
            ))

            conn.commit()
            logger.debug(f"Cached sentiment for message_id={message_id}")

        except Exception as e:
            logger.error(f"Failed to cache sentiment: {e}")

    def get_sentiment_from_cache(self, message_id: int) -> Optional[Dict]:
        """从数据库缓存读取情感分析结果"""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                SELECT polarity, intensity, embedding
                FROM sentiment_cache
                WHERE message_id = ?
            ''', (message_id,))

            row = cursor.fetchone()
            if row:
                polarity, intensity, embedding_bytes = row
                embedding = pickle.loads(embedding_bytes)
                return {
                    'polarity': polarity,
                    'intensity': intensity,
                    'embedding': embedding
                }

            return None

        except Exception as e:
            logger.error(f"Failed to read sentiment from cache: {e}")
            return None
```

**验收标准**:
- ✅ 所有测试用例通过 (T016)
- ✅ SnowNLP 准确率 > 85%
- ✅ 句向量维度 = 384
- ✅ 批处理 32 条消息 < 5 秒
- ✅ 降级处理正常 (返回中性情感)

#### 🔥 T020: 实现 InteractionPairBuilder 类
**文件**: `backend/app/services/analysis/interaction_pair_builder.py`

**上下文文档**:
- [spec.md#L50-L70](specs/002-affinity-analysis/spec.md#L50-L70) - 交互对定义
- [research.md#L150-L220](specs/002-affinity-analysis/research.md#L150-L220) - 两阶段算法
- [data-model.md#L100-L200](specs/002-affinity-analysis/data-model.md#L100-L200) - speech_units 和 interaction_pairs 表

**关键方法**:
```python
class InteractionPairBuilder:
    def build_speech_units(self, messages: List[Dict]) -> List[Dict]:
        """
        构建发言单位

        规则:
        1. 同一发送者的连续消息
        2. 时间间隔 < 5 分钟
        3. 合并内容 (用空格连接)

        Returns:
            [
                {
                    'id': int,
                    'sender_id': int,
                    'content': str,
                    'timestamp': datetime,
                    'message_ids': List[int]
                }
            ]
        """
        pass

    def build_interaction_pairs(self, speech_units: List[Dict]) -> List[Dict]:
        """
        构建交互对

        规则:
        1. 交替发言 (A -> B -> A ...)
        2. 忽略奇数个发言单位 (最后一个落单)
        3. 预计算语义相似度

        Returns:
            [
                {
                    'id': int,
                    'unit_a_id': int,
                    'unit_b_id': int,
                    'semantic_similarity': float  # 余弦相似度
                }
            ]
        """
        pass

    def calculate_semantic_similarity(self, text_a: str, text_b: str) -> float:
        """计算两个文本的语义相似度 (余弦相似度)"""
        pass
```

#### 🔥 T021: 实现 EmotionalResonanceService 类
**文件**: `backend/app/services/analysis/emotional_resonance_service.py`

**上下文文档**:
- [spec.md#L70-L100](specs/002-affinity-analysis/spec.md#L70-L100) - FR-011 到 FR-020
- [history_analyze.md#L50-L150](history_analyze.md#L50-L150) - 完整算法公式

**5 个子维度实现**:
```python
class EmotionalResonanceService:
    def calculate_bidirectional_positive_response(self, pairs: List[Dict]) -> float:
        """
        双向积极情感响应率 (20% 权重)

        计算:
        - 正面-正面交互对数量 / 总正面消息数

        Returns:
            0 到 100 分
        """
        pass

    def calculate_polarity_consistency(self, pairs: List[Dict]) -> float:
        """
        情感极性一致性 (15% 权重)

        计算:
        - (相同极性交互对比例) × (平均语义相似度)

        Returns:
            0 到 100 分
        """
        pass

    def calculate_intensity_matching(self, pairs: List[Dict]) -> float:
        """
        情绪强度匹配度 (10% 权重)

        计算:
        - 1 / (平均强度差 + 0.1)

        Returns:
            0 到 100 分
        """
        pass

    def calculate_empathy_recognition(self, messages: List[Dict], keywords: Dict) -> float:
        """
        共情意图识别率 (30% 权重)

        计算:
        - 包含共情关键词的消息数 / 总消息数

        Returns:
            0 到 100 分
        """
        pass

    def calculate_negative_resolution(self, pairs: List[Dict], keywords: Dict) -> float:
        """
        负面情绪协同化解率 (25% 权重)

        计算:
        - 共情回应的负面交互对数 / 负面发起的交互对数

        Returns:
            0 到 100 分
        """
        pass

    def calculate_overall_resonance(self, interaction_pairs: List[Dict], messages: List[Dict], keywords: Dict) -> Dict:
        """
        计算综合情感共振得分

        Returns:
            {
                'overall_score': float,  # 0 到 100
                'sub_scores': {
                    'bidirectional_positive_response': float,
                    'polarity_consistency': float,
                    'intensity_matching': float,
                    'empathy_recognition': float,
                    'negative_resolution': float
                },
                'interpretation': str  # 人类可读的解释
            }
        """
        pass
```

#### T022: 实现 KeywordLibraries 类 - **跳过** (ting 会做)

#### T023-T024: 数据库集成
**文件**: 在 T019 和 T020 中已包含

---

## 🎯 Week 2-3: Orchestrator + Backend API

### Phase 7: Orchestrator (3 任务) - **你负责**

#### 🔥 T037: 实现 AffinityAnalysisService 编排器
**文件**: `backend/app/services/analysis/affinity_analysis_service.py`

**上下文文档**:
- [spec.md#L100-L150](specs/002-affinity-analysis/spec.md#L100-L150) - FR-030 到 FR-035
- [contracts/bridge_api.yaml](specs/002-affinity-analysis/contracts/bridge_api.yaml) - API 契约

**关键方法**:
```python
class AffinityAnalysisService:
    def analyze(self, conversation_id: int, force_reanalyze: bool = False, config_overrides: Dict = None) -> str:
        """
        执行完整好感度分析

        流程:
        1. 检查缓存 (如果 force_reanalyze=False)
        2. 预处理: 确保情感缓存和交互对存在
        3. 计算 4 个维度得分
        4. 计算总分 (加权求和)
        5. 保存结果到 affinity_scores 表
        6. 生成 task_id 用于进度查询

        Returns:
            task_id (格式: "affinity_{conversation_id}_{timestamp}")
        """
        pass

    def get_scores(self, conversation_id: int) -> Optional[Dict]:
        """获取已缓存的分析结果"""
        pass

    def reanalyze(self, conversation_id: int) -> str:
        """强制重新分析 (清除缓存)"""
        pass
```

#### T038: 任务跟踪和进度报告
**文件**: 在 T037 中集成

#### T039: 解释文本生成
**文件**: 在 T037 中集成

---

### Phase 8: Backend API (10 任务) - **你负责**

#### 🔥 T040-T049: 实现 8 个 API 端点
**文件**: `backend/app/webview/bridge.py`

**上下文文档**:
- [contracts/bridge_api.yaml](specs/002-affinity-analysis/contracts/bridge_api.yaml) - 完整 API 规范
- [quickstart.md#L300-L500](specs/002-affinity-analysis/quickstart.md#L300-L500) - 集成示例

**端点清单**:
```python
# T040: POST /affinity/analyze
@app.route('/affinity/analyze', methods=['POST'])
def analyze_affinity():
    """
    请求体: {conversation_id, force_reanalyze, config_overrides}
    响应: {task_id, estimated_duration_ms}
    """
    pass

# T041: GET /affinity/progress/<task_id>
@app.route('/affinity/progress/<task_id>', methods=['GET'])
def get_affinity_progress(task_id):
    """
    响应: {
        status: 'pending'|'running'|'completed'|'failed',
        progress_percent: 0-100,
        current_step: str,
        error: str (如果失败),
        result: dict (如果完成)
    }
    """
    pass

# T042: GET /affinity/scores/<conversation_id>
@app.route('/affinity/scores/<conversation_id>', methods=['GET'])
def get_affinity_scores(conversation_id):
    pass

# T043: GET /affinity/config/<conversation_id>
@app.route('/affinity/config/<conversation_id>', methods=['GET'])
def get_affinity_config(conversation_id):
    pass

# T044: PUT /affinity/config/<conversation_id>
@app.route('/affinity/config/<conversation_id>', methods=['PUT'])
def update_affinity_config(conversation_id):
    pass

# T045: GET /affinity/keywords
@app.route('/affinity/keywords', methods=['GET'])
def get_keywords():
    pass

# T046: POST /affinity/keywords
@app.route('/affinity/keywords', methods=['POST'])
def add_keywords():
    pass

# T047: DELETE /affinity/keywords
@app.route('/affinity/keywords', methods=['DELETE'])
def delete_keywords():
    pass

# T048: GET /affinity/preference-keywords/<conversation_id>
@app.route('/affinity/preference-keywords/<conversation_id>', methods=['GET'])
def get_preference_keywords(conversation_id):
    pass

# T049: PUT /affinity/preference-keywords/<conversation_id>
@app.route('/affinity/preference-keywords/<conversation_id>', methods=['PUT'])
def update_preference_keywords(conversation_id):
    pass
```

---

## 🎯 Week 4-5: 测试和优化 (联合)

### Phase 10-11: Testing & Polish - **与 ting 一起完成**

#### T059-T066: 单元测试 - **你负责后端测试**
#### T067-T069: 集成和性能测试 - **联合**
#### T070: 边界情况测试 - **你负责**
#### T071-T073: 性能优化 - **你负责**
#### T074-T078: 文档和代码质量 - **联合**

---

## 📝 提交规范

每次完成任务后，提交代码：

```bash
git add .
git commit -m "[juitar] 实现SentimentService类

- 集成SnowNLP和sentence-transformers
- analyze_sentiment()方法返回极性、强度、句向量
- 批处理优化 (32消息/批次)
- 数据库缓存集成

任务: T019
测试: 通过所有test_sentiment_service.py测试用例"
git push
```

---

## 🔗 快速参考

### 关键文档链接

| 文档 | 用途 |
|------|------|
| [tasks.md](specs/002-affinity-analysis/tasks.md) | 完整 84 任务清单 |
| [spec.md](specs/002-affinity-analysis/spec.md) | 功能规格 (40 个需求) |
| [research.md](specs/002-affinity-analysis/research.md) | 技术选型和算法 |
| [data-model.md](specs/002-affinity-analysis/data-model.md) | 数据库设计 |
| [quickstart.md](specs/002-affinity-analysis/quickstart.md) | 代码示例 |
| [contracts/bridge_api.yaml](specs/002-affinity-analysis/contracts/bridge_api.yaml) | API 规范 |
| [history_analyze.md](history_analyze.md) | 原始算法公式 |
| [SIMPLE_WORKFLOW.md](SIMPLE_WORKFLOW.md) | 协作流程 |

### 代码质量检查清单

每次完成任务前，确保：

- ✅ 遵循项目代码风格 (Python 3.8+)
- ✅ 所有方法有文档字符串
- ✅ 错误处理完善 (try-except)
- ✅ 日志记录完整 (logger.debug/info/error)
- ✅ 单元测试通过 (pytest)
- ✅ 性能满足要求 (见 research.md 性能目标)
- ✅ 边界情况处理 (空输入、None 值)

---

**最后更新**: 2026-01-09 | **状态**: ✅ 准备开始实施