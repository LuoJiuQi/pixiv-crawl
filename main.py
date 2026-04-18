"""
这个文件是整个项目的“程序入口”。

所谓入口，可以理解成：
“当你运行 `python main.py` 时，程序最先从哪里开始执行。”

现在这份入口文件已经被刻意拆薄了：
- 命令行交互放到 `app/services/cli_service.py`
- 单作品处理和批量任务流程放到 `app/services/task_service.py`
- 这里自己只保留“总调度”职责

这样做的好处是：
- 读起来更顺
- 后面继续扩展时不容易越改越乱
- 没学过代码的人也更容易看出每一步是在干什么
"""

import argparse
import sys

from app.browser.client import BrowserClient
from app.browser.login import PixivLoginService
from app.core.logging_config import configure_logging, get_logger
from app.crawler.author_crawler import AuthorCrawler
from app.crawler.artwork_crawler import ArtworkCrawler
from app.db.download_record_repository import DownloadRecordRepository
from app.downloader.image_downloader import PixivImageDownloader
from app.services import console_service
from app.services.cli_service import (
    AuthorCollectOptions,
    archive_old_records,
    collect_author_options,
    choose_action,
    collect_artwork_ids,
    collect_retry_artwork_ids,
    export_failed_records,
    parse_user_id,
    parse_artwork_ids,
    show_history,
)
from app.services.task_service import (
    process_artwork_batch,
    select_incremental_artwork_ids,
)

logger = get_logger(__name__)


def action_requires_direct_artwork_input(action: str) -> bool:
    """
    判断当前动作是否需要“手动输入作品 ID”。

    现在会自己去收集作品来源的模式有：
    - `crawl_author`：先从作者主页拿作品列表
    - `crawl_following`：先从关注画师列表里拿作者，再继续增量更新
    """
    return action not in {"crawl_author", "crawl_following"}


def build_argument_parser() -> argparse.ArgumentParser:
    """
    构建非交互命令行参数解析器。

    如果没有提供任何子命令，程序仍然会回到原来的交互菜单模式。
    """
    parser = argparse.ArgumentParser(
        description="Pixiv 批量抓取工具。不给子命令时，将进入交互菜单模式。",
    )
    subparsers = parser.add_subparsers(dest="action")

    crawl_parser = subparsers.add_parser("crawl", help="批量抓取作品")
    crawl_parser.add_argument(
        "artwork_inputs",
        nargs="+",
        help="作品 ID 或作品链接，可一次传多个。",
    )

    author_parser = subparsers.add_parser("crawl-author", help="按作者抓取作品")
    author_parser.add_argument("author", help="作者 ID 或作者主页链接。")
    author_parser.add_argument("--limit", type=int, default=0, help="最多抓取多少个作品。")
    author_parser.add_argument(
        "--update-mode",
        choices=["incremental", "full"],
        default="incremental",
        help="作者抓取模式，默认 incremental。",
    )
    author_parser.add_argument(
        "--completed-streak-limit",
        type=int,
        default=10,
        help="增量模式下连续遇到多少个已完成作品后停止扫描。",
    )

    following_parser = subparsers.add_parser("crawl-following", help="按关注列表更新画师")
    following_parser.add_argument("--limit", type=int, default=0, help="最多处理多少位关注画师。")
    following_parser.add_argument(
        "--completed-streak-limit",
        type=int,
        default=10,
        help="每位作者增量模式下连续遇到多少个已完成作品后停止扫描。",
    )

    history_parser = subparsers.add_parser("history", help="查看历史记录")
    history_parser.add_argument(
        "--status",
        choices=["all", "completed", "failed"],
        default="all",
        help="按状态筛选。",
    )
    history_parser.add_argument("--error-type", default="", help="按失败类型筛选。")
    history_parser.add_argument("--limit", type=int, default=10, help="最多展示多少条记录。")

    retry_parser = subparsers.add_parser("retry-failed", help="重试失败任务")
    retry_parser.add_argument("--error-type", default="", help="只重试某一种失败类型。")
    retry_parser.add_argument("--limit", type=int, default=0, help="最多重试多少条失败记录。")

    export_parser = subparsers.add_parser("export-failed", help="导出失败清单")
    export_parser.add_argument("--error-type", default="", help="只导出某一种失败类型。")
    export_parser.add_argument("--limit", type=int, default=0, help="最多导出多少条失败记录。")
    export_parser.add_argument(
        "--format",
        choices=["json", "txt"],
        default="json",
        help="导出格式。",
    )

    archive_parser = subparsers.add_parser("archive-records", help="归档并清理旧记录")
    archive_parser.add_argument(
        "--status",
        choices=["all", "completed", "failed"],
        default="completed",
        help="要归档的记录状态。",
    )
    archive_parser.add_argument("--days", type=int, default=30, help="归档多少天以前的记录。")
    archive_parser.add_argument("--limit", type=int, default=100, help="最多归档多少条记录。")
    archive_parser.add_argument(
        "--format",
        choices=["json", "txt"],
        default="json",
        help="归档文件格式。",
    )
    archive_parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行归档并删除，不再二次提示。",
    )

    return parser


