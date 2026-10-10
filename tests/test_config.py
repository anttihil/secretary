import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class SettingsPersistenceTests(unittest.TestCase):
    def test_configured_settings_survive_release_directory_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "shared/settings.json"
            target.parent.mkdir()
            try:
                with patch.dict(os.environ, {"SETTINGS_FILE": str(target)}):
                    importlib.reload(config)
                    config.save_settings(
                        {
                            "whisper_model": "tiny.en",
                            "whisper_device": "cpu",
                            "whisper_compute_type": "int8",
                        }
                    )
                    importlib.reload(config)
                    self.assertEqual(config.get_settings()["whisper_model"], "tiny.en")
                    self.assertEqual(
                        json.loads(target.read_text())["whisper_compute_type"], "int8"
                    )
            finally:
                importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
