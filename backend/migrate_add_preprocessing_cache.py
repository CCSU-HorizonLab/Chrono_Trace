"""
数据库迁移脚本：添加预处理缓存表

运行方式：
    python backend/migrate_add_preprocessing_cache.py
"""
import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.db.connection import get_db


def migrate():
    """执行数据库迁移"""
    print("=" * 60)
    print("开始数据库迁移：添加预处理缓存表")
    print("=" * 60)
    
    db = get_db()
    
    try:
        # 检查表是否已存在
        cursor = db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='message_preprocessed'
        """)
        
        if cursor.fetchone():
            print("\n⚠️  表 message_preprocessed 已存在，跳过创建")
        else:
            print("\n📦 创建表 message_preprocessed...")
            
            # 创建表
            db.execute("""
                CREATE TABLE IF NOT EXISTS message_preprocessed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL UNIQUE,
                    conversation_id INTEGER NOT NULL,
                    
                    cleaned_content TEXT,
                    
                    char_count INTEGER DEFAULT 0,
                    word_count INTEGER DEFAULT 0,
                    is_valid INTEGER DEFAULT 0,
                    
                    has_xml INTEGER DEFAULT 0,
                    has_media INTEGER DEFAULT 0,
                    
                    created_at INTEGER NOT NULL,
                    
                    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            
            print("✅ 表创建成功")
            
            # 创建索引
            print("\n📊 创建索引...")
            
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_preprocessed_message 
                ON message_preprocessed(message_id)
            """)
            
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_preprocessed_conversation 
                ON message_preprocessed(conversation_id)
            """)
            
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_preprocessed_valid 
                ON message_preprocessed(is_valid)
            """)
            
            print("✅ 索引创建成功")
        
        # 提交更改
        db.commit()
        
        # 统计信息
        cursor = db.execute("SELECT COUNT(*) FROM messages WHERE message_type = 1")
        total_messages = cursor.fetchone()[0]
        
        cursor = db.execute("SELECT COUNT(*) FROM message_preprocessed")
        cached_messages = cursor.fetchone()[0]
        
        print("\n" + "=" * 60)
        print("✅ 迁移完成!")
        print("=" * 60)
        print(f"📊 消息统计:")
        print(f"   - 文本消息总数: {total_messages}")
        print(f"   - 已缓存消息数: {cached_messages}")
        print(f"   - 未缓存消息数: {total_messages - cached_messages}")
        
        if total_messages > 0 and cached_messages == 0:
            print(f"\n💡 提示: 检测到 {total_messages} 条未缓存的消息")
            print("   建议运行以下命令进行预处理:")
            print("   python backend/preprocess_existing_messages.py")
        
        print("\n🎉 数据库迁移成功!")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)


if __name__ == "__main__":
    migrate()
