"""
这个文件是整个项目的“程序入口”。

所谓入口，可以理解成：
“当你运行 `python main.py` 时，程序最先从哪里开始执行。”

这个文件本身不负责具体业务细节，
它更像一个“总调度台”，把不同模块按顺序串起来：

1. 启动浏览器
2. 检查并复用登录状态
3. 必要时手动登录
4. 打开指定作品页
5. 获取 HTML 并解析作品信息
6. 保存 HTML 和解析结果
7. 下载作品图片

如果你想先快速理解“整个项目是怎么跑起来的”，
最适合先读这个文件。
"""

from pathlib import Path
import re
from datetime import datetime, timedelta
from typing import TypedDict

from app.browser.client import BrowserClient
from app.browser.login import PixivLoginService
from app.crawler.artwork_crawler import ArtworkCrawler
from app.db.download_record_repository import DownloadRecordRepository
from app.downloader.image_downloader import PixivImageDownloader
from app.parser.artwork_parser import ArtworkParser
from app.services.failure_classifier import classify_failure
from app.services.failure_exporter import build_failure_export_path, export_failure_records
from app.services.record_exporter import build_record_export_path, export_records


class ProcessResult(TypedDict):
    """
    描述“单个作品处理结果”应该包含哪些字段。

    以前这里直接用 `dict[str, object]`，
    虽然运行没问题，但类型检查器并不知道每个键对应的值是什么类型，
    所以在取 `page_count`、`downloaded_files` 时容易报错。
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


def choose_action() -> str:
    """
    让用户选择本次要执行的操作。

    目前支持两种模式：
    - `crawl`：正常抓取和下载
    - `history`：查看数据库里的历史记录
    - `retry_failed`：重试数据库里失败过的作品
    - `export_failed`：导出失败清单
    - `archive_records`：归档并清理旧记录
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


def collect_history_options() -> tuple[str | None, str | None, int]:
    """
    读取“查看历史记录”模式下的过滤条件。
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
    从数据库里挑出需要重试的失败作品 ID。

    这里默认按“最近失败的优先”来取，
    因为越新的失败记录，通常越接近你当前正在处理的问题。
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
    导出失败清单到本地文件。
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
    归档并清理较旧的历史记录。

    默认更偏保守：
    - 先筛选
    - 先导出
    - 再删除
    - 默认只处理 `completed`
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


def parse_artwork_ids(raw_text: str) -> list[str]:
    """
    把用户输入的一段文本解析成作品 ID 列表。

    支持的输入形式：
    - 单个作品 ID
    - 多个作品 ID，用空格、逗号、顿号、分号分隔
    - 多行粘贴
    - 直接粘贴 Pixiv 作品链接

    例如下面这些输入都可以：
    - `142463788`
    - `142463788, 142543623`
    - `https://www.pixiv.net/artworks/142463788`
    """
    candidates = re.findall(r"(?:https?://www\.pixiv\.net/(?:[a-z]{2}/)?artworks/)?(\d+)", raw_text)

    artwork_ids: list[str] = []
    for artwork_id in candidates:
        if artwork_id not in artwork_ids:
            artwork_ids.append(artwork_id)

    return artwork_ids


def collect_artwork_ids() -> list[str]:
    """
    从命令行读取一批作品 ID。

    输入方式尽量做得宽松一点，方便你直接粘贴：
    - 可以一次输入一行，行内用空格或逗号分隔多个 ID
    - 也可以连续粘贴多行
    - 输入一个空行，表示“输入结束，开始执行”
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


def process_artwork(
    artwork_id: str,
    crawler: ArtworkCrawler,
    downloader: PixivImageDownloader,
) -> ProcessResult:
    """
    处理单个作品。

    这里把“打开页面 -> 解析 -> 保存 -> 下载”这整套流程单独封装起来，
    这样主函数在做批量循环时会更清晰。
    """
    # 打开对应作品页，并拿到最终停留的页面 URL。
    current_url = crawler.open_artwork_page(artwork_id)

    # 先打印一些基础信息，方便你快速确认：
    # - 是否真的进入了目标作品页
    # - 页面标题是不是对的
    print("当前页面 URL：", current_url)
    print("页面标题：", crawler.get_page_title())
    print("是否成功进入作品页：", crawler.is_artwork_page_available(artwork_id))

    # 获取当前页面的完整 HTML。
    # 后面的解析器会基于这份 HTML 提取结构化字段。
    html = crawler.get_page_content()

    # 创建解析器，并把 HTML 交给它。
    parser = ArtworkParser(html)

    # 一次性提取完整作品信息。
    # 返回的是 `ArtworkInfo` 结构化对象，而不是普通字典。
    info = parser.extract_full_info()

    # 把解析结果打印到控制台，方便你立刻看到程序提取到了什么。
    print("解析结果：")
    print("title =", info.title)
    print("og_title =", info.og_title)
    print("og_image =", info.og_image)
    print("description =", info.description)
    print("canonical_url =", info.canonical_url)
    print("artwork_id =", info.artwork_id)
    print("user_id =", info.user_id)
    print("author_name =", info.author_name)
    print("tags =", info.tags)
    print("page_count =", info.page_count)

    # 图片候选地址可能比较多，所以这里只先打印前 10 个，避免刷屏。
    print("possible_image_urls =", info.possible_image_urls[:10])
    print("has_next_data =", info.has_next_data)
    print("next_data_hits =", info.next_data_hits)

    # 保存当前页面 HTML 到本地。
    # 这个文件后面很适合做：
    # - 页面结构调试
    # - 解析器排错
    # - 单元测试样本
    saved_file = crawler.save_page_source(artwork_id)
    print("页面源码已保存到：", saved_file)

    # 把已经解析好的结构化结果也保存成 JSON。
    # `model_dump()` 会把 Pydantic 模型转成普通字典，方便写入 JSON 文件。
    saved_json = crawler.save_parsed_info(artwork_id, info.model_dump())
    print("解析结果 JSON 已保存到：", saved_json)

    # 如果本地已经存在这个作品的全部图片，就直接跳过重复下载。
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

    # 开始下载图片。
    # 下载器会根据解析器给出的候选 URL 自动选择合适的图片地址。
    downloaded_files = downloader.download_artwork(info)
    print("下载完成，图片数量：", len(downloaded_files))

    # 同样为了避免输出太长，这里只先显示前 10 个文件路径。
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


