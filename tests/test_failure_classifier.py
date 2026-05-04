import unittest

import httpx

from app.services.failure_classifier import classify_failure


class FailureClassifierTestCase(unittest.TestCase):
    def test_classify_login_error(self) -> None:
        self.assertEqual(classify_failure("Pixiv 要求进行 reCAPTCHA 验证，自动登录被拦截。"), "login")

    def test_classify_timeout_error(self) -> None:
        self.assertEqual(classify_failure("等待登录超时，请确认是否已经成功登录。"), "timeout")

    def test_classify_artwork_unavailable_error(self) -> None:
        self.assertEqual(classify_failure("未成功进入目标作品页，当前 URL: https://www.pixiv.net/"), "artwork_unavailable")

    def test_classify_download_error(self) -> None:
        self.assertEqual(classify_failure("未找到可下载图片 URL，作品 ID: 123"), "download")

    def test_classify_incomplete_download_error(self) -> None:
        self.assertEqual(classify_failure("下载文件大小不匹配，预期: 10 字节，实际: 5 字节"), "download")

    def test_classify_rate_limit_http_status_error(self) -> None:
        request = httpx.Request("GET", "https://i.pximg.net/image.jpg")
        response = httpx.Response(429, request=request)
        error = httpx.HTTPStatusError("rate limited", request=request, response=response)

        self.assertEqual(classify_failure(error), "rate_limit")

    def test_classify_http_5xx_status_error(self) -> None:
        request = httpx.Request("GET", "https://i.pximg.net/image.jpg")
        response = httpx.Response(503, request=request)
        error = httpx.HTTPStatusError("server unavailable", request=request, response=response)

        self.assertEqual(classify_failure(error), "http_5xx")

    def test_classify_network_request_error(self) -> None:
        request = httpx.Request("GET", "https://i.pximg.net/image.jpg")
        error = httpx.ConnectError("connection failed", request=request)

        self.assertEqual(classify_failure(error), "network")

    def test_classify_timeout_request_error(self) -> None:
        request = httpx.Request("GET", "https://i.pximg.net/image.jpg")
        error = httpx.ReadTimeout("timed out", request=request)

        self.assertEqual(classify_failure(error), "timeout")

    def test_classify_rate_limit_from_text(self) -> None:
        self.assertEqual(classify_failure("HTTP 429 Too Many Requests"), "rate_limit")

    def test_classify_http_5xx_from_text(self) -> None:
        self.assertEqual(classify_failure("HTTP 503 Service Unavailable"), "http_5xx")

    def test_classify_unknown_error(self) -> None:
        self.assertEqual(classify_failure("some strange message"), "unknown")


if __name__ == "__main__":
    unittest.main()
