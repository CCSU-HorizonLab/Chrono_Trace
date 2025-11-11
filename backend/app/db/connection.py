"""数据库连接与初始化模块"""
import sqlite3
import os
from pathlib import Path
from typing import Optional


class DatabaseConnection:
    """数据库连接管理器"""
    
    _instance: Optional[sqlite3.Connection] = None
    _db_path: Optional[str] = None
    
    @classmethod
    def initialize(cls, db_path: Optional[str] = None) -> sqlite3.Connection:
        """
        初始化数据库连接（单例模式）
        
        Args:
            db_path: 数据库文件路径，默认为 backend/data/chrono_trace.db
            
        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        if cls._instance is not None:
            return cls._instance
        
        # 确定数据库路径
        if db_path is None:
            backend_dir = Path(__file__).parent.parent.parent
            data_dir = backend_dir / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "chrono_trace.db")
        
        cls._db_path = db_path
        
        # 创建连接
        cls._instance = sqlite3.connect(db_path, check_same_thread=False)
        cls._instance.row_factory = sqlite3.Row  # 支持字典式访问
        
        # 执行建表SQL
        cls._create_tables()
        
        return cls._instance
    
    @classmethod
    def _create_tables(cls):
        """执行建表SQL"""
        schema_path = Path(__file__).parent / "schema.sql"
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        
        # 执行所有建表语句
        with cls._instance:
            cls._instance.executescript(schema_sql)
    
    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        """获取数据库连接"""
        if cls._instance is None:
            return cls.initialize()
        return cls._instance
    
    @classmethod
    def close(cls):
        """关闭数据库连接"""
        if cls._instance:
            cls._instance.close()
            cls._instance = None
    
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
