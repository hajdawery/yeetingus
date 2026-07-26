"""
naming.py — filesystem-safe names for downloaded clips.

Folder:  "<VIDEO ID> - <video title> - <channel name>"
File:    "<videoid>-clip-001.mp4"   (sequential, never overwrites)

Sanitising rule: keep letters, digits, combining marks and a small punctuation
whitelist; drop everything else. That preserves accented text (Zażółć, Kraków,
日本語) while removing emoji, symbols, control characters and every byte Windows
forbids in a path.
"""

from __future__ import annotations

import glob
import os
import re
import unicodedata

# Punctuation that is safe on Windows, macOS and Linux alike. Deliberately
# excludes < > : " / \ | ? * and the trailing-dot/space traps.
_ALLOWED_PUNCT = set(" -_.,()[]&'+#@!=~")

# Windows refuses these as file/folder names, with or without an extension.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_TITLE = 80
MAX_CHANNEL = 40
MAX_FOLDER = 130


_URL_ID = re.compile(
    r"(?:[?&]v=|/shorts/|youtu\.be/|/embed/|/live/|/v/)([A-Za-z0-9_-]{6,})"
)


def video_id_from_url(url: str) -> str:
    """Best-effort id straight from the URL, for when the metadata probe fails."""
    m = _URL_ID.search(url or "")
    return m.group(1) if m else ""


# YouTube's "start at" parameter, in all the shapes it appears in the wild:
#   ?t=169   &t=169s   &t=2m49s   &t=1h2m3s   ?start=169   #t=90
_T_PARAM = re.compile(r"[?&#](?:t|start|time_continue)=([0-9hms]+)", re.IGNORECASE)
_HMS = re.compile(r"(\d+)\s*([hms])", re.IGNORECASE)


def start_seconds_from_url(url: str) -> int | None:
    """Seconds from a share link's timestamp, or None if it has none."""
    m = _T_PARAM.search(url or "")
    if not m:
        return None
    raw = m.group(1).lower()
    if raw.isdigit():
        return int(raw)
    parts = _HMS.findall(raw)
    if not parts:
        return None
    scale = {"h": 3600, "m": 60, "s": 1}
    return sum(int(value) * scale[unit.lower()] for value, unit in parts)


def safe_component(text: str, max_len: int = 80) -> str:
    """Reduce arbitrary text to something every filesystem accepts."""
    if not text:
        return ""

    # NFKC folds compatibility forms (ﬁ -> fi, fullwidth -> ASCII) so the
    # whitelist below sees canonical characters.
    text = unicodedata.normalize("NFKC", text)

    kept = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N", "M"):        # letters, numbers, combining marks
            kept.append(ch)
        elif ch in _ALLOWED_PUNCT:
            kept.append(ch)
        else:
            # Emoji (So), control chars (Cc/Cf), surrogates (Cs), separators
            # other than plain space, and the illegal path bytes all land here.
            kept.append(" ")
    out = "".join(kept)

    out = re.sub(r"\s+", " ", out).strip()
    out = re.sub(r"[-_]{3,}", "--", out)          # collapse divider runs
    if len(out) > max_len:
        out = out[:max_len].rstrip()

    # Windows strips trailing dots/spaces silently, which breaks path matching.
    out = out.rstrip(" .")

    if out.upper() in _RESERVED or out.split(".")[0].upper() in _RESERVED:
        out = "_" + out
    return out


def folder_name(video_id: str, title: str = "", channel: str = "") -> str:
    """Build "<ID> - <title> - <channel>", omitting parts we don't know."""
    vid = safe_component(video_id, 40) or "unknown-id"
    parts = [vid]
    t = safe_component(title, MAX_TITLE)
    c = safe_component(channel, MAX_CHANNEL)
    if t:
        parts.append(t)
    if c:
        parts.append(c)

    name = " - ".join(parts)
    if len(name) > MAX_FOLDER:
        name = name[:MAX_FOLDER].rstrip(" -.")
    return name


def ensure_clip_folder(root: str, video_id: str, title: str = "",
                       channel: str = "") -> str:
    """Create (or reuse) the folder for this video and return its path."""
    path = os.path.join(root, folder_name(video_id, title, channel))
    os.makedirs(path, exist_ok=True)
    return path


def next_clip_stem(folder: str, video_id: str) -> str:
    """Return "<id>-clip-NNN" using the lowest free number in `folder`.

    Scans what is already on disk rather than keeping a counter, so it stays
    correct across restarts and if you delete clips by hand.
    """
    vid = safe_component(video_id, 40) or "unknown-id"
    prefix = f"{vid}-clip-"

    used: set[int] = set()
    pattern = re.compile(re.escape(prefix) + r"(\d+)", re.IGNORECASE)
    try:
        for entry in os.listdir(folder):
            m = pattern.match(entry)
            if m:
                used.add(int(m.group(1)))
    except OSError:
        pass

    n = 1
    while n in used:
        n += 1

    # Belt and braces: never hand back a stem that already has files on disk
    # (covers odd extensions and yt-dlp's intermediate .f137.mp4 parts).
    while glob.glob(os.path.join(glob.escape(folder), f"{prefix}{n:03d}*")):
        n += 1

    return f"{prefix}{n:03d}"
