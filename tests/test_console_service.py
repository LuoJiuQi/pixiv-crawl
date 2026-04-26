import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from app.services import console_service


class ConsoleServiceTestCase(unittest.TestCase):
    def test_show_menu_prints_numbered_options(self) -> None:
        with patch("builtins.print") as mocked_print:
            console_service.show_menu(["批量抓取作品", "查看历史记录"])

        mocked_print.assert_has_calls(
            [
                call("请选择操作："),
                call("1. 批量抓取作品"),
                call("2. 查看历史记录"),
            ]
        )

    def test_show_summary_prints_key_value_rows(self) -> None:
        with patch("builtins.print") as mocked_print:
            console_service.show_summary(
                "当前数据库记录概览",
                [("completed", 3), ("failed", 1)],
            )

        mocked_print.assert_has_calls(
            [
                call("当前数据库记录概览："),
                call("completed = 3"),
                call("failed = 1"),
            ]
        )

    def test_show_list_handles_empty_items(self) -> None:
        with patch("builtins.print") as mocked_print:
            console_service.show_list("失败详情", [])

        mocked_print.assert_has_calls(
            [
                call("失败详情："),
                call("(空)"),
            ]
        )

    def test_pause_before_exit_reads_enter(self) -> None:
        with patch("builtins.input", return_value="") as mocked_input:
            console_service.pause_before_exit()

        mocked_input.assert_called_once_with("按回车键关闭浏览器...")

    def test_show_json_prints_pretty_json_without_ascii_escaping(self) -> None:
        with patch("builtins.print") as mocked_print:
            console_service.show_json({"message": "环境正常", "ok": True})

        mocked_print.assert_called_once_with('{\n  "message": "环境正常",\n  "ok": true\n}')

    def test_write_json_file_creates_parent_directories_and_writes_utf8_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "doctor" / "report.json"

            console_service.write_json_file({"message": "环境正常", "ok": True}, str(output_path))

            self.assertTrue(output_path.exists())
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                '{\n  "message": "环境正常",\n  "ok": true\n}',
            )


if __name__ == "__main__":
    unittest.main()
