"""
这个文件定义“作品数据的标准格式”。

以前解析器返回普通字典也能工作，
但随着项目变大，字典会越来越难维护：
- 字段名容易拼错
- 别人不知道应该有哪些字段
- 测试和数据库对接时不够稳定

所以这里用 Pydantic 定义一个明确的数据模型。
"""

from typing import Any

from pydantic import BaseModel, Field


class ArtworkInfo(BaseModel):
    """
    用来描述“一条 Pixiv 作品信息”应该长什么样。
    """

    # 页面 `<title>` 内容。
    title: str = ""

    # Open Graph 标题，通常给社交平台预览使用。
    og_title: str = ""

    # Open Graph 图片地址。
    og_image: str = ""

    # 页面描述信息。
    description: str = ""

    # 作品详情页的标准地址。
    canonical_url: str = ""

    # 作品 ID。
    artwork_id: str = ""

    # 作者用户 ID。
    # 注意：有些页面里可能拿不到稳定线索，所以允许为空字符串。
    user_id: str = ""

    # 作者名字。
    author_name: str = ""

    # 标签列表。
    # 用 `default_factory=list` 可以避免多个实例共享同一个默认列表对象。
    tags: list[str] = Field(default_factory=list)

    # 作品页数。单图作品通常是 1。
    page_count: int = 0

    # 从页面中提取到的“可能图片地址”列表。
    possible_image_urls: list[str] = Field(default_factory=list)

    # 是否成功解析到 `__NEXT_DATA__`。
    has_next_data: bool = False

    # 调试信息：记录结构化数据里命中的关键字段。
    next_data_hits: list[tuple[str, Any]] = Field(default_factory=list)
