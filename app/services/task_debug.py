"""
任务调试输出相关的辅助函数。

把这些“只影响日志可读性”的细节单独拿出来，
避免它们继续挤占任务执行主流程。
"""

import json
from logging import Logger
from typing import Any


def truncate_text(text: str, max_length: int = 120) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def summarize_debug_value(value: Any) -> str:
    if isinstance(value, dict):
        keys = list(value.keys())
        preview = ", ".join(str(key) for key in keys[:5])
        if len(keys) > 5:
            preview += ", ..."
        return f"dict，共 {len(value)} 个键：{preview}"

    if isinstance(value, list):
        if not value:
            return "list，空列表"

        preview_items = ", ".join(truncate_text(repr(item), 24) for item in value[:3])
        if len(value) > 3:
            preview_items += ", ..."
        return f"list，共 {len(value)} 项：{preview_items}"

    if isinstance(value, tuple):
        return f"tuple：{truncate_text(repr(value), 80)}"

    if isinstance(value, str):
        return truncate_text(value, 120)

    return truncate_text(repr(value), 120)


def log_image_url_candidates(logger: Logger, urls: list[str]) -> None:
    logger.debug("候选图片 URL，共 %s 条：", len(urls))
    if not urls:
        logger.debug("  (空)")
        return

    for index, url in enumerate(urls, start=1):
        logger.debug("  [%s] %s", index, url)


def log_downloaded_files(logger: Logger, files: list[str], title: str) -> None:
    logger.debug("%s，共 %s 张：", title, len(files))
    if not files:
        logger.debug("  (空)")
        return

    for index, file_path in enumerate(files, start=1):
        logger.debug("  [%s] %s", index, file_path)


def log_next_data_hits(logger: Logger, hits: list[tuple[str, Any]]) -> None:
    logger.debug("结构化命中（next_data_hits），共 %s 条：", len(hits))
    if not hits:
        logger.debug("  (空)")
        return

    for index, (path, value) in enumerate(hits, start=1):
        logger.debug("  [%s] %s", index, path)
        logger.debug("      %s", summarize_debug_value(value))


def log_parsed_info(logger: Logger, info: Any) -> None:
    logger.debug("解析结果：")
    logger.debug("标题：%s", info.title)
    logger.debug("分享标题（og:title）：%s", info.og_title)
    logger.debug("分享图片（og:image）：%s", info.og_image)
    logger.debug("页面简介（description）：%s", truncate_text(info.description, 160))
    logger.debug("标准地址（canonical）：%s", info.canonical_url)
    logger.debug("作品 ID：%s", info.artwork_id)
    logger.debug("作者 ID：%s", info.user_id)
    logger.debug("作者名：%s", info.author_name)
    logger.debug("标签：%s", json.dumps(info.tags, ensure_ascii=False))
    logger.debug("页数：%s", info.page_count)
    logger.debug("是否包含 __NEXT_DATA__：%s", info.has_next_data)

    log_image_url_candidates(logger, info.possible_image_urls[:10])
    log_next_data_hits(logger, info.next_data_hits)
