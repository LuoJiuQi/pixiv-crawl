"""
任务处理过程里会复用的结构化结果定义。

这些类型会同时被：
- 任务执行层
- 终端展示层
- 测试

共同使用，所以放到独立 schema 模块里，避免服务之间互相反向依赖。
"""

from typing import TypedDict


class ProcessResult(TypedDict):
    """
    描述“单个作品处理结果”应该长什么样。
    """

    artwork_id: str
    title: str
    author_name: str
    page_count: int
    download_count: int
    saved_html: str
    saved_json: str
    downloaded_files: list[str]
    skipped_download: bool
    skipped_by_db: bool


class FailedResult(TypedDict):
    """
    描述“单个失败结果”的最小信息。
    """

    artwork_id: str
    error: str


class BatchRunSummary(TypedDict):
    """
    描述“一整批任务跑完后的汇总结果”。
    """

    success_results: list[ProcessResult]
    failed_results: list[FailedResult]


class IncrementalSelectionResult(TypedDict):
    """
    描述“按作者增量更新时，筛选出来的任务集合”。
    """

    candidate_artwork_ids: list[str]
    new_artwork_ids: list[str]
    retry_artwork_ids: list[str]
    skipped_completed_ids: list[str]
    scanned_artwork_count: int
    total_available_artwork_count: int
    stopped_early: bool
    stop_after_completed_streak: int
