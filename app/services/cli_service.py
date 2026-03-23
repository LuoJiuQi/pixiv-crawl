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

from app.db.download_record_repository import DownloadRecordRepository
from app.services.failure_exporter import build_failure_export_path, export_failure_records
from app.services.record_exporter import build_record_export_path, export_records


def choose_action() -> str:
    """
    让用户选择本次要执行的操作。

    返回的不是数字，而是更容易读懂的动作名。
    这样主流程后面判断时，代码会比判断 `1/2/3/4/5` 更清晰。
    """
    print("请选择操作：")
    print("1. 批量抓取作品")
    print("2. 查看历史记录")
    print("3. 重试失败任务")
    print("4. 导出失败清单")
    print("5. 归档并清理旧记录")

    choice = input("请输入 1、2、3、4 或 5，直接回车默认 1：").strip()
    if choice == "2":
        return "history"
    if choice == "3":
        return "retry_failed"
    if choice == "4":
        return "export_failed"
    if choice == "5":
        return "archive_records"
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


def collect_artwork_ids() -> list[str]:
    """
    从命令行读取一批作品 ID。

    使用方式尽量做得“宽松”一点，
    因为实际使用时，你很可能是从网页、记事本、聊天窗口里直接复制过来。
    """
    print("请输入 Pixiv 作品 ID，支持批量输入。")
    print("可直接粘贴多个 ID 或作品链接，支持空格、逗号和多行。")
    print("输入完成后，直接输入一个空行开始执行。")

    lines: list[str] = []
    while True:
        line = input().strip()

        if not line:
            if lines:
                break

            print("还没有输入任何作品 ID，请至少输入一个。")
            continue

        lines.append(line)

    artwork_ids = parse_artwork_ids("\n".join(lines))
    if not artwork_ids:
        raise RuntimeError("没有识别到有效的作品 ID，请检查输入格式。")

    return artwork_ids


def collect_history_options() -> tuple[str | None, str | None, int]:
    """
    读取“查看历史记录”时的筛选条件。

    返回值依次是：
    - 状态过滤条件
    - 失败类型过滤条件
    - 最多看多少条
    """
    raw_status = input("按状态筛选（all/completed/failed，直接回车默认 all）：").strip().lower()
    if raw_status in {"completed", "failed"}:
        status = raw_status
    else:
        status = None

    error_type = None
    if status in {None, "failed"}:
        raw_error_type = input(
            "按失败类型筛选（all/login/timeout/download/...，直接回车默认 all）："
        ).strip().lower()
        if raw_error_type and raw_error_type != "all":
            error_type = raw_error_type

    raw_limit = input("查看最近多少条记录（直接回车默认 10）：").strip()
    limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else 10
    return status, error_type, limit


def show_history(record_repository: DownloadRecordRepository) -> None:
    """
    把数据库里的历史记录打印出来。

    这个函数不负责“怎么查数据库”，
    它只负责把仓库层查到的数据，用人更容易读懂的方式展示出来。
    """
    summary = record_repository.get_status_summary()
    print("当前数据库记录概览：")
    print("completed =", summary.get("completed", 0))
    print("failed =", summary.get("failed", 0))
    print("pending =", summary.get("pending", 0))

    error_type_summary = record_repository.get_error_type_summary(status="failed")
    if error_type_summary:
        print("失败类型分布：", error_type_summary)

    status, error_type, limit = collect_history_options()
    records = record_repository.list_records(limit=limit, status=status, error_type=error_type)

    print()
    print("========== 历史记录 ==========")
    if not records:
        print("当前没有符合条件的记录。")
        return

    for index, record in enumerate(records, start=1):
        print(f"{index}. artwork_id = {record['artwork_id']}")
        print(f"   status = {record['status']}")
        print(f"   error_type = {record['error_type']}")
        print(f"   title = {record['title']}")
        print(f"   author_name = {record['author_name']}")
        print(f"   page_count = {record['page_count']}")
        print(f"   download_count = {record['download_count']}")
        print(f"   updated_at = {record['updated_at']}")
        if record["error_message"]:
            print(f"   error_message = {record['error_message']}")


