import unittest
from tempfile import TemporaryDirectory

from app.db.download_record_repository import DownloadRecordRepository
from app.services.task_service import select_incremental_artwork_ids


class TaskServiceTestCase(unittest.TestCase):
    def test_select_incremental_artwork_ids_keeps_new_and_failed_artworks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()

            repository.upsert_record("200", status="completed", error_type="", title="done")
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

            repository.upsert_record("500", status="completed", error_type="", title="done")
            repository.upsert_record("400", status="completed", error_type="", title="done")
            repository.upsert_record("300", status="completed", error_type="", title="done")

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


if __name__ == "__main__":
    unittest.main()
