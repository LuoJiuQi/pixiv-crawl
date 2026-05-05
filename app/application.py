"""
这个文件是整个项目的"应用层调度器"。

它把原来散落在 main.py 中的资源管理、动作分发、生命周期控制
集中到一个类里，让 main.py 只保留入口调用。

主要职责：
- 统一管理 BrowserClient / RecordRepository 的生命周期
- 按动作名称分发到具体的处理方法
- 处理浏览器启动、登录态检查、资源关闭等横切关注点
"""

from __future__ import annotations

import sys
from argparse import Namespace
from logging import Logger
from typing import Any

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
    show_history,
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


class PixivApplication:
    """
    应用层调度器：管理整个爬虫应用的生命周期和动作分发。

    使用方式：
        with PixivApplication() as app:
            app.run(sys.argv[1:])

    `__enter__` 会完成控制台编码、日志初始化等准备工作。
    `__exit__` 会确保浏览器资源被正确释放。
    """

    def __init__(self) -> None:
        self.client: BrowserClient | None = None
        self.login_service: PixivLoginService | None = None
        self.crawler: ArtworkCrawler | None = None
        self.downloader: PixivImageDownloader | None = None
        self.author_crawler: AuthorCrawler | None = None
        self.record_repository = DownloadRecordRepository()
        self._started = False

    def __enter__(self) -> "PixivApplication":
        console_service.configure_console_encoding()
        configure_logging()
        return self

    def __exit__(self, *args: Any) -> None:
        self._close()

    # ----------------------------------------------------------------
    #  公开入口
    # ----------------------------------------------------------------

    def run(self, argv: list[str] | None = None) -> int | None:
        """
        解析参数并执行对应的动作。

        返回值含义：
        - None / 0：正常结束
        - 非 0：执行过程中遇到了需要以错误码退出的情况
        """
        runtime_args = parse_runtime_arguments(argv)
        interactive_mode = runtime_args is None

        if interactive_mode and settings.scheduled_run_enabled:
            return run_scheduled_crawl_loop()

        action = runtime_args.action if runtime_args else choose_action()

        # --- 不需要浏览器 / 数据库的动作 ---
        if action == "doctor":
            return self._handle_doctor(runtime_args, interactive_mode)

        # --- 只需要数据库的动作 ---
        self.record_repository.initialize()

        if action == "history":
            return self._handle_history(runtime_args, interactive_mode)

        if action == "export_failed":
            return self._handle_export_failed(runtime_args, interactive_mode)

        if action == "archive_records":
            return self._handle_archive_records(runtime_args, interactive_mode)

        # --- 需要浏览器的动作 ---
        return self._handle_browser_actions(action, runtime_args, interactive_mode)

    # ----------------------------------------------------------------
    #  动作分发
    # ----------------------------------------------------------------

    def _handle_doctor(
        self,
        runtime_args: Namespace | None,
        interactive_mode: bool,
    ) -> int:
        """执行运行环境自检。"""
        report = run_doctor()
        summary = summarize_doctor_report(report)
        strict = bool(runtime_args.strict) if runtime_args else False
        exit_code = get_doctor_exit_code(report, strict=strict)
        payload = {
            "checks": report.checks,
            "summary": summary,
            "strict": strict,
            "exit_code": exit_code,
        }

        output_path = str(runtime_args.output).strip() if runtime_args else ""
        if output_path:
            console_service.write_json_file(payload, output_path)

        if runtime_args and runtime_args.json_output:
            console_service.show_json(payload)
        else:
            console_service.show_doctor_report(report)
            console_service.show_summary("自检结果汇总", list(summary.items()))
            if output_path:
                console_service.show_success(f"自检结果已写入：{output_path}")

        if interactive_mode:
            console_service.pause_before_exit()
        return exit_code

    def _handle_history(
        self,
        runtime_args: Namespace | None,
        interactive_mode: bool,
    ) -> None:
        """查看历史记录。"""
        show_history(
            self.record_repository,
            status=(
                None
                if not runtime_args or runtime_args.status == "all"
                else runtime_args.status
            ),
            error_type=normalize_optional_text(runtime_args.error_type) if runtime_args else None,
            limit=runtime_args.limit if runtime_args else 10,
            prompt_for_filters=interactive_mode,
        )

    def _handle_export_failed(
        self,
        runtime_args: Namespace | None,
        interactive_mode: bool,
    ) -> None:
        """导出失败清单。"""
        export_failed_records(
            self.record_repository,
            error_type=normalize_optional_text(runtime_args.error_type) if runtime_args else None,
            limit=runtime_args.limit if runtime_args else None,
            file_format=runtime_args.format if runtime_args else "json",
            interactive=interactive_mode,
        )

    def _handle_archive_records(
        self,
        runtime_args: Namespace | None,
        interactive_mode: bool,
    ) -> None:
        """归档并清理旧记录。"""
        archive_old_records(
            self.record_repository,
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

    # ----------------------------------------------------------------
    #  浏览器相关动作
    # ----------------------------------------------------------------

    def _handle_browser_actions(
        self,
        action: str,
        runtime_args: Namespace | None,
        interactive_mode: bool,
    ) -> int | None:
        """
        启动浏览器 → 登录 → 执行需要网络的动作。
        """
        # 1. 收集作品 ID（在浏览器启动前，因为有些是交互式的）
        author_request: AuthorCollectOptions | None = None
        if action == "retry_failed":
            artwork_ids = collect_retry_artwork_ids(
                self.record_repository,
                error_type=normalize_optional_text(runtime_args.error_type) if runtime_args else None,
                limit=runtime_args.limit if runtime_args else None,
                interactive=interactive_mode,
            )
            if not artwork_ids:
                return
        elif action == "crawl_author":
            author_request = (
                runtime_args.author_request
                if runtime_args
                else collect_author_options()
            )
            artwork_ids = []
        elif action_requires_direct_artwork_input(action):
            artwork_ids = runtime_args.artwork_ids if runtime_args else collect_artwork_ids()
        else:
            artwork_ids = []

        # 2. 启动浏览器并确保登录
        self._start_browser()
        if not self._ensure_logged_in():
            return

        # 3. 执行具体动作
        if action == "crawl_author":
            return self._handle_crawl_author(author_request, interactive_mode)

        if action == "crawl_following":
            return self._handle_crawl_following(runtime_args, interactive_mode)

        # 默认：批量抓取作品
        return self._handle_batch_crawl(artwork_ids, interactive_mode)

    def _start_browser(self) -> None:
        """启动浏览器并准备好所有依赖的爬虫/下载器对象。"""
        self.client = BrowserClient()
        self.client.start()

        self.login_service = PixivLoginService(self.client)
        self.crawler = ArtworkCrawler(self.client)
        self.downloader = PixivImageDownloader(self.client)
        self.author_crawler = AuthorCrawler(self.client)
        self._started = True

    def _ensure_logged_in(self) -> bool:
        """
        检查并确保当前浏览器上下文已经登录 Pixiv。

        优先复用本地存储的登录态文件；
        失效时自动删除并重新登录。
        """
        if self.client is None or self.login_service is None:
            raise RuntimeError("浏览器尚未启动，无法检查登录态。")

        state_manager = self.client.state_manager

        if state_manager.state_exists():
            if self.login_service.is_logged_in():
                logger.info("检测到已有可用登录状态，无需重新登录。")
                return True

            logger.warning("已有登录状态失效，准备重新登录。")
            state_manager.delete_state()
            login_result = self.login_service.login_and_save_state()
            if not login_result["success"]:
                logger.error("登录未完成，程序结束。")
                return False
            return True

        logger.info("未检测到登录状态，准备首次登录。")
        login_result = self.login_service.login_and_save_state()
        if not login_result["success"]:
            logger.error("登录未完成，程序结束。")
            return False
        return True

    def _handle_crawl_author(
        self,
        author_request: AuthorCollectOptions | None,
        interactive_mode: bool,
    ) -> int | None:
        """按作者抓取作品。"""
        if author_request is None:
            raise RuntimeError("作者抓取模式缺少作者输入，请重新选择操作。")

        assert self.author_crawler is not None
        user_id = author_request.user_id
        limit = author_request.limit
        author_artwork_ids = self.author_crawler.collect_author_artwork_ids(user_id, limit=limit)
        if not author_artwork_ids:
            logger.warning("未从作者 %s 的主页里识别到作品 ID。", user_id)
            return

        logger.info("已从作者 %s 主页识别到 %s 个作品。", user_id, len(author_artwork_ids))

        if author_request.update_mode == "incremental":
            selection = select_incremental_artwork_ids(
                author_artwork_ids,
                self.record_repository,
                completed_streak_limit=author_request.completed_streak_limit,
            )
            artwork_ids = selection.candidate_artwork_ids
            console_service.show_incremental_selection_summary(selection)

            if not artwork_ids:
                logger.info("这位作者当前没有需要增量处理的新作品。")
                return
        else:
            logger.info("当前使用全量模式，会按识别到的作品列表逐个处理。")
            artwork_ids = author_artwork_ids

        return self._handle_batch_crawl(artwork_ids, interactive_mode)

    def _handle_crawl_following(
        self,
        runtime_args: Namespace | None,
        interactive_mode: bool,
    ) -> None:
        """按关注列表更新画师作品。"""
        assert self.author_crawler is not None
        followed_user_ids = self.author_crawler.collect_following_user_ids(
            limit=runtime_args.following_limit if runtime_args else None,
        )
        if not followed_user_ids:
            logger.info("当前没有识别到任何已关注画师。")
            return

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
                author_artwork_ids = self.author_crawler.collect_author_artwork_ids(user_id)
                if not author_artwork_ids:
                    logger.debug("作者 %s 当前没有识别到可处理作品，先跳过。", user_id)
                    skipped_authors.append(user_id)
                    continue

                selection = select_incremental_artwork_ids(
                    author_artwork_ids,
                    self.record_repository,
                    completed_streak_limit=(
                        runtime_args.completed_streak_limit if runtime_args else 10
                    ),
                )
                console_service.show_incremental_selection_summary(selection)

                artwork_ids = selection.candidate_artwork_ids
                if not artwork_ids:
                    logger.debug("作者 %s 当前没有需要增量处理的新作品。", user_id)
                    skipped_authors.append(user_id)
                    continue

                assert self.crawler is not None
                assert self.downloader is not None
                summary = process_artwork_batch(
                    artwork_ids=artwork_ids,
                    crawler=self.crawler,
                    downloader=self.downloader,
                    record_repository=self.record_repository,
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

        if interactive_mode:
            console_service.pause_before_exit()

    def _handle_batch_crawl(
        self,
        artwork_ids: list[str],
        interactive_mode: bool,
    ) -> None:
        """批量抓取一批作品 ID。"""
        assert self.crawler is not None
        assert self.downloader is not None
        logger.info("本次共识别到 %s 个作品 ID。", len(artwork_ids))
        logger.debug("本次作品 ID 列表：%s", artwork_ids)

        summary = process_artwork_batch(
            artwork_ids=artwork_ids,
            crawler=self.crawler,
            downloader=self.downloader,
            record_repository=self.record_repository,
        )
        console_service.show_batch_summary(summary)

        if interactive_mode:
            console_service.pause_before_exit()

    # ----------------------------------------------------------------
    #  资源管理
    # ----------------------------------------------------------------

    def _close(self) -> None:
        """释放所有资源：浏览器、Playwright 等。"""
        if self.client is not None:
            self.client.close()
            self.client = None
        self._started = False
