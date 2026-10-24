"""向量相似度单一实现：检索/索引/语义记忆三处余弦共用。

维度错配（换嵌入模型窗口期等）在写侧会被拒绝，读侧在此显式归零并
告警一次——静默按 min(len) 截断会算出「部分相似度」，检索质量无声劣化。
"""

import logging
import math

logger = logging.getLogger(__name__)

_dimension_warned = False


def cosine(a: list[float], b: list[float]) -> float:
    global _dimension_warned
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        if not _dimension_warned:
            logger.warning(
                "[RAG] 向量维度不一致(%d vs %d)，该对相似度按 0 处理",
                len(a),
                len(b),
            )
            _dimension_warned = True
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) ** 2 for x in a))
    norm_b = math.sqrt(sum(float(y) ** 2 for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)
