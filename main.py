"""
这个文件是整个项目的“程序入口”。

所谓入口，可以理解成：
“当你运行 `python main.py` 时，程序最先从哪里开始执行。”

现在这份入口文件已经被刻意拆薄了：
- 命令行交互放到 `app/services/cli_service.py`
- 参数解析放到 `app/services/runtime_args_service.py`
- 单作品处理和批量任务流程放到 `app/services/task_service.py`
- 这里自己只保留“总调度”职责

这样做的好处是：
- 读起来更顺
- 后面继续扩展时不容易越改越乱
- 没学过代码的人也更容易看出每一步是在干什么
"""

import sys

from app.browser.client import BrowserClient
from app.browser.login import PixivLoginService
from app.core.config import settings
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
from app.services.application_service import (
    ensure_pixiv_login,
    handle_crawl_author_action,
    handle_crawl_following_action,
    handle_doctor_action,
)
from app.services.doctor_service import get_doctor_exit_code, run_doctor, summarize_doctor_report
from app.services.runtime_args_service import (
    action_requires_direct_artwork_input,
    normalize_optional_text,
    parse_runtime_arguments,
)
from app.services.scheduler_service import run_scheduled_crawl_loop
from app.services.task_service import (
    process_artwork_batch,
    select_incremental_artwork_ids,
)

logger = get_logger(__name__)
def main(argv: list[str] | None = None) -> int | None:
    """
    主函数。

    它像一个“总指挥”：
    - 先决定本次要执行哪种模式
    - 再准备数据库、浏览器、登录服务
    - 最后把任务交给更具体的服务去执行

    换句话说，这里尽量只做“安排工作”，
    不做太多具体实现细节。
    """
    console_service.configure_console_encoding()
    configure_logging()
    client = BrowserClient()
    record_repository = DownloadRecordRepository()
    runtime_args = parse_runtime_arguments(argv)
    interactive_mode = runtime_args is None

    try:
        if interactive_mode and settings.scheduled_run_enabled:
            return run_scheduled_crawl_loop()

        action = runtime_args.action if runtime_args else choose_action()
        if action == "doctor":
            return handle_doctor_action(
                runtime_args=runtime_args,
                interactive_mode=interactive_mode,
                console_service=console_service,
                run_doctor_fn=run_doctor,
                summarize_doctor_report_fn=summarize_doctor_report,
                get_doctor_exit_code_fn=get_doctor_exit_code,
            )

        # 先确保数据库表已经准备好。
        # 这样后面不管是查看历史、重试失败，还是正式抓取，都有地方读写记录。
        record_repository.initialize()

        if action == "history":
            show_history(
                record_repository,
                status=None if not runtime_args or runtime_args.status == "all" else runtime_args.status,
                error_type=normalize_optional_text(runtime_args.error_type) if runtime_args else None,
                limit=runtime_args.limit if runtime_args else 10,
                prompt_for_filters=interactive_mode,
            )
            return

        if action == "export_failed":
            export_failed_records(
                record_repository,
                error_type=normalize_optional_text(runtime_args.error_type) if runtime_args else None,
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
                error_type=normalize_optional_text(runtime_args.error_type) if runtime_args else None,
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
        if not ensure_pixiv_login(client=client, login_service=login_service, logger=logger):
            return

        crawler = ArtworkCrawler(client)
        downloader = PixivImageDownloader(client)
        author_crawler = AuthorCrawler(client)

        if action == "crawl_author":
            prepared_artwork_ids = handle_crawl_author_action(
                author_request=author_request,
                author_crawler=author_crawler,
                record_repository=record_repository,
                console_service=console_service,
                logger=logger,
                select_incremental_artwork_ids_fn=select_incremental_artwork_ids,
            )
            if prepared_artwork_ids is None:
                return
            artwork_ids = prepared_artwork_ids

        if action == "crawl_following":
            # 这里的目标不是抓“一个作者”，
            # 而是先把“我当前关注的所有作者”收集出来，
            # 再逐个复用现有的作者增量更新流程。
            handle_crawl_following_action(
                runtime_args=runtime_args,
                interactive_mode=interactive_mode,
                author_crawler=author_crawler,
                crawler=crawler,
                downloader=downloader,
                record_repository=record_repository,
                console_service=console_service,
                logger=logger,
                select_incremental_artwork_ids_fn=select_incremental_artwork_ids,
                process_artwork_batch_fn=process_artwork_batch,
            )
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
    sys.exit(main(sys.argv[1:]))