def parse_runtime_arguments(argv: list[str] | None) -> argparse.Namespace | None:
    """
    解析运行时参数。

    约定：
    - `argv is None`：表示使用原来的交互模式
    - `argv == []`：脚本直接启动但没带参数，也回到交互模式
    """
    if argv is None or not argv:
        return None

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    raw_action = args.action

    if raw_action == "crawl":
        artwork_ids = parse_artwork_ids("\n".join(args.artwork_inputs))
        if not artwork_ids:
            parser.error("没有识别到有效的作品 ID，请传入作品 ID 或作品链接。")
        args.artwork_ids = artwork_ids

    if raw_action == "crawl-author":
        user_id = parse_user_id(args.author)
        if not user_id:
            parser.error("没有识别到有效的作者 ID，请传入作者 ID 或作者主页链接。")
        if args.limit < 0:
            parser.error("--limit 不能小于 0。")
        if args.completed_streak_limit <= 0:
            parser.error("--completed-streak-limit 必须大于 0。")
        args.author_request = {
            "user_id": user_id,
            "limit": args.limit or None,
            "update_mode": args.update_mode,
            "completed_streak_limit": args.completed_streak_limit,
        }

    if raw_action == "crawl-following":
        if args.limit < 0:
            parser.error("--limit 不能小于 0。")
        if args.completed_streak_limit <= 0:
            parser.error("--completed-streak-limit 必须大于 0。")
        args.following_limit = args.limit or None

    if raw_action == "history":
        if args.limit <= 0:
            parser.error("--limit 必须大于 0。")

    if raw_action == "retry-failed":
        if args.limit < 0:
            parser.error("--limit 不能小于 0。")

    if raw_action == "export-failed":
        if args.limit < 0:
            parser.error("--limit 不能小于 0。")

    if raw_action == "archive-records":
        if args.days <= 0:
            parser.error("--days 必须大于 0。")
        if args.limit <= 0:
            parser.error("--limit 必须大于 0。")
        if not args.yes:
            parser.error("archive-records 需要显式传入 --yes 才会执行删除。")

    args.action = raw_action.replace("-", "_")
    return args