def collect_retry_artwork_ids(record_repository: DownloadRecordRepository) -> list[str]:
    """
    从数据库里挑出这次要重试的失败作品 ID。

    这里把“问用户”和“拼出 ID 列表”封装到一起，
    主函数就不用知道这些交互细节。
    """
    summary = record_repository.get_status_summary()
    failed_count = summary.get("failed", 0)

    if failed_count <= 0:
        print("数据库里当前没有失败记录，不需要重试。")
        return []

    print(f"当前共有 {failed_count} 条失败记录。")
    error_type_summary = record_repository.get_error_type_summary(status="failed")
    if error_type_summary:
        print("当前失败类型分布：", error_type_summary)

    raw_error_type = input(
        "这次只重试某一种失败类型吗？输入类型名，直接回车默认全部："
    ).strip().lower()
    error_type = raw_error_type or None

    raw_limit = input("本次要重试最近多少条失败记录？直接回车默认全部：").strip()
    if raw_limit.isdigit() and int(raw_limit) > 0:
        limit = int(raw_limit)
    else:
        limit = failed_count

    records = record_repository.list_records(limit=limit, status="failed", error_type=error_type)
    artwork_ids = [str(record["artwork_id"]) for record in records]

    print(f"本次将重试 {len(artwork_ids)} 个作品：{artwork_ids}")
    return artwork_ids


def export_failed_records(record_repository: DownloadRecordRepository) -> None:
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
        print("数据库里当前没有失败记录，无需导出。")
        return

    error_type_summary = record_repository.get_error_type_summary(status="failed")
    if error_type_summary:
        print("当前失败类型分布：", error_type_summary)

    raw_error_type = input(
        "只导出某一种失败类型吗？输入类型名，直接回车默认全部："
    ).strip().lower()
    error_type = raw_error_type or None

    raw_limit = input("本次最多导出多少条失败记录？直接回车默认全部：").strip()
    if raw_limit.isdigit() and int(raw_limit) > 0:
        limit = int(raw_limit)
    else:
        limit = failed_count

    raw_format = input("导出格式（json/txt，直接回车默认 json）：").strip().lower()
    file_format = raw_format if raw_format in {"json", "txt"} else "json"

    records = record_repository.list_records(limit=limit, status="failed", error_type=error_type)
    if not records:
        print("当前没有符合条件的失败记录可导出。")
        return

    output_path = build_failure_export_path(
        Path("./data/exports"),
        error_type=error_type,
        file_format=file_format,
    )
    exported_path = export_failure_records(records, output_path, file_format=file_format)

    print(f"已导出 {len(records)} 条失败记录。")
    print("导出文件：", str(exported_path))


def archive_old_records(record_repository: DownloadRecordRepository) -> None:
    """
    先导出，再删除较旧的历史记录。

    这是比较保守的做法：
    - 先把数据另存一份
    - 再真的从数据库里删掉
    这样就算后面后悔了，也至少还有归档文件可查。
    """
    summary = record_repository.get_status_summary()
    print("当前数据库记录概览：", summary)

    raw_status = input("要归档哪种状态（completed/failed/all，直接回车默认 completed）：").strip().lower()
    if raw_status in {"completed", "failed"}:
        status = raw_status
    else:
        status = None if raw_status == "all" else "completed"

    raw_days = input("归档多少天以前的记录（直接回车默认 30）：").strip()
    days = int(raw_days) if raw_days.isdigit() and int(raw_days) > 0 else 30

    raw_limit = input("本次最多归档多少条（直接回车默认 100）：").strip()
    limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else 100

    raw_format = input("归档文件格式（json/txt，直接回车默认 json）：").strip().lower()
    file_format = raw_format if raw_format in {"json", "txt"} else "json"

    cutoff_time = datetime.now() - timedelta(days=days)
    cutoff_text = cutoff_time.isoformat(timespec="seconds")

    records = record_repository.list_records(
        limit=limit,
        status=status,
        updated_before=cutoff_text,
    )
    if not records:
        print("当前没有符合条件的旧记录可归档。")
        return

    print(f"本次将归档 {len(records)} 条记录。")
    print("示例作品：", [record["artwork_id"] for record in records[:10]])

    confirm = input("确认执行归档并删除这些记录吗？输入 yes 确认：").strip().lower()
    if confirm != "yes":
        print("已取消归档。")
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

    print(f"已归档 {len(records)} 条记录。")
    print(f"实际删除 {deleted_count} 条数据库记录。")
    print("归档文件：", str(exported_path))
