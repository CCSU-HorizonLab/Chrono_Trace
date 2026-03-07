"""微信数据库解密模块（兼容性包装器）"""
import logging


logger = logging.getLogger(__name__)
class WeChatDBDecryptor:
    """微信数据库解密器（包装 WeChatDBDecryptorV2）"""
    
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
            from .db_decryptor_v2 import WeChatDBDecryptorV2
            decryptor = WeChatDBDecryptorV2()
            return decryptor.verify_key_from_file(db_path, key_hex)
        except Exception as e:
            logger.error(f"[DEBUG] 密钥验证失败: {e}")
            return False
    
    @staticmethod
    def decrypt_database(input_path: str, output_path: str, key_hex: str):
        """
        解密数据库
        
        Args:
            input_path: 加密数据库路径
            output_path: 输出路径
            key_hex: 密钥
        """
        from .db_decryptor_v2 import WeChatDBDecryptorV2
        decryptor = WeChatDBDecryptorV2()
        decryptor.decrypt_database(input_path, output_path, key_hex)
