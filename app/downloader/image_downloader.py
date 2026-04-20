"""
这个文件保留下载器对外门面。

它现在主要负责：
1. 组合下载计划器和本地路径构建器
2. 复用浏览器上下文里的登录态和 cookies
3. 构造请求头并执行真实图片下载
4. 保持任务层依赖的公开接口稳定
"""

from pathlib import Path
import time
from urllib.parse import quote
from urllib.parse import urlparse

import httpx

from app.browser.client import BrowserClient
from app.core.config import settings
from app.core.logging_config import get_logger
from app.downloader.download_path_builder import DownloadPathBuilder
from app.downloader.download_planner import DownloadPlanner, PreparedArtworkDownload
from app.schemas.artwork import ArtworkInfo


logger = get_logger(__name__)


class PixivImageDownloader:
    """
    基于当前浏览器登录态下载 Pixiv 作品图片。
    """

    # 兜底浏览器标识。
    # 如果没法从当前页面动态读取 `navigator.userAgent`，就用这个默认值。
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
    RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(self, client: BrowserClient, download_dir: str | None = None):
        """
        保存浏览器客户端和下载目录。
        """
        self.client = client
        self.download_dir = Path(download_dir or settings.download_dir)
        self.path_builder = DownloadPathBuilder(self.download_dir)
        self.planner = DownloadPlanner(client)

    def _get_request_headers(self, artwork: ArtworkInfo) -> dict[str, str]:
        """
        构造下载图片时需要的请求头。

        其中最关键的是 `Referer`，Pixiv 很看重这个字段。
        """
        user_agent = self.DEFAULT_USER_AGENT

        try:
            # 优先从真实浏览器环境里读取当前 user-agent。
            user_agent = self.client.get_page().evaluate("() => navigator.userAgent")
        except Exception:
            # 如果读取失败，就静默回退到默认值。
            logger.debug(
                "读取 navigator.userAgent 失败，回退默认值：%s",
                artwork.artwork_id,
                exc_info=True,
            )
            pass

        referer = artwork.canonical_url or f"https://www.pixiv.net/artworks/{artwork.artwork_id}"

        return {
            "Referer": referer,
            "User-Agent": user_agent,
        }

    def _build_cookies(self) -> httpx.Cookies:
        """
        从浏览器上下文里提取 cookies，并转换成 `httpx` 可用格式。
        """
        cookies = httpx.Cookies()

        for cookie in self.client.get_context().cookies():
            cookie_name = cookie.get("name")
            cookie_value = cookie.get("value")
            if not isinstance(cookie_name, str) or not isinstance(cookie_value, str):
                continue

            cookie_path = cookie.get("path")
            path = cookie_path if isinstance(cookie_path, str) and cookie_path else "/"
            cookie_domain = cookie.get("domain")

            if isinstance(cookie_domain, str) and cookie_domain:
                cookies.set(
                    cookie_name,
                    cookie_value,
                    domain=cookie_domain,
                    path=path,
                )
                continue

            cookies.set(
                cookie_name,
                cookie_value,
                path=path,
            )

        return cookies

    def _build_proxy_url(self) -> str | None:
        """
        生成 `httpx` 可直接使用的代理地址。

        代理如果不需要认证，直接返回原始地址。
        如果需要认证，就把账号密码拼进 URL。
        """
        proxy_server = settings.proxy_server.strip()
        if not proxy_server:
            return None

        proxy_username = settings.proxy_username.strip()
        proxy_password = settings.proxy_password.strip()
        if not proxy_username:
            return proxy_server

        parsed = urlparse(proxy_server)
        if not parsed.scheme or not parsed.hostname:
            return proxy_server

        auth = quote(proxy_username, safe="")
        if proxy_password:
            auth += f":{quote(proxy_password, safe='')}"

        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"

        return f"{parsed.scheme}://{auth}@{host}"

    def _build_http_client(
        self,
        headers: dict[str, str],
        cookies: httpx.Cookies,
        proxy_url: str | None,
    ) -> httpx.Client:
        client_kwargs: dict[str, object] = {
            "headers": headers,
            "cookies": cookies,
            "follow_redirects": True,
            "timeout": settings.download_timeout_seconds,
        }
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        return httpx.Client(**client_kwargs)

    def _is_retryable_download_error(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in self.RETRYABLE_STATUS_CODES

        return isinstance(exc, httpx.RequestError)

    def _get_retry_delay(self, attempt_index: int) -> float:
        base_delay = max(0.0, settings.download_retry_backoff_seconds)
        return base_delay * (2 ** (attempt_index - 1))

    def _remove_file_if_exists(self, path: Path | None) -> None:
        if path is None:
            return

        try:
            path.unlink(missing_ok=True)
        except TypeError:
            if path.exists():
                path.unlink()

    def _download_page_with_retry(
        self,
        http_client: httpx.Client,
        artwork: ArtworkInfo,
        page_index: int,
        total_pages: int,
        url: str,
    ) -> str:
        max_attempts = max(1, settings.download_retry_attempts)

        for attempt_index in range(1, max_attempts + 1):
            temp_output_path: Path | None = None

            try:
                with http_client.stream("GET", url) as response:
                    response.raise_for_status()

                    content_type = response.headers.get("content-type", "")
                    if "image/" not in content_type:
                        raise RuntimeError(
                            f"下载结果不是图片内容，作品 ID: {artwork.artwork_id}, URL: {url}"
                        )

                    # 有些图片地址会跳转，所以这里用最终响应 URL 来重新推断扩展名。
                    output_path = self._build_output_path(
                        artwork,
                        page_index,
                        str(response.url),
                        content_type=content_type,
                        total_pages=total_pages,
                    )
                    temp_output_path = output_path.with_name(f"{output_path.name}.part")

                    with temp_output_path.open("wb") as output_file:
                        for chunk in response.iter_bytes():
                            if chunk:
                                output_file.write(chunk)

                    temp_output_path.replace(output_path)
                    return str(output_path)
            except Exception as exc:
                self._remove_file_if_exists(temp_output_path)

                if not self._is_retryable_download_error(exc) or attempt_index >= max_attempts:
                    raise

                retry_delay = self._get_retry_delay(attempt_index)
                logger.warning(
                    "下载作品 %s 第 %s/%s 页失败，%.1f 秒后开始第 %s/%s 次尝试：%s",
                    artwork.artwork_id,
                    page_index + 1,
                    total_pages,
                    retry_delay,
                    attempt_index + 1,
                    max_attempts,
                    exc,
                )
                time.sleep(retry_delay)

    def _build_download_plan(self, artwork: ArtworkInfo) -> list[tuple[int, str]]:
        return self.planner.build_download_plan(artwork)

    def _normalize_url(self, url: str) -> str:
        return self.planner._normalize_url(url)

    def _fetch_artwork_pages_data(self, artwork: ArtworkInfo) -> list[dict]:
        return self.planner._fetch_artwork_pages_data(artwork)

    def _enrich_artwork_from_pages_api(self, artwork: ArtworkInfo) -> ArtworkInfo:
        pages_data = self._fetch_artwork_pages_data(artwork)
        if not pages_data:
            return artwork

        page_urls: list[str] = []
        for item in pages_data:
            if not isinstance(item, dict):
                continue

            urls = item.get("urls", {})
            if not isinstance(urls, dict):
                continue

            for key in ("original", "regular", "small", "thumb_mini"):
                value = urls.get(key)
                if isinstance(value, str) and value.strip():
                    page_urls.append(self._normalize_url(value))

        if not page_urls:
            return artwork

        merged_urls = list(dict.fromkeys(page_urls + artwork.possible_image_urls))
        return artwork.model_copy(
            update={
                "possible_image_urls": merged_urls,
                "page_count": max(artwork.page_count, len(pages_data)),
            }
        )

    def _plan_looks_like_preview_only(self, download_plan: list[tuple[int, str]]) -> bool:
        return self.planner._plan_looks_like_preview_only(download_plan)

    def _extract_live_page_image_urls(self, artwork_id: str) -> list[str]:
        return self.planner._extract_live_page_image_urls(artwork_id)

    def _infer_extension(self, url: str, content_type: str | None = None) -> str:
        return self.path_builder.infer_extension(url, content_type=content_type)

    def _build_author_folder_name(self, artwork: ArtworkInfo) -> str:
        return self.path_builder.build_author_folder_name(artwork)

    def _build_file_stem(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        total_pages: int,
    ) -> str:
        return self.path_builder.build_file_stem(
            artwork,
            page_index,
            total_pages=total_pages,
        )

    def _build_output_path(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        url: str,
        content_type: str | None = None,
        total_pages: int | None = None,
    ) -> Path:
        """
        生成图片最终保存路径。

        目录结构当前是：
        `data/images/作者文件夹/作品标题__作品ID.扩展名`
        或
        `data/images/作者文件夹/作品标题__作品ID_p页码.扩展名`

        也就是说，同一个作者的所有图片都会落进同一个目录里，
        不再是一张作品一个文件夹。
        """
        return self.path_builder.build_output_path(
            artwork,
            page_index,
            url,
            content_type=content_type,
            total_pages=total_pages,
        )

    def _prepare_download_targets(self, artwork: ArtworkInfo) -> tuple[ArtworkInfo, list[tuple[int, str]]]:
        """
        先把作品补全成“适合下载判断”的状态，再生成最终下载计划。

        这样后面的“是否已下载完成”和“真正开始下载”都能复用同一套准备逻辑，
        避免两边判断标准不一致。
        """
        artwork = self._enrich_artwork_from_pages_api(artwork)
        download_plan = self._build_download_plan(artwork)

        # 如果当前计划看起来只拿到了分享预览图，就从真实页面 DOM 再补抓一次。
        if self._plan_looks_like_preview_only(download_plan):
            live_urls = self._extract_live_page_image_urls(artwork.artwork_id)
            if live_urls:
                enhanced_urls = list(dict.fromkeys(artwork.possible_image_urls + live_urls))
                artwork = artwork.model_copy(update={"possible_image_urls": enhanced_urls})
                download_plan = self._build_download_plan(artwork)

        return artwork, download_plan

    def _find_existing_file_for_page(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        total_pages: int,
    ) -> Path | None:
        """
        查找某一页是否已经有对应的本地文件。

        这里故意不强依赖扩展名，因为图片可能是 `.jpg`、`.png`，
        我们只关心“这一页是否已经存在可复用文件”。
        """
        return self.path_builder.find_existing_file_for_page(
            artwork,
            page_index,
            total_pages=total_pages,
        )

    def is_artwork_downloaded(self, artwork: ArtworkInfo) -> tuple[bool, list[str]]:
        """
        判断一个作品是否已经完整下载。

        返回值：
        - 第一个值：是否已经完整下载
        - 第二个值：当前找到的本地文件路径列表

        “完整下载”的标准是：
        - 能生成出下载计划
        - 下载计划里每一页对应的本地文件都已经存在
        """
        prepared = self.prepare_artwork_download(artwork)
        return self.is_prepared_artwork_downloaded(prepared)

    def prepare_artwork_download(self, artwork: ArtworkInfo) -> PreparedArtworkDownload:
        """
        预先补全作品下载信息，并生成下载计划。

        这样任务层可以只准备一次，再把同一份结果同时用于：
        - 判断是否已下载
        - 真正执行下载
        """
        return self._prepare_download_targets(artwork)

    def is_prepared_artwork_downloaded(
        self,
        prepared: PreparedArtworkDownload,
    ) -> tuple[bool, list[str]]:
        """
        基于已经准备好的下载信息判断作品是否已完整下载。
        """
        artwork, download_plan = prepared
        if not download_plan:
            return False, []

        existing_files: list[str] = []
        total_pages = len(download_plan)
        for page_index, _ in download_plan:
            existing_file = self._find_existing_file_for_page(
                artwork,
                page_index,
                total_pages=total_pages,
            )
            if existing_file is None:
                return False, []
            existing_files.append(str(existing_file))

        return True, existing_files

    def download_artwork(self, artwork: ArtworkInfo, overwrite: bool = False) -> list[str]:
        """
        下载整个作品的图片，并返回本地文件路径列表。

        参数说明：
        - `overwrite=False`：文件已存在时不重复下载
        - `overwrite=True`：即使文件存在，也重新下载覆盖
        """
        prepared = self.prepare_artwork_download(artwork)
        return self.download_prepared_artwork(prepared, overwrite=overwrite)

    def download_prepared_artwork(
        self,
        prepared: PreparedArtworkDownload,
        overwrite: bool = False,
    ) -> list[str]:
        """
        基于已经准备好的下载信息执行真正的下载。
        """
        artwork, download_plan = prepared

        if not download_plan:
            raise RuntimeError(f"未找到可下载图片 URL，作品 ID: {artwork.artwork_id}")

        downloaded_files: list[str] = []
        headers = self._get_request_headers(artwork)
        cookies = self._build_cookies()
        proxy_url = self._build_proxy_url()

        # 使用 `httpx.Client` 可以复用连接，效率更高。
        with self._build_http_client(headers, cookies, proxy_url) as http_client:
            total_pages = len(download_plan)
            for page_index, url in download_plan:
                existing_file = self._find_existing_file_for_page(
                    artwork,
                    page_index,
                    total_pages=total_pages,
                )
                if existing_file is not None and not overwrite:
                    downloaded_files.append(str(existing_file))
                    continue

                downloaded_files.append(
                    self._download_page_with_retry(
                        http_client,
                        artwork,
                        page_index,
                        total_pages,
                        url,
                    )
                )

        return downloaded_files
