"""
这个文件负责“给失败原因做分类”。

原始异常文本虽然有用，但它通常比较散：
- 有的写中文
- 有的写英文
- 有的带 URL
- 有的只是一句超时

所以这里额外做一层“错误类型归类”，
方便后面查看历史记录、筛选问题和决定优先排查方向。
"""

import re

import httpx


def _classify_http_status(status_code: int) -> str:
    if status_code == 429:
        return "rate_limit"
    if 500 <= status_code <= 599:
        return "http_5xx"
    if status_code in {401, 403, 404, 410, 451}:
        return "artwork_unavailable"
    return "network"


def classify_failure(error: str | BaseException) -> str:
    """
    根据报错文本，归类出一个较稳定的错误类型。

    当前分类是偏实用型的：
    - login
    - rate_limit
    - http_5xx
    - timeout
    - artwork_unavailable
    - download
    - network
    - parse
    - input
    - browser
    - unknown
    """
    if isinstance(error, httpx.HTTPStatusError):
        return _classify_http_status(error.response.status_code)

    if isinstance(error, httpx.TimeoutException):
        return "timeout"

    if isinstance(error, httpx.RequestError):
        return "network"

    normalized = str(error).strip().lower()

    if not normalized:
        return "unknown"

    if any(
        keyword in normalized
        for keyword in (
            "429",
            "too many requests",
            "rate limit",
            "rate limited",
            "retry-after",
            "限流",
            "请求过多",
        )
    ):
        return "rate_limit"

    if any(
        keyword in normalized
        for keyword in (
            "internal server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "server unavailable",
        )
    ) or re.search(r"\b5\d\d\b", normalized):
        return "http_5xx"

    if any(keyword in normalized for keyword in ("timeout", "超时")):
        return "timeout"

    if any(
        keyword in normalized
        for keyword in (
            "recaptcha",
            "验证码",
            "登录",
            "账号密码",
            "pixiv 自动登录",
            "登录状态",
        )
    ):
        return "login"

    if any(
        keyword in normalized
        for keyword in (
            "未成功进入目标作品页",
            "作品不存在",
            "作品已删除",
            "作品不可见",
            "/artworks/",
        )
    ):
        return "artwork_unavailable"

    if any(
        keyword in normalized
        for keyword in (
            "未找到可下载图片",
            "下载结果不是图片内容",
            "image/",
            "pximg",
            "download",
        )
    ):
        return "download"

    if any(
        keyword in normalized
        for keyword in (
            "__next_data__",
            "解析",
            "parser",
            "jsondecodeerror",
            "pydantic",
        )
    ):
        return "parse"

    if any(
        keyword in normalized
        for keyword in (
            "403",
            "404",
            "cloudflare",
            "connection",
            "proxy",
            "ssl",
            "dns",
            "network",
            "net::",
        )
    ):
        return "network"

    if any(
        keyword in normalized
        for keyword in (
            "没有识别到有效的作品 id",
            "输入",
        )
    ):
        return "input"

    if any(
        keyword in normalized
        for keyword in (
            "浏览器尚未启动",
            "浏览器上下文",
            "playwright",
            "chromium",
        )
    ):
        return "browser"

    return "unknown"
