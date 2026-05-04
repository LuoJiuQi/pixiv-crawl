import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.services import scheduler_service


class SchedulerServiceTestCase(unittest.TestCase):
    def _build_options(
        self,
        *,
        run_time: str = "09:30",
        retry_failed_enabled: bool = False,
        retry_failed_limit: int = 20,
        report_output_dir: str = "./data/exports/scheduled-reports",
    ) -> scheduler_service.ScheduledRunOptions:
        return scheduler_service.ScheduledRunOptions(
            run_time=run_time,
            retry_failed_enabled=retry_failed_enabled,
            retry_failed_limit=retry_failed_limit,
            report_output_dir=report_output_dir,
        )

    def test_compute_next_scheduled_run_uses_today_when_time_is_in_future(self) -> None:
        now = datetime(2026, 4, 29, 8, 0, 0)

        next_run = scheduler_service.compute_next_scheduled_run(now, "09:30")

        self.assertEqual(next_run, datetime(2026, 4, 29, 9, 30, 0))

    def test_compute_next_scheduled_run_uses_tomorrow_when_time_has_passed(self) -> None:
        now = datetime(2026, 4, 29, 8, 0, 0)

        next_run = scheduler_service.compute_next_scheduled_run(now, "07:30")

        self.assertEqual(next_run, datetime(2026, 4, 30, 7, 30, 0))

    def test_build_scheduled_crawl_command_targets_following_mode(self) -> None:
        command = scheduler_service.build_scheduled_crawl_command(python_executable="python")

        self.assertEqual(command[0], "python")
        self.assertEqual(command[-1], "crawl-following")
        self.assertTrue(command[1].endswith("main.py"))

    def test_build_scheduled_doctor_command_uses_strict_mode(self) -> None:
        command = scheduler_service.build_scheduled_doctor_command(python_executable="python")

        self.assertEqual(command[0], "python")
        self.assertEqual(command[-2:], ["doctor", "--strict"])
        self.assertTrue(command[1].endswith("main.py"))

    def test_build_scheduled_retry_command_uses_limit(self) -> None:
        command = scheduler_service.build_scheduled_retry_command(
            python_executable="python",
            limit=15,
        )

        self.assertEqual(command[0], "python")
        self.assertEqual(command[-3:], ["retry-failed", "--limit", "15"])
        self.assertTrue(command[1].endswith("main.py"))

    def test_build_scheduled_report_path_uses_timestamped_json_name(self) -> None:
        report_path = scheduler_service.build_scheduled_report_path(
            datetime(2026, 4, 29, 9, 30, 5),
            output_dir="./data/exports/reports",
        )

        normalized_path = report_path.replace("\\", "/")
        self.assertTrue(
            normalized_path.endswith("data/exports/reports/scheduled-run-20260429-093005.json")
        )

    def test_write_scheduled_run_report_writes_json_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report_path = scheduler_service.write_scheduled_run_report(
                {"status": "completed"},
                run_started_at=datetime(2026, 4, 29, 9, 30, 5),
                output_dir=temp_dir,
            )

            self.assertTrue(Path(report_path).exists())
            self.assertEqual(
                Path(report_path).read_text(encoding="utf-8"),
                '{\n  "status": "completed"\n}',
            )

    def test_run_scheduled_crawl_loop_runs_doctor_then_crawl_when_limited(self) -> None:
        commands: list[tuple[list[str], str]] = []
        written_reports: list[tuple[dict[str, object], datetime, str | None]] = []

        def fake_command_runner(command: list[str], *, cwd: str) -> SimpleNamespace:
            commands.append((command, cwd))
            return SimpleNamespace(returncode=0)

        result = scheduler_service.run_scheduled_crawl_loop(
            stop_after_runs=1,
            options=self._build_options(),
            now_fn=lambda: datetime(2026, 4, 29, 8, 0, 0),
            sleep_fn=lambda _seconds: None,
            sleep_until_fn=lambda target, *, now_fn, sleep_fn: None,
            command_runner=fake_command_runner,
            python_executable="python",
            report_writer=lambda report, *, run_started_at, output_dir=None: written_reports.append(
                (report, run_started_at, output_dir)
            )
            or "mock-report.json",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][0][-2:], ["doctor", "--strict"])
        self.assertEqual(commands[1][0][-1], "crawl-following")
        self.assertEqual(len(written_reports), 1)
        self.assertEqual(written_reports[0][0]["status"], "completed")

    def test_run_scheduled_crawl_loop_skips_crawl_when_doctor_fails(self) -> None:
        commands: list[tuple[list[str], str]] = []
        written_reports: list[dict[str, object]] = []

        def fake_command_runner(command: list[str], *, cwd: str) -> SimpleNamespace:
            commands.append((command, cwd))
            return_code = 1 if command[-2:] == ["doctor", "--strict"] else 0
            return SimpleNamespace(returncode=return_code)

        result = scheduler_service.run_scheduled_crawl_loop(
            stop_after_runs=1,
            options=self._build_options(),
            now_fn=lambda: datetime(2026, 4, 29, 8, 0, 0),
            sleep_fn=lambda _seconds: None,
            sleep_until_fn=lambda target, *, now_fn, sleep_fn: None,
            command_runner=fake_command_runner,
            python_executable="python",
            report_writer=lambda report, *, run_started_at, output_dir=None: written_reports.append(report)
            or "mock-report.json",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0][-2:], ["doctor", "--strict"])
        self.assertEqual(written_reports[0]["status"], "skipped_by_doctor")

    def test_run_scheduled_crawl_loop_runs_retry_after_successful_crawl_when_enabled(self) -> None:
        commands: list[tuple[list[str], str]] = []
        written_reports: list[dict[str, object]] = []

        def fake_command_runner(command: list[str], *, cwd: str) -> SimpleNamespace:
            commands.append((command, cwd))
            return SimpleNamespace(returncode=0)

        result = scheduler_service.run_scheduled_crawl_loop(
            stop_after_runs=1,
            options=self._build_options(retry_failed_enabled=True, retry_failed_limit=15),
            now_fn=lambda: datetime(2026, 4, 29, 8, 0, 0),
            sleep_fn=lambda _seconds: None,
            sleep_until_fn=lambda target, *, now_fn, sleep_fn: None,
            command_runner=fake_command_runner,
            python_executable="python",
            report_writer=lambda report, *, run_started_at, output_dir=None: written_reports.append(report)
            or "mock-report.json",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[0][0][-2:], ["doctor", "--strict"])
        self.assertEqual(commands[1][0][-1], "crawl-following")
        self.assertEqual(commands[2][0][-3:], ["retry-failed", "--limit", "15"])
        self.assertEqual(written_reports[0]["status"], "completed")
        self.assertEqual(written_reports[0]["retry_failed"]["returncode"], 0)

    def test_run_scheduled_crawl_loop_skips_retry_when_crawl_fails(self) -> None:
        commands: list[tuple[list[str], str]] = []
        written_reports: list[dict[str, object]] = []

        def fake_command_runner(command: list[str], *, cwd: str) -> SimpleNamespace:
            commands.append((command, cwd))
            if command[-1] == "crawl-following":
                return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)

        result = scheduler_service.run_scheduled_crawl_loop(
            stop_after_runs=1,
            options=self._build_options(retry_failed_enabled=True, retry_failed_limit=15),
            now_fn=lambda: datetime(2026, 4, 29, 8, 0, 0),
            sleep_fn=lambda _seconds: None,
            sleep_until_fn=lambda target, *, now_fn, sleep_fn: None,
            command_runner=fake_command_runner,
            python_executable="python",
            report_writer=lambda report, *, run_started_at, output_dir=None: written_reports.append(report)
            or "mock-report.json",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][0][-2:], ["doctor", "--strict"])
        self.assertEqual(commands[1][0][-1], "crawl-following")
        self.assertEqual(written_reports[0]["status"], "crawl_failed")
        self.assertEqual(written_reports[0]["retry_failed"]["reason"], "crawl_failed")
