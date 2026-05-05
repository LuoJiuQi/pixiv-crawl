"""
这个文件负责"按关注列表更新画师"的核心遍历逻辑。

从 PixivApplication._handle_crawl_following 拆分出来，
让主调度器保持精简，关注列表逻辑可独立测试。
"""

from __future__ import annotations

from typing import Any

from app.core.logging_config import get_logger
from app.crawler.author_crawler import AuthorCrawler
from app.crawler.artwork_crawler import ArtworkCrawler
from app.db.download_record_repository import DownloadRecordRepository
from app.downloader.image_downloader import PixivImageDownloader
from app.services import console_service
from app.services.task_service import process_artwork_batch, select_incremental_artwork_ids

logger = get_logger(__name__)


def process_following_authors(
    followed_user_ids: list[str],
    author_crawler: AuthorCrawler,
    crawler: ArtworkCrawler,
    downloader: PixivImageDownloader,
    record_repository: DownloadRecordRepository,
    completed_streak_limit: int = 10,
) -> None:
    """
    遍历关注画师列表，对每位画师执行增量更新。

    参数：
    - followed_user_ids：要处理的画师用户 ID 列表
    - author_crawler：用于收集每位画师的作品列表
    - crawler / downloader：用于实际处理作品
    - record_repository：用于增量筛选和记录持久化
    - completed_streak_limit：增量模式下连续已完成作品的停止阈值
    """
    logger.info("本次共识别到 %s 个关注画师。", len(followed_user_ids))

    total_success_results: list[Any] = []
    total_failed_results: list[Any] = []
    updated_authors: list[str] = []
    skipped_authors: list[str] = []
    failed_authors: list[tuple[str, str]] = []

    for index, user_id in enumerate(followed_user_ids, start=1):
        logger.debug(
            "========== 开始处理第 %s/%s 个关注画师：%s ==========",
            index,
            len(followed_user_ids),
            user_id,
        )

        try:
            author_artwork_ids = author_crawler.collect_author_artwork_ids(user_id)
            if not author_artwork_ids:
                logger.debug("作者 %s 当前没有识别到可处理作品，先跳过。", user_id)
                skipped_authors.append(user_id)
                continue

            selection = select_incremental_artwork_ids(
                author_artwork_ids,
                record_repository,
                completed_streak_limit=completed_streak_limit,
            )
            console_service.show_incremental_selection_summary(selection)

            artwork_ids = selection.candidate_artwork_ids
            if not artwork_ids:
                logger.debug("作者 %s 当前没有需要增量处理的新作品。", user_id)
                skipped_authors.append(user_id)
                continue

            summary = process_artwork_batch(
                artwork_ids=artwork_ids,
                crawler=crawler,
                downloader=downloader,
                record_repository=record_repository,
            )
            console_service.show_batch_summary(summary)

            total_success_results.extend(summary.success_results)
            total_failed_results.extend(summary.failed_results)
            updated_authors.append(user_id)
        except Exception as exc:
            error_message = str(exc)
            failed_authors.append((user_id, error_message))
            logger.warning("作者 %s 处理失败：%s", user_id, error_message)

    console_service.show_following_update_summary(
        followed_user_ids=followed_user_ids,
        updated_authors=updated_authors,
        skipped_authors=skipped_authors,
        failed_authors=failed_authors,
        total_success_results=total_success_results,
        total_failed_results=total_failed_results,
    )
