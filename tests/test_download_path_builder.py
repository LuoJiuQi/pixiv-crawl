import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.downloader.download_path_builder import DownloadPathBuilder
from app.schemas.artwork import ArtworkInfo


class DownloadPathBuilderTestCase(unittest.TestCase):
    def test_build_author_folder_name_prefers_author_name_and_user_id(self) -> None:
        builder = DownloadPathBuilder("D:/tmp")
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
        )

        folder_name = builder.build_author_folder_name(artwork)

        self.assertEqual(folder_name, "mignon_998877")

    def test_build_file_stem_uses_title_for_single_page_artwork(self) -> None:
        builder = DownloadPathBuilder("D:/tmp")
        artwork = ArtworkInfo(
            artwork_id="123456789",
            title="引きこもりの妹が制服を着てみた回",
            page_count=1,
        )

        stem = builder.build_file_stem(artwork, page_index=0, total_pages=1)

        self.assertEqual(stem, "引きこもりの妹が制服を着てみた回__123456789")

    def test_build_file_stem_adds_page_suffix_for_multi_page_artwork(self) -> None:
        builder = DownloadPathBuilder("D:/tmp")
        artwork = ArtworkInfo(
            artwork_id="123456789",
            title="制服まとめ",
            page_count=3,
        )

        stem = builder.build_file_stem(artwork, page_index=1, total_pages=3)

        self.assertEqual(stem, "制服まとめ__123456789_p1")

    def test_build_file_stem_keeps_artworks_unique_even_when_titles_match(self) -> None:
        builder = DownloadPathBuilder("D:/tmp")
        first_artwork = ArtworkInfo(
            artwork_id="111111111",
            title="同名作品",
            page_count=1,
        )
        second_artwork = ArtworkInfo(
            artwork_id="222222222",
            title="同名作品",
            page_count=1,
        )

        first_stem = builder.build_file_stem(first_artwork, page_index=0, total_pages=1)
        second_stem = builder.build_file_stem(second_artwork, page_index=0, total_pages=1)

        self.assertNotEqual(first_stem, second_stem)

    def test_infer_extension_prefers_image_content_type_over_php_url(self) -> None:
        builder = DownloadPathBuilder("D:/tmp")

        extension = builder.infer_extension(
            "https://embed.pixiv.net/artwork.php?illust_id=142522397&mdate=1774000000",
            content_type="image/jpeg",
        )

        self.assertEqual(extension, ".jpg")

    def test_find_existing_file_for_page_matches_any_known_extension(self) -> None:
        artwork = ArtworkInfo(
            artwork_id="123456789",
            user_id="998877",
            author_name="mignon",
            title="制服まとめ",
            page_count=2,
        )

        with TemporaryDirectory() as temp_dir:
            builder = DownloadPathBuilder(temp_dir)
            author_dir = Path(temp_dir) / builder.build_author_folder_name(artwork)
            author_dir.mkdir(parents=True, exist_ok=True)
            saved_path = author_dir / "制服まとめ__123456789_p1.png"
            saved_path.write_bytes(b"ok")

            matched = builder.find_existing_file_for_page(
                artwork,
                page_index=1,
                total_pages=2,
            )

        self.assertEqual(matched, saved_path)


if __name__ == "__main__":
    unittest.main()
