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


def _windows_videos_dir() -> str:
    """The real Videos folder, which users often relocate to another drive."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            path, _ = winreg.QueryValueEx(handle, "My Video")
        if path and os.path.isdir(path):
            return path
    except Exception:  # noqa: BLE001 — registry missing/renamed; fall through
        pass
    return os.path.join(os.path.expanduser("~"), "Videos")


def _xdg_videos_dir() -> str:
    """Linux: honour XDG_VIDEOS_DIR if the user has configured one."""
    conf = os.path.join(os.path.expanduser("~"), ".config", "user-dirs.dirs")
    try:
        with open(conf, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("XDG_VIDEOS_DIR"):
                    raw = line.split("=", 1)[1].strip().strip('"')
                    path = os.path.expandvars(raw.replace("$HOME", "~"))
                    path = os.path.expanduser(path)
                    if os.path.isdir(path):
                        return path
    except OSError:
        pass
    return os.path.join(os.path.expanduser("~"), "Videos")


def videos_dir() -> str:
    """The platform's videos folder. macOS calls it Movies, not Videos."""
    if sys.platform == "win32":
        return _windows_videos_dir()
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Movies")
    return _xdg_videos_dir()


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

DEFAULTS: dict = {
    "download_dir": default_download_dir(),
    # End point applied at launch, measured from the in point.
    "default_length": 30,
}


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
