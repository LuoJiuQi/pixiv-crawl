import unittest
from argparse import Namespace
from unittest.mock import MagicMock

from app.services.application_service import (
    ensure_pixiv_login,
    handle_crawl_author_action,
    handle_crawl_following_action,
    handle_doctor_action,
)


class ApplicationServiceTestCase(unittest.TestCase):
    def test_handle_doctor_action_writes_json_and_skips_human_output_when_json_requested(self) -> None:
        console_service = MagicMock()
        runtime_args = Namespace(strict=True, output="data/doctor.json", json_output=True)
        report = {"checks": [{"name": "浏览器启动", "status": "ok", "detail": "ok"}]}
        summary = {"ok": 1, "warn": 0, "error": 0, "skip": 0}

        exit_code = handle_doctor_action(
            runtime_args=runtime_args,
            interactive_mode=False,
            console_service=console_service,
            run_doctor_fn=lambda: report,
            summarize_doctor_report_fn=lambda _report: summary,
            get_doctor_exit_code_fn=lambda _report, *, strict: 0 if strict else 1,
        )

        expected_payload = {
            "checks": report["checks"],
            "summary": summary,
            "strict": True,
            "exit_code": 0,
        }
        self.assertEqual(exit_code, 0)
        console_service.write_json_file.assert_called_once_with(expected_payload, "data/doctor.json")
        console_service.show_json.assert_called_once_with(expected_payload)
        console_service.show_doctor_report.assert_not_called()
        console_service.pause_before_exit.assert_not_called()

    def test_ensure_pixiv_login_reuses_valid_existing_state(self) -> None:
        client = MagicMock()
        client.state_manager.state_exists.return_value = True
        login_service = MagicMock()
        login_service.is_logged_in.return_value = True
        logger = MagicMock()

        result = ensure_pixiv_login(client=client, login_service=login_service, logger=logger)

        self.assertTrue(result)
        login_service.login_and_save_state.assert_not_called()
        client.state_manager.delete_state.assert_not_called()
        logger.info.assert_called_once_with("检测到已有可用登录状态，无需重新登录。")

    def test_ensure_pixiv_login_deletes_invalid_state_and_stops_when_login_fails(self) -> None:
        client = MagicMock()
        client.state_manager.state_exists.return_value = True
        login_service = MagicMock()
        login_service.is_logged_in.return_value = False
        login_service.login_and_save_state.return_value = {"success": False}
        logger = MagicMock()

        result = ensure_pixiv_login(client=client, login_service=login_service, logger=logger)

        self.assertFalse(result)
        client.state_manager.delete_state.assert_called_once()
        login_service.login_and_save_state.assert_called_once()
        logger.error.assert_called_once_with("登录未完成，程序结束。")

    def test_handle_crawl_author_action_returns_incremental_candidates(self) -> None:
        author_crawler = MagicMock()
        author_crawler.collect_author_artwork_ids.return_value = ["300", "200", "100"]
        console_service = MagicMock()
        logger = MagicMock()
        repository = MagicMock()
        selection = {
            "candidate_artwork_ids": ["300", "200"],
            "total_available_artwork_count": 3,
            "scanned_artwork_count": 3,
            "new_artwork_ids": ["300"],
            "retry_artwork_ids": ["200"],
            "skipped_completed_ids": ["100"],
            "stopped_early": False,
            "stop_after_completed_streak": 10,
        }
        select_incremental = MagicMock(return_value=selection)

        artwork_ids = handle_crawl_author_action(
            author_request={
                "user_id": "123",
                "limit": 20,
                "update_mode": "incremental",
                "completed_streak_limit": 10,
            },
            author_crawler=author_crawler,
            record_repository=repository,
            console_service=console_service,
            logger=logger,
            select_incremental_artwork_ids_fn=select_incremental,
        )

        self.assertEqual(artwork_ids, ["300", "200"])
        author_crawler.collect_author_artwork_ids.assert_called_once_with("123", limit=20)
        select_incremental.assert_called_once_with(
            ["300", "200", "100"],
            repository,
            completed_streak_limit=10,
        )
        console_service.show_incremental_selection_summary.assert_called_once_with(selection)

    def test_handle_crawl_following_action_summarizes_updated_skipped_and_failed_authors(self) -> None:
        runtime_args = Namespace(following_limit=3, completed_streak_limit=10)
        author_crawler = MagicMock()
        author_crawler.collect_following_user_ids.return_value = ["1", "2", "3"]
        author_crawler.collect_author_artwork_ids.side_effect = [
            ["100"],
            [],
            RuntimeError("profile failed"),
        ]
        console_service = MagicMock()
        logger = MagicMock()
        repository = MagicMock()
        crawler = MagicMock()
        downloader = MagicMock()
        selection = {
            "candidate_artwork_ids": ["100"],
            "total_available_artwork_count": 1,
            "scanned_artwork_count": 1,
            "new_artwork_ids": ["100"],
            "retry_artwork_ids": [],
            "skipped_completed_ids": [],
            "stopped_early": False,
            "stop_after_completed_streak": 10,
        }
        summary = {"success_results": [{"artwork_id": "100"}], "failed_results": []}
        select_incremental = MagicMock(return_value=selection)
        process_batch = MagicMock(return_value=summary)

        handle_crawl_following_action(
            runtime_args=runtime_args,
            interactive_mode=False,
            author_crawler=author_crawler,
            crawler=crawler,
            downloader=downloader,
            record_repository=repository,
            console_service=console_service,
            logger=logger,
            select_incremental_artwork_ids_fn=select_incremental,
            process_artwork_batch_fn=process_batch,
        )

        process_batch.assert_called_once_with(
            artwork_ids=["100"],
            crawler=crawler,
            downloader=downloader,
            record_repository=repository,
        )
        console_service.show_following_update_summary.assert_called_once_with(
            followed_user_ids=["1", "2", "3"],
            updated_authors=["1"],
            skipped_authors=["2"],
            failed_authors=[("3", "profile failed")],
            total_success_results=[{"artwork_id": "100"}],
            total_failed_results=[],
        )
        console_service.pause_before_exit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
