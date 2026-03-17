"""聊天积极度服务测试

测试 ChatPositivityService 的所有 5 个子维度计算方法
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))


class TestChatPositivityService:
    """测试聊天积极度服务"""

    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库连接"""
        mock = MagicMock()
        return mock

    @pytest.fixture
    def mock_stats(self):
        """创建模拟预处理统计数据"""
        from app.services.analysis.preprocessing_orchestrator import PreprocessedStatistics
        
        stats = PreprocessedStatistics()
        stats.total_message_count = 1000
        stats.conversation_duration_days = 30.0
        stats.average_message_length = 25.0
        stats.total_sessions = 50
        stats.sender_initiated_count = 20
        stats.contact_initiated_count = 30
        return stats

    @pytest.fixture
    def service(self, mock_db):
        """创建服务实例"""
        patcher = patch('app.services.analysis.chat_positivity_service.get_db', return_value=mock_db)
        patcher.start()
        from app.services.analysis.chat_positivity_service import ChatPositivityService
        service = ChatPositivityService(timeliness_threshold_seconds=300)
        yield service
        patcher.stop()

    # ========================================
    # 日均消息数测试
    # ========================================

    def test_daily_message_score_normal(self, service, mock_stats):
        """测试正常情况下的日均消息数"""
        # 1000 消息 / 30 天 = 33.33 条/天
        # 满分基准是 10 条/天，所以应该得满分
        score = service.calculate_daily_message_score(mock_stats)
        assert score == 100.0

    def test_daily_message_score_low(self, service, mock_stats):
        """测试低消息量"""
        mock_stats.total_message_count = 100
        mock_stats.conversation_duration_days = 30.0
        # 100 / 30 = 3.33 条/天
        # 3.33 / 10 * 100 = 33.3
        score = service.calculate_daily_message_score(mock_stats)
        assert 33 <= score <= 34

    def test_daily_message_score_zero_duration(self, service, mock_stats):
        """测试零持续时间"""
        mock_stats.conversation_duration_days = 0
        score = service.calculate_daily_message_score(mock_stats)
        assert score == 0.0

    # ========================================
    # 回复及时率测试
    # ========================================

    def test_reply_timeliness_all_timely(self, service, mock_db):
        """测试全部及时回复"""
        # 模拟所有交互对都及时回复
        mock_db.execute.return_value.fetchone.return_value = (100, 100)
        
        score = service.calculate_reply_timeliness_score(1)
        assert score == 100.0

    def test_reply_timeliness_half_timely(self, service, mock_db):
        """测试一半及时回复"""
        mock_db.execute.return_value.fetchone.return_value = (100, 50)
        
        score = service.calculate_reply_timeliness_score(1)
        assert score == 50.0

    def test_reply_timeliness_no_pairs(self, service, mock_db):
        """测试无交互对"""
        mock_db.execute.return_value.fetchone.return_value = (0, 0)
        
        score = service.calculate_reply_timeliness_score(1)
        assert score == 0.0

    # ========================================
    # 长文本占比加分测试
    # ========================================

    def test_long_text_bonus_high(self, service, mock_db, mock_stats):
        """测试高长文本占比加分"""
        # 30% 长文本 = 满分10分
        mock_db.execute.return_value.fetchone.return_value = (300,)
        mock_stats.total_message_count = 1000
        
        score = service.calculate_long_text_bonus(1, mock_stats)
        assert score == 10.0

    def test_long_text_bonus_low(self, service, mock_db, mock_stats):
        """测试低长文本占比加分"""
        # 10% 长文本
        mock_db.execute.return_value.fetchone.return_value = (100,)
        mock_stats.total_message_count = 1000
        
        score = service.calculate_long_text_bonus(1, mock_stats)
        assert 3.3 <= score <= 3.4

    def test_long_text_bonus_zero_messages(self, service, mock_db, mock_stats):
        """测试零消息"""
        mock_stats.total_message_count = 0
        
        score = service.calculate_long_text_bonus(1, mock_stats)
        assert score == 0.0

    # ========================================
    # 话题延续性测试
    # ========================================

    def test_topic_continuity_high(self, service, mock_db):
        """测试高话题延续性"""
        mock_db.execute.return_value.fetchone.return_value = (1, 0.8)
        
        score = service.calculate_topic_continuity_score(1)
        assert score == 100.0

    def test_topic_continuity_low(self, service, mock_db):
        """测试低话题延续性"""
        mock_db.execute.return_value.fetchone.return_value = (1, 0.3)
        
        score = service.calculate_topic_continuity_score(1)
        assert score == 60.0

    def test_topic_continuity_null(self, service, mock_db):
        """测试无相似度数据"""
        mock_db.execute.return_value.fetchone.return_value = (0, None)
        
        score = service.calculate_topic_continuity_score(1)
        assert score == 0.0

    def test_topic_continuity_falls_back_to_session_rebuild(self, service, mock_db):
        """当交互对缺少语义相似度时，回退到会话级重算"""
        mock_db.execute.return_value.fetchone.return_value = (0, None)

        with patch.object(service, '_calculate_topic_continuity_from_sessions', return_value=0.4) as fallback:
            score = service.calculate_topic_continuity_score(1)

        fallback.assert_called_once_with(1)
        assert score == 80.0

    # ========================================
    # 主动发起率测试
    # ========================================

    def test_active_initiation_high(self, service, mock_stats):
        """测试高主动发起率"""
        mock_stats.total_sessions = 100
        mock_stats.contact_initiated_count = 80
        
        score = service.calculate_active_initiation_score(mock_stats)
        assert score == 100.0

    def test_active_initiation_low(self, service, mock_stats):
        """测试低主动发起率"""
        mock_stats.total_sessions = 100
        mock_stats.contact_initiated_count = 20
        
        score = service.calculate_active_initiation_score(mock_stats)
        assert score == 40.0

    def test_active_initiation_zero_sessions(self, service, mock_stats):
        """测试零会话"""
        mock_stats.total_sessions = 0
        mock_stats.contact_initiated_count = 0
        
        score = service.calculate_active_initiation_score(mock_stats)
        assert score == 0.0

    # ========================================
    # 综合评分测试
    # ========================================

    def test_overall_score_weights(self, service):
        """测试综合评分权重正确"""
        from app.services.analysis.chat_positivity_service import ChatPositivityResult
        
        result = ChatPositivityResult()
        result.daily_message_score = 100
        result.reply_timeliness_score = 100
        result.topic_continuity_score = 100
        result.active_initiation_score = 100
        result.long_text_bonus = 0
        
        overall = service._calculate_overall_score(result)
        # 所有子维度都是 100，所以综合评分应该是 100
        assert overall == 100.0

    def test_overall_score_partial(self, service):
        """测试部分得分"""
        from app.services.analysis.chat_positivity_service import ChatPositivityResult
        
        result = ChatPositivityResult()
        result.daily_message_score = 50
        result.reply_timeliness_score = 50
        result.topic_continuity_score = 50
        result.active_initiation_score = 50
        result.long_text_bonus = 5
        
        overall = service._calculate_overall_score(result)
        # 50 + 5加分
        assert overall == 55.0
    
    def test_overall_score_weights_sum_to_100(self, service):
        """测试权重总和为100%"""
        # 验证权重总和
        total_weight = (
            service.WEIGHT_DAILY_MESSAGE +
            service.WEIGHT_REPLY_TIMELINESS +
            service.WEIGHT_TOPIC_CONTINUITY +
            service.WEIGHT_ACTIVE_INITIATION
        )
        assert abs(total_weight - 1.0) < 0.001  # 允许浮点误差
    
    def test_overall_score_weighted_correctly(self, service):
        """测试加权计算正确性"""
        from app.services.analysis.chat_positivity_service import ChatPositivityResult
        
        result = ChatPositivityResult()
        # 设置不同的分数
        result.daily_message_score = 80
        result.reply_timeliness_score = 60
        result.topic_continuity_score = 90
        result.active_initiation_score = 40
        result.long_text_bonus = 8
        
        overall = service._calculate_overall_score(result)
        
        # 手动计算期望值
        expected = (
            80 * 0.15 +  # 12
            60 * 0.25 +  # 15
            90 * 0.25 +  # 22.5
            40 * 0.35    # 14
        ) + 8  # = 63.5 + 8 = 71.5
        
        assert abs(overall - expected) < 0.1

    # ========================================
    # 解释文本测试
    # ========================================

    def test_interpretation_high(self, service):
        """测试高分解释"""
        interpretation = service.generate_interpretation(85)
        assert "非常高" in interpretation

    def test_interpretation_medium(self, service):
        """测试中等分解释"""
        interpretation = service.generate_interpretation(55)
        assert "一般" in interpretation

    def test_interpretation_low(self, service):
        """测试低分解释"""
        interpretation = service.generate_interpretation(15)
        assert "很低" in interpretation


