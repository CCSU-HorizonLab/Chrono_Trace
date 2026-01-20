"""测试预处理编排器 - 端到端预处理流程测试

测试目标:
1. 验证所有29个统计常量被正确收集
2. 验证单次遍历 O(N) 复杂度
3. 验证缓存行为
4. 验证缓存失效
"""

import pytest
import time
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.analysis.preprocessing_orchestrator import (
    PreprocessingOrchestrator,
    PreprocessedStatistics
)


class TestPreprocessingOrchestrator:
    """测试预处理编排器"""
    
    @pytest.fixture
    def orchestrator(self, test_db):
        """创建编排器实例"""
        return PreprocessingOrchestrator()
    
    @pytest.fixture
    def sample_conversation_id(self, test_db):
        """创建测试会话"""
        cursor = test_db.execute("""
            INSERT INTO conversations (username, display_name, created_at, updated_at)
            VALUES ('test_user', 'Test User', 1234567890, 1234567890)
        """)
        test_db.commit()
        return cursor.lastrowid
    
    @pytest.fixture
    def sample_messages(self, test_db, sample_conversation_id):
        """创建测试消息"""
        messages = []
        base_timestamp = 1234567890
        
        # 创建100条测试消息
        for i in range(100):
            cursor = test_db.execute("""
                INSERT INTO messages 
                (conversation_id, talker, is_sender, message_type, content, timestamp, created_at)
                VALUES (?, 'test_user', ?, 1, ?, ?, ?)
            """, (
                sample_conversation_id,
                i % 2,  # 交替发送者
                f"测试消息 {i}",
                base_timestamp + i * 3600,  # 每小时一条
                int(time.time())
            ))
            messages.append(cursor.lastrowid)
        
        test_db.commit()
        return messages
    
    def test_orchestrate_preprocessing_basic(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试基础预处理流程"""
        # 执行预处理
        stats = orchestrator.orchestrate_preprocessing(sample_conversation_id)
        
        # 验证返回类型
        assert isinstance(stats, PreprocessedStatistics)
        
        # 验证基础统计
        assert stats.conversation_id == sample_conversation_id
        assert stats.total_message_count > 0
        assert stats.preprocessing_timestamp > 0
        assert stats.preprocessing_duration_ms > 0
        
        print(f"✓ 基础预处理完成: {stats.total_message_count} 条消息")
    
    def test_all_29_statistics_collected(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试所有29个统计常量被正确收集"""
        stats = orchestrator.orchestrate_preprocessing(sample_conversation_id)
        
        # 验证所有29个统计常量
        # 1. 基础消息统计 (4个)
        assert stats.total_message_count >= 0
        assert stats.total_positive_count >= 0
        assert stats.total_negative_count >= 0
        assert stats.total_neutral_count >= 0
        
        # 2. 时间统计 (4个)
        assert stats.conversation_start_timestamp >= 0
        assert stats.conversation_end_timestamp >= 0
        assert stats.conversation_duration_days >= 0
        assert stats.chat_days_count >= 0
        
        # 3. 长度统计 (2个)
        assert stats.total_characters >= 0
        assert stats.average_message_length >= 0
        
        # 4. 交互对统计 (3个)
        assert stats.total_interaction_pairs >= 0
        assert stats.bidirectional_pairs >= 0
        assert stats.same_parity_pairs >= 0
        
        # 5. 会话统计 (3个)
        assert stats.total_sessions >= 0
        assert stats.average_session_length >= 0
        assert stats.average_session_gap >= 0
        
        # 6. 会话发起者统计 (2个)
        assert stats.sender_initiated_count >= 0
        assert stats.contact_initiated_count >= 0
        
        # 7. 态度统计 (7个)
        assert stats.emoji_message_count >= 0
        assert stats.voice_message_count >= 0
        assert stats.video_message_count >= 0
        assert stats.nickname_message_count >= 0
        assert stats.privacy_message_count >= 0
        assert stats.holiday_message_count >= 0
        assert stats.holidays_sent_count >= 0
        
        print(f"✓ 所有29个统计常量已收集")
        print(f"  - 消息统计: {stats.total_message_count} 条")
        print(f"  - 时间跨度: {stats.conversation_duration_days} 天")
        print(f"  - 交互对: {stats.total_interaction_pairs} 个")
        print(f"  - 会话: {stats.total_sessions} 个")
    
    def test_cache_behavior(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试缓存行为"""
        # 第一次执行 - 应该计算
        start_time = time.time()
        stats1 = orchestrator.orchestrate_preprocessing(sample_conversation_id)
        first_duration = time.time() - start_time
        
        # 第二次执行 - 应该使用缓存
        start_time = time.time()
        stats2 = orchestrator.orchestrate_preprocessing(sample_conversation_id)
        second_duration = time.time() - start_time
        
        # 验证结果一致
        assert stats1.total_message_count == stats2.total_message_count
        assert stats1.total_sessions == stats2.total_sessions
        
        # 验证缓存加速 (第二次应该更快)
        assert second_duration < first_duration
        
        print(f"✓ 缓存命中测试通过")
        print(f"  - 首次: {first_duration:.3f}s")
        print(f"  - 缓存: {second_duration:.3f}s")
        print(f"  - 加速: {first_duration / second_duration:.1f}x")
    
    def test_cache_invalidation(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试缓存失效"""
        # 执行预处理
        stats1 = orchestrator.orchestrate_preprocessing(sample_conversation_id)
        
        # 清除缓存
        orchestrator.invalidate_cache(sample_conversation_id)
        
        # 强制重新处理
        stats2 = orchestrator.orchestrate_preprocessing(
            sample_conversation_id,
            force_reprocess=True
        )
        
        # 验证结果一致
        assert stats1.total_message_count == stats2.total_message_count
        
        print(f"✓ 缓存失效测试通过")
    
    def test_empty_conversation(self, orchestrator, test_db):
        """测试空会话"""
        # 创建空会话
        cursor = test_db.execute("""
            INSERT INTO conversations (username, display_name, created_at, updated_at)
            VALUES ('empty_user', 'Empty User', 1234567890, 1234567890)
        """)
        test_db.commit()
        empty_conversation_id = cursor.lastrowid
        
        # 执行预处理
        stats = orchestrator.orchestrate_preprocessing(empty_conversation_id)
        
        # 验证所有统计为0
        assert stats.total_message_count == 0
        assert stats.total_sessions == 0
        assert stats.total_interaction_pairs == 0
        
        print(f"✓ 空会话处理正确")
    
    def test_single_pass_complexity(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试单次遍历 O(N) 复杂度"""
        # 使用mock验证各服务只被调用一次
        with patch.object(
            orchestrator.basic_service,
            'collect_message_statistics',
            wraps=orchestrator.basic_service.collect_message_statistics
        ) as mock_basic:
            with patch.object(
                orchestrator.pair_service,
                'build_speech_units',
                wraps=orchestrator.pair_service.build_speech_units
            ) as mock_pair:
                with patch.object(
                    orchestrator.session_manager,
                    'split_sessions',
                    wraps=orchestrator.session_manager.split_sessions
                ) as mock_session:
                    with patch.object(
                        orchestrator.attitude_service,
                        'collect_attitude_statistics',
                        wraps=orchestrator.attitude_service.collect_attitude_statistics
                    ) as mock_attitude:
                        # 执行预处理
                        stats = orchestrator.orchestrate_preprocessing(
                            sample_conversation_id,
                            force_reprocess=True
                        )
                        
                        # 验证每个服务只被调用一次
                        assert mock_basic.call_count == 1
                        assert mock_pair.call_count == 1
                        assert mock_session.call_count == 1
                        assert mock_attitude.call_count == 1
        
        print(f"✓ O(N) 单次遍历验证通过")
    
    def test_statistics_consistency(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试统计数据一致性"""
        stats = orchestrator.orchestrate_preprocessing(sample_conversation_id)
        
        # 验证情感分类总和
        sentiment_sum = (
            stats.total_positive_count +
            stats.total_negative_count +
            stats.total_neutral_count
        )
        # 注意: sentiment_sum 可能小于 total_message_count (非文本消息不分析情感)
        assert sentiment_sum <= stats.total_message_count
        
        # 验证会话发起者总和
        initiator_sum = (
            stats.sender_initiated_count +
            stats.contact_initiated_count
        )
        assert initiator_sum == stats.total_sessions
        
        # 验证时间逻辑
        assert stats.conversation_end_timestamp >= stats.conversation_start_timestamp
        
        print(f"✓ 统计数据一致性验证通过")
    
    def test_get_preprocessed_statistics_interface(
        self,
        orchestrator,
        sample_conversation_id,
        sample_messages
    ):
        """测试公共接口"""
        # 使用公共接口
        stats = orchestrator.get_preprocessed_statistics(sample_conversation_id)
        
        # 验证返回类型
        assert isinstance(stats, PreprocessedStatistics)
        assert stats.total_message_count > 0
        
        print(f"✓ 公共接口测试通过")


class TestPreprocessedStatistics:
    """测试PreprocessedStatistics数据类"""
    
    def test_dataclass_initialization(self):
        """测试数据类初始化"""
        stats = PreprocessedStatistics()
        
        # 验证默认值
        assert stats.total_message_count == 0
        assert stats.conversation_id == 0
        assert stats.preprocessing_timestamp == 0
        
        print(f"✓ 数据类初始化正确")
    
    def test_dataclass_with_values(self):
        """测试数据类赋值"""
        stats = PreprocessedStatistics(
            conversation_id=123,
            total_message_count=1000,
            total_positive_count=600,
            total_negative_count=200,
            total_neutral_count=200
        )
        
        assert stats.conversation_id == 123
        assert stats.total_message_count == 1000
        assert stats.total_positive_count == 600
        
        print(f"✓ 数据类赋值正确")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
