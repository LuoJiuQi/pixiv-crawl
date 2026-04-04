import unittest
from typing import cast

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

    def open_author_artworks_page(self, user_id: str) -> str:
        self.opened_user_id = user_id
        return f"https://www.pixiv.net/users/{user_id}/artworks"

    def _fetch_profile_all_data(self, user_id: str) -> dict:
        return self.payload

    def _extract_artwork_ids_from_page_links(self) -> list[str]:
        return self.fallback_ids


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


if __name__ == "__main__":
    unittest.main()
