"""
这个文件负责“把数据库记录导出成文件”。

它比失败导出更通用：
- 可以导出失败记录
- 也可以导出即将归档的旧记录
"""

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from app.db.download_record_repository import DownloadRecord


def build_record_export_path(
    export_dir: str | Path,
    *,
    prefix: str,
    status: str | None = None,
    file_format: str = "json",
) -> Path:
    """
    生成记录导出文件路径。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_parts = [prefix]

    if status:
        name_parts.append(status)

    file_name = "_".join(name_parts) + f"_{timestamp}.{file_format}"
    return Path(export_dir) / file_name


def export_records(
    records: Sequence[DownloadRecord],
    output_path: str | Path,
    *,
    file_format: str = "json",
) -> Path:
    """
    把记录导出成文件。
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized_format = file_format.lower()
    if normalized_format == "json":
        path.write_text(
            json.dumps([rec.model_dump() for rec in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    if normalized_format == "txt":
        lines: list[str] = []
        for index, record in enumerate(records, start=1):
            lines.append(f"{index}. artwork_id = {record.artwork_id}")
            lines.append(f"   status = {record.status}")
            lines.append(f"   error_type = {record.error_type}")
            lines.append(f"   title = {record.title}")
            lines.append(f"   author_name = {record.author_name}")
            lines.append(f"   page_count = {record.page_count}")
            lines.append(f"   download_count = {record.download_count}")
            lines.append(f"   created_at = {record.created_at}")
            lines.append(f"   updated_at = {record.updated_at}")
            if record.error_message:
                lines.append(f"   error_message = {record.error_message}")
            lines.append("")

        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    raise ValueError(f"不支持的导出格式: {file_format}")
