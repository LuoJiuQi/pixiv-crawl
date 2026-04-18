import unittest
from unittest.mock import MagicMock, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.browser.login import PixivLoginService


class PixivLoginServiceTestCase(unittest.TestCase):
    def _build_service(self) -> tuple[PixivLoginService, MagicMock, MagicMock]:
        page = MagicMock()
        client = MagicMock()
        client.get_page.return_value = page
        service = PixivLoginService(client)
        return service, client, page

    def _build_locator(self, *, count: int = 1, visible: bool = True) -> MagicMock:
        locator = MagicMock()
        locator.first = locator
        locator.count.return_value = count
        locator.is_visible.return_value = visible
        return locator

    def test_login_automatically_returns_missing_credentials_issue(self) -> None:
        service, _, _ = self._build_service()

        with patch.object(service, "open_login_page"), patch.object(
            service,
            "_dismiss_cookie_banner",
        ), patch.object(
            service,
            "_credentials_ready",
            return_value=False,
        ):
            result = service.login_automatically()

        self.assertFalse(result["success"])
        self.assertEqual(result["issue"], "missing_credentials")

    def test_get_submit_control_prefers_structural_submit_selector(self) -> None:
        service, _, _ = self._build_service()
        form = MagicMock()
        submit_locator = self._build_locator()
        empty_locator = self._build_locator(count=0, visible=False)

        def locate(selector: str) -> MagicMock:
            if selector == 'button[type="submit"]':
                return submit_locator
            return empty_locator

        form.locator.side_effect = locate
        form.get_by_role.return_value = empty_locator

        submit_control = service._get_submit_control(form)

        self.assertIs(submit_control, submit_locator)

    def test_dismiss_cookie_banner_uses_common_accept_button_name_as_fallback(self) -> None:
        service, _, page = self._build_service()
        empty_locator = self._build_locator(count=0, visible=False)
        accept_button = self._build_locator(count=1, visible=True)

        page.locator.return_value = empty_locator

        def get_button_by_name(*, name: str, exact: bool) -> MagicMock:
            if name == "Accept" and exact:
                return accept_button
            return empty_locator

        page.get_by_role.side_effect = lambda role, name, exact: get_button_by_name(
            name=name,
            exact=exact,
        )

        service._dismiss_cookie_banner()

        accept_button.click.assert_called_once()
        page.wait_for_timeout.assert_called_once_with(800)

    def test_login_automatically_returns_recaptcha_issue_when_blocked(self) -> None:
        service, _, page = self._build_service()
        page.url = "https://accounts.pixiv.net/login"

        with patch.object(service, "open_login_page"), patch.object(
            service,
            "_dismiss_cookie_banner",
        ), patch.object(
            service,
            "_fill_login_form",
            return_value={"success": False, "issue": "", "requires_manual_action": False, "state_saved": False},
        ) as mocked_fill, patch.object(
            service,
            "_has_recaptcha_prompt",
            return_value=True,
        ), patch.object(
            service,
            "is_logged_in",
            return_value=False,
        ), patch("app.browser.login.console_service.show_warning"):
            mocked_fill.return_value = {
                "success": True,
                "issue": "",
                "requires_manual_action": False,
                "state_saved": False,
            }
            page.wait_for_url.side_effect = PlaywrightTimeoutError("timeout")
            result = service.login_automatically()

        self.assertFalse(result["success"])
        self.assertEqual(result["issue"], "recaptcha")

    def test_wait_for_manual_login_returns_timeout_issue(self) -> None:
        service, _, page = self._build_service()
        page.wait_for_url.side_effect = PlaywrightTimeoutError("timeout")

        with patch.object(service, "is_logged_in", return_value=False), patch(
            "app.browser.login.console_service.show_warning"
        ), patch("app.browser.login.console_service.show_success"):
            result = service.wait_for_manual_login(timeout=1000)

        self.assertFalse(result["success"])
        self.assertEqual(result["issue"], "manual_login_timeout")

    def test_login_and_save_state_returns_headless_manual_required(self) -> None:
        service, _, _ = self._build_service()

        with patch.object(
            service,
            "login_automatically",
            return_value={
                "success": False,
                "issue": "recaptcha",
                "requires_manual_action": True,
                "state_saved": False,
            },
        ), patch("app.browser.login.settings.headless", True), patch(
            "app.browser.login.console_service.show_error"
        ), patch("app.browser.login.console_service.show_warning"), patch(
            "app.browser.login.console_service.show_success"
        ):
            result = service.login_and_save_state()

        self.assertFalse(result["success"])
        self.assertEqual(result["issue"], "headless_manual_required")

    def test_login_and_save_state_saves_state_after_success(self) -> None:
        service, client, _ = self._build_service()

        with patch.object(
            service,
            "login_automatically",
            return_value={
                "success": True,
                "issue": "",
                "requires_manual_action": False,
                "state_saved": False,
            },
        ), patch("app.browser.login.console_service.show_success"):
            result = service.login_and_save_state()

        client.save_storage_state.assert_called_once()
        self.assertTrue(result["success"])
        self.assertTrue(result["state_saved"])

    def test_login_flow_uses_console_for_user_guidance(self) -> None:
        service, _, _ = self._build_service()

        with patch.object(
            service,
            "login_automatically",
            return_value={
                "success": False,
                "issue": "recaptcha",
                "requires_manual_action": True,
                "state_saved": False,
            },
        ), patch("app.browser.login.settings.headless", True), patch(
            "app.browser.login.console_service.show_error"
        ) as mocked_show_error:
            service.login_and_save_state()

        mocked_show_error.assert_any_call("当前处于无头模式，无法人工补充验证码或二次验证。")

    def test_login_flow_uses_logger_for_diagnostics(self) -> None:
        service, _, page = self._build_service()
        page.goto.side_effect = RuntimeError("network")

        with patch("app.browser.login.logger") as mocked_logger:
            result = service.is_logged_in()

        self.assertFalse(result)
        mocked_logger.warning.assert_called_once()

    def test_has_recaptcha_prompt_returns_false_and_logs_debug_when_body_read_fails(self) -> None:
        service, _, page = self._build_service()
        page.locator.return_value.inner_text.side_effect = RuntimeError("dom not ready")

        with self.assertLogs("pixiv_crawl.app.browser.login", level="DEBUG") as captured:
            has_prompt = service._has_recaptcha_prompt()

        self.assertFalse(has_prompt)
        self.assertTrue(
            any("读取登录页 body 文本失败" in message for message in captured.output),
            captured.output,
        )


if __name__ == "__main__":
    unittest.main()
