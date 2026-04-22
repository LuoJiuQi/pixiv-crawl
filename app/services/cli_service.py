"""
这个文件专门放“命令行交互”相关的代码。

你可以把它理解成项目的“前台接待”：
- 负责问用户这次想做什么
- 负责读取你在终端里输入的内容
- 负责把数据库里的历史记录打印出来
- 负责导出失败清单、归档旧记录

这样拆开以后，`main.py` 就不用一边管浏览器，
一边还要管各种输入输出细节。
"""

from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Literal, TypedDict

from app.db.download_record_repository import DownloadRecordRepository
from app.services import console_service
from app.services.failure_exporter import build_failure_export_path, export_failure_records
from app.services.record_exporter import build_record_export_path, export_records


class AuthorCollectOptions(TypedDict):
    """
    描述“按作者抓取”模式收集到的输入参数。
    """

    user_id: str
    limit: int | None
    update_mode: Literal["incremental", "full"]
    completed_streak_limit: int


def choose_action() -> str:
    """
    让用户选择本次要执行的操作。

    返回的不是数字，而是更容易读懂的动作名。
    这样主流程后面判断时，代码会比判断 `1/2/3/4/5` 更清晰。
    """
    console_service.show_menu(
        [
            "批量抓取作品",
            "查看历史记录",
            "重试失败任务",
            "导出失败清单",
            "归档并清理旧记录",
            "按作者批量抓取作品",
            "按关注列表更新画师",
        ]
    )

    choice = console_service.prompt("请输入 1、2、3、4、5、6 或 7，直接回车默认 1：").strip()
    if choice == "2":
        return "history"
    if choice == "3":
        return "retry_failed"
    if choice == "4":
        return "export_failed"
    if choice == "5":
        return "archive_records"
    if choice == "6":
        return "crawl_author"
    if choice == "7":
        return "crawl_following"
    return "crawl"


def parse_artwork_ids(raw_text: str) -> list[str]:
    """
    把一段自由文本解析成作品 ID 列表。

    这里故意支持多种输入方式，是为了让你平时复制内容更省事：
    - 直接输入数字 ID
    - 粘贴多个 ID
    - 粘贴作品链接
    - 多行混着来
    """
    candidates = re.findall(r"(?:https?://www\.pixiv\.net/(?:[a-z]{2}/)?artworks/)?(\d+)", raw_text)

    artwork_ids: list[str] = []
    for artwork_id in candidates:
        # 去重，但尽量保留原本的输入顺序。
        if artwork_id not in artwork_ids:
            artwork_ids.append(artwork_id)

    return artwork_ids


