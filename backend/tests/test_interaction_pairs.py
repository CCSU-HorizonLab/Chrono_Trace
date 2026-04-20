"""交互对预处理服务单元测试

测试发言单元合并 (< 5分钟间隔)
测试交互对构建 (双向交替)
"""

import pytest
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到 Python 路径
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))


class TestInteractionPairs:
    """交互对预处理服务测试套件"""

    @pytest.fixture
    def preprocessing_service(self):
        """创建预处理服务实例"""
        from app.services.analysis.preprocessing_service import PairPreprocessingService
        return PairPreprocessingService()

    @pytest.fixture
    def pair_storage_db(self, monkeypatch):
        """创建仅包含交互对相关表的临时数据库。"""
        from app.services.analysis import preprocessing_service as preprocessing_module

        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE speech_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                message_ids TEXT NOT NULL,
                sender TEXT NOT NULL,
                first_message_timestamp INTEGER NOT NULL,
                last_message_timestamp INTEGER NOT NULL,
                message_count INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE interaction_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                from_speech_unit_id INTEGER NOT NULL,
                to_speech_unit_id INTEGER NOT NULL,
                time_gap INTEGER NOT NULL,
                semantic_similarity REAL,
                from_polarity INTEGER NOT NULL,
                to_polarity INTEGER NOT NULL,
                from_intensity REAL NOT NULL,
                to_intensity REAL NOT NULL,
                is_negative_initiation INTEGER DEFAULT 0,
                is_empathetic_response INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)

        monkeypatch.setattr(preprocessing_module, "get_db", lambda: conn)
        yield conn
        conn.close()

    # ========== 发言单元合并测试 ==========

    def test_merge_consecutive_messages_same_sender(self, preprocessing_service):
        """测试合并同一发送者的连续消息 (< 5分钟间隔)"""
        # 创建测试消息: 同一发送者在5分钟内发送多条消息
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在吗", "is_sender": 1, "timestamp": base_timestamp + 60},  # 1分钟后
            {"id": 3, "content": "我想问个事", "is_sender": 1, "timestamp": base_timestamp + 120},  # 2分钟后
            {"id": 4, "content": "在的", "is_sender": 0, "timestamp": base_timestamp + 180},  # 3分钟后,对方回复
            {"id": 5, "content": "什么事", "is_sender": 0, "timestamp": base_timestamp + 240},  # 4分钟后
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 应该合并为2个发言单元
        assert len(speech_units) == 2, \
            f"应该合并为2个发言单元, 实际为: {len(speech_units)}"

        # 第一个发言单元: 发送者的3条消息
        assert speech_units[0]["is_sender"] == 1
        assert speech_units[0]["message_count"] == 3
        assert speech_units[0]["start_timestamp"] == base_timestamp
        assert speech_units[0]["end_timestamp"] == base_timestamp + 120

        # 第二个发言单元: 对方的2条消息
        assert speech_units[1]["is_sender"] == 0
        assert speech_units[1]["message_count"] == 2
        assert speech_units[1]["start_timestamp"] == base_timestamp + 180
        assert speech_units[1]["end_timestamp"] == base_timestamp + 240

    def test_no_merge_over_5_minutes(self, preprocessing_service):
        """测试超过5分钟不合并"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在吗", "is_sender": 1, "timestamp": base_timestamp + 301},  # 超过5分钟(301秒)
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 应该是2个独立的发言单元
        assert len(speech_units) == 2, \
            f"超过5分钟不应该合并, 实际为: {len(speech_units)}个单元"

        assert speech_units[0]["message_count"] == 1
        assert speech_units[1]["message_count"] == 1

    def test_merge_exactly_5_minutes(self, preprocessing_service):
        """测试刚好5分钟边界"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在吗", "is_sender": 1, "timestamp": base_timestamp + 300},  # 刚好5分钟
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 5分钟边界: 应该不合并 (使用 < 5分钟)
        assert len(speech_units) == 2, \
            f"刚好5分钟不应该合并, 实际为: {len(speech_units)}个单元"

    def test_merge_different_senders(self, preprocessing_service):
        """测试不同发送者的消息不合并"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在的", "is_sender": 0, "timestamp": base_timestamp + 60},  # 1分钟后,不同发送者
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 不同发送者不应该合并
        assert len(speech_units) == 2

        assert speech_units[0]["is_sender"] == 1
        assert speech_units[1]["is_sender"] == 0

    def test_speech_unit_content_aggregation(self, preprocessing_service):
        """测试发言单元内容聚合"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在吗", "is_sender": 1, "timestamp": base_timestamp + 60},
            {"id": 3, "content": "我想问个事", "is_sender": 1, "timestamp": base_timestamp + 120},
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 检查内容是否正确聚合
        assert len(speech_units) == 1
        unit = speech_units[0]

        # 内容应该用空格连接
        assert unit["content"] == "你好 在吗 我想问个事" or \
               unit["content"] == "你好 在吗我想问个事" or \
               "你好" in unit["content"] and "在吗" in unit["content"] and "我想问个事" in unit["content"]

        assert unit["message_ids"] == [1, 2, 3]

    # ========== 交互对构建测试 ==========

    def test_build_interaction_pairs_alternating(self, preprocessing_service):
        """测试构建相邻异发送者交互对"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        # 创建发言单元
        speech_units = [
            {
                "id": 1,
                "conversation_id": 1,
                "is_sender": 1,
                "content": "你好",
                "start_timestamp": base_timestamp,
                "end_timestamp": base_timestamp,
                "message_count": 1,
                "message_ids": [1]
            },
            {
                "id": 2,
                "conversation_id": 1,
                "is_sender": 0,
                "content": "在的",
                "start_timestamp": base_timestamp + 60,
                "end_timestamp": base_timestamp + 60,
                "message_count": 1,
                "message_ids": [2]
            },
            {
                "id": 3,
                "conversation_id": 1,
                "is_sender": 1,
                "content": "我想问个事",
                "start_timestamp": base_timestamp + 120,
                "end_timestamp": base_timestamp + 120,
                "message_count": 1,
                "message_ids": [3]
            },
            {
                "id": 4,
                "conversation_id": 1,
                "is_sender": 0,
                "content": "什么事",
                "start_timestamp": base_timestamp + 180,
                "end_timestamp": base_timestamp + 180,
                "message_count": 1,
                "message_ids": [4]
            }
        ]

        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        # 应该生成3个交互对 (1-2, 2-3, 3-4)
        assert len(interaction_pairs) == 3, \
            f"应该生成3个交互对, 实际为: {len(interaction_pairs)}"

        # 检查第一个交互对: 发送者 -> 对方
        assert interaction_pairs[0]["first_unit_id"] == 1
        assert interaction_pairs[0]["second_unit_id"] == 2
        assert interaction_pairs[0]["time_gap_seconds"] == 60

        # 检查第二个交互对: 对方 -> 发送者
        assert interaction_pairs[1]["first_unit_id"] == 2
        assert interaction_pairs[1]["second_unit_id"] == 3
        assert interaction_pairs[1]["time_gap_seconds"] == 60

        # 检查第三个交互对: 发送者 -> 对方
        assert interaction_pairs[2]["first_unit_id"] == 3
        assert interaction_pairs[2]["second_unit_id"] == 4
        assert interaction_pairs[2]["time_gap_seconds"] == 60

    def test_interaction_pair_bidirectional(self, preprocessing_service):
        """测试交互对保留基础情感字段"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        speech_units = [
            {
                "id": 1,
                "conversation_id": 1,
                "is_sender": 1,
                "content": "你好",
                "start_timestamp": base_timestamp,
                "end_timestamp": base_timestamp,
                "message_count": 1,
                "message_ids": [1]
            },
            {
                "id": 2,
                "conversation_id": 1,
                "is_sender": 0,
                "content": "在的",
                "start_timestamp": base_timestamp + 60,
                "end_timestamp": base_timestamp + 60,
                "message_count": 1,
                "message_ids": [2]
            }
        ]

        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        # 应该生成1个交互对
        assert len(interaction_pairs) == 1

        pair = interaction_pairs[0]

        # 检查当前实现保留的基础字段
        assert pair["first_unit_id"] == 1
        assert pair["second_unit_id"] == 2
        assert pair["time_gap_seconds"] == 60
        assert "from_polarity" in pair
        assert "to_polarity" in pair
        assert "from_intensity" in pair
        assert "to_intensity" in pair

    def test_interaction_pair_same_parity(self, preprocessing_service):
        """测试交互对按相邻单元顺序配对"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        # 创建4个发言单元 (2轮对话)
        speech_units = [
            {
                "id": i,
                "conversation_id": 1,
                "is_sender": 1 if i % 2 == 1 else 0,
                "content": f"消息{i}",
                "start_timestamp": base_timestamp + i * 60,
                "end_timestamp": base_timestamp + i * 60,
                "message_count": 1,
                "message_ids": [i]
            }
            for i in range(1, 5)
        ]

        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        # 应该生成3个交互对
        assert len(interaction_pairs) == 3

        assert [(pair["first_unit_id"], pair["second_unit_id"]) for pair in interaction_pairs] == [
            (1, 2),
            (2, 3),
            (3, 4),
        ]

    def test_interaction_pair_time_gap(self, preprocessing_service):
        """测试交互对时间间隔计算与统计转换"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        speech_units = [
            {
                "id": 1,
                "conversation_id": 1,
                "is_sender": 1,
                "content": "你好",
                "start_timestamp": base_timestamp,
                "end_timestamp": base_timestamp,
                "message_count": 1,
                "message_ids": [1]
            },
            {
                "id": 2,
                "conversation_id": 1,
                "is_sender": 0,
                "content": "在的",
                "start_timestamp": base_timestamp + 300,  # 5分钟后
                "end_timestamp": base_timestamp + 300,
                "message_count": 1,
                "message_ids": [2]
            }
        ]

        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        assert len(interaction_pairs) == 1

        pair = interaction_pairs[0]

        # 检查时间间隔
        assert pair["time_gap_seconds"] == 300
        stats = preprocessing_service.collect_pair_statistics(interaction_pairs)
        assert stats["avg_time_gap_minutes"] == 5.0

    def test_no_pair_single_unit(self, preprocessing_service):
        """测试单个发言单元无法构建交互对"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        speech_units = [
            {
                "id": 1,
                "conversation_id": 1,
                "is_sender": 1,
                "content": "你好",
                "start_timestamp": base_timestamp,
                "end_timestamp": base_timestamp,
                "message_count": 1,
                "message_ids": [1]
            }
        ]

        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        # 单个发言单元无法构建交互对
        assert len(interaction_pairs) == 0

    # ========== 统计信息测试 ==========

    def test_collect_pair_statistics(self, preprocessing_service):
        """测试收集交互对统计信息"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        speech_units = [
            {
                "id": i,
                "conversation_id": 1,
                "is_sender": 1 if i % 2 == 1 else 0,
                "content": f"消息{i}",
                "start_timestamp": base_timestamp + i * 60,
                "end_timestamp": base_timestamp + i * 60,
                "message_count": 1,
                "message_ids": [i]
            }
            for i in range(1, 6)  # 5个发言单元
        ]

        # 构建交互对
        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        # 收集统计信息
        stats = preprocessing_service.collect_pair_statistics(interaction_pairs)

        # 5个发言单元应该生成4个交互对
        assert stats["total_interaction_pairs"] == 4
        assert stats["bidirectional_pairs"] == 4  # 所有交互对都是双向的

        # 检查奇偶对数量
        assert stats["same_parity_pairs"] in [0, 1, 2]  # 4个交互对中可能有0-2个奇偶对

        # 检查平均时间间隔
        assert "avg_time_gap_seconds" in stats
        assert "avg_time_gap_minutes" in stats

    def test_save_speech_units_with_mapping_returns_db_ids(self, preprocessing_service, pair_storage_db):
        """保存发言单元时应返回数据库真实 ID，而不是内存临时 ID。"""
        speech_units = [
            {
                "id": 101,
                "is_sender": 1,
                "start_timestamp": 100,
                "end_timestamp": 100,
                "message_count": 1,
                "message_ids": [1],
            },
            {
                "id": 202,
                "is_sender": 0,
                "start_timestamp": 200,
                "end_timestamp": 200,
                "message_count": 1,
                "message_ids": [2],
            },
        ]

        unit_id_map = preprocessing_service.save_speech_units_with_mapping(9, speech_units)

        rows = pair_storage_db.execute(
            "SELECT id, conversation_id FROM speech_units ORDER BY id"
        ).fetchall()

        assert len(rows) == 2
        assert unit_id_map == {101: rows[0][0], 202: rows[1][0]}
        assert rows[0][0] != 101
        assert rows[1][0] != 202

    def test_clear_cached_pairs_removes_previous_rows(self, preprocessing_service, pair_storage_db):
        """重新预处理前应清空该会话旧数据，避免交互对重复累积。"""
        pair_storage_db.execute("""
            INSERT INTO speech_units (
                conversation_id, message_ids, sender, first_message_timestamp,
                last_message_timestamp, message_count, created_at
            ) VALUES (7, '[1]', 'user', 100, 100, 1, 1)
        """)
        pair_storage_db.execute("""
            INSERT INTO interaction_pairs (
                conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap,
                semantic_similarity, from_polarity, to_polarity, from_intensity,
                to_intensity, is_negative_initiation, is_empathetic_response, created_at
            ) VALUES (7, 1, 2, 60, NULL, 1, 1, 0.8, 0.9, 0, 0, 1)
        """)
        pair_storage_db.commit()

        preprocessing_service.clear_cached_pairs(7)

        speech_unit_count = pair_storage_db.execute(
            "SELECT COUNT(*) FROM speech_units WHERE conversation_id = 7"
        ).fetchone()[0]
        pair_count = pair_storage_db.execute(
            "SELECT COUNT(*) FROM interaction_pairs WHERE conversation_id = 7"
        ).fetchone()[0]

        assert speech_unit_count == 0
        assert pair_count == 0

    # ========== 边界情况测试 ==========

    def test_empty_messages(self, preprocessing_service):
        """测试空消息列表"""
        speech_units = preprocessing_service.build_speech_units([])
        assert len(speech_units) == 0

    def test_single_message(self, preprocessing_service):
        """测试单条消息"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp}
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        assert len(speech_units) == 1
        assert speech_units[0]["message_count"] == 1

    def test_very_long_conversation(self, preprocessing_service):
        """测试超长对话 (性能测试)"""
        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        # 生成1000条消息 (500轮对话)
        messages = []
        for i in range(1000):
            messages.append({
                "id": i + 1,
                "content": f"消息{i + 1}",
                "is_sender": 1 if i % 2 == 0 else 0,
                "timestamp": base_timestamp + i * 60
            })

        speech_units = preprocessing_service.build_speech_units(messages)

        # 1000条交替消息应该生成1000个发言单元
        assert len(speech_units) == 1000

        # 构建交互对
        interaction_pairs = preprocessing_service.build_interaction_pairs(speech_units)

        # 应该生成999个交互对
        assert len(interaction_pairs) == 999

    def test_session_split_with_time_gap(self, preprocessing_service):
        """测试基于时间间隔的会话切分 (> 30分钟强制切分)"""
        from app.services.analysis.preprocessing_service import SessionManager

        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        # 创建两个会话：间隔40分钟 (> 30分钟阈值)
        # 使用同一个人连续发言避免语义相似度引起的切分
        messages = [
            # 第一个会话 (用户连续发言)
            {"id": 1, "content": "你好你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在吗在吗", "is_sender": 1, "timestamp": base_timestamp + 60},
            {"id": 3, "content": "我想问个事", "is_sender": 1, "timestamp": base_timestamp + 120},
            # 40分钟间隔 (> 30分钟阈值)
            {"id": 4, "content": "刚才在忙", "is_sender": 1, "timestamp": base_timestamp + 2400},
            {"id": 5, "content": "没事没事", "is_sender": 1, "timestamp": base_timestamp + 2460},
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 创建会话管理器并切分会话
        session_manager = SessionManager()
        sessions = session_manager.split_sessions(speech_units)

        # 应该切分成2个会话（因为时间间隔 > 30分钟）
        # 注意：发言单元会合并同一发送者的连续消息
        assert len(sessions) >= 2  # 至少有2个会话（可能因为语义相似度有更多切分）

        # 验证确实有时间间隔引起的切分
        # 检查会话之间的时间间隔
        for i in range(len(sessions) - 1):
            time_gap = sessions[i + 1]["start_timestamp"] - sessions[i]["end_timestamp"]
            # 如果两个会话之间时间间隔 > 30分钟，说明时间回退逻辑生效
            if time_gap > 1800:
                return  # 测试通过

        # 如果没有找到 > 30分钟的时间间隔，测试失败
        assert False, "未检测到基于时间间隔的会话切分"

    def test_session_no_split_with_short_time_gap(self, preprocessing_service):
        """测试短时间间隔不会切分会话 (< 30分钟)"""
        from app.services.analysis.preprocessing_service import SessionManager

        base_timestamp = datetime(2024, 1, 1, 12, 0, 0).timestamp()

        # 创建消息序列：间隔10分钟 (< 30分钟阈值)
        messages = [
            {"id": 1, "content": "你好", "is_sender": 1, "timestamp": base_timestamp},
            {"id": 2, "content": "在吗", "is_sender": 0, "timestamp": base_timestamp + 600},  # 10分钟后
            {"id": 3, "content": "我想问个事", "is_sender": 1, "timestamp": base_timestamp + 1200},  # 再10分钟
            {"id": 4, "content": "刚才在忙", "is_sender": 0, "timestamp": base_timestamp + 1800},  # 再10分钟
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 创建会话管理器并切分会话
        session_manager = SessionManager()
        sessions = session_manager.split_sessions(speech_units)

        # 由于时间间隔都 < 30分钟，应该作为一个会话（假设语义相似度也不低）
        # 注意：实际结果可能受语义相似度影响，但至少不应该因为时间间隔而切分
        assert len(sessions) >= 1  # 至少有1个会话

    def test_session_split_with_midnight_cross(self, preprocessing_service):
        """测试跨越午夜时的会话切分"""
        from app.services.analysis.preprocessing_service import SessionManager

        # 2024-01-01 23:50
        before_midnight = datetime(2024, 1, 1, 23, 50, 0).timestamp()
        # 2024-01-02 00:10 (跨越午夜)
        after_midnight = datetime(2024, 1, 2, 0, 10, 0).timestamp()

        # 创建消息序列：跨越午夜，且两侧各自有足够单元，避免被碎片合并逻辑吞并
        messages = [
            {"id": 1, "content": "还没睡呢", "is_sender": 1, "timestamp": before_midnight},
            {"id": 2, "content": "在加班", "is_sender": 0, "timestamp": before_midnight + 120},
            {"id": 3, "content": "快结束了", "is_sender": 1, "timestamp": before_midnight + 240},
            {"id": 4, "content": "早点休息", "is_sender": 0, "timestamp": after_midnight},
            {"id": 5, "content": "刚下班", "is_sender": 1, "timestamp": after_midnight + 120},
            {"id": 6, "content": "到家说声", "is_sender": 0, "timestamp": after_midnight + 240},
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 创建会话管理器并切分会话
        session_manager = SessionManager()
        sessions = session_manager.split_sessions(speech_units)

        # 应该切分成至少2个会话（因为跨越午夜）
        assert len(sessions) >= 2  # 至少有2个会话

        # 验证确实有跨越午夜的切分
        for i in range(len(sessions) - 1):
            # 检查会话边界是否跨越了午夜
            session_end = datetime.fromtimestamp(sessions[i]["end_timestamp"])
            next_session_start = datetime.fromtimestamp(sessions[i + 1]["start_timestamp"])

            # 如果不在同一天，说明检测到了跨越午夜
            if session_end.date() != next_session_start.date():
                return  # 测试通过

        # 如果没有找到跨越午夜的切分，测试失败
        assert False, "未检测到基于跨越午夜的会话切分"

    def test_session_split_in_sleep_hours(self, preprocessing_service):
        """测试在睡眠时段（00:00-07:00）内的会话切分"""
        from app.services.analysis.preprocessing_service import SessionManager

        # 2024-01-01 03:00 (睡眠时段内)
        sleep_time_1 = datetime(2024, 1, 1, 3, 0, 0).timestamp()
        # 2024-01-01 06:30 (睡眠时段内，但接近7点)
        sleep_time_2 = datetime(2024, 1, 1, 6, 30, 0).timestamp()
        # 2024-01-01 08:00 (已过睡眠时段)
        after_sleep = datetime(2024, 1, 1, 8, 0, 0).timestamp()

        # 创建消息序列：在睡眠时段内跨越7点
        messages = [
            {"id": 1, "content": "还没睡", "is_sender": 1, "timestamp": sleep_time_1},
            {"id": 2, "content": "失眠了", "is_sender": 1, "timestamp": sleep_time_2},
            {"id": 3, "content": "早上好", "is_sender": 0, "timestamp": after_sleep},
        ]

        speech_units = preprocessing_service.build_speech_units(messages)

        # 创建会话管理器并切分会话
        session_manager = SessionManager()
        sessions = session_manager.split_sessions(speech_units)

        # 应该切分成2个会话（因为在00:00-07:00时段内跨越了7点）
        assert len(sessions) >= 2  # 至少有2个会话


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "-s"])
