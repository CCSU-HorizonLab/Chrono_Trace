"""数据库连接与初始化模块"""
import sqlite3
from pathlib import Path
from typing import Optional

from ..config import DB_PATH, DB_SCHEMA_PATH

import threading

class DatabaseConnection:
    """数据库连接管理器"""
    
    _local = threading.local()
    _db_path: Optional[str] = None
    
    @classmethod
    def _get_instance(cls) -> Optional[sqlite3.Connection]:
        return getattr(cls._local, 'instance', None)
        
    @classmethod
    def _set_instance(cls, conn: sqlite3.Connection):
        cls._local.instance = conn

    @classmethod
    def initialize(cls, db_path: Optional[str] = None) -> sqlite3.Connection:
        """
        初始化数据库连接（按线程本地单例）
        
        Args:
            db_path: 数据库文件路径，默认为用户数据目录中的 chrono_trace.db
            
        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        if cls._get_instance() is not None:
            return cls._get_instance()
        
        # 确定数据库路径
        if db_path is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(DB_PATH)
        
        cls._db_path = db_path
        
        # 创建连接
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # 支持字典式访问
        cls._set_instance(conn)
        
        # 执行建表SQL
        cls._create_tables()
        
        return conn
    
    @classmethod
    def _create_tables(cls):
        """执行建表SQL"""
        schema_sql = cls._load_schema_sql()
        conn = cls._get_instance()
        
        # 执行所有建表语句
        with conn:
            # 旧版数据库缺少 account_wxid。先做破坏性重建兜底，
            # 避免新版 schema 中的账号索引在迁移前访问不存在的列。
            cls._migrate_wechat_account_isolation(conn)
            conn.executescript(schema_sql)
            cls._run_compat_migrations()

    @classmethod
    def _load_schema_sql(cls) -> str:
        schema_path = Path(DB_SCHEMA_PATH)
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        return schema_path.read_text(encoding="utf-8")

    @classmethod
    def _table_exists(cls, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    @classmethod
    def _table_columns(cls, conn: sqlite3.Connection, table_name: str) -> set[str]:
        if not cls._table_exists(conn, table_name):
            return set()
        columns = set()
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall():
            try:
                columns.add(str(row["name"]))
            except Exception:
                columns.add(str(row[1]))
        return columns

    @classmethod
    def _clear_wechat_related_data(cls, conn: sqlite3.Connection) -> None:
        cleanup_tables = [
            "suggestion_observations",
            "realtime_suggestions",
            "session_threads",
            "realtime_monitor_checkpoints",
            "realtime_message_buffer",
            "contact_rules",
            "self_profiles",
            "contact_profiles",
            "sentiment_cache",
            "interaction_pairs",
            "speech_units",
            "word_counts",
            "initiative_stats",
            "response_times",
            "sessions",
            "message_preprocessed",
            "analysis_segments",
            "affinity_scores",
            "affinity_config",
            "suggestions",
            "messages",
            "conversations",
            "contacts",
        ]
        for table_name in cleanup_tables:
            if cls._table_exists(conn, table_name):
                conn.execute(f"DELETE FROM {table_name}")

        if cls._table_exists(conn, "import_records"):
            conn.execute(
                "DELETE FROM import_records WHERE import_type LIKE 'wechat_%'"
            )

    @classmethod
    def _recreate_wechat_account_tables(cls, conn: sqlite3.Connection) -> None:
        structural_tables = [
            "suggestion_observations",
            "realtime_suggestions",
            "session_threads",
            "realtime_monitor_checkpoints",
            "realtime_message_buffer",
            "contact_rules",
            "self_profiles",
            "contact_profiles",
            "conversations",
            "contacts",
        ]
        for table_name in structural_tables:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        index_names = [
            "idx_conversations_username",
            "idx_conversations_updated_at",
            "idx_contacts_username",
            "idx_realtime_buffer_talker",
            "idx_realtime_buffer_batch",
            "idx_realtime_buffer_processed",
            "idx_realtime_buffer_timestamp",
            "idx_realtime_buffer_hash",
            "idx_realtime_suggestions_batch",
            "idx_realtime_suggestions_created",
            "idx_suggestion_observations_display",
            "idx_realtime_checkpoint_updated",
            "idx_realtime_checkpoint_display_name",
        ]
        for index_name in index_names:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")

        conn.executescript(cls._load_schema_sql())

    @classmethod
    def _migrate_wechat_account_isolation(cls, conn: sqlite3.Connection) -> None:
        required_columns = {
            "contacts": {"account_wxid"},
            "conversations": {"account_wxid"},
            "realtime_message_buffer": {"account_wxid"},
            "realtime_monitor_checkpoints": {"account_wxid"},
            "realtime_suggestions": {"account_wxid"},
            "suggestion_observations": {"account_wxid"},
        }

        migration_needed = False
        for table_name, columns in required_columns.items():
            existing_columns = cls._table_columns(conn, table_name)
            if existing_columns and not columns.issubset(existing_columns):
                migration_needed = True
                break

        optional_account_tables = ("session_threads", "contact_profiles", "self_profiles", "contact_rules")
        if not migration_needed:
            for table_name in optional_account_tables:
                existing_columns = cls._table_columns(conn, table_name)
                if existing_columns and "account_wxid" not in existing_columns:
                    migration_needed = True
                    break

        if not migration_needed:
            return

        cls._clear_wechat_related_data(conn)
        cls._recreate_wechat_account_tables(conn)
        conn.commit()

    @classmethod
    def _run_compat_migrations(cls):
        """Apply lightweight compatibility migrations for existing databases."""
        conn = cls._get_instance()
        if conn is None:
            return

        cls._migrate_wechat_account_isolation(conn)

        conn.execute(
            """
            DELETE FROM messages
            WHERE local_id IS NOT NULL
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM messages
                  WHERE local_id IS NOT NULL
                  GROUP BY conversation_id, local_id
              )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_conv_local_unique
            ON messages(conversation_id, local_id)
            WHERE local_id IS NOT NULL
            """
        )
        conn.execute(
            """
            UPDATE conversations
            SET message_count = (
                    SELECT COUNT(*)
                    FROM messages
                    WHERE messages.conversation_id = conversations.id
                ),
                updated_at = COALESCE(
                    (
                        SELECT MAX(timestamp)
                        FROM messages
                        WHERE messages.conversation_id = conversations.id
                    ),
                    updated_at
                )
            """
        )
        conn.commit()
    
    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        """获取当前线程的数据库连接"""
        if cls._get_instance() is None:
            return cls.initialize(cls._db_path)
        return cls._get_instance()
    
    @classmethod
    def close(cls):
        """关闭当前线程的数据库连接"""
        conn = cls._get_instance()
        if conn:
            conn.close()
            cls._set_instance(None)
    
    @classmethod
    def execute(cls, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        执行SQL语句
        
        Args:
            sql: SQL语句
            params: 参数元组
            
        Returns:
            sqlite3.Cursor
        """
        conn = cls.get_connection()
        return conn.execute(sql, params)
    
    @classmethod
    def commit(cls):
        """提交事务"""
        conn = cls.get_connection()
        conn.commit()
    
    @classmethod
    def rollback(cls):
        """回滚事务"""
        conn = cls.get_connection()
        conn.rollback()


def get_db() -> sqlite3.Connection:
    """快捷方法：获取数据库连接"""
    return DatabaseConnection.get_connection()


def batch_insert(table: str, columns: list, data: list, db: sqlite3.Connection = None) -> int:
    """
    批量插入数据

    Args:
        table: 表名
        columns: 列名列表
        data: 数据列表，每个元素是一个元组
        db: 数据库连接（可选，默认使用get_db()）

    Returns:
        int: 插入的行数
    """
    if db is None:
        db = get_db()

    if not data:
        return 0

    placeholders = ', '.join(['?'] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

    cursor = db.executemany(sql, data)
    return cursor.rowcount


def execute_transaction(operations: list, db: sqlite3.Connection = None) -> bool:
    """
    执行事务（一组操作，全部成功或全部回滚）

    Args:
        operations: 操作列表，每个元素是 (sql, params) 元组
        db: 数据库连接（可选，默认使用get_db()）

    Returns:
        bool: 是否成功
    """
    if db is None:
        db = get_db()

    try:
        for sql, params in operations:
            db.execute(sql, params)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        raise e
