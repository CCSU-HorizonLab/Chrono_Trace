# -*- coding: utf-8 -*-
"""
测试自动特征提取功能
验证数据导入后是否自动触发特征提取
"""
import sys
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.services.wechat.ingest_service import WeChatIngestService


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_auto_extract_features():
    """测试自动特征提取功能"""
    print_section("自动特征提取功能测试")

    service = WeChatIngestService()

    # 测试自动提取
    print("[INFO] 开始测试自动特征提取...")
    print()

    try:
        result = service._auto_extract_features()

        print(f"\n[OK] 自动特征提取完成!")
        print(f"  总会话数: {result['total_conversations']}")
        print(f"  处理成功: {result['processed']}")
        print(f"  已有特征跳过: {result['skipped']}")
        print(f"  失败: {result.get('failed', 0)}")

        if result.get('error'):
            print(f"  错误: {result['error']}")

        # 验证数据库
        print_section("验证数据库写入")
        from app.db.connection import get_db
        db = get_db()

        cursor = db.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]
        print(f"  sessions表: {session_count}条记录")

        cursor = db.execute("SELECT COUNT(*) FROM response_times")
        rt_count = cursor.fetchone()[0]
        print(f"  response_times表: {rt_count}条记录")

        cursor = db.execute("SELECT COUNT(*) FROM initiative_stats")
        ini_count = cursor.fetchone()[0]
        print(f"  initiative_stats表: {ini_count}条记录")

        cursor = db.execute("SELECT COUNT(*) FROM word_counts")
        wc_count = cursor.fetchone()[0]
        print(f"  word_counts表: {wc_count}条记录")

        # 获取示例会话
        if session_count > 0:
            print_section("示例会话")
            cursor = db.execute("""
                SELECT s.id, c.display_name, s.start_time, s.end_time, s.message_count, s.initiator
                FROM sessions s
                JOIN conversations c ON s.conversation_id = c.id
                ORDER BY s.start_time DESC
                LIMIT 3
            """)

            for i, row in enumerate(cursor.fetchall(), 1):
                import time
                sid, name, start, end, count, initiator = row
                duration = (end - start) / 60
                initiator_str = "我" if initiator == "user" else "对方"
                print(f"  会话{i}: {name}")
                print(f"    时间: {time.strftime('%Y-%m-%d %H:%M', time.localtime(start))}")
                print(f"    时长: {duration:.1f}分钟")
                print(f"    消息数: {count}")
                print(f"    发起者: {initiator_str}")

        print_section("[OK] 测试完成")

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError("自动特征提取测试失败") from e


if __name__ == "__main__":
    print("="*60)
    print("  Auto Feature Extraction Test")
    print("="*60)

    test_auto_extract_features()

    print("\n[OK] 测试脚本执行完毕!")
