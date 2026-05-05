"""
这个文件保留“失败清单导出”的兼容入口。

底层实现已经抽到更通用的 `record_exporter`，
这里继续保留原函数名，避免主流程和测试里已有调用全都要改。
"""

from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.record_exporter import build_record_export_path, export_records


def build_failure_export_path(
    export_dir: str | Path,
    *,
    error_type: str | None = None,
    file_format: str = "json",
) -> Path:
    """
    生成失败清单导出文件路径。
    """
    exported_path = build_record_export_path(
        export_dir,
        prefix="failed_records",
        status=error_type,
        file_format=file_format,
    )
    return exported_path


def export_failure_records(
    records: Sequence[DownloadRecord],
    output_path: str | Path,
    *,
    file_format: str = "json",
) -> Path:
    """
    导出失败记录，内部复用通用记录导出器。
    """
    return export_records(records, output_path, file_format=file_format)
