"""微信数据库解密模块 V2 (纯Python实现，参考EchoTrace)"""
import hashlib
import hmac
import struct
from pathlib import Path
from typing import Optional, Tuple
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
import logging


logger = logging.getLogger(__name__)
class WeChatDBDecryptorV2:
    """微信V4数据库解密器 (纯Python实现)"""
    
    # 常量
    KEY_SIZE = 32
    SALT_SIZE = 16
    AES_BLOCK_SIZE = 16
    SQLITE_HEADER = b"SQLite format 3\x00"
    IV_SIZE = 16
    
    # V4 版本特定常量
    PAGE_SIZE = 4096
    V4_ITER_COUNT = 256000
    HMAC_SHA512_SIZE = 64
    
    def __init__(self):
        """初始化解密器"""
        # 计算保留字节大小
        self.reserve = self.IV_SIZE + self.HMAC_SHA512_SIZE
        if self.reserve % self.AES_BLOCK_SIZE != 0:
            self.reserve = ((self.reserve // self.AES_BLOCK_SIZE) + 1) * self.AES_BLOCK_SIZE
    
    def derive_keys(self, key: bytes, salt: bytes) -> Tuple[bytes, bytes]:
        """
        派生加密密钥和MAC密钥
        
        Args:
            key: 原始密钥 (32字节)
            salt: 盐值 (16字节)
            
        Returns:
            (enc_key, mac_key): 加密密钥和MAC密钥
        """
        from Crypto.Hash import SHA512
        
        # 生成加密密钥
        enc_key = PBKDF2(
            key, 
            salt, 
            dkLen=self.KEY_SIZE,
            count=self.V4_ITER_COUNT,
            hmac_hash_module=SHA512
        )
        
        # 生成MAC密钥
        mac_salt = bytes(b ^ 0x3a for b in salt)
        mac_key = PBKDF2(
            enc_key,
            mac_salt,
            dkLen=self.KEY_SIZE,
            count=2,
            hmac_hash_module=SHA512
        )
        
        return enc_key, mac_key
    
    def validate_key(self, first_page: bytes, key: bytes) -> bool:
        """
        验证密钥是否正确
        
        Args:
            first_page: 第一页数据 (4096字节)
            key: 密钥 (32字节)
            
        Returns:
            bool: 密钥是否正确
        """
        if len(first_page) < self.PAGE_SIZE or len(key) != self.KEY_SIZE:
            return False
        
        salt = first_page[:self.SALT_SIZE]
        _, mac_key = self.derive_keys(key, salt)
        
        # 计算HMAC
        h = hmac.new(mac_key, digestmod=hashlib.sha512)
        data_end = self.PAGE_SIZE - self.reserve + self.IV_SIZE
        h.update(first_page[self.SALT_SIZE:data_end])
        
        # 页号 (第一页为1)
        page_no = struct.pack('<I', 1)
        h.update(page_no)
        
        calculated_mac = h.digest()
        stored_mac = first_page[data_end:data_end + self.HMAC_SHA512_SIZE]
        
        return hmac.compare_digest(calculated_mac, stored_mac)
    
    def decrypt_page(
        self, 
        page_buf: bytes, 
        enc_key: bytes, 
        mac_key: bytes, 
        page_num: int
    ) -> bytes:
        """
        解密单个页面
        
        Args:
            page_buf: 页面数据
            enc_key: 加密密钥
            mac_key: MAC密钥
            page_num: 页号 (从0开始)
            
        Returns:
            bytes: 解密后的页面数据
        """
        offset = 0
        if page_num == 0:
            offset = self.SALT_SIZE
        
        # 验证HMAC
        h = hmac.new(mac_key, digestmod=hashlib.sha512)
        h.update(page_buf[offset:self.PAGE_SIZE - self.reserve + self.IV_SIZE])
        
        page_no = struct.pack('<I', page_num + 1)
        h.update(page_no)
        
        hash_mac = h.digest()
        
        hash_mac_start = self.PAGE_SIZE - self.reserve + self.IV_SIZE
        hash_mac_end = hash_mac_start + self.HMAC_SHA512_SIZE
        
        if not hmac.compare_digest(hash_mac, page_buf[hash_mac_start:hash_mac_end]):
            raise ValueError(f"Page {page_num}: HMAC verification failed")
        
        # 提取IV
        iv = page_buf[self.PAGE_SIZE - self.reserve:self.PAGE_SIZE - self.reserve + self.IV_SIZE]
        
        # 解密数据
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        encrypted = page_buf[offset:self.PAGE_SIZE - self.reserve]
        decrypted = cipher.decrypt(encrypted)
        
        # 组合解密数据和保留字节
        return decrypted + page_buf[self.PAGE_SIZE - self.reserve:]
    
    def verify_key_from_file(self, db_path: str, key_hex: str) -> bool:
        """
        从文件验证密钥
        
        Args:
            db_path: 数据库文件路径
            key_hex: 64字符hex密钥
            
        Returns:
            bool: 密钥是否正确
        """
        try:
            with open(db_path, 'rb') as f:
                first_page = f.read(self.PAGE_SIZE)
            
            if len(first_page) < self.PAGE_SIZE:
                return False
            
            key = bytes.fromhex(key_hex)
            if len(key) != self.KEY_SIZE:
                return False
            
            return self.validate_key(first_page, key)
        except Exception as e:
            logger.error(f"[DEBUG Decryptor] 验证密钥失败: {e}")
            return False
    
    def decrypt_database(
        self, 
        input_path: str, 
        output_path: str, 
        key_hex: str,
        progress_callback=None
    ) -> None:
        """
        解密整个数据库
        
        Args:
            input_path: 加密数据库路径
            output_path: 输出路径
            key_hex: 64字符hex密钥
            progress_callback: 进度回调 callback(current, total)
        """
        # 读取第一页验证密钥
        with open(input_path, 'rb') as f:
            first_page = f.read(self.PAGE_SIZE)
        
        key = bytes.fromhex(key_hex)
        
        if not self.validate_key(first_page, key):
            raise ValueError("Invalid key")
        
        # 派生密钥
        salt = first_page[:self.SALT_SIZE]
        enc_key, mac_key = self.derive_keys(key, salt)
        
        # 计算总页数
        file_size = Path(input_path).stat().st_size
        total_pages = (file_size + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        
        # 解密所有页面
        with open(input_path, 'rb') as input_file:
            with open(output_path, 'wb') as output_file:
                # 写入SQLite头
                output_file.write(self.SQLITE_HEADER)
                
                for page_num in range(total_pages):
                    page_buf = input_file.read(self.PAGE_SIZE)
                    
                    if len(page_buf) == 0:
                        break
                    
                    # 检查是否全为零
                    if page_buf == b'\x00' * len(page_buf):
                        output_file.write(page_buf)
                        continue
                    
                    # 解密页面
                    try:
                        decrypted = self.decrypt_page(page_buf, enc_key, mac_key, page_num)
                        output_file.write(decrypted)
                    except Exception as e:
                        logger.error(f"[WARN] 解密页面 {page_num} 失败: {e}")
                        # 写入原始数据
                        output_file.write(page_buf)
                    
                    # 进度回调
                    if progress_callback:
                        progress_callback(page_num + 1, total_pages)


# 保持向后兼容
class WeChatDBDecryptor:
    """兼容性包装类"""
    
    @staticmethod
    def verify_key(db_path: str, key_hex: str) -> bool:
        """验证密钥"""
        decryptor = WeChatDBDecryptorV2()
        return decryptor.verify_key_from_file(db_path, key_hex)
    
    @staticmethod
    def decrypt_database(input_path: str, output_path: str, key_hex: str):
        """解密数据库"""
        decryptor = WeChatDBDecryptorV2()
        decryptor.decrypt_database(input_path, output_path, key_hex)
