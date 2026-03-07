import json
import os
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"

DEFAULTS = {
    "whisper_device": "cpu",
    "whisper_compute_type": "auto",
    "whisper_model": "base.en",
}


def get_settings() -> dict[str, str]:
    settings = {
        "whisper_device": os.environ.get("WHISPER_DEVICE", DEFAULTS["whisper_device"]),
        "whisper_compute_type": os.environ.get(
            "WHISPER_COMPUTE_TYPE", DEFAULTS["whisper_compute_type"]
        ),
        "whisper_model": os.environ.get("WHISPER_MODEL", DEFAULTS["whisper_model"]),
    }
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text())
            for key in DEFAULTS:
                if key in saved:
                    settings[key] = saved[key]
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict[str, str]) -> None:
    data = {key: settings[key] for key in DEFAULTS if key in settings}
    SETTINGS_FILE.write_text(json.dumps(data, indent=2) + "\n")
