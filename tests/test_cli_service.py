import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.db.download_record_repository import DownloadRecordRepository
from app.services.cli_service import (
    archive_old_records,
    choose_action,
    collect_retry_artwork_ids,
    export_failed_records,
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

    def test_choose_action_supports_doctor_mode(self) -> None:
        with patch("app.services.cli_service.console_service.show_menu") as mocked_show_menu, patch(
            "builtins.input",
            return_value="8",
        ):
            self.assertEqual(choose_action(), "doctor")

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

    def test_show_history_skips_prompt_when_filters_are_provided(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {
            "completed": 3,
            "failed": 2,
            "pending": 0,
        }
        mock_repository.get_error_type_summary.return_value = {"timeout": 2}
        mock_repository.list_records.return_value = []

        with patch(
            "app.services.cli_service.collect_history_options"
        ) as mocked_collect_history_options, patch(
            "app.services.cli_service.console_service.show_summary"
        ), patch(
            "app.services.cli_service.console_service.show_records"
        ):
            show_history(
                mock_repository,
                status="failed",
                error_type="timeout",
                limit=5,
                prompt_for_filters=False,
            )

        mocked_collect_history_options.assert_not_called()
        mock_repository.list_records.assert_called_once_with(
            limit=5,
            status="failed",
            error_type="timeout",
        )

    def test_show_history_replays_http_5xx_filter_against_real_repository(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            repository.upsert_record("100", status="failed", error_type="http_5xx", error_message="503")
            repository.upsert_record("200", status="failed", error_type="rate_limit", error_message="429")
            repository.upsert_record("300", status="failed", error_type="timeout", error_message="timed out")

            with patch(
                "app.services.cli_service.console_service.show_summary"
            ), patch(
                "app.services.cli_service.console_service.show_records"
            ) as mocked_show_records:
                show_history(
                    repository,
                    status="failed",
                    error_type="http_5xx",
                    limit=10,
                    prompt_for_filters=False,
                )

        mocked_show_records.assert_called_once()
        shown_records = mocked_show_records.call_args.args[1]
        self.assertEqual([record["artwork_id"] for record in shown_records], ["100"])

    def test_collect_retry_artwork_ids_shows_empty_failed_hint_via_console(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {"failed": 0}

        with patch(
            "app.services.cli_service.console_service.show_warning"
        ) as mocked_show_warning:
            artwork_ids = collect_retry_artwork_ids(mock_repository)

        self.assertEqual(artwork_ids, [])
        mocked_show_warning.assert_called_once()

    def test_collect_retry_artwork_ids_uses_noninteractive_filters_without_prompting(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {"failed": 3}
        mock_repository.get_error_type_summary.return_value = {"timeout": 2}
        mock_repository.list_records.return_value = [
            {"artwork_id": "100"},
            {"artwork_id": "200"},
        ]

        with patch("app.services.cli_service.console_service.prompt") as mocked_prompt, patch(
            "app.services.cli_service.console_service.show_summary"
        ), patch(
            "app.services.cli_service.console_service.show_list"
        ):
            artwork_ids = collect_retry_artwork_ids(
                mock_repository,
                error_type="timeout",
                limit=2,
                interactive=False,
            )

        self.assertEqual(artwork_ids, ["100", "200"])
        mocked_prompt.assert_not_called()
        mock_repository.list_records.assert_called_once_with(
            limit=2,
            status="failed",
            error_type="timeout",
        )

    def test_collect_retry_artwork_ids_replays_rate_limit_filter_against_real_repository(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = DownloadRecordRepository(f"{temp_dir}/pixiv.db")
            repository.initialize()
            repository.upsert_record("100", status="failed", error_type="rate_limit", error_message="429")
            repository.upsert_record("200", status="failed", error_type="http_5xx", error_message="503")
            repository.upsert_record("300", status="failed", error_type="rate_limit", error_message="429")

            with patch(
                "app.services.cli_service.console_service.show_summary"
            ), patch(
                "app.services.cli_service.console_service.show_list"
            ):
                artwork_ids = collect_retry_artwork_ids(
                    repository,
                    error_type="rate_limit",
                    limit=10,
                    interactive=False,
                )

        self.assertEqual(artwork_ids, ["300", "100"])

    def test_export_failed_records_uses_noninteractive_arguments_without_prompting(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {"failed": 3}
        mock_repository.get_error_type_summary.return_value = {"timeout": 3}
        mock_repository.list_records.return_value = [{"artwork_id": "100"}]

        with patch("app.services.cli_service.console_service.prompt") as mocked_prompt, patch(
            "app.services.cli_service.console_service.show_summary"
        ), patch(
            "app.services.cli_service.console_service.show_success"
        ), patch(
            "app.services.cli_service.build_failure_export_path",
            return_value=Path("data/exports/failed_timeout.txt"),
        ) as mocked_build_path, patch(
            "app.services.cli_service.export_failure_records",
            return_value=Path("data/exports/failed_timeout.txt"),
        ) as mocked_export_records:
            export_failed_records(
                mock_repository,
                error_type="timeout",
                file_format="txt",
                interactive=False,
            )

        mocked_prompt.assert_not_called()
        mock_repository.list_records.assert_called_once_with(
            limit=3,
            status="failed",
            error_type="timeout",
        )
        mocked_build_path.assert_called_once_with(
            Path("./data/exports"),
            error_type="timeout",
            file_format="txt",
        )
        mocked_export_records.assert_called_once_with(
            [{"artwork_id": "100"}],
            Path("data/exports/failed_timeout.txt"),
            file_format="txt",
        )

    def test_archive_old_records_uses_noninteractive_arguments_without_prompting(self) -> None:
        mock_repository = MagicMock()
        mock_repository.get_status_summary.return_value = {"completed": 5, "failed": 1}
        mock_repository.list_records.return_value = [{"artwork_id": "100"}]
        mock_repository.delete_records.return_value = 1
        fixed_now = datetime(2026, 4, 20, 12, 0, 0)

        with patch("app.services.cli_service.console_service.prompt") as mocked_prompt, patch(
            "app.services.cli_service.console_service.show_summary"
        ), patch(
            "app.services.cli_service.console_service.show_list"
        ), patch(
            "app.services.cli_service.console_service.show_success"
        ), patch(
            "app.services.cli_service.datetime"
        ) as mocked_datetime, patch(
            "app.services.cli_service.build_record_export_path",
            return_value=Path("data/exports/archived_records_failed.txt"),
        ) as mocked_build_path, patch(
            "app.services.cli_service.export_records",
            return_value=Path("data/exports/archived_records_failed.txt"),
        ) as mocked_export_records:
            mocked_datetime.now.return_value = fixed_now

            archive_old_records(
                mock_repository,
                status="failed",
                days=7,
                limit=2,
                file_format="txt",
                interactive=False,
                confirmed=True,
            )

        mocked_prompt.assert_not_called()
        mock_repository.list_records.assert_called_once_with(
            limit=2,
            status="failed",
            updated_before="2026-04-13T12:00:00",
        )
        mocked_build_path.assert_called_once_with(
            Path("./data/exports"),
            prefix="archived_records",
            status="failed",
            file_format="txt",
        )
        mocked_export_records.assert_called_once_with(
            [{"artwork_id": "100"}],
            Path("data/exports/archived_records_failed.txt"),
            file_format="txt",
        )
        mock_repository.delete_records.assert_called_once_with(["100"])


if __name__ == "__main__":
    unittest.main()
