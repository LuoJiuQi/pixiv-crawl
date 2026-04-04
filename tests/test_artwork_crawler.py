import unittest
from typing import cast
from unittest.mock import patch

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from app.browser.client import BrowserClient
from app.crawler import artwork_crawler
from app.crawler.artwork_crawler import ArtworkCrawler


class DummyClient:
    def __init__(self, page):
        self._page = page

    def get_page(self):
        return self._page


class FakePage:
    def __init__(self, *, url: str, goto_error: Exception | None = None, wait_side_effects=None):
        self.url = url
        self.goto_error = goto_error
        self.wait_side_effects = list(wait_side_effects or [])
        self.goto_calls = []
        self.wait_calls = []

    def goto(self, url: str, wait_until: str, timeout: int):
        self.goto_calls.append((url, wait_until, timeout))
        if self.goto_error is not None:
            raise self.goto_error

    def wait_for_function(self, script: str, **kwargs):
        self.wait_calls.append((script, kwargs))
        if self.wait_side_effects:
            effect = self.wait_side_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect
        return None


def make_crawler(page: FakePage) -> ArtworkCrawler:
    return ArtworkCrawler(cast(BrowserClient, DummyClient(page)))


class ArtworkCrawlerTestCase(unittest.TestCase):
    def test_open_artwork_page_logs_warning_when_initial_goto_fails(self) -> None:
        page = FakePage(
            url="https://www.pixiv.net/artworks/123456789",
            goto_error=PlaywrightError("boom"),
        )
        crawler = make_crawler(page)

        with patch.object(artwork_crawler.logger, "warning") as mock_warning:
            result = crawler.open_artwork_page("123456789")

        self.assertEqual(result, "https://www.pixiv.net/artworks/123456789")
        mock_warning.assert_called_once()
        self.assertEqual(mock_warning.call_args.args[0], "作品页首次跳转失败，继续检查最终 URL：%s; reason=%r")
        self.assertEqual(mock_warning.call_args.args[1], "https://www.pixiv.net/artworks/123456789")
        self.assertIsInstance(mock_warning.call_args.args[2], PlaywrightError)
        self.assertEqual(str(mock_warning.call_args.args[2]), "boom")

    def test_open_artwork_page_logs_debug_when_metadata_wait_times_out(self) -> None:
        page = FakePage(
            url="https://www.pixiv.net/artworks/123456789",
            wait_side_effects=[
                PlaywrightTimeoutError("metadata timeout"),
            ],
        )
        crawler = make_crawler(page)

        with patch.object(artwork_crawler.logger, "debug") as mock_debug:
            result = crawler.open_artwork_page("123456789")

        self.assertEqual(result, "https://www.pixiv.net/artworks/123456789")
        mock_debug.assert_any_call("等待作品页 metadata 节点超时，继续兜底：%s", "123456789")
        self.assertEqual(mock_debug.call_count, 1)

    def test_open_artwork_page_logs_debug_when_image_wait_times_out(self) -> None:
        page = FakePage(
            url="https://www.pixiv.net/artworks/123456789",
            wait_side_effects=[
                None,
                PlaywrightTimeoutError("image timeout"),
            ],
        )
        crawler = make_crawler(page)

        with patch.object(artwork_crawler.logger, "debug") as mock_debug:
            result = crawler.open_artwork_page("123456789")

        self.assertEqual(result, "https://www.pixiv.net/artworks/123456789")
        mock_debug.assert_any_call("等待作品页主图节点超时，继续兜底：%s", "123456789")
        self.assertEqual(mock_debug.call_count, 1)


if __name__ == "__main__":
    unittest.main()
