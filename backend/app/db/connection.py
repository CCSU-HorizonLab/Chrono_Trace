"""数据库连接与初始化模块"""
import sqlite3
import os
from pathlib import Path
from typing import Optional


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
            db_path: 数据库文件路径，默认为 backend/data/chrono_trace.db
            
        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        if cls._get_instance() is not None:
            return cls._get_instance()
        
        # 确定数据库路径
        if db_path is None:
            backend_dir = Path(__file__).parent.parent.parent
            data_dir = backend_dir / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "chrono_trace.db")
        
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
        schema_path = Path(__file__).parent / "schema.sql"
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        
        # 执行所有建表语句
        with cls._get_instance():
            cls._get_instance().executescript(schema_sql)
    
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
