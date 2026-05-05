"""
这个文件负责“把任务处理结果保存到 SQLite 数据库”。

你可以把它理解成项目的“任务台账”：
- 哪个作品处理过
- 处理结果是成功还是失败
- 标题、作者、页数是什么
- 下载了几张图
- 最近一次报错是什么

有了这层之后，批量任务就不只是“能跑”，
而是能记住历史结果，后面可以按记录跳过已完成作品。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, Field

from app.core.config import settings


class DownloadRecord(BaseModel):
    """下载记录数据模型。"""
    artwork_id: str = ""
    title: str = ""
    author_name: str = ""
    page_count: int = 0
    status: str = ""
    error_type: str = ""
    download_count: int = 0
    saved_html: str = ""
    saved_json: str = ""
    downloaded_files: list[str] = Field(default_factory=list)
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""


class DownloadRecordRepository:
    """
    专门管理下载记录表的仓库类。

    当前使用 SQLite，是因为它足够轻量：
    - 不需要单独启动数据库服务
    - 一个 `.db` 文件就能直接用
    - 很适合这种单机爬虫项目
    """

    def __init__(self, db_path: str | None = None):
        """
        保存数据库文件路径。
        """
        self.db_path = Path(db_path or settings.db_path)

    def _ensure_db_dir(self) -> None:
        """
        确保数据库文件所在目录存在。
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """
        创建一个 SQLite 连接。

        `row_factory` 设成 `sqlite3.Row` 后，
        查询结果就可以像字典一样按列名取值，代码会更好读。
        """
        self._ensure_db_dir()
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """
        提供一个会在使用结束后显式关闭的数据库连接。

        `sqlite3.Connection` 自带的上下文管理器只负责提交或回滚事务，
        并不会顺手关闭连接。在 Windows 上如果这里不主动 `close()`，
        临时数据库文件很容易一直被句柄占住，导致测试清理目录失败。
        """
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """
        初始化数据库表。

        这一步可以放心重复调用，
        因为 `CREATE TABLE IF NOT EXISTS` 本来就是幂等的。
        """
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS download_records (
                    artwork_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    author_name TEXT NOT NULL DEFAULT '',
                    page_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_type TEXT NOT NULL DEFAULT '',
                    download_count INTEGER NOT NULL DEFAULT 0,
                    saved_html TEXT NOT NULL DEFAULT '',
                    saved_json TEXT NOT NULL DEFAULT '',
                    downloaded_files_json TEXT NOT NULL DEFAULT '[]',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # 给旧数据库做一个轻量迁移。
            # 如果之前已经建过表，但还没有 `error_type` 列，
            # 就补一个默认空字符串的列进去。
            existing_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(download_records)").fetchall()
            }
            if "error_type" not in existing_columns:
                connection.execute(
                    """
                    ALTER TABLE download_records
                    ADD COLUMN error_type TEXT NOT NULL DEFAULT ''
                    """
                )

    def get_record(self, artwork_id: str) -> DownloadRecord | None:
        """
        根据作品 ID 获取一条记录。
        """
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    artwork_id,
                    title,
                    author_name,
                    page_count,
                    status,
                    error_type,
                    download_count,
                    saved_html,
                    saved_json,
                    downloaded_files_json,
                    error_message,
                    created_at,
                    updated_at
                FROM download_records
                WHERE artwork_id = ?
                """,
                (artwork_id,),
            ).fetchone()

        if row is None:
            return None

        return DownloadRecord(
            artwork_id=row["artwork_id"],
            title=row["title"],
            author_name=row["author_name"],
            page_count=row["page_count"],
            status=row["status"],
            error_type=row["error_type"],
            download_count=row["download_count"],
            saved_html=row["saved_html"],
            saved_json=row["saved_json"],
            downloaded_files=json.loads(row["downloaded_files_json"]),
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def is_artwork_completed(self, artwork_id: str) -> bool:
        """
        判断一个作品是否已经被完整处理过。

        当前标准很直接：
        - 数据库里有这条记录
        - 状态是 `completed`
        """
        record = self.get_record(artwork_id)
        return bool(record and record.status == "completed")

    def upsert_record(
        self,
        artwork_id: str,
        *,
        status: str,
        title: str = "",
        author_name: str = "",
        page_count: int = 0,
        error_type: str = "",
        download_count: int = 0,
        saved_html: str = "",
        saved_json: str = "",
        downloaded_files: list[str] | None = None,
        error_message: str = "",
    ) -> None:
        """
        新增或更新一条下载记录。

        之所以做成 upsert，而不是“只插入”或“只更新”，
        是因为一个作品可能会经历：
        - 第一次失败
        - 第二次成功
        - 后续再次被检测到已完成

        用 upsert 可以统一处理这些情况。
        """
        now = datetime.now().isoformat(timespec="seconds")
        downloaded_files_json = json.dumps(downloaded_files or [], ensure_ascii=False)

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO download_records (
                    artwork_id,
                    title,
                    author_name,
                    page_count,
                    status,
                    error_type,
                    download_count,
                    saved_html,
                    saved_json,
                    downloaded_files_json,
                    error_message,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artwork_id) DO UPDATE SET
                    title = excluded.title,
                    author_name = excluded.author_name,
                    page_count = excluded.page_count,
                    status = excluded.status,
                    error_type = excluded.error_type,
                    download_count = excluded.download_count,
                    saved_html = excluded.saved_html,
                    saved_json = excluded.saved_json,
                    downloaded_files_json = excluded.downloaded_files_json,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    artwork_id,
                    title,
                    author_name,
                    page_count,
                    status,
                    error_type,
                    download_count,
                    saved_html,
                    saved_json,
                    downloaded_files_json,
                    error_message,
                    now,
                    now,
                ),
            )

    def mark_failed(self, artwork_id: str, *, error_type: str, error_message: str) -> None:
        """
        仅更新失败状态和错误信息，不覆盖已有的作品元数据。

        这样可以避免作品曾经成功过、后来某次重试失败时，
        把标题、作者、下载文件列表等历史信息清空掉。
        """
        now = datetime.now().isoformat(timespec="seconds")

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO download_records (
                    artwork_id,
                    status,
                    error_type,
                    error_message,
                    created_at,
                    updated_at
                )
                VALUES (?, 'failed', ?, ?, ?, ?)
                ON CONFLICT(artwork_id) DO UPDATE SET
                    status = 'failed',
                    error_type = excluded.error_type,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    artwork_id,
                    error_type,
                    error_message,
                    now,
                    now,
                ),
            )

    def list_records(
        self,
        limit: int = 10,
        status: str | None = None,
        error_type: str | None = None,
        updated_before: str | None = None,
    ) -> list[DownloadRecord]:
        """
        按更新时间倒序列出最近的记录。

        参数说明：
        - `limit`：最多返回多少条
        - `status`：如果给了，就只看某一种状态，比如 `completed` 或 `failed`
        - `error_type`：如果给了，就进一步只看某一种失败类型
        - `updated_before`：如果给了，就只看更新时间早于某个时间点的记录
        """
        sql = """
            SELECT
                artwork_id,
                title,
                author_name,
                page_count,
                status,
                error_type,
                download_count,
                saved_html,
                saved_json,
                downloaded_files_json,
                error_message,
                created_at,
                updated_at
            FROM download_records
        """
        parameters: list[Any] = []
        conditions: list[str] = []

        if status:
            conditions.append("status = ?")
            parameters.append(status)

        if error_type:
            conditions.append("error_type = ?")
            parameters.append(error_type)

        if updated_before:
            conditions.append("updated_at < ?")
            parameters.append(updated_before)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY updated_at DESC, artwork_id DESC LIMIT ?"
        parameters.append(limit)

        with self._connection() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()

        records: list[DownloadRecord] = []
        for row in rows:
            records.append(
                DownloadRecord(
                    artwork_id=row["artwork_id"],
                    title=row["title"],
                    author_name=row["author_name"],
                    page_count=row["page_count"],
                    status=row["status"],
                    error_type=row["error_type"],
                    download_count=row["download_count"],
                    saved_html=row["saved_html"],
                    saved_json=row["saved_json"],
                    downloaded_files=json.loads(row["downloaded_files_json"]),
                    error_message=row["error_message"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )

        return records

    def delete_records(self, artwork_ids: list[str]) -> int:
        """
        根据作品 ID 列表删除记录，并返回实际删除的条数。
        """
        if not artwork_ids:
            return 0

        placeholders = ", ".join("?" for _ in artwork_ids)
        with self._connection() as connection:
            cursor = connection.execute(
                f"DELETE FROM download_records WHERE artwork_id IN ({placeholders})",
                tuple(artwork_ids),
            )
            return int(cursor.rowcount)

    def get_status_summary(self) -> dict[str, int]:
        """
        统计不同状态各有多少条记录。
        """
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM download_records
                GROUP BY status
                """
            ).fetchall()

        return {str(row["status"]): int(row["total"]) for row in rows}

    def get_error_type_summary(self, status: str | None = "failed") -> dict[str, int]:
        """
        统计不同错误类型各有多少条记录。

        默认只统计 `failed`，因为这个维度主要是给失败排查和失败重试用的。
        """
        sql = """
            SELECT error_type, COUNT(*) AS total
            FROM download_records
        """
        parameters: list[Any] = []

        if status:
            sql += " WHERE status = ?"
            parameters.append(status)

        sql += " GROUP BY error_type"

        with self._connection() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()

        summary: dict[str, int] = {}
        for row in rows:
            summary[str(row["error_type"] or "unknown")] = int(row["total"])

        return summary
