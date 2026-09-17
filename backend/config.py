"""
config.py — persisted user settings.

Stored as JSON in the platform's per-user application-data folder
(%LOCALAPPDATA%\\YEETingus on Windows, ~/Library/Application Support/YEETingus on
macOS), so it survives reinstalls — install.py only replaces the app and
launcher.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_paths as _pp  # noqa: E402
from version import APP_NAME  # noqa: E402

_APP_DIR = _pp.app_data_dir()

SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")

# Re-exported so callers don't need to know which module owns the platform
# branching; this was config's own API before the split.
videos_dir = _pp.videos_dir


def default_download_dir() -> str:
    """Clips live under the user's videos folder, in an app-named subfolder.

    Deliberately NOT %TEMP%: Disk Cleanup and Storage Sense delete temp files,
    which would take media that timelines still reference offline.
    """
    return os.path.join(videos_dir(), APP_NAME)


# Where clips used to go. A stored value equal to this means the user never chose
# it, so it can be upgraded to the new default; anything else is their choice and
# is left alone.
LEGACY_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "yeet_downloads")


# Clip lengths offered in Settings, in seconds. Any positive int is accepted from
# a hand-edited file; these are just the presets shown as buttons.
LENGTH_CHOICES = (15, 30, 60, 90)
MAX_LENGTH = 86400  # a day — beyond this it's a typo, not an intention

EDITORS = ("resolve", "premiere")
# What Resolve does with a clip whose frame rate differs from the timeline's;
# keys of resolve_bridge.RETIME_PROCESSES.
RETIMES = ("project", "nearest", "blend", "optical")
CONFORMS = ("sharp", "blend", "off")

DEFAULTS: dict = {
    "download_dir": default_download_dir(),
    # End point applied at launch, measured from the in point.
    "default_length": 30,
    # Where clips are pasted: DaVinci Resolve (its Python API) or Premiere Pro
    # (through the YEETingus UXP panel).
    "editor": "resolve",
    # Set once the first-run setup has been through (or skipped).
    "onboarded": False,
    # Resolve only (Premiere's panel API has no time-interpolation control).
    "retime": "blend",
    # Deliver clips at the timeline's frame rate, converted once here, so the
    # editor never has to retime them: "sharp" (drop/repeat frames), "blend"
    # (mix neighbours), or "off" (keep the source rate; Resolve's retime applies).
    "conform": "sharp",
}

# Older versions wrote a re-encode setting that no longer exists. load()
# ignores any unknown key and save() writes only DEFAULTS, so a stale file
# heals itself.


def load() -> dict:
    """Read settings, falling back to defaults for anything missing or broken.

    A stored value is only accepted if it matches the type of its default, so a
    hand-edited or stale file can't put something unusable into the UI.
    """
    cfg = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for key, default in DEFAULTS.items():
                value = stored.get(key)
                if isinstance(default, bool):
                    if isinstance(value, bool):
                        cfg[key] = value
                elif isinstance(default, int):
                    # bool is a subclass of int, so exclude it explicitly.
                    if isinstance(value, int) and not isinstance(value, bool):
                        cfg[key] = value
                elif isinstance(default, str):
                    if isinstance(value, str) and value.strip():
                        cfg[key] = value
    except (OSError, ValueError):
        pass  # first run, or a corrupt file — defaults are fine

    length = cfg.get("default_length")
    if not isinstance(length, int) or not 1 <= length <= MAX_LENGTH:
        cfg["default_length"] = DEFAULTS["default_length"]
    if cfg.get("editor") not in EDITORS:
        cfg["editor"] = DEFAULTS["editor"]
    if cfg.get("retime") not in RETIMES:
        cfg["retime"] = DEFAULTS["retime"]
    if cfg.get("conform") not in CONFORMS:
        cfg["conform"] = DEFAULTS["conform"]

    # Upgrade anyone still pointing at the old %TEMP% location, which the OS is
    # entitled to delete. Existing clips are NOT moved: timelines reference them
    # by path, so relocating them would take that media offline.
    if os.path.normcase(os.path.normpath(cfg["download_dir"])) == \
            os.path.normcase(os.path.normpath(LEGACY_DOWNLOAD_DIR)):
        cfg["download_dir"] = DEFAULTS["download_dir"]
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
