import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.services import doctor_service
from app.services.doctor_service import DoctorCheck, DoctorReport, get_doctor_exit_code, run_doctor, summarize_doctor_report


class DoctorServiceTestCase(unittest.TestCase):
    def test_run_doctor_reports_missing_credentials_and_state_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "images"
            db_path = Path(temp_dir) / "pixiv.db"
            log_path = Path(temp_dir) / "logs" / "app.log"
            state_path = Path(temp_dir) / "state" / "storage_state.json"

            mock_client = MagicMock()
            mock_client.state_manager.state_exists.return_value = False

            with patch.object(doctor_service.settings, "pixiv_username", ""), patch.object(
                doctor_service.settings,
                "pixiv_password",
                "",
            ), patch.object(
                doctor_service.settings,
                "download_dir",
                str(download_dir),
            ), patch.object(
                doctor_service.settings,
                "db_path",
                str(db_path),
            ), patch.object(
                doctor_service.settings,
                "log_path",
                str(log_path),
            ), patch.object(
                doctor_service.settings,
                "state_file",
                str(state_path),
            ), patch(
                "app.services.doctor_service.BrowserClient",
                return_value=mock_client,
            ):
                report = run_doctor()

        checks_by_name = {check.name: check for check in report.checks}
        self.assertEqual(checks_by_name["账号密码"].status, "warn")
        self.assertEqual(checks_by_name["登录态文件"].status, "warn")
        self.assertEqual(checks_by_name["浏览器启动"].status, "ok")
        self.assertEqual(checks_by_name["登录态有效性"].status, "skip")

    def test_run_doctor_reports_invalid_proxy_and_login_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "images"
            db_path = Path(temp_dir) / "pixiv.db"
            log_path = Path(temp_dir) / "logs" / "app.log"
            state_path = Path(temp_dir) / "state" / "storage_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

            mock_client = MagicMock()
            mock_client.state_manager.state_exists.return_value = True
            mock_login_service = MagicMock()
            mock_login_service.is_logged_in.return_value = False

            with patch.object(doctor_service.settings, "pixiv_username", "demo"), patch.object(
                doctor_service.settings,
                "pixiv_password",
                "secret",
            ), patch.object(
                doctor_service.settings,
                "proxy_server",
                "",
            ), patch.object(
                doctor_service.settings,
                "proxy_username",
                "proxy-user",
            ), patch.object(
                doctor_service.settings,
                "proxy_password",
                "",
            ), patch.object(
                doctor_service.settings,
                "download_dir",
                str(download_dir),
            ), patch.object(
                doctor_service.settings,
                "db_path",
                str(db_path),
            ), patch.object(
                doctor_service.settings,
                "log_path",
                str(log_path),
            ), patch.object(
                doctor_service.settings,
                "state_file",
                str(state_path),
            ), patch(
                "app.services.doctor_service.BrowserClient",
                return_value=mock_client,
            ), patch(
                "app.services.doctor_service.PixivLoginService",
                return_value=mock_login_service,
            ):
                report = run_doctor()

        checks_by_name = {check.name: check for check in report.checks}
        self.assertEqual(checks_by_name["账号密码"].status, "ok")
        self.assertEqual(checks_by_name["代理配置"].status, "warn")
        self.assertEqual(checks_by_name["登录态文件"].status, "ok")
        self.assertEqual(checks_by_name["登录态有效性"].status, "warn")

    def test_run_doctor_reports_browser_start_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "images"
            db_path = Path(temp_dir) / "pixiv.db"
            log_path = Path(temp_dir) / "logs" / "app.log"
            state_path = Path(temp_dir) / "state" / "storage_state.json"

            mock_client = MagicMock()
            mock_client.start.side_effect = RuntimeError("browser missing")

            with patch.object(doctor_service.settings, "download_dir", str(download_dir)), patch.object(
                doctor_service.settings,
                "db_path",
                str(db_path),
            ), patch.object(
                doctor_service.settings,
                "log_path",
                str(log_path),
            ), patch.object(
                doctor_service.settings,
                "state_file",
                str(state_path),
            ), patch(
                "app.services.doctor_service.BrowserClient",
                return_value=mock_client,
            ):
                report = run_doctor()

        checks_by_name = {check.name: check for check in report.checks}
        self.assertEqual(checks_by_name["浏览器启动"].status, "error")
        mock_client.close.assert_called_once()

    def test_summarize_doctor_report_counts_each_status(self) -> None:
        summary = summarize_doctor_report(
            DoctorReport(checks=[
                DoctorCheck(name="a", status="ok"),
                DoctorCheck(name="b", status="warn"),
                DoctorCheck(name="c", status="warn"),
                DoctorCheck(name="d", status="error"),
                DoctorCheck(name="e", status="skip"),
            ])
        )

        self.assertEqual(
            summary,
            {"ok": 1, "warn": 2, "error": 1, "skip": 1},
        )

    def test_get_doctor_exit_code_returns_zero_when_only_warn_without_strict(self) -> None:
        exit_code = get_doctor_exit_code(
            DoctorReport(checks=[
                DoctorCheck(name="a", status="ok"),
                DoctorCheck(name="b", status="warn"),
            ])
        )

        self.assertEqual(exit_code, 0)

    def test_get_doctor_exit_code_returns_one_for_warn_in_strict_mode(self) -> None:
        exit_code = get_doctor_exit_code(
            DoctorReport(checks=[
                DoctorCheck(name="a", status="warn"),
            ]),
            strict=True,
        )

        self.assertEqual(exit_code, 1)

    def test_get_doctor_exit_code_returns_one_when_error_exists(self) -> None:
        exit_code = get_doctor_exit_code(
            DoctorReport(checks=[
                DoctorCheck(name="a", status="error"),
                DoctorCheck(name="b", status="warn"),
            ])
        )

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
