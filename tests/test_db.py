import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from app.db.download_record_repository import DownloadRecord, DownloadRecordRepository


class DownloadRecordRepositoryTestCase(unittest.TestCase):
    def test_upsert_and_get_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record(
                "142463788",
                status="completed",
                error_type="",
                title="ヤチいろ",
                author_name="律空rikuu",
                page_count=1,
                download_count=1,
                saved_html="./data/temp/html/artwork_142463788.html",
                saved_json="./data/temp/json/artwork_142463788.json",
                downloaded_files=["./data/images/142463788/142463788_p0.jpg"],
            )

            record = repository.get_record("142463788")

        self.assertIsNotNone(record)
        record = cast(DownloadRecord, record)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["error_type"], "")
        self.assertEqual(record["title"], "ヤチいろ")
        self.assertEqual(record["downloaded_files"], ["./data/images/142463788/142463788_p0.jpg"])

    def test_is_artwork_completed_only_returns_true_for_completed_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record(
                "142463788",
                status="failed",
                error_type="timeout",
                error_message="timeout",
            )
            self.assertFalse(repository.is_artwork_completed("142463788"))

            repository.upsert_record(
                "142463788",
                status="completed",
                error_type="",
                title="ヤチいろ",
            )
            self.assertTrue(repository.is_artwork_completed("142463788"))

    def test_list_records_supports_status_filter_and_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record("100", status="completed", error_type="", title="A")
            repository.upsert_record(
                "200",
                status="failed",
                error_type="timeout",
                title="B",
                error_message="timeout",
            )
            repository.upsert_record("300", status="completed", error_type="", title="C")

            completed_records = repository.list_records(limit=10, status="completed")
            latest_two_records = repository.list_records(limit=2)
            timeout_failed_records = repository.list_records(
                limit=10,
                status="failed",
                error_type="timeout",
            )
            old_completed_records = repository.list_records(
                limit=10,
                status="completed",
                updated_before="9999-01-01T00:00:00",
            )

        self.assertEqual([record["artwork_id"] for record in completed_records], ["300", "100"])
        self.assertEqual(len(latest_two_records), 2)
        self.assertEqual([record["artwork_id"] for record in timeout_failed_records], ["200"])
        self.assertEqual([record["artwork_id"] for record in old_completed_records], ["300", "100"])

    def test_get_status_summary_counts_each_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record("100", status="completed", error_type="", title="A")
            repository.upsert_record(
                "200",
                status="failed",
                error_type="timeout",
                title="B",
                error_message="timeout",
            )
            repository.upsert_record("300", status="completed", error_type="", title="C")

            summary = repository.get_status_summary()

        self.assertEqual(summary.get("completed"), 2)
        self.assertEqual(summary.get("failed"), 1)

    def test_get_error_type_summary_counts_each_error_type(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record("100", status="failed", error_type="timeout", error_message="timeout")
            repository.upsert_record("200", status="failed", error_type="timeout", error_message="timeout")
            repository.upsert_record("300", status="failed", error_type="download", error_message="download")
            repository.upsert_record("400", status="completed", error_type="", title="done")

            summary = repository.get_error_type_summary(status="failed")

        self.assertEqual(summary.get("timeout"), 2)
        self.assertEqual(summary.get("download"), 1)

    def test_delete_records_removes_rows_by_artwork_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record("100", status="completed", error_type="", title="A")
            repository.upsert_record("200", status="failed", error_type="timeout", error_message="timeout")
            deleted_count = repository.delete_records(["100", "999"])
            remaining_100 = repository.get_record("100")
            remaining_200 = repository.get_record("200")

        self.assertEqual(deleted_count, 1)
        self.assertIsNone(remaining_100)
        self.assertIsNotNone(remaining_200)

    def test_mark_failed_preserves_existing_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            downloaded_file = Path(temp_dir) / "artwork_100_p0.jpg"
            downloaded_file.write_bytes(b"image")

            repository.upsert_record(
                "100",
                status="completed",
                error_type="",
                title="A",
                author_name="Author",
                page_count=1,
                download_count=1,
                saved_html="./data/temp/html/artwork_100.html",
                saved_json="./data/temp/json/artwork_100.json",
                downloaded_files=[str(downloaded_file)],
            )

            repository.mark_failed("100", error_type="timeout", error_message="timeout")
            record = repository.get_record("100")

        self.assertIsNotNone(record)
        record = cast(DownloadRecord, record)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error_type"], "timeout")
        self.assertEqual(record["error_message"], "timeout")
        self.assertEqual(record["title"], "A")
        self.assertEqual(record["author_name"], "Author")
        self.assertEqual(record["page_count"], 1)
        self.assertEqual(record["download_count"], 1)
        self.assertEqual(record["saved_html"], "./data/temp/html/artwork_100.html")
        self.assertEqual(record["saved_json"], "./data/temp/json/artwork_100.json")
        self.assertEqual(record["downloaded_files"], [str(downloaded_file)])


if __name__ == "__main__":
    unittest.main()
