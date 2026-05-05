import json
import unittest
from tempfile import TemporaryDirectory

from app.db.download_record_repository import DownloadRecord
from app.services.record_exporter import build_record_export_path, export_records


class RecordExporterTestCase(unittest.TestCase):
    def test_build_record_export_path_contains_prefix_and_status(self) -> None:
        path = build_record_export_path(
            "./data/exports",
            prefix="archived_records",
            status="completed",
            file_format="json",
        )

        self.assertEqual(path.suffix, ".json")
        self.assertIn("archived_records_completed_", path.name)

    def test_export_records_writes_json(self) -> None:
        records = [DownloadRecord(artwork_id="100", status="completed")]

        with TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/records.json"
            exported = export_records(records, output_path, file_format="json")
            payload = json.loads(exported.read_text(encoding="utf-8"))

        self.assertEqual(payload[0]["artwork_id"], "100")

    def test_export_records_writes_txt(self) -> None:
        records = [
            DownloadRecord(
                artwork_id="200",
                status="failed",
                error_type="download",
                title="sample",
                author_name="author",
                page_count=1,
                download_count=0,
                created_at="2026-03-23T12:00:00",
                updated_at="2026-03-23T12:00:00",
                error_message="download failed",
            )
        ]

        with TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/records.txt"
            exported = export_records(records, output_path, file_format="txt")
            content = exported.read_text(encoding="utf-8")

        self.assertIn("artwork_id = 200", content)
        self.assertIn("created_at = 2026-03-23T12:00:00", content)


if __name__ == "__main__":
    unittest.main()
