import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import Settings


class SettingsTestCase(unittest.TestCase):
    def test_debug_flags_default_to_false_without_env_sources(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertFalse(settings.save_debug_artifacts)
        self.assertFalse(settings.verbose_debug_output)

    def test_debug_flags_can_be_enabled_via_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SAVE_DEBUG_ARTIFACTS": "true",
                "VERBOSE_DEBUG_OUTPUT": "true",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertTrue(settings.save_debug_artifacts)
        self.assertTrue(settings.verbose_debug_output)

    def test_scheduled_run_defaults_are_disabled_and_normalized(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertFalse(settings.scheduled_run_enabled)
        self.assertEqual(settings.scheduled_run_time, "02:00")
        self.assertFalse(settings.scheduled_retry_failed_enabled)
        self.assertEqual(settings.scheduled_retry_failed_limit, 20)

    def test_scheduled_run_time_can_be_loaded_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SCHEDULED_RUN_ENABLED": "true",
                "SCHEDULED_RUN_TIME": "6:30",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertTrue(settings.scheduled_run_enabled)
        self.assertEqual(settings.scheduled_run_time, "06:30")

    def test_scheduled_run_time_rejects_invalid_24_hour_value(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SCHEDULED_RUN_TIME": "25:99",
            },
            clear=True,
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

    def test_scheduled_retry_failed_config_can_be_loaded_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SCHEDULED_RETRY_FAILED_ENABLED": "true",
                "SCHEDULED_RETRY_FAILED_LIMIT": "15",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertTrue(settings.scheduled_retry_failed_enabled)
        self.assertEqual(settings.scheduled_retry_failed_limit, 15)

    def test_scheduled_retry_failed_limit_rejects_negative_value(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SCHEDULED_RETRY_FAILED_LIMIT": "-1",
            },
            clear=True,
        ):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)


if __name__ == "__main__":
    unittest.main()
