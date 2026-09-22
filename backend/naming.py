"""
naming.py — filesystem-safe names for downloaded clips.

Folder:  "<VIDEO ID> - <video title> - <channel name>"
Clip:    "<videoid>-<ChannelName>-c001.mp4"  (numbered, never overwrites)
Full:    "<videoid>-<ChannelName>-full.mp4"  (fixed name, so it can be reused)

Sanitising rule: fold accented Latin text down to ASCII, then keep letters,
digits and a small punctuation whitelist and drop everything else. "Zażółć
gęślą jaźń" becomes "Zazolc gesla jazn"; emoji, symbols, control characters and
every byte Windows forbids in a path are removed.

Non-Latin scripts are left alone (日本語 stays 日本語) — there is no meaningful
ASCII to fold them to, and mangling them into nothing would leave a folder
called "unnamed".
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

# Latin letters that carry no combining mark to strip, so NFKD leaves them
# untouched and _fold_latin would otherwise keep them as-is. Polish ł is the one
# that matters here; the rest are the usual European suspects, included so the
# rule doesn't look arbitrary the next time a name comes through with a ø in it.
_TRANSLIT = {
    "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ð": "d", "Ð": "D",
    "ø": "o", "Ø": "O",
    "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "ß": "ss", "ẞ": "SS",
    "þ": "th", "Þ": "Th",
    "ı": "i", "İ": "I",
    "ŋ": "n", "Ŋ": "N",
}


def _fold_latin(text: str) -> str:
    """Reduce accented Latin characters to ASCII, leaving other scripts alone.

    Two mechanisms, because one isn't enough: NFKD splits é into "e" plus a
    combining accent that we then drop, but ł has no decomposition at all — it
    is a distinct letter, not l-with-a-mark — so it needs the explicit table
    above. Getting this wrong is how "Zażółć" becomes "Zazoc".

    A character whose folded form isn't pure ASCII is kept unchanged, which is
    what leaves CJK, Cyrillic and Greek readable instead of deleting them.
    """
    out = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
            continue
        if ch.isascii():
            out.append(ch)
            continue
        stripped = "".join(c for c in unicodedata.normalize("NFKD", ch)
                           if not unicodedata.combining(c))
        out.append(stripped if stripped and stripped.isascii() else ch)
    return "".join(out)

# Used when a title or channel consisted entirely of characters we strip — an
# all-emoji title, say. Distinct from "unknown", which means we never had the
# value in the first place (metadata probe failed) and simply omit the field.
FALLBACK_NAME = "unnamed"


def _or_fallback(original: str, cleaned: str) -> str:
    """`cleaned`, or FALLBACK_NAME when sanitising consumed real content."""
    if cleaned:
        return cleaned
    return FALLBACK_NAME if (original or "").strip() else ""


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
    # Then accented Latin down to plain ASCII: ż -> z, ł -> l, ó -> o.
    text = _fold_latin(text)

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


def compact_token(text: str, max_len: int = 32) -> str:
    """Squash text into a single separator-free token for use inside a filename.

    Keeps letters, digits and combining marks (so accented and CJK channel names
    survive) but drops spaces, punctuation and emoji entirely — "Rick Astley"
    becomes "RickAstley". Hyphens go too, since they're the field separator in
    the clip filename.
    """
    cleaned = safe_component(text, max_len * 3)
    token = "".join(
        ch for ch in cleaned if unicodedata.category(ch)[0] in ("L", "N", "M"))
    return _or_fallback(text, token[:max_len])


# yt-dlp extractors whose "title" is the post's text rather than a title.
_POST_EXTRACTORS = ("twitter", "x", "bluesky", "bsky", "mastodon", "threads",
                    "facebook", "instagram", "reddit", "tiktok", "vk")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def title_is_post_text(extractor: str, title: str = "", description: str = "",
                       channel: str = "") -> bool:
    """True when yt-dlp's title is really the post body, so it shouldn't go
    into a folder name. Known post sites are listed; any other site counts
    when the title is just the description (or its start), or is the poster's
    name followed by the description — the shapes yt-dlp falls back to for
    videos that have no title of their own."""
    key = (extractor or "").lower().split(":")[0]
    if any(key == e or (len(e) > 2 and key.startswith(e)) for e in _POST_EXTRACTORS):
        return True
    t, d, c = _norm(title), _norm(description), _norm(channel)
    if not t or not d:
        return False
    # "<channel> - <text>": strip the channel only as a whole word.
    if c and t.startswith(c) and (len(t) == len(c) or t[len(c)] in " -:|–—"):
        t = t[len(c):].lstrip(" -:|–—").strip()
        if not t:
            return False
    t = t.rstrip(".…")
    return len(t) >= 12 and (d.startswith(t) or (len(d) >= 12 and t.startswith(d)))


def folder_name(video_id: str, title: str = "", channel: str = "") -> str:
    """Build "<ID> - <title> - <channel>", omitting parts we don't know."""
    vid = safe_component(video_id, 40) or "unknown-id"
    parts = [vid]
    t = _or_fallback(title, safe_component(title, MAX_TITLE))
    c = _or_fallback(channel, safe_component(channel, MAX_CHANNEL))
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


def clip_prefix(video_id: str, channel: str = "") -> str:
    """Filename prefix: "<id>-<ChannelName>-c" (channel omitted if unknown)."""
    vid = safe_component(video_id, 40) or "unknown-id"
    chan = compact_token(channel)
    return f"{vid}-{chan}-c" if chan else f"{vid}-c"


def full_stem(video_id: str, channel: str = "") -> str:
    """Filename stem for a whole-video download: "<id>-<ChannelName>-full".

    Unnumbered on purpose — there is only ever one "entire video" per id, so a
    fixed name lets a repeat request find and reuse it instead of downloading
    the same thing again.
    """
    vid = safe_component(video_id, 40) or "unknown-id"
    chan = compact_token(channel)
    return f"{vid}-{chan}-full" if chan else f"{vid}-full"


def next_clip_stem(folder: str, video_id: str, channel: str = "") -> str:
    """Return "<id>-<ChannelName>-cNNN" using the lowest free number in `folder`.

    Scans what is already on disk rather than keeping a counter, so it stays
    correct across restarts and if you delete clips by hand.
    """
    prefix = clip_prefix(video_id, channel)

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
