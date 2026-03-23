import unittest

from main import parse_artwork_ids


class MainInputParsingTestCase(unittest.TestCase):
    def test_parse_artwork_ids_supports_multiple_separators(self) -> None:
        raw_text = "142463788, 142543623 142522397\n142501413；142463788"

        artwork_ids = parse_artwork_ids(raw_text)

        self.assertEqual(
            artwork_ids,
            ["142463788", "142543623", "142522397", "142501413"],
        )

    def test_parse_artwork_ids_supports_pixiv_urls(self) -> None:
        raw_text = """
        https://www.pixiv.net/artworks/142463788
        https://www.pixiv.net/en/artworks/142543623
        """

        artwork_ids = parse_artwork_ids(raw_text)

        self.assertEqual(artwork_ids, ["142463788", "142543623"])

    def test_parse_artwork_ids_returns_empty_for_invalid_text(self) -> None:
        raw_text = "hello world, not an artwork id"

        artwork_ids = parse_artwork_ids(raw_text)

        self.assertEqual(artwork_ids, [])


if __name__ == "__main__":
    unittest.main()
