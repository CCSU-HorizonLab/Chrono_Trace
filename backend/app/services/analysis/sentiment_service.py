"""情感分析服务 - 使用SnowNLP进行情感分类和向量生成

功能:
- analyze_sentiment(): 分析单条消息情感
- analyze_batch(): 批量分析消息
- cache_sentiment_result(): 缓存分析结果
- get_sentiment_from_cache(): 读取缓存
- batch_cache_sentiments(): 批量写入缓存
"""

import pickle
import time
import os
from typing import Dict, Any, List, Optional
from ...db.connection import get_db

# 配置HuggingFace镜像站（解决SSL证书问题）
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'


class SentimentService:
    """情感分析服务

    使用SnowNLP进行情感分类:
    - polarity: -1 (负面), 0 (中性), 1 (正面)
    - intensity: -1.0 到 1.0 的连续值
    - embedding: 384维语义向量 (使用sentence-transformers)
    """

    def __init__(self):
        self.db = get_db()
        self._snownlp_model = None
        self._embedding_model = None
        self._embedding_cache = {}  # LRU缓存: {text: embedding}

    # ========== 模型加载 (延迟加载) ==========

    def _load_snownlp(self):
        """延迟加载SnowNLP模型"""
        if self._snownlp_model is None:
            try:
                from snownlp import SnowNLP
                self._snownlp_model = SnowNLP
                print("[情感服务] SnowNLP模型加载成功")
            except ImportError:
                print("[情感服务] 警告: SnowNLP未安装,请运行 pip install snownlp")
                raise

    def _load_embedding_model(self):
        """延迟加载sentence-transformers模型（自动检测GPU）"""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                import torch
                
                # 自动检测GPU
                if torch.cuda.is_available():
                    device = "cuda"
                    gpu_name = torch.cuda.get_device_name(0)
                    print(f"[情感服务] 检测到GPU: {gpu_name}")
                else:
                    device = "cpu"
                    print("[情感服务] 未检测到GPU，使用CPU模式")
                
                # 使用轻量级中文模型 (384维)
                model_name = "shibing624/text2vec-base-chinese"
                self._embedding_model = SentenceTransformer(model_name, device=device)
                print(f"[情感服务] 向量模型加载成功: {model_name} (设备: {device})")
            except ImportError:
                print("[情感服务] 警告: sentence-transformers未安装")
                print("请运行: pip install sentence-transformers")
                raise

    # ========== 情感分析 ==========

    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        分析单条文本的情感

        Args:
            text: 待分析的文本

        Returns:
            {
                "polarity": -1/0/1,  # 负面/中性/正面
                "intensity": -1.0到1.0,  # 情感强度
                "embedding": [0.1, 0.2, ...]  # 384维向量
            }
        """
        # 处理空字符串
        if not text or not text.strip():
            return {
                "polarity": 0,
                "intensity": 0.0,
                "embedding": [0.0] * 384
            }

        try:
            # 加载SnowNLP模型
            self._load_snownlp()

            # 情感分类
            snlp = self._snownlp_model(text)
            sentiment_score = snlp.sentiments  # 0到1之间的浮点数

            # 转换为三元分类 (-1/0/1)
            if sentiment_score >= 0.6:
                polarity = 1  # 正面
            elif sentiment_score <= 0.4:
                polarity = -1  # 负面
            else:
                polarity = 0  # 中性

            # 计算强度 (-1.0 到 1.0)
            # polarity=1时: intensity = sentiment_score (0.6~1.0)
            # polarity=-1时: intensity = -(1 - sentiment_score) (-1.0~-0.6)
            # polarity=0时: intensity = (sentiment_score - 0.5) * 2 (-0.2~0.2)
            if polarity == 1:
                intensity = sentiment_score
            elif polarity == -1:
                intensity = -(1.0 - sentiment_score)
            else:
                intensity = (sentiment_score - 0.5) * 2

            # 生成向量嵌入
            embedding = self._get_embedding(text)

            return {
                "polarity": polarity,
                "intensity": round(intensity, 4),
                "embedding": embedding
            }

        except Exception as e:
            print(f"[情感服务] 分析失败: {e}, 文本: '{text[:50]}...'")
            # 失败时回退到中性值
            return {
                "polarity": 0,
                "intensity": 0.0,
                "embedding": [0.0] * 384
            }

    def analyze_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """
        批量分析多条文本的情感

        Args:
            texts: 文本列表

        Returns:
            [
                {"polarity": -1/0/1, "intensity": -1.0到1.0, "embedding": [...]},
                ...
            ]
        """
        if not texts:
            return []

        results = []
        batch_size = 32

        # 分批处理
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            for text in batch:
                try:
                    result = self.analyze_sentiment(text)
                    results.append(result)
                except Exception as e:
                    print(f"[情感服务] 批处理失败: {e}")
                    # 失败时回退到中性值
                    results.append({
                        "polarity": 0,
                        "intensity": 0.0,
                        "embedding": [0.0] * 384
                    })

        return results

    # ========== 向量生成 ==========

    def _get_embedding(self, text: str) -> List[float]:
        """
        生成文本的384维向量嵌入

        Args:
            text: 输入文本

        Returns:
            384维浮点数向量
        """
        # 检查缓存
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        try:
            # 加载embedding模型
            self._load_embedding_model()

            # 生成向量（禁用进度条）
            embedding = self._embedding_model.encode(
                text,
                normalize_embeddings=True,  # 归一化为单位向量
                show_progress_bar=False  # 禁用进度条
            )

            # 转换为列表
            embedding_list = embedding.tolist()

            # 更新LRU缓存 (最多缓存10,000个)
            if len(self._embedding_cache) >= 10000:
                # 删除最旧的缓存项
                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]

            self._embedding_cache[text] = embedding_list

            return embedding_list

        except Exception as e:
            print(f"[情感服务] 向量生成失败: {e}")
            # 失败时返回零向量
            return [0.0] * 384

    # ========== 缓存操作 ==========

    def cache_sentiment_result(
        self,
        message_id: int,
        conversation_id: int,
        polarity: int,
        intensity: float,
        embedding: List[float]
    ):
        """
        缓存单条情感分析结果

        Args:
            message_id: 消息ID
            conversation_id: 会话ID
            polarity: 情感极性 (-1/0/1)
            intensity: 情感强度 (-1.0到1.0)
            embedding: 384维向量
        """
        try:
            # 序列化向量为字节
            embedding_bytes = pickle.dumps(embedding)

            self.db.execute("""
                INSERT OR REPLACE INTO sentiment_cache
                (message_id, polarity, intensity, embedding_vector, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                message_id,
                polarity,
                intensity,
                embedding_bytes,
                int(time.time())
            ))

            self.db.commit()

        except Exception as e:
            print(f"[情感服务] 缓存写入失败 (message_id={message_id}): {e}")

    def get_sentiment_from_cache(self, message_id: int) -> Optional[Dict[str, Any]]:
        """
        从缓存读取情感分析结果

        Args:
            message_id: 消息ID

        Returns:
            {
                "polarity": -1/0/1,
                "intensity": -1.0到1.0,
                "embedding": [...]
            }
            或 None (如果缓存不存在)
        """
        try:
            cursor = self.db.execute("""
                SELECT polarity, intensity, embedding_vector
                FROM sentiment_cache
                WHERE message_id = ?
            """, (message_id,))

            row = cursor.fetchone()

            if not row:
                return None

            # 反序列化向量
            embedding = pickle.loads(row[2])

            return {
                "polarity": row[0],
                "intensity": row[1],
                "embedding": embedding
            }

        except Exception as e:
            print(f"[情感服务] 缓存读取失败 (message_id={message_id}): {e}")
            return None

    def batch_cache_sentiments(self, results: List[Dict[str, Any]]):
        """
        批量写入情感分析缓存

        Args:
            results: [
                {
                    "message_id": 123,
                    "conversation_id": 1,
                    "polarity": 1,
                    "intensity": 0.8,
                    "embedding": [...]
                },
                ...
            ]
        """
        try:
            for result in results:
                # 序列化向量
                embedding_bytes = pickle.dumps(result["embedding"])

                self.db.execute("""
                    INSERT OR REPLACE INTO sentiment_cache
                    (message_id, polarity, intensity, embedding_vector, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    result["message_id"],
                    result["polarity"],
                    result["intensity"],
                    embedding_bytes,
                    int(time.time())
                ))

            self.db.commit()
            print(f"[情感服务] 批量缓存写入成功: {len(results)} 条")

        except Exception as e:
            print(f"[情感服务] 批量缓存写入失败: {e}")

    # ========== 缓存统计 ==========

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            {
                "total_cached": 1234,
                "memory_cache_size": 567,
                "positive_count": 800,
                "negative_count": 200,
                "neutral_count": 234
            }
        """
        try:
            # 统计数据库缓存
            cursor = self.db.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN polarity = 1 THEN 1 ELSE 0 END) as positive,
                    SUM(CASE WHEN polarity = -1 THEN 1 ELSE 0 END) as negative,
                    SUM(CASE WHEN polarity = 0 THEN 1 ELSE 0 END) as neutral
                FROM sentiment_cache
            """)

            row = cursor.fetchone()

            return {
                "total_cached": row[0],
                "memory_cache_size": len(self._embedding_cache),
                "positive_count": row[1],
                "negative_count": row[2],
                "neutral_count": row[3]
            }

        except Exception as e:
            print(f"[情感服务] 缓存统计失败: {e}")
            return {
                "total_cached": 0,
                "memory_cache_size": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0
            }

    def clear_memory_cache(self):
        """清空内存缓存"""
        self._embedding_cache.clear()
        print("[情感服务] 内存缓存已清空")
