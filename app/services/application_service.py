"""
主入口调度辅助服务。

这个模块只负责把 [`main.py`](../../main.py) 中原本较长的分支逻辑拆成可复用的小函数。
为了降低重构风险，这些函数都通过参数接收外部依赖；这样入口文件里的测试仍然可以通过
patch [`main.py`](../../main.py) 中的依赖来验证现有行为。
"""

from __future__ import annotations

from argparse import Namespace
from logging import Logger
from typing import TYPE_CHECKING, Any, Callable, Protocol

from app.schemas.task import BatchRunSummary, IncrementalSelectionResult

if TYPE_CHECKING:
    from app.browser.client import BrowserClient
    from app.db.download_record_repository import DownloadRecordRepository
    from app.services.cli_service import AuthorCollectOptions
else:
    BrowserClient = Any
    DownloadRecordRepository = Any
    AuthorCollectOptions = dict[str, Any]


class ConsoleServiceProtocol(Protocol):
    def write_json_file(self, payload: object, file_path: str) -> None: ...
    def show_json(self, payload: object) -> None: ...
    def show_doctor_report(self, report: Any) -> None: ...
    def show_summary(self, title: str, rows: list[tuple[str, object]]) -> None: ...
    def show_success(self, message: str) -> None: ...
    def show_incremental_selection_summary(self, selection: IncrementalSelectionResult) -> None: ...
    def show_batch_summary(self, summary: BatchRunSummary) -> None: ...
    def show_following_update_summary(
        self,
        *,
        followed_user_ids: list[str],
        updated_authors: list[str],
        skipped_authors: list[str],
        failed_authors: list[tuple[str, str]],
        total_success_results: list[Any],
        total_failed_results: list[Any],
    ) -> None: ...
    def pause_before_exit(self) -> None: ...


class LoginServiceProtocol(Protocol):
    def is_logged_in(self) -> bool: ...
    def login_and_save_state(self) -> dict[str, Any]: ...


class AuthorCrawlerProtocol(Protocol):
    def collect_author_artwork_ids(self, user_id: str, limit: int | None = None) -> list[str]: ...
    def collect_following_user_ids(self, limit: int | None = None) -> list[str]: ...


class ArtworkCrawlerProtocol(Protocol):
    pass


class DownloaderProtocol(Protocol):
    pass


def handle_doctor_action(
    *,
    runtime_args: Namespace | None,
    interactive_mode: bool,
    console_service: ConsoleServiceProtocol,
    run_doctor_fn: Callable[[], Any],
    summarize_doctor_report_fn: Callable[[Any], dict[str, int]],
    get_doctor_exit_code_fn: Callable[..., int],
) -> int:
    """执行 doctor 分支并返回退出码。"""
    report = run_doctor_fn()
    summary = summarize_doctor_report_fn(report)
    strict = bool(runtime_args.strict) if runtime_args else False
    exit_code = get_doctor_exit_code_fn(report, strict=strict)
    payload = {
        "checks": report["checks"],
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


def ensure_pixiv_login(
    *,
    client: BrowserClient,
    login_service: LoginServiceProtocol,
    logger: Logger,
) -> bool:
    """确保当前浏览器上下文已经登录 Pixiv。"""
    if client.state_manager.state_exists():
        if login_service.is_logged_in():
            logger.info("检测到已有可用登录状态，无需重新登录。")
            return True

        logger.warning("已有登录状态失效，准备重新登录。")
        client.state_manager.delete_state()
        login_result = login_service.login_and_save_state()
        if not login_result["success"]:
            logger.error("登录未完成，程序结束。")
            return False
        return True

    logger.info("未检测到登录状态，准备首次登录。")
    login_result = login_service.login_and_save_state()
    if not login_result["success"]:
        logger.error("登录未完成，程序结束。")
        return False
    return True


def handle_crawl_author_action(
    *,
    author_request: AuthorCollectOptions | None,
    author_crawler: AuthorCrawlerProtocol,
    record_repository: DownloadRecordRepository,
    console_service: ConsoleServiceProtocol,
    logger: Logger,
    select_incremental_artwork_ids_fn: Callable[..., IncrementalSelectionResult],
) -> list[str] | None:
    """执行 crawl-author 前置收集逻辑，返回本次需要处理的作品 ID。"""
    if author_request is None:
        raise RuntimeError("作者抓取模式缺少作者输入，请重新选择操作。")

    user_id = author_request["user_id"]
    limit = author_request["limit"]
    author_artwork_ids = author_crawler.collect_author_artwork_ids(user_id, limit=limit)
    if not author_artwork_ids:
        logger.warning("未从作者 %s 的主页里识别到作品 ID。", user_id)
        return None

    logger.info("已从作者 %s 主页识别到 %s 个作品。", user_id, len(author_artwork_ids))

    if author_request["update_mode"] == "incremental":
        selection = select_incremental_artwork_ids_fn(
            author_artwork_ids,
            record_repository,
            completed_streak_limit=author_request["completed_streak_limit"],
        )
        artwork_ids = selection["candidate_artwork_ids"]
        console_service.show_incremental_selection_summary(selection)

        if not artwork_ids:
            logger.info("这位作者当前没有需要增量处理的新作品。")
            return None
        return artwork_ids

    logger.info("当前使用全量模式，会按识别到的作品列表逐个处理。")
    return author_artwork_ids


def handle_crawl_following_action(
    *,
    runtime_args: Namespace | None,
    interactive_mode: bool,
    author_crawler: AuthorCrawlerProtocol,
    crawler: ArtworkCrawlerProtocol,
    downloader: DownloaderProtocol,
    record_repository: DownloadRecordRepository,
    console_service: ConsoleServiceProtocol,
    logger: Logger,
    select_incremental_artwork_ids_fn: Callable[..., IncrementalSelectionResult],
    process_artwork_batch_fn: Callable[..., BatchRunSummary],
) -> None:
    """执行 crawl-following 完整流程。"""
    followed_user_ids = author_crawler.collect_following_user_ids(
        limit=runtime_args.following_limit if runtime_args else None
    )
    if not followed_user_ids:
        logger.info("当前没有识别到任何已关注画师。")
        return

    logger.info("本次共识别到 %s 个关注画师。", len(followed_user_ids))
    logger.debug("关注画师 ID 列表：%s", followed_user_ids)

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

            selection = select_incremental_artwork_ids_fn(
                author_artwork_ids,
                record_repository,
                completed_streak_limit=(runtime_args.completed_streak_limit if runtime_args else 10),
            )
            console_service.show_incremental_selection_summary(selection)

            artwork_ids = selection["candidate_artwork_ids"]
            if not artwork_ids:
                logger.debug("作者 %s 当前没有需要增量处理的新作品。", user_id)
                skipped_authors.append(user_id)
                continue

            summary = process_artwork_batch_fn(
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
