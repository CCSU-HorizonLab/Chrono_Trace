"""微信数据库解密模块（使用 pysqlcipher3）"""
import os
from typing import Optional
from pysqlcipher3 import dbapi2 as sqlite


class WeChatDBDecryptor:
    """微信数据库解密器"""
    
    @staticmethod
    def open_encrypted_db(db_path: str, key_hex: str):
        """
        打开加密的微信数据库
        
        Args:
            db_path: 数据库文件路径
            key_hex: 32位十六进制密钥字符串（如 "1a2b3c4d..."）
            
        Returns:
            sqlite.Connection: 数据库连接对象
            
        Raises:
            FileNotFoundError: 数据库文件不存在
            ValueError: 密钥格式错误
            sqlite.DatabaseError: 密钥错误或数据库损坏
        """
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        
        # 验证密钥格式（应为32位hex字符串）
        if not key_hex or len(key_hex) != 64:
            raise ValueError("Key must be a 64-character hex string (32 bytes)")
        
        try:
            # 验证hex格式
            int(key_hex, 16)
        except ValueError:
            raise ValueError("Invalid hex key format")
        
        # 打开数据库
        conn = sqlite.connect(db_path)
        
        # 设置密钥（SQLCipher格式）
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        
        # 设置微信使用的加密参数（适配4.x版本）
        conn.execute("PRAGMA cipher_page_size = 1024")
        conn.execute("PRAGMA kdf_iter = 64000")
        conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
        conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA1")
        
        # 验证密钥是否正确（尝试查询系统表）
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite.DatabaseError as e:
            conn.close()
            raise sqlite.DatabaseError(f"Failed to decrypt database (wrong key?): {e}")
        
        conn.row_factory = sqlite.Row
        return conn
    
    @staticmethod
    def verify_key(db_path: str, key_hex: str) -> bool:
        """
        验证密钥是否正确
        
        Args:
            db_path: 数据库文件路径
            key_hex: 密钥
            
        Returns:
            bool: 密钥是否正确
        """
        try:
            conn = WeChatDBDecryptor.open_encrypted_db(db_path, key_hex)
            conn.close()
            return True
        except Exception:
            return False
    
    @staticmethod
    def export_decrypted_db(src_path: str, key_hex: str, dest_path: str):
        """
        导出为未加密的SQLite文件（可选功能，用于调试）
        
        Args:
            src_path: 加密数据库路径
            key_hex: 密钥
            dest_path: 导出路径
        """
        conn = WeChatDBDecryptor.open_encrypted_db(src_path, key_hex)
        
        try:
            # 使用ATTACH + EXPORT方式导出
            conn.execute(f"ATTACH DATABASE '{dest_path}' AS plaintext KEY ''")
            
            # 获取所有表
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            
            # 复制每个表
            for table in tables:
                table_name = table[0]
                conn.execute(f"CREATE TABLE plaintext.{table_name} AS SELECT * FROM {table_name}")
            
            conn.execute("DETACH DATABASE plaintext")
        finally:
            conn.close()
