"""微信数据库版本检测器"""

import os
import logging


logger = logging.getLogger(__name__)


def detect_wechat_version(wechat_dir: str) -> str:
    """
    检测微信数据库版本

    Args:
        wechat_dir: 微信用户数据目录 (如 xwechat_files/wxid_xxx 或 WeChat Files/wxid_xxx)

    Returns:
        "v4"  - 新版微信4.0+ (db_storage目录存在)
        "v3"  - 旧版微信3.9 (Msg/MicroMsg.db 结构，仅支持检测用于升级引导，不支持导入)
        "unknown" - 无法识别

    检测逻辑:
        1. 检查是否存在 db_storage 目录 (V4特征)
        2. 检查是否存在 Msg/MicroMsg.db 或 Msg/Multi/MSG*.db (V3特征)
    """
    if not wechat_dir or not os.path.exists(wechat_dir):
        return "unknown"

    # 检查 V4 特征目录
    db_storage = os.path.join(wechat_dir, "db_storage")
    if os.path.exists(db_storage):
        return "v4"

    # 检查 V3 特征目录 (3.9: Msg/MicroMsg.db, Msg/Multi/MSG0.db...)
    msg_dir = os.path.join(wechat_dir, "Msg")
    if os.path.isfile(os.path.join(msg_dir, "MicroMsg.db")):
        return "v3"

    multi_dir = os.path.join(msg_dir, "Multi")
    if os.path.isdir(multi_dir):
        try:
            for file_name in os.listdir(multi_dir):
                if file_name.lower().startswith("msg") and file_name.lower().endswith(".db"):
                    return "v3"
        except OSError:
            pass

    return "unknown"
