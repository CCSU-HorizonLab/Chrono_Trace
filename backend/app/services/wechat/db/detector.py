"""微信数据库版本检测器 (仅支持V4)"""

import os


def detect_wechat_version(wechat_dir: str) -> str:
    """
    检测微信数据库版本 (仅支持V4)
    
    Args:
        wechat_dir: 微信用户数据目录 (如 xwechat_files/wxid_xxx)
        
    Returns:
        "v4"  - 新版微信4.0+ (db_storage目录存在)
        "unknown" - 无法识别
        
    检测逻辑:
        检查是否存在 db_storage 目录 (V4特征)
    """
    if not wechat_dir or not os.path.exists(wechat_dir):
        return "unknown"
    
    # 检查 V4 特征目录
    db_storage = os.path.join(wechat_dir, "db_storage")
    if os.path.exists(db_storage):
        return "v4"
    
    return "unknown"
