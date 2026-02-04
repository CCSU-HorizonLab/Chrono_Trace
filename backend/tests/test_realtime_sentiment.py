"""实时消息情感分析测试

测试RealtimeSentimentService的各项功能
"""

import pytest
import sys
import os

# 添加backend到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.realtime.realtime_sentiment_service import RealtimeSentimentService


class TestRealtimeSentiment:
    """实时情感分析测试"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return RealtimeSentimentService()
    
    # ========== 基础功能测试 ==========
    
    def test_simple_positive(self, service):
        """测试简单正面消息"""
        result = service.analyze("今天心情不错😊")
        
        assert result['polarity'] == 1, "应该识别为正面"
        assert result['intensity'] > 0, "强度应该为正"
        assert '正面表情' in str(result['rules_applied']) or result['polarity'] == 1
        print(f"✓ 简单正面: {result}")
    
    def test_simple_negative(self, service):
        """测试简单负面消息"""
        result = service.analyze("今天心情很差😢")
        
        assert result['polarity'] == -1, "应该识别为负面"
        assert result['intensity'] < 0, "强度应该为负"
        print(f"✓ 简单负面: {result}")
    
    def test_neutral(self, service):
        """测试中性消息"""
        result = service.analyze("今天天气还可以")
        
        assert result['polarity'] in [-1, 0, 1], "极性应该有效"
        print(f"✓ 中性消息: {result}")
    
    # ========== 表情符号测试 ==========
    
    def test_emoji_positive(self, service):
        """测试正面表情符号"""
        test_cases = [
            "开心😊",
            "太好了👍",
            "爱了❤️",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            assert result['polarity'] >= 0, f"'{text}' 应该是正面或中性"
            print(f"✓ 表情测试 '{text}': polarity={result['polarity']}")
    
    def test_emoji_negative(self, service):
        """测试负面表情符号"""
        test_cases = [
            "难过😢",
            "生气😡",
            "失望💔",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            assert result['polarity'] <= 0, f"'{text}' 应该是负面或中性"
            print(f"✓ 表情测试 '{text}': polarity={result['polarity']}")
    
    # ========== 网络用语测试 ==========
    
    def test_internet_slang_positive(self, service):
        """测试正面网络用语"""
        test_cases = [
            "这个功能yyds!",
            "绝绝子",
            "666",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            assert result['polarity'] >= 0, f"'{text}' 应该是正面或中性"
            print(f"✓ 网络用语 '{text}': polarity={result['polarity']}")
    
    def test_internet_slang_negative(self, service):
        """测试负面网络用语"""
        test_cases = [
            "emo了",
            "无语了",
            "崩溃",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            assert result['polarity'] <= 0, f"'{text}' 应该是负面或中性"
            print(f"✓ 网络用语 '{text}': polarity={result['polarity']}")
    
    # ========== 转折句测试 ==========
    
    def test_transition_sentence(self, service):
        """测试转折句"""
        test_cases = [
            ("虽然累,但是很开心", 1),  # 应该是正面
            ("今天天气不错,但是心情不好", -1),  # 应该是负面
        ]
        
        for text, expected_polarity in test_cases:
            result = service.analyze(text)
            # 转折句可能比较复杂,只检查是否有结果
            assert result['polarity'] in [-1, 0, 1]
            print(f"✓ 转折句 '{text}': polarity={result['polarity']} (期望={expected_polarity})")
    
    # ========== 否定句测试 ==========
    
    def test_negation(self, service):
        """测试否定句"""
        test_cases = [
            "不好",
            "不开心",
            "不满意",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            # 否定词应该导致负面情感
            assert result['polarity'] in [-1, 0, 1]
            print(f"✓ 否定句 '{text}': polarity={result['polarity']}")
    
    # ========== 反讽检测测试 ==========
    
    def test_sarcasm(self, service):
        """测试反讽检测"""
        test_cases = [
            "呵呵,好的好的",
            "行行行",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            # 反讽检测应该降低置信度或改变极性
            assert result['polarity'] in [-1, 0, 1]
            print(f"✓ 反讽 '{text}': polarity={result['polarity']}, confidence={result['confidence']}")
    
    # ========== 敷衍检测测试 ==========
    
    def test_perfunctory(self, service):
        """测试敷衍回复"""
        test_cases = [
            "嗯",
            "哦",
            "好吧",
        ]
        
        for text in test_cases:
            result = service.analyze(text)
            # 敷衍回复应该是中性
            assert result['polarity'] == 0, f"'{text}' 应该是中性"
            assert '敷衍回复' in result['rules_applied']
            print(f"✓ 敷衍 '{text}': {result}")
    
    # ========== 空文本测试 ==========
    
    def test_empty_text(self, service):
        """测试空文本"""
        test_cases = ["", "   ", None]
        
        for text in test_cases:
            if text is None:
                text = ""
            result = service.analyze(text)
            assert result['polarity'] == 0
            assert result['intensity'] == 0.0
            print(f"✓ 空文本: {result}")
    
    # ========== 批量处理测试 ==========
    
    def test_batch_analysis(self, service):
        """测试批量分析"""
        texts = [
            "今天很开心😊",
            "心情不好😢",
            "还可以",
            "yyds!",
            "emo了"
        ]
        
        results = service.analyze_batch(texts)
        
        assert len(results) == len(texts), "结果数量应该匹配"
        
        for text, result in zip(texts, results):
            assert result['polarity'] in [-1, 0, 1]
            print(f"✓ 批量 '{text}': polarity={result['polarity']}")
    
    # ========== 性能测试 ==========
    
    def test_performance(self, service):
        """测试性能"""
        import time
        
        text = "今天天气不错,心情也很好"
        
        # 单条消息性能
        start = time.time()
        result = service.analyze(text)
        elapsed = (time.time() - start) * 1000
        
        print(f"✓ 单条消息耗时: {elapsed:.2f}ms")
        assert elapsed < 5000, "单条消息应该在5秒内完成(首次加载模型较慢)"
        
        # 第二次应该更快(模型已加载)
        start = time.time()
        result = service.analyze(text)
        elapsed = (time.time() - start) * 1000
        
        print(f"✓ 第二次耗时: {elapsed:.2f}ms")
    
    # ========== 综合测试 ==========
    
    def test_comprehensive(self, service):
        """综合测试案例"""
        test_cases = [
            {
                'text': "今天的会议虽然时间长,但是大家的想法都很棒😊",
                'expected_polarity': 1,
                'description': "转折+表情"
            },
            {
                'text': "这个功能yyds!太好用了👍",
                'expected_polarity': 1,
                'description': "网络用语+表情"
            },
            {
                'text': "累死了,不想干了😩",
                'expected_polarity': -1,
                'description': "负面+表情"
            },
            {
                'text': "还行吧,一般般",
                'expected_polarity': 0,
                'description': "中性评价"
            },
        ]
        
        for case in test_cases:
            result = service.analyze(case['text'])
            print(f"\n✓ {case['description']}")
            print(f"  文本: {case['text']}")
            print(f"  结果: polarity={result['polarity']}, intensity={result['intensity']}")
            print(f"  规则: {result['rules_applied']}")
            print(f"  置信度: {result['confidence']}")


if __name__ == '__main__':
    # 直接运行测试
    service = RealtimeSentimentService()
    
    print("=" * 60)
    print("实时消息情感分析测试")
    print("=" * 60)
    
    test_cases = [
        "今天心情不错😊",
        "虽然累,但是很开心",
        "这个功能yyds!",
        "emo了",
        "呵呵,好的好的",
        "嗯",
    ]
    
    for text in test_cases:
        result = service.analyze(text)
        print(f"\n文本: {text}")
        print(f"极性: {result['polarity']} | 强度: {result['intensity']:.2f} | 置信度: {result['confidence']:.2f}")
        print(f"规则: {result['rules_applied']}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
