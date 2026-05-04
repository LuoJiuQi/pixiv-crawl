"""
这个文件负责“浏览器基础设施”。

它不负责：
- 登录 Pixiv
- 打开作品页
- 解析 HTML

它只负责：
- 启动浏览器
- 创建浏览器上下文
- 复用登录状态
- 创建页面对象
- 正确关闭所有资源

你可以把它理解成整个爬虫项目的“浏览器底座”。
"""

from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright._impl._api_structures import ProxySettings, StorageState

from app.browser.state_manager import StateManager
from app.core.config import settings
from app.core.logging_config import get_logger


logger = get_logger(__name__)


class BrowserClient:
    """
    对 Playwright 做一层简单封装。

    这样做的好处是：
    - 主流程不用关心太多 Playwright 细节
    - 登录模块、爬虫模块、下载模块都可以复用同一个浏览器实例
    - 浏览器的启动和关闭逻辑集中管理，不容易乱
    """

    def __init__(self):
        """
        初始化时先把几个核心对象设为 `None`。

        这里先不真的启动浏览器，只是先准备好变量位置。

        这些属性分别表示：
        - `playwright`：Playwright 框架本身
        - `browser`：真正启动出来的 Chromium 浏览器
        - `context`：浏览器上下文，可以理解成一个独立的登录环境
        - `page`：当前正在操作的网页标签页
        - `state_manager`：专门管理登录状态文件的工具
        """
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.state_manager = StateManager()

    def start(self) -> None:
        """
        按顺序启动浏览器自动化环境。

        整体流程是：
        1. 确保登录状态目录存在
        2. 启动 Playwright
        3. 启动 Chromium
        4. 读取本地登录状态并复用
        5. 设置统一超时时间
        6. 创建页面对象
        """

        # 登录状态文件通常会保存在 `data/state` 目录下。
        # 如果目录不存在，后面保存状态文件会失败，所以先确保它存在。
        self.state_manager.ensure_state_dir()

        # 启动 Playwright 的同步接口。
        self.playwright = sync_playwright().start()

        proxy_config: ProxySettings | None = None

        # 如果配置了代理，就在浏览器启动阶段一起接上。
        # 这样页面访问、登录流程、站内接口请求都会走同一条代理链路。
        if settings.proxy_server.strip():
            proxy_config = {
                "server": settings.proxy_server.strip(),
            }
            if settings.proxy_username.strip():
                proxy_config["username"] = settings.proxy_username.strip()
            if settings.proxy_password.strip():
                proxy_config["password"] = settings.proxy_password.strip()

        # 启动 Chromium 浏览器。
        # 是否显示窗口，由配置里的 `headless` 决定。
        self.browser = self.playwright.chromium.launch(
            headless=settings.headless,
            proxy=proxy_config,
        )

        # 如果本地已经有保存过的登录状态，就直接复用。
        # 这样通常不需要每次启动都重新登录。
        if self.state_manager.state_exists():
            self.context = self.browser.new_context(
                storage_state=self.state_manager.get_state_file()
            )
        else:
            # 没有登录状态时，就创建一个全新的上下文。
            self.context = self.browser.new_context()

        # 设置默认超时时间。
        # 后续的大多数页面操作都会自动使用这个超时值。
        self.context.set_default_timeout(settings.timeout)

        # 创建一个页面对象。
        # 后续登录、访问作品页、读取页面内容都依赖它。
        self.page = self.context.new_page()

    def get_page(self) -> Page:
        """
        返回当前页面对象。

        如果浏览器还没启动，就主动抛出一个更直白的错误，
        这样比让代码在别处报奇怪异常更容易排查。
        """
        if self.page is None:
            raise RuntimeError("浏览器尚未启动，请先调用 start()")
        return self.page

    def get_context(self) -> BrowserContext:
        """
        返回当前浏览器上下文对象。

        浏览器上下文里保存着：
        - cookies
        - 本地存储
        - 登录状态

        下载器后面就会通过它读取 cookies。
        """
        if self.context is None:
            raise RuntimeError("浏览器上下文尚未创建，请先调用 start()")
        return self.context

    def save_storage_state(self) -> None:
        """
        把当前浏览器里的登录状态保存到本地文件。

        保存的内容通常包括：
        - cookies
        - localStorage
        - 其他会影响登录态的浏览器存储信息
        """
        if self.context is None:
            raise RuntimeError("浏览器上下文不存在，无法保存登录状态")

        # 先让 Playwright 返回原始状态数据，
        # 再交给 `StateManager` 统一写成可读版 JSON。
        state_data: StorageState = self.context.storage_state()
        self.state_manager.save_state_data(state_data)

    def close(self) -> None:
        """
        按顺序释放资源。

        关闭顺序通常是：
        页面 -> 上下文 -> 浏览器 -> Playwright

        这样做更稳，也更不容易留下后台残留进程。
        """
        self._safe_release("page", "close")
        self._safe_release("context", "close")
        self._safe_release("browser", "close")
        self._safe_release("playwright", "stop")

    def _safe_release(self, attribute_name: str, method_name: str) -> None:
        """
        尝试释放单个浏览器资源，即使失败也继续后面的清理。

        `main()` 会在 `finally` 里调用 `close()`。
        如果这里某一步抛错就直接中断，后面的浏览器或 Playwright 进程
        可能会残留在后台。所以这里采用 best-effort 策略：
        - 尽量调用对应关闭方法
        - 失败时记日志
        - 无论成功失败，都把属性清空
        """
        resource = getattr(self, attribute_name)
        if resource is None:
            return

        try:
            getattr(resource, method_name)()
        except Exception:
            logger.warning("关闭浏览器资源失败：%s.%s()", attribute_name, method_name, exc_info=True)
        finally:
            setattr(self, attribute_name, None)
