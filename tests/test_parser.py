import unittest
from pathlib import Path

from app.parser.artwork_parser import ArtworkParser
from app.schemas.artwork import ArtworkInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_HTML_DIR = PROJECT_ROOT / "data" / "temp" / "html"


class ArtworkParserTestCase(unittest.TestCase):
    def test_extract_full_info_from_saved_html_samples(self) -> None:
        cases = [
            {
                "file_name": "artwork_142463788.html",
                "artwork_id": "142463788",
                "author_name": "律空rikuu",
                "title_fragment": "ヤチいろ",
                "expected_user_id": "",
            },
            {
                "file_name": "artwork_142501413.html",
                "artwork_id": "142501413",
                "author_name": "ミョワ",
                "title_fragment": "ナツカ",
                "expected_user_id": "",
            },
            {
                "file_name": "artwork_142543623.html",
                "artwork_id": "142543623",
                "author_name": "mignon",
                "title_fragment": "引きこもりの妹が制服を着てみた回",
                "expected_user_id": "24234",
            },
        ]

        for case in cases:
            with self.subTest(file_name=case["file_name"]):
                html = (TEMP_HTML_DIR / case["file_name"]).read_text(encoding="utf-8")

                info = ArtworkParser(html).extract_full_info()

                self.assertIsInstance(info, ArtworkInfo)
                self.assertEqual(info.artwork_id, case["artwork_id"])
                self.assertIn(case["title_fragment"], info.title)
                self.assertEqual(info.author_name, case["author_name"])
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
