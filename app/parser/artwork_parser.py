"""
这个文件是“页面解析器”。

输入：
- 一整段 Pixiv 作品页 HTML

输出：
- 一个结构化的 `ArtworkInfo` 对象

它的核心工作是把“网页源码”拆成“程序能直接使用的数据”。

为什么要把解析器单独放一个文件？
- 抓网页和解析网页是两个不同阶段
- 页面打不开，和字段解析错了，是两类不同问题
- 分开以后更容易测试，也更容易维护
"""

import json
import re
from html import unescape
from typing import Any

from app.schemas.artwork import ArtworkInfo


class ArtworkParser:
    """
    负责从 Pixiv 作品页 HTML 中提取各种字段。

    当前主要提取：
    - 标题
    - 作者名字
    - 作品 ID
    - 作者 ID
    - 标签
    - 页数
    - 可能的图片地址
    """

    def __init__(self, html: str):
        """
        保存原始 HTML。

        后面所有解析方法都会围绕这份 HTML 工作，
        所以这里只需要保存一次即可。
        """
        self.html = html

    def _extract_meta(self, name: str, attr: str = "property") -> str:
        """
        从 `<meta>` 标签里提取内容。

        例如：
        `<meta property="og:title" content="xxx">`

        之所以准备多种正则，是因为真实 HTML 里经常会出现：
        - 单引号 / 双引号混用
        - 属性顺序不固定
        """
        patterns = [
            rf'<meta[^>]+{attr}="{re.escape(name)}"[^>]+content="(.*?)"',
            rf"<meta[^>]+{attr}='{re.escape(name)}'[^>]+content='(.*?)'",
            rf'<meta[^>]+content="(.*?)"[^>]+{attr}="{re.escape(name)}"',
            rf"<meta[^>]+content='(.*?)'[^>]+{attr}='{re.escape(name)}'",
        ]

        for pattern in patterns:
            match = re.search(pattern, self.html, re.I | re.S)
            if match:
                # `unescape` 用来把 HTML 转义字符恢复成正常文本。
                return unescape(match.group(1)).strip()

        return ""

    def _extract_first_match(self, patterns: list[str], flags: int = re.I | re.S) -> str:
        """
        给一组正则模式，返回第一个命中的结果。

        这是一个通用工具函数。
        这样很多字段都可以复用同一套“多模式尝试”的逻辑，
        避免每个方法都写一遍重复代码。
        """
        for pattern in patterns:
            match = re.search(pattern, self.html, flags)
            if match:
                # 有的正则写了分组，有的没写。
                # 这里统一兼容处理。
                value = match.group(1) if match.lastindex else match.group(0)
                return unescape(value).strip()
        return ""

    def _safe_json_loads(self, text: str) -> Any:
        """
        安全解析 JSON。

        为什么不直接 `json.loads(text)`？
        - 页面里的 JSON 可能格式异常
        - 一旦异常，不想让整个程序直接崩掉
        - 所以这里失败时返回 `None`
        """
        try:
            return json.loads(text)
        except Exception:
            return None

    def _walk_find_keys(
        self,
        obj: Any,
        target_keys: set[str],
        results: list[tuple[str, Any]],
        path: str = "",
    ) -> None:
        """
        递归遍历 JSON，查找目标字段。

        为什么要递归？
        因为 `__NEXT_DATA__` 往往是很多层嵌套的 JSON，
        比如你知道想找 `pageCount`，但你未必知道它在第几层。

        所以最稳的办法是：
        - 一层一层往下走
        - 看到目标 key 就记下来
        - 同时记录它的路径，方便后面调试
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                if key in target_keys:
                    results.append((current_path, value))
                self._walk_find_keys(value, target_keys, results, current_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                current_path = f"{path}[{i}]"
                self._walk_find_keys(item, target_keys, results, current_path)

    def extract_title(self) -> str:
        """
        提取页面 `<title>` 标签内容。
        """
        match = re.search(r"<title[^>]*>(.*?)</title>", self.html, re.I | re.S)
        if match:
            return unescape(match.group(1)).strip()
        return ""

    def extract_og_title(self) -> str:
        """
        提取 `og:title`。
        """
        return self._extract_meta("og:title")

    def extract_og_image(self) -> str:
        """
        提取 `og:image`。
        """
        return self._extract_meta("og:image")

    def extract_description(self) -> str:
        """
        提取 `meta name="description"`。
        """
        return self._extract_meta("description", attr="name")

    def extract_canonical_url(self) -> str:
        """
        提取 canonical 地址。

        canonical 可以理解成“这页内容的标准 URL”。
        """
        patterns = [
            r'<link[^>]+rel="canonical"[^>]+href="(.*?)"',
            r"<link[^>]+rel='canonical'[^>]+href='(.*?)'",
            r'<link[^>]+href="(.*?)"[^>]+rel="canonical"',
            r"<link[^>]+href='(.*?)'[^>]+rel='canonical'",
        ]
        return self._extract_first_match(patterns)

    def extract_artwork_id(self) -> str:
        """
        提取作品 ID。

        同一个作品 ID 可能出现在：
        - URL 里
        - 页面 JSON 里
        - 分享图片链接参数里

        所以这里会尝试多个入口。
        """
        patterns = [
            r'/artworks/(\d+)',
            r'"illustId":"?(\d+)"?',
            r'"artworkId":"?(\d+)"?',
            r'illust_id=(\d+)',
        ]
        return self._extract_first_match(patterns, flags=re.I)

    def extract_author_name(self) -> str:
        """
        提取作者名字。

        优先级大致是：
        1. 页面里显式显示的作者区域
        2. JSON 里的作者字段
        3. `og:title` 或 `<title>` 里带的作者名
        """
        patterns = [
            r'<a[^>]+data-gtm-value="\d+"[^>]+href="/users/\d+"><div[^>]+title="(.*?)"',
            r'<a[^>]+data-gtm-value="\d+"[^>]+href="/users/\d+"><div>(.*?)</div></a>',
            r'"authorName":"(.*?)"',
            r'"artistName":"(.*?)"',
            r'<meta[^>]+property="og:title"[^>]+content=".*? - (.*?)的插画 - pixiv"',
            r"<meta[^>]+property='og:title'[^>]+content='.*? - (.*?)的插画 - pixiv'",
            r'<title>.*? - (.*?)的插画 - pixiv</title>',
        ]

        author_name = self._extract_first_match(patterns)
        if author_name:
            return author_name

        # 如果前面的规则都没命中，就从标题结构里兜底提一次。
        title = self.extract_og_title() or self.extract_title()
        match = re.search(r" - (.*?)的插画 - pixiv", title)
        if match:
            return match.group(1).strip()

        return ""

    def extract_next_data(self) -> dict[str, Any]:
        """
        提取 Next.js 常见的 `__NEXT_DATA__`。

        这个字段往往比直接解析页面 DOM 更稳定，
        因为很多首屏数据都藏在这里。
        """
        match = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            self.html,
            re.I | re.S,
        )
        if not match:
            return {}

        # `<script>` 标签里的内容本身就是一整段 JSON。
        raw_json = match.group(1).strip()
        parsed = self._safe_json_loads(raw_json)
        return parsed if isinstance(parsed, dict) else {}

    def extract_server_preloaded_state(self) -> dict[str, Any]:
        """
        从 `__NEXT_DATA__` 里继续提取 `serverSerializedPreloadedState`。

        注意这个字段经常是“字符串形式的 JSON”，
        所以这里还要再做一次 JSON 解析。
        """
        next_data = self.extract_next_data()
        page_props = next_data.get("props", {}).get("pageProps", {})
        raw_state = page_props.get("serverSerializedPreloadedState")

        if not isinstance(raw_state, str) or not raw_state.strip():
            return {}

        parsed = self._safe_json_loads(raw_state)
        return parsed if isinstance(parsed, dict) else {}

    def extract_next_data_hits(self) -> list[tuple[str, Any]]:
        """
        在 `__NEXT_DATA__` 里查找可能有用的关键字段。

        这里不是直接取最终值，而是先把“命中线索”记录下来，
        这样页面结构变化时，更容易排查。
        """
        next_data = self.extract_next_data()
        if not next_data:
            return []

        results: list[tuple[str, Any]] = []
        target_keys = {
            "pageCount",
            "illustId",
            "userId",
            "userName",
            "tags",
            "tag",
            "urls",
            "original",
            "regular",
            "small",
            "thumb",
            "page_count",
        }
        self._walk_find_keys(next_data, target_keys, results)
        return results

    def extract_preloaded_state_hits(self) -> list[tuple[str, Any]]:
        """
        在 `serverSerializedPreloadedState` 中查找关键字段。
        """
        preloaded_state = self.extract_server_preloaded_state()
        if not preloaded_state:
            return []

        results: list[tuple[str, Any]] = []
        target_keys = {
            "pageCount",
            "illustId",
            "userId",
            "userName",
            "tags",
            "tag",
            "urls",
            "original",
            "regular",
            "small",
            "thumb",
            "page_count",
        }
        self._walk_find_keys(preloaded_state, target_keys, results)
        return results

    def extract_tags(self) -> list[str]:
        """
        从作品描述里提取标签。

        当前策略比较务实：
        - 先拿 `description`
        - 再从日文引号 `「xxx」` 中找词
        - 然后过滤掉链接、FANBOX 文案和明显噪声
        """
        tags: list[str] = []

        description = self.extract_description()
        quoted_tags = re.findall(r'「(.*?)」', description)

        for tag in quoted_tags:
            tag = tag.strip()
            if not tag:
                continue

            # 明显是链接的内容，不当作标签。
            if tag.startswith("http://") or tag.startswith("https://"):
                continue

            # FANBOX 推广信息通常不是真正作品标签。
            if "fanbox" in tag.lower():
                continue

            # 太长的文本大概率不是标签。
            if len(tag) > 40:
                continue

            # 去重，避免返回重复标签。
            if tag not in tags:
                tags.append(tag)

        return tags

    def extract_page_count(self) -> int:
        """
        提取作品页数。

        这里使用“多层兜底”思路：
        1. 先从结构化 JSON 中找明确页数
        2. 找不到再从 HTML 文本里找
        3. 再不行，就根据图片 URL 里的 `_p0 / _p1 / _p2` 推断
        4. 如果至少看到主图 `p0`，那就按单图作品返回 1
        """
        hits = self.extract_next_data_hits() + self.extract_preloaded_state_hits()

        for key_path, value in hits:
            if key_path.endswith("pageCount") or key_path.endswith("page_count"):
                try:
                    return int(value)
                except Exception:
                    # 有些值可能不是纯数字，这时继续走后面的兜底逻辑。
                    pass

        patterns = [
            r'"pageCount":\s*(\d+)',
            r'"illustPageCount":\s*(\d+)',
            r'"page_count":\s*(\d+)',
        ]

        value = self._extract_first_match(patterns, flags=re.I)
        if value.isdigit():
            return int(value)

        artwork_id = self.extract_artwork_id()
        if artwork_id:
            # 如果页面里出现了 `作品ID_p0 / p1 / p2` 这样的 URL，
            # 那么最大页码 + 1 就可以当作总页数。
            page_indexes = {
                int(index)
                for index in re.findall(rf"{re.escape(artwork_id)}_p(\d+)", self.html, re.I)
            }
            if page_indexes:
                return max(page_indexes) + 1

            # 如果只看到了主图 `p0` 的线索，也至少能判断它是单图作品。
            main_image_patterns = [
                rf'https://i\.pximg\.net[^"\']*{re.escape(artwork_id)}_p0[^"\']*',
                rf'https://i-cf\.pximg\.net[^"\']*{re.escape(artwork_id)}_p0[^"\']*',
                rf'https://embed\.pixiv\.net/artwork\.php\?illust_id={re.escape(artwork_id)}[^"\']*',
            ]
            if any(re.search(pattern, self.html, re.I) for pattern in main_image_patterns):
                return 1

        return 0

    def extract_possible_image_urls(self) -> list[str]:
        """
        提取“可能属于当前作品”的图片 URL。

        这里先尽量多找，但会做一些基础过滤：
        - 过滤头像
        - 过滤特别小的缩略图
        - 去重
        """
        artwork_id = self.extract_artwork_id()
        patterns: list[str] = []

        if artwork_id:
            # 如果已经知道作品 ID，就尽量只抓和这个作品相关的图片地址。
            escaped_artwork_id = re.escape(artwork_id)
            patterns.extend(
                [
                    rf'https://i\.pximg\.net[^\s"\']*{escaped_artwork_id}_p\d+[^\s"\']*',
                    rf'https://i-cf\.pximg\.net[^\s"\']*{escaped_artwork_id}_p\d+[^\s"\']*',
                    rf'https://embed\.pixiv\.net/artwork\.php\?illust_id={escaped_artwork_id}[^\s"\']*',
                    rf'https://[^"\']*pixiv\.net/artwork\.php\?illust_id={escaped_artwork_id}[^\s"\']*',
                ]
            )
        else:
            # 如果作品 ID 都没提出来，就只能更宽松地全局扫描可能图片地址。
            patterns.extend(
                [
                    r'https://i\.pximg\.net[^\s"\']+',
                    r'https://i-cf\.pximg\.net[^\s"\']+',
                    r'https://embed\.pixiv\.net[^\s"\']+',
                    r'https://[^"\']*pximg\.net[^"\']+',
                    r'https://[^"\']*pixiv\.net/artwork\.php[^"\']+',
                ]
            )

        results: list[str] = []

        for pattern in patterns:
            matches = re.findall(pattern, self.html, re.I | re.S)
            for url in matches:
                # 把 HTML / JSON 里的转义 URL 恢复成正常 URL。
                url = unescape(url.replace("\\/", "/").replace("\\u0026", "&")).rstrip("\\").strip()

                if not url:
                    continue

                # 头像图片不是作品图，过滤掉。
                if "/user-profile/" in url:
                    continue

                # 一些很小的头像缩略图会以 `_50` / `_170` 结尾，也过滤掉。
                if re.search(r'_(50|170)\.(jpg|jpeg|png|webp)$', url, re.I):
                    continue

                # 去重，避免后面下载器拿到一堆重复地址。
                if url not in results:
                    results.append(url)

        return results

    def extract_user_id(self) -> str:
        """
        提取作者用户 ID。

        这里要格外小心，因为页面里还常常包含“当前登录用户”的 ID。
        如果匹配太宽，很容易误抓成你自己的账号 ID。

        所以这里优先找“作者区域附近”的用户 ID 线索。
        """
        author_patterns = [
            r'data-gtm-user-id="(\d+)"\s+data-click-action="click"\s+data-click-label="follow"',
            r'href="/users/(\d+)/artworks"[^>]*>查看作品目录',
            r'<a[^>]+data-gtm-value="(\d+)"[^>]+href="/users/\1"',
            r'"authorId":"?(\d+)"?',
        ]

        user_id = self._extract_first_match(author_patterns, flags=re.I | re.S)
        if user_id:
            return user_id

        # 如果页面里没有显式的作者 ID，再结合作者名字做更谨慎的兜底匹配。
        author_name = self.extract_author_name()
        if author_name:
            escaped_author_name = re.escape(author_name)
            name_bound_patterns = [
                rf'<a[^>]+href="/users/(\d+)"[^>]*>\s*<div[^>]*>{escaped_author_name}</div>',
                rf'data-gtm-user-id="(\d+)"[^>]*>\s*已关注',
            ]
            user_id = self._extract_first_match(name_bound_patterns, flags=re.I | re.S)
            if user_id:
                return user_id

        return ""

    def extract_full_info(self) -> ArtworkInfo:
        """
        一次性提取完整作品信息，并打包成 `ArtworkInfo` 对象。

        这样外部调用时只需要调用这一个方法，
        就能拿到统一格式的完整结果。
        """
        next_data = self.extract_next_data()
        next_data_hits = self.extract_next_data_hits() + self.extract_preloaded_state_hits()

        # 这里相当于把“网页原始信息”整理成“项目内部标准数据结构”。
        return ArtworkInfo(
            title=self.extract_title(),
            og_title=self.extract_og_title(),
            og_image=self.extract_og_image(),
            description=self.extract_description(),
            canonical_url=self.extract_canonical_url(),
            artwork_id=self.extract_artwork_id(),
            user_id=self.extract_user_id(),
            author_name=self.extract_author_name(),
            tags=self.extract_tags(),
            page_count=self.extract_page_count(),
            possible_image_urls=self.extract_possible_image_urls(),
            has_next_data=bool(next_data),
            # 调试信息先只保留前 30 条，避免结果太长。
            next_data_hits=next_data_hits[:30],
        )
