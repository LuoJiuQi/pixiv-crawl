import unittest
from unittest.mock import MagicMock, patch

from app.schemas.task import BatchRunSummary, FailedResult, IncrementalSelectionResult, ProcessResult
from app.services.doctor_service import DoctorCheck, DoctorReport
import main
from app import application as app_module


class MainInputParsingTestCase(unittest.TestCase):
    def test_main_stops_when_login_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = False

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.login_and_save_state.return_value = MagicMock(success=False)

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.configure_logging",
        ) as mocked_configure_logging, patch(
            "app.application.choose_action",
            return_value="crawl",
        ), patch("app.application.collect_artwork_ids", return_value=["100"]), patch(
            "app.application.process_artwork_batch"
        ) as mocked_batch, patch.object(
            app_module,
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

    def test_main_configures_console_encoding_before_logging(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = False
        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.login_and_save_state.return_value = MagicMock(success=False)

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.console_service.configure_console_encoding",
        ) as mocked_configure_console_encoding, patch(
            "app.application.configure_logging",
        ) as mocked_configure_logging, patch(
            "app.application.choose_action",
            return_value="crawl",
        ), patch("app.application.collect_artwork_ids", return_value=["100"]):
            main.main()

        mocked_configure_console_encoding.assert_called_once()
        mocked_configure_logging.assert_called_once()

    def test_main_uses_console_pause_before_exit_after_batch(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = BatchRunSummary(success_results=[], failed_results=[])

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action",
            return_value="crawl",
        ), patch("app.application.collect_artwork_ids", return_value=["100"]), patch(
            "app.application.process_artwork_batch",
            return_value=summary,
        ), patch(
            "app.application.console_service.show_batch_summary"
        ), patch(
            "app.application.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main()

        mocked_pause.assert_called_once()
        mock_client.close.assert_called_once()

    def test_main_enters_scheduled_mode_when_enabled_without_arguments(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.settings.scheduled_run_enabled", True), patch(
            "app.application.console_service.configure_console_encoding",
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.run_scheduled_crawl_loop",
            return_value=0,
        ) as mocked_run_scheduled_crawl_loop, patch(
            "app.application.choose_action"
        ) as mocked_choose_action:
            exit_code = main.main()

        mocked_run_scheduled_crawl_loop.assert_called_once()
        mocked_choose_action.assert_not_called()
        mock_repository.initialize.assert_not_called()
        mock_client.start.assert_not_called()
        self.assertEqual(exit_code, 0)

    def test_main_routes_batch_summary_to_console_layer(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = BatchRunSummary(
            success_results=[
                ProcessResult(artwork_id="100", skipped_download=False, skipped_by_db=False),
            ],
            failed_results=[FailedResult(artwork_id="200", error="timeout")],
        )

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action",
            return_value="crawl",
        ), patch("app.application.collect_artwork_ids", return_value=["100"]), patch(
            "app.application.process_artwork_batch",
            return_value=summary,
        ), patch(
            "app.application.console_service.show_batch_summary"
        ) as mocked_show_batch_summary, patch(
            "app.application.console_service.pause_before_exit"
        ):
            main.main()

        mocked_show_batch_summary.assert_called_once_with(summary)

    def test_main_logs_long_artwork_id_list_at_debug_level(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = BatchRunSummary(success_results=[], failed_results=[])

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action",
            return_value="crawl",
        ), patch("app.application.collect_artwork_ids", return_value=["100", "200"]), patch(
            "app.application.process_artwork_batch",
            return_value=summary,
        ), patch(
            "app.application.console_service.show_batch_summary"
        ), patch(
            "app.application.console_service.pause_before_exit"
        ), patch.object(
            app_module,
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
        summary = BatchRunSummary(success_results=[], failed_results=[])

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action"
        ) as mocked_choose_action, patch(
            "app.application.collect_artwork_ids"
        ) as mocked_collect_artwork_ids, patch(
            "app.application.process_artwork_batch",
            return_value=summary,
        ), patch(
            "app.application.console_service.show_batch_summary"
        ), patch(
            "app.application.console_service.pause_before_exit"
        ) as mocked_pause:
            main.main(["crawl", "100", "200"])

        mocked_choose_action.assert_not_called()
        mocked_collect_artwork_ids.assert_not_called()
        mocked_pause.assert_not_called()
        mock_client.close.assert_called_once()

    def test_main_routes_history_cli_arguments_without_prompting_for_filters(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action"
        ) as mocked_choose_action, patch(
            "app.application.show_history"
        ) as mocked_show_history, patch(
            "app.application.console_service.pause_before_exit"
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

    def test_main_routes_doctor_command_without_initializing_database(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = DoctorReport(checks=[
            DoctorCheck(name="浏览器启动", status="ok", detail="ok"),
        ])

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.run_doctor",
            return_value=report,
        ) as mocked_run_doctor, patch(
            "app.application.summarize_doctor_report",
            return_value={"ok": 1, "warn": 0, "error": 0, "skip": 0},
        ) as mocked_summarize, patch(
            "app.application.get_doctor_exit_code",
            return_value=0,
        ) as mocked_get_exit_code, patch(
            "app.application.console_service.show_doctor_report"
        ) as mocked_show_doctor_report, patch(
            "app.application.console_service.show_summary"
        ) as mocked_show_summary, patch(
            "app.application.console_service.pause_before_exit"
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

    def test_main_routes_doctor_strict_mode_to_nonzero_exit_code(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = DoctorReport(checks=[
            DoctorCheck(name="账号密码", status="warn", detail="missing"),
        ])

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.run_doctor",
            return_value=report,
        ), patch(
            "app.application.summarize_doctor_report",
            return_value={"ok": 0, "warn": 1, "error": 0, "skip": 0},
        ), patch(
            "app.application.get_doctor_exit_code",
            return_value=1,
        ) as mocked_get_exit_code, patch(
            "app.application.console_service.show_doctor_report"
        ), patch(
            "app.application.console_service.show_summary"
        ), patch(
            "app.application.console_service.pause_before_exit"
        ) as mocked_pause:
            exit_code = main.main(["doctor", "--strict"])

        mocked_get_exit_code.assert_called_once_with(report, strict=True)
        self.assertEqual(exit_code, 1)
        mocked_pause.assert_not_called()
        mock_repository.initialize.assert_not_called()

    def test_main_routes_doctor_json_output_without_human_summary(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = DoctorReport(checks=[
            DoctorCheck(name="浏览器启动", status="ok", detail="ok"),
            DoctorCheck(name="登录态有效性", status="skip", detail="missing"),
        ])
        summary = {"ok": 1, "warn": 0, "error": 0, "skip": 1}

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.run_doctor",
            return_value=report,
        ), patch(
            "app.application.summarize_doctor_report",
            return_value=summary,
        ), patch(
            "app.application.get_doctor_exit_code",
            return_value=0,
        ) as mocked_get_exit_code, patch(
            "app.application.console_service.show_json"
        ) as mocked_show_json, patch(
            "app.application.console_service.show_doctor_report"
        ) as mocked_show_doctor_report, patch(
            "app.application.console_service.show_summary"
        ) as mocked_show_summary:
            exit_code = main.main(["doctor", "--json"])

        mocked_get_exit_code.assert_called_once_with(report, strict=False)
        mocked_show_json.assert_called_once_with(
            {
                "checks": [check.model_dump() for check in report.checks],
                "summary": summary,
                "strict": False,
                "exit_code": 0,
            }
        )
        mocked_show_doctor_report.assert_not_called()
        mocked_show_summary.assert_not_called()
        self.assertEqual(exit_code, 0)
        mock_repository.initialize.assert_not_called()

    def test_main_routes_doctor_output_file_with_human_summary(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = DoctorReport(checks=[
            DoctorCheck(name="浏览器启动", status="ok", detail="ok"),
        ])
        summary = {"ok": 1, "warn": 0, "error": 0, "skip": 0}

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.run_doctor",
            return_value=report,
        ), patch(
            "app.application.summarize_doctor_report",
            return_value=summary,
        ), patch(
            "app.application.get_doctor_exit_code",
            return_value=0,
        ), patch(
            "app.application.console_service.write_json_file"
        ) as mocked_write_json_file, patch(
            "app.application.console_service.show_doctor_report"
        ) as mocked_show_doctor_report, patch(
            "app.application.console_service.show_summary"
        ) as mocked_show_summary, patch(
            "app.application.console_service.show_success"
        ) as mocked_show_success, patch(
            "app.application.console_service.show_json"
        ) as mocked_show_json:
            exit_code = main.main(["doctor", "--output", "data/doctor.json"])

        mocked_write_json_file.assert_called_once_with(
            {
                "checks": [check.model_dump() for check in report.checks],
                "summary": summary,
                "strict": False,
                "exit_code": 0,
            },
            "data/doctor.json",
        )
        mocked_show_doctor_report.assert_called_once_with(report)
        mocked_show_summary.assert_called_once_with(
            "自检结果汇总",
            [("ok", 1), ("warn", 0), ("error", 0), ("skip", 0)],
        )
        mocked_show_success.assert_called_once_with("自检结果已写入：data/doctor.json")
        mocked_show_json.assert_not_called()
        self.assertEqual(exit_code, 0)
        mock_repository.initialize.assert_not_called()

    def test_main_routes_doctor_json_output_can_write_file_at_same_time(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()
        report = DoctorReport(checks=[
            DoctorCheck(name="浏览器启动", status="ok", detail="ok"),
        ])
        summary = {"ok": 1, "warn": 0, "error": 0, "skip": 0}

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.run_doctor",
            return_value=report,
        ), patch(
            "app.application.summarize_doctor_report",
            return_value=summary,
        ), patch(
            "app.application.get_doctor_exit_code",
            return_value=0,
        ), patch(
            "app.application.console_service.write_json_file"
        ) as mocked_write_json_file, patch(
            "app.application.console_service.show_json"
        ) as mocked_show_json, patch(
            "app.application.console_service.show_doctor_report"
        ) as mocked_show_doctor_report, patch(
            "app.application.console_service.show_summary"
        ) as mocked_show_summary, patch(
            "app.application.console_service.show_success"
        ) as mocked_show_success:
            exit_code = main.main(["doctor", "--json", "--output", "data/doctor.json"])

        payload = {
            "checks": [check.model_dump() for check in report.checks],
            "summary": summary,
            "strict": False,
            "exit_code": 0,
        }
        mocked_write_json_file.assert_called_once_with(payload, "data/doctor.json")
        mocked_show_json.assert_called_once_with(payload)
        mocked_show_doctor_report.assert_not_called()
        mocked_show_summary.assert_not_called()
        mocked_show_success.assert_not_called()
        self.assertEqual(exit_code, 0)
        mock_repository.initialize.assert_not_called()

    def test_main_routes_export_failed_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action"
        ) as mocked_choose_action, patch(
            "app.application.export_failed_records"
        ) as mocked_export_failed_records, patch(
            "app.application.console_service.pause_before_exit"
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

    def test_main_routes_archive_records_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_repository = MagicMock()

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action"
        ) as mocked_choose_action, patch(
            "app.application.archive_old_records"
        ) as mocked_archive_old_records, patch(
            "app.application.console_service.pause_before_exit"
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

    def test_main_routes_retry_failed_cli_arguments_without_prompting(self) -> None:
        mock_client = MagicMock()
        mock_client.state_manager.state_exists.return_value = True

        mock_repository = MagicMock()
        mock_login_service = MagicMock()
        mock_login_service.is_logged_in.return_value = True
        summary = BatchRunSummary(success_results=[], failed_results=[])

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action"
        ) as mocked_choose_action, patch(
            "app.application.collect_retry_artwork_ids",
            return_value=["100"],
        ) as mocked_collect_retry_artwork_ids, patch(
            "app.application.process_artwork_batch",
            return_value=summary,
        ) as mocked_process_artwork_batch, patch(
            "app.application.console_service.show_batch_summary"
        ), patch(
            "app.application.console_service.pause_before_exit"
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
        summary = BatchRunSummary(success_results=[], failed_results=[])
        selection = IncrementalSelectionResult(
            total_available_artwork_count=1,
            scanned_artwork_count=1,
            new_artwork_ids=["100"],
            retry_artwork_ids=[],
            skipped_completed_ids=[],
            candidate_artwork_ids=["100"],
            stopped_early=False,
            stop_after_completed_streak=15,
        )

        with patch("app.application.BrowserClient", return_value=mock_client), patch(
            "app.application.DownloadRecordRepository",
            return_value=mock_repository,
        ), patch("app.application.PixivLoginService", return_value=mock_login_service), patch(
            "app.application.AuthorCrawler",
            return_value=mock_author_crawler,
        ), patch(
            "app.application.configure_logging",
        ), patch(
            "app.application.choose_action"
        ) as mocked_choose_action, patch(
            "app.application.select_incremental_artwork_ids",
            return_value=selection,
        ) as mocked_select_incremental_artwork_ids, patch(
            "app.application.process_artwork_batch",
            return_value=summary,
        ) as mocked_process_artwork_batch, patch(
            "app.application.console_service.show_incremental_selection_summary"
        ), patch(
            "app.application.console_service.show_batch_summary"
        ), patch(
            "app.application.console_service.show_following_update_summary"
        ), patch(
            "app.application.console_service.pause_before_exit"
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
