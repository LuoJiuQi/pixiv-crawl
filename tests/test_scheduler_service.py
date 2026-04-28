import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services import scheduler_service


class SchedulerServiceTestCase(unittest.TestCase):
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

    def test_run_scheduled_crawl_loop_runs_one_command_when_limited(self) -> None:
        commands: list[tuple[list[str], str]] = []

        def fake_command_runner(command: list[str], *, cwd: str) -> SimpleNamespace:
            commands.append((command, cwd))
            return SimpleNamespace(returncode=0)

        original_time = scheduler_service.settings.scheduled_run_time
        scheduler_service.settings.scheduled_run_time = "09:30"
        try:
            original_sleep_until = scheduler_service.sleep_until
            scheduler_service.sleep_until = lambda target, *, now_fn, sleep_fn: None
            try:
                result = scheduler_service.run_scheduled_crawl_loop(
                    stop_after_runs=1,
                    now_fn=lambda: datetime(2026, 4, 29, 8, 0, 0),
                    sleep_fn=lambda _seconds: None,
                    command_runner=fake_command_runner,
                    python_executable="python",
                )
            finally:
                scheduler_service.sleep_until = original_sleep_until
        finally:
            scheduler_service.settings.scheduled_run_time = original_time

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0][-1], "crawl-following")
