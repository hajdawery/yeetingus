"""
platform_paths.py — every path that differs between Windows, macOS and Linux.

Split out because the same three questions were being answered independently in
config.py, deps.py and install.py, and they had already drifted: each grew its
own copy of "where does per-user application data live", which is exactly the
kind of duplication that makes a port miss a spot.

Deliberately imports nothing beyond the standard library and version.py, so the
installer can use it without dragging tkinter in behind it.

The four questions:
  app_data_dir()   where our settings and downloaded tools live
  videos_dir()     where the user keeps video, per platform convention
  resolve_paths()  Resolve's scripting API dir and its native library
  scripts_dirs()   Resolve's Scripts/Utility folders, most-preferred first
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from version import APP_NAME  # noqa: E402

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = not WINDOWS and not MACOS

# Suffix for executables. Empty everywhere but Windows, which lets callers build
# tool names without branching at every call site.
EXE_SUFFIX = ".exe" if WINDOWS else ""


def _home() -> str:
    return os.path.expanduser("~")


# --------------------------------------------------------------------------- #
# Application data
# --------------------------------------------------------------------------- #


def app_data_dir() -> str:
    """Per-user folder holding settings.json and the downloaded tool cache.

    Windows uses %LOCALAPPDATA% (not %APPDATA%: this is machine-local cache and
    tooling, which shouldn't follow a roaming profile around). macOS and Linux
    follow their own conventions rather than borrowing the Windows one.
    """
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or _home()
        return os.path.join(base, APP_NAME)
    if MACOS:
        return os.path.join(_home(), "Library", "Application Support", APP_NAME)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(_home(), ".local", "share")
    return os.path.join(base, APP_NAME)


def bin_dir() -> str:
    """Where downloaded tools land. Created on demand."""
    path = os.path.join(app_data_dir(), "bin")
    os.makedirs(path, exist_ok=True)
    return path


# --------------------------------------------------------------------------- #
# Videos folder
# --------------------------------------------------------------------------- #


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
    return os.path.join(_home(), "Videos")


def _xdg_videos_dir() -> str:
    """Linux: honour XDG_VIDEOS_DIR if the user has configured one."""
    conf = os.path.join(_home(), ".config", "user-dirs.dirs")
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
    return os.path.join(_home(), "Videos")


def videos_dir() -> str:
    """The platform's videos folder. macOS calls it Movies, not Videos.

    macOS has no relocatable-folder mechanism to consult — ~/Movies is fixed by
    convention — so unlike Windows there is nothing to look up.
    """
    if WINDOWS:
        return _windows_videos_dir()
    if MACOS:
        return os.path.join(_home(), "Movies")
    return _xdg_videos_dir()


# --------------------------------------------------------------------------- #
# DaVinci Resolve
# --------------------------------------------------------------------------- #

# Blackmagic's own README (Developer/Scripting/README.txt) documents one location
# per platform; the extra Windows entries cover installs on a non-default drive,
# and the macOS Studio entry covers the separately-named Studio bundle.
_RESOLVE_API_CANDIDATES = {
    "win32": [
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting",
    ],
    "darwin": [
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    ],
    "linux": [
        "/opt/resolve/Developer/Scripting",
        "/home/resolve/Developer/Scripting",
    ],
}

_RESOLVE_LIB_CANDIDATES = {
    "win32": [
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
        r"C:\Program Files (x86)\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\fusionscript.dll",
    ],
    "darwin": [
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/"
        "fusionscript.so",
        "/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app/Contents/"
        "Libraries/Fusion/fusionscript.so",
    ],
    "linux": [
        "/opt/resolve/libs/Fusion/fusionscript.so",
        "/home/resolve/libs/Fusion/fusionscript.so",
    ],
}

# Resolve's Scripts/Utility folders, per-user first: writing there needs no admin
# rights, and a per-user entry shadows a machine-wide one of the same name.
#
# Note the Windows per-user path has a "Support" component that the machine-wide
# one lacks, and macOS is the reverse of what you'd guess from Windows — the
# per-user path has no "Support". Both are as Blackmagic documents them.
_RESOLVE_SCRIPTS_CANDIDATES = {
    "win32": [
        (os.environ.get("APPDATA", ""), "Blackmagic Design", "DaVinci Resolve",
         "Support", "Fusion", "Scripts", "Utility"),
        (os.environ.get("PROGRAMDATA", ""), "Blackmagic Design", "DaVinci Resolve",
         "Fusion", "Scripts", "Utility"),
    ],
    "darwin": [
        (_home(), "Library", "Application Support", "Blackmagic Design",
         "DaVinci Resolve", "Fusion", "Scripts", "Utility"),
        ("/Library", "Application Support", "Blackmagic Design", "DaVinci Resolve",
         "Fusion", "Scripts", "Utility"),
    ],
    "linux": [
        (_home(), ".local", "share", "DaVinciResolve", "Fusion", "Scripts", "Utility"),
        ("/opt", "resolve", "Fusion", "Scripts", "Utility"),
    ],
}


def _key() -> str:
    if WINDOWS:
        return "win32"
    return "darwin" if MACOS else "linux"


def resolve_api_candidates() -> list[str]:
    """Scripting API directories to probe, most-preferred first."""
    return list(_RESOLVE_API_CANDIDATES[_key()])


def resolve_lib_candidates() -> list[str]:
    """fusionscript library paths to probe, most-preferred first."""
    return list(_RESOLVE_LIB_CANDIDATES[_key()])


def scripts_dirs() -> list[str]:
    """Resolve's Scripts/Utility folders, per-user first.

    Entries whose environment variable was empty are dropped rather than
    silently becoming a relative path — on Windows a missing %APPDATA% would
    otherwise produce a path rooted at the current directory.
    """
    out = []
    for parts in _RESOLVE_SCRIPTS_CANDIDATES[_key()]:
        if not parts[0]:
            continue
        out.append(os.path.join(*parts))
    return out


def scripts_dir() -> str:
    """The Scripts/Utility folder to install into.

    The first that already exists; failing that the per-user one, which the
    caller is expected to create. Resolve makes it on first run, so it is
    missing only when Resolve has never been opened.
    """
    candidates = scripts_dirs()
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]
