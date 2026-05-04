"""
这个文件负责“内置定时抓取”。

设计原则很简单：
- 定时器本身只负责“等到时间”
- 真正的抓取仍然复用现有 CLI

这样调度层就很薄，不需要自己重新拼一遍浏览器、登录、抓取和落库流程。
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections.abc import Callable as CallableABC
from typing import Callable, Protocol

from app.core.config import settings
from app.core.logging_config import get_logger
from app.services.console_service import write_json_file

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, cwd: str) -> subprocess.CompletedProcess[bytes]: ...


@dataclass(frozen=True)
class ScheduledRunOptions:
    run_time: str
    retry_failed_enabled: bool
    retry_failed_limit: int
    report_output_dir: str


def parse_scheduled_run_time(time_text: str) -> tuple[int, int]:
    hour_text, _, minute_text = time_text.partition(":")
    return int(hour_text), int(minute_text)


def build_scheduled_run_options() -> ScheduledRunOptions:
    return ScheduledRunOptions(
        run_time=settings.scheduled_run_time,
        retry_failed_enabled=settings.scheduled_retry_failed_enabled,
        retry_failed_limit=settings.scheduled_retry_failed_limit,
        report_output_dir=settings.scheduled_report_output_dir,
    )


def compute_next_scheduled_run(now: datetime, time_text: str) -> datetime:
    hour, minute = parse_scheduled_run_time(time_text)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def sleep_until(target: datetime, *, now_fn: CallableABC[[], datetime] = datetime.now, sleep_fn: CallableABC[[float], None] = time.sleep) -> None:
    while True:
        remaining_seconds = (target - now_fn()).total_seconds()
        if remaining_seconds <= 0:
            return
        sleep_fn(min(remaining_seconds, 60))


def build_scheduled_crawl_command(python_executable: str | None = None) -> list[str]:
    executable = python_executable or sys.executable
    return [executable, str(PROJECT_ROOT / "main.py"), "crawl-following"]


def build_scheduled_doctor_command(python_executable: str | None = None) -> list[str]:
    executable = python_executable or sys.executable
    return [executable, str(PROJECT_ROOT / "main.py"), "doctor", "--strict"]


def build_scheduled_retry_command(
    *,
    python_executable: str | None = None,
    limit: int | None = None,
) -> list[str]:
    executable = python_executable or sys.executable
    retry_limit = settings.scheduled_retry_failed_limit if limit is None else limit
    return [
        executable,
        str(PROJECT_ROOT / "main.py"),
        "retry-failed",
        "--limit",
        str(retry_limit),
    ]


def build_scheduled_report_path(
    run_started_at: datetime,
    *,
    output_dir: str | None = None,
) -> str:
    report_dir = Path(output_dir or settings.scheduled_report_output_dir)
    report_name = f"scheduled-run-{run_started_at.strftime('%Y%m%d-%H%M%S')}.json"
    return str(report_dir / report_name)


def _build_command_report(
    command: list[str],
    *,
    returncode: int | None = None,
    skipped: bool = False,
    reason: str = "",
) -> dict[str, object]:
    return {
        "command": command,
        "returncode": returncode,
        "skipped": skipped,
        "reason": reason,
    }


def write_scheduled_run_report(
    report: dict[str, object],
    *,
    run_started_at: datetime,
    output_dir: str | None = None,
) -> str:
    target_path = build_scheduled_report_path(run_started_at, output_dir=output_dir)
    write_json_file(report, target_path)
    return target_path


def run_scheduled_crawl_loop(
    *,
    stop_after_runs: int | None = None,
    options: ScheduledRunOptions | None = None,
    now_fn: Callable[[], datetime] = datetime.now,
    sleep_fn: Callable[[float], None] = time.sleep,
    sleep_until_fn: Callable[..., None] = sleep_until,
    command_runner: CommandRunner = lambda command, *, cwd: subprocess.run(command, cwd=cwd, check=False),  # pyright: ignore[reportAssignmentType]
    python_executable: str | None = None,
    report_writer: Callable[..., str] = write_scheduled_run_report,
) -> int:
    resolved_options = options or build_scheduled_run_options()
    run_count = 0

    while stop_after_runs is None or run_count < stop_after_runs:
        now = now_fn()
        next_run = compute_next_scheduled_run(now, resolved_options.run_time)
        logger.info(
            "已开启定时抓取，下次将在 %s 执行关注列表更新。",
            next_run.strftime("%Y-%m-%d %H:%M"),
        )
        sleep_until_fn(next_run, now_fn=now_fn, sleep_fn=sleep_fn)
        run_started_at = now_fn()

        doctor_command = build_scheduled_doctor_command(python_executable=python_executable)
        logger.info("开始执行定时自检命令：%s", doctor_command)
        doctor_result = command_runner(doctor_command, cwd=str(PROJECT_ROOT))
        logger.info("本次定时自检已结束，退出码：%s", doctor_result.returncode)

        report: dict[str, object] = {
            "scheduled_time": resolved_options.run_time,
            "scheduled_for": next_run.isoformat(timespec="seconds"),
            "started_at": run_started_at.isoformat(timespec="seconds"),
            "doctor": _build_command_report(
                doctor_command,
                returncode=doctor_result.returncode,
            ),
            "crawl_following": _build_command_report(
                build_scheduled_crawl_command(python_executable=python_executable),
                skipped=True,
                reason="waiting_for_doctor",
            ),
            "retry_failed": _build_command_report(
                build_scheduled_retry_command(
                    python_executable=python_executable,
                    limit=resolved_options.retry_failed_limit,
                ),
                skipped=True,
                reason="disabled",
            ),
        }

        if doctor_result.returncode != 0:
            logger.warning("定时自检未通过，已跳过本轮关注列表更新。")
            report["status"] = "skipped_by_doctor"
            report_path = report_writer(
                report,
                run_started_at=run_started_at,
                output_dir=resolved_options.report_output_dir,
            )
            logger.info("本轮定时报告已写入：%s", report_path)
            run_count += 1
            continue

        command = build_scheduled_crawl_command(python_executable=python_executable)
        logger.info("开始执行定时抓取命令：%s", command)
        result = command_runner(command, cwd=str(PROJECT_ROOT))
        logger.info("本次定时抓取已结束，退出码：%s", result.returncode)
        report["crawl_following"] = _build_command_report(command, returncode=result.returncode, skipped=False)

        if result.returncode == 0 and resolved_options.retry_failed_enabled:
            retry_limit = resolved_options.retry_failed_limit
            if retry_limit > 0:
                retry_command = build_scheduled_retry_command(
                    python_executable=python_executable,
                    limit=retry_limit,
                )
                logger.info("开始执行定时失败重试命令：%s", retry_command)
                retry_result = command_runner(retry_command, cwd=str(PROJECT_ROOT))
                logger.info("本次定时失败重试已结束，退出码：%s", retry_result.returncode)
                report["retry_failed"] = _build_command_report(
                    retry_command,
                    returncode=retry_result.returncode,
                    skipped=False,
                )
                report["status"] = (
                    "completed" if retry_result.returncode == 0 else "completed_with_retry_failure"
                )
            else:
                logger.info("已开启定时失败重试，但重试上限为 0，本轮跳过失败补偿。")
                report["retry_failed"] = _build_command_report(
                    build_scheduled_retry_command(python_executable=python_executable, limit=retry_limit),
                    skipped=True,
                    reason="limit_is_zero",
                )
                report["status"] = "completed"
        elif result.returncode != 0 and resolved_options.retry_failed_enabled:
            logger.warning("定时抓取未成功结束，已跳过本轮失败补偿。")
            report["retry_failed"] = _build_command_report(
                build_scheduled_retry_command(
                    python_executable=python_executable,
                    limit=resolved_options.retry_failed_limit,
                ),
                skipped=True,
                reason="crawl_failed",
            )
            report["status"] = "crawl_failed"
        else:
            report["status"] = "completed" if result.returncode == 0 else "crawl_failed"
            if result.returncode == 0:
                report["retry_failed"] = _build_command_report(
                    build_scheduled_retry_command(
                        python_executable=python_executable,
                        limit=resolved_options.retry_failed_limit,
                    ),
                    skipped=True,
                    reason="disabled",
                )
            else:
                report["retry_failed"] = _build_command_report(
                    build_scheduled_retry_command(
                        python_executable=python_executable,
                        limit=resolved_options.retry_failed_limit,
                    ),
                    skipped=True,
                    reason="crawl_failed",
                )

        report_path = report_writer(
            report,
            run_started_at=run_started_at,
            output_dir=resolved_options.report_output_dir,
        )
        logger.info("本轮定时报告已写入：%s", report_path)
        run_count += 1

    return 0
