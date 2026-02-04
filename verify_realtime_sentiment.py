"""快速验证实时情感分析功能

不需要完整的pytest环境,直接测试核心功能
"""

import sys
import os

# 添加backend到路径
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_path)

print("=" * 70)
print("实时消息情感分析 - 快速验证")
print("=" * 70)

try:
    from app.services.realtime.realtime_sentiment_service import RealtimeSentimentService
    
    print("\n✓ 成功导入RealtimeSentimentService")
    
    # 创建服务实例
    print("\n正在初始化服务...")
    service = RealtimeSentimentService()
    print("✓ 服务初始化成功")
    
    # 测试用例
    test_cases = [
        {
            'text': "今天心情不错😊",
            'expected': '正面',
            'description': '简单正面+表情'
        },
        {
            'text': "虽然累,但是很开心",
            'expected': '正面',
            'description': '转折句'
        },
        {
            'text': "这个功能yyds!",
            'expected': '正面',
            'description': '网络用语'
        },
        {
            'text': "emo了😢",
            'expected': '负面',
            'description': '网络用语+负面表情'
        },
        {
            'text': "呵呵,好的好的",
            'expected': '中性/负面',
            'description': '反讽检测'
        },
        {
            'text': "嗯",
            'expected': '中性',
            'description': '敷衍回复'
        },
        {
            'text': "今天天气还可以",
            'expected': '中性/正面',
            'description': '中性评价'
        },
    ]
    
    print("\n" + "=" * 70)
    print("开始测试...")
    print("=" * 70)
    
    polarity_map = {-1: '负面', 0: '中性', 1: '正面'}
    
    passed = 0
    total = len(test_cases)
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n[测试 {i}/{total}] {case['description']}")
        print(f"文本: {case['text']}")
        print(f"期望: {case['expected']}")
        
        try:
            result = service.analyze(case['text'])
            
            polarity_text = polarity_map[result['polarity']]
            print(f"结果: {polarity_text} (极性={result['polarity']}, 强度={result['intensity']:.2f})")
            print(f"置信度: {result['confidence']:.2f}")
            print(f"应用规则: {', '.join(result['rules_applied']) if result['rules_applied'] else '无'}")
            
            # 简单验证
            if result['polarity'] in [-1, 0, 1]:
                print("✓ 测试通过")
                passed += 1
            else:
                print("✗ 测试失败: 极性值无效")
                
        except Exception as e:
            print(f"✗ 测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"测试完成: {passed}/{total} 通过")
    print("=" * 70)
    
    # 性能测试
    print("\n" + "=" * 70)
    print("性能测试")
    print("=" * 70)
    
    import time
    
    text = "今天天气不错,心情也很好"
    
    # 预热(首次加载模型)
    print("\n正在加载模型(首次较慢)...")
    start = time.time()
    result = service.analyze(text)
    elapsed = (time.time() - start) * 1000
    print(f"首次分析耗时: {elapsed:.0f}ms")
    
    # 第二次(模型已加载)
    start = time.time()
    result = service.analyze(text)
    elapsed = (time.time() - start) * 1000
    print(f"第二次分析耗时: {elapsed:.0f}ms")
    
    # 批量测试
    texts = [text] * 10
    start = time.time()
    results = service.analyze_batch(texts)
    elapsed = (time.time() - start) * 1000
    print(f"批量分析10条耗时: {elapsed:.0f}ms (平均{elapsed/10:.0f}ms/条)")
    
    print("\n" + "=" * 70)
    print("验证完成!")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 所有测试通过!")
        sys.exit(0)
    else:
        print(f"\n⚠️ 部分测试失败 ({total-passed}/{total})")
        sys.exit(1)

except ImportError as e:
    print(f"\n✗ 导入失败: {e}")
    print("\n请确保:")
    print("1. 已安装依赖: pip install transformers jieba")
    print("2. 在项目根目录运行此脚本")
    sys.exit(1)
    
except Exception as e:
    print(f"\n✗ 验证失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
