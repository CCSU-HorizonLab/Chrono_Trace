"""微信数据库路径自动寻址模块 (仅支持V4)"""
import os
import winreg
from pathlib import Path
from typing import Optional, Dict, List


class WeChatPathFinder:
    """微信数据库路径查找器 (仅支持微信4.0+版本)"""
    
    @staticmethod
    def find_wechat_install_path() -> Optional[str]:
        """
        从Windows注册表获取微信安装路径
        
        Returns:
            str: 微信安装路径,失败返回None
        """
        try:
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
        查找微信数据目录(支持新版xwechat_files和旧版WeChat Files)
        
        Returns:
            str: 微信数据目录路径
        """
        try:
            # 方法1:从注册表获取
            key_path = r"Software\Tencent\WeChat"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            data_path, _ = winreg.QueryValueEx(key, "FileSavePath")
            winreg.CloseKey(key)
            
            if data_path and os.path.exists(data_path):
                return data_path
        except Exception:
            pass
        
        # 方法2:尝试多个可能的路径
        # 新版微信使用 xwechat_files (4.0+)
        try:
            username = os.getlogin()
            possible_paths = [
                Path(f"C:/Users/{username}/xwechat_files"),  # 新版
                Path.home() / "xwechat_files",  # 新版(用户目录)
                Path.home() / "Documents" / "WeChat Files",  # 旧版(保留以防万一)
            ]
        except Exception:
            possible_paths = [
                Path.home() / "xwechat_files",
                Path.home() / "Documents" / "WeChat Files",
            ]
        
        for path in possible_paths:
            if path.exists():
                return str(path)
        
        return None
    
    @staticmethod
    def find_current_user_wxid(data_path: str) -> Optional[str]:
        """
        查找当前活跃的微信用户ID
        
        Args:
            data_path: 微信数据目录
            
        Returns:
            str: wxid(如 wxid_xxx),按修改时间选择最近使用的
        """
        if not data_path or not os.path.exists(data_path):
            return None
        
        # 扫描所有子目录,筛选出wxid格式的目录
        user_dirs = []
        
        for item in os.listdir(data_path):
            item_path = os.path.join(data_path, item)
            
            if not os.path.isdir(item_path):
                continue
            
            # 过滤系统目录
            if item in ["All Users", "Applet", "WMPF"]:
                continue
            
            # 检查是否为有效wxid(通常以wxid_开头)
            if item.startswith("wxid_"):
                user_dirs.append((item, os.path.getmtime(item_path)))
        
        # 按修改时间排序,返回最近的
        if user_dirs:
            user_dirs.sort(key=lambda x: x[1], reverse=True)
            return user_dirs[0][0]
        
        return None
    
    @staticmethod
    def find_databases(wxid: str, data_path: str) -> Dict[str, List[str]]:
        """
        查找指定wxid的所有数据库文件(仅支持V4版本)
        
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
        user_dir = Path(data_path) / wxid / "db_storage"
        print(f"[DEBUG PathFinder] db_storage路径: {user_dir}")
        print(f"[DEBUG PathFinder] db_storage存在: {user_dir.exists()}")
        
        if not user_dir.exists():
            print(f"[DEBUG PathFinder] ❌ db_storage目录不存在!")
            return {"message": [], "session": None, "contact": None}
        
        # 列出db_storage下的子目录
        if user_dir.exists():
            subdirs = [d.name for d in user_dir.iterdir() if d.is_dir()]
            print(f"[DEBUG PathFinder] db_storage子目录: {subdirs}")
        
        return WeChatPathFinder._find_databases_v4(user_dir)
    
    @staticmethod
    def _find_databases_v4(db_storage_dir: Path) -> Dict[str, List[str]]:
        """
        查找 V4 版本数据库
        
        目录结构 (db_storage/):
        - contact/*.db
        - message/*.db
        - session/*.db
        """
        result = {
            "message": [],
            "session": None,
            "contact": None
        }
        
        # 查找联系人数据库
        contact_dir = db_storage_dir / "contact"
        print(f"[DEBUG PathFinder] 检查contact目录: {contact_dir} (存在:{contact_dir.exists()})")
        
        if contact_dir.exists():
            db_files = [f.name for f in contact_dir.iterdir() if f.suffix.lower() == ".db"]
            print(f"[DEBUG PathFinder] contact下的.db文件: {db_files}")
            
            for file in contact_dir.iterdir():
                if file.suffix.lower() == ".db":
                    result["contact"] = str(file)
                    print(f"[DEBUG PathFinder] ✅ 找到contact.db: {file}")
                    break
        
        # 查找消息数据库(可能有多个分片)
        message_dir = db_storage_dir / "message"
        print(f"[DEBUG PathFinder] 检查message目录: {message_dir} (存在:{message_dir.exists()})")
        
        if message_dir.exists():
            db_files = [f.name for f in message_dir.iterdir() if f.suffix.lower() == ".db"]
            print(f"[DEBUG PathFinder] message下的.db文件: {db_files}")
            
            for file in message_dir.iterdir():
                if file.suffix.lower() == ".db":
                    result["message"].append(str(file))
            
            # 按文件名排序
            result["message"].sort()
            print(f"[DEBUG PathFinder] ✅ 找到 {len(result['message'])} 个消息数据库")
        
        # 查找会话数据库
        session_dir = db_storage_dir / "session"
        print(f"[DEBUG PathFinder] 检查session目录: {session_dir} (存在:{session_dir.exists()})")
        
        if session_dir.exists():
            db_files = [f.name for f in session_dir.iterdir() if f.suffix.lower() == ".db"]
            print(f"[DEBUG PathFinder] session下的.db文件: {db_files}")
            
            for file in session_dir.iterdir():
                if file.suffix.lower() == ".db":
                    result["session"] = str(file)
                    print(f"[DEBUG PathFinder] ✅ 找到session.db: {file}")
                    break
        
        return result
    
    @classmethod
    def find_all_wechat_dbs(cls) -> Optional[Dict]:
        """
        完整流程:自动查找微信数据库路径
        
        Returns:
            dict: 数据库信息
            {
                "wechat_dir": "C:/Users/xxx/xwechat_files",
                "current_user": "wxid_xxx",
                "databases": {
                    "message": [...],
                    "session": "...",
                    "contact": "..."
                }
            }
        """
        print(f"\n[DEBUG PathFinder] === 开始查找微信数据库 ===")
        
        # 1. 查找微信数据目录
        data_path = cls.find_wechat_data_path()
        print(f"[DEBUG PathFinder] 数据目录: {data_path}")
        
        if not data_path:
            print(f"[DEBUG PathFinder] ❌ 未找到微信数据目录")
            return None
        
        # 2. 查找当前用户
        wxid = cls.find_current_user_wxid(data_path)
        print(f"[DEBUG PathFinder] 当前用户wxid: {wxid}")
        
        if not wxid:
            print(f"[DEBUG PathFinder] ❌ 未找到用户wxid")
            return None
        
        # 3. 查找数据库文件
        print(f"[DEBUG PathFinder] 开始查找数据库文件...")
        databases = cls.find_databases(wxid, data_path)
        print(f"[DEBUG PathFinder] 数据库查找结果:")
        print(f"  - contact: {databases.get('contact')}")
        print(f"  - message: {databases.get('message')}")
        print(f"  - session: {databases.get('session')}")
        
        return {
            "wechat_dir": data_path,
            "current_user": wxid,
            "databases": databases
        }