def _normalize_optional_text(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def main(argv: list[str] | None = None) -> None:
    """
    主函数。

    它像一个“总指挥”：
    - 先决定本次要执行哪种模式
    - 再准备数据库、浏览器、登录服务
    - 最后把任务交给更具体的服务去执行

    换句话说，这里尽量只做“安排工作”，
    不做太多具体实现细节。
    """
    configure_logging()
    client = BrowserClient()
    record_repository = DownloadRecordRepository()
    runtime_args = parse_runtime_arguments(argv)
    interactive_mode = runtime_args is None

    try:
        # 先确保数据库表已经准备好。
        # 这样后面不管是查看历史、重试失败，还是正式抓取，都有地方读写记录。
        record_repository.initialize()

        action = runtime_args.action if runtime_args else choose_action()
        if action == "history":
            show_history(
                record_repository,
                status=None if not runtime_args or runtime_args.status == "all" else runtime_args.status,
                error_type=_normalize_optional_text(runtime_args.error_type) if runtime_args else None,
                limit=runtime_args.limit if runtime_args else 10,
                prompt_for_filters=interactive_mode,
            )
            return

        if action == "export_failed":
            export_failed_records(
                record_repository,
                error_type=_normalize_optional_text(runtime_args.error_type) if runtime_args else None,
                limit=runtime_args.limit if runtime_args else None,
                file_format=runtime_args.format if runtime_args else "json",
                interactive=interactive_mode,
            )
            return

        if action == "archive_records":
            archive_old_records(
                record_repository,
                status=(
                    None
                    if runtime_args and runtime_args.status == "all"
                    else runtime_args.status if runtime_args else None
                ),
                days=runtime_args.days if runtime_args else 30,
                limit=runtime_args.limit if runtime_args else 100,
                file_format=runtime_args.format if runtime_args else "json",
                interactive=interactive_mode,
                confirmed=bool(runtime_args.yes) if runtime_args else False,
            )
            return

        author_request: AuthorCollectOptions | None = None
        if action == "retry_failed":
            artwork_ids = collect_retry_artwork_ids(
                record_repository,
                error_type=_normalize_optional_text(runtime_args.error_type) if runtime_args else None,
                limit=runtime_args.limit if runtime_args else None,
                interactive=interactive_mode,
            )
            if not artwork_ids:
                return
        elif action == "crawl_author":
            author_request = runtime_args.author_request if runtime_args else collect_author_options()
            artwork_ids = []
        elif action_requires_direct_artwork_input(action):
            artwork_ids = runtime_args.artwork_ids if runtime_args else collect_artwork_ids()
        else:
            artwork_ids = []

        # 到这里说明本次真的需要访问网站，
        # 所以才启动浏览器。
        client.start()

        login_service = PixivLoginService(client)

        # 如果本地已经有登录态文件，就优先尝试复用。
        # 复用失败时，再删除旧状态并重新登录。
        if client.state_manager.state_exists():
            if login_service.is_logged_in():
                logger.info("检测到已有可用登录状态，无需重新登录。")
            else:
                logger.warning("已有登录状态失效，准备重新登录。")
                client.state_manager.delete_state()
                login_result = login_service.login_and_save_state()
                if not login_result["success"]:
                    logger.error("登录未完成，程序结束。")
                    return
        else:
            logger.info("未检测到登录状态，准备首次登录。")
            login_result = login_service.login_and_save_state()
            if not login_result["success"]:
                logger.error("登录未完成，程序结束。")
                return

        crawler = ArtworkCrawler(client)
        downloader = PixivImageDownloader(client)
        author_crawler = AuthorCrawler(client)

        if action == "crawl_author":
            # 对人来说，这里前面已经在 `crawl_author` 分支里赋过值了。
            # 但类型检查器只看到：`author_request` 的类型是“元组或 None”。
            # 所以这里显式拦一下，告诉它后面一定是可解包的元组。
            if author_request is None:
                raise RuntimeError("作者抓取模式缺少作者输入，请重新选择操作。")

            user_id = author_request["user_id"]
            limit = author_request["limit"]
            author_artwork_ids = author_crawler.collect_author_artwork_ids(user_id, limit=limit)
            if not author_artwork_ids:
                logger.warning("未从作者 %s 的主页里识别到作品 ID。", user_id)
                return

            logger.info("已从作者 %s 主页识别到 %s 个作品。", user_id, len(author_artwork_ids))

            if author_request["update_mode"] == "incremental":
                selection = select_incremental_artwork_ids(
                    author_artwork_ids,
                    record_repository,
                    completed_streak_limit=author_request["completed_streak_limit"],
                )
                artwork_ids = selection["candidate_artwork_ids"]
                console_service.show_incremental_selection_summary(selection)

                if not artwork_ids:
                    logger.info("这位作者当前没有需要增量处理的新作品。")
                    return
            else:
                artwork_ids = author_artwork_ids
                logger.info("当前使用全量模式，会按识别到的作品列表逐个处理。")

        if action == "crawl_following":
            # 这里的目标不是抓“一个作者”，
            # 而是先把“我当前关注的所有作者”收集出来，
            # 再逐个复用现有的作者增量更新流程。
            followed_user_ids = author_crawler.collect_following_user_ids(
                limit=runtime_args.following_limit if runtime_args else None
            )
            if not followed_user_ids:
                logger.info("当前没有识别到任何已关注画师。")
                return

            logger.info("本次共识别到 %s 个关注画师。", len(followed_user_ids))
            logger.debug("关注画师 ID 列表：%s", followed_user_ids)

            total_success_results = []
            total_failed_results = []
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
                        completed_streak_limit=(
                            runtime_args.completed_streak_limit if runtime_args else 10
                        ),
                    )
                    console_service.show_incremental_selection_summary(selection)

                    artwork_ids = selection["candidate_artwork_ids"]
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

                    total_success_results.extend(summary["success_results"])
                    total_failed_results.extend(summary["failed_results"])
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

            if interactive_mode:
                console_service.pause_before_exit()
            return

        logger.info("本次共识别到 %s 个作品 ID。", len(artwork_ids))
        logger.debug("本次作品 ID 列表：%s", artwork_ids)

        summary = process_artwork_batch(
            artwork_ids=artwork_ids,
            crawler=crawler,
            downloader=downloader,
            record_repository=record_repository,
        )
        console_service.show_batch_summary(summary)

        # 留一点时间给你人工确认结果。
        if interactive_mode:
            console_service.pause_before_exit()
    finally:
        # 不管中间有没有报错，最后都要把浏览器关掉。
        # 这样可以避免后台残留浏览器进程。
        client.close()


# 这行的意思是：
# 只有你“直接运行这个文件”时，程序才会从这里启动。
# 如果别的文件只是 `import main`，那就不会自动执行。
if __name__ == "__main__":
    main(sys.argv[1:])
