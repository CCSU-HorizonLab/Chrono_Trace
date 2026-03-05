"""测试预处理模块"""
from app.db.connection import DatabaseConnection
from app.services.analysis.preprocessing_service import PreprocessingService


def test_clean_content():
    """测试消息清洗功能"""
    preprocessor = PreprocessingService()
    
    test_cases = [
        {
            "input": "你好[微笑]",
            "expected_cleaned": "你好",
            "desc": "移除表情"
        },
        {
            "input": "<msg><type>1</type><content>系统消息</content></msg>",
            "expected_cleaned": "",
            "desc": "移除XML系统消息"
        },
        {
            "input": "发了一张[图片]给你",
            "expected_cleaned": "发了一张给你",
            "desc": "移除媒体标签"
        },
        {
            "input": "   多个    空格   ",
            "expected_cleaned": "多个 空格",
            "desc": "规范化空格"
        },
        {
            "input": "正常文本内容",
            "expected_cleaned": "正常文本内容",
            "desc": "正常文本"
        },
        {
            "input": "",
            "expected_cleaned": "",
            "desc": "空字符串"
        }
    ]
    
    print("\n" + "="*60)
    print("测试消息清洗功能")
    print("="*60)
    
    for i, case in enumerate(test_cases, 1):
        result = preprocessor.clean_content(case["input"])
        success = result["cleaned"] == case["expected_cleaned"]
        
        print(f"\n测试 {i}: {case['desc']}")
        print(f"  输入: {repr(case['input'])}")
        print(f"  期望: {repr(case['expected_cleaned'])}")
        print(f"  实际: {repr(result['cleaned'])}")
        print(f"  结果: {'✓ 通过' if success else '✗ 失败'}")
        print(f"  详情: 原始长度={result['original_length']}, "
              f"清洗后长度={result['cleaned_length']}, "
              f"有效={result['is_valid']}")
        
        if not success:
            print(f"  ⚠️  清洗结果不符合预期！")


def test_message_stats():
    """测试消息统计功能"""
    preprocessor = PreprocessingService()
    
    test_cases = [
        {"input": "你好世界", "desc": "简单中文"},
        {"input": "Hello World", "desc": "英文"},
        {"input": "你好，世界！", "desc": "带标点"},
        {"input": "今天天气真不错，我们去爬山吧", "desc": "长句子"}
    ]
    
    print("\n" + "="*60)
    print("测试消息统计功能")
    print("="*60)
    
    for i, case in enumerate(test_cases, 1):
        stats = preprocessor.calculate_message_stats(case["input"])
        
        print(f"\n测试 {i}: {case['desc']}")
        print(f"  文本: {case['input']}")
        print(f"  字符数: {stats['char_count']}")
        print(f"  词数: {stats['word_count']}")
        print(f"  有标点: {stats['has_punctuation']}")


def test_preprocess_conversation():
    """测试完整预处理流程（需要数据库有数据）"""
    print("\n" + "="*60)
    print("测试完整预处理流程 + 缓存功能")
    print("="*60)
    
    # 初始化数据库
    db = DatabaseConnection.initialize()
    
    # 检查是否有会话数据
    cursor = db.execute("SELECT COUNT(*) FROM conversations")
    conv_count = cursor.fetchone()[0]
    
    if conv_count == 0:
        print("\n⚠️  数据库中没有会话数据，跳过完整流程测试")
        print("   请先运行数据导入功能")
        return
    
    # 获取第一个会话ID
    cursor = db.execute(
        "SELECT id, display_name, message_count FROM conversations LIMIT 1"
    )
    row = cursor.fetchone()
    conv_id = row[0]
    conv_name = row[1]
    msg_count = row[2]
    
    print(f"\n测试会话: ID={conv_id}, 名称={conv_name}, 消息数={msg_count}")
    
    # 执行预处理（第一次，无缓存）
    print("\n第一次预处理（无缓存）:")
    preprocessor = PreprocessingService()
    result1 = preprocessor.preprocess_conversation(conv_id, limit=100, use_cache=True)
    
    print(f"  总消息数: {result1['total_messages']}")
    print(f"  有效消息数: {result1['valid_messages']}")
    print(f"  无效消息数: {result1['stats']['invalid_messages']}")
    print(f"  XML消息数: {result1['stats']['xml_count']}")
    print(f"  媒体消息数: {result1['stats']['media_count']}")
    print(f"  平均字符数: {result1['stats']['avg_char_count']}")
    print(f"  平均词数: {result1['stats']['avg_word_count']}")
    print(f"  缓存命中率: {result1['stats']['cache_hit_rate'] * 100:.1f}%")
    
    # 执行预处理（第二次，应该全部命中缓存）
    print("\n第二次预处理（应该全部命中缓存）:")
    result2 = preprocessor.preprocess_conversation(conv_id, limit=100, use_cache=True)
    
    print(f"  总消息数: {result2['total_messages']}")
    print(f"  缓存命中率: {result2['stats']['cache_hit_rate'] * 100:.1f}%")
    
    # 验证缓存效果
    if result2['stats']['cache_hit_rate'] >= 0.99:
        print("\n✅ 缓存测试通过！第二次查询完全命中缓存")
    else:
        print(f"\n⚠️  缓存命中率较低: {result2['stats']['cache_hit_rate'] * 100:.1f}%")
    
    # 显示前3条清洗后的消息
    if result1['cleaned_messages']:
        print(f"\n前3条清洗后的消息示例:")
        for i, msg in enumerate(result1['cleaned_messages'][:3], 1):
            print(f"\n  消息 {i}:")
            original_preview = msg['original_content'][:50] if len(msg['original_content']) > 50 else msg['original_content']
            cleaned_preview = msg['cleaned_content'][:50] if len(msg['cleaned_content']) > 50 else msg['cleaned_content']
            print(f"    原始: {original_preview}{'...' if len(msg['original_content']) > 50 else ''}")
            print(f"    清洗: {cleaned_preview}{'...' if len(msg['cleaned_content']) > 50 else ''}")
            print(f"    字符数: {msg['char_count']}, 词数: {msg['word_count']}")
    
    # 统计缓存表
    cursor = db.execute("SELECT COUNT(*) FROM message_preprocessed WHERE conversation_id = ?", (conv_id,))
    cached_count = cursor.fetchone()[0]
    print(f"\n📊 缓存统计: 该会话已缓存 {cached_count} 条消息")


if __name__ == "__main__":
    print("\n🚀 开始测试预处理模块")
    print("="*60)
    
    # 测试1: 消息清洗
    test_clean_content()
    
    # 测试2: 消息统计
    test_message_stats()
    
    # 测试3: 完整流程（需要数据）
    test_preprocess_conversation()
    
    print("\n" + "="*60)
    print("✅ 测试完成")
    print("="*60)
