"""
项目自定义异常体系。

替代原来分散在业务代码中的 RuntimeError 字符串，
让失败分类器可以基于类型（isinstance）而非字符串匹配做分类。
"""


class PixivCrawlError(Exception):
    """所有项目异常的基类。"""


class LoginError(PixivCrawlError):
    """登录相关错误：凭证缺失、reCAPTCHA、登录超时等。"""


class RateLimitError(PixivCrawlError):
    """被 Pixiv 限流，HTTP 429 或 Retry-After。"""


class Http5xxError(PixivCrawlError):
    """Pixiv 服务器 5xx 错误。"""


class TimeoutError(PixivCrawlError):
    """请求超时。"""


class ArtworkUnavailableError(PixivCrawlError):
    """作品不存在、已删除或不可见。"""


class DownloadError(PixivCrawlError):
    """下载阶段错误：空文件、大小不匹配、非图片内容。"""


class NetworkError(PixivCrawlError):
    """网络层错误：连接失败、DNS、代理、SSL 等。"""


class ParseError(PixivCrawlError):
    """解析错误：JSON 解析失败、Pydantic 校验失败。"""


class BrowserError(PixivCrawlError):
    """浏览器相关错误：启动失败、上下文丢失。"""


class InputError(PixivCrawlError):
    """用户输入错误：无效的作品 ID、作者 ID 格式错误。"""
