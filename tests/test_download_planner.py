import unittest
from typing import cast

from app.browser.client import BrowserClient
from app.downloader.download_planner import DownloadPlanner
from app.schemas.artwork import ArtworkInfo


class DummyClient:
    def __init__(self, page=None):
        self._page = page or DummyPage()

    def get_page(self):
        return self._page


class DummyPage:
    def __init__(
        self,
        url: str = "https://www.pixiv.net/artworks/123456789",
        *,
        goto_error: Exception | None = None,
        evaluate_error: Exception | None = None,
        wait_for_function_error: Exception | None = None,
    ):
        self.url = url
        self.goto_error = goto_error
        self.evaluate_error = evaluate_error
        self.wait_for_function_error = wait_for_function_error

    def goto(self, url, wait_until=None, timeout=None):
        if self.goto_error:
            raise self.goto_error

    def wait_for_timeout(self, timeout):
        return None

    def wait_for_function(self, script: str, arg=None, timeout=None):
        if self.wait_for_function_error:
            raise self.wait_for_function_error

    def evaluate(self, script: str, *args):
        if self.evaluate_error:
            raise self.evaluate_error
        if args:
            return [
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ]
        return []


def make_dummy_client(page: DummyPage | None = None) -> BrowserClient:
    return cast(BrowserClient, DummyClient(page))


class StubPagesPlanner(DownloadPlanner):
    def __init__(self, pages_data):
        super().__init__(make_dummy_client())
        self._pages_data = pages_data

    def _fetch_artwork_pages_data(self, artwork: ArtworkInfo) -> list[dict]:
        return self._pages_data


class DownloadPlannerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = DownloadPlanner(make_dummy_client())

    def test_build_download_plan_prefers_original_image(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="142543623",
            page_count=1,
            possible_image_urls=[
                "https://i.pximg.net/img-master/img/2026/03/21/00/12/12/142543623_p0_master1200.jpg",
                "https://i.pximg.net/img-original/img/2026/03/21/00/12/12/142543623_p0.jpg",
                "https://embed.pixiv.net/artwork.php?illust_id=142543623&mdate=1774019532",
            ],
        )

        plan = self.planner.build_download_plan(artwork)

        self.assertEqual(
            plan,
            [
                (
                    0,
                    "https://i.pximg.net/img-original/img/2026/03/21/00/12/12/142543623_p0.jpg",
                )
            ],
        )

    def test_build_download_plan_expands_multi_page_from_p0(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            page_count=3,
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/21/00/12/12/123456789_p0.png",
            ],
        )

        plan = self.planner.build_download_plan(artwork)

        self.assertEqual(
            plan,
            [
                (0, "https://i.pximg.net/img-original/img/2026/03/21/00/12/12/123456789_p0.png"),
                (1, "https://i.pximg.net/img-original/img/2026/03/21/00/12/12/123456789_p1.png"),
                (2, "https://i.pximg.net/img-original/img/2026/03/21/00/12/12/123456789_p2.png"),
            ],
        )

    def test_build_download_plan_falls_back_to_embed_url(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="142501413",
            page_count=1,
            possible_image_urls=[
                "https://embed.pixiv.net/artwork.php?illust_id=142501413&mdate=1773932425",
            ],
        )

        plan = self.planner.build_download_plan(artwork)

        self.assertEqual(
            plan,
            [(0, "https://embed.pixiv.net/artwork.php?illust_id=142501413&mdate=1773932425")],
        )

    def test_plan_looks_like_preview_only_for_embed_urls(self) -> None:
        self.assertTrue(
            self.planner._plan_looks_like_preview_only(
                [(0, "https://embed.pixiv.net/artwork.php?illust_id=142522397&mdate=1774000000")]
            )
        )
        self.assertFalse(
            self.planner._plan_looks_like_preview_only(
                [(0, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/142522397_p0.jpg")]
            )
        )

    def test_enrich_artwork_from_pages_api_updates_urls_and_page_count(self) -> None:
        planner = StubPagesPlanner(
            [
                {
                    "urls": {
                        "original": "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                        "regular": "https://i.pximg.net/img-master/img/2026/03/20/15/42/15/123456789_p0_master1200.jpg",
                    }
                },
                {
                    "urls": {
                        "original": "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
                        "regular": "https://i.pximg.net/img-master/img/2026/03/20/15/42/15/123456789_p1_master1200.jpg",
                    }
                },
            ]
        )
        artwork = ArtworkInfo(
            artwork_id="123456789",
            page_count=1,
            possible_image_urls=[
                "https://embed.pixiv.net/artwork.php?illust_id=123456789&mdate=1774000000"
            ],
        )

        enriched = planner.enrich_artwork_from_pages_api(artwork)

        self.assertEqual(enriched.page_count, 2)
        self.assertIn(
            "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            enriched.possible_image_urls,
        )
        self.assertIn(
            "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            enriched.possible_image_urls,
        )

    def test_prepare_download_targets_uses_api_enriched_multi_page_urls(self) -> None:
        planner = StubPagesPlanner(
            [
                {"urls": {"original": "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg"}},
                {"urls": {"original": "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg"}},
                {"urls": {"original": "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p2.jpg"}},
            ]
        )
        artwork = ArtworkInfo(
            artwork_id="123456789",
            page_count=1,
            possible_image_urls=[
                "https://embed.pixiv.net/artwork.php?illust_id=123456789&mdate=1774000000"
            ],
        )

        enriched, plan = planner.prepare_download_targets(artwork)

        self.assertEqual(enriched.page_count, 3)
        self.assertEqual(
            plan,
            [
                (0, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg"),
                (1, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg"),
                (2, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p2.jpg"),
            ],
        )

    def test_fetch_artwork_pages_data_logs_warning_when_initial_navigation_fails(self) -> None:
        page = DummyPage(
            url="https://www.pixiv.net/",
            goto_error=RuntimeError("navigation failed"),
        )
        planner = DownloadPlanner(make_dummy_client(page))
        artwork = ArtworkInfo(artwork_id="123456789")
        logger_name = f"pixiv_crawl.{DownloadPlanner.__module__}"

        with self.assertLogs(logger_name, level="WARNING") as captured:
            result = planner._fetch_artwork_pages_data(artwork)

        self.assertEqual(result, [])
        self.assertTrue(any("页码接口前置跳转失败" in message for message in captured.output))

    def test_fetch_artwork_pages_data_logs_warning_when_evaluate_fails(self) -> None:
        page = DummyPage(
            url="https://www.pixiv.net/",
            evaluate_error=RuntimeError("evaluate failed"),
        )
        planner = DownloadPlanner(make_dummy_client(page))
        artwork = ArtworkInfo(artwork_id="123456789")
        logger_name = f"pixiv_crawl.{DownloadPlanner.__module__}"

        with self.assertLogs(logger_name, level="WARNING") as captured:
            result = planner._fetch_artwork_pages_data(artwork)

        self.assertEqual(result, [])
        self.assertTrue(any("页码接口 page.evaluate() 失败" in message for message in captured.output))

    def test_extract_live_page_image_urls_logs_debug_when_waiting_for_dom_times_out(self) -> None:
        page = DummyPage(
            wait_for_function_error=RuntimeError("timeout"),
        )
        planner = DownloadPlanner(make_dummy_client(page))
        logger_name = f"pixiv_crawl.{DownloadPlanner.__module__}"

        with self.assertLogs(logger_name, level="DEBUG") as captured:
            urls = planner._extract_live_page_image_urls("123456789")

        self.assertEqual(
            urls,
            [
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ],
        )
        self.assertTrue(any("DOM 主图等待失败" in message for message in captured.output))

    def test_extract_live_page_image_urls_logs_debug_when_dom_evaluation_fails(self) -> None:
        page = DummyPage(
            evaluate_error=RuntimeError("dom read failed"),
        )
        planner = DownloadPlanner(make_dummy_client(page))
        logger_name = f"pixiv_crawl.{DownloadPlanner.__module__}"

        with self.assertLogs(logger_name, level="DEBUG") as captured:
            urls = planner._extract_live_page_image_urls("123456789")

        self.assertEqual(urls, [])
        self.assertTrue(any("DOM 补抓失败" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
