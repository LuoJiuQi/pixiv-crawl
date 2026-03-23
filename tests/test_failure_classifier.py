import unittest

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

    def test_classify_unknown_error(self) -> None:
        self.assertEqual(classify_failure("some strange message"), "unknown")


if __name__ == "__main__":
    unittest.main()
