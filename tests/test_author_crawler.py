import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from app.browser.client import BrowserClient
from app.crawler.author_crawler import AuthorCrawler


class DummyClient:
    pass


class StubAuthorCrawler(AuthorCrawler):
    def __init__(self, payload: dict, fallback_ids: list[str]):
        super().__init__(cast(BrowserClient, DummyClient()))
        self.payload = payload
        self.fallback_ids = fallback_ids
        self.opened_user_id = ""
        self.opened_following_page = False

    def open_author_artworks_page(self, user_id: str) -> str:
        self.opened_user_id = user_id
        return f"https://www.pixiv.net/users/{user_id}/artworks"

    def _fetch_profile_all_data(self, user_id: str) -> dict:
        return self.payload

    def _extract_artwork_ids_from_page_links(self) -> list[str]:
        return self.fallback_ids

    def open_following_page(self) -> str:
        self.opened_following_page = True
        return "https://www.pixiv.net/bookmark.php?type=user"

    def _fetch_following_users_payload(self) -> dict:
        return self.payload

    def _extract_following_user_ids_from_page_links(self) -> list[str]:
        return self.fallback_ids


class LoggingAuthorCrawlerTestCase(unittest.TestCase):
    def _build_crawler(self) -> tuple[AuthorCrawler, MagicMock, MagicMock]:
        page = MagicMock()
        client = MagicMock()
        client.get_page.return_value = page
        crawler = AuthorCrawler(cast(BrowserClient, client))
        return crawler, client, page

    def test_collect_author_artwork_ids_logs_warning_and_debug_when_fallback_fails(self) -> None:
        crawler, _, page = self._build_crawler()

        def evaluate_side_effect(script: str, *args: Any) -> Any:
            if "/ajax/user/" in script:
                raise Exception("profile payload failed")
            if 'a[href*="/artworks/"]' in script:
                raise Exception("page links failed")
            return []

        page.evaluate.side_effect = evaluate_side_effect

        with patch.object(crawler, "open_author_artworks_page", return_value=None), self.assertLogs(
            "pixiv_crawl.app.crawler.author_crawler",
            level="DEBUG",
        ) as captured:
            artwork_ids = crawler.collect_author_artwork_ids("778899")

        self.assertEqual(artwork_ids, [])
        self.assertTrue(
            any("作者作品接口获取失败" in message for message in captured.output),
            captured.output,
        )
        self.assertTrue(
            any("从作者页链接兜底提取作品 ID 失败" in message for message in captured.output),
            captured.output,
        )

    def test_collect_author_artwork_ids_logs_debug_when_page_links_return_non_list(self) -> None:
        crawler, _, page = self._build_crawler()
        page.evaluate.return_value = {}

        with patch.object(crawler, "open_author_artworks_page", return_value=None), patch.object(
            crawler,
            "_fetch_profile_all_data",
            return_value={},
        ), self.assertLogs("pixiv_crawl.app.crawler.author_crawler", level="DEBUG") as captured:
            artwork_ids = crawler.collect_author_artwork_ids("778899")

        self.assertEqual(artwork_ids, [])
        self.assertTrue(
            any("从作者页链接兜底提取作品 ID 返回非列表" in message for message in captured.output),
            captured.output,
        )

    def test_collect_following_user_ids_logs_warning_and_falls_back_to_page_links(self) -> None:
        crawler, _, page = self._build_crawler()

        def evaluate_side_effect(script: str, *args: Any) -> Any:
            if "/ajax/user/" in script:
                raise Exception("following payload failed")
            if 'a[href*="/users/"]' in script:
                return ["888", "777"]
            return []

        page.evaluate.side_effect = evaluate_side_effect

        with patch.object(crawler, "open_following_page", return_value=None), patch.object(
            crawler,
            "_get_logged_in_user_id",
            return_value="112233",
        ), self.assertLogs("pixiv_crawl.app.crawler.author_crawler", level="DEBUG") as captured:
            user_ids = crawler.collect_following_user_ids()

        self.assertEqual(user_ids, ["888", "777"])
        self.assertTrue(
            any("关注画师接口获取失败" in message for message in captured.output),
            captured.output,
        )

    def test_collect_following_user_ids_logs_debug_when_page_links_return_non_list(self) -> None:
        crawler, _, page = self._build_crawler()
        page.evaluate.return_value = {}

        with patch.object(crawler, "open_following_page", return_value=None), patch.object(
            crawler,
            "_fetch_following_users_payload",
            return_value={},
        ), patch.object(
            crawler,
            "_get_logged_in_user_id",
            return_value="112233",
        ), self.assertLogs("pixiv_crawl.app.crawler.author_crawler", level="DEBUG") as captured:
            user_ids = crawler.collect_following_user_ids()

        self.assertEqual(user_ids, [])
        self.assertTrue(
            any("从关注页链接兜底提取作者 ID 返回非列表" in message for message in captured.output),
            captured.output,
        )

    def test_open_author_artworks_page_logs_warning_and_debug_on_transient_load_issues(self) -> None:
        crawler, _, page = self._build_crawler()
        page.url = "https://www.pixiv.net/users/778899/artworks"
        page.goto.side_effect = PlaywrightError("network")
        page.wait_for_function.side_effect = PlaywrightTimeoutError("timeout")

        with self.assertLogs("pixiv_crawl.app.crawler.author_crawler", level="DEBUG") as captured:
            url = crawler.open_author_artworks_page("778899")

        self.assertEqual(url, page.url)
        self.assertTrue(
            any("作者页首次跳转失败" in message for message in captured.output),
            captured.output,
        )
        self.assertTrue(
            any("等待作者页主体节点超时" in message for message in captured.output),
            captured.output,
        )

    def test_get_logged_in_user_id_logs_diagnostics_before_raising(self) -> None:
        crawler, _, page = self._build_crawler()
        page.evaluate.side_effect = RuntimeError("next_data unavailable")
        page.goto.side_effect = PlaywrightError("network")

        with self.assertLogs("pixiv_crawl.app.crawler.author_crawler", level="DEBUG") as captured:
            with self.assertRaises(RuntimeError):
                crawler._get_logged_in_user_id()

        self.assertTrue(
            any("识别当前登录用户 ID 失败" in message for message in captured.output),
            captured.output,
        )
        self.assertTrue(
            any("刷新 Pixiv 首页以识别当前登录用户 ID 失败" in message for message in captured.output),
            captured.output,
        )


