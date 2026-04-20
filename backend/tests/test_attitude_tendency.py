"""态度倾向服务真实数据测试

测试 6 个子维度：
1. 正面词频率 (25%权重)
2. 负面词频率 (-20%权重，反向计分)
3. 多媒体使用率 (15%权重)
4. 专属称呼频率 (25%权重)
5. 隐私分享频率 (20%权重)
6. 节日祝福频率 (15%权重)
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.analysis.attitude_tendency_service import AttitudeTendencyService
from app.db.connection import get_db


class TestAttitudeTendencyRealData:
    """使用真实数据测试态度倾向服务"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        print("\n[初始化] 创建 AttitudeTendencyService 实例...")
        service = AttitudeTendencyService()
        print("[初始化] ✓ 服务实例创建成功")
        return service
    
    @pytest.fixture
    def real_conversation_id(self):
        """获取真实的会话ID"""
        db = get_db()
        cursor = db.execute("""
            SELECT id, username, display_name
            FROM conversations
            WHERE username = ?
        """, ("wxid_anon_contact_b",))
        row = cursor.fetchone()

        if not row:
            pytest.skip("数据库中没有找到微信ID 'wxid_anon_contact_b' 的会话")

        conversation_id = row[0]
        username = row[1]
        display_name = row[2]

        print(f"\n[数据] 使用真实会话:")
        print(f"  - 会话ID: {conversation_id}")
        print(f"  - 用户名: {username}")
        print(f"  - 显示名: {display_name}")

        # 检查消息数量
        cursor = db.execute("""
            SELECT COUNT(*) FROM messages WHERE conversation_id = ?
        """, (conversation_id,))
        message_count = cursor.fetchone()[0]
        print(f"  - 消息数: {message_count}")

        if message_count == 0:
            pytest.skip(f"会话 {conversation_id} 没有消息")

        return conversation_id
    
    def test_service_initialization(self, service):
        """测试1: 服务初始化"""
        print("\n" + "="*60)
        print("测试1: 服务初始化")
        print("="*60)
        
        assert service is not None
        assert hasattr(service, 'orchestrator')
        assert hasattr(service, 'keyword_lib')
        assert hasattr(service, 'direction_service')
        assert hasattr(service, 'relationship_context_service')
        
        print("✓ 服务初始化成功")
        print("✓ 预处理编排器已加载")
        print("✓ 关键词库已加载")
    
    def test_positive_word_frequency(self, service, real_conversation_id):
        """测试2: 正面词频率 (25%权重)"""
        print("\n" + "="*60)
        print("测试2: 正面词频率 (25%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的正面词频率...")
        
        try:
            rate = service.calculate_positive_word_frequency(real_conversation_id)
            
            print(f"[结果] 正面词频率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_negative_word_frequency(self, service, real_conversation_id):
        """测试3: 负面词频率 (-20%权重，反向计分)"""
        print("\n" + "="*60)
        print("测试3: 负面词频率 (-20%权重，反向计分)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的负面词频率...")
        
        try:
            rate = service.calculate_negative_word_frequency(real_conversation_id)
            
            print(f"[结果] 负面词频率: {rate}%")
            print(f"[说明] 反向计分后得分: {100 - rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_multimedia_usage(self, service, real_conversation_id):
        """测试4: 多媒体使用率 (15%权重)"""
        print("\n" + "="*60)
        print("测试4: 多媒体使用率 (15%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的多媒体使用率...")
        
        try:
            rate = service.calculate_multimedia_usage(real_conversation_id)
            
            print(f"[结果] 多媒体使用率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_nickname_frequency(self, service, real_conversation_id):
        """测试5: 专属称呼频率 (25%权重)"""
        print("\n" + "="*60)
        print("测试5: 专属称呼频率 (25%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的专属称呼频率...")
        
        try:
            rate = service.calculate_nickname_frequency(real_conversation_id)
            
            print(f"[结果] 专属称呼频率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_privacy_sharing(self, service, real_conversation_id):
        """测试6: 隐私分享频率 (20%权重)"""
        print("\n" + "="*60)
        print("测试6: 隐私分享频率 (20%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的隐私分享频率...")
        
        try:
            rate = service.calculate_privacy_sharing(real_conversation_id)
            
            print(f"[结果] 隐私分享频率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_holiday_greeting(self, service, real_conversation_id):
        """测试7: 节日祝福频率 (15%权重)"""
        print("\n" + "="*60)
        print("测试7: 节日祝福频率 (15%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的节日祝福频率...")
        
        try:
            rate = service.calculate_holiday_greeting(real_conversation_id)
            
            print(f"[结果] 节日祝福频率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_overall_attitude(self, service, real_conversation_id):
        """测试8: 综合态度倾向 (最重要)"""
        print("\n" + "="*60)
        print("测试8: 综合态度倾向 (加权总分)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的综合态度倾向...")
        
        try:
            result = service.calculate_overall_attitude(real_conversation_id)
            
            print("\n[结果] 态度倾向分析结果:")
            print("-" * 60)
            print(f"  总分: {result['overall_score']}")
            print(f"  解释: {result['interpretation']}")
            print("\n  子维度得分:")
            print(f"    - 正面词频率 (25%):     {result['sub_scores']['positive_word_frequency']}")
            print(f"    - 负面词频率 (-20%):    {result['sub_scores']['negative_word_frequency']}")
            print(f"    - 多媒体使用率 (15%):   {result['sub_scores']['multimedia_usage']}")
            print(f"    - 专属称呼频率 (25%):   {result['sub_scores']['nickname_frequency']}")
            print(f"    - 隐私分享频率 (20%):   {result['sub_scores']['privacy_sharing']}")
            print(f"    - 节日祝福频率 (15%):   {result['sub_scores']['holiday_greeting']}")
            print("-" * 60)
            
            # 验证结果结构
            assert 'overall_score' in result
            assert 'sub_scores' in result
            assert 'interpretation' in result
            
            # 验证总分范围
            assert 0 <= result['overall_score'] <= 100
            
            # 验证子维度
            sub_scores = result['sub_scores']
            assert 'positive_word_frequency' in sub_scores
            assert 'negative_word_frequency' in sub_scores
            assert 'multimedia_usage' in sub_scores
            assert 'nickname_frequency' in sub_scores
            assert 'privacy_sharing' in sub_scores
            assert 'holiday_greeting' in sub_scores
            
            # 验证所有子维度在有效范围
            for key, value in sub_scores.items():
                assert 0 <= value <= 100, f"{key} 超出范围: {value}"
            
            # 验证解释文本
            assert isinstance(result['interpretation'], str)
            assert len(result['interpretation']) > 0
            
            print("\n✓ 综合计算成功")
            print("✓ 结果结构正确")
            print("✓ 所有子维度在有效范围内")
            print("✓ 解释文本生成成功")
            
        except Exception as e:
            print(f"\n[错误] {e}")
            print("\n[提示] 可能的原因:")
            print("  1. 需要先运行预处理 (PreprocessingOrchestrator)")
            print("  2. 缺少必要的数据表")
            print("  3. 关键词库未初始化")
            raise


if __name__ == "__main__":
    print("\n" + "="*60)
    print("态度倾向服务真实数据测试")
    print("="*60)
    print("\n运行命令:")
    print("  cd backend")
    print("  pytest tests/test_attitude_tendency.py -v -s")
    print("\n" + "="*60 + "\n")
    
    pytest.main([__file__, "-v", "-s"])
