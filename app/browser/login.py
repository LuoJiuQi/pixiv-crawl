"""
这个文件负责“登录流程”。

现在的登录策略是：
1. 优先尝试自动登录
2. 如果 Pixiv 触发了 reCAPTCHA 等额外验证
3. 再根据当前模式决定是否回退到人工补验证

也就是说，它已经不是最早那种“纯手动登录”了，
而是“自动优先，必要时人工兜底”。
"""

from typing import Any, TypedDict

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.browser.client import BrowserClient
from app.core.config import settings
from app.core.logging_config import get_logger
from app.services import console_service


logger = get_logger(__name__)


class LoginResult(TypedDict):
    success: bool
    requires_manual_action: bool
    state_saved: bool
    issue: str


class PixivLoginService:
    """
    专门处理 Pixiv 登录逻辑。

    它依赖浏览器客户端，但不负责自己启动浏览器。
    这样职责会更清晰：
    - `BrowserClient` 管浏览器环境
    - `PixivLoginService` 管登录流程
    """

    LOGIN_URL = "https://accounts.pixiv.net/login"
    HOME_URL = "https://www.pixiv.net/"

    # 当前登录页里比较稳定的定位方式。
    USERNAME_SELECTOR = 'input[autocomplete*="username"]'
    PASSWORD_SELECTOR = 'input[autocomplete*="current-password"]'

    # 当前页面里会出现的 reCAPTCHA 提示文案。
    RECAPTCHA_HINTS = (
        "reCAPTCHA認証を行ってください。",
        "reCAPTCHA",
        "CAPTCHA",
    )

    # 登录页常见的提交控件选择器。
    SUBMIT_CONTROL_SELECTORS = (
        'button[type="submit"]',
        'input[type="submit"]',
        'button[data-testid*="login"]',
        'button[name="login"]',
    )

    # Cookie 横幅常见的接受按钮文案兜底。
    COOKIE_BANNER_BUTTON_NAMES = (
        "同意",
        "接受",
        "Accept",
        "I agree",
    )

    def __init__(self, client: BrowserClient):
        """
        接收一个已经准备好的浏览器客户端。
        """
        self.client = client
        # 记录最近一次自动登录失败的主要原因，
        # 这样后面切换到人工处理时，可以给出更具体的提示。
        self.last_login_issue: str | None = None

    def _set_login_issue(self, issue: str | None) -> None:
        """
        记录当前登录阶段遇到的主要问题。
        """
        self.last_login_issue = issue

    def _build_result(
        self,
        *,
        success: bool,
        issue: str = "",
        requires_manual_action: bool = False,
        state_saved: bool = False,
    ) -> LoginResult:
        return {
            "success": success,
            "requires_manual_action": requires_manual_action,
            "state_saved": state_saved,
            "issue": issue,
        }

    def open_login_page(self) -> None:
        """
        打开 Pixiv 登录页。
        """
        page = self.client.get_page()
        page.goto(self.LOGIN_URL, wait_until="domcontentloaded")

    def _dismiss_cookie_banner(self) -> None:
        """
        如果页面上有 cookie 同意弹窗，就先点掉它。

        不然有可能会挡住输入框或按钮。
        """
        page = self.client.get_page()
        consent_button = self._find_cookie_banner_button(page)
        if consent_button is None:
            return

        consent_button.click()
        page.wait_for_timeout(800)

    def _get_login_form(self):
        """
        获取真正的登录表单。

        登录页里可能有多个 `form`，
        所以这里不是简单拿第一个表单，
        而是拿“包含用户名输入框”的那个表单。
        """
        page = self.client.get_page()
        return page.locator("form").filter(
            has=page.locator(self.USERNAME_SELECTOR)
        ).first

    def _find_cookie_banner_button(self, page: Any):
        """
        找到最可能的 cookie 同意按钮。

        这里优先尝试一些更通用的结构化选择器，
        再退回到少量常见文案，尽量降低对页面语言的耦合。
        """
        selector_candidates = [
            'button[id*="accept"]',
            'button[class*="accept"]',
            'button[data-testid*="accept"]',
            'button[aria-label*="Accept"]',
            'button[aria-label*="accept"]',
            'button[aria-label*="同意"]',
        ]

        for selector in selector_candidates:
            button = page.locator(selector).first
            if self._locator_is_visible(button):
                return button

        for name in self.COOKIE_BANNER_BUTTON_NAMES:
            button = page.get_by_role("button", name=name, exact=True).first
            if self._locator_is_visible(button):
                return button

        return None

    def _get_submit_control(self, form: Any):
        """
        获取登录表单的提交控件。

        优先使用表单结构里的 submit 控件，只有没找到时才回退到按钮文案。
        """
        for selector in self.SUBMIT_CONTROL_SELECTORS:
            control = form.locator(selector).first
            if self._locator_exists(control):
                return control

        fallback_names = ("ログイン", "登录", "登入", "Log in", "Login")
        for name in fallback_names:
            control = form.get_by_role("button", name=name, exact=True).first
            if self._locator_exists(control):
                return control

        return form.locator("button").first

    def _locator_exists(self, locator: Any) -> bool:
        """
        判断 locator 是否至少命中一个节点。
        """
        try:
            return locator.count() > 0
        except Exception:
            return False

    def _locator_is_visible(self, locator: Any) -> bool:
        """
        判断 locator 当前是否可见。
        """
        try:
            return self._locator_exists(locator) and bool(locator.is_visible())
        except Exception:
            return False

    def _credentials_ready(self) -> bool:
        """
        判断配置里是否已经提供了账号密码。
        """
        return bool(settings.pixiv_username.strip() and settings.pixiv_password.strip())

    def _has_recaptcha_prompt(self) -> bool:
        """
        检查当前页面是否出现了 reCAPTCHA 提示。
        """
        page = self.client.get_page()
        try:
            body_text = page.locator("body").inner_text()
        except Exception:
            logger.debug("读取登录页 body 文本失败，暂时无法判断是否出现 reCAPTCHA 提示。", exc_info=True)
            return False
        return any(hint in body_text for hint in self.RECAPTCHA_HINTS)

    def _fill_login_form(self) -> LoginResult:
        """
        自动填写账号密码，并确认提交按钮是否可点。

        返回值含义：
        - `True`：表单已准备好，可以提交
        - `False`：表单没准备好，无法继续自动登录
        """
        if not self._credentials_ready():
            self._set_login_issue("missing_credentials")
            return self._build_result(success=False, issue="missing_credentials")

        page = self.client.get_page()
        try:
            page.locator(self.USERNAME_SELECTOR).first.wait_for(timeout=30000)
            page.locator(self.PASSWORD_SELECTOR).first.wait_for(timeout=30000)
        except PlaywrightTimeoutError:
            self._set_login_issue("login_form_not_found")
            return self._build_result(success=False, issue="login_form_not_found")

        form = self._get_login_form()

        username_input = form.locator(self.USERNAME_SELECTOR)
        password_input = form.locator(self.PASSWORD_SELECTOR)
        submit_button = self._get_submit_control(form)

        username_input.click()
        username_input.fill(settings.pixiv_username)

        password_input.click()
        password_input.fill(settings.pixiv_password)

        # 给页面一点时间，让前端表单状态更新。
        page.wait_for_timeout(1000)

        # 某些受控表单会在失去焦点后才重新计算按钮状态。
        if submit_button.is_disabled():
            username_input.press("Tab")
            password_input.press("Tab")
            page.wait_for_timeout(1000)

        if submit_button.is_disabled():
            self._set_login_issue("submit_disabled")
            return self._build_result(success=False, issue="submit_disabled")

        return self._build_result(success=True)

    def _print_manual_login_guide(self) -> None:
        """
        根据当前失败原因，打印更具体的人工处理提示。
        """
        if self.last_login_issue == "recaptcha":
            console_service.show_warning("检测到 Pixiv 要求进行 reCAPTCHA 验证。")
            console_service.show_warning(
                "请在浏览器中手动完成验证码；如果验证完成后页面没有自动跳转，请再点一次“ログイン”。"
            )
            return

        if self.last_login_issue == "missing_credentials":
            console_service.show_warning("当前没有可用于自动登录的账号密码。")
            console_service.show_warning("请在浏览器中手动输入账号密码并完成登录。")
            return

        if self.last_login_issue == "login_form_not_found":
            console_service.show_warning("当前页面没有按预期显示标准登录表单。")
            console_service.show_warning(
                "请观察浏览器页面，如果出现了其他验证页或中间页，请手动完成后继续。"
            )
            return

        if self.last_login_issue == "submit_disabled":
            console_service.show_warning("自动填表后登录按钮仍不可点击。")
            console_service.show_warning(
                "请检查浏览器页面里是否还有额外选项、弹窗或验证步骤需要手动处理。"
            )
            return

        console_service.show_warning("请在浏览器中手动完成 Pixiv 登录。")

    def wait_for_manual_login(self, timeout: int = 180000) -> LoginResult:
        """
        等待用户手动完成登录。

        这个方法现在主要作为“自动登录失败后的兜底方案”。
        """
        page = self.client.get_page()

        # 先检查一次，避免其实已经登录成功，但这里只是还没来得及返回。
        if self.is_logged_in():
            console_service.show_success("当前已经处于登录状态，无需继续人工操作。")
            return self._build_result(success=True, requires_manual_action=True)

        self._print_manual_login_guide()
        console_service.show_warning("程序会继续等待页面跳转到 Pixiv 主站...")

        try:
            page.wait_for_url("https://www.pixiv.net/*", timeout=timeout)
            console_service.show_success("检测到页面已跳转到 Pixiv 主站。")
        except PlaywrightTimeoutError:
            return self._build_result(
                success=False,
                issue="manual_login_timeout",
                requires_manual_action=True,
            )

        return self._build_result(
            success=self.is_logged_in(),
            requires_manual_action=True,
            issue="" if self.is_logged_in() else "unknown",
        )

    def login_automatically(self, timeout: int = 180000) -> LoginResult:
        """
        尝试执行自动登录。

        自动登录流程：
        1. 打开登录页
        2. 关闭可能挡住页面的 cookie 同意弹窗
        3. 自动填写账号密码
        4. 点击登录按钮
        5. 等待跳转到 Pixiv 主站

        如果被 reCAPTCHA 拦住，这个方法不会假装成功，
        而是明确告诉上层“自动登录没走通”。
        """
        self._set_login_issue(None)
        self.open_login_page()
        page = self.client.get_page()

        # 如果访问登录页后直接被重定向回 Pixiv 主站，
        # 说明当前上下文其实已经是登录状态了。
        if "accounts.pixiv.net" not in page.url and "pixiv.net" in page.url:
            return self._build_result(success=True)

        self._dismiss_cookie_banner()

        fill_result = self._fill_login_form()
        if not fill_result["success"]:
            return fill_result

        form = self._get_login_form()
        submit_button = self._get_submit_control(form)

        console_service.show_warning("已自动填写账号密码，正在尝试自动登录...")
        submit_button.click()

        try:
            page.wait_for_url("https://www.pixiv.net/*", timeout=timeout)
            return self._build_result(success=self.is_logged_in())
        except PlaywrightTimeoutError:
            # 没在规定时间内跳过去，不一定就是密码错。
            # 也可能是触发了 reCAPTCHA、二次验证、风控等额外流程。
            page.wait_for_timeout(3000)

        if self._has_recaptcha_prompt():
            self._set_login_issue("recaptcha")
            return self._build_result(
                success=False,
                issue="recaptcha",
                requires_manual_action=True,
            )

        if self.is_logged_in():
            return self._build_result(success=True)

        self._set_login_issue("unknown")
        return self._build_result(success=False, issue="unknown")

    def is_logged_in(self) -> bool:
        """
        判断当前浏览器是否已经登录 Pixiv。
        """
        page = self.client.get_page()

        try:
            page.goto(self.HOME_URL, wait_until="domcontentloaded")
        except Exception as e:
            logger.warning("访问 Pixiv 首页失败：%s", e)
            return False

        current_url = page.url

        if "accounts.pixiv.net" in current_url:
            return False

        if "pixiv.net" in current_url:
            return True

        return False

    def save_login_state(self) -> LoginResult:
        """
        保存当前登录状态到本地文件。
        """
        self.client.save_storage_state()
        console_service.show_success("登录状态已保存。")
        return self._build_result(success=True, state_saved=True)

    def login_and_save_state(self, timeout: int = 180000) -> LoginResult:
        """
        执行“登录并保存状态”的完整流程。

        新逻辑是：
        - 先尝试自动登录
        - 如果自动登录失败，并且当前不是无头模式
          就允许用户在浏览器里手动补完成验证
        - 最后再保存登录状态
        """
        auto_result = self.login_automatically(timeout=timeout)
        if auto_result["success"]:
            saved_result = self.save_login_state()
            console_service.show_success("Pixiv 自动登录成功。")
            return self._build_result(success=True, state_saved=saved_result["state_saved"])

        # 如果当前是无头模式，看不到浏览器界面，
        # 那么人工补验证码也没有意义，所以直接返回失败。
        if settings.headless:
            console_service.show_error("当前处于无头模式，无法人工补充验证码或二次验证。")
            if auto_result["issue"] == "recaptcha":
                console_service.show_error(
                    "这次失败的直接原因是 reCAPTCHA；请把 HEADLESS 设为 false 后，在可见浏览器里完成人工验证。"
                )
            console_service.show_error("如果 Pixiv 触发了 reCAPTCHA，请把 HEADLESS 设为 false 后重试。")
            return self._build_result(success=False, issue="headless_manual_required")

        console_service.show_warning("自动登录未完成，准备切换为人工补充验证。")
        manual_result = self.wait_for_manual_login(timeout=timeout)
        if not manual_result["success"]:
            console_service.show_error("登录失败，未保存登录状态。")
            return manual_result

        saved_result = self.save_login_state()
        console_service.show_success("Pixiv 登录成功。")
        return self._build_result(
            success=True,
            requires_manual_action=True,
            state_saved=saved_result["state_saved"],
        )
