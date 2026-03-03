"""
测试 Erlangshen 情感分析模型
验证模型加载和推理效果
"""
import sys
import os
import time

# 添加backend到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.realtime.realtime_sentiment_service import RealtimeSentimentService


def test_model_loading():
    """测试模型加载"""
    print("=" * 60)
    print("测试 Erlangshen 情感分析模型")
    print("=" * 60)
    
    print("\n[1/3] 初始化服务...")
    service = RealtimeSentimentService()
    
    print("\n[2/3] 加载模型(首次使用会下载约450MB)...")
    start_time = time.time()
    
    # 触发模型加载
    result = service.analyze("测试")
    
    load_time = time.time() - start_time
    print(f"\n✓ 模型加载完成,耗时: {load_time:.2f}秒")
    
    return service


def test_inference_speed(service):
    """测试推理速度"""
    print("\n[3/3] 测试推理速度...")
    
    test_texts = [
        "今天心情不错😊",
        "太难过了😢",
        "还可以吧",
        "这个功能yyds!",
        "emo了",
    ]
    
    # 预热
    service.analyze("预热")
    
    # 测试单条推理速度
    times = []
    for text in test_texts:
        start = time.time()
        result = service.analyze(text)
        elapsed = (time.time() - start) * 1000  # 转换为毫秒
        times.append(elapsed)
        
        polarity_text = {-1: '负面', 0: '中性', 1: '正面'}[result['polarity']]
        print(f"  '{text}' -> {polarity_text} (强度:{result['intensity']:+.2f}) [{elapsed:.1f}ms]")
    
    avg_time = sum(times) / len(times)
    print(f"\n✓ 平均推理时间: {avg_time:.1f}ms")
    
    # 性能评估
    if avg_time < 50:
        print("  性能评级: ⭐⭐⭐⭐⭐ 优秀 (GPU加速)")
    elif avg_time < 150:
        print("  性能评级: ⭐⭐⭐⭐ 良好 (适合实时使用)")
    elif avg_time < 300:
        print("  性能评级: ⭐⭐⭐ 可用 (CPU模式)")
    else:
        print("  性能评级: ⭐⭐ 较慢 (建议优化)")


def test_comprehensive_cases(service):
    """测试综合案例"""
    print("\n" + "=" * 60)
    print("综合测试案例")
    print("=" * 60)
    
    test_cases = [
        # 正面情感
        ("今天天气真好,心情也很棒😊", "正面"),
        ("这个功能太牛了!yyds!", "正面"),
        ("爱了爱了❤️", "正面"),
        ("666,给力!", "正面"),
        
        # 负面情感
        ("心情不好,烦死了😡", "负面"),
        ("太难过了,想哭😢", "负面"),
        ("emo了,不想说话", "负面"),
        ("无语了,崩溃", "负面"),
        
        # 中性情感
        ("嗯,知道了", "中性"),
        ("还可以吧", "中性"),
        ("一般般", "中性"),
        ("好吧", "中性"),
    ]
    
    correct = 0
    total = len(test_cases)
    
    for text, expected in test_cases:
        result = service.analyze(text)
        polarity_text = {-1: '负面', 0: '中性', 1: '正面'}[result['polarity']]
        
        is_correct = polarity_text == expected
        correct += is_correct
        
        status = "✓" if is_correct else "✗"
        print(f"{status} '{text}'")
        print(f"   预期:{expected} | 实际:{polarity_text} | 强度:{result['intensity']:+.2f} | 置信度:{result['confidence']:.2f}")
        print()
    
    accuracy = correct / total * 100
    print(f"准确率: {correct}/{total} ({accuracy:.1f}%)")
    
    if accuracy >= 80:
        print("✓ 模型效果良好!")
    elif accuracy >= 60:
        print("⚠ 模型效果一般,建议后续微调")
    else:
        print("✗ 模型效果较差,需要微调或使用其他模型")


def main():
    try:
        # 1. 测试模型加载
        service = test_model_loading()
        
        # 2. 测试推理速度
        test_inference_speed(service)
        
        # 3. 测试综合案例
        test_comprehensive_cases(service)
        
        print("\n" + "=" * 60)
        print("测试完成!")
        print("=" * 60)
        print("\n💡 提示:")
        print("  - 如果准确率不理想,可以考虑后续使用自己的数据微调")
        print("  - 模型已缓存到本地,下次启动会更快")
        print("  - 可以在实时监听中观察实际效果")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
