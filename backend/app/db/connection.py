"""数据库连接与初始化模块"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from ..config import DB_PATH, DB_SCHEMA_PATH

import threading


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
        # 大库读写性能：默认页缓存 2MB/连接对 GB 级库的会话级扫描明显
        # 吃紧；mmap 免行拷贝、temp_store=MEMORY 让 GROUP BY/排序的临时
        # B 树不落盘
        conn.execute("PRAGMA cache_size = -65536")  # 64MB
        conn.execute("PRAGMA mmap_size = 268435456")  # 256MB
        conn.execute("PRAGMA temp_store = MEMORY")
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
        """执行建表SQL（schema.sql 为唯一建表源；不做历史库兼容迁移，旧库删除重导）"""
        schema_sql = cls._load_schema_sql()
        conn = cls._get_instance()

        with conn:
            conn.executescript(schema_sql)

    @classmethod
    def _load_schema_sql(cls) -> str:
        schema_path = Path(DB_SCHEMA_PATH)
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        return schema_path.read_text(encoding="utf-8")

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


def optimize_query_plans() -> None:
    """大批量写入完成后收集查询计划统计（PRAGMA optimize ≈ 按需 ANALYZE）。

    sqlite_stat1 落库持久化，帮助查询计划器在 messages/sentiment_cache
    等大表上选对索引；失败静默——统计缺失只影响计划质量不影响正确性。
    """
    try:
        db = get_db()
        db.execute("PRAGMA optimize")
        db.commit()
    except Exception:
        pass


@contextmanager
def write_transaction(db: sqlite3.Connection = None):
    """显式批量写事务。

    连接是 autocommit（isolation_level=None，为消灭挂起事务死锁），不
    包事务的批写（含 executemany）实际逐语句提交——百万行级导入要额外
    付出数千万次 WAL 帧追加与写锁获取。批量写点统一走本助手；嵌套调用
    时并入外层事务，由最外层提交。
    """
    if db is None:
        db = get_db()
    if db.in_transaction:
        yield db
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except Exception:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


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

    with write_transaction(db):
        cursor = db.executemany(sql, data)
    return cursor.rowcount


def execute_transaction(operations: list, db: sqlite3.Connection = None) -> bool:
    """
    执行事务（一组操作，全部成功或全部回滚）

    Args:
        operations: 操作列表，每个元素为 (sql, params) 元组

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
