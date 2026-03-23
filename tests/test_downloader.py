import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from app.browser.client import BrowserClient
from app.downloader.image_downloader import PixivImageDownloader
from app.schemas.artwork import ArtworkInfo


class DummyClient:
    pass


def make_dummy_client() -> BrowserClient:
    """
    为单元测试构造一个“类型上兼容”的假客户端。

    这些测试只覆盖下载器里与 URL 规划、本地文件判断相关的逻辑，
    不会真的调用浏览器，因此这里用测试替身就足够了。
    """
    return cast(BrowserClient, DummyClient())


class StubPagesDownloader(PixivImageDownloader):
    def __init__(self, pages_data):
        super().__init__(make_dummy_client())
        self._pages_data = pages_data

    def _fetch_artwork_pages_data(self, artwork: ArtworkInfo) -> list[dict]:
        return self._pages_data


class LocalOnlyDownloader(PixivImageDownloader):
    def _fetch_artwork_pages_data(self, artwork: ArtworkInfo) -> list[dict]:
        return []

    def _extract_live_page_image_urls(self, artwork_id: str) -> list[str]:
        return []


class PixivImageDownloaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.downloader = PixivImageDownloader(make_dummy_client())

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

        plan = self.downloader._build_download_plan(artwork)

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

        plan = self.downloader._build_download_plan(artwork)

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

        plan = self.downloader._build_download_plan(artwork)

        self.assertEqual(
            plan,
            [(0, "https://embed.pixiv.net/artwork.php?illust_id=142501413&mdate=1773932425")],
        )

    def test_infer_extension_prefers_image_content_type_over_php_url(self) -> None:
        extension = self.downloader._infer_extension(
            "https://embed.pixiv.net/artwork.php?illust_id=142522397&mdate=1774000000",
            content_type="image/jpeg",
        )

        self.assertEqual(extension, ".jpg")

    def test_plan_looks_like_preview_only_for_embed_urls(self) -> None:
        self.assertTrue(
            self.downloader._plan_looks_like_preview_only(
                [(0, "https://embed.pixiv.net/artwork.php?illust_id=142522397&mdate=1774000000")]
            )
        )
        self.assertFalse(
            self.downloader._plan_looks_like_preview_only(
                [(0, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/142522397_p0.jpg")]
            )
        )

    def test_enrich_artwork_from_pages_api_updates_urls_and_page_count(self) -> None:
        downloader = StubPagesDownloader(
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

        enriched = downloader._enrich_artwork_from_pages_api(artwork)

        self.assertEqual(enriched.page_count, 2)
        self.assertIn(
            "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            enriched.possible_image_urls,
        )
        self.assertIn(
            "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            enriched.possible_image_urls,
        )

    def test_build_download_plan_uses_api_enriched_multi_page_urls(self) -> None:
        downloader = StubPagesDownloader(
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

        enriched = downloader._enrich_artwork_from_pages_api(artwork)
        plan = downloader._build_download_plan(enriched)

        self.assertEqual(
            plan,
            [
                (0, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg"),
                (1, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg"),
                (2, "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p2.jpg"),
            ],
        )

    def test_is_artwork_downloaded_returns_true_when_all_pages_exist(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            page_count=2,
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ],
        )

        with TemporaryDirectory() as temp_dir:
            artwork_dir = Path(temp_dir) / artwork.artwork_id
            artwork_dir.mkdir(parents=True, exist_ok=True)
            (artwork_dir / "123456789_p0.jpg").write_bytes(b"p0")
            (artwork_dir / "123456789_p1.png").write_bytes(b"p1")

            downloader = LocalOnlyDownloader(make_dummy_client(), download_dir=temp_dir)
            is_downloaded, existing_files = downloader.is_artwork_downloaded(artwork)

        self.assertTrue(is_downloaded)
        self.assertEqual(len(existing_files), 2)

    def test_is_artwork_downloaded_returns_false_when_pages_are_missing(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            page_count=2,
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ],
        )

        with TemporaryDirectory() as temp_dir:
            artwork_dir = Path(temp_dir) / artwork.artwork_id
            artwork_dir.mkdir(parents=True, exist_ok=True)
            (artwork_dir / "123456789_p0.jpg").write_bytes(b"p0")

            downloader = LocalOnlyDownloader(make_dummy_client(), download_dir=temp_dir)
            is_downloaded, existing_files = downloader.is_artwork_downloaded(artwork)

        self.assertFalse(is_downloaded)
        self.assertEqual(existing_files, [])


if __name__ == "__main__":
    unittest.main()
