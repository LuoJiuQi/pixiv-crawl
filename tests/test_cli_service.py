import unittest

from app.services.cli_service import parse_user_id


class CliServiceTestCase(unittest.TestCase):
    def test_parse_user_id_supports_plain_numeric_id(self) -> None:
        self.assertEqual(parse_user_id("12345678"), "12345678")

    def test_parse_user_id_supports_users_url(self) -> None:
        raw_text = "https://www.pixiv.net/users/87654321"

        self.assertEqual(parse_user_id(raw_text), "87654321")

    def test_parse_user_id_supports_old_member_url(self) -> None:
        raw_text = "https://www.pixiv.net/member.php?id=11223344"

        self.assertEqual(parse_user_id(raw_text), "11223344")

    def test_parse_user_id_returns_empty_for_invalid_text(self) -> None:
        self.assertEqual(parse_user_id("hello world"), "")


if __name__ == "__main__":
    unittest.main()
