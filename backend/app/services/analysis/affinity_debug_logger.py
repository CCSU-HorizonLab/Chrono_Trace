import logging
import os

_affinity_debug_logger = None

def get_affinity_debug_logger():
    """获取共用的亲密度分析文件日志器"""
    global _affinity_debug_logger
    if _affinity_debug_logger is None:
        _affinity_debug_logger = logging.getLogger("affinity_debug_global")
        _affinity_debug_logger.setLevel(logging.DEBUG)
        
        # 将日志写入项目根目录下的 debug_affinity.log
        log_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), 
            "debug_affinity.log"
        )
        
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%H:%M:%S'))
        _affinity_debug_logger.addHandler(file_handler)
        
        # 阻止向上传递，避免在终端双重输出
        _affinity_debug_logger.propagate = False
        
    return _affinity_debug_logger

def affinity_debug_log(msg: str):
    """写入亲密度分析调试日志"""
    get_affinity_debug_logger().debug(msg)
