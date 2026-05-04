"""
任务处理过程里会复用的结构化结果定义。

这些类型会同时被：
- 任务执行层
- 终端展示层
- 测试

共同使用，所以放到独立 schema 模块里，避免服务之间互相反向依赖。

所有模型现统一使用 pydantic BaseModel，获得：
- 运行时字段校验
- 统一的 .model_dump() 序列化
- IDE 属性提示
"""

from pydantic import BaseModel, Field


class ProcessResult(BaseModel):
    """
    描述"单个作品处理结果"应该长什么样。
    """

    artwork_id: str = ""
    title: str = ""
    author_name: str = ""
    page_count: int = 0
    download_count: int = 0
    saved_html: str = ""
    saved_json: str = ""
    downloaded_files: list[str] = Field(default_factory=list)
    skipped_download: bool = False
    skipped_by_db: bool = False


class FailedResult(BaseModel):
    """
    描述"单个失败结果"的最小信息。
    """

    artwork_id: str = ""
    error: str = ""


class BatchRunSummary(BaseModel):
    """
    描述"一整批任务跑完后的汇总结果"。
    """

    success_results: list[ProcessResult] = Field(default_factory=list)
    failed_results: list[FailedResult] = Field(default_factory=list)


class IncrementalSelectionResult(BaseModel):
    """
    描述"按作者增量更新时，筛选出来的任务集合"。
    """

    candidate_artwork_ids: list[str] = Field(default_factory=list)
    new_artwork_ids: list[str] = Field(default_factory=list)
    retry_artwork_ids: list[str] = Field(default_factory=list)
    skipped_completed_ids: list[str] = Field(default_factory=list)
    scanned_artwork_count: int = 0
    total_available_artwork_count: int = 0
    stopped_early: bool = False
    stop_after_completed_streak: int = 0
