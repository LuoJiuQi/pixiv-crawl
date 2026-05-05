import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import call, patch

import httpx

from app.browser.client import BrowserClient
from app.core.config import settings
from app.downloader.download_planner import PreparedArtworkDownload
from app.downloader.image_downloader import PixivImageDownloader
from app.schemas.artwork import ArtworkInfo


class DummyClient:
    def __init__(self, page=None):
        self._page = page or DummyPage()

    def get_context(self):
        return DummyContext()

    def get_page(self):
        return self._page


class DummyContext:
    def cookies(self):
        return []


class DummyPage:
    def __init__(
        self,
        url: str = "https://www.pixiv.net/artworks/123456789",
        *,
        goto_error: Exception | None = None,
        evaluate_error: Exception | None = None,
        wait_for_function_error: Exception | None = None,
        user_agent: str = "UnitTestAgent/1.0",
    ):
        self.url = url
        self.goto_error = goto_error
        self.evaluate_error = evaluate_error
        self.wait_for_function_error = wait_for_function_error
        self.user_agent = user_agent
        self.goto_calls = []
        self.wait_for_function_calls = []
        self.evaluate_calls = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        if self.goto_error:
            raise self.goto_error

    def wait_for_timeout(self, timeout):
        return None

    def wait_for_function(self, script: str, arg=None, timeout=None):
        self.wait_for_function_calls.append((script, arg, timeout))
        if self.wait_for_function_error:
            raise self.wait_for_function_error

    def evaluate(self, script: str, *args):
        self.evaluate_calls.append((script, args))
        if self.evaluate_error:
            raise self.evaluate_error
        if "navigator.userAgent" in script:
            return self.user_agent
        if args:
            return [
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ]
        return []


def make_dummy_client() -> BrowserClient:
    """
    为单元测试构造一个“类型上兼容”的假客户端。

    这些测试只覆盖下载器里与 URL 规划、本地文件判断相关的逻辑，
    不会真的调用浏览器，因此这里用测试替身就足够了。
    """
    return cast(BrowserClient, DummyClient())


def make_client_with_page(page: DummyPage) -> BrowserClient:
    return cast(BrowserClient, DummyClient(page))


class LocalOnlyDownloader(PixivImageDownloader):
    """跳过 API 补全，直接用静态 possible_image_urls 生成下载计划。"""

    def prepare_artwork_download(self, artwork: ArtworkInfo) -> PreparedArtworkDownload:
        plan = self.planner.build_download_plan(artwork)
        return PreparedArtworkDownload(artwork=artwork, plan=plan)


class StreamFriendlyDownloader(LocalOnlyDownloader):
    """用 possible_image_urls 的第一条生成单页下载计划，忽略补全逻辑。"""

    def prepare_artwork_download(self, artwork: ArtworkInfo) -> PreparedArtworkDownload:
        return PreparedArtworkDownload(artwork=artwork, plan=[(0, artwork.possible_image_urls[0])])


class PixivImageDownloaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.downloader = PixivImageDownloader(make_dummy_client())

    def test_get_request_headers_logs_debug_and_falls_back_to_default_user_agent(self) -> None:
        page = DummyPage(
            evaluate_error=RuntimeError("user agent unavailable"),
        )
        downloader = PixivImageDownloader(make_client_with_page(page))
        artwork = ArtworkInfo(
            artwork_id="123456789",
            canonical_url="https://www.pixiv.net/artworks/123456789",
        )
        logger_name = f"pixiv_crawl.{PixivImageDownloader.__module__}"

        with self.assertLogs(logger_name, level="DEBUG") as captured:
            headers = downloader._get_request_headers(artwork)

        self.assertEqual(headers["User-Agent"], downloader.DEFAULT_USER_AGENT)
        self.assertEqual(headers["Referer"], "https://www.pixiv.net/artworks/123456789")
        self.assertTrue(any("读取 navigator.userAgent 失败" in message for message in captured.output))

    def test_build_cookies_skips_entries_missing_required_fields(self) -> None:
        class CookieClient(DummyClient):
            def get_context(self):
                class CookieContext:
                    def cookies(self):
                        return [
                            {"name": "session", "value": "abc", "path": "/"},
                            {"value": "missing_name"},
                            {"name": "missing_value"},
                        ]

                return CookieContext()

        downloader = PixivImageDownloader(cast(BrowserClient, CookieClient()))

        cookies = downloader._build_cookies()

        self.assertEqual(cookies.get("session"), "abc")
        self.assertIsNone(cookies.get("missing_name"))
        self.assertIsNone(cookies.get("missing_value"))

    def test_is_artwork_downloaded_returns_true_when_all_pages_exist(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=2,
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ],
        )

        with TemporaryDirectory() as temp_dir:
            downloader = LocalOnlyDownloader(make_dummy_client(), download_dir=temp_dir)
            author_dir = Path(temp_dir) / downloader._build_author_folder_name(artwork)
            author_dir.mkdir(parents=True, exist_ok=True)
            (author_dir / "制服まとめ__123456789_p0.jpg").write_bytes(b"p0")
            (author_dir / "制服まとめ__123456789_p1.png").write_bytes(b"p1")

            is_downloaded, existing_files = downloader.is_artwork_downloaded(artwork)

        self.assertTrue(is_downloaded)
        self.assertEqual(len(existing_files), 2)

    def test_is_artwork_downloaded_returns_false_when_pages_are_missing(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=2,
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p1.jpg",
            ],
        )

        with TemporaryDirectory() as temp_dir:
            downloader = LocalOnlyDownloader(make_dummy_client(), download_dir=temp_dir)
            author_dir = Path(temp_dir) / downloader._build_author_folder_name(artwork)
            author_dir.mkdir(parents=True, exist_ok=True)
            (author_dir / "制服まとめ__123456789_p0.jpg").write_bytes(b"p0")

            is_downloaded, existing_files = downloader.is_artwork_downloaded(artwork)

        self.assertFalse(is_downloaded)
        self.assertEqual(existing_files, [])

    def test_is_artwork_downloaded_returns_false_for_partial_or_empty_files(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        with TemporaryDirectory() as temp_dir:
            downloader = LocalOnlyDownloader(make_dummy_client(), download_dir=temp_dir)
            author_dir = Path(temp_dir) / downloader._build_author_folder_name(artwork)
            author_dir.mkdir(parents=True, exist_ok=True)
            (author_dir / "制服まとめ__123456789.jpg.part").write_bytes(b"partial")
            (author_dir / "制服まとめ__123456789.png").write_bytes(b"")

            is_downloaded, existing_files = downloader.is_artwork_downloaded(artwork)

        self.assertFalse(is_downloaded)
        self.assertEqual(existing_files, [])

    def test_download_artwork_streams_response_body_to_disk(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            canonical_url="https://www.pixiv.net/artworks/123456789",
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        class FakeResponse:
            def __init__(self) -> None:
                self.headers = {"content-type": "image/jpeg"}
                self.url = artwork.possible_image_urls[0]

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self) -> list[bytes]:
                return [b"chunk1", b"chunk2"]

        class FakeStreamContext:
            def __enter__(self):
                return FakeResponse()

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                self.last_request = (method, url)
                return FakeStreamContext()

        with TemporaryDirectory() as temp_dir:
            downloader = StreamFriendlyDownloader(make_dummy_client(), download_dir=temp_dir)

            with patch("app.downloader.image_downloader.httpx.Client", FakeHttpClient):
                downloaded_files = downloader.download_artwork(artwork)

            saved_path = Path(downloaded_files[0])
            saved_bytes = saved_path.read_bytes()

        self.assertEqual(saved_bytes, b"chunk1chunk2")
        self.assertEqual(saved_path.suffix, ".jpg")

    def test_download_artwork_rejects_empty_response_and_removes_partial_file(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            canonical_url="https://www.pixiv.net/artworks/123456789",
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        class EmptyResponse:
            def __init__(self) -> None:
                self.headers = {"content-type": "image/jpeg", "content-length": "0"}
                self.url = artwork.possible_image_urls[0]

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self) -> list[bytes]:
                return []

        class FakeStreamContext:
            def __enter__(self):
                return EmptyResponse()

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                return FakeStreamContext()

        with TemporaryDirectory() as temp_dir:
            downloader = StreamFriendlyDownloader(make_dummy_client(), download_dir=temp_dir)

            with patch("app.downloader.image_downloader.httpx.Client", FakeHttpClient), self.assertRaisesRegex(
                RuntimeError,
                "下载结果为空文件",
            ):
                downloader.download_artwork(artwork)

            part_files = list(Path(temp_dir).rglob("*.part"))

        self.assertEqual(part_files, [])

    def test_download_artwork_rejects_content_length_mismatch_and_removes_partial_file(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            canonical_url="https://www.pixiv.net/artworks/123456789",
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        class MismatchedResponse:
            def __init__(self) -> None:
                self.headers = {"content-type": "image/jpeg", "content-length": "10"}
                self.url = artwork.possible_image_urls[0]

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self) -> list[bytes]:
                return [b"short"]

        class FakeStreamContext:
            def __enter__(self):
                return MismatchedResponse()

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                return FakeStreamContext()

        with TemporaryDirectory() as temp_dir:
            downloader = StreamFriendlyDownloader(make_dummy_client(), download_dir=temp_dir)

            with patch("app.downloader.image_downloader.httpx.Client", FakeHttpClient), self.assertRaisesRegex(
                RuntimeError,
                "下载文件大小不匹配",
            ):
                downloader.download_artwork(artwork)

            part_files = list(Path(temp_dir).rglob("*.part"))

        self.assertEqual(part_files, [])

    def test_download_artwork_retries_retryable_http_status_before_succeeding(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            canonical_url="https://www.pixiv.net/artworks/123456789",
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        class SequencedResponse:
            def __init__(self, outcome: str) -> None:
                self.outcome = outcome
                self.headers = {"content-type": "image/jpeg"}
                self.url = artwork.possible_image_urls[0]

            def raise_for_status(self) -> None:
                if self.outcome == "503":
                    request = httpx.Request("GET", self.url)
                    response = httpx.Response(503, request=request)
                    raise httpx.HTTPStatusError("server unavailable", request=request, response=response)

            def iter_bytes(self) -> list[bytes]:
                return [b"ok"]

        class SequencedStreamContext:
            def __init__(self, response: SequencedResponse):
                self.response = response

            def __enter__(self):
                return self.response

            def __exit__(self, exc_type, exc, tb):
                return False

        class SequencedHttpClient:
            instances: list["SequencedHttpClient"] = []

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.outcomes = ["503", "success"]
                self.requests = []
                self.__class__.instances.append(self)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                self.requests.append((method, url))
                return SequencedStreamContext(SequencedResponse(self.outcomes.pop(0)))

        with TemporaryDirectory() as temp_dir:
            downloader = StreamFriendlyDownloader(make_dummy_client(), download_dir=temp_dir)

            with patch("app.downloader.image_downloader.httpx.Client", SequencedHttpClient), patch(
                "app.downloader.image_downloader.time.sleep"
            ) as mocked_sleep, patch.object(
                settings,
                "download_retry_attempts",
                3,
            ), patch.object(
                settings,
                "download_retry_backoff_seconds",
                0.25,
            ):
                downloaded_files = downloader.download_artwork(artwork)

            saved_path = Path(downloaded_files[0])
            saved_bytes = saved_path.read_bytes()

        self.assertEqual(saved_bytes, b"ok")
        self.assertEqual(SequencedHttpClient.instances[0].requests, [("GET", artwork.possible_image_urls[0])] * 2)
        mocked_sleep.assert_called_once_with(0.25)

    def test_download_artwork_prefers_retry_after_header_for_rate_limit(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            canonical_url="https://www.pixiv.net/artworks/123456789",
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        class SequencedResponse:
            def __init__(self, outcome: str) -> None:
                self.outcome = outcome
                self.headers = {"content-type": "image/jpeg"}
                self.url = artwork.possible_image_urls[0]

            def raise_for_status(self) -> None:
                if self.outcome == "429":
                    request = httpx.Request("GET", self.url)
                    response = httpx.Response(429, headers={"retry-after": "3"}, request=request)
                    raise httpx.HTTPStatusError("rate limited", request=request, response=response)

            def iter_bytes(self) -> list[bytes]:
                return [b"ok"]

        class SequencedStreamContext:
            def __init__(self, response: SequencedResponse):
                self.response = response

            def __enter__(self):
                return self.response

            def __exit__(self, exc_type, exc, tb):
                return False

        class SequencedHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.outcomes = ["429", "success"]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                return SequencedStreamContext(SequencedResponse(self.outcomes.pop(0)))

        with TemporaryDirectory() as temp_dir:
            downloader = StreamFriendlyDownloader(make_dummy_client(), download_dir=temp_dir)

            with patch("app.downloader.image_downloader.httpx.Client", SequencedHttpClient), patch(
                "app.downloader.image_downloader.time.sleep"
            ) as mocked_sleep, patch.object(
                settings,
                "download_retry_attempts",
                3,
            ), patch.object(
                settings,
                "download_retry_backoff_seconds",
                0.25,
            ):
                downloaded_files = downloader.download_artwork(artwork)

            saved_path = Path(downloaded_files[0])
            saved_bytes = saved_path.read_bytes()

        self.assertEqual(saved_bytes, b"ok")
        mocked_sleep.assert_called_once_with(3.0)

    def test_download_artwork_retries_request_errors_until_exhausted(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=1,
            canonical_url="https://www.pixiv.net/artworks/123456789",
            possible_image_urls=[
                "https://i.pximg.net/img-original/img/2026/03/20/15/42/15/123456789_p0.jpg",
            ],
        )

        class ErrorStreamContext:
            def __init__(self, error: Exception):
                self.error = error

            def __enter__(self):
                raise self.error

            def __exit__(self, exc_type, exc, tb):
                return False

        class ErrorHttpClient:
            instances: list["ErrorHttpClient"] = []

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.requests = []
                self.__class__.instances.append(self)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def stream(self, method: str, url: str):
                self.requests.append((method, url))
                return ErrorStreamContext(httpx.ReadTimeout("timed out"))

        with TemporaryDirectory() as temp_dir:
            downloader = StreamFriendlyDownloader(make_dummy_client(), download_dir=temp_dir)

            with patch("app.downloader.image_downloader.httpx.Client", ErrorHttpClient), patch(
                "app.downloader.image_downloader.time.sleep"
            ) as mocked_sleep, patch.object(
                settings,
                "download_retry_attempts",
                3,
            ), patch.object(
                settings,
                "download_retry_backoff_seconds",
                0.25,
            ):
                with self.assertRaises(httpx.ReadTimeout):
                    downloader.download_artwork(artwork)

        self.assertEqual(
            ErrorHttpClient.instances[0].requests,
            [("GET", artwork.possible_image_urls[0])] * 3,
        )
        mocked_sleep.assert_has_calls([call(0.25), call(0.5)])


if __name__ == "__main__":
    unittest.main()
