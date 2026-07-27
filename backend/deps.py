"""
deps.py — locate (and on first run, fetch) the external binaries YEETingus needs.

Lookup order for each tool:
  1. env override            (YEET_YTDLP / YEET_FFMPEG)
  2. bundled next to the exe (vendor/ inside the PyInstaller bundle)
  3. the app's own bin dir   (%LOCALAPPDATA%\\YEETingus\\bin) — first-run downloads land here
  4. whatever is on PATH
  5. (yt-dlp only) the pip-installed module, via `python -m yt_dlp`

Anything still missing after that is downloaded from the official GitHub release
of the respective project. Downloads are cached in (3), so this happens once.
"""

from __future__ import annotations

import os
import shutil
import sys
import urllib.request
import zipfile
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from version import APP_NAME  # noqa: E402

# Official release artifacts.
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
# yt-dlp's own ffmpeg builds — the ones it's tested against.
FFMPEG_URL = (
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

ProgressCB = Callable[[str], None]


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def bin_dir() -> str:
    d = os.path.join(app_dir(), "bin")
    os.makedirs(d, exist_ok=True)
    return d


def _bundled_dir() -> str | None:
    """vendor/ inside a PyInstaller bundle, or the repo's vendor/ during dev."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "vendor")
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(os.path.dirname(here), "vendor")
    return cand if os.path.isdir(cand) else None


def _look_for(exe: str) -> str | None:
    bundled = _bundled_dir()
    if bundled:
        p = os.path.join(bundled, exe)
        if os.path.isfile(p):
            return p
    p = os.path.join(bin_dir(), exe)
    if os.path.isfile(p):
        return p
    found = shutil.which(exe)
    return found


# --------------------------------------------------------------------------- #
# Download helper
# --------------------------------------------------------------------------- #


def _download(url: str, dest: str, log: ProgressCB) -> None:
    log(f"Downloading {os.path.basename(dest)} …")
    log(f"  from {url}")
    tmp = dest + ".part"
    last_pct = -10

    req = urllib.request.Request(url, headers={"User-Agent": "YEETingus/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if pct - last_pct >= 10:
                    last_pct = pct
                    log(f"  {pct}%  ({done // 1048576} / {total // 1048576} MB)")
            elif done % (8 * 1048576) < 262144:
                log(f"  {done // 1048576} MB…")

    os.replace(tmp, dest)
    log(f"  saved to {dest}")


# --------------------------------------------------------------------------- #
# yt-dlp
# --------------------------------------------------------------------------- #


def find_ytdlp() -> list[str] | None:
    override = os.environ.get("YEET_YTDLP")
    if override and os.path.isfile(override):
        return [override]

    exe = _look_for("yt-dlp.exe") or _look_for("yt-dlp")
    if exe:
        return [exe]

    # pip-installed module (dev convenience only; not available when frozen)
    if not getattr(sys, "frozen", False):
        try:
            import importlib.util

            if importlib.util.find_spec("yt_dlp") is not None:
                return [sys.executable, "-m", "yt_dlp"]
        except Exception:  # noqa: BLE001
            pass
    return None


def ensure_ytdlp(log: ProgressCB) -> list[str]:
    cmd = find_ytdlp()
    if cmd:
        return cmd
    dest = os.path.join(bin_dir(), "yt-dlp.exe")
    _download(YTDLP_URL, dest, log)
    return [dest]


# --------------------------------------------------------------------------- #
# ffmpeg
# --------------------------------------------------------------------------- #


def find_ffmpeg() -> str | None:
    override = os.environ.get("YEET_FFMPEG")
    if override and os.path.isfile(override):
        return override
    return _look_for("ffmpeg.exe") or _look_for("ffmpeg")


def find_ffprobe() -> str | None:
    """ffprobe ships beside ffmpeg in every build we use, so fall back to that."""
    override = os.environ.get("YEET_FFPROBE")
    if override and os.path.isfile(override):
        return override
    found = _look_for("ffprobe.exe") or _look_for("ffprobe")
    if found:
        return found
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        candidate = os.path.join(os.path.dirname(ffmpeg), exe)
        if os.path.isfile(candidate):
            return candidate
    return None


def ensure_ffmpeg(log: ProgressCB) -> str:
    found = find_ffmpeg()
    if found:
        return found

    zip_path = os.path.join(bin_dir(), "_ffmpeg.zip")
    _download(FFMPEG_URL, zip_path, log)

    log("  extracting ffmpeg…")
    wanted = ("ffmpeg.exe", "ffprobe.exe")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            name = os.path.basename(member)
            if name in wanted:
                with zf.open(member) as src, open(os.path.join(bin_dir(), name), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                log(f"  extracted {name}")
    try:
        os.remove(zip_path)
    except OSError:
        pass

    found = find_ffmpeg()
    if not found:
        raise RuntimeError("ffmpeg archive downloaded but ffmpeg.exe wasn't found inside it.")
    return found


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def ensure_all(log: ProgressCB) -> tuple[list[str], str]:
    """Return (ytdlp_cmd, ffmpeg_path), downloading whatever is missing.

    Raises on failure — the caller shows the message in the UI log.
    """
    ytdlp = ensure_ytdlp(log)
    ffmpeg = ensure_ffmpeg(log)
    return ytdlp, ffmpeg
