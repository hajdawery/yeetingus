"""
config.py — persisted user settings.

Stored as JSON next to the app in %LOCALAPPDATA%\\YEETingus\\settings.json, so it
survives reinstalls (install.py only replaces the exe and launcher).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from version import APP_NAME  # noqa: E402

_APP_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)

SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")


def default_download_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "yeet_downloads")


DEFAULTS: dict = {
    "download_dir": default_download_dir(),
}


def load() -> dict:
    """Read settings, falling back to defaults for anything missing or broken."""
    cfg = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for key in DEFAULTS:
                value = stored.get(key)
                if isinstance(value, str) and value.strip():
                    cfg[key] = value
    except (OSError, ValueError):
        pass  # first run, or a corrupt file — defaults are fine
    return cfg


def save(cfg: dict) -> str:
    """Persist settings. Returns the path written."""
    os.makedirs(_APP_DIR, exist_ok=True)
    merged = {key: cfg.get(key, DEFAULTS[key]) for key in DEFAULTS}
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
    os.replace(tmp, SETTINGS_PATH)  # atomic, so a crash can't truncate settings
    return SETTINGS_PATH
