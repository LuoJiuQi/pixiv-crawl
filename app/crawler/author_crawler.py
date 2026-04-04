"""
这个文件负责“从作者主页收集作品 ID”。

和作品详情页抓取器不同，这里的目标不是解析单个作品内容，
而是先回答一个更前置的问题：
“这个作者名下都有哪些作品可以处理？”

这样做完以后，主流程就不再需要你手动一个一个找作品 ID，
而是可以先拿到一整批作品，再复用现有下载链路继续跑。
"""

from typing import Any

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from app.browser.client import BrowserClient


class AuthorCrawler:
    """
    专门处理 Pixiv 作者主页和作品列表页。
    """

    def __init__(self, client: BrowserClient):
        """
        接收一个已经启动好的浏览器客户端。
        """
        self.client = client

    def open_author_artworks_page(self, user_id: str) -> str:
        """
        打开作者作品页，并返回最终 URL。

        这里优先进入 `/users/{id}/artworks`，
        因为这个页面语义最明确，后续拿作品列表也更自然。
        """
        page = self.client.get_page()
        url = f"https://www.pixiv.net/users/{user_id}/artworks"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightError:
            # 某些前端站点在初次进入时会有瞬时异常或跳转，
            # 所以这里先让流程继续，后面再根据最终 URL 做校验。
            pass

        current_url = page.url
        if f"/users/{user_id}" not in current_url:
            raise RuntimeError(f"未成功进入目标作者页，当前 URL: {current_url}")

        try:
            # 先等到页面主体基本可见。
            page.wait_for_function(
                """
                () => {
                    return Boolean(
                        document.querySelector('main') ||
                        document.querySelector('section') ||
                        document.querySelector('title')
                    );
                }
                """,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            # 即使等不到，也先不立刻失败。
            # 后面还有接口抓取和 DOM 兜底两层机会。
            pass

        return page.url

    def _fetch_profile_all_data(self, user_id: str) -> dict[str, Any]:
        """
        在浏览器页面里调用 Pixiv 当前站内接口，拿到作者名下全部作品信息。

        这里选择“页面内 fetch”而不是自己用 `httpx` 去请求，
        是因为当前浏览器上下文里已经有登录态、cookies 和前端环境，
        成功率通常更高。
        """
        page = self.client.get_page()

        try:
            result = page.evaluate(
                """
                async (userId) => {
                    const response = await fetch(`/ajax/user/${userId}/profile/all?lang=zh`, {
                        credentials: 'include'
                    });

                    if (!response.ok) {
                        return {
                            ok: false,
                            status: response.status,
                            body: {}
                        };
                    }

                    const data = await response.json();
                    return {
                        ok: !data.error,
                        status: response.status,
                        body: data.body || {}
                    };
                }
                """,
                user_id,
            )
        except Exception:
            return {}

        if not isinstance(result, dict) or not result.get("ok"):
            return {}

        body = result.get("body", {})
        return body if isinstance(body, dict) else {}

    def _extract_artwork_ids_from_profile_payload(self, payload: dict[str, Any]) -> list[str]:
        """
        从作者接口返回的数据里抽出作品 ID。

        当前主要关注两类：
        - `illusts`：插画
        - `manga`：漫画

        Pixiv 的接口结构有时会稍微变化，
        所以这里故意写得更宽松一点，尽量兼容字典或列表形式。
        """
        candidates: list[str] = []

        for key in ("illusts", "manga"):
            value = payload.get(key)

            if isinstance(value, dict):
                for artwork_id in value.keys():
                    text = str(artwork_id).strip()
                    if text.isdigit() and text not in candidates:
                        candidates.append(text)
                continue

            if isinstance(value, list):
                for item in value:
                    text = str(item).strip()
                    if text.isdigit() and text not in candidates:
                        candidates.append(text)

        # 接口返回如果是字典，原始顺序不一定真的就是作品发布时间顺序。
        # 这里按 ID 倒序排，通常会更接近“新的作品在前面”的直觉。
        return sorted(candidates, key=int, reverse=True)

    def _extract_artwork_ids_from_page_links(self) -> list[str]:
        """
        如果接口没有拿到数据，就从当前页面链接里兜底提取作品 ID。
        """
        page = self.client.get_page()

        try:
            artwork_ids = page.evaluate(
                """
                () => {
                    const values = new Set();

                    for (const anchor of document.querySelectorAll('a[href*="/artworks/"]')) {
                        const match = anchor.href.match(/\\/artworks\\/(\\d+)/);
                        if (match) {
                            values.add(match[1]);
                        }
                    }

                    return Array.from(values);
                }
                """
            )
        except Exception:
            return []

        if not isinstance(artwork_ids, list):
            return []

        results: list[str] = []
        for item in artwork_ids:
            text = str(item).strip()
            if text.isdigit() and text not in results:
                results.append(text)
        return results

    def collect_author_artwork_ids(self, user_id: str, limit: int | None = None) -> list[str]:
        """
        收集某个作者名下的作品 ID 列表。

        整体策略是：
        1. 先打开作者作品页
        2. 优先尝试站内接口，尽量拿全量作品
        3. 如果接口失败，再从页面链接里兜底提取
        4. 如果用户指定了数量上限，就只保留前 N 个
        """
        self.open_author_artworks_page(user_id)

        payload = self._fetch_profile_all_data(user_id)
        artwork_ids = self._extract_artwork_ids_from_profile_payload(payload)

        if not artwork_ids:
            artwork_ids = self._extract_artwork_ids_from_page_links()

        if limit is not None and limit > 0:
            artwork_ids = artwork_ids[:limit]

        return artwork_ids
