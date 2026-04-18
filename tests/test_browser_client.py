import unittest
from unittest.mock import MagicMock, patch

from app.browser.client import BrowserClient


class BrowserClientTestCase(unittest.TestCase):
    def test_close_continues_releasing_resources_when_page_close_fails(self) -> None:
        client = BrowserClient()
        page = MagicMock()
        context = MagicMock()
        browser = MagicMock()
        playwright = MagicMock()

        client.page = page
        client.context = context
        client.browser = browser
        client.playwright = playwright

        page.close.side_effect = RuntimeError("page close failed")

        with patch("app.browser.client.logger") as mocked_logger:
            client.close()

        page.close.assert_called_once()
        context.close.assert_called_once()
        browser.close.assert_called_once()
        playwright.stop.assert_called_once()
        mocked_logger.warning.assert_called_once()
        self.assertIsNone(client.page)
        self.assertIsNone(client.context)
        self.assertIsNone(client.browser)
        self.assertIsNone(client.playwright)

    def test_close_handles_all_resources_missing(self) -> None:
        client = BrowserClient()

        with patch("app.browser.client.logger") as mocked_logger:
            client.close()

        mocked_logger.warning.assert_not_called()
        self.assertIsNone(client.page)
        self.assertIsNone(client.context)
        self.assertIsNone(client.browser)
        self.assertIsNone(client.playwright)


if __name__ == "__main__":
    unittest.main()
