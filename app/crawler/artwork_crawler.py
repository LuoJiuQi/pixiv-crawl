"""
这个文件负责“打开作品页并获取原始页面内容”。

注意它的职责边界：
- 它负责进入页面
- 它负责拿 HTML
- 它负责把 HTML / JSON 保存到本地

但它不负责：
- 从 HTML 里提取标题
- 解析作者名字
- 计算页数

这些是解析器的工作。
"""

from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from app.browser.client import BrowserClient
from app.utils.file_formatters import pretty_html_text, pretty_json_text


class ArtworkCrawler:
    """
    专门处理 Pixiv 作品详情页的打开和原始内容采集。
    """

    def __init__(self, client: BrowserClient):
        """
        接收一个已经启动好的浏览器客户端。
        """
        self.client = client

    def open_artwork_page(self, artwork_id: str) -> str:
        """
        根据作品 ID 打开对应作品页，并返回最终页面 URL。

        返回最终 URL 的原因是：
        - 页面可能发生跳转
        - 程序需要确认自己最后到底到了哪里
        """
        page = self.client.get_page()
        url = f"https://www.pixiv.net/artworks/{artwork_id}"

        try:
            # 尝试打开作品页。
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightError:
            # 某些前端页面在加载过程中会触发额外跳转或瞬时异常。
            # 所以这里先不直接失败，后面继续检查最终 URL。
            pass

        current_url = page.url

        # 如果最后没有进入目标作品页，说明当前页面不适合继续解析。
        if f"/artworks/{artwork_id}" not in current_url:
            raise RuntimeError(f"未成功进入目标作品页，当前 URL: {current_url}")

        # 页面虽然打开了，但 `title`、`canonical` 等信息未必已经准备好。
        # 这里多等一步，让后面的 HTML 抓取更稳定。
        try:
            page.wait_for_function(
                """
                () => {
                    const title = document.querySelector('title');
                    const ogTitle = document.querySelector('meta[property="og:title"]');
                    const canonical = document.querySelector('link[rel="canonical"]');
                    return (
                        (title && title.textContent.trim().length > 0) ||
                        ogTitle ||
                        canonical
                    );
                }
                """,
                timeout=15000
            )
        except PlaywrightTimeoutError:
            # 即使等不到，也不急着失败。
            # 很多时候 HTML 里依然已经有足够信息给解析器使用。
            pass

        # 再额外等一下作品主图相关节点。
        # 有些作品页的标题很快就出来了，但真正的作品图片 DOM 还没插进页面，
        # 如果这时立刻抓 `page.content()`，解析器就只能拿到 `og:image` 的分享图。
        try:
            page.wait_for_function(
                """
                (artworkId) => {
                    const imageAnchor = document.querySelector(`a[href*="${artworkId}_p"][href*="i.pximg.net"]`);
                    const imageNode = document.querySelector(`img[src*="${artworkId}_p"]`);
                    return Boolean(imageAnchor || imageNode);
                }
                """,
                arg=artwork_id,
                timeout=15000
            )
        except PlaywrightTimeoutError:
            # 如果仍然等不到，也先不报错。
            # 下载器后面还有一层“从当前页面实时补抓图片 URL”的兜底逻辑。
            pass

        return page.url

    def get_page_title(self) -> str:
        """
        获取当前页面标题。
        """
        page = self.client.get_page()
        return page.title()

    def get_page_content(self) -> str:
        """
        获取当前页面完整 HTML。

        这份 HTML 会交给解析器进一步处理。
        """
        page = self.client.get_page()
        return page.content()

    def save_page_source(self, artwork_id: str, save_dir: str = "./data/temp/html") -> str:
        """
        把当前页面源码保存到本地。

        这个功能很适合：
        - 调试解析器
        - 留存出错样本
        - 写回归测试
        """
        content = self.get_page_content()
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        file_path = save_path / f"artwork_{artwork_id}.html"
        file_path.write_text(pretty_html_text(content), encoding="utf-8")

        return str(file_path)

    def save_parsed_info(
        self,
        artwork_id: str,
        parsed_info: dict[str, Any],
        save_dir: str = "./data/temp/json",
    ) -> str:
        """
        把已经解析好的作品信息保存成 JSON 文件。

        HTML 适合分析页面结构，
        JSON 更适合直接检查“解析出来的结果对不对”。
        """
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        file_path = save_path / f"artwork_{artwork_id}.json"
        file_path.write_text(pretty_json_text(parsed_info), encoding="utf-8")

        return str(file_path)

    def is_artwork_page_available(self, artwork_id: str | None = None) -> bool:
        """
        判断当前页面是不是一个可用的作品详情页。

        当前逻辑比较直接：
        - URL 里必须包含 `pixiv.net/artworks/`
        - 如果指定了 `artwork_id`，还要进一步确认 ID 一致
        """
        page = self.client.get_page()
        current_url = page.url

        if "pixiv.net/artworks/" not in current_url:
            return False

        if artwork_id and f"/artworks/{artwork_id}" not in current_url:
            return False

        return True
