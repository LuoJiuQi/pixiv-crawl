import unittest

from app.services.cli_service import parse_artwork_ids
from app.services.runtime_args_service import (
    action_requires_direct_artwork_input,
    parse_runtime_arguments,
)


class RuntimeArgsServiceTestCase(unittest.TestCase):
    def test_action_requires_direct_artwork_input_skips_following_mode(self) -> None:
        self.assertFalse(action_requires_direct_artwork_input("crawl_following"))

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

    def test_parse_runtime_arguments_supports_crawl_inputs(self) -> None:
        args = parse_runtime_arguments(
            ["crawl", "142463788", "https://www.pixiv.net/artworks/142543623"]
        )

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "crawl")
        self.assertEqual(args.artwork_ids, ["142463788", "142543623"])

    def test_parse_runtime_arguments_supports_crawl_author_options(self) -> None:
        args = parse_runtime_arguments(
            [
                "crawl-author",
                "https://www.pixiv.net/users/123456",
                "--limit",
                "20",
                "--update-mode",
                "full",
                "--completed-streak-limit",
                "15",
            ]
        )

        from app.services.cli_service import AuthorCollectOptions
        self.assertIsNotNone(args)
        self.assertEqual(args.action, "crawl_author")
        self.assertEqual(
            args.author_request,
            AuthorCollectOptions(
                user_id="123456",
                limit=20,
                update_mode="full",
                completed_streak_limit=15,
            ),
        )

    def test_parse_runtime_arguments_supports_crawl_following_options(self) -> None:
        args = parse_runtime_arguments(
            ["crawl-following", "--limit", "3", "--completed-streak-limit", "15"]
        )

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "crawl_following")
        self.assertEqual(args.following_limit, 3)
        self.assertEqual(args.completed_streak_limit, 15)

    def test_parse_runtime_arguments_supports_doctor_command(self) -> None:
        args = parse_runtime_arguments(["doctor"])

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "doctor")

    def test_parse_runtime_arguments_supports_doctor_strict_mode(self) -> None:
        args = parse_runtime_arguments(["doctor", "--strict"])

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "doctor")
        self.assertTrue(args.strict)

    def test_parse_runtime_arguments_supports_doctor_json_output(self) -> None:
        args = parse_runtime_arguments(["doctor", "--json"])

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "doctor")
        self.assertTrue(args.json_output)

    def test_parse_runtime_arguments_supports_doctor_output_file(self) -> None:
        args = parse_runtime_arguments(["doctor", "--output", "data/doctor.json"])

        self.assertIsNotNone(args)
        self.assertEqual(args.action, "doctor")
        self.assertEqual(args.output, "data/doctor.json")
