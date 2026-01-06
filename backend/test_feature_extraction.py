"""
特征提取服务测试脚本
测试会话切分、响应时间、主动性统计、字数统计功能
"""
import sys
import time
from pathlib import Path

# 添加项目路径到sys.path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.services.analysis.analysis_service import AnalysisService


def print_section(title: str):
    """打印分隔线"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_feature_extraction(conversation_id: int):
    """测试特征提取功能"""
    print_section(f"测试对话 ID={conversation_id}")

    service = AnalysisService()

    # 1. 检查对话是否存在
    import sqlite3
    db = sqlite3.connect(backend_dir / "data" / "chrono_trace.db")
    cursor = db.execute("""
        SELECT id, display_name, message_count
        FROM conversations
        WHERE id = ?
    """, (conversation_id,))
    conv = cursor.fetchone()
    db.close()

    if not conv:
        print(f"❌ 对话 ID={conversation_id} 不存在")
        return

    print(f"📊 对话信息:")
    print(f"  ID: {conv[0]}")
    print(f"  名称: {conv[1]}")
    print(f"  消息总数: {conv[2]}")

    # 2. 执行特征提取
    print_section("1️⃣ 开始特征提取")
    start_time = time.time()

    try:
        result = service.extract_features(conversation_id)

        elapsed_time = time.time() - start_time
        print(f"✅ 特征提取完成！耗时: {elapsed_time:.2f}秒")
        print(f"  任务ID: {result['task_id']}")

        # 3. 显示会话切分结果
        print_section("2️⃣ 会话切分结果")
        sessions = result['sessions']
        print(f"✅ 检测到 {len(sessions)} 个会话")

        if sessions:
            print(f"\n前3个会话:")
            for i, session in enumerate(sessions[:3], 1):
                start_ts = session['start_time']
                end_ts = session['end_time']
                duration = end_ts - start_ts
                initiator = "我" if session['initiator'] == 'user' else "对方"

                print(f"  会话{i}:")
                print(f"    发起者: {initiator}")
                print(f"    时间: {time.strftime('%Y-%m-%d %H:%M', time.localtime(start_ts))} -> {time.strftime('%H:%M', time.localtime(end_ts))}")
                print(f"    时长: {duration}秒 ({duration/60:.1f}分钟)")
                print(f"    消息数: {session['message_count']}")

        # 4. 显示响应时间统计
        print_section("3️⃣ 响应时间统计")
        rt_stats = result['response_time_stats']
        print(f"  有效响应次数: {rt_stats['count']}")
        print(f"  平均响应时间: {rt_stats['avg']:.1f}秒 ({rt_stats['avg']/60:.1f}分钟)" if rt_stats['avg'] else "  平均响应时间: 无数据")
        print(f"  中位数: {rt_stats['median']:.1f}秒 ({rt_stats['median']/60:.1f}分钟)" if rt_stats['median'] else "  中位数: 无数据")
        print(f"  最快: {rt_stats['min']:.1f}秒" if rt_stats['min'] else "  最快: 无数据")
        print(f"  最慢: {rt_stats['max']:.1f}秒 ({rt_stats['max']/60:.1f}分钟)" if rt_stats['max'] else "  最慢: 无数据")
        print(f"  异常响应: {rt_stats['abnormal_count']}个")

        # 5. 显示主动性统计
        print_section("4️⃣ 主动性统计")
        ini_stats = result['initiative_stats']
        print(f"  总会话数: {ini_stats['total_sessions']}")
        print(f"  我主动发起: {ini_stats['user_initiated_sessions']}个")
        print(f"  对方主动发起: {ini_stats['other_initiated_sessions']}个")
        print(f"  对方主动率: {ini_stats['initiative_rate']*100:.1f}%")
        print(f"  解读: {ini_stats['interpretation']}")

        # 6. 显示字数统计
        print_section("5️⃣ 字数统计")
        wc = result['word_counts']['overall']
        print(f"  我的字数: {wc['user_char_count']}")
        print(f"  对方字数: {wc['other_char_count']}")
        print(f"  字数比: {wc['char_ratio']:.2f}")
        print(f"  解读: {wc['interpretation']}")

        # 7. 验证数据已写入数据库
        print_section("6️⃣ 验证数据库写入")
        db = sqlite3.connect(backend_dir / "data" / "chrono_trace.db")

        cursor = db.execute("SELECT COUNT(*) FROM sessions WHERE conversation_id = ?", (conversation_id,))
        session_count = cursor.fetchone()[0]
        print(f"  sessions表记录: {session_count}条")

        cursor = db.execute("SELECT COUNT(*) FROM response_times WHERE conversation_id = ?", (conversation_id,))
        rt_count = cursor.fetchone()[0]
        print(f"  response_times表记录: {rt_count}条")

        cursor = db.execute("SELECT COUNT(*) FROM initiative_stats WHERE conversation_id = ?", (conversation_id,))
        ini_count = cursor.fetchone()[0]
        print(f"  initiative_stats表记录: {ini_count}条")

        cursor = db.execute("SELECT COUNT(*) FROM word_counts WHERE conversation_id = ?", (conversation_id,))
        wc_count = cursor.fetchone()[0]
        print(f"  word_counts表记录: {wc_count}条")

        db.close()

        print_section("✅ 测试完成")
        return True

    except Exception as e:
        print(f"❌ 特征提取失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multiple_conversations():
    """测试多个对话（性能测试）"""
    print_section("性能测试: 多个对话")

    service = AnalysisService()

    # 获取有足够消息的对话
    import sqlite3
    db = sqlite3.connect(backend_dir / "data" / "chrono_trace.db")
    cursor = db.execute("""
        SELECT id, display_name, message_count
        FROM conversations
        WHERE message_count >= 100
        ORDER BY message_count DESC
        LIMIT 5
    """)
    test_convs = cursor.fetchall()
    db.close()

    if not test_convs:
        print("⚠️ 没有找到消息数>=100的对话")
        return

    print(f"📊 将测试 {len(test_convs)} 个对话:")
    for conv in test_convs:
        print(f"  ID={conv[0]}, 名称={conv[1]}, 消息数={conv[2]}")

    total_start = time.time()
    success_count = 0

    for conv in test_convs:
        conv_id, name, msg_count = conv
        print(f"\n▶️ 测试对话 ID={conv_id} ({msg_count}条消息)...")

        start = time.time()
        try:
            result = service.extract_features(conv_id)
            elapsed = time.time() - start
            success_count += 1
            print(f"  ✅ 成功，耗时: {elapsed:.2f}秒")
        except Exception as e:
            print(f"  ❌ 失败: {e}")

    total_elapsed = time.time() - total_start

    print_section("性能测试结果")
    print(f"  成功: {success_count}/{len(test_convs)}")
    print(f"  总耗时: {total_elapsed:.2f}秒")
    print(f"  平均耗时: {total_elapsed/len(test_convs):.2f}秒/对话")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║         Chrono Trace - 特征提取服务测试                    ║
╚══════════════════════════════════════════════════════════╝
    """)

    # 测试1: 单个对话（选择一个有较多消息的对话）
    import sqlite3
    db = sqlite3.connect(backend_dir / "data" / "chrono_trace.db")
    cursor = db.execute("""
        SELECT id FROM conversations
        WHERE message_count >= 50
        ORDER BY message_count DESC
        LIMIT 1
    """)
    result = cursor.fetchone()
    db.close()

    if result:
        test_conv_id = result[0]
        test_feature_extraction(test_conv_id)
    else:
        print("⚠️ 没有找到测试数据（需要消息数>=50的对话）")

    # 测试2: 性能测试（可选）
    print("\n" + "="*60)
    choice = input("是否运行性能测试？(y/n): ").strip().lower()

    if choice == 'y':
        test_multiple_conversations()

    print("\n✅ 测试完成！")
