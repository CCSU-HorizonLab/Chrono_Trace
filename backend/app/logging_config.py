import logging
import os
from logging.handlers import RotatingFileHandler
from backend.app.config import MAIN_LOG_FILE, LOG_DIR


def setup_logging(level=logging.INFO, console_only=False):
    """
    配置全局日志

    Args:
        level: 日志级别
        console_only: 是否只输出到控制台，不写入文件
    """
    # 获取根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有的 handlers，防止重复添加
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 添加控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 添加文件 handler（如果不是 console_only 模式）
    if not console_only:
        try:
            # 确保日志目录存在
            if not os.path.exists(LOG_DIR):
                os.makedirs(LOG_DIR, exist_ok=True)

            # 使用 RotatingFileHandler，单个文件最大 10MB，保留 5 个备份
            file_handler = RotatingFileHandler(
                MAIN_LOG_FILE,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

            # 记录日志文件位置
            root_logger.info(f"日志文件已配置: {MAIN_LOG_FILE}")

        except Exception as e:
            root_logger.warning(f"无法配置文件日志，将只输出到控制台: {e}")

    # 抑制第三方库的冗余日志
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
    logging.getLogger("jieba").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Hugging Face 彻底静默控制台输出的环境变量预设（可选的保险保障）
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    return root_logger


def get_logger(name):
    """
    获取命名 logger 的便捷函数

    Args:
        name: logger 名称，通常用 __name__

    Returns:
        logging.Logger: 命名 logger 实例
    """
    return logging.getLogger(name)
