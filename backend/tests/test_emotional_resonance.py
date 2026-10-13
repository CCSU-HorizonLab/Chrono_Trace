"""情感共振率服务真实数据测试

使用数据库中的真实会话数据进行测试
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.analysis.emotional_resonance_service import EmotionalResonanceService
from app.services.analysis.engagement_metrics import EngagementMetrics
from app.db.connection import get_db


class TestEmotionalResonanceRealData:
    """使用真实数据测试情感共振率服务"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        print("\n[初始化] 创建 EmotionalResonanceService 实例...")
        service = EmotionalResonanceService()
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
        
        print("✓ 服务初始化成功")
        print("✓ 预处理编排器已加载")
        print("✓ 关键词库已加载")
    
    def test_bidirectional_positive_response(self, service, real_conversation_id):
        """测试2: 双向积极情感响应率"""
        print("\n" + "="*60)
        print("测试2: 双向积极情感响应率 (20%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的双向积极响应率...")
        
        try:
            rate = service.calculate_bidirectional_positive_response(real_conversation_id)
            
            print(f"[结果] 双向积极情感响应率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            print("[提示] 可能需要先运行预处理")
            raise
    
    def test_polarity_consistency(self, service, real_conversation_id):
        """测试3: 情感极性一致性"""
        print("\n" + "="*60)
        print("测试3: 情感极性一致性 (15%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的极性一致性...")
        
        try:
            score = service.calculate_polarity_consistency(real_conversation_id)
            
            print(f"[结果] 情感极性一致性得分: {score}")
            print(f"[验证] 检查结果范围: 0 <= {score} <= 100")
            
            assert 0 <= score <= 100
            assert isinstance(score, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_intensity_matching(self, service, real_conversation_id):
        """测试4: 情绪强度匹配度"""
        print("\n" + "="*60)
        print("测试4: 情绪强度匹配度 (10%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的强度匹配度...")
        
        try:
            score = service.calculate_intensity_matching(real_conversation_id)
            
            print(f"[结果] 情绪强度匹配度: {score}")
            print(f"[验证] 检查结果范围: 0 <= {score} <= 100")
            
            assert 0 <= score <= 100
            assert isinstance(score, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_empathy_recognition(self, service, real_conversation_id):
        """测试5: 共情意图识别率"""
        print("\n" + "="*60)
        print("测试5: 共情意图识别率 (30%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的共情识别率...")
        
        try:
            rate = service.calculate_empathy_recognition(real_conversation_id)
            
            print(f"[结果] 共情意图识别率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_negative_resolution(self, service, real_conversation_id):
        """测试6: 负面情绪协同化解率"""
        print("\n" + "="*60)
        print("测试6: 负面情绪协同化解率 (25%权重)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的负面化解率...")
        
        try:
            rate = service.calculate_negative_resolution(real_conversation_id)
            
            print(f"[结果] 负面情绪协同化解率: {rate}%")
            print(f"[验证] 检查结果范围: 0 <= {rate} <= 100")
            
            assert 0 <= rate <= 100
            assert isinstance(rate, (int, float))
            
            print("✓ 计算成功")
            print("✓ 结果在有效范围内")
            
        except Exception as e:
            print(f"[错误] {e}")
            raise
    
    def test_overall_resonance(self, service, real_conversation_id):
        """测试7: 综合情感共振率 (最重要)"""
        print("\n" + "="*60)
        print("测试7: 综合情感共振率 (加权总分)")
        print("="*60)
        
        print(f"[执行] 计算会话 {real_conversation_id} 的综合情感共振率...")
        
        try:
            result = service.calculate_overall_resonance(
                real_conversation_id, EngagementMetrics()
            )
            
            print("\n[结果] 情感共振率分析结果:")
            print("-" * 60)
            print(f"  总分: {result['overall_score']}")
            print(f"  解释: {result['interpretation']}")
            print("\n  子维度得分:")
            print(f"    - 双向积极情感响应率 (20%): {result['sub_scores']['bidirectional_positive_response']}")
            print(f"    - 情感极性一致性 (15%):     {result['sub_scores']['polarity_consistency']}")
            print(f"    - 情绪强度匹配度 (10%):     {result['sub_scores']['intensity_matching']}")
            print(f"    - 共情意图识别率 (30%):     {result['sub_scores']['empathy_recognition']}")
            print(f"    - 负面情绪协同化解率 (25%): {result['sub_scores']['negative_resolution']}")
            print("-" * 60)
            
            # 验证结果结构
            assert 'overall_score' in result
            assert 'sub_scores' in result
            assert 'interpretation' in result
            
            # 验证总分范围
            assert 0 <= result['overall_score'] <= 100
            
            # 验证子维度
            sub_scores = result['sub_scores']
            assert 'bidirectional_positive_response' in sub_scores
            assert 'polarity_consistency' in sub_scores
            assert 'intensity_matching' in sub_scores
            assert 'empathy_recognition' in sub_scores
            assert 'negative_resolution' in sub_scores
            
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
            print("  2. 缺少必要的数据表 (sentiment_cache, interaction_pairs等)")
            print("  3. 关键词库未初始化")
            raise
    
    def test_check_data_availability(self, real_conversation_id):
        """测试8: 检查数据完整性"""
        print("\n" + "="*60)
        print("测试8: 检查数据完整性")
        print("="*60)
        
        db = get_db()
        
        # 检查消息
        cursor = db.execute("""
            SELECT COUNT(*) FROM messages WHERE conversation_id = ?
        """, (real_conversation_id,))
        message_count = cursor.fetchone()[0]
        print(f"[检查] 消息数: {message_count}")
        
        # 检查情感缓存（通过 messages 表关联）
        cursor = db.execute("""
            SELECT COUNT(*) 
            FROM sentiment_cache sc
            JOIN messages m ON sc.message_id = m.id
            WHERE m.conversation_id = ?
        """, (real_conversation_id,))
        sentiment_count = cursor.fetchone()[0]
        print(f"[检查] 情感缓存: {sentiment_count}")
        
        # 检查发言单元
        cursor = db.execute("""
            SELECT COUNT(*) FROM speech_units WHERE conversation_id = ?
        """, (real_conversation_id,))
        speech_unit_count = cursor.fetchone()[0]
        print(f"[检查] 发言单元: {speech_unit_count}")
        
        # 检查交互对
        cursor = db.execute("""
            SELECT COUNT(*) FROM interaction_pairs WHERE conversation_id = ?
        """, (real_conversation_id,))
        pair_count = cursor.fetchone()[0]
        print(f"[检查] 交互对: {pair_count}")
        
        print("\n[建议]")
        if sentiment_count == 0:
            print("  ⚠️  需要运行情感分析")
        if speech_unit_count == 0:
            print("  ⚠️  需要构建发言单元")
        if pair_count == 0:
            print("  ⚠️  需要构建交互对")
        
        if sentiment_count > 0 and speech_unit_count > 0 and pair_count > 0:
            print("  ✓ 数据完整,可以进行情感共振率分析")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("情感共振率服务真实数据测试")
    print("="*60)
    print("\n运行命令:")
    print("  cd backend")
    print("  pytest tests/test_emotional_resonance.py -v -s")
    print("\n" + "="*60 + "\n")
    
    pytest.main([__file__, "-v", "-s"])