class AuthorCrawlerTestCase(unittest.TestCase):
    def test_extract_artwork_ids_from_profile_payload_merges_and_sorts(self) -> None:
        crawler = StubAuthorCrawler(payload={}, fallback_ids=[])

        payload = {
            "illusts": {
                "100": {},
                "300": {},
            },
            "manga": {
                "200": {},
                "300": {},
            },
        }

        artwork_ids = crawler._extract_artwork_ids_from_profile_payload(payload)

        self.assertEqual(artwork_ids, ["300", "200", "100"])

    def test_collect_author_artwork_ids_uses_payload_and_limit(self) -> None:
        crawler = StubAuthorCrawler(
            payload={
                "illusts": {
                    "100": {},
                    "300": {},
                    "200": {},
                }
            },
            fallback_ids=[],
        )

        artwork_ids = crawler.collect_author_artwork_ids("778899", limit=2)

        self.assertEqual(crawler.opened_user_id, "778899")
        self.assertEqual(artwork_ids, ["300", "200"])

    def test_collect_author_artwork_ids_falls_back_to_page_links(self) -> None:
        crawler = StubAuthorCrawler(
            payload={},
            fallback_ids=["888", "777"],
        )

        artwork_ids = crawler.collect_author_artwork_ids("445566")

        self.assertEqual(artwork_ids, ["888", "777"])

    def test_extract_following_user_ids_from_payload_deduplicates_and_keeps_order(self) -> None:
        crawler = StubAuthorCrawler(payload={}, fallback_ids=[])

        payload = {
            "users": [
                {"userId": "300"},
                {"userId": 100},
                {"user_id": "200"},
                {"userId": "300"},
            ]
        }

        user_ids = crawler._extract_following_user_ids_from_payload(payload)

        self.assertEqual(user_ids, ["300", "100", "200"])

    def test_collect_following_user_ids_prefers_payload_and_limit(self) -> None:
        crawler = StubAuthorCrawler(
            payload={
                "users": [
                    {"userId": "300"},
                    {"userId": "200"},
                    {"userId": "100"},
                ]
            },
            fallback_ids=["999"],
        )

        user_ids = crawler.collect_following_user_ids(limit=2)

        self.assertTrue(crawler.opened_following_page)
        self.assertEqual(user_ids, ["300", "200"])

    def test_collect_following_user_ids_falls_back_to_page_links(self) -> None:
        crawler = StubAuthorCrawler(
            payload={},
            fallback_ids=["888", "777"],
        )

        user_ids = crawler.collect_following_user_ids()

        self.assertEqual(user_ids, ["888", "777"])


if __name__ == "__main__":
    unittest.main()
