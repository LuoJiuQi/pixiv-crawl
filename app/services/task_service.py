"""
这个文件专门放“任务执行流程”相关的代码。

这里的“任务”可以简单理解成：
“拿到一个作品 ID 后，程序到底要怎么一步一步把它处理完。”

把这部分独立出来以后：
- `main.py` 只负责总调度
- 这里负责真正干活
- 命令行输入输出则交给 `cli_service.py`

这样每个文件的职责都会更单纯，也更容易读懂。
"""

import json
from typing import Any, TypedDict

from app.crawler.artwork_crawler import ArtworkCrawler
from app.db.download_record_repository import DownloadRecordRepository
from app.downloader.image_downloader import PixivImageDownloader
from app.parser.artwork_parser import ArtworkParser
from app.services.failure_classifier import classify_failure


class ProcessResult(TypedDict):
    """
    描述“单个作品处理结果”应该长什么样。

    你可以把它理解成一张固定格式的“结果清单”。
    只要一个作品处理完成，不管是正常下载，还是被跳过，
    最后都整理成这个格式再往外传。
    """

    artwork_id: str
    title: str
    author_name: str
    page_count: int
    download_count: int
    saved_html: str
    saved_json: str
    downloaded_files: list[str]
    skipped_download: bool
    skipped_by_db: bool


class FailedResult(TypedDict):
    """
    描述“单个失败结果”的最小信息。
    """

    artwork_id: str
    error: str


class BatchRunSummary(TypedDict):
    """
    描述“一整批任务跑完后的汇总结果”。
    """

    success_results: list[ProcessResult]
    failed_results: list[FailedResult]


class IncrementalSelectionResult(TypedDict):
    """
    描述“按作者增量更新时，筛选出来的任务集合”。

    这里除了最终要处理的作品 ID，
    还额外保留一些统计信息，方便在终端里解释：
    - 为什么这次只处理这些作品
    - 为什么提前停止继续往后扫描
    """

    candidate_artwork_ids: list[str]
    new_artwork_ids: list[str]
    retry_artwork_ids: list[str]
    skipped_completed_ids: list[str]
    scanned_artwork_count: int
    total_available_artwork_count: int
    stopped_early: bool
    stop_after_completed_streak: int


