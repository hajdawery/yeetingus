"""
engine.py — everything YEETingus does, with no window attached.

The pipeline (look the video up, download the section, run the preparation
pass from media.py, paste it into Resolve), the tools it needs (yt-dlp, ffmpeg,
Deno) and the user's settings all live in one Engine object. The Tk app drives
it in-process; service.py drives it over localhost HTTP for the other front
ends. Neither knows anything the other doesn't.

Talking back is by events only. Every event is a dict with a "kind", a
monotonically increasing "seq" and a timestamp "t", and is handed to each
subscribed listener, on whatever thread produced it — listeners
marshal to their own UI thread. The kinds:

    log        text, tag        a log line (tag: None | "highlight" | ...)
    progress   fraction, step   either may be None (= unchanged)
    resolve    text, level      editor connection pill; level "ok" | "error"
               (named for the first editor; it reports whichever is chosen)
    busy       busy             a job is running / finished
    tools      <tools_info()>   yt-dlp / ffmpeg / video / JS lines changed
    tool_busy  tool, busy       a Settings action (update/install) in flight
    reveal_log                  something went wrong; show the log
    clips                       the clip library changed; re-list it
    resolve_menu <info> + last_install   the Resolve Scripts-menu entry changed
    settings   <state()["settings"]> + editor   a setting changed

Blocking methods (boot, run_job, update_ytdlp, install_*) are meant to run on
a worker thread; the start_* wrappers do that. Only one job runs at a time.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from fractions import Fraction
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config                    # noqa: E402
import deps                      # noqa: E402
import media                     # noqa: E402
import naming                    # noqa: E402
import premiere_bridge           # noqa: E402
import resolve_bridge            # noqa: E402
import resolve_menu              # noqa: E402
from version import APP_NAME, __version__  # noqa: E402

# Progress is split into bands so the bar moves through the whole job, not just
# the download: info lookup, download, the preparation pass (the conversion in
# media.py), then the Resolve insert.
P_INFO, P_DOWNLOAD, P_PREPARE, P_INSERT = 0.06, 0.70, 0.94, 0.97

_PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

# ffmpeg -progress output, for the preparation pass: "out_time_us=12345678".
_FFMPEG_TIME_RE = re.compile(r"^out_time_us=(\d+)", re.MULTILINE)


def spawn_kwargs() -> dict:
    """subprocess keyword arguments for launching an external tool.

    Three platform concerns, all invisible when they work:

    * No console window on Windows. CREATE_NO_WINDOW doesn't exist on POSIX, and
      passing 0 there is accepted and ignored.
    * UTF-8 output. yt-dlp and ffmpeg write UTF-8 whatever the console codepage
      is, but `text=True` alone decodes using the locale — cp1252 on a Western
      Windows install — which turned a Polish title into
      "WiedÅºmin 3 ... PieÅ›ni przeszÅ‚oÅ›ci" in the log. Only the echoed output
      was affected, never the files: yt-dlp escapes non-ASCII in the JSON the
      metadata probe reads, so folder names were always correct. errors=replace
      because a mangled character must never take down a download.
    * A killable process group. yt-dlp spawns ffmpeg as a child, so STOP has to
      take out the whole tree — killing the parent alone leaves ffmpeg running
      and still writing to the output file. Windows does this at kill time with
      `taskkill /T`, which walks the tree itself. POSIX has no equivalent, so the
      group must be established when the process starts: start_new_session puts
      the child in a fresh process group whose id equals its pid, which
      os.killpg can then signal as a unit. Set it here or STOP cannot work.
    """
    kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    "encoding": "utf-8", "errors": "replace"}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    return kwargs


# yt-dlp's post-download stages (merging the video and audio streams), which
# deserve their own label rather than sitting at "Downloading... 100%".
_POST_MARKERS = ("[merger]", "[videoconvertor]", "[videoremuxer]", "[fixup",
                 "[extractaudio]", "[postprocess", "[splitchapters]")

QUALITY_OPTIONS = {
    "Best available": None,
    "2160p (4K)": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}

INSERT_MODES = ("playhead", "start")

# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

_TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?\s*$|^\s*(\d+(?:\.\d+)?)\s*$")


def normalize_timestamp(text: str) -> str | None:
    """Accept 'SS', 'SS.ms', 'MM:SS' or 'HH:MM:SS(.ms)'; return a form yt-dlp's
    --download-sections understands. None if unparseable."""
    m = _TS_RE.match(text)
    if not m:
        return None
    if m.group(5) is not None:
        total = float(m.group(5))
        h, rem = divmod(total, 3600)
        mnt, sec = divmod(rem, 60)
        return f"{int(h):02d}:{int(mnt):02d}:{sec:06.3f}".rstrip("0").rstrip(".")
    h = int(m.group(1) or 0)
    mnt, sec, frac = int(m.group(2)), int(m.group(3)), m.group(4)
    base = f"{h:02d}:{mnt:02d}:{sec:02d}"
    return f"{base}.{frac}" if frac else base


def to_seconds(ts_norm: str) -> float:
    parts = [float(p) for p in ts_norm.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def seconds_to_timestamp(total: float) -> str:
    """Seconds -> 'MM:SS', or 'HH:MM:SS' once it passes an hour."""
    total = int(total)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _video_heights(data: dict) -> list[int]:
    """Distinct video resolutions a video offers, tallest first.

    Skips audio-only entries (vcodec "none") and formats with no height, e.g.
    storyboards.
    """
    heights = {
        f.get("height")
        for f in (data.get("formats") or [])
        if f.get("height") and f.get("vcodec") not in (None, "none")
    }
    return sorted((h for h in heights if isinstance(h, int)), reverse=True)


# Resolution first, then AV1 as the tiebreaker. Every download is converted
# anyway (media.py explains why), so the codec only affects the download: AV1
# is YouTube's smallest stream at any resolution, and both AV1 and VP9 decode
# in hardware on the way in. Resolution is never capped.
#
# acodec:aac is not optional. Older Resolve builds import Opus silently, and
# without naming an audio codec yt-dlp picks Opus by preference even when
# YouTube also offers AAC, which it almost always does. When Opus does arrive
# it is converted to AAC (media.COPYABLE_AUDIO).
FORMAT_SORT = "res,vcodec:av01,acodec:aac"

# yt-dlp's intermediate per-stream files, e.g. "<stem>.f313.webm" (video only) and
# "<stem>.f140.m4a" (audio only), which it merges and then deletes. An interrupted
# download leaves them behind, and handing one to Resolve gives MEDIA OFFLINE.
_FRAGMENT_RE = re.compile(r"\.f\d+\.", re.IGNORECASE)

# What yt-dlp writes, before the preparation pass turns it into "<stem>.mp4".
# Deleted once that succeeds; never handed to Resolve.
SOURCE_TAG = ".src"

# Containers a finished download can legitimately arrive in.
MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v")

# Copies made from a finished clip for the other editor: "<stem>.hevc.mp4",
# "<stem>.av1.mp4".
_SIBLING_RE = re.compile(r"\.(?:hevc|av1)\.mp4$", re.IGNORECASE)


_EMPTY_META = {"id": "", "title": "", "channel": "", "heights": [],
               "duration": None, "thumbnail": None, "age_restricted": False}

# yt-dlp's wording for a video that needs a signed-in session:
# "Sign in to confirm your age. Use --cookies-from-browser or --cookies ...".
# Matched loosely, since the sentence has changed before.
_AGE_GATE_RE = re.compile(r"(confirm your age|age[- ]restricted|sign in to confirm)",
                          re.IGNORECASE)


def _looks_age_gated(line: str) -> bool:
    return bool(_AGE_GATE_RE.search(line or ""))


def format_selector(max_height: int | None) -> str:
    """yt-dlp -f expression. Codec preference is handled by FORMAT_SORT."""
    if max_height is None:
        return "bv*+ba/b"
    h = max_height
    return f"bv*[height<={h}]+ba/b[height<={h}]/b"


def quality_label(max_height: int | None) -> str:
    return next((k for k, v in QUALITY_OPTIONS.items() if v == max_height),
                f"{max_height}p")


def validate_range(in_text: str, out_text: str) -> tuple[str | None, str | None]:
    """The section a form asks for, as normalised timestamps.

    Both None means "whole video", which is what both points sitting at zero
    means. Raises ValueError with a message written for the log.
    """
    start = normalize_timestamp(in_text)
    end = normalize_timestamp(out_text)
    if start is None or end is None:
        raise ValueError("in/end point must be SS, MM:SS or HH:MM:SS.")
    if to_seconds(start) == 0 and to_seconds(end) == 0:
        return None, None
    if to_seconds(end) <= to_seconds(start):
        raise ValueError("end point must be after in point "
                         "(or set both to 00:00 for the whole video).")
    return start, end


Listener = Callable[[dict], None]


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class Engine:
    # Log lines kept for a front end that attaches after the fact.
    HISTORY = 500

    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._listeners_lock = threading.Lock()
        self.history: deque[dict] = deque(maxlen=self.HISTORY)
        # Every event gets the next number, so a client that drops its stream
        # can ask for everything after the last one it saw.
        self._seq = 0

        self.busy = False
        self._busy_lock = threading.Lock()
        self.ytdlp_cmd: list[str] | None = None
        self.ffmpeg_path: str | None = None
        self.ytdlp_version: str | None = None
        # JavaScript runtime for yt-dlp's YouTube challenge solver, and the
        # yt-dlp arguments that point at it. Empty when the runtime is missing
        # or this yt-dlp predates the flags — downloads still go ahead, they
        # just lose the formats that are behind a challenge.
        self.deno_path: str | None = None
        self.deno_version: str | None = None
        self.js_args: list[str] = []
        self._js_note: str | None = None     # shown instead of a path when unusable
        # Cancellation: the event is checked between phases and inside the
        # download loop; active_proc lets us kill yt-dlp (and its ffmpeg child)
        # mid-flight rather than waiting for it to finish.
        self.cancel_event = threading.Event()
        self.active_proc: subprocess.Popen | None = None
        self.settings = config.load()
        self.download_dir = self.settings["download_dir"]
        self.default_length = self.settings["default_length"]
        self.editor = self.settings["editor"]
        self.retime = self.settings["retime"]
        self.conform = self.settings["conform"]
        # The timeline's frame rate, read when a job starts (None = unknown).
        self._timeline_fps: Fraction | None = None
        # The Premiere panel's side of the conversation (see premiere_bridge).
        # It reports connect/disconnect so the pill can follow without polling.
        self.premiere = premiere_bridge.PremiereBridge()
        self.premiere.on_change = self._premiere_changed
        # What Adobe's installer lists for our panel (None = not installed,
        # "?" = not asked yet); asked in the background, never on a request.
        self._panel_installed: str | None = "?"
        self._last_install: str | None = None
        # The desktop app's executable, when a shell told us (service --app-exe).
        self.app_exe: str | None = None
        self._last_menu_install: str | None = None
        # Hardware AV1 support, probed once ffmpeg is known (see boot).
        self.caps: media.Capabilities | None = None
        self.booted = False
        # The last thing said about Resolve, for a front end attaching late.
        self.resolve_state = {"text": "checking…", "level": "error"}
        self.last_progress = {"fraction": 0.0, "step": ""}

    # ---- events ----------------------------------------------------------- #

    def subscribe(self, fn: Listener) -> None:
        with self._listeners_lock:
            self._listeners.append(fn)

    def unsubscribe(self, fn: Listener) -> None:
        with self._listeners_lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def emit(self, kind: str, **data) -> None:
        with self._listeners_lock:
            self._seq += 1
            seq = self._seq
        event = {"kind": kind, "seq": seq, "t": time.time(), **data}
        if kind == "log":
            self.history.append(event)
        elif kind == "resolve":
            self.resolve_state = {"text": data["text"], "level": data["level"]}
        elif kind == "progress":
            if data.get("fraction") is not None:
                self.last_progress["fraction"] = data["fraction"]
            if data.get("step") is not None:
                self.last_progress["step"] = data["step"]
        with self._listeners_lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception:  # noqa: BLE001 — one broken listener mustn't stop the rest
                pass

    def log(self, msg: str, tag: str | None = None) -> None:
        """`tag` forces a log style; without it the style is guessed from the text."""
        self.emit("log", text=f"[{datetime.now():%H:%M:%S}] {msg}", tag=tag)

    def _progress(self, fraction: float | None = None, step: str | None = None) -> None:
        self.emit("progress", fraction=fraction, step=step)

    def reveal_log(self) -> None:
        """Ask the front end to bring the log into view (something went wrong)."""
        self.emit("reveal_log")

    def _set_status(self, text: str, level: str) -> None:
        self.emit("resolve", text=text, level=level)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.emit("busy", busy=busy)

    def _tool_busy(self, tool: str, busy: bool) -> None:
        self.emit("tool_busy", tool=tool, busy=busy)

    def _tools_changed(self) -> None:
        self.emit("tools", **self.tools_info())

    # ---- state for a front end ------------------------------------------- #

    def ytdlp_info_text(self) -> str:
        where = " ".join(self.ytdlp_cmd) if self.ytdlp_cmd else "not found"
        return f"{self.ytdlp_version or '?'}  —  {where}"

    def js_info_text(self) -> str:
        """Reads the cached version rather than probing, so a UI can build its
        Settings window without spawning deno."""
        if self._js_note:
            return self._js_note
        if not self.deno_path:
            return "not found"
        return f"deno {self.deno_version or '?'}  —  {self.deno_path}"

    def tools_info(self) -> dict:
        return {
            "ytdlp": self.ytdlp_info_text(),
            "ytdlp_cmd": list(self.ytdlp_cmd or []),
            "ytdlp_version": self.ytdlp_version,
            "ffmpeg": self.ffmpeg_path or "not found",
            "ffmpeg_path": self.ffmpeg_path,
            "video": self.caps.describe() if self.caps else "not checked",
            "js": self.js_info_text(),
            "deno_path": self.deno_path,
            "ffmpeg_manual": bool(deps.MACOS_FFMPEG_MANUAL),
            "ready": bool(self.ytdlp_cmd and self.ffmpeg_path),
        }

    def state(self) -> dict:
        """Everything a front end needs to draw itself from scratch."""
        return {
            "app": APP_NAME,
            "version": __version__,
            "booted": self.booted,
            "busy": self.busy,
            "editor": self.editor,
            "editors": list(config.EDITORS),
            "resolve": dict(self.resolve_state),
            "resolve_menu": {**self.resolve_menu_info(), "last_install": self._last_menu_install},
            "premiere": self.premiere_info(),
            "progress": dict(self.last_progress),
            "tools": self.tools_info(),
            "settings": {
                "download_dir": self.download_dir,
                "default_length": self.default_length,
                "editor": self.editor,
                "onboarded": bool(self.settings.get("onboarded")),
                "retime": self.retime,
                "conform": self.conform,
            },
            "retimes": list(config.RETIMES),
            "quality_options": list(QUALITY_OPTIONS),
            "insert_modes": list(INSERT_MODES),
        }

    # ---- settings --------------------------------------------------------- #

    def update_settings(self, download_dir: str | None = None,
                        default_length: int | None = None,
                        editor: str | None = None,
                        onboarded: bool | None = None,
                        retime: str | None = None,
                        conform: str | bool | None = None) -> str | None:
        """Apply and persist what changed. Returns the path written, or None if
        nothing changed. Raises ValueError for an unusable value."""
        changed = False
        if download_dir is not None:
            new_dir = download_dir.strip()
            if not new_dir:
                raise ValueError("clips folder can't be empty")
            if new_dir != self.download_dir:
                self.settings["download_dir"] = new_dir
                self.download_dir = new_dir
                changed = True
        if default_length is not None:
            if not isinstance(default_length, int) or \
                    not 1 <= default_length <= config.MAX_LENGTH:
                raise ValueError("default length must be a whole number of seconds")
            if default_length != self.default_length:
                self.settings["default_length"] = default_length
                self.default_length = default_length
                changed = True
        if editor is not None:
            if editor not in config.EDITORS:
                raise ValueError(f"unknown editor '{editor}'")
            if editor != self.editor:
                self.settings["editor"] = editor
                self.editor = editor
                changed = True
                self.log("Clips go to " + ("Premiere Pro." if editor == "premiere"
                                           else "DaVinci Resolve."))
                self.refresh_connection()
        if retime is not None:
            if retime not in config.RETIMES:
                raise ValueError(f"unknown retime process '{retime}'")
            if retime != self.retime:
                self.settings["retime"] = retime
                self.retime = retime
                changed = True
        if conform is not None:
            if conform is True:
                conform = "sharp"
            if conform is False:
                conform = "off"
            if conform not in config.CONFORMS:
                raise ValueError(f"unknown conform mode '{conform}'")
            if conform != self.conform:
                self.settings["conform"] = conform
                self.conform = conform
                changed = True
        if onboarded is not None and bool(onboarded) != self.settings.get("onboarded"):
            self.settings["onboarded"] = bool(onboarded)
            changed = True
        if not changed:
            return None
        path = config.save(self.settings)
        self.log(f"Settings saved → {path}")
        self.emit("settings", **self.state()["settings"])
        return path

    # ---- Premiere ------------------------------------------------------------ #

    def premiere_info(self) -> dict:
        return {
            "connected": self.premiere.connected,
            "panel": dict(self.premiere.panel),
            "installer": premiere_bridge.installer_path() is not None,
            "panel_source": premiere_bridge.panel_source() is not None,
            "installed": self._panel_installed,
            "last_install": self._last_install,
        }

    def refresh_panel_installed(self) -> None:
        """Ask Adobe's installer what it has, off-thread; it takes a moment."""
        agent = premiere_bridge.installer_path()
        if not agent:
            self._panel_installed = None
            return

        def ask() -> None:
            try:
                self._panel_installed = premiere_bridge.installed_version(agent)
            except Exception:  # noqa: BLE001 — a listing failure is just "unknown"
                self._panel_installed = "?"
            self.emit("premiere", **self.premiere_info())

        threading.Thread(target=ask, daemon=True).start()

    # ---- Resolve Scripts menu ------------------------------------------------ #

    def resolve_menu_info(self) -> dict:
        return resolve_menu.info(self.app_exe)

    def start_install_resolve_menu(self) -> bool:
        if self.busy:
            return False
        threading.Thread(target=self.install_resolve_menu, daemon=True).start()
        return True

    def install_resolve_menu(self) -> None:
        """Write the launcher into Resolve's Scripts menu. Only from a click."""
        self._tool_busy("resolve_menu", True)
        self._last_menu_install = None
        try:
            dest = resolve_menu.install(self.app_exe, self.log)
            self.log(f"Resolve menu entry → {dest}")
            self._last_menu_install = ("ok: Added. Restart Resolve, then it's under "
                                       "Workspace → Scripts → Utility → YEETingus.")
            self.log(self._last_menu_install[4:])
        except resolve_menu.ResolveMenuError as e:
            self._last_menu_install = f"error: {e}"
            self.log(f"ERROR: {e}")
        except Exception as e:  # noqa: BLE001
            self._last_menu_install = f"error: {e}"
            self.log(f"ERROR adding the Resolve menu entry: {e}")
        finally:
            self._tool_busy("resolve_menu", False)
            self.emit("resolve_menu", **self.resolve_menu_info(),
                      last_install=self._last_menu_install)

    def _premiere_changed(self, connected: bool) -> None:
        self.log("Premiere panel " + ("connected." if connected else "disconnected."))
        if self.editor == "premiere":
            self.refresh_connection()
        self.emit("premiere", **self.premiere_info())

    def start_install_premiere_panel(self) -> bool:
        if self.busy:
            return False
        threading.Thread(target=self.install_premiere_panel, daemon=True).start()
        return True

    def install_premiere_panel(self) -> None:
        """Build the .ccx and hand it to Adobe's installer. Only ever from a
        button — nothing is installed into Adobe on its own."""
        self._tool_busy("premiere", True)
        self._last_install = None
        try:
            out = premiere_bridge.install(config._APP_DIR, self.log, app_exe=self.app_exe)
            for line in out.splitlines()[-6:]:
                self.log(f"  {line}")
            self._last_install = ("ok: Panel installed. In Premiere: Window → UXP Plugins → "
                                  "YEETingus, dock it, save the workspace — it's there from then on.")
            self.log(self._last_install[4:])
        except premiere_bridge.PremiereError as e:
            self._last_install = f"error: {e}"
            self.log(f"ERROR: {e}")
        except Exception as e:  # noqa: BLE001
            self._last_install = f"error: {e}"
            self.log(f"ERROR installing the panel: {e}")
        finally:
            self._tool_busy("premiere", False)
            self.emit("premiere", **self.premiere_info())
            self.refresh_panel_installed()

    # ---- boot ------------------------------------------------------------- #

    def start_boot(self) -> threading.Thread:
        t = threading.Thread(target=self.boot, daemon=True)
        t.start()
        return t

    def boot(self) -> None:
        """Resolve dependencies and check Resolve. Blocking."""
        self.log(f"{APP_NAME} {__version__} starting…")
        self.log(f"Clips → {self.download_dir}")

        # Resolved separately rather than via ensure_all, so a missing ffmpeg
        # doesn't also throw away a perfectly good yt-dlp: on macOS ffmpeg is the
        # user's to install, and the Settings button that installs it needs
        # ytdlp_cmd already recorded to pick up where this left off.
        try:
            self.ytdlp_cmd = deps.ensure_ytdlp(self.log)
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR getting yt-dlp: {e}")
            self._set_status("missing tools", "error")
            self._tools_changed()
            return

        try:
            self.ffmpeg_path = deps.ensure_ffmpeg(self.log)
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR: {e}")
            self._set_status("ffmpeg missing", "error")
            self.reveal_log()
            if deps.MACOS_FFMPEG_MANUAL:
                self.log("Open Settings to install it, or run the command above.")
            self._tools_changed()
            return

        self.ytdlp_version = self._probe_version()
        self._probe_hardware()
        # After yt-dlp, because it asks yt-dlp which flags it understands, and
        # non-fatal by design — see _setup_js_runtime.
        self._setup_js_runtime()
        runtime = f" · deno {self.deno_version or '?'}" if self.deno_path else ""
        self.log(f"yt-dlp {self.ytdlp_version or '?'} ready · "
                 f"ffmpeg {os.path.basename(self.ffmpeg_path or '?')}{runtime}")
        self._tools_changed()

        self.check_connection()
        self.refresh_panel_installed()
        self.booted = True
        # Action buttons start disabled until the tools are resolved; a busy
        # event with False is what lets them in.
        self._set_busy(False)

    def _probe_hardware(self) -> None:
        """Find out what the preparation pass can use on this machine.

        A second or so of tiny test encodes/decodes; done once at startup and
        after an ffmpeg install. Never fatal — with nothing found, everything
        still works through the CPU path.
        """
        if not self.ffmpeg_path:
            return
        try:
            self.caps = media.probe_capabilities(self.ffmpeg_path)
        except Exception as e:  # noqa: BLE001
            self.log(f"Hardware check failed ({e}); using the CPU path.")
            self.caps = media.Capabilities()
        self.log(f"Video: {self.caps.describe()}")
        self._tools_changed()

    def _probe_version(self) -> str | None:
        try:
            proc = subprocess.run([*(self.ytdlp_cmd or []), "--version"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=30, **spawn_kwargs())
            return (proc.stdout or "").strip().splitlines()[-1] if proc.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    # ---- Resolve connection ----------------------------------------------- #

    def refresh_connection(self) -> None:
        threading.Thread(target=self.check_connection, daemon=True).start()

    def check_connection(self, quiet: bool = False) -> bool:
        """Report what we can actually see of the chosen editor."""
        if self.editor == "premiere":
            return self._check_premiere(quiet)
        try:
            info = resolve_bridge.get_timeline_info()
        except resolve_bridge.ResolveError as e:
            msg = str(e)
            # Distinguish "Resolve isn't there" from "Resolve is there but has
            # nothing open" — they need different fixes.
            if "timeline" in msg.lower():
                self._set_status("no timeline open", "error")
            elif "project" in msg.lower():
                self._set_status("no project open", "error")
            else:
                self._set_status("Resolve not connected", "error")
            if not quiet:
                self.log(f"RESOLVE: {msg}")
            return False
        except Exception as e:  # noqa: BLE001
            self._set_status("Resolve error", "error")
            if not quiet:
                self.log(f"RESOLVE: unexpected problem — {e}")
            return False

        self._set_status(f"{info['project']} · {info['timeline']}", "ok")
        if not quiet:
            self.log(f"Resolve ready: '{info['timeline']}' @ {info['fps']}fps, "
                     f"playhead {info['currentTimecode']}")
        playback = info.get("playbackFps")
        if playback and abs(playback - float(info["fps"])) > 0.01:
            self.log(f"WARNING: Resolve's playback frame rate is {playback:g} but the "
                     f"timeline is {info['fps']:g} fps — playback will look choppy. "
                     "Project Settings → Master Settings → Playback frame rate.")
        return True

    def _check_premiere(self, quiet: bool) -> bool:
        self.premiere.check()
        if not self.premiere.connected:
            self._set_status("Premiere panel not open", "error")
            if not quiet:
                self.log("PREMIERE: the YEETingus panel isn't open. In Premiere: "
                         "Window → UXP Plugins → YEETingus (dock it and save the "
                         "workspace to keep it).")
            return False
        try:
            info = self.premiere.status()
        except premiere_bridge.PremiereError as e:
            self._set_status("Premiere error", "error")
            if not quiet:
                self.log(f"PREMIERE: {e}")
            return False
        project = info.get("project") or "no project"
        sequence = info.get("sequence") or "no sequence"
        if not info.get("sequence"):
            self._set_status(f"{project} · no sequence open", "error")
            if not quiet:
                self.log("PREMIERE: open a sequence first.")
            return False
        self._set_status(f"{project} · {sequence}", "ok")
        if not quiet:
            fps = info.get("fps")
            self.log(f"Premiere ready: '{sequence}'"
                     + (f" @ {float(fps):.6g}fps." if isinstance(fps, (int, float)) else "."))
        return True

    _RETIME_NAMES = {"nearest": "Nearest", "blend": "Frame Blend", "optical": "Optical Flow",
                     "project": "the project default"}

    def _note_retime(self, res: dict) -> None:
        r = res.get("retimed")
        if r:
            self.log(f"  {r['clipFps']:g} fps clip on a {r['timelineFps']:g} fps timeline — "
                     f"retime set to {self._RETIME_NAMES.get(r['mode'], r['mode'])}.")

    def timeline_fps(self, quiet: bool = True) -> Fraction | None:
        """The chosen editor's current timeline rate, or None if unreachable."""
        try:
            if self.editor == "premiere":
                fps = self.premiere.status().get("fps") if self.premiere.connected else None
            else:
                fps = resolve_bridge.get_timeline_info().get("fps")
        except Exception:  # noqa: BLE001 — no timeline is simply "unknown"
            return None
        if not fps:
            return None
        rate = media.nle_rate(Fraction(fps).limit_denominator(1001))
        return rate

    def _conform_target(self) -> Fraction | None:
        """What rate to deliver at: the timeline's, when conforming is on and
        a timeline is there to ask. Download-only with no editor gets None."""
        if self.conform == "off":
            return None
        if self._timeline_fps is None:
            self._timeline_fps = self.timeline_fps()
        return self._timeline_fps

    def _editor_insert(self, path: str, insert_at: str) -> dict:
        """Paste a file into whichever editor is chosen. Same result shape."""
        if self.editor == "premiere":
            info = self._probe_media(path)
            return self.premiere.insert(path, insert_at, has_video=bool(info and info.vcodec))
        return resolve_bridge.import_and_insert(path, insert_at=insert_at, retime=self.retime)

    # ---- yt-dlp update ----------------------------------------------------- #

    def start_update_ytdlp(self) -> bool:
        if self.busy or not self.ytdlp_cmd:
            return False
        threading.Thread(target=self.update_ytdlp, daemon=True).start()
        return True

    def _ytdlp_help(self) -> str:
        """yt-dlp's --help text, for checking whether a flag exists.

        Probed rather than inferred from the version string: the EJS flags
        arrived in a particular release, but yt-dlp can also come from a distro
        package or a pip install whose version doesn't map cleanly onto one.
        Asking it what it supports can't be wrong.
        """
        try:
            proc = subprocess.run([*(self.ytdlp_cmd or []), "--help"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=60, **spawn_kwargs())
            return proc.stdout or ""
        except Exception:  # noqa: BLE001 — treat unreadable help as "no flags"
            return ""

    def _run_logged(self, args: list[str]) -> tuple[int, str]:
        """Run a command, stream it to the log, and return (exit code, output)."""
        self.log("Running: " + " ".join(args))
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1, **spawn_kwargs())
        assert proc.stdout is not None
        lines: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                self.log(f"  {line}")
        return proc.wait(), "\n".join(lines)

    @staticmethod
    def _is_pip_install(output: str) -> bool:
        """Whether a failed `-U` was refused because pip owns this copy.

        yt-dlp's exact wording is "You installed yt-dlp with pip or using the
        wheel from PyPi; Use that to update", so match on the durable part
        rather than the whole sentence — and note PyPi's unconventional casing,
        which is why this is case-insensitive.
        """
        low = output.lower()
        return "with pip" in low or "wheel from pypi" in low

    @staticmethod
    def _interpreter_for(script: str) -> str | None:
        """The Python that owns a pip console script, or None.

        pip drops `yt-dlp.exe` in `<prefix>\\Scripts` on Windows and `yt-dlp` in
        `<prefix>/bin` elsewhere, with the interpreter one step away in both
        layouts. Derived from the script's own path rather than sys.executable,
        which in a frozen build is YEETingus itself — running `-m pip` on that
        would relaunch the app instead of upgrading anything.
        """
        bindir = os.path.dirname(os.path.abspath(script))
        candidates = ([os.path.join(os.path.dirname(bindir), "python.exe"),
                       os.path.join(bindir, "python.exe")] if sys.platform == "win32"
                      else [os.path.join(bindir, "python3"),
                            os.path.join(bindir, "python")])
        return next((p for p in candidates if os.path.isfile(p)), None)

    def update_ytdlp(self) -> None:
        """Update yt-dlp by whichever route actually owns this copy.

        Three ways it can be installed, and they don't update the same way:

          * a standalone binary, which self-updates with -U;
          * `python -m yt_dlp`, which pip owns;
          * a **pip console script**, which looks exactly like a standalone
            binary from here — same single path, same name — but refuses -U with
            "You installed yt-dlp with pip... Use that to update" and exit 100.

        That third case used to dead-end: the button reported the exit code and
        stopped, with no hint that pip was the answer, while a stale yt-dlp is
        the single most common reason downloads start failing. So a -U refusal
        is now detected and retried through pip automatically.
        """
        self._tool_busy("ytdlp", True)
        try:
            cmd = list(self.ytdlp_cmd or [])
            if not cmd:
                self.log("ERROR: yt-dlp isn't resolved yet; nothing to update.")
                return

            before = self.ytdlp_version
            if len(cmd) > 1:
                # Already `python -m yt_dlp`: pip owns it, and cmd[0] is the
                # interpreter to use.
                code, _ = self._run_logged([cmd[0], "-m", "pip", "install",
                                            "-U", "yt-dlp"])
            else:
                code, out = self._run_logged(cmd + ["-U"])
                if code != 0 and self._is_pip_install(out):
                    self.log("This yt-dlp was installed with pip, which can't "
                             "self-update. Retrying through pip…")
                    python = self._interpreter_for(cmd[0])
                    if python:
                        code, _ = self._run_logged([python, "-m", "pip",
                                                    "install", "-U", "yt-dlp"])
                    else:
                        self.log("ERROR: couldn't find the Python that owns "
                                 f"{cmd[0]}.")
                        self.log("  Update it yourself with:  pip install -U yt-dlp")

            if code == 0:
                self.ytdlp_version = self._probe_version()
                now = self.ytdlp_version or "?"
                self.log(f"yt-dlp is now {now}."
                         + ("  (unchanged — it was already current)"
                            if before and before == self.ytdlp_version else ""))
                self._tools_changed()
            else:
                self.log(f"ERROR: updating yt-dlp failed (exit {code}). See above.")
                self.log("  Fix it by hand with:  pip install -U yt-dlp")
                self.log("  Or delete the copy YEETingus is using and reopen the "
                         "app — it will download its own.")
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR updating yt-dlp: {e}")
        finally:
            self._tool_busy("ytdlp", False)

    # ---- ffmpeg install (macOS) -------------------------------------------- #

    def start_install_ffmpeg(self) -> bool:
        if self.busy:
            return False
        threading.Thread(target=self.install_ffmpeg, daemon=True).start()
        return True

    def install_ffmpeg(self) -> None:
        """Hand off to Homebrew, then adopt the result without a restart."""
        self._tool_busy("ffmpeg", True)
        self.reveal_log()   # brew is chatty and slow; the user should see it working
        try:
            self.ffmpeg_path = deps.install_ffmpeg_via_brew(self.log)
            self._tools_changed()
            self.log("ffmpeg is ready — no restart needed.")
            self._probe_hardware()
            # The boot sequence gives up on a missing ffmpeg and leaves the
            # action buttons disabled; now that it's here, let them back in.
            if self.ytdlp_cmd:
                self.booted = True
                self._set_busy(False)
                self.check_connection()
        except Exception as e:  # noqa: BLE001 — message is written for the log
            self.log(f"ERROR: {e}")
            self._tool_busy("ffmpeg", False)

    # ---- JavaScript runtime ------------------------------------------------ #

    def start_install_js(self) -> bool:
        if self.busy:
            return False
        threading.Thread(target=self.install_js, daemon=True).start()
        return True

    def install_js(self) -> None:
        """Fetch Deno on demand, from Settings, and adopt it without a restart."""
        self._tool_busy("js", True)
        self.reveal_log()   # it's a ~40 MB download; show that something is happening
        if self._setup_js_runtime():
            self.log("JavaScript runtime ready — no restart needed.")
        else:
            self._tool_busy("js", False)

    def _setup_js_runtime(self) -> bool:
        """Find or fetch Deno and build the yt-dlp arguments that point at it.

        YouTube serves its formats behind a JavaScript challenge; yt-dlp solves
        it by running solver scripts in an external runtime. Without one, some
        videos come back missing formats and others don't download at all. See
        https://github.com/yt-dlp/yt-dlp/wiki/EJS

        Never fatal — a download without a runtime is degraded, not impossible,
        so a failure here leaves the app usable and says what to do about it.
        Returns whether a runtime is now in use.
        """
        self.js_args = []
        help_text = self._ytdlp_help()
        if "--js-runtimes" not in help_text:
            self.log("NOTE: this yt-dlp predates YouTube's JavaScript challenge "
                     "support.")
            self.log("      Press 'Update yt-dlp' in Settings if downloads start "
                     "failing.")
            self._js_note = "unused — yt-dlp too old"
            self._tools_changed()
            return False

        try:
            self.deno_path = deps.ensure_deno(self.log)
        except Exception as e:  # noqa: BLE001 — message is written for the log
            self.log(f"WARNING: no JavaScript runtime — {e}")
            self.log("  YouTube may refuse some formats until one is available.")
            self.log("  Retry from Settings, or install Deno yourself: "
                     "https://deno.com")
            self._js_note = None
            self._tools_changed()
            return False

        self.deno_version = deps.deno_version(self.deno_path)
        args = ["--js-runtimes", f"deno:{self.deno_path}"]
        if "--remote-components" in help_text:
            # Last-resort source for the solver scripts, used only when the
            # copies bundled with yt-dlp are missing or too old for the challenge
            # YouTube is currently serving — which is exactly the case where a
            # video would otherwise refuse to download. yt-dlp checks what it
            # fetches against its own hash allowlist before running it, and Deno
            # runs it with no filesystem or network access.
            args += ["--remote-components", "ejs:github"]
        self.js_args = args
        self._js_note = None
        self._tools_changed()
        return True

    # ---- jobs ------------------------------------------------------------- #

    def start_job(self, url: str, in_text: str, out_text: str,
                  max_height: int | None, insert_at: str,
                  insert: bool = True) -> bool:
        """Validate and launch a job on a worker thread.

        Returns False (after logging why) if nothing was started. The form's
        raw text comes in so every front end gets the same validation.
        """
        if not self.ytdlp_cmd:
            self.log("ERROR: yt-dlp isn't available yet.")
            return False
        url = (url or "").strip()
        if not url:
            self.log("ERROR: no video link.")
            return False
        try:
            start, end = validate_range(in_text, out_text)
        except ValueError as e:
            self.log(f"ERROR: {e}")
            return False
        if insert_at not in INSERT_MODES:
            self.log(f"ERROR: unknown insert mode '{insert_at}'.")
            return False
        if insert and not self.check_connection(quiet=True):
            # Refused before the download, not after it: the chosen editor
            # isn't reachable, and a finished clip would only sit there.
            if self.editor == "premiere":
                self.log("ERROR: the YEETingus panel isn't open in Premiere. "
                         "Window → UXP Plugins → YEETingus, then try again "
                         "(or use Download only).")
            else:
                self.log("ERROR: Resolve isn't reachable (running, Studio, a project "
                         "and timeline open, external scripting set to Local?). "
                         "Fix that, or use Download only.")
            return False

        with self._busy_lock:
            if self.busy:
                return False
            self.cancel_event.clear()
            self._set_busy(True)
        threading.Thread(
            target=self.run_job,
            args=(url, start, end, max_height, insert_at, insert),
            daemon=True,
        ).start()
        return True

    def cancel(self) -> bool:
        if not self.busy or self.cancel_event.is_set():
            return False
        self.cancel_event.set()
        self.log("Stopping…")
        self._progress(step="Stopping…")
        self._kill_active()
        return True

    def _kill_active(self) -> None:
        """Kill the running tool and everything it spawned.

        yt-dlp spawns ffmpeg, so the whole tree has to go — killing only the
        parent leaves ffmpeg running, still holding and writing the output file,
        which then can't be cleaned up.

        Windows walks the tree at kill time with `taskkill /T`. POSIX signals the
        process group that spawn_kwargs established, giving it a SIGTERM to
        close its files before escalating to SIGKILL.
        """
        proc = self.active_proc
        if not proc or proc.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=20,
                )
            else:
                try:
                    group = os.getpgid(proc.pid)
                except (ProcessLookupError, PermissionError):
                    # Already reaped, or not ours after all — fall back to the
                    # single process rather than signalling a group we don't own.
                    proc.kill()
                    return
                os.killpg(group, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass  # exited between the poll above and the signal; nothing to do
        except Exception as e:  # noqa: BLE001
            self.log(f"Couldn't stop the process cleanly: {e}")

    def _cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def probe_metadata(self, url: str, quiet: bool = False) -> dict:
        """Look up id/title/channel before downloading, so the clip can be filed
        under a descriptive folder. Best effort — a failure just means a plainer
        folder name, not a failed download.

        `quiet` keeps it out of the log — for a front end previewing a link as
        it's typed, where the chatter would drown the log."""
        log = (lambda *_a, **_k: None) if quiet else self.log
        log("Reading video info…")
        cmd = [*(self.ytdlp_cmd or []), *self.js_args,
               "--dump-single-json", "--no-warnings",
               "--skip-download", "--no-playlist", url]
        try:
            # Popen (not run) so STOP can kill it mid-lookup.
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                **spawn_kwargs(),
            )
            self.active_proc = proc
            out, err = proc.communicate(timeout=120)
            self.active_proc = None
            if self._cancelled():
                return dict(_EMPTY_META)
            proc = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
            if proc.returncode == 0 and (proc.stdout or "").strip():
                data = json.loads(proc.stdout)
                return {
                    "id": data.get("id") or "",
                    "title": data.get("title") or "",
                    "channel": data.get("channel") or data.get("uploader") or "",
                    "heights": _video_heights(data),
                    # None for a livestream, and absent on some extractors.
                    "duration": data.get("duration"),
                    "thumbnail": data.get("thumbnail"),
                    "age_restricted": False,
                }
            tail = (proc.stderr or "").strip().splitlines()
            if tail and _looks_age_gated(tail[-1]):
                # yt-dlp can't even read the page without a signed-in session,
                # so there is nothing to fall back to — say so up front rather
                # than after a doomed download.
                if not quiet:
                    log("This video is age restricted; YouTube won't show it "
                        "without a signed-in session.")
                return {**_EMPTY_META, "id": naming.video_id_from_url(url),
                        "age_restricted": True}
            log("Couldn't read video info; falling back to the URL id.")
            if tail:
                log(f"  {tail[-1]}")
        except Exception as e:  # noqa: BLE001
            log(f"Video info lookup failed: {e}")
        return {**_EMPTY_META, "id": naming.video_id_from_url(url)}

    def _probe_media(self, path: str) -> media.SourceInfo | None:
        """What is actually on disk (codec, size, rate, timing), or None."""
        ffprobe = deps.find_ffprobe()
        if not ffprobe:
            return None
        try:
            return media.probe(ffprobe, path)
        except Exception:  # noqa: BLE001 — a missing detail isn't worth failing over
            return None

    @staticmethod
    def _existing_download(folder: str, stem: str, raw: bool = False) -> str | None:
        """A finished download for `stem`, or None.

        Skips yt-dlp's scratch files and zero-byte remnants, so an interrupted
        attempt is never mistaken for a complete one — that would insert a broken
        file instead of re-downloading. The raw "<stem>.src.*" download is
        skipped too unless `raw` is set, which is how _download finds it.
        """
        try:
            names = os.listdir(folder)
        except OSError:
            return None
        # Prefer the merged mp4, then any other container.
        for name in sorted(names, key=lambda n: (not n.endswith(".mp4"), n)):
            if not name.startswith(stem + "."):
                continue
            if name.endswith((".part", ".ytdl", ".temp")):
                continue
            # A leftover per-stream fragment is video-only or audio-only; treating
            # one as a finished download is what put MEDIA OFFLINE on the timeline.
            # The raw download (".src.") is likewise not the finished file.
            if _FRAGMENT_RE.search(name) or (not raw and (SOURCE_TAG + ".") in name):
                continue
            if not name.lower().endswith(MEDIA_EXTS):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return path
            except OSError:
                continue
        return None

    def _looks_complete(self, path: str, meta: dict) -> bool:
        """Whether an existing whole-video file actually holds the whole video.

        The reuse check accepts any non-empty media file with the right name,
        which is fine until a download dies partway: ffmpeg can leave a valid
        but truncated .mp4 behind, and if cleanup couldn't delete it — Windows
        won't unlink a file the dying ffmpeg still holds — every later attempt
        reports "Already downloaded" and hands Resolve 40 seconds of a
        10-minute video, forever.

        So the file's own duration is compared against the video's. Anything
        materially short is treated as unfinished. Unknown either way means we
        can't judge, and the file is trusted rather than thrown away: a needless
        re-download of a whole video is expensive.
        """
        wanted = meta.get("duration")
        if not isinstance(wanted, (int, float)) or wanted <= 0:
            return True
        actual = self._stream_duration(path)
        if actual is None:
            # ffprobe couldn't read it at all, which a badly truncated file does.
            self.log("  That file can't be read back; treating it as unfinished.")
            return False
        # 5% or two seconds of slack, whichever is larger: a container's own
        # duration rarely matches the metadata to the frame.
        if actual + max(2.0, wanted * 0.05) < wanted:
            self.log(f"  It holds only {seconds_to_timestamp(round(actual))} of "
                     f"{seconds_to_timestamp(round(wanted))} — unfinished.")
            return False
        return True

    def _check_range(self, start: str | None, end: str | None,
                     meta: dict) -> tuple[str | None, str | None] | None:
        """Reconcile the requested section with the video's actual length.

        Asking for a range past the end used to reach ffmpeg, which computed a
        negative duration and emitted twenty lines of filter-graph noise ending
        in "ffmpeg exited with code 4294967262" — plus a 0-byte .part file. None
        of that says "your in point is after the end of the video".

        Returns the (possibly trimmed) range, or None if there is nothing to
        download. A whole-video request and an unknown duration both pass
        straight through — livestreams report no duration, and there is nothing
        to check against.
        """
        if start is None or end is None:
            return start, end
        duration = meta.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            return start, end

        length = seconds_to_timestamp(round(duration))
        if to_seconds(start) >= duration:
            self.log(f"ERROR: the in point ({start}) is past the end of this "
                     f"video, which is {length} long.")
            self.log("       Pick an in point inside the video and try again.")
            return None

        if to_seconds(end) > duration:
            self.log(f"NOTE: the end point is past the end of this video "
                     f"({length}); trimming the request to there.")
            # Back through normalize_timestamp so the trimmed value is in the
            # same HH:MM:SS form as the one the user typed — --download-sections
            # takes a single "*start-end" string, and mixing "00:00:60.00" with
            # "01:15" inside it is asking for a parsing surprise.
            end = normalize_timestamp(seconds_to_timestamp(round(duration))) or end
        return start, end

    def _explain_403(self, got_bytes: bool, age_gated: bool) -> None:
        """Say what a 403 actually means here, and what to do about it.

        This used to read "403 means YouTube refused that format's URL. Try
        'Best available', or hit 'Update yt-dlp'." — which buried the real cause
        behind a suggestion that cannot help. Changing quality does nothing when
        every format is refused, and an out-of-date yt-dlp is far and away the
        common case: YouTube changes its signing regularly and a yt-dlp from
        even a few weeks earlier stops being able to fetch anything.

        The two shapes look different in the log and are worth telling apart:

          * nothing downloaded at all — the URL was rejected outright. For a
            clip that is usually ffmpeg fetching the byte range, since it can't
            reproduce the headers those URLs are bound to.
          * it got part-way, then 403 — reads like a dropped connection, but is
            the same stale-extractor problem showing up mid-transfer.
        """
        version = self.ytdlp_version or "unknown"
        if age_gated:
            self.log("WHY: YouTube refused this video (403) because it is age "
                     "restricted.")
            self.log("     That needs a signed-in session, which YEETingus "
                     "doesn't use. Nothing to fix.")
            return

        if got_bytes:
            self.log("WHY: the download started, then YouTube refused the rest "
                     "with 403.")
            self.log("     That looks like a dropped connection but usually "
                     "isn't — it's the same")
            self.log("     out-of-date yt-dlp problem as an outright refusal.")
        else:
            self.log("WHY: YouTube refused the video URL outright (403). Not a "
                     "resolution problem —")
            self.log("     changing quality won't help, because every format is "
                     "refused the same way.")

        self.log(f"FIX: update yt-dlp. Yours is {version}, and YouTube breaks "
                 "older ones regularly.")
        self.log("     Settings -> Update yt-dlp, then try again.")
        self.log("     (If the update itself fails, the log there says how to "
                 "finish it by hand.)")
        self.log("Still failing on a freshly updated yt-dlp? Age-restricted "
                 "videos always 403 —")
        self.log("  they need a signed-in session. Otherwise it's worth "
                 "reporting.")

    def _prepare(self, raw: str, section: media.Section | None) -> str | None:
        """Turn the raw download into the file the editor gets (media.py
        decides how). Returns the finished path, or None on failure or
        cancellation.

        A file that is already the finished "<stem>.mp4" — a reused whole video,
        including one made by an older version — passes straight through,
        unless the chosen editor can't play its codec (an AV1 file made for
        Resolve, reused for Premiere): then it's converted once more into
        "<stem>.<codec>.mp4" beside it, and that is what gets inserted.
        """
        if (SOURCE_TAG + ".") not in os.path.basename(raw):
            return self._for_editor(raw)

        info = self._probe_media(raw)
        if info is None:
            self.log("ERROR: can't read the download back; nothing to prepare.")
            return None
        out = os.path.splitext(raw.replace(SOURCE_TAG + ".", "."))[0] + ".mp4"
        return self._transcode(raw, info, section, out, keep_source=False)

    def _transcode(self, src_path: str, info: media.SourceInfo,
                   section: media.Section | None, out: str,
                   keep_source: bool) -> str | None:
        """Run the preparation pass from `src_path` to `out`. Returns `out`,
        or None on failure or cancellation. `keep_source` leaves the input
        in place (a finished file being re-made for another editor); the raw
        download is deleted once its conversion succeeds."""
        ffmpeg = self.ffmpeg_path or deps.find_ffmpeg()
        if not ffmpeg:
            self.log("ERROR: ffmpeg isn't available; nothing to prepare.")
            return None
        if self.caps is None:
            self._probe_hardware()
        caps = self.caps or media.Capabilities()

        target = self._conform_target()
        plan = media.plan(info, caps, section, editor=self.editor, target_fps=target,
                          conform=self.conform if self.conform != "off" else "sharp")
        media.assert_allowed_encoder(plan)
        # output_path_for swaps the extension for the plan's container; the
        # sibling's ".hevc" is part of its stem and must survive that.
        out = media.output_path_for(out, plan)
        tmp = f"{os.path.splitext(out)[0]}.tmp.{plan.container}"
        cmd = media.build_command(ffmpeg, info, plan, tmp)

        self.log(f"Downloaded: {info.describe()}" if not keep_source else f"Source: {info.describe()}")
        self.log(f"Preparing: converting with {plan.encoder} "
                 f"(keyframe every {plan.gop} frames) so the editor scrubs it well."
                 + (f" Delivered at {float(plan.rate):g} fps to match the timeline." if plan.conformed else ""))
        estimate = media.estimate_seconds(info, plan, section)
        rough = "a few seconds" if estimate < 15 else (
            "under a minute" if estimate < 60 else f"around {estimate / 60:.0f} min")
        self.log(f"  Expect {rough}. STOP still works.")
        for note in plan.notes:
            self.log(f"  {note}")

        # The span the progress bar counts down: the section, or the whole file.
        total = info.duration
        if section and section.end is not None:
            total = section.end - section.start
        self._progress(P_DOWNLOAD, "Preparing…")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1, **spawn_kwargs())
        self.active_proc = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            if self._cancelled():
                break
            m = _FFMPEG_TIME_RE.match(line)
            if m and total > 0:
                done = min(int(m.group(1)) / 1_000_000 / total, 1.0)
                self._progress(P_DOWNLOAD + (P_PREPARE - P_DOWNLOAD) * done,
                               f"Preparing… {done * 100:.0f}%")
        _, err = proc.communicate()
        self.active_proc = None

        if self._cancelled() or proc.returncode != 0:
            if proc.returncode != 0 and not self._cancelled():
                self.log(f"Preparation failed (exit {proc.returncode}).")
                for l in (err or "").strip().splitlines()[-4:]:
                    self.log(f"  {l}")
                if plan.hardware:
                    # A hardware encoder that passed its probe can still fail on
                    # real footage (driver limits, odd dimensions). Retry on CPU
                    # rather than leave the user with nothing.
                    self.log("  Retrying with the CPU encoder…")
                    self.caps = media.Capabilities(av1_encoder=None, hevc_encoder=None)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    return self._transcode(src_path, info, section, out, keep_source)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None

        try:
            os.replace(tmp, out)
        except OSError as e:
            self.log(f"Prepared fine but couldn't move the result into place: {e}")
            return None
        if not keep_source:
            try:
                os.remove(src_path)
            except OSError:
                self.log(f"  (couldn't delete the raw download {os.path.basename(src_path)})")

        self._progress(P_PREPARE, "Prepared")
        return out

    def _for_editor(self, path: str) -> str | None:
        """`path` if the chosen editor plays it as-is; otherwise a converted
        sibling made now (or reused): "<stem>.hevc.mp4" for Premiere, or
        "<stem>.av1.mp4" for Resolve. The original stays. (Frame rate is not
        re-conformed for an existing clip — that's done once, when the clip is
        made; an old clip on another timeline rate gets Resolve's retime.)"""
        info = self._probe_media(path)
        if info is None:
            return path
        editor_name = "Premiere" if self.editor == "premiere" else "Resolve"
        tags, why = [], []
        if not media.plays_in(self.editor, info.vcodec):
            tags.append("hevc" if self.editor == "premiere" else "av1")
            why.append(f"it's {info.vcodec}, which {editor_name} can't play")
        if not tags:
            return path
        sibling = f"{os.path.splitext(path)[0]}.{'.'.join(tags)}.mp4"
        if os.path.isfile(sibling) and os.path.getsize(sibling) > 0:
            self.log(f"Using {os.path.basename(sibling)} for {editor_name}.")
            return sibling
        self.log(f"Converting a copy of {os.path.basename(path)}: " + "; ".join(why) + "…")
        return self._transcode(path, info, None, sibling, keep_source=True)

    def _stream_duration(self, path: str) -> float | None:
        """Container duration in seconds, for the reuse completeness check."""
        ffprobe = deps.find_ffprobe()
        if not ffprobe:
            return None
        try:
            proc = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=60, **spawn_kwargs())
            return float((proc.stdout or "").strip())
        except Exception:  # noqa: BLE001 — no duration just means a vaguer bar
            return None

    def _resolve_quality(self, max_height: int | None, meta: dict) -> int | None:
        """Reconcile the requested cap with what the video actually offers.

        Asking for 4K on a 1080p upload used to just fail; now we say what the
        video has and fall back to its best instead.
        """
        heights = meta.get("heights") or []
        if not heights:
            self.log("Couldn't read available formats; trying your selection as-is.")
            return max_height

        self.log("Available: " + ", ".join(f"{h}p" for h in heights))
        best = heights[0]

        if max_height is None:
            self.log(f"Using best available ({best}p).")
            return None

        if max_height > best:
            self.log(f"NOTE: {max_height}p isn't available for this video — "
                     f"the highest is {best}p. Using {best}p instead.")
            return best

        chosen = next((h for h in heights if h <= max_height), best)
        self.log(f"Using {chosen}p (capped at {max_height}p).")
        return max_height

    def run_job(self, url, start, end, max_height, insert_at, insert=True) -> None:
        """The whole job, blocking. start_job is the normal way in."""
        self._timeline_fps = None
        try:
            self._progress(P_INFO, "Reading video info…")
            meta = self.probe_metadata(url)
            if self._cancelled():
                self._stopped()
                return

            if meta.get("age_restricted"):
                self._explain_403(got_bytes=False, age_gated=True)
                self._progress(0.0, "Age restricted — can't download")
                self.reveal_log()
                return

            max_height = self._resolve_quality(max_height, meta)

            checked = self._check_range(start, end, meta)
            if checked is None:
                self._progress(0.0, "Nothing to download — see log")
                self.reveal_log()
                return
            start, end = checked

            raw = self._download(url, start, end, max_height, meta)
            if self._cancelled():
                self._stopped()
                return
            if not raw:
                self._progress(0.0, "Failed — see log")
                self.reveal_log()
                return

            # The preparation pass: the fast, seek-friendly transcode described
            # in media.py. A reused whole video has already been through it (it
            # is the finished "<stem>.mp4").
            section = None
            if start is not None and end is not None:
                section = media.Section(to_seconds(start), to_seconds(end))
            path = self._prepare(raw, section)
            if self._cancelled():
                self._stopped()
                return
            if path is None:
                self._progress(0.0, "Failed — see log")
                self.reveal_log()
                return

            if insert:
                # Past this point the file exists; the insert itself is quick and
                # atomic enough that we let it finish rather than half-cancel it.
                self._progress(P_INSERT, "Pasting into timeline…")
                self.log("Sending to " + ("Premiere…" if self.editor == "premiere" else "Resolve…"))
                res = self._editor_insert(path, insert_at)
                self.log(f"Inserted '{res['clipName']}' at frame "
                         f"{res['insertedFrame']}. Done.")
                self._note_retime(res)
            else:
                res = {"clipName": os.path.basename(path)}
                self.log(f"Downloaded '{res['clipName']}' — not inserted. Done.")
                self.log(f"  Saved to: {path}")

            # Recap what we got — the filename is only an id, so the
            # human-readable title and channel are worth restating here.
            info = self._probe_media(path)
            self.log(f"  Video:   {meta.get('title') or 'unknown'}")
            self.log(f"  Channel: {meta.get('channel') or 'unknown'}")
            self.log(f"  Quality: {info.describe() if info else 'unknown'}")
            self._write_sidecar(path, url, meta, start, end,
                                info.describe() if info else None,
                                info.duration if info else None)
            self.emit("clips")

            self.log("Make sure to credit the sources!", tag="highlight")
            self._progress(1.0, f"Done — {res['clipName']}")
            if insert:
                self.check_connection(quiet=True)
        except resolve_bridge.ResolveError as e:
            self.log(f"RESOLVE: {e}")
            self._progress(0.0, "Resolve error — see log")
            self.reveal_log()
            self.check_connection(quiet=True)
        except premiere_bridge.PremiereError as e:
            self.log(f"PREMIERE: {e}")
            self._progress(0.0, "Premiere error — see log")
            self.reveal_log()
            self.check_connection(quiet=True)
        except Exception as e:  # noqa: BLE001
            if self._cancelled():
                self._stopped()          # a kill surfaces as an exception too
            else:
                self.log(f"ERROR: {e}")
                self._progress(0.0, "Failed — see log")
                self.reveal_log()
        finally:
            self.active_proc = None
            self._set_busy(False)

    # ---- clip library ------------------------------------------------------ #
    #
    # The clips folder is the database: one subfolder per video
    # ("<id> - <title> - <channel>", see naming.py) holding "<stem>.mp4" files,
    # plus a "<stem>.json" sidecar written after each job with what the folder
    # name can't hold exactly (the full title, the thumbnail, the section).
    # Clips made before the sidecar existed are listed from their names.

    SIDECAR_EXT = ".json"

    def _write_sidecar(self, path: str, url: str, meta: dict,
                       start: str | None, end: str | None,
                       quality: str | None, duration: float | None = None) -> None:
        data = {
            "duration": duration,
            "id": meta.get("id") or "",
            "title": meta.get("title") or "",
            "channel": meta.get("channel") or "",
            "url": url,
            "thumbnail": meta.get("thumbnail"),
            "section": None if start is None else {"start": start, "end": end},
            "quality": quality,
            "created": time.time(),
        }
        try:
            with open(os.path.splitext(path)[0] + self.SIDECAR_EXT, "w",
                      encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError as e:
            self.log(f"  (couldn't write the clip's info file: {e})")

    @staticmethod
    def _read_sidecar(path: str) -> dict:
        try:
            with open(os.path.splitext(path)[0] + Engine.SIDECAR_EXT, "r",
                      encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _parse_folder(name: str) -> tuple[str, str, str]:
        """"<id> - <title> - <channel>" back into its parts, best effort: the
        title may itself contain " - ", so the first part is the id, the last
        the channel (when there are three or more), the rest the title."""
        parts = name.split(" - ")
        if len(parts) == 1:
            return parts[0], "", ""
        if len(parts) == 2:
            return parts[0], parts[1], ""
        return parts[0], " - ".join(parts[1:-1]), parts[-1]

    def _is_finished_clip(self, name: str) -> bool:
        low = name.lower()
        if not low.endswith(MEDIA_EXTS):
            return False
        # A per-editor copy ("<stem>.hevc.mp4", "<stem>.av1.mp4") belongs to
        # its clip, not the list.
        if _SIBLING_RE.search(name):
            return False
        if (SOURCE_TAG + ".") in low or ".tmp." in low or _FRAGMENT_RE.search(name):
            return False
        return not low.endswith((".part", ".ytdl", ".temp"))

    def _inside_library(self, path: str) -> bool:
        root = os.path.realpath(self.download_dir)
        target = os.path.realpath(path)
        try:
            return os.path.commonpath([root, target]) == root and target != root
        except ValueError:
            return False        # different drives

    def list_clips(self) -> list[dict]:
        """Every finished clip under the clips folder, newest first."""
        root = self.download_dir
        clips: list[dict] = []
        try:
            entries = os.listdir(root)
        except OSError:
            return clips

        def add(folder: str, name: str, video_id: str, title: str, channel: str) -> None:
            path = os.path.join(folder, name)
            try:
                st = os.stat(path)
            except OSError:
                return
            if st.st_size <= 0:
                return
            side = self._read_sidecar(path)
            stem = os.path.splitext(name)[0]
            m = re.search(r"-c(\d+)$", stem)
            clips.append({
                "path": path,
                "name": name,
                "folder": folder,
                "id": side.get("id") or video_id,
                "title": side.get("title") or title,
                "channel": side.get("channel") or channel,
                "url": side.get("url"),
                "thumbnail": side.get("thumbnail"),
                "section": side.get("section"),
                "quality": side.get("quality"),
                "kind": "full" if stem.endswith("-full") else "clip",
                "number": int(m.group(1)) if m else None,
                "size": st.st_size,
                "mtime": side.get("created") or st.st_mtime,
                "duration": side.get("duration"),
                "source": self.clip_source_url(path),
            })

        for entry in entries:
            full = os.path.join(root, entry)
            if os.path.isdir(full):
                video_id, title, channel = self._parse_folder(entry)
                try:
                    names = os.listdir(full)
                except OSError:
                    continue
                for name in names:
                    if self._is_finished_clip(name):
                        add(full, name, video_id, title, channel)
            elif self._is_finished_clip(entry):
                # Older layout: clips straight in the root.
                add(root, entry, "", "", "")

        clips.sort(key=lambda c: c["mtime"], reverse=True)
        self._fill_durations([c["path"] for c in clips if c["duration"] is None])
        return clips

    _durations_thread: threading.Thread | None = None

    def _fill_durations(self, paths: list[str]) -> None:
        """Clips from before the sidecar existed have no stored length. Probe
        them once, off the caller's thread, write it into their sidecars and
        say the library changed — the list is served immediately and fills in
        a moment later."""
        if not paths:
            return
        if self._durations_thread and self._durations_thread.is_alive():
            return              # one sweep at a time; it'll pick up the rest

        def sweep() -> None:
            done = 0
            for path in paths:
                seconds = self._stream_duration(path)
                if seconds is None:
                    continue
                side = self._read_sidecar(path)
                side["duration"] = seconds
                try:
                    with open(os.path.splitext(path)[0] + self.SIDECAR_EXT, "w",
                              encoding="utf-8") as fh:
                        json.dump(side, fh, indent=2, ensure_ascii=False)
                    done += 1
                except OSError:
                    pass
            if done:
                self.emit("clips")

        self._durations_thread = threading.Thread(target=sweep, daemon=True)
        self._durations_thread.start()

    def start_insert(self, paths: list[str] | str, insert_at: str) -> bool:
        """Paste clips that are already on disk into the timeline, in order.
        Same busy slot as a job, so the buttons behave the same way."""
        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in paths if p]
        if not paths:
            return False
        for path in paths:
            if not self._inside_library(path) or not os.path.isfile(path):
                self.log("ERROR: that clip isn't in the clips folder any more.")
                return False
        if insert_at not in INSERT_MODES:
            self.log(f"ERROR: unknown insert mode '{insert_at}'.")
            return False
        with self._busy_lock:
            if self.busy:
                return False
            self.cancel_event.clear()
            self._set_busy(True)
        threading.Thread(target=self._insert_existing, args=(paths, insert_at),
                         daemon=True).start()
        return True

    def _insert_existing(self, paths: list[str], insert_at: str) -> None:
        total = len(paths)
        try:
            self.cancel_event.clear()
            last = None
            for i, path in enumerate(paths):
                if self.cancel_event.is_set():
                    self.log("Cancelled.")
                    self._progress(0.0, "Cancelled")
                    return
                which = f" ({i + 1}/{total})" if total > 1 else ""
                usable = self._for_editor(path)
                if usable is None:
                    self._progress(0.0, "Failed — see log")
                    self.reveal_log()
                    return
                path = usable
                self._progress(P_INSERT + (1.0 - P_INSERT) * i / total,
                               f"Pasting into timeline…{which}")
                self.log(f"Sending {os.path.basename(path)} to "
                         + ("Premiere…" if self.editor == "premiere" else "Resolve…")
                         + which)
                res = self._editor_insert(path, insert_at)
                self.log(f"Inserted '{res['clipName']}' at frame "
                         f"{res['insertedFrame']}. Done.")
                self._note_retime(res)
                last = res
            if last is not None:
                self._progress(1.0, f"Done — {total} clips" if total > 1
                               else f"Done — {last['clipName']}")
            self.check_connection(quiet=True)
        except resolve_bridge.ResolveError as e:
            self.log(f"RESOLVE: {e}")
            self._progress(0.0, "Resolve error — see log")
            self.reveal_log()
            self.check_connection(quiet=True)
        except premiere_bridge.PremiereError as e:
            self.log(f"PREMIERE: {e}")
            self._progress(0.0, "Premiere error — see log")
            self.reveal_log()
            self.check_connection(quiet=True)
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR: {e}")
            self._progress(0.0, "Failed — see log")
            self.reveal_log()
        finally:
            self.active_proc = None
            self._set_busy(False)

    def delete_clip(self, path: str) -> bool:
        """Remove a clip and its sidecar; drop the folder too once it's empty.
        Refused while a job runs — it might be the file being written."""
        if self.busy:
            self.log("ERROR: can't delete while a job is running.")
            return False
        if not self._inside_library(path) or not os.path.isfile(path):
            self.log("ERROR: that clip isn't in the clips folder any more.")
            return False
        try:
            os.remove(path)
        except OSError as e:
            self.log(f"ERROR: couldn't delete {os.path.basename(path)} — {e}")
            return False
        stem = os.path.splitext(path)[0]
        import glob as _glob
        for extra in [stem + self.SIDECAR_EXT] + [
                p for p in _glob.glob(_glob.escape(stem) + ".*.mp4") if _SIBLING_RE.search(p)]:
            try:
                os.remove(extra)
            except OSError:
                pass
        folder = os.path.dirname(path)
        try:
            if os.path.realpath(folder) != os.path.realpath(self.download_dir) \
                    and not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass
        self.log(f"Deleted {os.path.basename(path)}.")
        self.emit("clips")
        return True

    def clip_file(self, path: str) -> str | None:
        """The clip's own path if it's ours and still there, else None."""
        if not self._inside_library(path) or not os.path.isfile(path):
            return None
        return path

    def clip_source_url(self, path: str) -> str | None:
        """Where a clip came from: the sidecar's url, or a YouTube watch link
        rebuilt from the id for clips that predate sidecars. None if unknown."""
        if not self._inside_library(path):
            return None
        side = self._read_sidecar(path)
        if side.get("url"):
            return str(side["url"])
        video_id = side.get("id") or self._parse_folder(
            os.path.basename(os.path.dirname(path)))[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
            return f"https://www.youtube.com/watch?v={video_id}"
        return None

    def clip_folder(self, path: str) -> str | None:
        """The folder to open for a clip, or None if it isn't ours."""
        if not self._inside_library(path):
            return None
        return os.path.dirname(path)

    def _stopped(self) -> None:
        self.log("Stopped.")
        self._progress(0.0, "Stopped")

    def _cleanup_partial(self, folder: str, stem: str) -> None:
        """Remove the fragments of a cancelled or failed download.

        Retried, because the first attempt usually loses a race: yt-dlp has
        exited but the ffmpeg it spawned still holds the output open for a
        moment, and Windows refuses to unlink an open file. A single try left a
        truncated .mp4 on disk — which for a whole video is worse than clutter,
        since the reuse check would then hand that half-file to Resolve forever.
        _looks_complete is the backstop for when this still fails.
        """
        removed = 0
        stuck: list[str] = []
        for attempt in range(4):
            stuck = []
            try:
                names = [n for n in os.listdir(folder) if n.startswith(stem + ".")]
            except OSError:
                return
            if not names:
                break
            for name in names:
                try:
                    os.remove(os.path.join(folder, name))
                    removed += 1
                except OSError:
                    stuck.append(name)
            if not stuck:
                break
            if attempt < 3:
                time.sleep(0.5)     # let the dying ffmpeg release its handle

        if removed:
            self.log(f"Cleaned up {removed} partial file(s).")
        for name in stuck:
            self.log(f"! couldn't delete {name} — something still has it open.")
            self.log("  Delete it by hand if the next attempt reuses it.")

    def _download(self, url, start, end, max_height, meta: dict) -> str | None:
        # Checked explicitly, because the bare OSError from makedirs surfaces as
        # "[WinError 3] The system cannot find the path specified: 'Q:\\'" with
        # nothing to say it is the clips folder. The realistic cause is a clip
        # folder on a drive that isn't mounted right now.
        try:
            os.makedirs(self.download_dir, exist_ok=True)
        except OSError as e:
            self.log(f"ERROR: can't use the clips folder — {e}")
            self.log(f"       {self.download_dir}")
            self.log("       If that's on a removable drive, reconnect it; "
                     "otherwise pick another")
            self.log("       folder in Settings.")
            return None
        video_id = meta.get("id") or "unknown-id"

        # "<ID> - <title> - <channel>", sanitised for any OS.
        job_dir = naming.ensure_clip_folder(
            self.download_dir, video_id, meta.get("title", ""), meta.get("channel", ""))
        whole = start is None or end is None
        channel = meta.get("channel", "")

        if whole:
            # One fixed name per video, so a repeat request can reuse it.
            stem = naming.full_stem(video_id, channel)
            existing = self._existing_download(job_dir, stem)
            if existing and not self._looks_complete(existing, meta):
                # Left by an interrupted attempt. Removed rather than resumed:
                # yt-dlp has no idea it's there, and leaving it would mean
                # reusing it again on the next run.
                self.log("  Downloading it again.")
                try:
                    os.remove(existing)
                except OSError as e:
                    self.log(f"! couldn't remove it ({e}); delete it by hand "
                             "if this keeps happening.")
                existing = None
            if existing:
                self.log(f"Already downloaded — reusing {os.path.basename(existing)}")
                info = self._probe_media(existing)
                if info:
                    self.log(f"  {info.describe()}")
                self.log("  Delete that file to download it again.")
                self._progress(P_DOWNLOAD, "Using existing download…")
                return existing
        else:
            # "<id>-<ChannelName>-cNNN", numbered from what's already on disk so
            # nothing is ever overwritten.
            stem = naming.next_clip_stem(job_dir, video_id, channel)

        self.log(f"Folder: {os.path.basename(job_dir)}")
        self.log(f"File:   {stem}.mp4")

        cmd = [
            *(self.ytdlp_cmd or []),
            *self.js_args,
            url,
            "-f", format_selector(max_height),
            "-S", FORMAT_SORT,
            # MP4 for the raw download: yt-dlp then hides the keyframe lead of a
            # section behind an edit list, so the file already plays from the
            # in point and the conversion's trim has nothing left to do.
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", os.path.join(job_dir, stem + SOURCE_TAG + ".%(ext)s"),
            "--newline",
        ]
        if not whole:
            # Section mode: fetch only the requested range, cut at the keyframe
            # before the in point and exactly at the end point, with no
            # re-encoding here — the preparation pass makes the in point exact
            # (media.py explains how). Never --force-keyframes-at-cuts: that
            # re-encodes every clip with the container's default encoder.
            cmd += ["--download-sections", f"*{start}-{end}"]
        if self.ffmpeg_path:
            cmd += ["--ffmpeg-location", os.path.dirname(self.ffmpeg_path)]

        label = quality_label(max_height)
        if whole:
            self.log(f"Fetching the entire video at {label}…")
        else:
            self.log(f"Fetching *{start}-{end} at {label}…")
        # yt-dlp spends a moment extracting and selecting formats before any frames
        # arrive, so say what we're actually doing instead of leaving the label
        # on "Reading video info...".
        self._progress(step="Preparing download…")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, **spawn_kwargs())
        self.active_proc = proc
        assert proc.stdout is not None
        saw_403 = False
        saw_no_js = False
        saw_age_gate = False
        got_bytes = False        # did any data actually arrive before it died?
        phase = "prepare"
        for line in proc.stdout:
            if self._cancelled():
                break
            line = line.rstrip()
            if not line:
                continue
            self.log(line)
            low = line.lower()
            if "403" in line and "forbidden" in low:
                saw_403 = True
            if "javascript runtime" in low:
                saw_no_js = True
            if "age" in low and ("confirm" in low or "sign in" in low
                                 or "inappropriate" in low):
                saw_age_gate = True

            # yt-dlp reports a percentage per stream; map it into the download
            # band so the bar tracks real progress instead of guessing.
            m = _PCT_RE.search(line)
            if m:
                phase = "download"
                if float(m.group(1)) > 0:
                    got_bytes = True
                pct = float(m.group(1)) / 100.0
                self._progress(P_INFO + (P_DOWNLOAD - P_INFO) * pct,
                               f"Downloading… {m.group(1)}%")
            elif low.startswith("[download]") and phase != "download":
                # First [download] line (usually "Destination: ...") — frames are
                # coming now, so stop claiming we're still reading info.
                phase = "download"
                self._progress(step="Downloading…")
            elif any(mark in low for mark in _POST_MARKERS) and phase != "post":
                phase = "post"
                self._progress(P_DOWNLOAD, "Merging & trimming…")
        proc.wait()
        self.active_proc = None

        if self._cancelled():
            # Drop the half-written pieces so this clip number stays free.
            self._cleanup_partial(job_dir, stem)
            return None

        if proc.returncode != 0:
            # Same cleanup as a cancellation. Without it a failed attempt leaves
            # "<stem>.mp4.part" behind, and next_clip_stem counts that as taken —
            # so every failure permanently burned a clip number and left junk in
            # the folder. On a flaky connection that adds up fast.
            self._cleanup_partial(job_dir, stem)
            self.log(f"yt-dlp exited with code {proc.returncode}.")
            if saw_no_js:
                # The most likely cause of a YouTube failure now, and the one
                # with a concrete fix, so it goes first. Deliberately not phrased
                # as "not installed": yt-dlp prints the same complaint for a
                # runtime that is present but older than it accepts.
                self.log("HINT: yt-dlp found no usable JavaScript runtime, so "
                         "YouTube withheld formats.")
                self.log("      Check the JS line in Settings — see "
                         "https://github.com/yt-dlp/yt-dlp/wiki/EJS")
            if saw_403:
                self._explain_403(got_bytes, saw_age_gate)
            return None

        # The merged raw file if it's there, otherwise another container —
        # never a scratch file and never a per-stream fragment, which would be
        # video-only or audio-only.
        produced = self._existing_download(job_dir, stem + SOURCE_TAG, raw=True)
        if not produced:
            self._cleanup_partial(job_dir, stem)
            self.log("yt-dlp finished but produced no usable file.")
            self.log("  (only per-stream fragments were found — the merge step "
                     "may have failed)")
            return None
        return produced
