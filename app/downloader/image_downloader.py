"""
这个文件负责“真正把图片下载到本地”。

它的主要工作是：
1. 从解析器给出的候选图片 URL 里挑出最合适的
2. 复用浏览器上下文里的登录态和 cookies
3. 带着正确的请求头请求 Pixiv 图片
4. 把图片写入本地文件

之所以不能只写一句 `httpx.get(url)`，是因为 Pixiv 图片请求通常还需要：
- `Referer`
- 登录 cookies
否则很容易拿到 403 或错误页面。
"""

import mimetypes
import re
from html import unescape
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlparse

import httpx

from app.browser.client import BrowserClient
from app.core.config import settings
from app.schemas.artwork import ArtworkInfo


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

    def __init__(self, client: BrowserClient, download_dir: str | None = None):
        """
        保存浏览器客户端和下载目录。
        """
        self.client = client
        self.download_dir = Path(download_dir or settings.download_dir)

    def _normalize_url(self, url: str) -> str:
        """
        把 HTML / JSON 里的转义 URL 还原成正常 URL。
        """
        return unescape(url.replace("\\/", "/").replace("\\u0026", "&")).strip()

    def _score_url(self, url: str) -> int:
        """
        给候选图片 URL 打分。

        分数越高，说明我们越偏向选择它。
        """
        if "img-original" in url:
            return 500
        if "img-master" in url:
            return 400
        if "custom-thumb" in url:
            return 300
        if "square" in url:
            return 200
        if "embed.pixiv.net/artwork.php" in url:
            return 100
        return 0

    def _extract_page_index(self, url: str) -> int | None:
        """
        从 URL 中提取页码，比如 `_p0`、`_p1`。
        """
        match = re.search(r"_p(\d+)", url)
        if not match:
            return None
        return int(match.group(1))

    def _swap_page_index(self, url: str, page_index: int) -> str:
        """
        把 URL 里的页码替换成指定页码。
        """
        return re.sub(r"_p\d+", f"_p{page_index}", url, count=1)

    def _build_download_plan(self, artwork: ArtworkInfo) -> list[tuple[int, str]]:
        """
        生成下载计划。

        返回值格式是：
        `(页码, 图片地址)`

        处理思路：
        - 先清洗 URL
        - 再按页码归类
        - 同一页存在多个候选时，选得分更高的那个
        - 如果知道总页数，但只拿到 `p0`，就尝试推导 `p1/p2...`
        """
        normalized_urls = []
        for url in artwork.possible_image_urls:
            normalized = self._normalize_url(url)
            if normalized and normalized not in normalized_urls:
                normalized_urls.append(normalized)

        page_url_map: dict[int, str] = {}
        fallback_urls: list[str] = []

        for url in normalized_urls:
            page_index = self._extract_page_index(url)
            if page_index is None:
                # 没有页码的地址先记到兜底列表里。
                fallback_urls.append(url)
                continue

            current_url = page_url_map.get(page_index)
            if current_url is None or self._score_url(url) > self._score_url(current_url):
                page_url_map[page_index] = url

        if page_url_map:
            # `page_count` 可能比目前看到的页码更多，
            # 说明还需要补齐缺失页。
            page_count = max(artwork.page_count, max(page_url_map) + 1)

            # 选一个质量最高的地址作为“模板 URL”，后面用它推导其他页。
            _, seed_url = max(
                page_url_map.items(),
                key=lambda item: self._score_url(item[1]),
            )

            for page_index in range(page_count):
                if page_index not in page_url_map:
                    page_url_map[page_index] = self._swap_page_index(seed_url, page_index)

            return sorted(page_url_map.items())

        if fallback_urls:
            best_fallback = max(fallback_urls, key=self._score_url)
            return [(0, best_fallback)]

        return []

    def _fetch_artwork_pages_data(self, artwork: ArtworkInfo) -> list[dict]:
        """
        通过浏览器页面内的 `fetch` 调 Pixiv 作品页接口，拿到每一页的图片信息。

        为什么要在浏览器页面里请求，而不是直接用 `httpx` 请求接口？
        - 直接请求 Pixiv AJAX 接口时，容易被 Cloudflare 拦住
        - 浏览器页面已经通过了站点的前端校验和登录态检查
        - 在页面上下文里 `fetch`，成功率会高很多

        成功时返回每一页对应的字典列表，失败时返回空列表。
        """
        page = self.client.get_page()
        artwork_url = artwork.canonical_url or f"https://www.pixiv.net/artworks/{artwork.artwork_id}"

        if f"/artworks/{artwork.artwork_id}" not in page.url:
            try:
                page.goto(artwork_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            except Exception:
                return []

        try:
            result = page.evaluate(
                """
                async (artworkId) => {
                    const response = await fetch(`/ajax/illust/${artworkId}/pages?lang=zh`, {
                        credentials: 'include'
                    });

                    if (!response.ok) {
                        return { ok: false, status: response.status, body: [] };
                    }

                    const data = await response.json();
                    return {
                        ok: !data.error,
                        status: response.status,
                        body: Array.isArray(data.body) ? data.body : []
                    };
                }
                """,
                artwork.artwork_id,
            )
        except Exception:
            return []

        if not result.get("ok"):
            return []

        body = result.get("body", [])
        return body if isinstance(body, list) else []

    def _enrich_artwork_from_pages_api(self, artwork: ArtworkInfo) -> ArtworkInfo:
        """
        用 Pixiv 页码接口补全真实图片地址和总页数。

        如果接口可用，就把每一页的原图 URL 合并进 `possible_image_urls`，
        同时把 `page_count` 更新成接口返回的真实页数。
        """
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
        """
        判断当前下载计划是不是只拿到了分享预览图。

        典型特征就是：
        - 下载计划不为空
        - 里面所有地址都还是 `embed.pixiv.net/artwork.php?...`

        这种地址虽然能返回一张图片，但通常不是原始作品图，
        更像社交分享卡片。
        """
        return bool(download_plan) and all(
            "embed.pixiv.net/artwork.php" in url for _, url in download_plan
        )

    def _extract_live_page_image_urls(self, artwork_id: str) -> list[str]:
        """
        直接从当前浏览器页面的 DOM 中补抓作品图片 URL。

        这个方法主要是给下载器兜底用的：
        - 如果解析器只拿到了 `og:image`
        - 但浏览器页面里其实已经出现了真实图片链接
        - 那就优先使用页面里的真实链接
        """
        page = self.client.get_page()

        if f"/artworks/{artwork_id}" not in page.url:
            return []

        try:
            page.wait_for_function(
                """
                (artworkId) => {
                    const imageAnchor = document.querySelector(`a[href*="${artworkId}_p"][href*="i.pximg.net"]`);
                    const imageNode = document.querySelector(`img[src*="${artworkId}_p"]`);
                    return Boolean(imageAnchor || imageNode);
                }
                """,
                arg=artwork_id,
                timeout=10000,
            )
        except Exception:
            pass

        try:
            urls = page.evaluate(
                """
                (artworkId) => {
                    const values = new Set();

                    for (const anchor of document.querySelectorAll('a[href*="i.pximg.net"]')) {
                        if (anchor.href.includes(`${artworkId}_p`)) {
                            values.add(anchor.href);
                        }
                    }

                    for (const image of document.querySelectorAll('img[src*="pximg.net"]')) {
                        if (image.src.includes(`${artworkId}_p`)) {
                            values.add(image.src);
                        }
                    }

                    return Array.from(values);
                }
                """,
                artwork_id,
            )
        except Exception:
            return []

        return [self._normalize_url(url) for url in urls if url]

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
            cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
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

    def _infer_extension(self, url: str, content_type: str | None = None) -> str:
        """
        推断图片文件扩展名。

        优先级：
        1. 如果响应头已经明确告诉我们是图片，就优先相信响应头
        2. 否则再看 URL 自己带不带后缀
        3. 最后兜底用 `.bin`

        这样可以避免这种情况：
        - URL 长得像 `artwork.php?...`
        - 但服务器实际返回的是 JPEG 图片
        - 如果只看 URL，就会错误保存成 `.php`
        """
        if content_type:
            normalized_type = content_type.split(";")[0].strip().lower()
            guessed = mimetypes.guess_extension(normalized_type)
            if guessed:
                return ".jpg" if guessed == ".jpe" else guessed

        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix:
            return suffix

        return ".bin"

    def _sanitize_path_part(self, text: str) -> str:
        """
        把作者名这类文本清理成适合当文件夹名的样子。

        Windows 文件系统对这些字符比较敏感：
        `<>:"/\\|?*`
        所以这里统一替换成下划线，避免保存文件时报错。
        """
        sanitized = re.sub(r'[<>:"/\\|?*]+', "_", text).strip(" .")
        if not sanitized:
            return "unknown_author"
        return sanitized[:80]

    def _build_author_folder_name(self, artwork: ArtworkInfo) -> str:
        """
        生成作者文件夹名。

        目标是既尽量稳定，又尽量让人一眼能看懂：
        - 优先保留作者名，方便直接浏览目录
        - 如果有作者 ID，就顺手拼进去，减少重名概率
        """
        safe_author_name = self._sanitize_path_part(artwork.author_name or "unknown_author")
        safe_user_id = self._sanitize_path_part(artwork.user_id)

        if artwork.user_id:
            return f"{safe_author_name}_{safe_user_id}"

        return safe_author_name

    def _build_file_stem(
        self,
        artwork: ArtworkInfo,
        page_index: int,
        total_pages: int,
    ) -> str:
        """
        生成图片文件名的“主干部分”，不包含扩展名。

        现在文件名会优先使用作品标题，但会始终带上作品 ID。

        这样做的原因是：
        - 单看标题更容易认图
        - 但不同作品可能重名
        - 只在撞名时再补 ID，会让“是否已下载”的判断变得不可靠

        所以这里采用一个更稳妥的规则：
        “标题负责好读，作品 ID 负责唯一性”

        命名规则：
        - 单图作品：`作品标题__作品ID`
        - 多图作品：`作品标题__作品ID_p0`、`作品标题__作品ID_p1`
        """
        safe_title = self._sanitize_path_part(artwork.title or artwork.artwork_id)
        base_name = f"{safe_title}__{artwork.artwork_id}"

        if total_pages <= 1:
            return base_name

        return f"{base_name}_p{page_index}"

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
        author_dir = self.download_dir / self._build_author_folder_name(artwork)
        author_dir.mkdir(parents=True, exist_ok=True)

        extension = self._infer_extension(url, content_type=content_type)
        stem = self._build_file_stem(
            artwork,
            page_index,
            total_pages=total_pages if total_pages is not None else artwork.page_count,
        )
        return author_dir / f"{stem}{extension}"

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
        author_dir = self.download_dir / self._build_author_folder_name(artwork)
        if not author_dir.exists():
            return None

        stem = self._build_file_stem(artwork, page_index, total_pages=total_pages)
        matches = sorted(author_dir.glob(f"{stem}.*"))
        return matches[0] if matches else None

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
        artwork, download_plan = self._prepare_download_targets(artwork)
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
        artwork, download_plan = self._prepare_download_targets(artwork)

        if not download_plan:
            raise RuntimeError(f"未找到可下载图片 URL，作品 ID: {artwork.artwork_id}")

        downloaded_files: list[str] = []
        headers = self._get_request_headers(artwork)
        cookies = self._build_cookies()
        proxy_url = self._build_proxy_url()

        client_kwargs: dict[str, object] = {
            "headers": headers,
            "cookies": cookies,
            "follow_redirects": True,
            "timeout": 60.0,
        }
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        # 使用 `httpx.Client` 可以复用连接，效率更高。
        with httpx.Client(**client_kwargs) as http_client:
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

                output_path = self._build_output_path(
                    artwork,
                    page_index,
                    url,
                    total_pages=total_pages,
                )

                response = http_client.get(url)
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

                # 把二进制图片内容写入本地文件。
                output_path.write_bytes(response.content)
                downloaded_files.append(str(output_path))

        return downloaded_files
