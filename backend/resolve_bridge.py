"""
resolve_bridge.py — talk to DaVinci Resolve directly via its official external
Python scripting API.

This replaces the earlier Lua-HTTP-server approach: Resolve's bundled Lua has no
luasocket, so an in-Resolve HTTP server isn't possible without vendoring native
DLLs. The external Python API is officially supported and much simpler — the same
process that runs yt-dlp can drive Resolve.

IMPORTANT: fusionscript (`.dll` on Windows, `.so` on macOS and Linux) is a
CPython C extension. It must be loaded by an interpreter whose ABI it was built
against; anything newer segfaults on import rather than raising. See MIN_PY /
MAX_PY below for the verified range.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_paths as _pp  # noqa: E402

# Where Resolve puts its scripting API and native library, per platform. The
# lists cover non-default install locations too. RESOLVE_SCRIPT_API /
# RESOLVE_SCRIPT_LIB still win if set.
_API_CANDIDATES = _pp.resolve_api_candidates()
_LIB_CANDIDATES = _pp.resolve_lib_candidates()

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
# Verified against Resolve's June 2026 fusionscript:
#   Windows (fusionscript.dll):
#     3.11 -> imports OK      3.13 -> imports OK      3.14 -> SEGFAULT
#   macOS arm64 (fusionscript.so, Resolve 20.x):
#     3.13 -> imports OK
#
# The range is the same on both, which is expected: it's the CPython ABI that
# constrains it, not the OS. Raise MAX_PY by one minor version at a time, and
# only after confirming
#   python3.X -c "import DaVinciResolveScript"
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
        launcher = (f"py -{MAX_PY[0]}.{MAX_PY[1]}" if _pp.WINDOWS
                    else f"python{MAX_PY[0]}.{MAX_PY[1]}")
        raise ResolveError(
            f"Python {sys.version_info.major}.{sys.version_info.minor} can't load Resolve's "
            f"scripting library (it would crash). Run the app with Python "
            f"{version_range_text()} — e.g. `{launcher} yeet_app.py`."
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
    """'HH:MM:SS:FF' (or drop-frame 'HH:MM:SS;FF') -> frame index.

    Drop-frame timecode skips frame numbers 0-1 (0-3 at 59.94) at the start
    of every minute except each tenth; counting it as non-drop put playhead
    inserts 108 frames late per hour of timecode at 29.97."""
    drop = ";" in tc
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return None
    try:
        hh, mm, ss, ff = (int(p) for p in parts)
    except ValueError:
        return None
    nominal = int(round(fps))
    frames = (hh * 3600 + mm * 60 + ss) * nominal + ff
    if drop and nominal in (30, 60):
        dropped = nominal // 15                 # 2 at 29.97, 4 at 59.94
        minutes = hh * 60 + mm
        frames -= dropped * (minutes - minutes // 10)
    return frames


def _fps(value, default: float) -> float:
    """Resolve's frame-rate setting as a number; it can read "29.97 DF"."""
    try:
        return float(str(value).split()[0]) if value else default
    except (ValueError, IndexError):
        return default


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
    fps = _fps(tl.GetSetting("timelineFrameRate"), 24.0)
    # Resolve *plays* at the project's playback rate, which can lag behind
    # the timeline's (a 24 default under a 60 fps timeline shows every 2.5th
    # frame and reads as "choppy"). Reported so the app can say so.
    try:
        playback = float(tl.GetSetting("timelinePlaybackFrameRate")
                         or project.GetSetting("timelinePlaybackFrameRate") or 0)
    except (TypeError, ValueError):
        playback = 0.0
    tc = tl.GetCurrentTimecode()
    return {
        "project": project.GetName(),
        "timeline": tl.GetName(),
        "fps": fps,
        "playbackFps": playback or None,
        "currentTimecode": tc,
        "currentFrame": _timecode_to_frames(tc, fps),
        "startFrame": tl.GetStartFrame(),
    }


# Resolve's per-clip retime process, as TimelineItem.SetProperty("RetimeProcess")
# takes it. What a clip does on a timeline of another frame rate: "nearest"
# repeats/drops frames (60 on 24p judders — every clip frame lasts 2 or 3
# timeline frames), "blend" mixes neighbours (smooth, slightly soft), "optical"
# synthesises in-between frames (best, GPU-heavy). "project" leaves the
# project's default in charge. Measured against Resolve 21.
RETIME_PROCESSES = {"project": 0, "nearest": 1, "blend": 2, "optical": 3}


def import_and_insert(path: str, insert_at: str = "playhead",
                      track_index: int | None = None,
                      start_frame: int = 0, end_frame: int | None = None,
                      retime: str = "blend") -> dict:
    """Import `path` into the media pool and place it on the current timeline.

    insert_at: "playhead" -> at the current timecode
               "start"    -> at the timeline's first frame
               "end"      -> appended after the last clip

    start_frame / end_frame pick the part of the clip that goes on the
    timeline, in source frames (end exclusive, as Resolve counts it). Used for
    a remuxed section, which keeps the keyframe before the in point so that
    nothing has to be re-encoded; the extra frames stay available as a handle.

    retime (see RETIME_PROCESSES) is applied to the placed item when the
    clip's frame rate differs from the timeline's, so a 60 fps clip on a 24p
    timeline plays smoothly instead of juddering; the result reports whether
    it was.
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
    if start_frame:
        clip_info["startFrame"] = int(start_frame)
    if end_frame is not None:
        clip_info["endFrame"] = int(end_frame)
    if insert_at == "playhead":
        fps = _fps(tl.GetSetting("timelineFrameRate"), 24.0)
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

    out = {
        "clipName": item.GetName(),
        "insertedFrame": clip_info.get("recordFrame"),
        "retimed": None,
    }

    # Frame-rate mismatch: pick the retime process on the item Resolve just
    # made. AppendToTimeline returns the placed items on recent Resolve
    # versions; older ones return True, so fall back to finding it by clip.
    try:
        tl_fps = _fps(tl.GetSetting("timelineFrameRate"), 0.0)
        clip_fps = float(item.GetClipProperty("FPS") or 0)
        mode = RETIME_PROCESSES.get(retime)
        if mode and tl_fps and clip_fps and abs(tl_fps - clip_fps) > 0.01:
            placed = [x for x in (result if isinstance(result, list) else [])
                      if hasattr(x, "SetProperty")]
            if not placed:
                for track in range(1, tl.GetTrackCount("video") + 1):
                    for x in tl.GetItemListInTrack("video", track) or []:
                        mpi = x.GetMediaPoolItem()
                        if mpi and mpi.GetMediaId() == item.GetMediaId() and \
                                ("recordFrame" not in clip_info
                                 or x.GetStart() == clip_info["recordFrame"]):
                            placed.append(x)
                if "recordFrame" not in clip_info and placed:
                    # Appended: ours is the last one, not earlier copies.
                    placed = [max(placed, key=lambda x: x.GetStart())]
            for x in placed:
                if x.SetProperty("RetimeProcess", mode):
                    out["retimed"] = {"mode": retime, "clipFps": clip_fps, "timelineFps": tl_fps}
    except Exception:  # noqa: BLE001 — a missing retime is a note, not a failed insert
        pass

    return out
