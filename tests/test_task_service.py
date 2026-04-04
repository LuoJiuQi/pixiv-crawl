import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

from app.db.download_record_repository import DownloadRecord, DownloadRecordRepository
from app.services import task_service
from app.services.task_service import process_artwork, process_artwork_batch, select_incremental_artwork_ids


class DummyCrawler:
    def open_artwork_page(self, artwork_id: str) -> str:
        return f"https://www.pixiv.net/artworks/{artwork_id}"

    def get_page_title(self) -> str:
        return "title"

    def is_artwork_page_available(self, artwork_id: str | None = None) -> bool:
        return True

    def get_page_content(self) -> str:
        return "<html></html>"

    def save_page_source(self, artwork_id: str) -> str:
        raise AssertionError("save_page_source should not be called")

    def save_parsed_info(self, artwork_id: str, parsed_info: dict) -> str:
        raise AssertionError("save_parsed_info should not be called")


class DummyDownloader:
    def is_artwork_downloaded(self, info) -> tuple[bool, list[str]]:
        return False, []

    def download_artwork(self, info) -> list[str]:
        return ["downloaded.jpg"]

    def prepare_artwork_download(self, info):
        return {"artwork": info, "download_plan": [(0, "https://example.com/image.jpg")]}

    def is_prepared_artwork_downloaded(self, prepared) -> tuple[bool, list[str]]:
        return False, []

    def download_prepared_artwork(self, prepared) -> list[str]:
        return ["downloaded.jpg"]