def parse_user_id(raw_text: str) -> str:
    """
    从一段文本里解析出作者用户 ID。

    支持这些输入形式：
    - 纯数字：`123456`
    - 作者主页：`https://www.pixiv.net/users/123456`
    - 旧式链接：`https://www.pixiv.net/member.php?id=123456`
    """
    patterns = [
        r"https?://www\.pixiv\.net/(?:[a-z]{2}/)?users/(\d+)",
        r"https?://www\.pixiv\.net/member\.php\?id=(\d+)",
        r"\b(\d+)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            return match.group(1)

    return ""


def collect_artwork_ids() -> list[str]:
    """
    从命令行读取一批作品 ID。

    使用方式尽量做得“宽松”一点，
    因为实际使用时，你很可能是从网页、记事本、聊天窗口里直接复制过来。
    """
    console_service.show_section("请输入 Pixiv 作品 ID")
    console_service.show_list(
        "支持的输入方式",
        [
            "可直接粘贴多个 ID 或作品链接",
            "支持空格、逗号和多行",
            "输入完成后，直接输入一个空行开始执行",
        ],
    )

    lines: list[str] = []
    while True:
        line = input().strip()

        if not line:
            if lines:
                break

            console_service.show_warning("还没有输入任何作品 ID，请至少输入一个。")
            continue

        lines.append(line)

    artwork_ids = parse_artwork_ids("\n".join(lines))
    if not artwork_ids:
        raise RuntimeError("没有识别到有效的作品 ID，请检查输入格式。")

    return artwork_ids


def collect_author_options() -> AuthorCollectOptions:
    """
    读取“按作者批量抓取”模式需要的输入。

    当前这里会额外询问“更新方式”，因为作者模式最适合长期使用，
    所以默认会走“增量更新”：
    - 新作品处理
    - 失败作品重试
    - 已完成老作品连续出现很多个后，提前停止
    """
    console_service.show_warning("请输入 Pixiv 作者 ID 或作者主页链接。")
    raw_author = console_service.prompt("作者：").strip()

    user_id = parse_user_id(raw_author)
    if not user_id:
        raise RuntimeError("没有识别到有效的作者 ID，请检查输入格式。")

    raw_limit = console_service.prompt("最多抓取多少个作品（直接回车默认全部）：").strip()
    if raw_limit.isdigit() and int(raw_limit) > 0:
        limit = int(raw_limit)
    else:
        limit = None

    raw_mode = console_service.prompt(
        "更新方式（incremental/full，直接回车默认 incremental）："
    ).strip().lower()
    update_mode: Literal["incremental", "full"]
    if raw_mode == "full":
        update_mode = "full"
    else:
        update_mode = "incremental"

    completed_streak_limit = 10
    if update_mode == "incremental":
        raw_streak_limit = console_service.prompt(
            "连续遇到多少个已完成作品后停止扫描（直接回车默认 10）："
        ).strip()
        if raw_streak_limit.isdigit() and int(raw_streak_limit) > 0:
            completed_streak_limit = int(raw_streak_limit)

    return {
        "user_id": user_id,
        "limit": limit,
        "update_mode": update_mode,
        "completed_streak_limit": completed_streak_limit,
    }


def collect_history_options() -> tuple[str | None, str | None, int]:
    """
    读取“查看历史记录”时的筛选条件。

    返回值依次是：
    - 状态过滤条件
    - 失败类型过滤条件
    - 最多看多少条
    """
    raw_status = console_service.prompt(
        "按状态筛选（all/completed/failed，直接回车默认 all）："
    ).strip().lower()
    if raw_status in {"completed", "failed"}:
        status = raw_status
    else:
        status = None

    error_type = None
    if status in {None, "failed"}:
        raw_error_type = console_service.prompt(
            "按失败类型筛选（all/login/rate_limit/http_5xx/timeout/network/download/...，直接回车默认 all）："
        ).strip().lower()
        if raw_error_type and raw_error_type != "all":
            error_type = raw_error_type

    raw_limit = console_service.prompt("查看最近多少条记录（直接回车默认 10）：").strip()
    limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else 10
    return status, error_type, limit


def show_history(
    record_repository: DownloadRecordRepository,
    *,
    status: str | None = None,
    error_type: str | None = None,
    limit: int = 10,
    prompt_for_filters: bool = True,
) -> None:
    """
    把数据库里的历史记录打印出来。

    这个函数既支持原来的交互模式，也支持外部直接传过滤条件的非交互模式。
    """
    summary = record_repository.get_status_summary()
    console_service.show_summary(
        "当前数据库记录概览",
        [
            ("completed", summary.get("completed", 0)),
            ("failed", summary.get("failed", 0)),
            ("pending", summary.get("pending", 0)),
        ],
    )

    error_type_summary = record_repository.get_error_type_summary(status="failed")
    if error_type_summary:
        console_service.show_summary("失败类型分布", list(error_type_summary.items()))

    if prompt_for_filters:
        status, error_type, limit = collect_history_options()

    records = record_repository.list_records(limit=limit, status=status, error_type=error_type)
    console_service.show_records("历史记录", records)


def collect_retry_artwork_ids(
    record_repository: DownloadRecordRepository,
    *,
    error_type: str | None = None,
    limit: int | None = None,
    interactive: bool = True,
) -> list[str]:
    """
    从数据库里挑出这次要重试的失败作品 ID。

    这里把“问用户”和“拼出 ID 列表”封装到一起，
    主函数就不用知道这些交互细节。
    """
    summary = record_repository.get_status_summary()
    failed_count = summary.get("failed", 0)

    if failed_count <= 0:
        console_service.show_warning("数据库里当前没有失败记录，不需要重试。")
        return []

    console_service.show_summary("失败记录概览", [("failed", failed_count)])
    error_type_summary = record_repository.get_error_type_summary(status="failed")
    if error_type_summary:
        console_service.show_summary("当前失败类型分布", list(error_type_summary.items()))

    if interactive:
        raw_error_type = console_service.prompt(
            "这次只重试某一种失败类型吗？输入类型名，直接回车默认全部："
        ).strip().lower()
        error_type = raw_error_type or None

        raw_limit = console_service.prompt("本次要重试最近多少条失败记录？直接回车默认全部：").strip()
        if raw_limit.isdigit() and int(raw_limit) > 0:
            limit = int(raw_limit)
        else:
            limit = failed_count
    elif limit is None or limit <= 0:
        limit = failed_count

    records = record_repository.list_records(limit=limit, status="failed", error_type=error_type)
    artwork_ids = [str(record["artwork_id"]) for record in records]

    console_service.show_list("本次将重试的作品 ID", artwork_ids)
    return artwork_ids


def export_failed_records(
    record_repository: DownloadRecordRepository,
    *,
    error_type: str | None = None,
    limit: int | None = None,
    file_format: str = "json",
    interactive: bool = True,
) -> None:
    """
    把失败记录导出成单独文件。

    这样做的好处是：
    - 你可以把失败任务单独保存下来
    - 方便后面人工复盘
    - 也方便单独分享给别人看
    """
    summary = record_repository.get_status_summary()
    failed_count = summary.get("failed", 0)

    if failed_count <= 0:
        console_service.show_warning("数据库里当前没有失败记录，无需导出。")
        return

    error_type_summary = record_repository.get_error_type_summary(status="failed")
    if error_type_summary:
        console_service.show_summary("当前失败类型分布", list(error_type_summary.items()))

    if interactive:
        raw_error_type = console_service.prompt(
            "只导出某一种失败类型吗？输入类型名，直接回车默认全部："
        ).strip().lower()
        error_type = raw_error_type or None

        raw_limit = console_service.prompt("本次最多导出多少条失败记录？直接回车默认全部：").strip()
        if raw_limit.isdigit() and int(raw_limit) > 0:
            limit = int(raw_limit)
        else:
            limit = failed_count

        raw_format = console_service.prompt("导出格式（json/txt，直接回车默认 json）：").strip().lower()
        file_format = raw_format if raw_format in {"json", "txt"} else "json"
    elif limit is None or limit <= 0:
        limit = failed_count

    records = record_repository.list_records(limit=limit, status="failed", error_type=error_type)
    if not records:
        console_service.show_warning("当前没有符合条件的失败记录可导出。")
        return

    output_path = build_failure_export_path(
        Path("./data/exports"),
        error_type=error_type,
        file_format=file_format,
    )
    exported_path = export_failure_records(records, output_path, file_format=file_format)

    console_service.show_success(f"已导出 {len(records)} 条失败记录。")
    console_service.show_success(f"导出文件：{exported_path}")


def archive_old_records(
    record_repository: DownloadRecordRepository,
    *,
    status: str | None = "completed",
    days: int = 30,
    limit: int = 100,
    file_format: str = "json",
    interactive: bool = True,
    confirmed: bool = False,
) -> None:
    """
    先导出，再删除较旧的历史记录。

    既支持交互确认，也支持外部传入参数的非交互模式。
    """
    summary = record_repository.get_status_summary()
    console_service.show_summary("当前数据库记录概览", list(summary.items()))

    if interactive:
        raw_status = console_service.prompt(
            "要归档哪种状态（completed/failed/all，直接回车默认 completed）："
        ).strip().lower()
        if raw_status in {"completed", "failed"}:
            status = raw_status
        else:
            status = None if raw_status == "all" else "completed"

        raw_days = console_service.prompt("归档多少天以前的记录（直接回车默认 30）：").strip()
        days = int(raw_days) if raw_days.isdigit() and int(raw_days) > 0 else 30

        raw_limit = console_service.prompt("本次最多归档多少条（直接回车默认 100）：").strip()
        limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else 100

        raw_format = console_service.prompt("归档文件格式（json/txt，直接回车默认 json）：").strip().lower()
        file_format = raw_format if raw_format in {"json", "txt"} else "json"

    cutoff_time = datetime.now() - timedelta(days=days)
    cutoff_text = cutoff_time.isoformat(timespec="seconds")

    records = record_repository.list_records(
        limit=limit,
        status=status,
        updated_before=cutoff_text,
    )
    if not records:
        console_service.show_warning("当前没有符合条件的旧记录可归档。")
        return

    console_service.show_summary("归档预览", [("record_count", len(records))])
    console_service.show_list("示例作品", [record["artwork_id"] for record in records[:10]])

    if interactive:
        confirm = console_service.prompt("确认执行归档并删除这些记录吗？输入 yes 确认：").strip().lower()
        confirmed = confirm == "yes"

    if not confirmed:
        console_service.show_warning("已取消归档。")
        return

    output_path = build_record_export_path(
        Path("./data/exports"),
        prefix="archived_records",
        status=status or "all",
        file_format=file_format,
    )
    exported_path = export_records(records, output_path, file_format=file_format)

    deleted_count = record_repository.delete_records(
        [str(record["artwork_id"]) for record in records]
    )

    console_service.show_success(f"已归档 {len(records)} 条记录。")
    console_service.show_success(f"实际删除 {deleted_count} 条数据库记录。")
    console_service.show_success(f"归档文件：{exported_path}")
