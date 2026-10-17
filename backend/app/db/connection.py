"""数据库连接与初始化模块"""
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from ..config import DB_PATH, DB_SCHEMA_PATH

import threading

logger = logging.getLogger(__name__)

class DatabaseConnection:
    """数据库连接管理器"""
    
    _local = threading.local()
    _db_path: Optional[str] = None
    _schema_lock = threading.RLock()
    _schema_initialized_paths: set[str] = set()
    _wal_initialized_paths: set[str] = set()
    
    @classmethod
    def _get_instance(cls) -> Optional[sqlite3.Connection]:
        return getattr(cls._local, 'instance', None)

    @classmethod
    def _get_instance_path(cls) -> Optional[str]:
        return getattr(cls._local, 'db_path', None)
        
    @classmethod
    def _set_instance(cls, conn: Optional[sqlite3.Connection], db_path: Optional[str] = None):
        cls._local.instance = conn
        cls._local.db_path = db_path if conn is not None else None

    @classmethod
    def _normalize_db_path(cls, db_path: str) -> str:
        try:
            return str(Path(db_path).expanduser().resolve())
        except Exception:
            return str(db_path)

    @classmethod
    def initialize(cls, db_path: Optional[str] = None) -> sqlite3.Connection:
        """
        初始化数据库连接（按线程本地单例）
        
        Args:
            db_path: 数据库文件路径，默认为用户数据目录中的 chrono_trace.db
            
        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        # 确定数据库路径
        if db_path is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            db_path = str(DB_PATH)
        db_path = cls._normalize_db_path(db_path)

        current = cls._get_instance()
        if current is not None:
            current_path = cls._get_instance_path()
            if current_path is None or current_path == db_path:
                return current
            current.close()
            cls._set_instance(None)
        
        with cls._schema_lock:
            cls._db_path = db_path
        
        # 创建连接。
        # isolation_level=None（autocommit）：每条写语句即时提交。
        # 默认的 legacy 隐式事务下，任何写路径异常退出时未回滚，该线程
        # 的连接就会永久持有写锁——之后所有连接（建议生成/设置页/索引
        # 队列）的写都在 busy 等待，表现为"任何相关操作都触发锁且锁死"。
        # autocommit 从机制上消灭挂起事务；写锁窗口缩为单语句毫秒级，
        # WAL + busy_timeout=30s 下并发连接最多短暂等待。conn.commit()
        # 变为安全 no-op，`with conn:` 块亦兼容。
        conn = sqlite3.connect(
            db_path, check_same_thread=False, timeout=30.0, isolation_level=None
        )
        conn.row_factory = sqlite3.Row  # 支持字典式访问
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA synchronous = NORMAL")
        cls._set_instance(conn, db_path)
        
        try:
            with cls._schema_lock:
                if db_path not in cls._wal_initialized_paths:
                    conn.execute("PRAGMA journal_mode = WAL")
                    cls._wal_initialized_paths.add(db_path)

                if db_path not in cls._schema_initialized_paths:
                    cls._create_tables()
                    cls._schema_initialized_paths.add(db_path)
        except Exception:
            conn.close()
            cls._set_instance(None)
            raise
        
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
            "embedding_cache",
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
    def _migrate_conversations_analysis_columns(cls, conn: sqlite3.Connection) -> None:
        """conversations 补分析新鲜度三列（纯增量 ALTER，老代码不读不炸）。

        analysis_stale 默认 1：存量会话分析新鲜度未知，诚实显示「待更新」。
        """
        additions = (
            ("analysis_stale", "INTEGER NOT NULL DEFAULT 1"),
            ("analysis_message_count", "INTEGER"),
            ("analysis_watermark_ts", "INTEGER"),
        )
        existing = cls._table_columns(conn, "conversations")
        if not existing:
            return
        changed = False
        for column_name, column_type in additions:
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE conversations ADD COLUMN {column_name} {column_type}"
                )
                changed = True
        if changed:
            conn.commit()

    @classmethod
    def _migrate_realtime_suggestions_columns(cls, conn: sqlite3.Connection) -> None:
        """realtime_suggestions 补对话回复/思考过程两列（纯增量 ALTER）。

        老库该表缺 reply/thought_process 时在此统一补齐；
        建表本身由 schema.sql（CREATE IF NOT EXISTS）负责。
        """
        additions = (
            ("reply", "TEXT"),
            ("thought_process", "TEXT"),
        )
        existing = cls._table_columns(conn, "realtime_suggestions")
        if not existing:
            return
        changed = False
        for column_name, column_type in additions:
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE realtime_suggestions ADD COLUMN {column_name} {column_type}"
                )
                changed = True
        if changed:
            conn.commit()

    @classmethod
    def _migrate_llm_models_extra_body(cls, conn: sqlite3.Connection) -> None:
        """llm_models 补 extra_body 列（模型级附加请求参数 JSON，纯增量 ALTER）。

        老库缺列时在此补齐；建表列清单由 schema.sql 负责。
        """
        existing = cls._table_columns(conn, "llm_models")
        if not existing or "extra_body" in existing:
            return
        conn.execute("ALTER TABLE llm_models ADD COLUMN extra_body TEXT")
        conn.commit()

    @classmethod
    def _migrate_strip_chatroom_prefixes(cls, conn: sqlite3.Connection) -> None:
        """一次性清理存量群消息的 'wxid_xxx:\\n' 发送者前缀。

        摄入端已改为存储剥离后的干净内容；本迁移处理修复前导入的存量
        （不清理则词频/情感/事实抽取/出网 prompt 持续被前缀污染）。
        settings 表键做一次性标记，避免每次启动重复扫描。
        """
        try:
            flag = conn.execute(
                "SELECT value FROM settings WHERE key = 'migration_chatroom_prefix_stripped'"
            ).fetchone()
            if flag:
                return
            from ..services.wechat.chatroom import (
                parse_chatroom_message,
                resolve_chatroom_display_name,
            )

            updates = []
            cleaned_updates = []
            touched_conversations: set[int] = set()
            rows = conn.execute(
                """
                SELECT m.id, m.content, m.sender, m.conversation_id,
                       mp.cleaned_content
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                LEFT JOIN message_preprocessed mp ON mp.message_id = m.id
                WHERE c.conversation_type = 'group'
                  AND (m.content LIKE '%' || ':' || char(10) || '%'
                       OR mp.cleaned_content LIKE '%' || ':' || char(10) || '%')
                """
            ).fetchall()
            for row in rows:
                content = row["content"] if isinstance(row["content"], str) else ""
                member_wxid, clean = parse_chatroom_message(content)
                sender = row["sender"] or ""
                cleaned = row["cleaned_content"] if isinstance(row["cleaned_content"], str) else ""
                cleaned_member, cleaned_clean = parse_chatroom_message(cleaned)
                if member_wxid is None and cleaned_member is None:
                    continue
                touched_conversations.add(int(row["conversation_id"]))
                if member_wxid is not None:
                    if not sender.strip():
                        sender = resolve_chatroom_display_name(member_wxid)
                    updates.append((clean, sender, row["id"]))
                if cleaned_member is not None:
                    # cleaned_content 是清洗产物，前缀可能独立残存，须单独剥离
                    cleaned_updates.append((cleaned_clean, row["id"]))
            if updates:
                conn.executemany(
                    "UPDATE messages SET content = ?, sender = ? WHERE id = ?",
                    updates,
                )
            if cleaned_updates:
                conn.executemany(
                    "UPDATE message_preprocessed SET cleaned_content = ? WHERE message_id = ?",
                    cleaned_updates,
                )
            if touched_conversations:
                # 派生层自愈：分析结果打脏（重分析秒级）；RAG 冷标脏
                # （口径同导入口径，见 ingest_service 导入后冷构建）——
                # 迁移波及面大，热入队会让后台无预期地逐个全量重建；
                # 冷标记由分析完成/首次使用（ensure_contact_index）按需建。
                # speech_units 不存内容，无需清洗
                try:
                    from ..services.analysis.analysis_state import mark_conversations_stale

                    mark_conversations_stale(sorted(touched_conversations))
                except Exception as stale_e:
                    logger.debug("[迁移] 群清洗后分析打脏跳过: %s", stale_e)
                try:
                    from ..services.realtime.rag.store import RagStore

                    rag_store = RagStore(conn)
                    for acc_wxid, conv_id in conn.execute(
                        "SELECT DISTINCT account_wxid, id FROM conversations "
                        "WHERE id IN (%s)" % ",".join(
                            str(c) for c in sorted(touched_conversations)
                        )
                    ).fetchall():
                        rag_store.mark_dirty(str(acc_wxid), int(conv_id))
                    rag_store.conn.commit()
                except Exception as rag_e:
                    logger.debug("[迁移] 群清洗后 RAG 标脏跳过: %s", rag_e)
            if updates or cleaned_updates:
                conn.commit()
                from ..services.realtime.safe_print import safe_print

                safe_print(
                    f"[迁移] 已清理 {len(updates)} 条群消息与 "
                    f"{len(cleaned_updates)} 条预处理净文本的发送者前缀"
                )
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) "
                "VALUES ('migration_chatroom_prefix_stripped', ?, strftime('%s', 'now'))",
                (str(len(updates)),),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("[迁移] 群消息前缀清理失败（下次启动重试）: %s", exc)

    @classmethod
    def _migrate_message_blob_content(cls, conn: sqlite3.Connection) -> None:
        """一次性归一乱码消息内容与未掩码的 local_type 高位 flag。

        两类脏内容：
        - BLOB（typeof='blob'）：zstd 压缩二进制原样入库，读侧 str(bytes)
          产出 b'(\\xb5...' 式 repr 乱码（实测 type=1 即有 7707 行）
        - U+FFFD 汤 TEXT：2026-10-06 起 ingest 曾以 errors='replace' 把
          zstd BLOB 强解成换坏字符文本落库（typeof='text'，blob 过滤捞
          不到）；SQL 侧 LIKE char(65533) 预筛候选，decode 幂等性复检

        压缩内容不解压（无 zstd 依赖，0.67% 占比的转发长文收益不值当），
        按掩码类型给占位符。归一行的派生层一并清理：sentiment_cache
        （乱码嵌入污染向量检索）、message_preprocessed（乱码净文本），
        并对涉及的会话把分析结果打脏、RAG 队列标脏（文档/事实基于旧
        文本重建）——不标脏则记忆与建议继续引用乱码直到手动重建。
        settings 表键记迁移版本（'1'=仅 BLOB 归一、'2'=扩入 FFFD 汤文本），
        不到最新版本的库下次启动补扫，避免每次启动全表扫描。
        """
        try:
            # 旗标为版本值而非布尔：'1' = 仅 BLOB 归一的旧版已跑，'2' = 已扩入
            # U+FFFD 汤文本归一。已跑过 v1 的库（真实数据曾出现 132 万消息里
            # 20.8 万条汤文本）必须再扫一次补齐，只有 '2' 才跳过
            flag = conn.execute(
                "SELECT value FROM settings WHERE key = 'migration_message_blob_normalized'"
            ).fetchone()
            if flag and str(flag[0]) == "2":
                return
            from ..services.wechat.content_codec import decode_message_content

            candidates = conn.execute(
                "SELECT id, message_type, content FROM messages WHERE typeof(content) = 'blob'"
            ).fetchall()
            # U+FFFD 汤 TEXT 预筛：decode 对正常文本幂等，返回值有变化才需归一
            candidates += conn.execute(
                "SELECT id, message_type, content FROM messages "
                "WHERE typeof(content) = 'text' "
                "AND content LIKE '%' || char(65533) || '%'"
            ).fetchall()
            updates = []
            blob_updates = 0
            for row in candidates:
                normalized = decode_message_content(row[2], row[1])
                if normalized != row[2]:
                    updates.append((normalized, row[0]))
                    if isinstance(row[2], (bytes, bytearray)):
                        blob_updates += 1

            if updates:
                conn.executemany(
                    "UPDATE messages SET content = ? WHERE id = ?", updates
                )
                id_rows = [(row[1],) for row in updates]
                conn.executemany(
                    "DELETE FROM sentiment_cache WHERE message_id = ?", id_rows
                )
                conn.executemany(
                    "DELETE FROM message_preprocessed WHERE message_id = ?", id_rows
                )
                # 派生层标脏（口径同群前缀清理迁移）
                touched_conversations = [
                    int(row[0])
                    for row in conn.execute(
                        "SELECT DISTINCT conversation_id FROM messages WHERE id IN (%s)"
                        % ",".join(str(row[1]) for row in updates)
                    ).fetchall()
                ]
                if touched_conversations:
                    try:
                        from ..services.analysis.analysis_state import (
                            mark_conversations_stale,
                        )

                        mark_conversations_stale(touched_conversations)
                    except Exception as stale_e:
                        logger.debug("[迁移] 乱码归一后分析打脏跳过: %s", stale_e)
                    try:
                        from ..services.realtime.rag.store import RagStore

                        # 冷标脏（只写 dirty_since 不入队）：迁移曾用
                        # RagIndexQueue.mark_dirty 热入队，1894 个会话在
                        # 后台无预期逐个重建；导入链路的口径是冷标记 +
                        # 分析/首次使用按需构建，迁移与它对齐
                        rag_store = RagStore(conn)
                        for account_row in conn.execute(
                            "SELECT account_wxid, id FROM conversations "
                            "WHERE id IN (%s)"
                            % ",".join(str(c) for c in touched_conversations)
                        ).fetchall():
                            rag_store.mark_dirty(str(account_row[0]), int(account_row[1]))
                        rag_store.conn.commit()
                    except Exception as rag_e:
                        logger.debug("[迁移] 乱码归一后 RAG 标脏跳过: %s", rag_e)
            masked = conn.execute(
                "UPDATE messages SET message_type = message_type % 4294967296 "
                "WHERE message_type > 4294967295"
            ).rowcount
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) "
                "VALUES ('migration_message_blob_normalized', '2', strftime('%s', 'now'))"
            )
            conn.commit()
            if updates or masked:
                logger.info(
                    "[迁移] 乱码内容归一 %d 行（BLOB %d / FFFD 汤 %d）、类型掩码 %d 行",
                    len(updates),
                    blob_updates,
                    len(updates) - blob_updates,
                    masked,
                )
        except Exception as exc:
            logger.warning("[迁移] BLOB 内容归一失败（下次启动重试）: %s", exc)

    @classmethod
    def _run_compat_migrations(cls):
        """Apply lightweight compatibility migrations for existing databases."""
        conn = cls._get_instance()
        if conn is None:
            return

        cls._migrate_wechat_account_isolation(conn)
        cls._migrate_conversations_analysis_columns(conn)
        cls._migrate_realtime_suggestions_columns(conn)
        cls._migrate_llm_models_extra_body(conn)
        cls._migrate_strip_chatroom_prefixes(conn)
        cls._migrate_message_blob_content(conn)

        conn.execute(
            """
            DELETE FROM messages
            WHERE local_id IS NOT NULL
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM messages
                  WHERE local_id IS NOT NULL
                  GROUP BY conversation_id, local_id, timestamp
              )
            """
        )
        # 判重键升级：(conversation_id, local_id) → 追加 timestamp。
        # 微信 V4 分片库的 local_id 是分片内自增（每片都从 1 开始），
        # 旧键会把后续分片的同号消息全部误判为重复吞掉（实测 02自动化
        # 23482 条只进 7519 条）。同名旧索引需先 DROP 再按新列建。
        conn.execute("DROP INDEX IF EXISTS idx_messages_conv_local_unique")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_conv_local_unique
            ON messages(conversation_id, local_id, timestamp)
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