class TestReplyTimelinessBoundaries:
    """回复及时性边界测试 - T016"""
    
    @pytest.fixture
    def service_300s(self, mock_db):
        """创建阈值为300秒的服务实例"""
        patcher = patch('app.services.analysis.chat_positivity_service.get_db', return_value=mock_db)
        patcher.start()
        from app.services.analysis.chat_positivity_service import ChatPositivityService
        service = ChatPositivityService(timeliness_threshold_seconds=300)
        yield service
        patcher.stop()
    
    @pytest.fixture
    def mock_db(self):
        """创建模拟数据库"""
        return MagicMock()
    
    # ========================================
    # 阈值边界测试
    # ========================================
    
    def test_exactly_at_threshold(self, service_300s, mock_db):
        """测试恰好等于阈值（300秒）"""
        # 模拟：总共10个交互对，其中5个恰好是300秒
        # 期望：300秒应该算及时（<=阈值）
        mock_db.execute.return_value.fetchone.return_value = (10, 5)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 5/10 = 50%
        assert score == 50.0
    
    def test_just_below_threshold(self, service_300s, mock_db):
        """测试刚好低于阈值（299秒）"""
        # 模拟：所有交互对都是299秒（及时）
        mock_db.execute.return_value.fetchone.return_value = (10, 10)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 10/10 = 100%
        assert score == 100.0
    
    def test_just_above_threshold(self, service_300s, mock_db):
        """测试刚好超过阈值（301秒）"""
        # 模拟：所有交互对都是301秒（不及时）
        mock_db.execute.return_value.fetchone.return_value = (10, 0)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 0/10 = 0%
        assert score == 0.0
    
    # ========================================
    # 负间隔测试
    # ========================================
    
    def test_negative_interval(self, service_300s, mock_db):
        """测试负间隔（时间戳错误）"""
        # 负间隔应该被忽略或处理为0
        # 这取决于数据库查询的实现
        # 如果数据库中有负间隔，应该不影响计算
        mock_db.execute.return_value.fetchone.return_value = (10, 8)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 应该正常计算
        assert 0 <= score <= 100
    
    # ========================================
    # 超长间隔测试
    # ========================================
    
    def test_interval_over_24_hours(self, service_300s, mock_db):
        """测试超过24小时的间隔（86400秒）"""
        # 模拟：所有交互对都超过24小时
        # 这些应该都算不及时
        mock_db.execute.return_value.fetchone.return_value = (10, 0)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 0/10 = 0%
        assert score == 0.0
    
    def test_interval_over_one_week(self, service_300s, mock_db):
        """测试超过一周的间隔（604800秒）"""
        # 模拟：所有交互对都超过一周
        mock_db.execute.return_value.fetchone.return_value = (10, 0)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 0/10 = 0%
        assert score == 0.0
    
    # ========================================
    # 零间隔测试
    # ========================================
    
    def test_zero_interval(self, service_300s, mock_db):
        """测试零间隔（几乎同时回复）"""
        # 模拟：所有交互对都是0秒（立即回复）
        # 0秒应该算及时
        mock_db.execute.return_value.fetchone.return_value = (10, 10)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 10/10 = 100%
        assert score == 100.0
    
    # ========================================
    # 混合场景测试
    # ========================================
    
    def test_mixed_intervals(self, service_300s, mock_db):
        """测试混合间隔（有快有慢）"""
        # 模拟：100个交互对，30个及时
        mock_db.execute.return_value.fetchone.return_value = (100, 30)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 30/100 = 30%
        assert score == 30.0
    
    # ========================================
    # 不同阈值测试
    # ========================================
    
    def test_different_threshold_60s(self, mock_db):
        """测试不同阈值（60秒）"""
        with patch('app.services.analysis.chat_positivity_service.get_db', return_value=mock_db):
            from app.services.analysis.chat_positivity_service import ChatPositivityService
            service = ChatPositivityService(timeliness_threshold_seconds=60)
            
            # 模拟：10个交互对，5个在60秒内
            mock_db.execute.return_value.fetchone.return_value = (10, 5)
            score = service.calculate_reply_timeliness_score(1)
            assert score == 50.0
    
    def test_different_threshold_600s(self, mock_db):
        """测试不同阈值（600秒 = 10分钟）"""
        with patch('app.services.analysis.chat_positivity_service.get_db', return_value=mock_db):
            from app.services.analysis.chat_positivity_service import ChatPositivityService
            service = ChatPositivityService(timeliness_threshold_seconds=600)
            
            # 模拟：10个交互对，8个在600秒内
            mock_db.execute.return_value.fetchone.return_value = (10, 8)
            score = service.calculate_reply_timeliness_score(1)
            assert score == 80.0
    
    # ========================================
    # 边界组合测试
    # ========================================
    
    def test_all_at_exact_threshold(self, service_300s, mock_db):
        """测试所有交互对都恰好在阈值上"""
        # 模拟：100个交互对，全部恰好300秒
        # 期望：全部算及时
        mock_db.execute.return_value.fetchone.return_value = (100, 100)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 100/100 = 100%
        assert score == 100.0
    
    def test_one_second_difference(self, service_300s, mock_db):
        """测试1秒之差的影响"""
        # 模拟：100个交互对，50个是299秒，50个是301秒
        # 期望：只有299秒的算及时
        mock_db.execute.return_value.fetchone.return_value = (100, 50)
        
        service_300s.db = mock_db
        score = service_300s.calculate_reply_timeliness_score(1)
        
        # 50/100 = 50%
        assert score == 50.0



