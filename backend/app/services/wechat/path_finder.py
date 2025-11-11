"""微信数据库路径自动寻址模块"""
import os
import winreg
from pathlib import Path
from typing import Optional, Dict, List


class WeChatPathFinder:
    """微信数据库路径查找器"""
    
    @staticmethod
    def find_wechat_install_path() -> Optional[str]:
        """
        从Windows注册表获取微信安装路径
        
        Returns:
            str: 微信安装路径，失败返回None
        """
        try:
            # 尝试从注册表获取微信安装路径
            key_path = r"Software\Tencent\WeChat"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return install_path
        except Exception:
            return None
    
    @staticmethod
    def find_wechat_data_path() -> Optional[str]:
        """
        查找微信数据目录（WeChat Files）
        
        Returns:
            str: 微信数据目录路径
        """
        try:
            # 方法1：从注册表获取
            key_path = r"Software\Tencent\WeChat"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            data_path, _ = winreg.QueryValueEx(key, "FileSavePath")
            winreg.CloseKey(key)
            
            if data_path and os.path.exists(data_path):
                return data_path
        except Exception:
            pass
        
        # 方法2：默认路径
        documents = Path.home() / "Documents"
        default_path = documents / "WeChat Files"
        
        if default_path.exists():
            return str(default_path)
        
        return None
    
    @staticmethod
    def find_current_user_wxid(data_path: str) -> Optional[str]:
        """
        查找当前活跃的微信用户ID
        
        Args:
            data_path: 微信数据目录
            
        Returns:
            str: wxid（如 wxid_xxx），按修改时间选择最近使用的
        """
        if not data_path or not os.path.exists(data_path):
            return None
        
        # 扫描所有子目录，筛选出wxid格式的目录
        user_dirs = []
        
        for item in os.listdir(data_path):
            item_path = os.path.join(data_path, item)
            
            if not os.path.isdir(item_path):
                continue
            
            # 过滤系统目录
            if item in ["All Users", "Applet", "WMPF"]:
                continue
            
            # 检查是否为有效wxid（通常以wxid_开头）
            if item.startswith("wxid_"):
                user_dirs.append((item, os.path.getmtime(item_path)))
        
        # 按修改时间排序，返回最近的
        if user_dirs:
            user_dirs.sort(key=lambda x: x[1], reverse=True)
            return user_dirs[0][0]
        
        return None
    
    @staticmethod
    def find_databases(wxid: str, data_path: str) -> Dict[str, List[str]]:
        """
        查找指定wxid的所有数据库文件
        
        Args:
            wxid: 微信用户ID
            data_path: 微信数据目录
            
        Returns:
            dict: 数据库分类字典
            {
                "message": [message_0.db路径列表],
                "session": "session.db路径",
                "contact": "contact.db路径"
            }
        """
        user_dir = Path(data_path) / wxid
        
        if not user_dir.exists():
            return {"message": [], "session": None, "contact": None}
        
        result = {
            "message": [],
            "session": None,
            "contact": None
        }
        
        # 查找消息数据库（可能分片：MSG0.db, MSG1.db...或 MicroMsg.db）
        msg_dir = user_dir / "Msg"
        if msg_dir.exists():
            for file in msg_dir.iterdir():
                if file.suffix.lower() == ".db":
                    file_name_lower = file.name.lower()
                    
                    # 匹配消息库
                    if file_name_lower.startswith("msg") or file_name_lower == "micromsg.db":
                        result["message"].append(str(file))
                    
                    # 匹配会话库
                    elif file_name_lower == "session.db":
                        result["session"] = str(file)
                    
                    # 匹配媒体消息库（可选）
                    elif file_name_lower == "mediamsg.db":
                        pass  # 暂不处理媒体库
        
        # 查找联系人数据库
        contact_dir = user_dir / "Contact"
        if contact_dir.exists():
            contact_db = contact_dir / "Contact.db"
            if contact_db.exists():
                result["contact"] = str(contact_db)
        
        return result
    
    @classmethod
    def find_all_wechat_dbs(cls) -> Optional[Dict]:
        """
        完整流程：自动查找微信数据库路径
        
        Returns:
            dict: 数据库信息
            {
                "wechat_dir": "C:/Users/xxx/Documents/WeChat Files",
                "current_user": "wxid_xxx",
                "databases": {
                    "message": [...],
                    "session": "...",
                    "contact": "..."
                }
            }
        """
        # 1. 查找微信数据目录
        data_path = cls.find_wechat_data_path()
        if not data_path:
            return None
        
        # 2. 查找当前用户
        wxid = cls.find_current_user_wxid(data_path)
        if not wxid:
            return None
        
        # 3. 查找数据库文件
        databases = cls.find_databases(wxid, data_path)
        
        return {
            "wechat_dir": data_path,
            "current_user": wxid,
            "databases": databases
        }
