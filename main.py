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

from app.browser.client import BrowserClient
from app.browser.login import PixivLoginService
from app.crawler.artwork_crawler import ArtworkCrawler
from app.db.download_record_repository import DownloadRecordRepository
from app.downloader.image_downloader import PixivImageDownloader
from app.services.cli_service import (
    archive_old_records,
    choose_action,
    collect_artwork_ids,
    collect_retry_artwork_ids,
    export_failed_records,
    parse_artwork_ids,
    show_history,
)
from app.services.task_service import print_batch_summary, process_artwork_batch


def main() -> None:
    """
    主函数。

    它像一个“总指挥”：
    - 先决定本次要执行哪种模式
    - 再准备数据库、浏览器、登录服务
    - 最后把任务交给更具体的服务去执行

    换句话说，这里尽量只做“安排工作”，
    不做太多具体实现细节。
    """
    client = BrowserClient()
    record_repository = DownloadRecordRepository()

    try:
        # 先确保数据库表已经准备好。
        # 这样后面不管是查看历史、重试失败，还是正式抓取，都有地方读写记录。
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
            artwork_ids = collect_artwork_ids()

        # 到这里说明本次真的需要访问网站，
        # 所以才启动浏览器。
        client.start()

        login_service = PixivLoginService(client)

        # 如果本地已经有登录态文件，就优先尝试复用。
        # 复用失败时，再删除旧状态并重新登录。
        if client.state_manager.state_exists():
            if login_service.is_logged_in():
                print("检测到已有可用登录状态，无需重新登录。")
            else:
                print("已有登录状态失效，准备重新登录。")
                client.state_manager.delete_state()
                login_service.login_and_save_state()
        else:
            print("未检测到登录状态，准备首次登录。")
            login_service.login_and_save_state()

        crawler = ArtworkCrawler(client)
        downloader = PixivImageDownloader(client)

        print(f"本次共识别到 {len(artwork_ids)} 个作品 ID：{artwork_ids}")

        summary = process_artwork_batch(
            artwork_ids=artwork_ids,
            crawler=crawler,
            downloader=downloader,
            record_repository=record_repository,
        )
        print_batch_summary(summary)

        # 留一点时间给你人工确认结果。
        input("按回车键关闭浏览器...")
    finally:
        # 不管中间有没有报错，最后都要把浏览器关掉。
        # 这样可以避免后台残留浏览器进程。
        client.close()


# 这行的意思是：
# 只有你“直接运行这个文件”时，程序才会从这里启动。
# 如果别的文件只是 `import main`，那就不会自动执行。
if __name__ == "__main__":
    main()
