"""情感服务单元测试

测试SnowNLP情感分类准确率 (>85%)
测试强度映射 (-1到1)
测试向量生成 (384维)
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))


class TestSentimentService:
    """情感服务测试套件"""

    @pytest.fixture
    def service(self):
        """创建情感服务实例"""
        from app.services.analysis.sentiment_service import SentimentService
        return SentimentService()

    # ========== 测试数据集 ==========

    # 积极情感测试样本 (共20条)
    POSITIVE_SAMPLES = [
        "今天天气真好！",
        "太棒了，终于完成了！",
        "非常喜欢这个方案",
        "开心的一天",
        "感谢你的帮助",
        "做得很好",
        "这个想法很棒",
        "真的很不错",
        "非常满意",
        "太赞了",
        "心情很好",
        "非常喜欢",
        "很有意思",
        "太好了",
        "很棒",
        "优秀",
        "完美",
        "精彩",
        "值得称赞",
        "充满希望"
    ]

    # 消极情感测试样本 (共20条)
    NEGATIVE_SAMPLES = [
        "今天天气真糟糕",
        "太差了，完全不行",
        "非常讨厌这个方案",
        "难过的一天",
        "很失望",
        "做得不好",
        "这个想法很糟",
        "真的很差劲",
        "非常不满",
        "太烂了",
        "心情很差",
        "非常讨厌",
        "很无聊",
        "太坏了",
        "很糟",
        "低劣",
        "糟糕透顶",
        "失败",
        "令人失望",
        "毫无希望"
    ]

    # 中性情感测试样本 (共10条)
    NEUTRAL_SAMPLES = [
        "今天天气一般",
        "还行吧",
        "这个方案可以考虑",
        "普通的一天",
        "就这样",
        "知道了",
        "这个想法可以",
        "还好",
        "还可以",
        "没什么特别的"
    ]

    # ========== 情感分类准确率测试 ==========

    def test_positive_sentiment_accuracy(self, service):
        """测试积极情感分类准确率 (>85%)"""
        correct = 0
        total = len(self.POSITIVE_SAMPLES)

        for text in self.POSITIVE_SAMPLES:
            result = service.analyze_sentiment(text)
            # 积极情感应该返回 polarity=1
            if result["polarity"] == 1:
                correct += 1

        accuracy = correct / total
        print(f"\n积极情感分类准确率: {accuracy * 100:.1f}% ({correct}/{total})")

        assert accuracy >= 0.85, f"积极情感分类准确率不足85%: {accuracy*100:.1f}%"

    def test_negative_sentiment_accuracy(self, service):
        """测试消极情感分类准确率 (>85%)"""
        correct = 0
        total = len(self.NEGATIVE_SAMPLES)

        for text in self.NEGATIVE_SAMPLES:
            result = service.analyze_sentiment(text)
            # 消极情感应该返回 polarity=-1
            if result["polarity"] == -1:
                correct += 1

        accuracy = correct / total
        print(f"\n消极情感分类准确率: {accuracy * 100:.1f}% ({correct}/{total})")

        assert accuracy >= 0.85, f"消极情感分类准确率不足85%: {accuracy*100:.1f}%"

    def test_neutral_sentiment_accuracy(self, service):
        """测试中性情感分类准确率 (>85%)"""
        correct = 0
        total = len(self.NEUTRAL_SAMPLES)

        for text in self.NEUTRAL_SAMPLES:
            result = service.analyze_sentiment(text)
            # 中性情感应该返回 polarity=0
            if result["polarity"] == 0:
                correct += 1

        accuracy = correct / total
        print(f"\n中性情感分类准确率: {accuracy * 100:.1f}% ({correct}/{total})")

        assert accuracy >= 0.85, f"中性情感分类准确率不足85%: {accuracy*100:.1f}%"

    # ========== 强度映射测试 ==========

    def test_intensity_range(self, service):
        """测试强度值在 -1 到 1 范围内"""
        test_cases = self.POSITIVE_SAMPLES + self.NEGATIVE_SAMPLES + self.NEUTRAL_SAMPLES

        for text in test_cases:
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            assert -1.0 <= intensity <= 1.0, \
                f"强度值超出范围 [-1, 1]: {intensity} (文本: '{text}')"

    def test_positive_intensity(self, service):
        """测试积极情感的强度为正值"""
        for text in self.POSITIVE_SAMPLES[:5]:  # 测试前5条
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            assert intensity > 0, \
                f"积极情感强度应该为正: {intensity} (文本: '{text}')"

    def test_negative_intensity(self, service):
        """测试消极情感的强度为负值"""
        for text in self.NEGATIVE_SAMPLES[:5]:  # 测试前5条
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            assert intensity < 0, \
                f"消极情感强度应该为负: {intensity} (文本: '{text}')"

    def test_neutral_intensity(self, service):
        """测试中性情感的强度接近0"""
        for text in self.NEUTRAL_SAMPLES[:5]:  # 测试前5条
            result = service.analyze_sentiment(text)
            intensity = result["intensity"]

            # 允许中性情感有轻微波动，但应该接近0
            assert -0.3 <= intensity <= 0.3, \
                f"中性情感强度应该接近0: {intensity} (文本: '{text}')"

    # ========== 向量生成测试 ==========

    def test_embedding_dimension(self, service):
        """测试向量维度为384"""
        text = "这是一个测试句子"
        result = service.analyze_sentiment(text)
        embedding = result["embedding"]

        assert len(embedding) == 384, \
            f"向量维度应该为384, 实际为: {len(embedding)}"

    def test_embedding_type(self, service):
        """测试向量为浮点数列表"""
        text = "这是一个测试句子"
        result = service.analyze_sentiment(text)
        embedding = result["embedding"]

        assert isinstance(embedding, list), "向量应该为列表类型"

        for i, val in enumerate(embedding):
            assert isinstance(val, float), \
                f"向量元素应该为浮点数: 索引{i}, 类型{type(val)}"

    def test_embedding_normalization(self, service):
        """测试向量归一化 (单位向量)"""
        import math

        text = "这是一个测试句子"
        result = service.analyze_sentiment(text)
        embedding = result["embedding"]

        # 计算L2范数
        norm = math.sqrt(sum(x * x for x in embedding))

        # 归一化向量的范数应该接近1
        assert 0.99 <= norm <= 1.01, \
            f"向量未归一化, 范数为: {norm}"

    def test_embedding_consistency(self, service):
        """测试相同文本生成相同向量"""
        text = "这是一条测试消息"

        result1 = service.analyze_sentiment(text)
        result2 = service.analyze_sentiment(text)

        embedding1 = result1["embedding"]
        embedding2 = result2["embedding"]

        # 比较每个元素
        for i, (v1, v2) in enumerate(zip(embedding1, embedding2)):
            assert abs(v1 - v2) < 1e-6, \
                f"向量不一致: 索引{i}, 值1={v1}, 值2={v2}"

    # ========== 批处理测试 ==========

    def test_batch_processing(self, service):
        """测试批处理功能"""
        texts = [
            "今天天气真好",
            "非常糟糕",
            "还好吧"
        ]

        results = service.analyze_batch(texts)

        assert len(results) == len(texts), \
            f"批处理结果数量不匹配: {len(results)} vs {len(texts)}"

        # 验证每个结果都有必需的字段
        for result in results:
            assert "polarity" in result
            assert "intensity" in result
            assert "embedding" in result
            assert len(result["embedding"]) == 384

    def test_batch_empty_list(self, service):
        """测试空列表批处理"""
        results = service.analyze_batch([])

        assert results == [], "空列表应该返回空结果"

    def test_batch_fallback_to_neutral(self, service):
        """测试批处理失败时回退到中性值"""
        # 使用空字符串和正常文本混合
        texts = [
            "正常文本",
            "",  # 空字符串应该回退到中性
            "另一条正常文本"
        ]

        results = service.analyze_batch(texts)

        assert len(results) == 3

        # 空字符串的结果应该是中性
        assert results[1]["polarity"] == 0
        assert results[1]["intensity"] == 0.0
        # embedding 应该是零向量
        assert all(v == 0.0 for v in results[1]["embedding"])

    # ========== 缓存测试 ==========

    def test_cache_sentiment_result(self, service):
        """测试写入情感分析缓存"""
        message_id = 99999  # 测试用的消息ID
        text = "测试缓存功能"

        result = service.analyze_sentiment(text)

        # 写入缓存
        service.cache_sentiment_result(
            message_id=message_id,
            conversation_id=1,
            **result
        )

        # 读取缓存
        cached = service.get_sentiment_from_cache(message_id)

        assert cached is not None, "缓存读取失败"
        assert cached["polarity"] == result["polarity"]
        assert cached["intensity"] == result["intensity"]
        assert cached["embedding"] == result["embedding"]

    def test_batch_cache_sentiments(self, service):
        """测试批量写入缓存"""
        results = [
            {
                "message_id": 10001,
                "conversation_id": 1,
                "polarity": 1,
                "intensity": 0.8,
                "embedding": [0.1] * 384
            },
            {
                "message_id": 10002,
                "conversation_id": 1,
                "polarity": -1,
                "intensity": -0.6,
                "embedding": [0.2] * 384
            }
        ]

        # 批量写入
        service.batch_cache_sentiments(results)

        # 验证第一条缓存
        cached1 = service.get_sentiment_from_cache(10001)
        assert cached1 is not None
        assert cached1["polarity"] == 1
        assert cached1["intensity"] == 0.8

        # 验证第二条缓存
        cached2 = service.get_sentiment_from_cache(10002)
        assert cached2 is not None
        assert cached2["polarity"] == -1
        assert cached2["intensity"] == -0.6

    # ========== 边界情况测试 ==========

    def test_empty_string(self, service):
        """测试空字符串处理"""
        result = service.analyze_sentiment("")

        # 空字符串应该返回中性值
        assert result["polarity"] == 0
        assert result["intensity"] == 0.0
        assert len(result["embedding"]) == 384

    def test_very_long_text(self, service):
        """测试超长文本处理"""
        long_text = "这是一个很长的句子。" * 100

        result = service.analyze_sentiment(long_text)

        # 应该正常返回结果
        assert "polarity" in result
        assert "intensity" in result
        assert len(result["embedding"]) == 384

    def test_special_characters(self, service):
        """测试特殊字符处理"""
        special_texts = [
            "😊😊😊",  # emoji
            "！！！。。。",  # 标点符号
            "123456789",  # 数字
            "abc@#$%^&*()",  # 特殊符号
            "中文English混合"  # 中英文混合
        ]

        for text in special_texts:
            result = service.analyze_sentiment(text)

            # 应该正常返回结果
            assert "polarity" in result
            assert "intensity" in result
            assert len(result["embedding"]) == 384


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "-s"])
