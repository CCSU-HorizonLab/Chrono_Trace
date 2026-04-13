"""微信数据库路径自动寻址模块 (仅支持V4)"""
import os
import logging
import winreg
from pathlib import Path
from typing import Optional, Dict, List


logger = logging.getLogger(__name__)
class WeChatPathFinder:
    """微信数据库路径查找器 (仅支持微信4.0+版本)"""

    @staticmethod
    def _looks_like_wechat_data_dir(path: Path) -> bool:
        """判断一个目录是否像微信数据根目录。"""
        if not path or not path.exists() or not path.is_dir():
            return False

        try:
            for child in path.iterdir():
                if not child.is_dir():
                    continue
                if child.name.startswith("wxid_"):
                    return True
        except Exception:
            return False

        return False

    @classmethod
    def _expand_data_dir_candidates(cls, base_path: Path) -> List[Path]:
        """从一个可能的基路径展开出真正的数据目录候选项。"""
        candidates: List[Path] = []
        seen = set()

        def _add(path: Path):
            normalized = os.path.normcase(str(path))
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(path)

        _add(base_path)
        _add(base_path / "xwechat_files")
        _add(base_path / "WeChat Files")

        if base_path.name.lower() != "documents":
            _add(base_path / "Documents" / "xwechat_files")
            _add(base_path / "Documents" / "WeChat Files")

        return candidates
    
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
        candidate_paths: List[Path] = []
        seen = set()

        def _append_candidates(paths: List[Path]):
            for path in paths:
                normalized = os.path.normcase(str(path))
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidate_paths.append(path)

        try:
            # 方法1:从注册表获取
            key_path = r"Software\Tencent\WeChat"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            data_path, _ = winreg.QueryValueEx(key, "FileSavePath")
            winreg.CloseKey(key)

            if data_path:
                _append_candidates(WeChatPathFinder._expand_data_dir_candidates(Path(data_path)))
        except Exception:
            pass

        # 方法2:尝试多个可能的路径
        # 新版微信使用 xwechat_files (4.0+)
        try:
            username = os.getlogin()
            possible_paths = [
                Path(f"C:/Users/{username}/xwechat_files"),  # 新版
                Path.home() / "xwechat_files",  # 新版(用户目录)
                Path.home() / "Documents" / "xwechat_files",  # 新版(文档目录)
                Path.home() / "Documents" / "WeChat Files",  # 旧版(保留以防万一)
            ]
        except Exception:
            possible_paths = [
                Path.home() / "xwechat_files",
                Path.home() / "Documents" / "xwechat_files",
                Path.home() / "Documents" / "WeChat Files",
            ]

        _append_candidates(possible_paths)

        for path in candidate_paths:
            if WeChatPathFinder._looks_like_wechat_data_dir(path):
                return str(path)

        for path in candidate_paths:
            if path.exists() and path.is_dir() and path.name.lower() in {"xwechat_files", "wechat files"}:
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
        logger.debug(f"[DEBUG PathFinder] db_storage路径: {user_dir}")
        logger.debug(f"[DEBUG PathFinder] db_storage存在: {user_dir.exists()}")
        
        if not user_dir.exists():
            logger.debug(f"[DEBUG PathFinder] ❌ db_storage目录不存在!")
            return {"message": [], "session": None, "contact": None}
        
        # 列出db_storage下的子目录
        if user_dir.exists():
            subdirs = [d.name for d in user_dir.iterdir() if d.is_dir()]
            logger.debug(f"[DEBUG PathFinder] db_storage子目录: {subdirs}")
        
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
        logger.debug(f"[DEBUG PathFinder] 检查contact目录: {contact_dir} (存在:{contact_dir.exists()})")
        
        if contact_dir.exists():
            db_files = [f.name for f in contact_dir.iterdir() if f.suffix.lower() == ".db"]
            logger.debug(f"[DEBUG PathFinder] contact下的.db文件: {db_files}")
            
            for file in contact_dir.iterdir():
                if file.suffix.lower() == ".db":
                    result["contact"] = str(file)
                    logger.info(f"[DEBUG PathFinder] ✅ 找到contact.db: {file}")
                    break
        
        # 查找消息数据库(可能有多个分片)
        message_dir = db_storage_dir / "message"
        logger.debug(f"[DEBUG PathFinder] 检查message目录: {message_dir} (存在:{message_dir.exists()})")
        
        if message_dir.exists():
            db_files = [f.name for f in message_dir.iterdir() if f.suffix.lower() == ".db"]
            logger.debug(f"[DEBUG PathFinder] message下的.db文件: {db_files}")
            
            for file in message_dir.iterdir():
                if file.suffix.lower() == ".db":
                    result["message"].append(str(file))
            
            # 按文件名排序
            result["message"].sort()
            logger.info(f"[DEBUG PathFinder] ✅ 找到 {len(result['message'])} 个消息数据库")
        
        # 查找会话数据库
        session_dir = db_storage_dir / "session"
        logger.debug(f"[DEBUG PathFinder] 检查session目录: {session_dir} (存在:{session_dir.exists()})")
        
        if session_dir.exists():
            db_files = [f.name for f in session_dir.iterdir() if f.suffix.lower() == ".db"]
            logger.debug(f"[DEBUG PathFinder] session下的.db文件: {db_files}")
            
            for file in session_dir.iterdir():
                if file.suffix.lower() == ".db":
                    result["session"] = str(file)
                    logger.info(f"[DEBUG PathFinder] ✅ 找到session.db: {file}")
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
        logger.info(f"\n[DEBUG PathFinder] === 开始查找微信数据库 ===")
        
        # 1. 查找微信数据目录
        data_path = cls.find_wechat_data_path()
        logger.debug(f"[DEBUG PathFinder] 数据目录: {data_path}")
        
        if not data_path:
            logger.debug(f"[DEBUG PathFinder] ❌ 未找到微信数据目录")
            return None
        
        # 2. 查找当前用户
        wxid = cls.find_current_user_wxid(data_path)
        logger.debug(f"[DEBUG PathFinder] 当前用户wxid: {wxid}")
        
        if not wxid:
            logger.debug(f"[DEBUG PathFinder] ❌ 未找到用户wxid")
            return None
        
        # 3. 查找数据库文件
        logger.info(f"[DEBUG PathFinder] 开始查找数据库文件...")
        databases = cls.find_databases(wxid, data_path)
        logger.debug(f"[DEBUG PathFinder] 数据库查找结果:")
        logger.debug(f"  - contact: {databases.get('contact')}")
        logger.debug(f"  - message: {databases.get('message')}")
        logger.debug(f"  - session: {databases.get('session')}")
        
        return {
            "wechat_dir": data_path,
            "current_user": wxid,
            "databases": databases
        }
