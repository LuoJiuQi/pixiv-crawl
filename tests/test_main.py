import unittest
from unittest.mock import MagicMock, patch

import main
from main import action_requires_direct_artwork_input, parse_artwork_ids, parse_runtime_arguments


class MainInputParsingTestCase(unittest.TestCase):
    def test_action_requires_direct_artwork_input_skips_following_mode(self) -> None:
        self.assertFalse(action_requires_direct_artwork_input("crawl_following"))

    def test_parse_artwork_ids_supports_multiple_separators(self) -> None:
        raw_text = "142463788, 142543623 142522397\n142501413；142463788"

        artwork_ids = parse_artwork_ids(raw_text)

        self.assertEqual(
            artwork_ids,
            ["142463788", "142543623", "142522397", "142501413"],
        )

    def test_parse_artwork_ids_supports_pixiv_urls(self) -> None:
        raw_text = """
        https://www.pixiv.net/artworks/142463788
        https://www.pixiv.net/en/artworks/142543623
        """

        artwork_ids = parse_artwork_ids(raw_text)

        self.assertEqual(artwork_ids, ["142463788", "142543623"])

    def test_parse_artwork_ids_returns_empty_for_invalid_text(self) -> None:
        raw_text = "hello world, not an artwork id"

        artwork_ids = parse_artwork_ids(raw_text)

        self.assertEqual(artwork_ids, [])

    def test_parse_runtime_arguments_supports_crawl_inputs(self) -> None:
        args = parse_runtime_arguments(
            ["crawl", "142463788", "https://www.pixiv.net/artworks/142543623"]
        )

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "crawl")
        self.assertEqual(args.artwork_ids, ["142463788", "142543623"])

    def test_parse_runtime_arguments_supports_crawl_author_options(self) -> None:
        args = parse_runtime_arguments(
            [
                "crawl-author",
                "https://www.pixiv.net/users/123456",
                "--limit",
                "20",
                "--update-mode",
                "full",
                "--completed-streak-limit",
                "15",
            ]
        )

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "crawl_author")
        self.assertEqual(
            args.author_request,
            {
                "user_id": "123456",
                "limit": 20,
                "update_mode": "full",
                "completed_streak_limit": 15,
            },
        )

    def test_parse_runtime_arguments_supports_crawl_following_options(self) -> None:
        args = parse_runtime_arguments(
            ["crawl-following", "--limit", "3", "--completed-streak-limit", "15"]
        )

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "crawl_following")
        self.assertEqual(args.following_limit, 3)
        self.assertEqual(args.completed_streak_limit, 15)

    def test_parse_runtime_arguments_supports_doctor_command(self) -> None:
        args = parse_runtime_arguments(["doctor"])

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "doctor")

    def test_parse_runtime_arguments_supports_doctor_strict_mode(self) -> None:
        args = parse_runtime_arguments(["doctor", "--strict"])

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "doctor")
        self.assertTrue(args.strict)

    def test_main_stops_when_login_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = False

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.login_and_save_state.return_value = {
            "success": False,
            "issue": "headless_manual_required",
            "requires_manual_action": False,
            "state_saved": False,
        }

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.configure_logging",
        ) as mocked_configure_logging, patch(
            "main.choose_action",
            return_value="crawl",
        ), patch("main.collect_artwork_ids", return_value=["100"]), patch(
            "main.process_artwork_batch"
        ) as mocked_batch, patch.object(
            main,
            "logger",
        ) as mocked_logger:
            main.main()

        mocked_configure_logging.assert_called_once()
        mock_repository.initialize.assert_called_once()
        mock_client.start.assert_called_once()
        mock_login_service.login_and_save_state.assert_called_once()
        mocked_batch.assert_not_called()
        mocked_logger.error.assert_called_once_with("登录未完成，程序结束。")
        mock_client.close.assert_called_once()

    def test_main_uses_console_pause_before_exit_after_batch(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = {"success_results": [], "failed_results": []}

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action",
            return_value="crawl",
        ), patch("main.collect_artwork_ids", return_value=["100"]), patch(
            "main.process_artwork_batch",
            return_value=summary,
        ), patch(
            "main.console_service.show_batch_summary"
        ), patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main()

        mocked_pause.assert_called_once()
        mock_client.close.assert_called_once()

    def test_main_routes_batch_summary_to_console_layer(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = {
            "success_results": [
                {
                    "artwork_id": "100",
                    "skipped_download": False,
                    "skipped_by_db": False,
                }
            ],
            "failed_results": [{"artwork_id": "200", "error": "timeout"}],
        }

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action",
            return_value="crawl",
        ), patch("main.collect_artwork_ids", return_value=["100"]), patch(
            "main.process_artwork_batch",
            return_value=summary,
        ), patch(
            "main.console_service.show_batch_summary"
        ) as mocked_show_batch_summary, patch(
            "main.console_service.pause_before_exit"
        ):
            main.main()

        mocked_show_batch_summary.assert_called_once_with(summary)

    def test_main_logs_long_artwork_id_list_at_debug_level(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = {"success_results": [], "failed_results": []}

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action",
            return_value="crawl",
        ), patch("main.collect_artwork_ids", return_value=["100", "200"]), patch(
            "main.process_artwork_batch",
            return_value=summary,
        ), patch(
            "main.console_service.show_batch_summary"
        ), patch(
            "main.console_service.pause_before_exit"
        ), patch.object(
            main,
            "logger",
        ) as mocked_logger:
            main.main()

        mocked_logger.info.assert_any_call("本次共识别到 %s 个作品 ID。", 2)
        mocked_logger.debug.assert_any_call("本次作品 ID 列表：%s", ["100", "200"])
        self.assertNotIn(
            unittest.mock.call("本次作品 ID 列表：%s", ["100", "200"]),
            mocked_logger.info.call_args_list,
        )

    def test_main_uses_cli_arguments_without_prompting_for_action_or_ids(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = {"success_results": [], "failed_results": []}

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action"
        ) as mocked_choose_action, patch(
            "main.collect_artwork_ids"
        ) as mocked_collect_artwork_ids, patch(
            "main.process_artwork_batch",
            return_value=summary,
        ), patch(
            "main.console_service.show_batch_summary"
        ), patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(["crawl", "100", "200"])

        mocked_choose_action.assert_not_called()
        mocked_collect_artwork_ids.assert_not_called()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_history_cli_arguments_without_prompting_for_filters(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action"
        ) as mocked_choose_action, patch(
            "main.show_history"
        ) as mocked_show_history, patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(["history", "--status", "failed", "--error-type", "timeout", "--limit", "5"])

        mocked_choose_action.assert_not_called()
        mocked_show_history.assert_called_once_with(
            mock_repository,
            status="failed",
            error_type="timeout",
            limit=5,
            prompt_for_filters=False,
        )
        mock_client.start.assert_not_called()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_doctor_command_without_initializing_database(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = {
            "checks": [
                {"name": "浏览器启动", "status": "ok", "detail": "ok"},
            ]
        }

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "main.configure_logging",
        ), patch(
            "main.run_doctor",
            return_value=report,
        ) as mocked_run_doctor, patch(
            "main.summarize_doctor_report",
            return_value={"ok": 1, "warn": 0, "error": 0, "skip": 0},
        ) as mocked_summarize, patch(
            "main.get_doctor_exit_code",
            return_value=0,
        ) as mocked_get_exit_code, patch(
            "main.console_service.show_doctor_report"
        ) as mocked_show_doctor_report, patch(
            "main.console_service.show_summary"
        ) as mocked_show_summary, patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            exit_code = main.main(["doctor"])

        mocked_run_doctor.assert_called_once()
        mocked_summarize.assert_called_once_with(report)
        mocked_get_exit_code.assert_called_once_with(report, strict=False)
        mocked_show_doctor_report.assert_called_once_with(report)
        mocked_show_summary.assert_called_once_with(
            "自检结果汇总",
            [("ok", 1), ("warn", 0), ("error", 0), ("skip", 0)],
        )
        self.assertEqual(exit_code, 0)
        mock_repository.initialize.assert_not_called()
        mock_client.start.assert_not_called()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_doctor_strict_mode_to_nonzero_exit_code(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = {
            "checks": [
                {"name": "账号密码", "status": "warn", "detail": "missing"},
            ]
        }

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "main.configure_logging",
        ), patch(
            "main.run_doctor",
            return_value=report,
        ), patch(
            "main.summarize_doctor_report",
            return_value={"ok": 0, "warn": 1, "error": 0, "skip": 0},
        ), patch(
            "main.get_doctor_exit_code",
            return_value=1,
        ) as mocked_get_exit_code, patch(
            "main.console_service.show_doctor_report"
        ), patch(
            "main.console_service.show_summary"
        ), patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            exit_code = main.main(["doctor", "--strict"])

        mocked_get_exit_code.assert_called_once_with(report, strict=True)
        self.assertEqual(exit_code, 1)
        mocked_pause.assert_not_called()
        mock_repository.initialize.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_export_failed_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action"
        ) as mocked_choose_action, patch(
            "main.export_failed_records"
        ) as mocked_export_failed_records, patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(
                ["export-failed", "--error-type", "timeout", "--limit", "5", "--format", "txt"]
            )

        mocked_choose_action.assert_not_called()
        mocked_export_failed_records.assert_called_once_with(
            mock_repository,
            error_type="timeout",
            limit=5,
            file_format="txt",
            interactive=False,
        )
        mock_client.start.assert_not_called()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_archive_records_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action"
        ) as mocked_choose_action, patch(
            "main.archive_old_records"
        ) as mocked_archive_old_records, patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(
                [
                    "archive-records",
                    "--status",
                    "failed",
                    "--days",
                    "30",
                    "--limit",
                    "5",
                    "--format",
                    "txt",
                    "--yes",
                ]
            )

        mocked_choose_action.assert_not_called()
        mocked_archive_old_records.assert_called_once_with(
            mock_repository,
            status="failed",
            days=30,
            limit=5,
            file_format="txt",
            interactive=False,
            confirmed=True,
        )
        mock_client.start.assert_not_called()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_retry_failed_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = {"success_results": [], "failed_results": []}

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action"
        ) as mocked_choose_action, patch(
            "main.collect_retry_artwork_ids",
            return_value=["100"],
        ) as mocked_collect_retry_artwork_ids, patch(
            "main.process_artwork_batch",
            return_value=summary,
        ) as mocked_process_artwork_batch, patch(
            "main.console_service.show_batch_summary"
        ), patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(["retry-failed", "--error-type", "timeout", "--limit", "5"])

        mocked_choose_action.assert_not_called()
        mocked_collect_retry_artwork_ids.assert_called_once_with(
            mock_repository,
            error_type="timeout",
            limit=5,
            interactive=False,
        )
        mocked_process_artwork_batch.assert_called_once()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_crawl_following_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        mock_author_crawler = MagicMock()
        mock_author_crawler.collect_following_user_ids.return_value = ["123"]
        mock_author_crawler.collect_author_artwork_ids.return_value = ["100"]
        summary = {"success_results": [], "failed_results": []}
        selection = {
            "total_available_artwork_count": 1,
            "scanned_artwork_count": 1,
            "new_artwork_ids": ["100"],
            "retry_artwork_ids": [],
            "skipped_completed_ids": [],
            "candidate_artwork_ids": ["100"],
            "stopped_early": False,
            "stop_after_completed_streak": 15,
        }

        with patch("main.BrowserClient", return_value=mock_client), patch(
            "main.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("main.PixivLoginService", return_value=mock_login_service), patch(
            "main.AuthorCrawler",
            return_value=mock_author_crawler,
        ), patch(
            "main.configure_logging",
        ), patch(
            "main.choose_action"
        ) as mocked_choose_action, patch(
            "main.select_incremental_artwork_ids",
            return_value=selection,
        ) as mocked_select_incremental_artwork_ids, patch(
            "main.process_artwork_batch",
            return_value=summary,
        ) as mocked_process_artwork_batch, patch(
            "main.console_service.show_incremental_selection_summary"
        ), patch(
            "main.console_service.show_batch_summary"
        ), patch(
            "main.console_service.show_following_update_summary"
        ), patch(
            "main.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(["crawl-following", "--limit", "3", "--completed-streak-limit", "15"])

        mocked_choose_action.assert_not_called()
        mock_author_crawler.collect_following_user_ids.assert_called_once_with(limit=3)
        mocked_select_incremental_artwork_ids.assert_called_once_with(
            ["100"],
            mock_repository,
            completed_streak_limit=15,
        )
        mocked_process_artwork_batch.assert_called_once()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