def _truncate_text(text: str, max_length: int = 120) -> str:
    """
    把过长的文本裁短一点，避免一行直接刷满整个终端。
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _summarize_debug_value(value: Any) -> str:
    """
    把复杂对象转换成“人眼更容易扫一眼看懂”的摘要文本。

    目标不是完整展示所有内容，
    而是先让你快速判断：
    - 这是字典、列表，还是普通字符串
    - 里面大概有多少项
    - 关键内容是不是已经命中
    """
    if isinstance(value, dict):
        keys = list(value.keys())
        preview = ", ".join(str(key) for key in keys[:5])
        if len(keys) > 5:
            preview += ", ..."
        return f"dict，共 {len(value)} 个键：{preview}"

    if isinstance(value, list):
        if not value:
            return "list，空列表"

        preview_items = ", ".join(_truncate_text(repr(item), 24) for item in value[:3])
        if len(value) > 3:
            preview_items += ", ..."
        return f"list，共 {len(value)} 项：{preview_items}"

    if isinstance(value, tuple):
        return f"tuple：{_truncate_text(repr(value), 80)}"

    if isinstance(value, str):
        return _truncate_text(value, 120)

    return _truncate_text(repr(value), 120)


def _print_image_url_debug(urls: list[str]) -> None:
    """
    更清楚地打印候选图片地址。

    以前是一整行长列表，读起来很费眼。
    现在改成：
    - 先显示总数量
    - 再逐条编号
    """
    print(f"possible_image_urls，共 {len(urls)} 条：")
    if not urls:
        print("  (空)")
        return

    for index, url in enumerate(urls, start=1):
        print(f"  [{index}] {url}")


def _print_next_data_hits_debug(hits: list[tuple[str, Any]]) -> None:
    """
    更清楚地打印 `next_data_hits`。

    这里不再把整个复杂对象原样一股脑塞进一行，
    而是改成“路径 + 摘要”的形式。
    真正完整内容仍然会保存在 JSON 里，调试时可以去文件里慢慢看。
    """
    print(f"next_data_hits，共 {len(hits)} 条：")
    if not hits:
        print("  (空)")
        return

    for index, (path, value) in enumerate(hits, start=1):
        print(f"  [{index}] {path}")
        print(f"      {_summarize_debug_value(value)}")


def _print_parsed_info_debug(info: Any) -> None:
    """
    把解析结果按更容易阅读的格式打印出来。

    这里刻意做成“普通字段一行一个，复杂字段分块展示”，
    这样你在终端里往回翻的时候，会轻松很多。
    """
    print("解析结果：")
    print("title =", info.title)
    print("og_title =", info.og_title)
    print("og_image =", info.og_image)
    print("description =", _truncate_text(info.description, 160))
    print("canonical_url =", info.canonical_url)
    print("artwork_id =", info.artwork_id)
    print("user_id =", info.user_id)
    print("author_name =", info.author_name)
    print("tags =", json.dumps(info.tags, ensure_ascii=False))
    print("page_count =", info.page_count)
    print("has_next_data =", info.has_next_data)

    _print_image_url_debug(info.possible_image_urls[:10])
    _print_next_data_hits_debug(info.next_data_hits)


def process_artwork(
    artwork_id: str,
    crawler: ArtworkCrawler,
    downloader: PixivImageDownloader,
) -> ProcessResult:
    """
    处理单个作品。

    这一步会依次完成：
    - 打开作品页
    - 抓取 HTML
    - 解析作品信息
    - 保存 HTML 和 JSON
    - 下载图片
    """
    current_url = crawler.open_artwork_page(artwork_id)

    print("当前页面 URL：", current_url)
    print("页面标题：", crawler.get_page_title())
    print("是否成功进入作品页：", crawler.is_artwork_page_available(artwork_id))

    html = crawler.get_page_content()
    parser = ArtworkParser(html)
    info = parser.extract_full_info()

    _print_parsed_info_debug(info)

    saved_file = crawler.save_page_source(artwork_id)
    print("页面源码已保存到：", saved_file)

    saved_json = crawler.save_parsed_info(artwork_id, info.model_dump())
    print("解析结果 JSON 已保存到：", saved_json)

    already_downloaded, existing_files = downloader.is_artwork_downloaded(info)
    if already_downloaded:
        print("检测到这个作品已经完整下载，自动跳过。")
        print("已有图片文件：", existing_files[:10])
        return {
            "artwork_id": artwork_id,
            "title": info.title,
            "author_name": info.author_name,
            "page_count": info.page_count,
            "download_count": len(existing_files),
            "saved_html": saved_file,
            "saved_json": saved_json,
            "downloaded_files": existing_files,
            "skipped_download": True,
            "skipped_by_db": False,
        }

    downloaded_files = downloader.download_artwork(info)
    print("下载完成，图片数量：", len(downloaded_files))
    print("图片文件：", downloaded_files[:10])

    return {
        "artwork_id": artwork_id,
        "title": info.title,
        "author_name": info.author_name,
        "page_count": info.page_count,
        "download_count": len(downloaded_files),
        "saved_html": saved_file,
        "saved_json": saved_json,
        "downloaded_files": downloaded_files,
        "skipped_download": False,
        "skipped_by_db": False,
    }


def select_incremental_artwork_ids(
    artwork_ids: list[str],
    record_repository: DownloadRecordRepository,
    completed_streak_limit: int = 10,
) -> IncrementalSelectionResult:
    """
    从作者作品列表里挑出“这次真正需要处理”的作品。

    增量更新的核心规则是：
    - 数据库里没有记录的作品，要处理
    - 数据库里记录为 `failed` 的作品，要处理
    - 数据库里已经 `completed` 的老作品，先跳过

    另外再加一个“提前停止”规则：
    - 如果连续遇到很多个已完成老作品，
      说明后面大概率也都是更老的作品
    - 这时就不必继续往后扫了
    """
    candidate_artwork_ids: list[str] = []
    new_artwork_ids: list[str] = []
    retry_artwork_ids: list[str] = []
    skipped_completed_ids: list[str] = []
    completed_streak = 0
    stopped_early = False
    scanned_artwork_count = 0

    for artwork_id in artwork_ids:
        scanned_artwork_count += 1
        record = record_repository.get_record(artwork_id)

        # 没见过的新作品，当然要处理。
        if record is None:
            candidate_artwork_ids.append(artwork_id)
            new_artwork_ids.append(artwork_id)
            completed_streak = 0
            continue

        # 以前失败过的作品，这次继续纳入候选。
        if record["status"] != "completed":
            candidate_artwork_ids.append(artwork_id)
            retry_artwork_ids.append(artwork_id)
            completed_streak = 0
            continue

        # 走到这里，说明它已经完成过了。
        skipped_completed_ids.append(artwork_id)
        completed_streak += 1

        if completed_streak_limit > 0 and completed_streak >= completed_streak_limit:
            stopped_early = True
            break

    return {
        "candidate_artwork_ids": candidate_artwork_ids,
        "new_artwork_ids": new_artwork_ids,
        "retry_artwork_ids": retry_artwork_ids,
        "skipped_completed_ids": skipped_completed_ids,
        "scanned_artwork_count": scanned_artwork_count,
        "total_available_artwork_count": len(artwork_ids),
        "stopped_early": stopped_early,
        "stop_after_completed_streak": completed_streak_limit,
    }


def print_incremental_selection_summary(selection: IncrementalSelectionResult) -> None:
    """
    把作者增量筛选结果用更直观的方式打印出来。

    这一步的重点不是“把所有 ID 都原样倒出来”，
    而是先让你快速看懂这次任务的大盘：
    - 总共识别到多少作品
    - 实际扫描了多少
    - 新作品有多少
    - 失败重试有多少
    - 已完成跳过有多少
    - 有没有因为连续老作品太多而提前停止
    """
    print("当前使用增量更新模式。")
    print(f"作者作品总数：{selection['total_available_artwork_count']}")
    print(f"本次实际扫描数量：{selection['scanned_artwork_count']}")
    print(f"新作品数量：{len(selection['new_artwork_ids'])}")
    print(f"失败待重试数量：{len(selection['retry_artwork_ids'])}")
    print(f"已完成并跳过数量：{len(selection['skipped_completed_ids'])}")
    print(f"本次最终待处理数量：{len(selection['candidate_artwork_ids'])}")

    if selection["new_artwork_ids"]:
        print("新作品 ID：", selection["new_artwork_ids"])

    if selection["retry_artwork_ids"]:
        print("失败待重试作品 ID：", selection["retry_artwork_ids"])

    if selection["stopped_early"]:
        print(
            "已触发提前停止："
            f"连续遇到 {selection['stop_after_completed_streak']} 个已完成老作品后，停止继续往后扫描。"
        )


def _build_completed_result_from_record(
    artwork_id: str,
    existing_record: dict[str, object],
) -> ProcessResult:
    """
    把数据库里“已完成”的记录，整理成和正常处理结果一致的格式。

    这样主流程后面就不用分两套判断逻辑：
    - 一套给“刚刚下载成功”的作品
    - 一套给“数据库里本来就完成了”的作品
    """
    return {
        "artwork_id": artwork_id,
        "title": str(existing_record["title"]),
        "author_name": str(existing_record["author_name"]),
        "page_count": int(existing_record["page_count"]),
        "download_count": int(existing_record["download_count"]),
        "saved_html": str(existing_record["saved_html"]),
        "saved_json": str(existing_record["saved_json"]),
        "downloaded_files": list(existing_record["downloaded_files"]),
        "skipped_download": True,
        "skipped_by_db": True,
    }


def process_artwork_batch(
    artwork_ids: list[str],
    crawler: ArtworkCrawler,
    downloader: PixivImageDownloader,
    record_repository: DownloadRecordRepository,
) -> BatchRunSummary:
    """
    批量处理多个作品 ID。

    这里最重要的设计点是：
    “单个作品失败，不要把整批任务直接带停。”

    所以每个作品都用自己的 `try/except` 包起来，
    这样一批任务里某一个出错，后面其他作品仍然还能继续跑。
    """
    success_results: list[ProcessResult] = []
    failed_results: list[FailedResult] = []

    for index, artwork_id in enumerate(artwork_ids, start=1):
        print()
        print(f"========== 开始处理第 {index}/{len(artwork_ids)} 个作品：{artwork_id} ==========")

        existing_record = record_repository.get_record(artwork_id)
        if existing_record and existing_record["status"] == "completed":
            print(f"作品 {artwork_id} 已在数据库中标记为完成，直接跳过整套任务。")
            success_results.append(_build_completed_result_from_record(artwork_id, existing_record))
            continue

        try:
            result = process_artwork(artwork_id, crawler, downloader)
            success_results.append(result)

            record_repository.upsert_record(
                artwork_id,
                status="completed",
                error_type="",
                title=result["title"],
                author_name=result["author_name"],
                page_count=result["page_count"],
                download_count=result["download_count"],
                saved_html=result["saved_html"],
                saved_json=result["saved_json"],
                downloaded_files=result["downloaded_files"],
                error_message="",
            )
            print(f"作品 {artwork_id} 处理完成。")
        except Exception as exc:
            error_message = str(exc)
            error_type = classify_failure(error_message)
            failed_result: FailedResult = {
                "artwork_id": artwork_id,
                "error": error_message,
            }
            failed_results.append(failed_result)

            record_repository.upsert_record(
                artwork_id,
                status="failed",
                error_type=error_type,
                error_message=error_message,
            )
            print(f"作品 {artwork_id} 处理失败：{error_message}")
            print(f"失败类型：{error_type}")

    return {
        "success_results": success_results,
        "failed_results": failed_results,
    }


def print_batch_summary(summary: BatchRunSummary) -> None:
    """
    把一整批任务的最终结果打印出来。

    这一步单独抽出来后，主函数只需要说：
    “批量跑完了，请把结果打印出来。”
    """
    success_results = summary["success_results"]
    failed_results = summary["failed_results"]

    print()
    print("========== 本次批量任务汇总 ==========")
    print("成功数量：", len(success_results))
    print("失败数量：", len(failed_results))

    if success_results:
        print("成功作品：", [result["artwork_id"] for result in success_results])
        print(
            "其中跳过重复下载的作品：",
            [result["artwork_id"] for result in success_results if result["skipped_download"]],
        )
        print(
            "其中按数据库直接跳过整套任务的作品：",
            [result["artwork_id"] for result in success_results if result["skipped_by_db"]],
        )

    if failed_results:
        print("失败详情：")
        for item in failed_results:
            print(f"- {item['artwork_id']}: {item['error']}")
