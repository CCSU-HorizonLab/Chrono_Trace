"""微信数据库路径自动寻址模块 (仅支持V4)"""
import logging
import os
import re
import winreg
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


logger = logging.getLogger(__name__)


class WeChatPathFinder:
    """微信数据库路径查找器 (仅支持微信4.0+版本)"""

    WECHAT_DATA_DIR_NAMES = {"xwechat_files", "wechat files"}
    SYSTEM_DIR_NAMES = {"all users", "applet", "wmpf"}
    MAX_SCAN_DEPTH = 4

    @staticmethod
    def _normalize_path(path: Path) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    @classmethod
    def _append_unique_paths(
        cls,
        container: List[Tuple[Path, int]],
        seen: Dict[str, int],
        paths: Iterable[Path],
        aggressive_depth: int,
    ) -> None:
        for path in paths:
            normalized = cls._normalize_path(path)
            existing_index = seen.get(normalized)
            if existing_index is not None:
                existing_path, existing_depth = container[existing_index]
                if aggressive_depth > existing_depth:
                    container[existing_index] = (existing_path, aggressive_depth)
                continue

            seen[normalized] = len(container)
            container.append((path, aggressive_depth))

    @staticmethod
    def _query_registry_value(
        key_path: str,
        value_name: str,
        hives: Tuple[int, ...] = (winreg.HKEY_CURRENT_USER,),
    ) -> Optional[str]:
        for hive in hives:
            key = None
            try:
                key = winreg.OpenKey(hive, key_path)
                value, _ = winreg.QueryValueEx(key, value_name)
                if isinstance(value, str):
                    expanded = os.path.expandvars(value).strip()
                    if expanded:
                        return expanded
            except OSError:
                continue
            finally:
                if key is not None:
                    try:
                        winreg.CloseKey(key)
                    except OSError:
                        pass

        return None

    @classmethod
    def _get_documents_paths(cls) -> List[Path]:
        paths: List[Path] = []
        seen = set()

        def _add(path: Optional[Path]) -> None:
            if not path:
                return

            normalized = cls._normalize_path(path)
            if normalized in seen:
                return
            seen.add(normalized)
            paths.append(path)

        shell_personal = cls._query_registry_value(
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            "Personal",
        )
        if not shell_personal:
            shell_personal = cls._query_registry_value(
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
                "Personal",
            )

        if shell_personal:
            _add(Path(shell_personal))

        home = Path.home()
        _add(home / "Documents")

        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            _add(Path(os.path.expandvars(userprofile)) / "Documents")

        for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            onedrive_root = os.environ.get(env_name)
            if not onedrive_root:
                continue

            expanded = Path(os.path.expandvars(onedrive_root))
            _add(expanded)
            _add(expanded / "Documents")

        return paths

    @staticmethod
    def _looks_like_wechat_user_dir(path: Path) -> bool:
        if not path or not path.exists() or not path.is_dir():
            return False
        return path.name.startswith("wxid_") and (path / "db_storage").is_dir()

    @staticmethod
    def _looks_like_wechat_data_dir(path: Path) -> bool:
        """判断一个目录是否像微信数据根目录。"""
        if not path or not path.exists() or not path.is_dir():
            return False

        if path.name.startswith("wxid_"):
            return False

        try:
            for child in path.iterdir():
                if not child.is_dir():
                    continue
                if WeChatPathFinder._looks_like_wechat_user_dir(child):
                    return True
        except OSError:
            return False

        return False

    @classmethod
    def _expand_data_dir_candidates(cls, base_path: Path) -> List[Path]:
        """从一个可能的基路径展开出真正的数据目录候选项。"""
        candidates: List[Path] = []
        seen = set()

        def _add(path: Path) -> None:
            normalized = cls._normalize_path(path)
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(path)

        if base_path.name.startswith("wxid_"):
            _add(base_path.parent)
        _add(base_path)
        _add(base_path / "xwechat_files")
        _add(base_path / "WeChat Files")

        if base_path.name.lower() not in {"documents", *cls.WECHAT_DATA_DIR_NAMES}:
            _add(base_path / "Documents")
            _add(base_path / "Documents" / "xwechat_files")
            _add(base_path / "Documents" / "WeChat Files")

        return candidates

    @classmethod
    def _discover_wechat_root_near(
        cls,
        root: Path,
        max_depth: int = MAX_SCAN_DEPTH,
        aggressive_depth: int = 1,
    ) -> Optional[Path]:
        if not root.exists() or not root.is_dir():
            return None

        queue = deque([(root, 0)])
        seen = set()

        while queue:
            current, depth = queue.popleft()
            normalized = cls._normalize_path(current)
            if normalized in seen:
                continue
            seen.add(normalized)

            if cls._looks_like_wechat_data_dir(current):
                return current

            if cls._looks_like_wechat_user_dir(current):
                return current.parent if current.parent.exists() else current

            if current.name.lower() in cls.WECHAT_DATA_DIR_NAMES:
                return current

            if depth >= max_depth:
                continue

            try:
                children = [child for child in current.iterdir() if child.is_dir()]
            except OSError:
                continue

            for child in children:
                child_name = child.name.lower()
                should_descend = (
                    child_name in cls.WECHAT_DATA_DIR_NAMES
                    or child.name.startswith("wxid_")
                    or child_name == "documents"
                    or child_name.startswith("onedrive")
                    or depth < aggressive_depth
                )
                if should_descend:
                    queue.append((child, depth + 1))

        return None

    @classmethod
    def _resolve_wechat_data_dir(cls, candidate: Path, aggressive_depth: int = 1) -> Optional[Path]:
        if not candidate.exists() or not candidate.is_dir():
            return None

        if cls._looks_like_wechat_user_dir(candidate):
            return candidate.parent if candidate.parent.exists() else candidate

        if cls._looks_like_wechat_data_dir(candidate):
            return candidate

        discovered = cls._discover_wechat_root_near(candidate, aggressive_depth=aggressive_depth)
        if discovered:
            return discovered

        if candidate.name.lower() in cls.WECHAT_DATA_DIR_NAMES:
            return candidate

        return None

    @classmethod
    def _user_dir_has_databases(cls, user_dir: Path) -> bool:
        db_storage_dir = user_dir / "db_storage"
        if not db_storage_dir.is_dir():
            return False

        for child_name in ("contact", "message", "session"):
            child_dir = db_storage_dir / child_name
            if not child_dir.is_dir():
                continue

            try:
                if any(file.is_file() and file.suffix.lower() == ".db" for file in child_dir.iterdir()):
                    return True
            except OSError:
                continue

        return False

    @classmethod
    def _discover_wechat_user_dirs_near(cls, root: Path, max_depth: int = 3) -> List[Path]:
        if not root.exists() or not root.is_dir():
            return []

        queue = deque([(root, 0)])
        seen = set()
        discovered: List[Path] = []

        while queue:
            current, depth = queue.popleft()
            normalized = cls._normalize_path(current)
            if normalized in seen:
                continue
            seen.add(normalized)

            if current.name.startswith("wxid_"):
                discovered.append(current)
                if (current / "db_storage").is_dir():
                    continue

            if depth >= max_depth:
                continue

            try:
                children = [child for child in current.iterdir() if child.is_dir()]
            except OSError:
                continue

            for child in children:
                child_name = child.name.lower()
                should_descend = (
                    child.name.startswith("wxid_")
                    or child_name in cls.WECHAT_DATA_DIR_NAMES
                    or child_name == "documents"
                    or child_name.startswith("onedrive")
                    or depth == 0
                )
                if should_descend:
                    queue.append((child, depth + 1))

        return discovered

    @classmethod
    def _find_user_dirs(cls, data_path: Path) -> List[Path]:
        resolved_root = cls._resolve_wechat_data_dir(data_path) or data_path
        candidates: Dict[str, Tuple[Path, int, float]] = {}

        def _register(path: Path) -> None:
            if not cls._looks_like_wechat_user_dir(path):
                return

            has_db_storage = (path / "db_storage").is_dir()
            has_databases = cls._user_dir_has_databases(path)
            score = 2 if has_databases else 1 if has_db_storage else 0

            try:
                stat_target = path / "db_storage" if has_db_storage else path
                mtime = stat_target.stat().st_mtime
            except OSError:
                mtime = 0.0

            existing = candidates.get(path.name)
            if existing is None or (score, mtime) > (existing[1], existing[2]):
                candidates[path.name] = (path, score, mtime)

        if resolved_root.is_dir():
            _register(resolved_root)
            try:
                for child in resolved_root.iterdir():
                    if child.is_dir() and child.name.lower() not in cls.SYSTEM_DIR_NAMES:
                        _register(child)
            except OSError:
                pass

        if not candidates or not any(item[1] > 0 for item in candidates.values()):
            for path in cls._discover_wechat_user_dirs_near(resolved_root):
                if path.name.lower() not in cls.SYSTEM_DIR_NAMES:
                    _register(path)

        ordered = sorted(
            candidates.values(),
            key=lambda item: (item[1], item[2], item[0].name),
            reverse=True,
        )
        return [item[0] for item in ordered]

    @staticmethod
    def _build_wxid_candidates(wxid: str) -> List[str]:
        normalized = str(wxid or "").strip()
        if not normalized:
            return []

        candidates = [normalized]
        match = re.match(r"^(wxid_[a-z0-9]+)_([a-z0-9]{4,6})$", normalized)
        if match:
            base_wxid = match.group(1)
            if base_wxid not in candidates:
                candidates.append(base_wxid)

        return candidates

    @classmethod
    def _resolve_user_dir(cls, wxid: str, data_path: Path) -> Optional[Path]:
        if not wxid or not data_path.exists() or not data_path.is_dir():
            return None

        wxid_candidates = cls._build_wxid_candidates(wxid)

        direct_candidates: List[Path] = []
        if data_path.name in wxid_candidates or data_path.name.startswith(f"{wxid}_"):
            direct_candidates.append(data_path)

        for candidate_name in wxid_candidates:
            direct_candidates.append(data_path / candidate_name)

        if data_path.is_dir():
            try:
                for child in data_path.iterdir():
                    if not child.is_dir():
                        continue
                    if child.name in wxid_candidates or child.name.startswith(f"{wxid}_"):
                        direct_candidates.append(child)
            except OSError:
                pass

        seen_paths = set()
        for candidate in direct_candidates:
            normalized = cls._normalize_path(candidate)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            if candidate.is_dir() and (candidate / "db_storage").is_dir():
                return candidate

        for candidate in cls._find_user_dirs(data_path):
            if candidate.name in wxid_candidates or candidate.name.startswith(f"{wxid}_"):
                return candidate

        return None

    @classmethod
    def find_wechat_install_path(cls) -> Optional[str]:
        """
        从Windows注册表获取微信安装路径

        Returns:
            str: 微信安装路径,失败返回None
        """
        return cls._query_registry_value(
            r"Software\Tencent\WeChat",
            "InstallPath",
            hives=(winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE),
        )

    @classmethod
    def find_wechat_data_path(cls) -> Optional[str]:
        """
        查找微信数据目录(支持新版xwechat_files和旧版WeChat Files)

        Returns:
            str: 微信数据目录路径
        """
        candidate_paths: List[Tuple[Path, int]] = []
        seen: Dict[str, int] = {}

        registry_data_path = cls._query_registry_value(r"Software\Tencent\WeChat", "FileSavePath")
        if registry_data_path:
            cls._append_unique_paths(
                candidate_paths,
                seen,
                cls._expand_data_dir_candidates(Path(registry_data_path)),
                aggressive_depth=2,
            )

        for documents_path in cls._get_documents_paths():
            cls._append_unique_paths(
                candidate_paths,
                seen,
                cls._expand_data_dir_candidates(documents_path),
                aggressive_depth=1,
            )

        home_path = Path.home()
        cls._append_unique_paths(
            candidate_paths,
            seen,
            cls._expand_data_dir_candidates(home_path),
            aggressive_depth=1,
        )

        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            cls._append_unique_paths(
                candidate_paths,
                seen,
                cls._expand_data_dir_candidates(Path(os.path.expandvars(userprofile))),
                aggressive_depth=1,
            )

        install_path = cls.find_wechat_install_path()
        if install_path:
            install_dir = Path(install_path)
            nearby_paths = [install_dir, install_dir.parent]
            if install_dir.parent.parent != install_dir.parent:
                nearby_paths.append(install_dir.parent.parent)
            cls._append_unique_paths(candidate_paths, seen, nearby_paths, aggressive_depth=1)

        for candidate_path, aggressive_depth in candidate_paths:
            resolved = cls._resolve_wechat_data_dir(candidate_path, aggressive_depth=aggressive_depth)
            if resolved:
                return str(resolved)

        return None

    @classmethod
    def find_all_user_wxids(cls, data_path: str) -> List[str]:
        """返回当前数据目录下所有候选微信账号。"""
        root = Path(data_path)
        return [user_dir.name for user_dir in cls._find_user_dirs(root)]

    @classmethod
    def find_current_user_wxid(cls, data_path: str) -> Optional[str]:
        """
        查找当前活跃的微信用户ID

        Args:
            data_path: 微信数据目录

        Returns:
            str: wxid(如 wxid_xxx),优先选择真实存在数据库的目录,再按修改时间排序
        """
        if not data_path or not os.path.exists(data_path):
            return None

        user_dirs = cls.find_all_user_wxids(data_path)
        if user_dirs:
            return user_dirs[0]

        return None

    @classmethod
    def find_databases(cls, wxid: str, data_path: str) -> Dict[str, List[str]]:
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
        user_dir = cls._resolve_user_dir(wxid, Path(data_path))
        logger.debug(f"[DEBUG PathFinder] wxid={wxid}, 数据根目录={data_path}, 命中的用户目录={user_dir}")

        if not user_dir:
            logger.debug("[DEBUG PathFinder] ❌ 未命中用户目录")
            return {"message": [], "session": None, "contact": None}

        db_storage_dir = user_dir / "db_storage"
        logger.debug(f"[DEBUG PathFinder] db_storage路径: {db_storage_dir}")
        logger.debug(f"[DEBUG PathFinder] db_storage存在: {db_storage_dir.exists()}")

        if not db_storage_dir.exists():
            logger.debug("[DEBUG PathFinder] ❌ db_storage目录不存在!")
            return {"message": [], "session": None, "contact": None}

        subdirs = [d.name for d in db_storage_dir.iterdir() if d.is_dir()]
        logger.debug(f"[DEBUG PathFinder] db_storage子目录: {subdirs}")

        return cls._find_databases_v4(db_storage_dir)

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
                "available_users": ["wxid_xxx", "wxid_yyy"],
                "databases": {
                    "message": [...],
                    "session": "...",
                    "contact": "..."
                }
            }
        """
        logger.info("\n[DEBUG PathFinder] === 开始查找微信数据库 ===")

        # 1. 查找微信数据目录
        data_path = cls.find_wechat_data_path()
        logger.debug(f"[DEBUG PathFinder] 数据目录: {data_path}")

        if not data_path:
            logger.debug("[DEBUG PathFinder] ❌ 未找到微信数据目录")
            return None

        # 2. 查找当前用户
        wxids = cls.find_all_user_wxids(data_path)
        logger.debug(f"[DEBUG PathFinder] 候选用户wxid列表: {wxids}")

        if not wxids:
            logger.debug("[DEBUG PathFinder] ❌ 未找到用户wxid")
            return None

        wxid = wxids[0]
        logger.debug(f"[DEBUG PathFinder] 当前用户wxid: {wxid}")

        # 3. 查找数据库文件
        logger.info("[DEBUG PathFinder] 开始查找数据库文件...")
        databases = cls.find_databases(wxid, data_path)
        logger.debug("[DEBUG PathFinder] 数据库查找结果:")
        logger.debug(f"  - contact: {databases.get('contact')}")
        logger.debug(f"  - message: {databases.get('message')}")
        logger.debug(f"  - session: {databases.get('session')}")

        return {
            "wechat_dir": data_path,
            "current_user": wxid,
            "available_users": wxids,
            "databases": databases
        }
