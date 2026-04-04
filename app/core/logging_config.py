"""
这个文件负责项目的基础日志配置。

目标是：
- 主流程和任务层不再直接依赖大量 `print`
- 可以按级别区分日常信息、调试信息和错误信息
- 仍然保留适合终端阅读的输出格式
"""

from pathlib import Path
import logging
import sys

from app.core.config import settings


LOGGER_ROOT_NAME = "pixiv_crawl"


def get_logger(name: str | None = None) -> logging.Logger:
    """
    获取项目日志对象。
    """
    if not name:
        return logging.getLogger(LOGGER_ROOT_NAME)
    return logging.getLogger(f"{LOGGER_ROOT_NAME}.{name}")


def configure_logging() -> logging.Logger:
    """
    初始化项目日志配置。

    这个方法是幂等的：
    - 多次调用不会不断重复添加 handler
    - 但会根据当前配置更新日志级别
    """
    logger = logging.getLogger(LOGGER_ROOT_NAME)
    level = logging.DEBUG if settings.verbose_debug_output else logging.INFO
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(console_handler)

        if settings.log_path.strip():
            log_path = Path(settings.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            logger.addHandler(file_handler)

    for handler in logger.handlers:
        handler.setLevel(level)

    return logger
