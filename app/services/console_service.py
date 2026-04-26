"""
统一管理终端里“面向用户”的展示输出。

这里不负责业务判断，只负责：
- 菜单和标题
- 摘要和列表
- 交互提示
"""

import json
from typing import TYPE_CHECKING
from collections.abc import Iterable, Mapping, Sequence

from app.services.task_service import BatchRunSummary, IncrementalSelectionResult

if TYPE_CHECKING:
    from app.services.doctor_service import DoctorReport


def show_menu(options: list[str]) -> None:
    print("请选择操作：")
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")


def show_section(title: str) -> None:
    print()
    print(f"========== {title} ==========")


def show_summary(title: str, rows: list[tuple[str, object]]) -> None:
    print(f"{title}：")
    for key, value in rows:
        print(f"{key} = {value}")


def show_list(title: str, items: Iterable[object]) -> None:
    rendered_items = list(items)
    print(f"{title}：")
    if not rendered_items:
        print("(空)")
        return

    for index, item in enumerate(rendered_items, start=1):
        print(f"{index}. {item}")


def show_records(title: str, records: Sequence[Mapping[str, object]]) -> None:
    show_section(title)
    if not records:
        print("当前没有符合条件的记录。")
        return

    for index, record in enumerate(records, start=1):
        print(f"{index}. artwork_id = {record.get('artwork_id', '')}")
        for key, value in record.items():
            if key == "artwork_id" or value in {"", None}:
                continue
            print(f"   {key} = {value}")


def show_incremental_selection_summary(selection: IncrementalSelectionResult) -> None:
    show_summary(
        "增量筛选结果",
        [
            ("作者作品总数", selection["total_available_artwork_count"]),
            ("本次实际扫描数量", selection["scanned_artwork_count"]),
            ("新作品数量", len(selection["new_artwork_ids"])),
            ("失败待重试数量", len(selection["retry_artwork_ids"])),
            ("已完成并跳过数量", len(selection["skipped_completed_ids"])),
            ("本次最终待处理数量", len(selection["candidate_artwork_ids"])),
        ],
    )

    if selection["new_artwork_ids"]:
        show_list("新作品 ID", selection["new_artwork_ids"])

    if selection["retry_artwork_ids"]:
        show_list("失败待重试作品 ID", selection["retry_artwork_ids"])

    if selection["stopped_early"]:
        show_warning(
            "已触发提前停止："
            f"连续遇到 {selection['stop_after_completed_streak']} 个已完成老作品后，停止继续往后扫描。"
        )


def show_batch_summary(summary: BatchRunSummary) -> None:
    success_results = summary["success_results"]
    failed_results = summary["failed_results"]

    show_summary(
        "本次批量任务汇总",
        [
            ("成功数量", len(success_results)),
            ("失败数量", len(failed_results)),
        ],
    )

    if success_results:
        show_list("成功作品", [result["artwork_id"] for result in success_results])
        show_list(
            "其中跳过重复下载的作品",
            [result["artwork_id"] for result in success_results if result["skipped_download"]],
        )
        show_list(
            "其中按数据库直接跳过整套任务的作品",
            [result["artwork_id"] for result in success_results if result["skipped_by_db"]],
        )

    if failed_results:
        show_list("失败详情", [f"{item['artwork_id']}: {item['error']}" for item in failed_results])


def show_following_update_summary(
    followed_user_ids: list[str],
    updated_authors: list[str],
    skipped_authors: list[str],
    failed_authors: list[tuple[str, str]],
    total_success_results: Sequence[Mapping[str, object]],
    total_failed_results: Sequence[Mapping[str, object]],
) -> None:
    show_summary(
        "关注画师更新汇总",
        [
            ("关注画师总数", len(followed_user_ids)),
            ("实际更新的作者数量", len(updated_authors)),
            ("无新作品而跳过的作者数量", len(skipped_authors)),
            ("作者级失败数量", len(failed_authors)),
            ("成功处理的作品数量", len(total_success_results)),
            ("失败的作品数量", len(total_failed_results)),
        ],
    )

    if updated_authors:
        show_list("本次实际更新的作者", updated_authors)
    if skipped_authors:
        show_list("本次跳过的作者", skipped_authors)
    if failed_authors:
        show_list("作者级失败详情", [f"{user_id}: {error}" for user_id, error in failed_authors])


def show_doctor_report(report: "DoctorReport") -> None:
    show_section("运行环境自检")
    for check in report["checks"]:
        print(f"[{check['status'].upper()}] {check['name']}：{check['detail']}")


def show_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def show_warning(message: str) -> None:
    print(message)


def show_success(message: str) -> None:
    print(message)


def show_error(message: str) -> None:
    print(message)


def prompt(label: str) -> str:
    return input(label)


def pause_before_exit() -> None:
    input("按回车键关闭浏览器...")
