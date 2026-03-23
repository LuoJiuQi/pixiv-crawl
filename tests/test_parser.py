import unittest
from pathlib import Path

from app.parser.artwork_parser import ArtworkParser
from app.schemas.artwork import ArtworkInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_HTML_DIR = PROJECT_ROOT / "data" / "temp" / "html"


class ArtworkParserTestCase(unittest.TestCase):
    def test_extract_full_info_from_saved_html_samples(self) -> None:
        # 这里故意只保留一个代表性样本。
        # 这样仓库更轻，别人拉下来也不会带太多调试文件，
        # 但解析器仍然有最基本的回归测试可跑。
        case = {
            "file_name": "artwork_142522397.html",
            "artwork_id": "142522397",
            "expected_user_id": "",
        }

        html = (TEMP_HTML_DIR / case["file_name"]).read_text(encoding="utf-8")
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
        self.assertNotEqual(info.user_id, "79004865")

        for url in info.possible_image_urls:
            self.assertTrue(
                case["artwork_id"] in url or f"illust_id={case['artwork_id']}" in url
            )


if __name__ == "__main__":
    unittest.main()
