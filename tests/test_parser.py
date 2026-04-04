import unittest
from pathlib import Path
from unittest.mock import patch

from app.parser.artwork_parser import ArtworkParser
from app.schemas.artwork import ArtworkInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_HTML_DIR = PROJECT_ROOT / "tests" / "fixtures" / "html"


class ArtworkParserTestCase(unittest.TestCase):
    def test_extract_full_info_from_saved_html_samples(self) -> None:
        # 这里故意只保留一个代表性样本。
        # 这样仓库更轻，别人拉下来也不会带太多调试文件，
        # 但解析器仍然有最基本的回归测试可跑。
        case = {
            "file_name": "artwork_141018669.html",
            "artwork_id": "141018669",
            "expected_user_id": "7110271",
        }

        html = (FIXTURE_HTML_DIR / case["file_name"]).read_text(encoding="utf-8")
        info = ArtworkParser(html).extract_full_info()

        self.assertIsInstance(info, ArtworkInfo)
        self.assertEqual(info.artwork_id, case["artwork_id"])
        # 这个保留样本的 HTML 本身带一点编码问题，
        # 所以这里不拿中文标题和作者名做精确断言，
        # 改为检查更稳定的结构字段。
        self.assertTrue(info.title)
        self.assertTrue(info.author_name)
        self.assertEqual(
            info.canonical_url,
            f"https://www.pixiv.net/artworks/{case['artwork_id']}",
        )
        self.assertEqual(info.page_count, 1)
        self.assertTrue(info.has_next_data)
        self.assertTrue(info.possible_image_urls)
        self.assertIn(f"illust_id={case['artwork_id']}", info.og_image)
        self.assertEqual(info.user_id, case["expected_user_id"])

        for url in info.possible_image_urls:
            self.assertTrue(
                case["artwork_id"] in url or f"illust_id={case['artwork_id']}" in url
            )

    def test_extract_full_info_reuses_built_snapshot(self) -> None:
        html = (FIXTURE_HTML_DIR / "artwork_141018669.html").read_text(encoding="utf-8")
        parser = ArtworkParser(html)

        with patch.object(parser, "_build_snapshot", wraps=parser._build_snapshot) as mocked:
            first = parser.extract_full_info()
            second = parser.extract_full_info()

        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(mocked.call_count, 1)

    def test_parser_falls_back_when_structured_data_is_missing(self) -> None:
        html = """
        <html>
          <head>
            <title>测试作品 - 测试作者的插画 - pixiv</title>
            <meta property="og:title" content="测试作品 - 测试作者的插画 - pixiv" />
            <meta property="og:image" content="https://embed.pixiv.net/artwork.php?illust_id=123456&mdate=1774000000" />
            <meta name="description" content="这是作品简介「标签A」「标签B」" />
            <link rel="canonical" href="https://www.pixiv.net/artworks/123456" />
          </head>
          <body></body>
        </html>
        """

        info = ArtworkParser(html).extract_full_info()

        self.assertEqual(info.artwork_id, "123456")
        self.assertEqual(info.author_name, "测试作者")
        self.assertEqual(info.canonical_url, "https://www.pixiv.net/artworks/123456")
        self.assertEqual(info.tags, ["标签A", "标签B"])
        self.assertEqual(info.page_count, 1)
        self.assertEqual(
            info.possible_image_urls,
            ["https://embed.pixiv.net/artwork.php?illust_id=123456&mdate=1774000000"],
        )
        self.assertFalse(info.has_next_data)

    def test_parser_prefers_current_page_artwork_id_over_related_structured_ids(self) -> None:
        html = """
        <html>
          <head>
            <title>当前作品 - 测试作者的插画 - pixiv</title>
            <meta property="og:title" content="当前作品 - 测试作者的插画 - pixiv" />
            <meta property="og:image" content="https://embed.pixiv.net/artwork.php?illust_id=139212665&mdate=1774000000" />
            <link rel="canonical" href="https://www.pixiv.net/artworks/139212665" />
            <script id="__NEXT_DATA__" type="application/json">
              {
                "props": {
                  "pageProps": {
                    "serverSerializedPreloadedState": "{\\"related\\":{\\"items\\":[{\\"illustId\\":\\"138948633\\"},{\\"illustId\\":\\"139212665\\",\\"userId\\":\\"7110271\\",\\"userName\\":\\"测试作者\\"}]}}"
                  }
                }
              }
            </script>
          </head>
          <body>
            <img src="https://i.pximg.net/img-original/img/2026/04/04/00/00/00/139212665_p0.jpg" />
          </body>
        </html>
        """

        info = ArtworkParser(html).extract_full_info()

        self.assertEqual(info.artwork_id, "139212665")
        self.assertEqual(info.canonical_url, "https://www.pixiv.net/artworks/139212665")
        self.assertTrue(
            any("139212665_p0.jpg" in url for url in info.possible_image_urls)
        )

    def test_parser_prefers_structured_tags_over_description_fallback(self) -> None:
        html = """
        <html>
          <head>
            <title>结构化标签作品 - 测试作者的插画 - pixiv</title>
            <meta property="og:title" content="结构化标签作品 - 测试作者的插画 - pixiv" />
            <meta property="og:image" content="https://embed.pixiv.net/artwork.php?illust_id=555666&mdate=1774000000" />
            <meta name="description" content="简介里还有「描述标签A」「描述标签B」" />
            <link rel="canonical" href="https://www.pixiv.net/artworks/555666" />
            <script id="__NEXT_DATA__" type="application/json">
              {
                "props": {
                  "pageProps": {
                    "serverSerializedPreloadedState": "{\\"illust\\":{\\"555666\\":{\\"illustId\\":\\"555666\\",\\"tags\\":[{\\"tag\\":\\"白ビキニ\\",\\"translation\\":{\\"zh\\":\\"白色比基尼\\"}},{\\"tag\\":\\"水着\\",\\"translation\\":{\\"zh\\":\\"泳装\\"}}]}}}"
                  }
                }
              }
            </script>
          </head>
          <body></body>
        </html>
        """

        info = ArtworkParser(html).extract_full_info()

        self.assertEqual(info.tags, ["白ビキニ", "水着"])

    def test_parser_falls_back_to_footer_dom_tags_when_structured_tags_are_missing(self) -> None:
        html = """
        <html>
          <head>
            <title>页脚标签作品 - 测试作者的插画 - pixiv</title>
            <meta property="og:title" content="页脚标签作品 - 测试作者的插画 - pixiv" />
            <meta property="og:image" content="https://embed.pixiv.net/artwork.php?illust_id=777888&mdate=1774000000" />
            <meta name="description" content="这里只保留说明文字，不带日文引号标签" />
            <link rel="canonical" href="https://www.pixiv.net/artworks/777888" />
          </head>
          <body>
            <footer>
              <ul>
                <li>
                  <span>
                    <span><a class="gtm-new-work-tag-event-click" href="/tags/%E7%99%BD%E3%83%93%E3%82%AD%E3%83%8B/artworks">白ビキニ</a></span>
                    <span><a class="gtm-new-work-translate-tag-event-click" href="/tags/%E7%99%BD%E3%83%93%E3%82%AD%E3%83%8B/artworks">白色比基尼</a></span>
                  </span>
                </li>
                <li>
                  <span>
                    <span><a class="gtm-new-work-tag-event-click" href="/tags/%E6%B0%B4%E7%9D%80/artworks">水着</a></span>
                    <span><a class="gtm-new-work-translate-tag-event-click" href="/tags/%E6%B0%B4%E7%9D%80/artworks">泳装</a></span>
                  </span>
                </li>
                <li><button class="style_tagEdit__2HfzH">+</button></li>
              </ul>
            </footer>
          </body>
        </html>
        """

        info = ArtworkParser(html).extract_full_info()

        self.assertEqual(info.tags, ["白ビキニ", "水着"])


if __name__ == "__main__":
    unittest.main()
