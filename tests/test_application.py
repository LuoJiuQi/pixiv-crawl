import unittest
from argparse import Namespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from app.application import PixivApplication
from app.crawler.author_crawler import AuthorCrawler
from app.schemas.task import BatchRunSummary, IncrementalSelectionResult, ProcessResult
from app.services.cli_service import AuthorCollectOptions


class PixivApplicationTestCase(unittest.TestCase):
    """测试 PixivApplication 各个动作处理方法的行为（从 test_application_service.py 迁移）。"""

    # ---- _handle_doctor -------------------------------------------------

    def test_handle_doctor_writes_json_and_skips_human_output_when_json_requested(self) -> None:
        app = PixivApplication()
        runtime_args = Namespace(strict=True, output="data/doctor.json", json_output=True)
        report = {"checks": [{"name": "浏览器启动", "status": "ok", "detail": "ok"}]}
        summary = {"ok": 1, "warn": 0, "error": 0, "skip": 0}

        with patch("app.application.run_doctor", return_value=report), \
                patch("app.application.summarize_doctor_report", return_value=summary), \
                patch("app.application.get_doctor_exit_code", return_value=0) as mocked_get_exit_code, \
                patch("app.application.console_service.write_json_file") as mocked_write_json_file, \
                patch("app.application.console_service.show_json") as mocked_show_json, \
                patch("app.application.console_service.show_doctor_report") as mocked_show_doctor_report, \
                patch("app.application.console_service.pause_before_exit") as mocked_pause:
            exit_code = app._handle_doctor(runtime_args=runtime_args, interactive_mode=False)

        expected_payload = {
            "checks": report["checks"],
            "summary": summary,
            "strict": True,
            "exit_code": 0,
        }
        self.assertEqual(exit_code, 0)
        mocked_get_exit_code.assert_called_once_with(report, strict=True)
        mocked_write_json_file.assert_called_once_with(expected_payload, "data/doctor.json")
        mocked_show_json.assert_called_once_with(expected_payload)
        mocked_show_doctor_report.assert_not_called()
        mocked_pause.assert_not_called()

    # ---- _ensure_logged_in -----------------------------------------------

    def test_ensure_logged_in_reuses_valid_existing_state(self) -> None:
        app = PixivApplication()
        app.client = cast(Any, MagicMock())
        app.client.state_manager.state_exists.return_value = True
        app.login_service = cast(Any, MagicMock())
        app.login_service.is_logged_in.return_value = True

        with patch("app.application.logger") as mocked_logger:
            result = app._ensure_logged_in()

        self.assertTrue(result)
        app.login_service.login_and_save_state.assert_not_called()
        app.client.state_manager.delete_state.assert_not_called()
        mocked_logger.info.assert_called_once_with("检测到已有可用登录状态，无需重新登录。")

    def test_ensure_logged_in_deletes_invalid_state_and_stops_when_login_fails(self) -> None:
        app = PixivApplication()
        app.client = cast(Any, MagicMock())
        app.client.state_manager.state_exists.return_value = True
        app.login_service = cast(Any, MagicMock())
        app.login_service.is_logged_in.return_value = False
        app.login_service.login_and_save_state.return_value = {"success": False}

        with patch("app.application.logger") as mocked_logger:
            result = app._ensure_logged_in()

        self.assertFalse(result)
        app.client.state_manager.delete_state.assert_called_once()
        app.login_service.login_and_save_state.assert_called_once()
        mocked_logger.error.assert_called_once_with("登录未完成，程序结束。")

    # ---- _handle_crawl_author --------------------------------------------

    # pyright: ignore[misc] — unittest requires instance methods
    def test_handle_crawl_author_returns_incremental_candidates(self) -> None:
        app = PixivApplication()
        app.author_crawler = cast(AuthorCrawler, MagicMock())
        app.author_crawler.collect_author_artwork_ids.return_value = ["300", "200", "100"]
        app.record_repository = MagicMock()
        app.crawler = MagicMock()
        app.downloader = MagicMock()
        selection = IncrementalSelectionResult(
            candidate_artwork_ids=["300", "200"],
            total_available_artwork_count=3,
            scanned_artwork_count=3,
            new_artwork_ids=["300"],
            retry_artwork_ids=["200"],
            skipped_completed_ids=["100"],
            stopped_early=False,
            stop_after_completed_streak=10,
        )

        with patch("app.application.select_incremental_artwork_ids", return_value=selection) as mocked_select, \
                patch("app.application.console_service.show_incremental_selection_summary") as mocked_show_selection, \
                patch("app.application.logger"):
            _ = app._handle_crawl_author(
                author_request=cast(AuthorCollectOptions, {
                    "user_id": "123",
                    "limit": 20,
                    "update_mode": "incremental",
                    "completed_streak_limit": 10,
                }),
                interactive_mode=False,
            )

        app.author_crawler.collect_author_artwork_ids.assert_called_once_with("123", limit=20)  # type: ignore[union-attr]
        mocked_select.assert_called_once_with(
            ["300", "200", "100"],
            app.record_repository,
            completed_streak_limit=10,
        )
        mocked_show_selection.assert_called_once_with(selection)

    # ---- _handle_crawl_following -----------------------------------------

    # pyright: ignore[misc] — unittest requires instance methods
    def test_handle_crawl_following_summarizes_updated_skipped_and_failed_authors(self) -> None:
        app = PixivApplication()
        runtime_args = Namespace(following_limit=3, completed_streak_limit=10)

        app.author_crawler = cast(AuthorCrawler, MagicMock())
        app.author_crawler.collect_following_user_ids.return_value = ["1", "2", "3"]  # type: ignore[union-attr]
        app.author_crawler.collect_author_artwork_ids.side_effect = [  # type: ignore[union-attr]
            ["100"],
            [],
            RuntimeError("profile failed"),
        ]
        app.crawler = MagicMock()
        app.downloader = MagicMock()
        app.record_repository = MagicMock()
        selection = IncrementalSelectionResult(
            candidate_artwork_ids=["100"],
            total_available_artwork_count=1,
            scanned_artwork_count=1,
            new_artwork_ids=["100"],
            retry_artwork_ids=[],
            skipped_completed_ids=[],
            stopped_early=False,
            stop_after_completed_streak=10,
        )
        summary = BatchRunSummary(
            success_results=[ProcessResult(artwork_id="100")],
            failed_results=[],
        )

        with patch("app.application.select_incremental_artwork_ids", return_value=selection), \
                patch("app.application.process_artwork_batch", return_value=summary) as mocked_process_batch, \
                patch("app.application.console_service.show_incremental_selection_summary"), \
                patch("app.application.console_service.show_batch_summary"), \
                patch("app.application.console_service.show_following_update_summary") as mocked_show_following, \
                patch("app.application.console_service.pause_before_exit") as mocked_pause, \
                patch("app.application.logger"):
            app._handle_crawl_following(runtime_args=runtime_args, interactive_mode=False)

        mocked_process_batch.assert_called_once_with(
            artwork_ids=["100"],
            crawler=app.crawler,
            downloader=app.downloader,
            record_repository=app.record_repository,
        )
        mocked_show_following.assert_called_once_with(
            followed_user_ids=["1", "2", "3"],
            updated_authors=["1"],
            skipped_authors=["2"],
            failed_authors=[("3", "profile failed")],
            total_success_results=[ProcessResult(artwork_id="100")],
            total_failed_results=[],
        )
        mocked_pause.assert_not_called()


if __name__ == "__main__":
    unittest.main()
