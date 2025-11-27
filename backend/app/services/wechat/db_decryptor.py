"""微信数据库解密模块（使用 pysqlcipher3）"""
import os
from typing import Optional, Tuple, Any

# pysqlcipher3 是 C 扩展，没有类型存根，需要 type: ignore
from pysqlcipher3 import dbapi2 as sqlite  # type: ignore
DatabaseError = sqlite.DatabaseError  # 显式引用以避免类型检查警告


class WeChatDBDecryptor:
    """微信数据库解密器"""
    
    # 微信不同版本的 SQLCipher 加密参数配置
    # 参考：EchoTrace 项目 + SQLCipher 官方文档
    WECHAT_CIPHER_CONFIGS = [
        # 配置 1：微信 4.x（Windows PC 最新版，SQLCipher 4）
        {
            "name": "WeChat 4.x (SQLCipher 4)",
            "compatibility": 4,
            "cipher_page_size": 4096,
            "kdf_iter": 256000,
            "cipher_kdf_algorithm": "PBKDF2_HMAC_SHA512",
            "cipher_hmac_algorithm": "HMAC_SHA512",
        },
        # 配置 2：微信 3.x（旧版 Windows PC，SQLCipher 3）
        {
            "name": "WeChat 3.x (SQLCipher 3)",
            "compatibility": 3,
            "cipher_page_size": 4096,
            "kdf_iter": 64000,
            "cipher_kdf_algorithm": "PBKDF2_HMAC_SHA1",
            "cipher_hmac_algorithm": "HMAC_SHA1",
        },
        # 配置 3：微信更旧版本（SQLCipher 1/2）
        {
            "name": "WeChat 2.x (SQLCipher 1/2)",
            "cipher_page_size": 1024,
            "kdf_iter": 4000,
        },
    ]
    
    @staticmethod
    def open_encrypted_db(db_path: str, key_hex: str, auto_detect: bool = True):
        """
        打开加密的微信数据库（支持自动检测版本）
        
        Args:
            db_path: 数据库文件路径
            key_hex: 32位十六进制密钥字符串（如 "1a2b3c4d..."）
            auto_detect: 是否自动检测加密参数（尝试多个版本配置）
            
        Returns:
            sqlite.Connection: 数据库连接对象
            
        Raises:
            FileNotFoundError: 数据库文件不存在
            ValueError: 密钥格式错误
            sqlite.DatabaseError: 密钥错误或数据库损坏
        """
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        
        # 验证密钥格式（应为32字节=64位hex字符串）
        if not key_hex or len(key_hex) != 64:
            raise ValueError("Key must be a 64-character hex string (32 bytes)")
        
        try:
            # 验证hex格式
            int(key_hex, 16)
        except ValueError:
            raise ValueError("Invalid hex key format")
        
        # 如果启用自动检测，尝试所有已知配置
        if auto_detect:
            last_error = None
            for config in WeChatDBDecryptor.WECHAT_CIPHER_CONFIGS:
                try:
                    conn = WeChatDBDecryptor._try_open_with_config(
                        db_path, key_hex, config
                    )
                    print(f"✅ 成功使用配置：{config['name']}")
                    return conn
                except Exception as e:
                    last_error = e
                    continue
            
            # 所有配置都失败
            msg_parts = [
                "解密失败，已尝试所有已知配置。",
                "可能的原因：",
                "1. 密钥错误（请使用 wx_key 工具重新获取）",
                "2. 数据库文件损坏",
                "3. 微信版本不支持（当前支持 2.x/3.x/4.x）",
                f"最后错误：{last_error}"
            ]
            raise DatabaseError("\n".join(msg_parts))
        else:
            # 使用默认配置（4.x）
            return WeChatDBDecryptor._try_open_with_config(
                db_path, key_hex, WeChatDBDecryptor.WECHAT_CIPHER_CONFIGS[0]
            )
    
    @staticmethod
    def _try_open_with_config(db_path: str, key_hex: str, config: dict):
        """
        使用指定配置尝试打开数据库
        
        Args:
            db_path: 数据库路径
            key_hex: 密钥
            config: 加密参数配置
            
        Returns:
            sqlite.Connection
            
        Raises:
            sqlite.DatabaseError: 解密失败
        """
        conn = sqlite.connect(db_path)
        
        try:
            # ⚠️ 关键：PRAGMA 顺序必须严格遵守！
            # 参考 SQLCipher 官方文档：https://www.zetetic.net/sqlcipher/sqlcipher-api/
            
            # 步骤 1：设置兼容性（如果配置中有）
            if "compatibility" in config:
                conn.execute(f"PRAGMA cipher_compatibility = {config['compatibility']}")
            
            # 步骤 2：设置页大小（必须在 key 之前！）
            conn.execute(f"PRAGMA cipher_page_size = {config['cipher_page_size']}")
            
            # 步骤 3：设置 KDF 迭代次数（必须在 key 之前！）
            conn.execute(f"PRAGMA kdf_iter = {config['kdf_iter']}")
            
            # 步骤 4：设置密钥（核心步骤）
            conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
            
            # 步骤 5：设置 KDF 和 HMAC 算法（在 key 之后）
            if "cipher_kdf_algorithm" in config:
                conn.execute(f"PRAGMA cipher_kdf_algorithm = {config['cipher_kdf_algorithm']}")
            
            if "cipher_hmac_algorithm" in config:
                conn.execute(f"PRAGMA cipher_hmac_algorithm = {config['cipher_hmac_algorithm']}")
            
            # 步骤 6：验证解密是否成功（触发实际解密操作）
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            
            # 步骤 7：设置 row_factory 便于后续使用
            conn.row_factory = sqlite.Row
            
            return conn
            
        except Exception as e:
            conn.close()
            error_msg = str(e)
            
            # 提供友好的错误提示
            if "file is not a database" in error_msg or "file is encrypted" in error_msg:
                raise DatabaseError(
                    f"配置 {config.get('name', 'Unknown')} 解密失败（密钥或参数不匹配）"
                )
            else:
                raise DatabaseError(f"配置 {config.get('name', 'Unknown')} 错误: {error_msg}")
    
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
            # 使用新的纯Python解密器
            from .db_decryptor_v2 import WeChatDBDecryptorV2
            decryptor = WeChatDBDecryptorV2()
            return decryptor.verify_key_from_file(db_path, key_hex)
        except Exception as e:
            print(f"[DEBUG] 密钥验证失败: {e}")
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
