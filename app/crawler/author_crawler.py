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
from app.core.logging_config import get_logger


logger = get_logger(__name__)


class AuthorCrawler:
    """
    专门处理 Pixiv 作者主页和作品列表页。
    """

    def __init__(self, client: BrowserClient):
        """
        接收一个已经启动好的浏览器客户端。
        """
        self.client = client

    def _get_logged_in_user_id(self) -> str:
        """
        识别当前登录账号自己的用户 ID。

        后面如果要进入“我关注的画师”页面，
        就需要先知道“当前登录的是谁”，
        这样才能拼出正确的关注页地址。
        """
        page = self.client.get_page()

        def read_user_id() -> str:
            try:
                value = page.evaluate(
                    """
                    () => window.__NEXT_DATA__?.props?.pageProps?.gaUserData?.userId ?? null
                    """
                )
            except Exception:
                logger.debug("识别当前登录用户 ID 失败，当前页结构中未拿到 gaUserData.userId。", exc_info=True)
                return ""

            text = str(value or "").strip()
            return text if text.isdigit() else ""

        user_id = read_user_id()
        if user_id:
            return user_id

        try:
            page.goto("https://www.pixiv.net/", wait_until="domcontentloaded", timeout=30000)
        except PlaywrightError:
            logger.warning("刷新 Pixiv 首页以识别当前登录用户 ID 失败。", exc_info=True)

        user_id = read_user_id()
        if user_id:
            return user_id

        raise RuntimeError("未能识别当前登录账号的用户 ID，无法进入关注画师列表。")

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
        except PlaywrightError as exc:
            logger.warning("作者页首次跳转失败，继续检查最终 URL：%s; reason=%r", url, exc, exc_info=True)
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
            logger.debug("等待作者页主体节点超时，继续兜底：%s", user_id)
            # 即使等不到，也先不立刻失败。
            # 后面还有接口抓取和 DOM 兜底两层机会。
            pass

        return page.url

    def open_following_page(self) -> str:
        """
        打开“我关注的画师”页面，并返回最终 URL。

        当前站点里，这个页面通常对应：
        `/users/{当前用户ID}/following`
        """
        page = self.client.get_page()
        current_user_id = self._get_logged_in_user_id()
        url = f"https://www.pixiv.net/users/{current_user_id}/following"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightError as exc:
            logger.warning("关注页首次跳转失败，继续检查最终 URL：%s; reason=%r", url, exc, exc_info=True)
            pass

        current_url = page.url
        if f"/users/{current_user_id}/following" not in current_url:
            raise RuntimeError(f"未成功进入关注画师页面，当前 URL: {current_url}")

        try:
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
            logger.debug("等待关注页主体节点超时，继续兜底：%s", current_user_id)
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
            logger.warning("作者作品接口获取失败，降级到页面链接兜底：%s", user_id, exc_info=True)
            return {}

        if not isinstance(result, dict) or not result.get("ok"):
            logger.warning("作者作品接口返回异常，降级到页面链接兜底：%s", user_id)
            return {}

        body = result.get("body", {})
        if not isinstance(body, dict):
            logger.warning("作者作品接口返回结构异常，降级到页面链接兜底：%s", user_id)
            return {}

        return body

    def _fetch_following_users_payload(self) -> dict[str, Any]:
        """
        调用 Pixiv 当前站内接口，拿到“我关注的画师”列表。

        这里会自动翻页，把所有关注作者合并成一个总结果，
        上层就不需要自己处理 offset / limit 了。
        """
        page = self.client.get_page()
        current_user_id = self._get_logged_in_user_id()
        offset = 0
        page_size = 24
        merged_users: list[dict[str, Any]] = []
        total = 0

        while True:
            try:
                result = page.evaluate(
                    """
                    async ({ userId, offset, limit }) => {
                        const response = await fetch(
                            `/ajax/user/${userId}/following?offset=${offset}&limit=${limit}&rest=show&lang=zh`,
                            {
                                credentials: 'include'
                            }
                        );

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
                    {
                        "userId": current_user_id,
                        "offset": offset,
                        "limit": page_size,
                    },
                )
            except Exception:
                logger.warning("关注画师接口获取失败，降级到页面链接兜底：%s", current_user_id, exc_info=True)
                return {}

            if not isinstance(result, dict) or not result.get("ok"):
                logger.warning("关注画师接口返回异常，降级到页面链接兜底：%s", current_user_id)
                return {}

            body = result.get("body", {})
            if not isinstance(body, dict):
                logger.warning("关注画师接口返回结构异常，降级到页面链接兜底：%s", current_user_id)
                return {}

            users = body.get("users", [])
            if not isinstance(users, list):
                users = []

            for item in users:
                if isinstance(item, dict):
                    merged_users.append(item)

            total_value = body.get("total", len(merged_users))
            total_text = str(total_value).strip()
            total = int(total_text) if total_text.isdigit() else len(merged_users)

            offset += len(users)
            if not users or offset >= total:
                break

        return {
            "users": merged_users,
            "total": total or len(merged_users),
        }

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

    def _extract_following_user_ids_from_payload(self, payload: dict[str, Any]) -> list[str]:
        """
        从“关注画师”接口返回的数据里抽出作者 ID。
        """
        raw_users = payload.get("users", [])
        if isinstance(raw_users, dict):
            raw_users = raw_users.get("users", [])

        if not isinstance(raw_users, list):
            return []

        user_ids: list[str] = []
        for item in raw_users:
            if not isinstance(item, dict):
                continue

            raw_user_id = item.get("userId", item.get("user_id", ""))
            text = str(raw_user_id).strip()
            if text.isdigit() and text not in user_ids:
                user_ids.append(text)

        return user_ids

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
            logger.debug("从作者页链接兜底提取作品 ID 失败")
            return []

        if not isinstance(artwork_ids, list):
            logger.debug("从作者页链接兜底提取作品 ID 返回非列表：%r", type(artwork_ids).__name__)
            return []

        results: list[str] = []
        for item in artwork_ids:
            text = str(item).strip()
            if text.isdigit() and text not in results:
                results.append(text)
        return results

    def _extract_following_user_ids_from_page_links(self) -> list[str]:
        """
        如果关注画师接口失败，就从页面链接里兜底提取作者 ID。
        """
        page = self.client.get_page()
        current_user_id = ""

        try:
            current_user_id = self._get_logged_in_user_id()
        except Exception:
            current_user_id = ""

        try:
            user_ids = page.evaluate(
                """
                () => {
                    const values = new Set();

                    for (const anchor of document.querySelectorAll('a[href*="/users/"]')) {
                        const match = anchor.href.match(/\\/users\\/(\\d+)/);
                        if (match) {
                            values.add(match[1]);
                        }
                    }

                    return Array.from(values);
                }
                """
            )
        except Exception:
            logger.debug("从关注页链接兜底提取作者 ID 失败")
            return []

        if not isinstance(user_ids, list):
            logger.debug("从关注页链接兜底提取作者 ID 返回非列表：%r", type(user_ids).__name__)
            return []

        results: list[str] = []
        for item in user_ids:
            text = str(item).strip()
            if text.isdigit() and text != current_user_id and text not in results:
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

    def collect_following_user_ids(self, limit: int | None = None) -> list[str]:
        """
        收集当前登录账号关注的画师列表。

        整体思路是：
        1. 先进入关注页
        2. 优先调用站内接口拿完整列表
        3. 接口失败时，再从页面链接兜底
        4. 如果外部指定了数量上限，就只保留前 N 个作者
        """
        self.open_following_page()

        payload = self._fetch_following_users_payload()
        user_ids = self._extract_following_user_ids_from_payload(payload)

        if not user_ids:
            user_ids = self._extract_following_user_ids_from_page_links()

        if limit is not None and limit > 0:
            user_ids = user_ids[:limit]

        return user_ids
