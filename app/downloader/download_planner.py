import re
from html import unescape
from typing import NamedTuple

from app.browser.client import BrowserClient
from app.core.logging_config import get_logger
from app.schemas.artwork import ArtworkInfo


class PreparedArtworkDownload(NamedTuple):
    """准备完成的下载信息：包含补全后的作品信息和下载计划。"""
    artwork: ArtworkInfo
    plan: list[tuple[int, str]]


logger = get_logger(__name__)


class DownloadPlanner:
    """
    负责把作品补全成可下载计划。
    """

    def __init__(self, client: BrowserClient):
        self.client = client

    def _normalize_url(self, url: str) -> str:
        """
        把 HTML / JSON 里的转义 URL 还原成正常 URL。
        """
        return unescape(url.replace("\\/", "/").replace("\\u0026", "&")).strip()

    def _score_url(self, url: str) -> int:
        """
        给候选图片 URL 打分。
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
        从 URL 中提取页码。
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

    def build_download_plan(self, artwork: ArtworkInfo) -> list[tuple[int, str]]:
        """
        生成下载计划。
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
                fallback_urls.append(url)
                continue

            current_url = page_url_map.get(page_index)
            if current_url is None or self._score_url(url) > self._score_url(current_url):
                page_url_map[page_index] = url

        if page_url_map:
            page_count = max(artwork.page_count, max(page_url_map) + 1)
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
        通过浏览器页面内的 fetch 调 Pixiv 作品页接口，拿到每一页的图片信息。
        """
        page = self.client.get_page()
        artwork_url = artwork.canonical_url or f"https://www.pixiv.net/artworks/{artwork.artwork_id}"

        if f"/artworks/{artwork.artwork_id}" not in page.url:
            try:
                page.goto(artwork_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            except Exception:
                logger.warning(
                    "页码接口前置跳转失败，降级为空列表：%s; artwork_id=%s",
                    artwork_url,
                    artwork.artwork_id,
                    exc_info=True,
                )
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
            logger.warning(
                "页码接口 page.evaluate() 失败，降级为空列表：%s; artwork_id=%s",
                artwork_url,
                artwork.artwork_id,
                exc_info=True,
            )
            return []

        if not result.get("ok"):
            return []

        body = result.get("body", [])
        return body if isinstance(body, list) else []

    def enrich_artwork_from_pages_api(self, artwork: ArtworkInfo) -> ArtworkInfo:
        """
        用 Pixiv 页码接口补全真实图片地址和总页数。
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
        判断下载计划是不是只拿到了分享预览图。
        """
        return bool(download_plan) and all(
            "embed.pixiv.net/artwork.php" in url for _, url in download_plan
        )

    def _extract_live_page_image_urls(self, artwork_id: str) -> list[str]:
        """
        直接从当前浏览器页面的 DOM 中补抓作品图片 URL。
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
            logger.debug(
                "DOM 主图等待失败，继续尝试补抓：%s",
                artwork_id,
                exc_info=True,
            )

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
            logger.debug(
                "DOM 补抓失败，降级为空列表：%s",
                artwork_id,
                exc_info=True,
            )
            return []

        return [self._normalize_url(url) for url in urls if url]

    def prepare_download_targets(self, artwork: ArtworkInfo) -> PreparedArtworkDownload:
        """
        先补全作品，再生成最终下载计划。
        """
        artwork = self.enrich_artwork_from_pages_api(artwork)
        download_plan = self.build_download_plan(artwork)

        if self._plan_looks_like_preview_only(download_plan):
            live_urls = self._extract_live_page_image_urls(artwork.artwork_id)
            if live_urls:
                enhanced_urls = list(dict.fromkeys(artwork.possible_image_urls + live_urls))
                artwork = artwork.model_copy(update={"possible_image_urls": enhanced_urls})
                download_plan = self.build_download_plan(artwork)

        return PreparedArtworkDownload(artwork=artwork, plan=download_plan)
