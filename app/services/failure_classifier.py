"""
这个文件负责"给失败原因做分类"。

优先使用自定义异常的类型匹配（isinstance），
对标准库异常或 httpx 异常也做类型优先分类，
最后回退到字符串关键字匹配。
"""

import re

import httpx

from app.exceptions import (
    ArtworkUnavailableError,
    BrowserError,
    DownloadError,
    Http5xxError,
    InputError,
    LoginError,
    NetworkError,
    ParseError,
    PixivCrawlError,
    RateLimitError,
    TimeoutError,
)


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
    # 1) 自定义异常 — 类型匹配
    if isinstance(error, LoginError):
        return "login"
    if isinstance(error, RateLimitError):
        return "rate_limit"
    if isinstance(error, Http5xxError):
        return "http_5xx"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ArtworkUnavailableError):
        return "artwork_unavailable"
    if isinstance(error, DownloadError):
        return "download"
    if isinstance(error, NetworkError):
        return "network"
    if isinstance(error, ParseError):
        return "parse"
    if isinstance(error, BrowserError):
        return "browser"
    if isinstance(error, InputError):
        return "input"
    if isinstance(error, PixivCrawlError):
        return "unknown"

    # 2) 标准库 / httpx 异常 — 类型匹配
    if isinstance(error, httpx.HTTPStatusError):
        http_err: httpx.HTTPStatusError = error
        return _classify_http_status(http_err.response.status_code)

    if isinstance(error, httpx.TimeoutException):
        return "timeout"

    if isinstance(error, httpx.RequestError):
        return "network"

    # 3) 回退 — 字符串关键字匹配
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
            "下载结果为空文件",
            "下载文件大小不匹配",
            "content-length",
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
