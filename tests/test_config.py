import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
