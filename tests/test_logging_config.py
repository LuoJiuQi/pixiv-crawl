import os
import logging
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core import logging_config


class LoggingConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(logging_config.LOGGER_ROOT_NAME)
        self.original_handlers = list(self.logger.handlers)
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate
        self._clear_current_handlers()

    def tearDown(self) -> None:
        self._clear_current_handlers()
        self.logger.handlers = self.original_handlers
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate

    def _clear_current_handlers(self) -> None:
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()

    def test_configure_logging_uses_rotating_file_handler(self) -> None:
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "app.log"

            with patch.object(logging_config.settings, "log_path", str(log_path)), patch.object(
                logging_config.settings,
                "log_max_bytes",
                2048,
            ), patch.object(
                logging_config.settings,
                "log_backup_count",
                7,
            ), patch.object(
                logging_config.settings,
                "verbose_debug_output",
                False,
            ):
                logger = logging_config.configure_logging()

            try:
                file_handlers = [
                    handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)
                ]
                self.assertEqual(len(file_handlers), 1)

                file_handler = file_handlers[0]
                self.assertTrue(os.path.samefile(file_handler.baseFilename, log_path))
                self.assertEqual(file_handler.maxBytes, 2048)
                self.assertEqual(file_handler.backupCount, 7)
                self.assertEqual(file_handler.level, logging.INFO)
            finally:
                self._clear_current_handlers()

    def test_configure_logging_is_idempotent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "app.log"

            with patch.object(logging_config.settings, "log_path", str(log_path)), patch.object(
                logging_config.settings,
                "log_max_bytes",
                4096,
            ), patch.object(
                logging_config.settings,
                "log_backup_count",
                3,
            ), patch.object(
                logging_config.settings,
                "verbose_debug_output",
                True,
            ):
                first_logger = logging_config.configure_logging()
                second_logger = logging_config.configure_logging()

            try:
                self.assertIs(first_logger, second_logger)
                self.assertEqual(len(second_logger.handlers), 2)
                self.assertEqual(second_logger.level, logging.DEBUG)
                self.assertEqual(
                    len(
                        [
                            handler
                            for handler in second_logger.handlers
                            if isinstance(handler, RotatingFileHandler)
                        ]
                    ),
                    1,
                )
            finally:
                self._clear_current_handlers()

    def test_configure_logging_removes_file_handler_when_log_path_is_empty(self) -> None:
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "app.log"

            with patch.object(logging_config.settings, "log_path", str(log_path)), patch.object(
                logging_config.settings,
                "log_max_bytes",
                4096,
            ), patch.object(
                logging_config.settings,
                "log_backup_count",
                3,
            ):
                logging_config.configure_logging()

            with patch.object(logging_config.settings, "log_path", ""):
                logger = logging_config.configure_logging()

            try:
                self.assertEqual(
                    len(
                        [
                            handler
                            for handler in logger.handlers
                            if isinstance(handler, RotatingFileHandler)
                        ]
                    ),
                    0,
                )
            finally:
                self._clear_current_handlers()


if __name__ == "__main__":
    unittest.main()
