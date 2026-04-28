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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]: ...


def parse_scheduled_run_time(time_text: str) -> tuple[int, int]:
    hour_text, _, minute_text = time_text.partition(":")
    return int(hour_text), int(minute_text)


def compute_next_scheduled_run(now: datetime, time_text: str) -> datetime:
    hour, minute = parse_scheduled_run_time(time_text)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def sleep_until(target: datetime, *, now_fn: callable = datetime.now, sleep_fn: callable = time.sleep) -> None:
    while True:
        remaining_seconds = (target - now_fn()).total_seconds()
        if remaining_seconds <= 0:
            return
        sleep_fn(min(remaining_seconds, 60))


def build_scheduled_crawl_command(python_executable: str | None = None) -> list[str]:
    executable = python_executable or sys.executable
    return [executable, str(PROJECT_ROOT / "main.py"), "crawl-following"]


def run_scheduled_crawl_loop(
    *,
    stop_after_runs: int | None = None,
    now_fn: callable = datetime.now,
    sleep_fn: callable = time.sleep,
    command_runner: CommandRunner = lambda command, *, cwd: subprocess.run(command, cwd=cwd, check=False),
    python_executable: str | None = None,
) -> int:
    run_count = 0

    while stop_after_runs is None or run_count < stop_after_runs:
        now = now_fn()
        next_run = compute_next_scheduled_run(now, settings.scheduled_run_time)
        logger.info(
            "已开启定时抓取，下次将在 %s 执行关注列表更新。",
            next_run.strftime("%Y-%m-%d %H:%M"),
        )
        sleep_until(next_run, now_fn=now_fn, sleep_fn=sleep_fn)

        command = build_scheduled_crawl_command(python_executable=python_executable)
        logger.info("开始执行定时抓取命令：%s", command)
        result = command_runner(command, cwd=str(PROJECT_ROOT))
        logger.info("本次定时抓取已结束，退出码：%s", result.returncode)
        run_count += 1

    return 0
