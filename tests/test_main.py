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


if __name__ == "__main__":
    unittest.main()
