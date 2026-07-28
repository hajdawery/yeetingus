"""
resolve_bridge.py — talk to DaVinci Resolve directly via its official external
Python scripting API.

This replaces the earlier Lua-HTTP-server approach: Resolve's bundled Lua has no
luasocket, so an in-Resolve HTTP server isn't possible without vendoring native
DLLs. The external Python API is officially supported and much simpler — the same
process that runs yt-dlp can drive Resolve.

IMPORTANT: `fusionscript.dll` is a CPython C extension. It must be loaded by an
interpreter whose ABI it was built against; anything newer segfaults on import
rather than raising. See MIN_PY / MAX_PY below for the verified range.
"""

from __future__ import annotations

import os
import sys

# Standard Windows locations, plus the places Resolve ends up when installed to a
# non-default drive. RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB still win if set.
_API_CANDIDATES = [
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting",
]
_LIB_CANDIDATES = [
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    r"C:\Program Files (x86)\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\fusionscript.dll",
]

DEFAULT_API = _API_CANDIDATES[0]
DEFAULT_LIB = _LIB_CANDIDATES[0]


def _first_existing(paths: list[str], want_dir: bool = False) -> str | None:
    for path in paths:
        if (os.path.isdir(path) if want_dir else os.path.isfile(path)):
            return path
    return None


class ResolveError(RuntimeError):
    """Raised for any Resolve-side problem, with a message fit for the UI log."""


def _ensure_env() -> None:
    """Point the Resolve scripting module at a real install.

    Explicit env vars win; otherwise probe the known locations so a non-default
    install directory doesn't need manual configuration.
    """
    api = (os.environ.get("RESOLVE_SCRIPT_API")
           or _first_existing(_API_CANDIDATES, want_dir=True) or DEFAULT_API)
    lib = (os.environ.get("RESOLVE_SCRIPT_LIB")
           or _first_existing(_LIB_CANDIDATES) or DEFAULT_LIB)
    os.environ["RESOLVE_SCRIPT_API"] = api
    os.environ["RESOLVE_SCRIPT_LIB"] = lib
    modules = os.path.join(api, "Modules")
    if modules not in sys.path:
        sys.path.append(modules)


def describe_env() -> dict:
    """Where we're looking for Resolve — surfaced in Settings for diagnostics."""
    _ensure_env()
    api = os.environ.get("RESOLVE_SCRIPT_API", "")
    lib = os.environ.get("RESOLVE_SCRIPT_LIB", "")
    return {
        "api": api,
        "lib": lib,
        "api_exists": os.path.isdir(api),
        "lib_exists": os.path.isfile(lib),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": python_is_supported(),
    }


# The interpreter range Resolve's fusionscript extension can be loaded into.
# It's a version-specific C extension (no Py_LIMITED_API), so it must match the
# running interpreter's ABI. Blackmagic's README optimistically claims "3.6+",
# but the real ceiling lags new Python releases until they rebuild it.
#
# Verified on this machine against Resolve's June 2026 fusionscript.dll:
#   3.11 -> imports OK        3.13 -> imports OK        3.14 -> SEGFAULT
#
# Raise MAX_PY by one minor version at a time, and only after confirming
#   py -3.X -c "import DaVinciResolveScript"
# exits 0 rather than crashing. This constant is the single source of truth --
# build.py reads it too.
MIN_PY = (3, 6)
MAX_PY = (3, 13)


def version_range_text() -> str:
    """The supported interpreter range, for error messages."""
    return f"{MIN_PY[0]}.{MIN_PY[1]}-{MAX_PY[0]}.{MAX_PY[1]}"


def python_is_supported() -> bool:
    """fusionscript.dll segfaults rather than raising on an ABI mismatch, so we
    gate on version before attempting the import."""
    return MIN_PY <= sys.version_info[:2] <= MAX_PY


