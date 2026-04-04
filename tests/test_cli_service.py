import unittest
from unittest.mock import MagicMock, patch

from app.services.cli_service import (
    choose_action,
    collect_retry_artwork_ids,
    parse_user_id,
    show_history,
)


class CliServiceTestCase(unittest.TestCase):
    def test_parse_user_id_supports_plain_numeric_id(self) -> None:
        self.assertEqual(parse_user_id("12345678"), "12345678")

    def test_parse_user_id_supports_users_url(self) -> None:
        raw_text = "https://www.pixiv.net/users/87654321"

        self.assertEqual(parse_user_id(raw_text), "87654321")

    def test_parse_user_id_supports_old_member_url(self) -> None:
        raw_text = "https://www.pixiv.net/member.php?id=11223344"

        self.assertEqual(parse_user_id(raw_text), "11223344")

    def test_parse_user_id_returns_empty_for_invalid_text(self) -> None:
        self.assertEqual(parse_user_id("hello world"), "")

    def test_choose_action_supports_following_mode(self) -> None:
        with patch("app.services.cli_service.console_service.show_menu") as mocked_show_menu, patch(
            "builtins.input",
            return_value="7",
        ):
            self.assertEqual(choose_action(), "crawl_following")

        mocked_show_menu.assert_called_once()

    def test_show_history_uses_console_summary_and_records(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {
            "completed": 3,
            "failed": 1,
            "pending": 0,
        }
        mock_repository.get_error_type_summary.return_value = {"download": 1}
        mock_repository.list_records.return_value = [
            {
                "artwork_id": "100",
                "status": "completed",
                "error_type": "",
                "title": "demo",
                "author_name": "author",
                "page_count": 1,
                "download_count": 1,
                "updated_at": "2026-04-04T12:00:00",
                "error_message": "",
            }
        ]

        with patch(
            "app.services.cli_service.collect_history_options",
            return_value=(None, None, 10),
        ), patch(
            "app.services.cli_service.console_service.show_summary"
        ) as mocked_show_summary, patch(
            "app.services.cli_service.console_service.show_records"
        ) as mocked_show_records:
            show_history(mock_repository)

        mocked_show_summary.assert_called()
        mocked_show_records.assert_called_once()

    def test_collect_retry_artwork_ids_shows_empty_failed_hint_via_console(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {"failed": 0}

        with patch(
            "app.services.cli_service.console_service.show_warning"
        ) as mocked_show_warning:
            artwork_ids = collect_retry_artwork_ids(mock_repository)

        self.assertEqual(artwork_ids, [])
        mocked_show_warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
