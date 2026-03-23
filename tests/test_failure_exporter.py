import json
import unittest
from tempfile import TemporaryDirectory

from app.services.failure_exporter import build_failure_export_path, export_failure_records


class FailureExporterTestCase(unittest.TestCase):
    def test_build_failure_export_path_contains_error_type_and_format(self) -> None:
        path = build_failure_export_path("./data/exports", error_type="timeout", file_format="json")

        self.assertEqual(path.suffix, ".json")
        self.assertIn("failed_records_timeout_", path.name)

    def test_export_failure_records_writes_json(self) -> None:
        records = [
            {
                "artwork_id": "100",
                "status": "failed",
                "error_type": "timeout",
                "error_message": "timeout",
            }
        ]

        with TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/failed.json"
            exported = export_failure_records(records, output_path, file_format="json")
            payload = json.loads(exported.read_text(encoding="utf-8"))

        self.assertEqual(payload[0]["artwork_id"], "100")
        self.assertEqual(payload[0]["error_type"], "timeout")

    def test_export_failure_records_writes_txt(self) -> None:
        records = [
            {
                "artwork_id": "200",
                "status": "failed",
                "error_type": "download",
                "title": "sample",
                "author_name": "author",
                "updated_at": "2026-03-23T12:00:00",
                "error_message": "download failed",
            }
        ]

        with TemporaryDirectory() as temp_dir:
            output_path = f"{temp_dir}/failed.txt"
            exported = export_failure_records(records, output_path, file_format="txt")
            content = exported.read_text(encoding="utf-8")

        self.assertIn("artwork_id = 200", content)
        self.assertIn("error_type = download", content)


if __name__ == "__main__":
    unittest.main()