def main():
    """
    主函数。

    这个函数相当于整条流程的“总指挥”。
    它不会自己去实现底层细节，而是负责：
    - 先创建需要的对象
    - 再按正确顺序调用它们
    - 最后把结果打印和保存出来
    """

    # 先创建浏览器客户端。
    # 这个对象负责 Playwright 浏览器的启动、页面对象创建、状态复用和关闭。
    client = BrowserClient()
    record_repository = DownloadRecordRepository()

    try:
        # 先初始化数据库表。
        # 这样后面不管是跳过已完成作品，还是写入结果，都有表可用。
        record_repository.initialize()

        action = choose_action()
        if action == "history":
            show_history(record_repository)
            return

        if action == "export_failed":
            export_failed_records(record_repository)
            return

        if action == "archive_records":
            archive_old_records(record_repository)
            return

        if action == "retry_failed":
            artwork_ids = collect_retry_artwork_ids(record_repository)
            if not artwork_ids:
                return
        else:
            # 从命令行读取用户输入的一批作品 ID。
            artwork_ids = collect_artwork_ids()

        # 启动浏览器环境。
        # 这一步完成后，后面登录、打开页面、读取 HTML 才有基础可用。
        client.start()

        # 创建登录服务对象。
        # 它会复用上面已经启动好的浏览器，而不是自己再开一个浏览器。
        login_service = PixivLoginService(client)

        # 先检查本地是否已经有保存过的登录状态文件。
        if client.state_manager.state_exists():
            # 有状态文件，不代表它一定还有效。
            # 所以这里还要进一步实际访问网站，判断登录态是否仍然可用。
            if login_service.is_logged_in():
                print("检测到已有可用登录状态，无需重新登录。")
            else:
                # 状态文件还在，但已经失效了。
                # 这时先删除旧状态，再走一次重新登录流程。
                print("已有登录状态失效，准备重新登录。")
                client.state_manager.delete_state()
                login_service.login_and_save_state()
        else:
            # 连状态文件都没有，说明这是首次运行，或者你之前主动删掉了状态。
            print("未检测到登录状态，准备首次登录。")
            login_service.login_and_save_state()

        # 登录完成后，创建作品页采集器。
        # 这个对象专门负责打开作品详情页、读取 HTML、保存页面源码。
        crawler = ArtworkCrawler(client)

        # 创建下载器。
        # 它会复用同一个浏览器上下文里的 cookies 和登录态来下载图片。
        downloader = PixivImageDownloader(client)

        print(f"本次共识别到 {len(artwork_ids)} 个作品 ID：{artwork_ids}")

        success_results: list[ProcessResult] = []
        failed_results: list[dict[str, str]] = []

        for index, artwork_id in enumerate(artwork_ids, start=1):
            print()
            print(f"========== 开始处理第 {index}/{len(artwork_ids)} 个作品：{artwork_id} ==========")

            # 如果数据库已经记住这个作品之前成功处理过，
            # 就连“打开网页和解析”这一步都直接跳过。
            existing_record = record_repository.get_record(artwork_id)
            if existing_record and existing_record["status"] == "completed":
                print(f"作品 {artwork_id} 已在数据库中标记为完成，直接跳过整套任务。")
                success_results.append(
                    {
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
                )
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
                # 批量模式下最重要的一点是：
                # 单个作品失败时，不要让后面的作品也全部停掉。
                error_message = str(exc)
                error_type = classify_failure(error_message)
                failed_results.append(
                    {
                        "artwork_id": artwork_id,
                        "error": error_message,
                    }
                )
                record_repository.upsert_record(
                    artwork_id,
                    status="failed",
                    error_type=error_type,
                    error_message=error_message,
                )
                print(f"作品 {artwork_id} 处理失败：{error_message}")
                print(f"失败类型：{error_type}")

        print()
        print("========== 本次批量任务汇总 ==========")
        print("成功数量：", len(success_results))
        print("失败数量：", len(failed_results))

        if success_results:
            print("成功作品：", [result["artwork_id"] for result in success_results])
            print(
                "其中跳过重复下载的作品：",
                [result["artwork_id"] for result in success_results if result.get("skipped_download")],
            )
            print(
                "其中按数据库直接跳过整套任务的作品：",
                [result["artwork_id"] for result in success_results if result.get("skipped_by_db")],
            )

        if failed_results:
            print("失败详情：")
            for item in failed_results:
                print(f"- {item['artwork_id']}: {item['error']}")

        # 程序执行完后先别急着关浏览器，
        # 给你留一个“手动确认结果”的机会。
        input("按回车键关闭浏览器...")
    finally:
        # `finally` 的意思是：
        # 不管前面流程成功还是失败，最后都会执行这里。
        #
        # 这样可以确保浏览器资源一定会被释放，
        # 避免后台残留 Chromium 进程。
        client.close()


# 只有当这个文件是“直接运行”时，才执行 main()。
# 如果它只是被别的文件 import 进去，就不会自动执行。
if __name__ == "__main__":
    main()
