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
from logging.handlers import RotatingFileHandler

from app.core.config import settings


LOGGER_ROOT_NAME = "pixiv_crawl"
CONSOLE_HANDLER_NAME = "pixiv_crawl_console"
FILE_HANDLER_NAME = "pixiv_crawl_file"


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

    console_handler = _get_named_handler(logger, CONSOLE_HANDLER_NAME)
    if console_handler is None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.set_name(CONSOLE_HANDLER_NAME)
        console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(console_handler)

    _configure_file_handler(logger)

    for handler in logger.handlers:
        handler.setLevel(level)

    return logger


def _configure_file_handler(logger: logging.Logger) -> None:
    """
    根据当前配置创建、复用或移除文件日志 handler。
    """
    log_path_text = settings.log_path.strip()
    existing_handler = _get_named_handler(logger, FILE_HANDLER_NAME)

    if not log_path_text:
        if existing_handler is not None:
            logger.removeHandler(existing_handler)
            existing_handler.close()
        return

    log_path = Path(log_path_text)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    requires_replacement = (
        existing_handler is None
        or not isinstance(existing_handler, RotatingFileHandler)
        or Path(existing_handler.baseFilename) != log_path.resolve()
        or existing_handler.maxBytes != settings.log_max_bytes
        or existing_handler.backupCount != settings.log_backup_count
    )

    if not requires_replacement:
        return

    if existing_handler is not None:
        logger.removeHandler(existing_handler)
        existing_handler.close()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.set_name(FILE_HANDLER_NAME)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(file_handler)


def _get_named_handler(logger: logging.Logger, name: str) -> logging.Handler | None:
    """
    根据 handler 名称查找已存在的日志处理器。
    """
    for handler in logger.handlers:
        if handler.get_name() == name:
            return handler
    return None
