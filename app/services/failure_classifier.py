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


def classify_failure(error_message: str) -> str:
    """
    根据报错文本，归类出一个较稳定的错误类型。

    当前分类是偏实用型的：
    - login
    - timeout
    - artwork_unavailable
    - download
    - parse
    - network
    - input
    - browser
    - unknown
    """
    normalized = error_message.strip().lower()

    if not normalized:
        return "unknown"

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