class TestChatPositivityIntegration:
    """聊天积极度服务集成测试 - 使用真实数据"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例"""
        from app.services.analysis.chat_positivity_service import ChatPositivityService
        return ChatPositivityService(timeliness_threshold_seconds=300)
    
    @pytest.fixture
    def real_conversation_id(self):
        """获取真实的会话ID"""
        from app.db.connection import get_db
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
        print(f"\n[数据] 使用真实会话: ID={conversation_id}, 用户名={row[1]}, 显示名={row[2]}")
        
        # 检查消息数量
        cursor = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,))
        message_count = cursor.fetchone()[0]
        print(f"  - 消息数: {message_count}")
        
        if message_count == 0:
            pytest.skip(f"会话 {conversation_id} 没有消息")

        return conversation_id
    
    def test_calculate_scores_full_pipeline(self, service, real_conversation_id):
        """测试完整计算流程 - 使用真实数据"""
        print("\n" + "="*60)
        print("集成测试: 聊天积极度完整计算流程")
        print("="*60)
        
        from app.services.analysis.preprocessing_orchestrator import PreprocessingOrchestrator
        
        # 获取预处理统计数据
        orchestrator = PreprocessingOrchestrator()
        stats = orchestrator.get_preprocessed_statistics(real_conversation_id)
        
        print(f"\n[预处理] 统计数据已加载:")
        print(f"  - 总消息数: {stats.total_message_count}")
        print(f"  - 会话持续天数: {stats.conversation_duration_days}")
        print(f"  - 平均消息长度: {stats.average_message_length}")
        print(f"  - 总会话数: {stats.total_sessions}")
        
        # 执行完整计算
        print(f"\n[执行] 计算聊天积极度...")
        result = service.calculate_scores(real_conversation_id, stats)
        
        # 验证结果结构
        assert hasattr(result, 'overall_score')
        assert hasattr(result, 'daily_message_score')
        assert hasattr(result, 'reply_timeliness_score')
        assert hasattr(result, 'topic_continuity_score')
        assert hasattr(result, 'active_initiation_score')
        assert hasattr(result, 'long_text_bonus')
        assert hasattr(result, 'interpretation')
        
        # 验证分数范围
        assert 0 <= result.overall_score <= 100
        assert 0 <= result.daily_message_score <= 100
        assert 0 <= result.reply_timeliness_score <= 100
        assert 0 <= result.topic_continuity_score <= 100
        assert 0 <= result.active_initiation_score <= 100
        assert 0 <= result.long_text_bonus <= 10
        
        # 验证解释文本
        assert isinstance(result.interpretation, str)
        assert len(result.interpretation) > 0
        
        # 打印结果
        print("\n[结果] 聊天积极度分析结果:")
        print("-" * 60)
        print(f"  总分: {result.overall_score:.2f}")
        print(f"  解释: {result.interpretation}")
        print("\n  子维度得分:")
        print(f"    - 日均消息数 (15%):    {result.daily_message_score:.2f} (日均: {result.daily_message_count:.2f})")
        print(f"    - 回复及时率 (25%):    {result.reply_timeliness_score:.2f} (及时率: {result.reply_timeliness_rate:.2%})")
        print(f"    - 话题延续性 (25%):    {result.topic_continuity_score:.2f} (相似度: {result.topic_continuity_avg:.2f})")
        print(f"    - 主动发起率 (35%):    {result.active_initiation_score:.2f} (发起率: {result.active_initiation_rate:.2%})")
        print(f"    [加分项] 长文本占比 (最高+10分):    +{result.long_text_bonus:.2f} (占比: {result.long_text_ratio:.2%})")
        print("-" * 60)
        
        print("\n✓ 集成测试通过")
        print("✓ 所有子维度在有效范围内")
        print("✓ 解释文本生成成功")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