def connect():
    """Return a live Resolve app handle, or raise ResolveError."""
    if not python_is_supported():
        raise ResolveError(
            f"Python {sys.version_info.major}.{sys.version_info.minor} can't load Resolve's "
            f"scripting library (it would crash). Run the app with Python "
            f"{version_range_text()} — e.g. `py -{MAX_PY[0]}.{MAX_PY[1]} yeet_app.py`."
        )
    _ensure_env()
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as e:
        raise ResolveError(
            "Couldn't import DaVinciResolveScript. Looked in "
            f"{os.environ.get('RESOLVE_SCRIPT_API')}. If Resolve is installed "
            "somewhere unusual, set RESOLVE_SCRIPT_API and RESOLVE_SCRIPT_LIB. "
            f"({e})"
        ) from e

    app = dvr.scriptapp("Resolve")
    if not app:
        raise ResolveError(
            "Resolve isn't responding. Make sure DaVinci Resolve is running, and that "
            "Preferences -> System -> General -> 'External scripting using' is set to Local."
        )
    return app


def _timecode_to_frames(tc: str, fps: float) -> int | None:
    """'HH:MM:SS:FF' -> frame index. Non-drop-frame math (fine for 24/25/30;
    29.97/59.94 drop-frame may be off by a frame or two)."""
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return None
    try:
        hh, mm, ss, ff = (int(p) for p in parts)
    except ValueError:
        return None
    rounded = int(round(fps))
    return (hh * 3600 + mm * 60 + ss) * rounded + ff


def get_timeline_info() -> dict:
    """Project name, timeline name, fps and playhead position.

    Raises ResolveError with a message fit for the UI when Resolve is not
    running, or has no project or timeline open."""
    app = connect()
    project = app.GetProjectManager().GetCurrentProject()
    if not project:
        raise ResolveError("No project is open in Resolve.")
    tl = project.GetCurrentTimeline()
    if not tl:
        raise ResolveError("No timeline is open. Create or open one first.")
    fps = float(tl.GetSetting("timelineFrameRate") or 24)
    tc = tl.GetCurrentTimecode()
    return {
        "project": project.GetName(),
        "timeline": tl.GetName(),
        "fps": fps,
        "currentTimecode": tc,
        "currentFrame": _timecode_to_frames(tc, fps),
        "startFrame": tl.GetStartFrame(),
    }


def import_and_insert(path: str, insert_at: str = "playhead",
                      track_index: int | None = None) -> dict:
    """Import `path` into the media pool and place it on the current timeline.

    insert_at: "playhead" -> at the current timecode
               "start"    -> at the timeline's first frame
               "end"      -> appended after the last clip
    """
    if not os.path.isfile(path):
        raise ResolveError(f"File not found: {path}")

    app = connect()
    project = app.GetProjectManager().GetCurrentProject()
    if not project:
        raise ResolveError("No project is open in Resolve.")
    tl = project.GetCurrentTimeline()
    if not tl:
        raise ResolveError("No timeline is open. Create or open one first.")

    pool = project.GetMediaPool()
    storage = app.GetMediaStorage()

    items = storage.AddItemListToMediaPool([os.path.abspath(path)])
    if not items:
        raise ResolveError(f"Resolve refused to import: {path}")
    item = items[0]

    clip_info: dict = {"mediaPoolItem": item}
    if insert_at == "playhead":
        fps = float(tl.GetSetting("timelineFrameRate") or 24)
        frame = _timecode_to_frames(tl.GetCurrentTimecode(), fps)
        if frame is not None:
            clip_info["recordFrame"] = frame
    elif insert_at == "start":
        clip_info["recordFrame"] = tl.GetStartFrame()
    # "end" -> omit recordFrame so Resolve appends.

    if track_index is not None:
        clip_info["trackIndex"] = track_index

    result = pool.AppendToTimeline([clip_info])
    if not result:
        raise ResolveError(
            "Imported to the media pool, but placing it on the timeline failed. "
            "The target spot may already be occupied — try moving the playhead, "
            "or add an empty video track."
        )

    return {
        "clipName": item.GetName(),
        "insertedFrame": clip_info.get("recordFrame"),
    }
