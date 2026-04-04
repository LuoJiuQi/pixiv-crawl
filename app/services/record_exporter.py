"""
这个文件负责“把数据库记录导出成文件”。

它比失败导出更通用：
- 可以导出失败记录
- 也可以导出即将归档的旧记录
"""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


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
    records: Sequence[Mapping[str, Any]],
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
        path.write_text(json.dumps(list(records), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    if normalized_format == "txt":
        lines: list[str] = []
        for index, record in enumerate(records, start=1):
            lines.append(f"{index}. artwork_id = {record.get('artwork_id', '')}")
            lines.append(f"   status = {record.get('status', '')}")
            lines.append(f"   error_type = {record.get('error_type', '')}")
            lines.append(f"   title = {record.get('title', '')}")
            lines.append(f"   author_name = {record.get('author_name', '')}")
            lines.append(f"   page_count = {record.get('page_count', '')}")
            lines.append(f"   download_count = {record.get('download_count', '')}")
            lines.append(f"   created_at = {record.get('created_at', '')}")
            lines.append(f"   updated_at = {record.get('updated_at', '')}")
            if record.get("error_message"):
                lines.append(f"   error_message = {record.get('error_message', '')}")
            lines.append("")

        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path

    raise ValueError(f"不支持的导出格式: {file_format}")