class TaskServiceTestCase(unittest.TestCase):
    def test_select_incremental_artwork_ids_keeps_new_and_failed_artworks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            completed_file = Path(temp_dir) / "200.jpg"
            completed_file.write_bytes(b"done")

            repository.upsert_record(
                "200",
                status="completed",
                error_type="",
                title="done",
                downloaded_files=[str(completed_file)],
            )
            repository.upsert_record("300", status="failed", error_type="timeout", error_message="timeout")

            selection = select_incremental_artwork_ids(
                ["100", "200", "300", "400"],
                repository,
                completed_streak_limit=10,
            )

        self.assertEqual(selection["candidate_artwork_ids"], ["100", "300", "400"])
        self.assertEqual(selection["new_artwork_ids"], ["100", "400"])
        self.assertEqual(selection["retry_artwork_ids"], ["300"])
        self.assertEqual(selection["skipped_completed_ids"], ["200"])
        self.assertEqual(selection["scanned_artwork_count"], 4)
        self.assertEqual(selection["total_available_artwork_count"], 4)
        self.assertFalse(selection["stopped_early"])

    def test_select_incremental_artwork_ids_stops_after_completed_streak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            completed_500 = Path(temp_dir) / "500.jpg"
            completed_400 = Path(temp_dir) / "400.jpg"
            completed_300 = Path(temp_dir) / "300.jpg"
            completed_500.write_bytes(b"500")
            completed_400.write_bytes(b"400")
            completed_300.write_bytes(b"300")

            repository.upsert_record(
                "500",
                status="completed",
                error_type="",
                title="done",
                downloaded_files=[str(completed_500)],
            )
            repository.upsert_record(
                "400",
                status="completed",
                error_type="",
                title="done",
                downloaded_files=[str(completed_400)],
            )
            repository.upsert_record(
                "300",
                status="completed",
                error_type="",
                title="done",
                downloaded_files=[str(completed_300)],
            )

            selection = select_incremental_artwork_ids(
                ["500", "400", "300", "200", "100"],
                repository,
                completed_streak_limit=3,
            )

        self.assertEqual(selection["candidate_artwork_ids"], [])
        self.assertEqual(selection["new_artwork_ids"], [])
        self.assertEqual(selection["retry_artwork_ids"], [])
        self.assertEqual(selection["skipped_completed_ids"], ["500", "400", "300"])
        self.assertEqual(selection["scanned_artwork_count"], 3)
        self.assertEqual(selection["total_available_artwork_count"], 5)
        self.assertTrue(selection["stopped_early"])
        self.assertEqual(selection["stop_after_completed_streak"], 3)

    def test_select_incremental_artwork_ids_retries_completed_artwork_when_files_are_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            repository.upsert_record(
                "200",
                status="completed",
                error_type="",
                title="done",
                downloaded_files=[str(Path(temp_dir) / "missing.jpg")],
            )

            selection = select_incremental_artwork_ids(
                ["200", "100"],
                repository,
                completed_streak_limit=10,
            )

        self.assertEqual(selection["candidate_artwork_ids"], ["200", "100"])
        self.assertEqual(selection["new_artwork_ids"], ["100"])
        self.assertEqual(selection["retry_artwork_ids"], ["200"])
        self.assertEqual(selection["skipped_completed_ids"], [])
        self.assertFalse(selection["stopped_early"])

    def test_process_artwork_batch_reprocesses_completed_record_when_files_are_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            repository.upsert_record(
                "100",
                status="completed",
                error_type="",
                title="old",
                author_name="author",
                page_count=1,
                download_count=1,
                saved_html="./data/temp/html/artwork_100.html",
                saved_json="./data/temp/json/artwork_100.json",
                downloaded_files=[str(Path(temp_dir) / "missing.jpg")],
            )

            expected_result = {
                "artwork_id": "100",
                "title": "new",
                "author_name": "author",
                "page_count": 1,
                "download_count": 1,
                "saved_html": "./data/temp/html/artwork_100.html",
                "saved_json": "./data/temp/json/artwork_100.json",
                "downloaded_files": [str(Path(temp_dir) / "redownloaded.jpg")],
                "skipped_download": False,
                "skipped_by_db": False,
            }

            with patch("app.services.task_service.process_artwork", return_value=expected_result) as mocked:
                with patch.object(task_service, "logger"):
                    summary = process_artwork_batch(
                        ["100"],
                        crawler=object(),
                        downloader=object(),
                        record_repository=repository,
                    )

            record = repository.get_record("100")

        self.assertEqual(len(summary["success_results"]), 1)
        self.assertEqual(summary["success_results"][0]["title"], "new")
        self.assertEqual(summary["failed_results"], [])
        mocked.assert_called_once()
        self.assertIsNotNone(record)
        record = cast(DownloadRecord, record)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["downloaded_files"], [str(Path(temp_dir) / "redownloaded.jpg")])

    def test_process_artwork_batch_reuses_completed_record_when_files_exist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            completed_file = Path(temp_dir) / "done.jpg"
            completed_file.write_bytes(b"done")
            repository.upsert_record(
                "100",
                status="completed",
                error_type="",
                title="old",
                author_name="author",
                page_count=2,
                download_count=1,
                saved_html="./data/temp/html/artwork_100.html",
                saved_json="./data/temp/json/artwork_100.json",
                downloaded_files=[str(completed_file)],
            )

            with patch("app.services.task_service.process_artwork") as mocked:
                summary = process_artwork_batch(
                    ["100"],
                    crawler=object(),
                    downloader=object(),
                    record_repository=repository,
                )

        mocked.assert_not_called()
        self.assertEqual(summary["failed_results"], [])
        self.assertEqual(len(summary["success_results"]), 1)
        self.assertEqual(
            summary["success_results"][0],
            {
                "artwork_id": "100",
                "title": "old",
                "author_name": "author",
                "page_count": 2,
                "download_count": 1,
                "saved_html": "./data/temp/html/artwork_100.html",
                "saved_json": "./data/temp/json/artwork_100.json",
                "downloaded_files": [str(completed_file)],
                "skipped_download": True,
                "skipped_by_db": True,
            },
        )

    def test_process_artwork_skips_debug_artifacts_when_disabled(self) -> None:
        fake_info = type(
            "FakeArtworkInfo",
            (),
            {
                "title": "Title",
                "og_title": "OG Title",
                "og_image": "https://example.com/og.jpg",
                "description": "desc",
                "canonical_url": "https://www.pixiv.net/artworks/100",
                "artwork_id": "100",
                "user_id": "200",
                "author_name": "Author",
                "tags": [],
                "page_count": 1,
                "possible_image_urls": ["https://i.pximg.net/img-original/img/2026/03/20/15/42/15/100_p0.jpg"],
                "has_next_data": True,
                "next_data_hits": [],
                "model_dump": lambda self: {"artwork_id": "100"},
            },
        )()

        with patch.object(task_service.settings, "save_debug_artifacts", False), patch.object(
            task_service.settings,
            "verbose_debug_output",
            False,
        ), patch("app.services.task_service.ArtworkParser") as parser_cls:
            parser_cls.return_value.extract_full_info.return_value = fake_info

            result = process_artwork(
                "100",
                crawler=DummyCrawler(),
                downloader=DummyDownloader(),
            )

        self.assertEqual(result["saved_html"], "")
        self.assertEqual(result["saved_json"], "")
        self.assertEqual(result["downloaded_files"], ["downloaded.jpg"])

    def test_process_artwork_prepares_download_targets_only_once(self) -> None:
        fake_info = type(
            "FakeArtworkInfo",
            (),
            {
                "title": "Title",
                "og_title": "OG Title",
                "og_image": "https://example.com/og.jpg",
                "description": "desc",
                "canonical_url": "https://www.pixiv.net/artworks/100",
                "artwork_id": "100",
                "user_id": "200",
                "author_name": "Author",
                "tags": [],
                "page_count": 1,
                "possible_image_urls": ["https://i.pximg.net/img-original/img/2026/03/20/15/42/15/100_p0.jpg"],
                "has_next_data": True,
                "next_data_hits": [],
                "model_dump": lambda self: {"artwork_id": "100"},
            },
        )()

        class PreparedOnceDownloader(DummyDownloader):
            def __init__(self) -> None:
                self.prepare_calls = 0
                self.received_prepared = None

            def prepare_artwork_download(self, info):
                self.prepare_calls += 1
                return {"artwork": info, "download_plan": [(0, "https://example.com/image.jpg")]}

            def download_prepared_artwork(self, prepared) -> list[str]:
                self.received_prepared = prepared
                return ["downloaded.jpg"]

        downloader = PreparedOnceDownloader()

        with patch.object(task_service.settings, "save_debug_artifacts", False), patch.object(
            task_service.settings,
            "verbose_debug_output",
            False,
        ), patch("app.services.task_service.ArtworkParser") as parser_cls:
            parser_cls.return_value.extract_full_info.return_value = fake_info

            result = process_artwork(
                "100",
                crawler=DummyCrawler(),
                downloader=downloader,
            )

        self.assertEqual(downloader.prepare_calls, 1)
        self.assertEqual(downloader.received_prepared["artwork"], fake_info)
        self.assertEqual(result["downloaded_files"], ["downloaded.jpg"])

    def test_process_artwork_emits_debug_logs_for_page_state(self) -> None:
        fake_info = type(
            "FakeArtworkInfo",
            (),
            {
                "title": "Title",
                "og_title": "OG Title",
                "og_image": "https://example.com/og.jpg",
                "description": "desc",
                "canonical_url": "https://www.pixiv.net/artworks/100",
                "artwork_id": "100",
                "user_id": "200",
                "author_name": "Author",
                "tags": [],
                "page_count": 1,
                "possible_image_urls": ["https://i.pximg.net/img-original/img/2026/03/20/15/42/15/100_p0.jpg"],
                "has_next_data": True,
                "next_data_hits": [],
                "model_dump": lambda self: {"artwork_id": "100"},
            },
        )()

        with patch.object(task_service.settings, "save_debug_artifacts", False), patch.object(
            task_service.settings,
            "verbose_debug_output",
            False,
        ), patch("app.services.task_service.ArtworkParser") as parser_cls, patch.object(
            task_service,
            "logger",
        ) as mocked_logger:
            parser_cls.return_value.extract_full_info.return_value = fake_info

            process_artwork(
                "100",
                crawler=DummyCrawler(),
                downloader=DummyDownloader(),
            )

        mocked_logger.debug.assert_any_call("当前页面 URL：%s", "https://www.pixiv.net/artworks/100")

    def test_process_artwork_verbose_debug_uses_logger_instead_of_print(self) -> None:
        fake_info = type(
            "FakeArtworkInfo",
            (),
            {
                "title": "Title",
                "og_title": "OG Title",
                "og_image": "https://example.com/og.jpg",
                "description": "desc",
                "canonical_url": "https://www.pixiv.net/artworks/100",
                "artwork_id": "100",
                "user_id": "200",
                "author_name": "Author",
                "tags": [],
                "page_count": 1,
                "possible_image_urls": ["https://example.com/image.jpg"],
                "has_next_data": True,
                "next_data_hits": [("props.illustId", "100")],
                "model_dump": lambda self: {"artwork_id": "100"},
            },
        )()

        with patch.object(task_service.settings, "save_debug_artifacts", False), patch.object(
            task_service.settings,
            "verbose_debug_output",
            True,
        ), patch("app.services.task_service.ArtworkParser") as parser_cls, patch.object(
            task_service,
            "logger",
        ) as mocked_logger, patch("builtins.print") as mocked_print:
            parser_cls.return_value.extract_full_info.return_value = fake_info

            process_artwork(
                "100",
                crawler=DummyCrawler(),
                downloader=DummyDownloader(),
            )

        mocked_print.assert_not_called()
        mocked_logger.debug.assert_any_call("解析结果：")
        mocked_logger.debug.assert_any_call("标题：%s", "Title")
        mocked_logger.debug.assert_any_call("分享标题（og:title）：%s", "OG Title")

    def test_process_artwork_logs_downloaded_files_as_numbered_lines_without_truncation(self) -> None:
        fake_info = type(
            "FakeArtworkInfo",
            (),
            {
                "title": "Title",
                "og_title": "OG Title",
                "og_image": "https://example.com/og.jpg",
                "description": "desc",
                "canonical_url": "https://www.pixiv.net/artworks/100",
                "artwork_id": "100",
                "user_id": "200",
                "author_name": "Author",
                "tags": [],
                "page_count": 12,
                "possible_image_urls": ["https://example.com/image.jpg"],
                "has_next_data": True,
                "next_data_hits": [],
                "model_dump": lambda self: {"artwork_id": "100"},
            },
        )()

        class MultiFileDownloader(DummyDownloader):
            def download_prepared_artwork(self, prepared) -> list[str]:
                return [
                    f"data/images/author/work__100_p{index}.jpg"
                    for index in range(12)
                ]

        with patch.object(task_service.settings, "save_debug_artifacts", False), patch.object(
            task_service.settings,
            "verbose_debug_output",
            False,
        ), patch("app.services.task_service.ArtworkParser") as parser_cls, patch.object(
            task_service,
            "logger",
        ) as mocked_logger:
            parser_cls.return_value.extract_full_info.return_value = fake_info

            process_artwork(
                "100",
                crawler=DummyCrawler(),
                downloader=MultiFileDownloader(),
            )

        mocked_logger.debug.assert_any_call("%s，共 %s 张：", "已下载图片", 12)
        mocked_logger.debug.assert_any_call("  [%s] %s", 12, "data/images/author/work__100_p11.jpg")
        self.assertNotIn(
            unittest.mock.call("图片文件：%s", unittest.mock.ANY),
            mocked_logger.debug.call_args_list,
        )

    def test_process_artwork_logs_single_artwork_success_at_debug_level(self) -> None:
        fake_info = type(
            "FakeArtworkInfo",
            (),
            {
                "title": "Title",
                "og_title": "OG Title",
                "og_image": "https://example.com/og.jpg",
                "description": "desc",
                "canonical_url": "https://www.pixiv.net/artworks/100",
                "artwork_id": "100",
                "user_id": "200",
                "author_name": "Author",
                "tags": [],
                "page_count": 1,
                "possible_image_urls": ["https://example.com/image.jpg"],
                "has_next_data": True,
                "next_data_hits": [],
                "model_dump": lambda self: {"artwork_id": "100"},
            },
        )()

        with patch.object(task_service.settings, "save_debug_artifacts", False), patch.object(
            task_service.settings,
            "verbose_debug_output",
            False,
        ), patch("app.services.task_service.ArtworkParser") as parser_cls, patch.object(
            task_service,
            "logger",
        ) as mocked_logger:
            parser_cls.return_value.extract_full_info.return_value = fake_info

            process_artwork(
                "100",
                crawler=DummyCrawler(),
                downloader=DummyDownloader(),
            )

        mocked_logger.debug.assert_any_call("作品 %s 下载完成，图片数量：%s", "100", 1)
        self.assertNotIn(
            unittest.mock.call("作品 %s 下载完成，图片数量：%s", "100", 1),
            mocked_logger.info.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
