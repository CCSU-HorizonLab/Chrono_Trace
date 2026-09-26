"""
批量预处理现有消息脚本

用于预处理导入前的老数据或手动触发预处理

运行方式：
    python backend/preprocess_existing_messages.py [--limit 1000] [--conversation-id 123]
"""
import argparse
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.db.connection import get_db
from backend.app.services.analysis.preprocessing_service import PreprocessingService


def preprocess_all_messages(limit: int = 0, conversation_id: int = None):
    """批量预处理所有未缓存的消息"""
    print("=" * 60)
    print("开始批量预处理消息")
    print("=" * 60)
    
    db = get_db()
    preprocessor = PreprocessingService()
    
    try:
        # 查找未预处理的消息
        if conversation_id:
            print(f"\n🎯 仅处理会话 ID: {conversation_id}")
            sql = """
                SELECT m.id, m.conversation_id
                FROM messages m
                LEFT JOIN message_preprocessed mp ON m.id = mp.message_id
                WHERE mp.id IS NULL
                    AND m.message_type = 1
                    AND m.content IS NOT NULL
                    AND m.content != ''
                    AND m.conversation_id = ?
                ORDER BY m.conversation_id, m.timestamp
            """
            params = (conversation_id,)
        else:
            print(f"\n🌐 处理所有会话")
            sql = """
                SELECT m.id, m.conversation_id
                FROM messages m
                LEFT JOIN message_preprocessed mp ON m.id = mp.message_id
                WHERE mp.id IS NULL
                    AND m.message_type = 1
                    AND m.content IS NOT NULL
                    AND m.content != ''
                ORDER BY m.conversation_id, m.timestamp
            """
            params = ()
        
        if limit > 0:
            sql += f" LIMIT {limit}"
            print(f"⚠️  限制处理数量: {limit} 条")
        
        cursor = db.execute(sql, params)
        unprocessed = cursor.fetchall()
        
        if not unprocessed:
            print("\n✅ 没有需要预处理的消息")
            return
        
        print(f"\n📦 找到 {len(unprocessed)} 条未预处理的消息")
        
        # 按会话分组
        conv_messages = {}
        for msg_id, conv_id in unprocessed:
            if conv_id not in conv_messages:
                conv_messages[conv_id] = []
            conv_messages[conv_id].append(msg_id)
        
        print(f"📂 涉及 {len(conv_messages)} 个会话\n")
        
        # 批量预处理
        total_processed = 0
        for idx, (conv_id, message_ids) in enumerate(conv_messages.items(), 1):
            print(f"[{idx}/{len(conv_messages)}] 处理会话 {conv_id} ({len(message_ids)} 条消息)...", end=" ")
            
            count = preprocessor.preprocess_message_batch(conv_id, message_ids)
            total_processed += count
            
            print(f"✅ 完成 ({count} 条)")
        
        print("\n" + "=" * 60)
        print(f"✅ 预处理完成! 共处理 {total_processed} 条消息")
        print("=" * 60)
        
        # 统计缓存覆盖率
        cursor = db.execute("SELECT COUNT(*) FROM messages WHERE message_type = 1")
        total_messages = cursor.fetchone()[0]
        
        cursor = db.execute("SELECT COUNT(*) FROM message_preprocessed")
        cached_messages = cursor.fetchone()[0]
        
        coverage = (cached_messages / total_messages * 100) if total_messages > 0 else 0
        
        print(f"\n📊 缓存覆盖率:")
        print(f"   - 文本消息总数: {total_messages}")
        print(f"   - 已缓存消息数: {cached_messages}")
        print(f"   - 覆盖率: {coverage:.1f}%")
        
        if coverage < 100:
            remaining = total_messages - cached_messages
            print(f"\n💡 仍有 {remaining} 条消息未缓存，可再次运行此脚本")
        
    except Exception as e:
        print(f"\n❌ 预处理失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量预处理现有消息")
    parser.add_argument("--limit", type=int, default=0, help="限制处理数量（0=全部）")
    parser.add_argument("--conversation-id", type=int, help="仅处理指定会话")
    
    args = parser.parse_args()
    
    preprocess_all_messages(limit=args.limit, conversation_id=args.conversation_id)
