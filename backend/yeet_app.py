#!/usr/bin/env python3
"""
YEETingus — pull a time-ranged fragment of a YouTube video with yt-dlp and paste it
straight onto the current DaVinci Resolve timeline.

Run from source (needs Python 3.6-3.13 — Resolve's fusionscript library is a C
extension that CRASHES on 3.14+; see resolve_bridge.MAX_PY):

    py -3.13 yeet_app.py

yt-dlp and ffmpeg are fetched automatically on first run into
%LOCALAPPDATA%\\YEETingus\\bin if they aren't already available.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config                    # noqa: E402
import deps                      # noqa: E402
import naming                    # noqa: E402
import resolve_bridge            # noqa: E402
import theme as T                # noqa: E402
from version import APP_NAME, AUTHOR_URL, COPYRIGHT, __version__  # noqa: E402

# Progress is split into bands so the bar moves through the whole job, not just
# the download: info lookup, download, then the Resolve insert.
# Progress-bar milestones. P_CONVERT is only reached when a whole video needs
# re-encoding to H.264; without that step the bar goes straight from P_DOWNLOAD
# to P_INSERT.
P_INFO, P_DOWNLOAD, P_CONVERT, P_INSERT = 0.06, 0.70, 0.94, 0.97

_PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

# ffmpeg -progress output, for the re-encode pass: "out_time_us=12345678".
_FFMPEG_TIME_RE = re.compile(r"^out_time_us=(\d+)", re.MULTILINE)

# Width of the log panel docked to the right; the window grows by this when the
# log is shown. Authored at 96 DPI like every other pixel value.
LOG_PANEL_W = 420

def _spawn_kwargs() -> dict:
    """subprocess keyword arguments for launching an external tool.

    Two platform concerns, both invisible when they work:

    * No console window on Windows. CREATE_NO_WINDOW doesn't exist on POSIX, and
      passing 0 there is accepted and ignored.
    * A killable process group. yt-dlp spawns ffmpeg as a child, so STOP has to
      take out the whole tree — killing the parent alone leaves ffmpeg running
      and still writing to the output file. Windows does this at kill time with
      `taskkill /T`, which walks the tree itself. POSIX has no equivalent, so the
      group must be established when the process starts: start_new_session puts
      the child in a fresh process group whose id equals its pid, which
      os.killpg can then signal as a unit. Set it here or STOP cannot work.
    """
    kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    return kwargs


# yt-dlp's post-download stages. --force-keyframes-at-cuts re-encodes around the
# cut points, so this can take a while and deserves its own label rather than
# sitting at "Downloading... 100%".
_POST_MARKERS = ("[merger]", "[videoconvertor]", "[videoremuxer]", "[fixup",
                 "[extractaudio]", "[postprocess", "[splitchapters]")

# Clip-length shortcuts: end point = in point + N seconds. These get their own
# buttons; the longer presets live behind the dropdown arrow.
QUICK_DURATIONS = (("15s", 15), ("30s", 30), ("90s", 90))
MORE_DURATIONS = (("2 minutes", 120), ("5 minutes", 300), ("10 minutes", 600))

# Both points at zero means "no section" — yt-dlp fetches the whole video.
WHOLE_VIDEO_HINT = (
    "Leave both the in point and end point at 00:00\n"
    "to download the entire video."
)

YEET_LABEL = "YEET (download & insert)"

QUALITY_OPTIONS = {
    "Best available": None,
    "2160p (4K)": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}

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


# Prefer H.264 *without* sacrificing resolution: sort by resolution first, then
# by codec. A fallback chain like "avc1 else anything" would silently cap "Best
# available" at 1080p, since that's as high as YouTube's H.264 goes.
#
# Why bother: H.264 hardware-decodes and scrubs well in Resolve, VP9 less so and
# AV1 poorly. YouTube also serves AV1 inside .mp4, so "ext=mp4" alone doesn't
# guarantee H.264.
#
# acodec:aac is not optional. Resolve cannot decode Opus at all — a clip with an
# Opus track imports and plays with silence. Without naming an audio codec here
# yt-dlp picks Opus by preference even when YouTube also offers AAC, which it
# almost always does.
FORMAT_SORT = "res,vcodec:h264,acodec:aac"

# The other way round: codec first, so H.264 wins even when that costs
# resolution. Used for a whole-video download when the user has turned the
# re-encode off — the point is then to avoid ever receiving VP9/AV1, which caps
# the result at 1080p because that is as high as YouTube's H.264 goes.
FORMAT_SORT_H264_FIRST = "vcodec:h264,res,acodec:aac"

# Re-encode settings for _to_h264. CRF 20 is visually transparent for editing
# footage. The preset is "medium" rather than something faster because decoding
# the VP9 source dominates the run: measured on a 4K60 clip, "fast" saved 7% of
# the time and cost 14% more file size, so the slower preset is the better trade.
REENCODE_CRF = "20"
REENCODE_PRESET = "medium"

# yt-dlp's intermediate per-stream files, e.g. "<stem>.f313.webm" (video only) and
# "<stem>.f140.m4a" (audio only), which it merges and then deletes. An interrupted
# download leaves them behind, and handing one to Resolve gives MEDIA OFFLINE.
_FRAGMENT_RE = re.compile(r"\.f\d+\.", re.IGNORECASE)

# Containers a finished download can legitimately arrive in.
MEDIA_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v")


def _asset(name: str) -> str | None:
    """An asset path, whether running frozen or from source."""
    if getattr(sys, "frozen", False):
        candidate = os.path.join(getattr(sys, "_MEIPASS", ""), "assets", name)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(os.path.dirname(here), "assets", name)
    return candidate if os.path.isfile(candidate) else None


def icon_path() -> str | None:
    """The app icon, whether running frozen or from source."""
    return _asset(f"{APP_NAME.lower()}.ico")


# Held for the lifetime of the process: Tk keeps only a weak reference to a
# PhotoImage passed to iconphoto, so letting it be collected blanks the icon.
_icon_image = None


def apply_icon(window: tk.Misc) -> None:
    """Set the window/taskbar icon. Silently skipped if no asset is available.

    iconbitmap wants a .ico on Windows and refuses one everywhere else, so on
    macOS and Linux the PNG goes through iconphoto instead. On macOS this mostly
    affects running from source — a built .app takes its Dock icon from the
    bundle's .icns, which the window setting can't override.
    """
    global _icon_image
    if sys.platform == "win32":
        path = icon_path()
        if not path:
            return
        try:
            window.iconbitmap(path)      # type: ignore[attr-defined]
        except tk.TclError:
            pass
        return

    png = _asset("logo.png")
    if not png:
        return
    try:
        _icon_image = tk.PhotoImage(file=png)
        window.iconphoto(True, _icon_image)   # type: ignore[attr-defined]
    except tk.TclError:
        pass


def format_selector(max_height: int | None) -> str:
    """yt-dlp -f expression. Codec preference is handled by FORMAT_SORT."""
    if max_height is None:
        return "bv*+ba/b"
    h = max_height
    return f"bv*[height<={h}]+ba/b[height<={h}]/b"


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


class YeetApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False
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
        # Cancellation: the event is checked between phases and inside the
        # download loop; active_proc lets us kill yt-dlp (and its ffmpeg child)
        # mid-flight rather than waiting for it to finish.
        self.cancel_event = threading.Event()
        self.active_proc: subprocess.Popen | None = None
        self.settings = config.load()
        self.download_dir = self.settings["download_dir"]
        self.default_length = self.settings["default_length"]
        self.reencode_h264 = self.settings["reencode_h264"]
        # "Update yt-dlp" lives in the Settings window, which may be closed while
        # an update is still running — hence the nullable reference.
        self.update_btn: T.RoundButton | None = None
        self.ytdlp_info_var = tk.StringVar(value="checking…")
        self.ffmpeg_info_var = tk.StringVar(value="checking…")
        self.js_info_var = tk.StringVar(value="checking…")
        # Settings-window buttons; None whenever that window isn't open.
        self.ffmpeg_btn = None
        self.js_btn = None

        root.title(APP_NAME)
        root.configure(bg=T.BG)
        apply_icon(root)
        # Must happen before any widget is built: Tk scales fonts by DPI but not
        # pixel dimensions, so without this the chrome stays small while the text
        # grows, and the whole window looks cramped on a HiDPI display.
        T.apply_ui_scale(root)
        T.style_combobox(root)

        self._build_ui()
        # Sized to the controls; the log is collapsed at startup and the window
        # widens by LOG_PANEL_W when it's shown.
        root.update_idletasks()
        root.geometry(f"{T.px(720)}x{self._fit_height(root.winfo_reqheight())}")
        # Derive the floor from what the controls actually need, so a long button
        # label can't be clipped by dragging the window narrow.
        root.minsize(max(T.px(470), root.winfo_reqwidth()), root.winfo_reqheight())
        # Dark native title bar; without this Windows draws a white bar above a
        # near-black window. Re-applied on focus because Windows can reset it when
        # the OS theme changes while the app is running.
        T.apply_titlebar_theme(root)
        root.bind("<FocusIn>", lambda _e: T.apply_titlebar_theme(root), add="+")

        self._poll_log_queue()
        threading.Thread(target=self._boot, daemon=True).start()

    def _fit_height(self, wanted: int) -> int:
        """Clamp a window height to what the screen can actually show.

        At 150% scale on a 4K display the scaled layout wants ~1700px, and opening
        the log would push it past the bottom of the screen (and behind the
        taskbar), where the buttons become unreachable.
        """
        usable = int(self.root.winfo_screenheight() * 0.92)
        floor = T.px(420)
        if usable <= floor:          # implausibly short screen; don't fight it
            return wanted
        return max(floor, min(wanted, usable))

    def _fit_width(self, wanted: int) -> int:
        """Same clamp for width, so opening the log can't push the window off the
        side of the screen."""
        usable = int(self.root.winfo_screenwidth() * 0.95)
        floor = T.px(470)
        if usable <= floor:
            return wanted
        return max(floor, min(wanted, usable))

    # ---- layout ----------------------------------------------------------- #

    def _build_ui(self) -> None:
        # Two columns: the controls, and the log docked to their right. Everything
        # below builds into `root` (the left column) exactly as before; only the
        # log lives in the shell so it can sit beside rather than under.
        shell = tk.Frame(self.root, bg=T.BG)
        shell.pack(fill="both", expand=True)
        self._shell = shell
        root = tk.Frame(shell, bg=T.BG)
        root.pack(side="left", fill="both", expand=True)
        self._column = root

        # Header ------------------------------------------------------------
        header = tk.Frame(root, bg=T.BG)
        header.pack(fill="x", padx=T.px(26), pady=(T.px(22), T.px(16)))

        mark = tk.Frame(header, bg=T.BG)
        mark.pack(side="left")
        tk.Label(mark, text=APP_NAME, bg=T.BG, fg=T.ACCENT,
                 font=(T.FONT, 24, "bold")).pack(side="left")
        tk.Label(mark, text=f"  v{__version__}", bg=T.BG,
                 fg=T.MUTED, font=(T.FONT, 10)).pack(side="left", pady=(T.px(10), 0))

        right = tk.Frame(header, bg=T.BG)
        right.pack(side="right", pady=(T.px(8), 0))
        self.status = T.StatusPill(right)
        self.status.pack(side="left")
        refresh = T.ghost_button(right, "↻", self.refresh_connection, height=30,
                                 width=36, radius=9, font=(T.FONT, 11))
        refresh.pack(side="left", padx=(T.px(12), 0))
        T.tooltip(refresh, "Re-check the connection to DaVinci Resolve.")

        # 1. Source --------------------------------------------------------- #
        card1 = T.Card(root)
        card1.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        b = card1.body
        T.step_header(b, 1, "Source").pack(anchor="w", pady=(0, T.px(18)))

        T.field_label(b, "Video link").pack(anchor="w")
        self.url_var = tk.StringVar()
        # Auto-detect a ?t= timestamp as soon as a link is pasted.
        self._auto_ts_url: str | None = None
        self.url_var.trace_add("write", self._on_url_changed)
        # width=1 keeps the requested size minimal; fill="x" makes it span the card.
        url_entry = T.entry(b, self.url_var, width=1)
        url_entry.pack(fill="x", pady=(T.px(7), T.px(18)))
        T.tooltip(url_entry.entry,
                  "Paste a YouTube or Twitch link.\n"
                  "A ?t= timestamp is detected automatically and\n"
                  "becomes the in point.")

        times = tk.Frame(b, bg=T.CARD)
        times.pack(fill="x")
        times.columnconfigure(0, weight=1)
        times.columnconfigure(1, weight=1)

        incol = tk.Frame(times, bg=T.CARD)
        incol.grid(row=0, column=0, sticky="ew", padx=(0, T.px(9)))
        T.field_label(incol, "In point").pack(anchor="w")
        self.in_var = tk.StringVar(value="00:00")
        self._last_in_value = self.in_var.get()
        in_entry = T.entry(incol, self.in_var, width=8)
        in_entry.pack(fill="x", pady=(T.px(7), 0))
        # Typing an in point and clicking away applies the default clip length.
        in_entry.entry.bind("<FocusOut>", self._on_in_point_committed, add="+")
        in_entry.entry.bind("<Return>", self._on_in_point_committed, add="+")
        T.tooltip(in_entry.entry,
                  f"{WHOLE_VIDEO_HINT}\n\n"
                  "Otherwise the end point follows automatically,\n"
                  "using the default clip length from Settings.")

        outcol = tk.Frame(times, bg=T.CARD)
        outcol.grid(row=0, column=1, sticky="ew", padx=(T.px(9), 0))
        T.field_label(outcol, "End point").pack(anchor="w")
        # End point starts at the configured default length past 00:00.
        self.out_var = tk.StringVar(value=seconds_to_timestamp(self.default_length))
        out_entry = T.entry(outcol, self.out_var, width=8)
        out_entry.pack(fill="x", pady=(T.px(7), 0))
        T.tooltip(out_entry.entry, WHOLE_VIDEO_HINT)

        # Quick durations: set the end point to in-point + N.
        T.field_label(b, "Clip length from in point").pack(anchor="w", pady=(T.px(16), 0))
        durations = tk.Frame(b, bg=T.CARD)
        durations.pack(fill="x", pady=(T.px(7), 0))
        for label, seconds in QUICK_DURATIONS:
            T.ghost_button(durations, label,
                           lambda s=seconds: self.set_length(s),
                           height=38, font=(T.FONT, 10)).pack(
                               side="left", fill="x", expand=True, padx=(0, T.px(8)))
        entire = T.ghost_button(durations, "Entire", self.set_entire,
                                height=38, font=(T.FONT, 10))
        entire.pack(side="left", fill="x", expand=True, padx=(0, T.px(8)))
        T.tooltip(entire, "Reset both points to 00:00 — downloads the whole video.")
        more = T.ghost_button(durations, "▾", None, height=38, width=44,
                              font=(T.FONT, 11))
        # Assigned after construction so the callback can reference the button
        # itself for positioning the popup.
        more._cmd = lambda btn=more: self.show_more_lengths(btn)
        more.pack(side="left")

        T.ghost_button(b, "Copy in point from link", self.copy_in_point_from_link,
                       height=38, font=(T.FONT, 10)).pack(fill="x", pady=(T.px(16), 0))

        tk.Label(b, text="mm:ss  ·  hh:mm:ss  ·  or plain seconds",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", pady=(T.px(12), 0))

        # 2. Quality -------------------------------------------------------- #
        card2 = T.Card(root)
        card2.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        b2 = card2.body
        T.step_header(b2, 2, "Max quality").pack(anchor="w", pady=(0, T.px(18)))
        self.quality_var = tk.StringVar(value="Best available")
        ttk.Combobox(b2, textvariable=self.quality_var, style="Y.TCombobox",
                     values=list(QUALITY_OPTIONS.keys()), state="readonly",
                     font=(T.FONT, 12)).pack(fill="x")

        # 3. Insert at ------------------------------------------------------ #
        card3 = T.Card(root)
        card3.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        b3 = card3.body
        T.step_header(b3, 3, "Insert clip by").pack(anchor="w", pady=(0, T.px(18)))
        self.insert_var = tk.StringVar(value="playhead")
        T.Segmented(b3, [("playhead", "Playhead"),
                         ("start", "Start of timeline")], self.insert_var).pack(fill="x")


        # Actions ----------------------------------------------------------- #
        actions = tk.Frame(root, bg=T.BG)
        actions.pack(fill="x", padx=T.px(26), pady=(T.px(10), T.px(20)))
        # Full-width primary action with a drop-into-timeline arrow.
        self.yeet_btn = T.RoundButton(actions, YEET_LABEL, self.on_yeet, height=64,
                                      radius=14, font=(T.FONT, 15, "bold"),
                                      icon="drop")
        self.yeet_btn.pack(fill="x", expand=True)
        self.yeet_btn.set_enabled(False)

        # Same pipeline, minus the Resolve insert — useful when Resolve isn't
        # running, or when you just want the file.
        self.dl_btn = T.ghost_button(actions, "Download only",
                                     self.on_download_only, height=46,
                                     font=(T.FONT, 12))
        self.dl_btn.pack(fill="x", pady=(T.px(10), 0))
        self.dl_btn.set_enabled(False)

        secondary = tk.Frame(root, bg=T.BG)
        secondary.pack(fill="x", padx=T.px(26), pady=(0, T.px(24)))
        buttons = (("Open folder", self.open_downloads, "folder"),
                   ("Show log", self.toggle_log, "list"),
                   ("Settings", self.open_settings, "gear"))
        for i, (label, command, icon) in enumerate(buttons):
            btn = T.ghost_button(secondary, label, command, height=44,
                                 font=(T.FONT, 11), icon=icon)
            # Gap between buttons only — the last one keeps flush with the
            # card edges above it.
            gap = (0, T.px(16)) if i < len(buttons) - 1 else (0, 0)
            btn.pack(side="left", fill="x", expand=True, padx=gap)
            if label == "Show log":
                self.log_btn = btn

        # Progress ----------------------------------------------------------- #
        prog = tk.Frame(root, bg=T.BG)
        prog.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        self.step_var = tk.StringVar(value="Idle")
        tk.Label(prog, textvariable=self.step_var, bg=T.BG, fg=T.MUTED,
                 font=(T.FONT, 11), anchor="w").pack(fill="x", pady=(0, T.px(9)))
        self.progress = T.ProgressBar(prog)
        self.progress.pack(fill="x")

        # Log --------------------------------------------------------------- #
        # Docked to the right of the controls, in a fixed-width holder so it can't
        # steal space from them. Built but not packed: it starts collapsed and the
        # window widens when it's revealed.
        self.log_wrap = tk.Frame(self._shell, bg=T.BG, width=T.px(LOG_PANEL_W))
        self.log_wrap.pack_propagate(False)
        self._log_pack = dict(side="right", fill="both")
        self.log_visible = False

        self.logcard = T.Card(self.log_wrap, fill=T.LOG_BG, pad=16)
        self.logcard.pack(fill="both", expand=True,
                          padx=(0, T.px(26)), pady=(T.px(22), T.px(26)))
        lb = self.logcard.body
        head = tk.Frame(lb, bg=T.LOG_BG)
        head.pack(fill="x", pady=(0, T.px(6)))
        tk.Label(head, text="LOG", bg=T.LOG_BG, fg=T.MUTED,
                 font=(T.FONT, 9, "bold")).pack(side="left")
        tk.Label(head, text="clear", bg=T.LOG_BG, fg=T.MUTED, font=(T.FONT, 9),
                 cursor="hand2").pack(side="right")
        head.winfo_children()[-1].bind("<Button-1>", lambda _e: self.clear_log())

        body = tk.Frame(lb, bg=T.LOG_BG)
        body.pack(fill="both", expand=True)
        # height=6 is only the floor — fill/expand grows it into all spare space,
        # so the window can still be shrunk on a short screen without clipping.
        self.log_text = tk.Text(body, height=6, width=1, wrap="word", state="disabled",
                                bg=T.LOG_BG, fg=T.MUTED, relief="flat", bd=0,
                                highlightthickness=0, font=(T.MONO, 10),
                                insertbackground=T.ACCENT, spacing1=1)
        scroll = ttk.Scrollbar(body, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.log_text.tag_configure("accent", foreground=T.ACCENT)
        self.log_text.tag_configure("bad", foreground=T.DANGER)
        # Genuine highlight — accent background, dark text — so it can't be
        # skimmed past in a wall of yt-dlp output.
        self.log_text.tag_configure("highlight", foreground=T.ACCENT_TEXT,
                                    background=T.ACCENT, font=(T.MONO, 10, "bold"),
                                    spacing1=4, spacing3=4)

    # ---- logging ---------------------------------------------------------- #

    def log(self, msg: str, tag: str | None = None) -> None:
        """`tag` forces a log style; without it the style is guessed from the text."""
        self.log_queue.put((f"[{datetime.now():%H:%M:%S}] {msg}", tag))

    def toggle_log(self) -> None:
        """Show/hide the log panel beside the controls.

        The window widens rather than growing taller: the control column is already
        tall, so extra height risked running off the screen, while width is the
        dimension there's room in — and a tall narrow log reads better anyway.
        """
        root = self.root
        root.update_idletasks()
        width, height = root.winfo_width(), root.winfo_height()
        panel = T.px(LOG_PANEL_W)

        if self.log_visible:
            self.log_wrap.pack_forget()
            self.log_visible = False
            self.log_btn.set_text("Show log")
            root.update_idletasks()
            new_width = max(root.winfo_reqwidth(), width - panel)
        else:
            self.log_wrap.pack(**self._log_pack)
            self.log_visible = True
            self.log_btn.set_text("Hide log")
            root.update_idletasks()
            new_width = max(width + panel, root.winfo_reqwidth())
            self.log_text.see("end")

        # Keep the floor in step with what's on screen, so collapsing can genuinely
        # shrink the window and expanding can't clip.
        root.minsize(max(T.px(470), root.winfo_reqwidth()), root.winfo_reqheight())
        root.geometry(f"{self._fit_width(new_width)}x{self._fit_height(height)}")

    def reveal_log(self) -> None:
        """Bring the log into view (used when something goes wrong)."""
        if not self.log_visible:
            self.root.after(0, self.toggle_log)

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line, tag = self.log_queue.get_nowait()
                if tag is None:
                    low = line.lower()
                    tag = "bad" if ("error" in low or "warning" in low or "resolve:" in low) else \
                          "accent" if ("ready" in low or "done" in low or "inserted" in low) else ""
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line + "\n", tag)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    # ---- progress (safe to call from worker threads) ----------------------- #

    def _progress(self, fraction: float | None = None, step: str | None = None) -> None:
        def apply() -> None:
            if fraction is not None:
                self.progress.set(fraction)
            if step is not None:
                self.step_var.set(step)
        self.root.after(0, apply)

    # ---- connection status ------------------------------------------------- #

    def refresh_connection(self) -> None:
        threading.Thread(target=self._check_connection, daemon=True).start()

    def _check_connection(self, quiet: bool = False) -> bool:
        """Report what we can actually see: Resolve, the project, the timeline."""
        try:
            info = resolve_bridge.get_timeline_info()
        except resolve_bridge.ResolveError as e:
            msg = str(e)
            # Distinguish "Resolve isn't there" from "Resolve is there but has
            # nothing open" — they need different fixes.
            if "timeline" in msg.lower():
                self._set_status("no timeline open", T.DANGER)
            elif "project" in msg.lower():
                self._set_status("no project open", T.DANGER)
            else:
                self._set_status("Resolve not connected", T.DANGER)
            if not quiet:
                self.log(f"RESOLVE: {msg}")
            return False
        except Exception as e:  # noqa: BLE001
            self._set_status("Resolve error", T.DANGER)
            if not quiet:
                self.log(f"RESOLVE: unexpected problem — {e}")
            return False

        self._set_status(f"{info['project']} · {info['timeline']}", T.ACCENT)
        if not quiet:
            self.log(f"Resolve ready: '{info['timeline']}' @ {info['fps']}fps, "
                     f"playhead {info['currentTimecode']}")
        return True

    def _set_status(self, text: str, colour: str) -> None:
        self.root.after(0, lambda: self.status.set(text, colour))


    # ---- yt-dlp update ----------------------------------------------------- #

    def _ytdlp_info_text(self) -> str:
        where = " ".join(self.ytdlp_cmd) if self.ytdlp_cmd else "not found"
        return f"{self.ytdlp_version or '?'}  —  {where}"

    def _enable_update_btn(self, enabled: bool) -> None:
        """Safe even if the Settings window has since been closed."""
        def apply() -> None:
            btn = self.update_btn
            if btn is not None and btn.winfo_exists():
                btn.set_enabled(enabled)
        self.root.after(0, apply)

    def on_update_ytdlp(self) -> None:
        if self.busy or not self.ytdlp_cmd:
            return
        threading.Thread(target=self._update_ytdlp, daemon=True).start()

    # ---- ffmpeg install (macOS) -------------------------------------------- #

    def _enable_ffmpeg_btn(self, enabled: bool) -> None:
        """Safe even if the Settings window has since been closed."""
        def apply() -> None:
            btn = self.ffmpeg_btn
            if btn is not None and btn.winfo_exists():
                btn.set_enabled(enabled)
        self.root.after(0, apply)

    def on_install_ffmpeg(self) -> None:
        if self.busy:
            return
        threading.Thread(target=self._install_ffmpeg, daemon=True).start()

    def _install_ffmpeg(self) -> None:
        """Hand off to Homebrew, then adopt the result without a restart."""
        self._enable_ffmpeg_btn(False)
        self.reveal_log()   # brew is chatty and slow; the user should see it working
        try:
            self.ffmpeg_path = deps.install_ffmpeg_via_brew(self.log)
            self.root.after(0, lambda: self.ffmpeg_info_var.set(self.ffmpeg_path or ""))
            self.log("ffmpeg is ready — no restart needed.")
            # The boot sequence gives up on a missing ffmpeg and leaves the
            # action buttons disabled; now that it's here, let them back in.
            if self.ytdlp_cmd:
                self.root.after(0, lambda: self._set_busy(False))
                self._check_connection()
        except Exception as e:  # noqa: BLE001 — message is written for the log
            self.log(f"ERROR: {e}")
            self._enable_ffmpeg_btn(True)

    # ---- JavaScript runtime ------------------------------------------------ #

    def _js_info_text(self) -> str:
        """Reads the cached version rather than probing: Settings builds this on
        the UI thread, and spawning deno there would stall the window opening."""
        if not self.deno_path:
            return "not found"
        return f"deno {self.deno_version or '?'}  —  {self.deno_path}"

    def _set_js_info(self, text: str) -> None:
        self.root.after(0, lambda: self.js_info_var.set(text))

    def _enable_js_btn(self, enabled: bool) -> None:
        """Safe even if the Settings window has since been closed."""
        def apply() -> None:
            btn = self.js_btn
            if btn is not None and btn.winfo_exists():
                btn.set_enabled(enabled)
        self.root.after(0, apply)

    def on_install_js(self) -> None:
        if self.busy:
            return
        threading.Thread(target=self._install_js, daemon=True).start()

    def _install_js(self) -> None:
        """Fetch Deno on demand, from Settings, and adopt it without a restart."""
        self._enable_js_btn(False)
        self.reveal_log()   # it's a ~40 MB download; show that something is happening
        if self._setup_js_runtime():
            self.log("JavaScript runtime ready — no restart needed.")
        else:
            self._enable_js_btn(True)

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
                                  text=True, timeout=60, **_spawn_kwargs())
            return proc.stdout or ""
        except Exception:  # noqa: BLE001 — treat unreadable help as "no flags"
            return ""

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
            self._set_js_info("unused — yt-dlp too old")
            return False

        try:
            self.deno_path = deps.ensure_deno(self.log)
        except Exception as e:  # noqa: BLE001 — message is written for the log
            self.log(f"WARNING: no JavaScript runtime — {e}")
            self.log("  YouTube may refuse some formats until one is available.")
            self.log("  Retry from Settings, or install Deno yourself: "
                     "https://deno.com")
            self._set_js_info("not found")
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
        self._set_js_info(self._js_info_text())
        return True

    def _update_ytdlp(self) -> None:
        self._enable_update_btn(False)
        try:
            cmd = list(self.ytdlp_cmd or [])
            # A standalone binary self-updates with -U; the pip module can't,
            # so upgrade the package instead.
            if len(cmd) == 1:
                args = cmd + ["-U"]
            else:
                args = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"]
            self.log("Updating yt-dlp: " + " ".join(args))
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                bufsize=1, **_spawn_kwargs())
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log(line)
            code = proc.wait()
            if code == 0:
                self.ytdlp_version = self._probe_version()
                self.log(f"yt-dlp is now {self.ytdlp_version or '?'}.")
                # Refresh the Settings readout if that window is still open.
                self.root.after(0, lambda: self.ytdlp_info_var.set(self._ytdlp_info_text()))
            else:
                self.log(f"Update failed (exit {code}).")
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR updating yt-dlp: {e}")
        finally:
            self._enable_update_btn(True)

    # ---- settings ---------------------------------------------------------- #

    def open_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title(f"{APP_NAME} Settings")
        win.configure(bg=T.BG)
        apply_icon(win)
        # Provisional; re-set from the packed content at the end of this method.
        win.geometry(f"{T.px(640)}x{self._fit_height(T.px(870))}")
        win.minsize(T.px(470), T.px(700))
        win.transient(self.root)
        win.grab_set()
        # After transient()/grab_set(), not before: Tk recreates the window frame
        # when the transient relationship is set, which discards the DWM attribute
        # and left this title bar white while the main window's was dark.
        T.apply_titlebar_theme(win)
        win.bind("<FocusIn>", lambda _e: T.apply_titlebar_theme(win), add="+")

        # Save/Cancel and the credit are packed first, against the bottom edge, so
        # the settings above them can never push them off it. On a 1080p display
        # at 150% scale the cards alone are taller than the usable screen height,
        # and a plain top-to-bottom pack put the two buttons the window exists for
        # out of reach. Everything above them scrolls instead.
        footer = tk.Frame(win, bg=T.BG)
        footer.pack(side="bottom", fill="x")
        # side="bottom" for both, and buttons first, so the credit line ends up
        # above the buttons rather than below them.
        buttons = tk.Frame(footer, bg=T.BG)
        buttons.pack(side="bottom", fill="x", padx=T.px(26), pady=(10, 22))
        about = tk.Frame(footer, bg=T.BG)

        scroll_host = tk.Frame(win, bg=T.BG)
        scroll_host.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=T.BG, highlightthickness=0, bd=0)
        vbar = tk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=T.BG)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync_scroll(_e: tk.Event | None = None) -> None:
            """Keep the scrollregion current, and show the bar only when needed."""
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(body_id, width=canvas.winfo_width())
            overflows = body.winfo_reqheight() > canvas.winfo_height()
            if overflows and not vbar.winfo_ismapped():
                vbar.pack(side="right", fill="y")
            elif not overflows and vbar.winfo_ismapped():
                vbar.pack_forget()

        body.bind("<Configure>", _sync_scroll)
        canvas.bind("<Configure>", _sync_scroll)

        def _on_wheel(e: tk.Event) -> None:
            if body.winfo_reqheight() <= canvas.winfo_height():
                return              # nothing to scroll; don't swallow the event
            # Windows/macOS report delta; X11 sends Button-4/5 instead.
            step = -1 if getattr(e, "num", None) == 4 else 1 if getattr(e, "num", None) == 5 \
                else (-1 if e.delta > 0 else 1)
            canvas.yview_scroll(step, "units")

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            win.bind_all(sequence, _on_wheel, add="+")

        tk.Label(body, text="Settings", bg=T.BG, fg=T.TEXT,
                 font=(T.FONT, 17, "bold")).pack(anchor="w", padx=T.px(26), pady=(T.px(22), T.px(16)))

        card = T.Card(body)
        card.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        b = card.body
        T.step_header(b, 1, "Clip storage").pack(anchor="w", pady=(0, T.px(16)))
        T.field_label(b, "Downloaded clips are saved here").pack(anchor="w")

        dir_var = tk.StringVar(value=self.download_dir)
        row = tk.Frame(b, bg=T.CARD)
        row.pack(fill="x", pady=(T.px(4), 0))
        T.entry(row, dir_var, width=1).pack(side="left", fill="x", expand=True)

        def browse() -> None:
            chosen = filedialog.askdirectory(
                parent=win, title="Choose where clips are saved",
                initialdir=dir_var.get() or os.path.expanduser("~"))
            if chosen:
                dir_var.set(os.path.normpath(chosen))

        def reset_dir() -> None:
            dir_var.set(config.default_download_dir())

        T.ghost_button(row, "Browse…", browse, height=48, width=104).pack(
            side="left", padx=(T.px(9), 0))
        reset_btn = T.ghost_button(row, "Reset", reset_dir, height=48, width=88)
        reset_btn.pack(side="left", padx=(T.px(7), 0))
        T.tooltip(reset_btn,
                  f"Back to the default:\n{config.default_download_dir()}")

        tk.Label(b, text="Existing clips are left where they are.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", pady=(T.px(10), 0))

        # Defaults ---------------------------------------------------------- #
        defaults_card = T.Card(body)
        defaults_card.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        db = defaults_card.body
        T.step_header(db, 2, "Default clip length").pack(anchor="w", pady=(0, T.px(16)))
        T.field_label(db, "End point set from the in point when the app opens").pack(
            anchor="w")

        # Snap the shown selection to a preset so a hand-edited value still
        # highlights something sensible; it's only overwritten if Save is pressed.
        current = min(config.LENGTH_CHOICES,
                      key=lambda s: abs(s - self.default_length))
        length_var = tk.StringVar(value=str(current))
        T.Segmented(db, [(str(s), f"{s}s") for s in config.LENGTH_CHOICES],
                    length_var).pack(fill="x", pady=(T.px(9), 0))

        # Whole-video codec ---------------------------------------------------- #
        codec_card = T.Card(body)
        codec_card.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        cb = codec_card.body
        T.step_header(cb, 3, "Whole videos above 1080p").pack(
            anchor="w", pady=(0, T.px(16)))
        T.field_label(
            cb, "YouTube only has H.264 up to 1080p — above that it's VP9/AV1, "
                "which Resolve can't play").pack(anchor="w")
        reencode_var = tk.StringVar(value="1" if self.reencode_h264 else "0")
        T.Segmented(cb, [("1", "Keep quality"), ("0", "Keep it quick")],
                    reencode_var).pack(fill="x", pady=(T.px(9), T.px(9)))
        hint = tk.Label(cb, bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9),
                        justify="left", anchor="w", wraplength=T.px(520))
        hint.pack(fill="x")

        def _codec_hint(*_a) -> None:
            hint.configure(text=(
                "Full resolution, converted to H.264 afterwards. Adds roughly "
                "60% of the video's length to the job — a 10-minute video takes "
                "about 6 extra minutes. STOP still works."
                if reencode_var.get() == "1" else
                "No waiting, but whole videos are capped at 1080p, because that "
                "is the highest resolution YouTube offers in H.264. Clips with an "
                "in/out point are unaffected and stay full resolution."))
        _codec_hint()
        reencode_var.trace_add("write", _codec_hint)

        info = T.Card(body)
        info.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        ib = info.body
        T.step_header(ib, 4, "Tools").pack(anchor="w", pady=(0, 14))
        # Live vars so an update performed from this window refreshes in place.
        self.ytdlp_info_var.set(self._ytdlp_info_text())
        self.ffmpeg_info_var.set(self.ffmpeg_path or "not found")
        # Only when there's a runtime to describe: otherwise the var already
        # holds the reason from startup ("not found" / "yt-dlp too old"), which
        # is more use than recomputing "not found" here.
        if self.deno_path:
            self.js_info_var.set(self._js_info_text())
        for label, var in (("yt-dlp", self.ytdlp_info_var),
                           ("ffmpeg", self.ffmpeg_info_var),
                           ("JS", self.js_info_var)):
            line = tk.Frame(ib, bg=T.CARD)
            line.pack(fill="x", pady=2)
            tk.Label(line, text=f"{label}:", bg=T.CARD, fg=T.MUTED,
                     font=(T.FONT, 10), width=8, anchor="w").pack(side="left")
            tk.Label(line, textvariable=var, bg=T.CARD, fg=T.TEXT, font=(T.MONO, 9),
                     anchor="w").pack(side="left", fill="x", expand=True)

        # Where we found Resolve — the first thing worth checking on a new setup.
        env = resolve_bridge.describe_env()
        resolve_line = ("Python %s %s · library %s" % (
            env["python"],
            "OK" if env["python_ok"] else "UNSUPPORTED",
            "found" if env["lib_exists"] else "MISSING"))
        line = tk.Frame(ib, bg=T.CARD)
        line.pack(fill="x", pady=2)
        tk.Label(line, text="Resolve:", bg=T.CARD, fg=T.MUTED,
                 font=(T.FONT, 10), width=8, anchor="w").pack(side="left")
        tk.Label(line, text=resolve_line, bg=T.CARD,
                 fg=T.TEXT if env["lib_exists"] and env["python_ok"] else T.DANGER,
                 font=(T.MONO, 9), anchor="w").pack(side="left", fill="x", expand=True)

        self.update_btn = T.ghost_button(ib, "Update yt-dlp", self.on_update_ytdlp,
                                         height=40, font=(T.FONT, 10))
        self.update_btn.pack(fill="x", pady=(T.px(14), 0))
        if self.busy:
            self.update_btn.set_enabled(False)

        # Only while it's actually missing: startup fetches the runtime by
        # itself, so this button is for the run where that failed — no network
        # on a first launch, say — rather than a normal step.
        self.js_btn = None
        if not self.deno_path:
            self.js_btn = T.ghost_button(
                ib, "Install JavaScript runtime (Deno)", self.on_install_js,
                height=40, font=(T.FONT, 10))
            self.js_btn.pack(fill="x", pady=(T.px(8), 0))
            if self.busy:
                self.js_btn.set_enabled(False)

        # macOS only, and only while it's actually missing: ffmpeg is installed
        # by Homebrew rather than downloaded (see deps.py), so this is the one
        # dependency the app can't just resolve on its own. Offering the command
        # as a button beats making the user find a terminal — but it runs only
        # on this explicit click, never as part of startup.
        self.ffmpeg_btn = None
        if deps.MACOS_FFMPEG_MANUAL and not self.ffmpeg_path:
            self.ffmpeg_btn = T.ghost_button(
                ib, "Install ffmpeg (Homebrew)", self.on_install_ffmpeg,
                height=40, font=(T.FONT, 10))
            self.ffmpeg_btn.pack(fill="x", pady=(T.px(8), 0))
            if self.busy:
                self.ffmpeg_btn.set_enabled(False)

        # The buttons live in a throwaway window; don't leave dead widget
        # references behind for the worker threads to poke at.
        def _forget(e: tk.Event) -> None:
            if e.widget is win:
                self.update_btn = None
                self.ffmpeg_btn = None
                self.js_btn = None
                # bind_all is application-wide, so these outlive the window they
                # were made for and would scroll a destroyed canvas on the next
                # wheel event anywhere in the app.
                for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    try:
                        win.unbind_all(sequence)
                    except tk.TclError:
                        pass
        win.bind("<Destroy>", _forget)

        # About / credit ---------------------------------------------------- #
        about.pack(side="bottom", fill="x", padx=T.px(26), pady=(T.px(2), 0))
        tk.Label(about, text=f"{APP_NAME} v{__version__}", bg=T.BG, fg=T.MUTED,
                 font=(T.FONT, 9)).pack(side="left")
        credit = tk.Label(about, text=COPYRIGHT, bg=T.BG, fg=T.MUTED,
                          font=(T.FONT, 9), cursor="hand2")
        credit.pack(side="right")
        credit.bind("<Button-1>", lambda _e: self.open_author_page())
        credit.bind("<Enter>", lambda _e: credit.configure(fg=T.ACCENT))
        credit.bind("<Leave>", lambda _e: credit.configure(fg=T.MUTED))
        T.tooltip(credit, AUTHOR_URL)

        def save() -> None:
            new_dir = dir_var.get().strip()
            if not new_dir:
                self.log("ERROR: clip folder can't be empty.")
                return
            new_dir = os.path.normpath(new_dir)
            try:
                os.makedirs(new_dir, exist_ok=True)
            except OSError as e:
                self.log(f"ERROR: can't use that folder — {e}")
                return
            self.settings["download_dir"] = new_dir
            self.download_dir = new_dir

            try:
                length = int(length_var.get())
            except ValueError:
                length = config.DEFAULTS["default_length"]
            self.settings["default_length"] = length
            self.default_length = length

            reencode = reencode_var.get() == "1"
            self.settings["reencode_h264"] = reencode
            self.reencode_h264 = reencode

            try:
                path = config.save(self.settings)
                self.log(f"Clips → {new_dir}")
                self.log(f"Default clip length → {seconds_to_timestamp(length)} "
                         "(applied when the app opens)")
                self.log("Whole videos above 1080p → " + (
                    "full resolution, converted to H.264" if reencode else
                    "capped at 1080p H.264, no conversion"))
                self.log(f"Settings saved to {path}")
            except OSError as e:
                self.log(f"ERROR saving settings: {e}")
            win.destroy()

        T.RoundButton(buttons, "Save", save, height=48, font=(T.FONT, 12, "bold")).pack(
            side="left", fill="x", expand=True)
        T.ghost_button(buttons, "Cancel", win.destroy, height=48, width=120).pack(
            side="left", padx=(T.px(10), 0))

        # Height from the content rather than a constant, since the cards grow and
        # shrink with what's installed and what's selected. Measured as body +
        # footer: the canvas in between has no natural height of its own, so
        # win.winfo_reqheight() would report far too little. _fit_height then
        # clamps to the screen, and anything that doesn't fit scrolls.
        win.update_idletasks()
        width = T.px(640)
        height = self._fit_height(body.winfo_reqheight() + footer.winfo_reqheight())
        # Placed explicitly rather than left to Tk. A tall settings window opens
        # near the main one and then extends past the bottom of the display, which
        # puts Save and Cancel off screen just as surely as clipping them did.
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 3)
        x = max(0, min(x, self.root.winfo_screenwidth() - width))
        y = max(0, min(y, int(self.root.winfo_screenheight() * 0.96) - height))
        win.geometry(f"{width}x{height}+{x}+{y}")
        _sync_scroll()
        canvas.yview_moveto(0)   # open at the top, not wherever the last resize left it

    # ---- startup ---------------------------------------------------------- #

    def _boot(self) -> None:
        """Resolve dependencies and check Resolve, off the UI thread."""
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
            self._set_status("missing tools", T.DANGER)
            return

        try:
            self.ffmpeg_path = deps.ensure_ffmpeg(self.log)
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR: {e}")
            self._set_status("ffmpeg missing", T.DANGER)
            self.reveal_log()
            if deps.MACOS_FFMPEG_MANUAL:
                self.log("Open Settings to install it, or run the command above.")
            return

        self.ytdlp_version = self._probe_version()
        # After yt-dlp, because it asks yt-dlp which flags it understands, and
        # non-fatal by design — see _setup_js_runtime.
        self._setup_js_runtime()
        runtime = f" · deno {self.deno_version or '?'}" if self.deno_path else ""
        self.log(f"yt-dlp {self.ytdlp_version or '?'} ready · "
                 f"ffmpeg {os.path.basename(self.ffmpeg_path or '?')}{runtime}")
        self.root.after(0, lambda: self.ytdlp_info_var.set(self._ytdlp_info_text()))

        self._check_connection()
        # Both action buttons start disabled until the tools are resolved; go
        # through _set_busy(False) so neither is forgotten.
        self.root.after(0, lambda: self._set_busy(False))

    def _probe_version(self) -> str | None:
        try:
            proc = subprocess.run([*(self.ytdlp_cmd or []), "--version"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=30, **_spawn_kwargs())
            return (proc.stdout or "").strip().splitlines()[-1] if proc.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    # ---- actions ---------------------------------------------------------- #

    def open_author_page(self) -> None:
        """Open the author's page in the default browser (from the Settings credit)."""
        try:
            import webbrowser
            webbrowser.open(AUTHOR_URL)
            self.log(f"Opened {AUTHOR_URL}")
        except Exception as e:  # noqa: BLE001
            self.log(f"Couldn't open {AUTHOR_URL}: {e}")

    def open_downloads(self) -> None:
        os.makedirs(self.download_dir, exist_ok=True)
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(self.download_dir)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.download_dir])
            else:
                subprocess.Popen(["xdg-open", self.download_dir])
            self.log(f"Opened {self.download_dir}")
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR opening folder: {e}")

    def set_length(self, seconds: int) -> None:
        """Set the end point to the in point plus `seconds`."""
        start = normalize_timestamp(self.in_var.get())
        if start is None:
            self.log("ERROR: in point must be SS, MM:SS or HH:MM:SS "
                     "before a length can be applied.")
            return
        end = seconds_to_timestamp(to_seconds(start) + seconds)
        self.out_var.set(end)
        self.log(f"Length {seconds_to_timestamp(seconds)} → end point {end}.")

    def set_entire(self) -> None:
        """Zero both points, which means "no section" — the whole video."""
        self._set_in_point("00:00")
        self.out_var.set("00:00")
        self.log("Both points cleared — the entire video will be downloaded.")

    def show_more_lengths(self, button) -> None:
        """Dropdown for the longer presets that don't warrant their own button."""
        menu = tk.Menu(self.root, tearoff=0,
                       bg=T.INPUT, fg=T.TEXT,
                       activebackground=T.ACCENT, activeforeground=T.ACCENT_TEXT,
                       bd=0, relief="flat", activeborderwidth=0,
                       font=(T.FONT, 10))
        for label, seconds in MORE_DURATIONS:
            menu.add_command(label=f"  {label}  ",
                             command=lambda s=seconds: self.set_length(s))
        try:
            # Drop it below the arrow rather than at the cursor.
            menu.tk_popup(button.winfo_rootx(),
                          button.winfo_rooty() + button.winfo_height())
        finally:
            menu.grab_release()

    def _set_in_point(self, stamp: str) -> None:
        """Set the in point programmatically, without arming the focus-out recalc."""
        self.in_var.set(stamp)
        self._last_in_value = stamp

    def _on_in_point_committed(self, _event=None) -> None:
        """After the in point is typed and committed, apply the default length.

        Only when the value actually changed — otherwise merely clicking through
        the field would wipe an end point the user had set deliberately.
        """
        raw = self.in_var.get()
        if raw == self._last_in_value:
            return
        start = normalize_timestamp(raw)
        if start is None:
            return                       # invalid; YEET will report it on submit
        self._last_in_value = raw

        end_now = normalize_timestamp(self.out_var.get())
        if to_seconds(start) == 0 and end_now is not None and to_seconds(end_now) == 0:
            return                       # both zero: whole-video mode, leave it

        new_end = seconds_to_timestamp(to_seconds(start) + self.default_length)
        self.out_var.set(new_end)
        self.log(f"End point set to {new_end} "
                 f"(+{self.default_length}s from the in point).")

    def _apply_link_timestamp(self, seconds: int, auto: bool) -> None:
        """Put a link's timestamp into the in point, keeping the range valid."""
        stamp = seconds_to_timestamp(seconds)
        self._set_in_point(stamp)
        if auto:
            self.log(f"Timestamp detected in the link — in point {stamp} "
                     f"(t={seconds}s).")
        else:
            self.log(f"In point set to {stamp} (from the link's t={seconds}s).")

        # An in point past the end point would just fail validation later, so
        # nudge the end out rather than leaving the fields contradictory. Uses the
        # configured default length so the result matches what the user expects a
        # fresh clip to be.
        end = normalize_timestamp(self.out_var.get())
        if end is None or to_seconds(end) <= seconds:
            new_end = seconds_to_timestamp(seconds + self.default_length)
            self.out_var.set(new_end)
            self.log(f"End point moved to {new_end} "
                     f"(+{self.default_length}s) to keep the range valid.")

    def _on_url_changed(self, *_args) -> None:
        """Auto-apply a pasted link's ?t= timestamp.

        Fires on every edit of the field, so it remembers which URL it already
        handled — otherwise typing or re-focusing would keep resetting an in point
        the user had since adjusted by hand.
        """
        url = self.url_var.get().strip()
        if not url:
            self._auto_ts_url = None      # cleared field: allow re-detection
            return
        if url == self._auto_ts_url:
            return

        seconds = naming.start_seconds_from_url(url)
        if seconds is None:
            return
        self._auto_ts_url = url
        self._apply_link_timestamp(seconds, auto=True)

    def copy_in_point_from_link(self) -> None:
        """Pull the ?t= timestamp out of a share link into the In point field."""
        url = self.url_var.get().strip()
        if not url:
            self.log("Paste a video link first.")
            return

        seconds = naming.start_seconds_from_url(url)
        if seconds is None:
            self.log("That link has no timestamp — share it with "
                     "'Start at' ticked to get a ?t= value.")
            return

        self._auto_ts_url = url
        self._apply_link_timestamp(seconds, auto=False)

    def _collect_job(self) -> tuple[str, str | None, str | None] | None:
        """Validate the form. Returns (url, start, end) or None after logging why.

        start/end come back as None for "whole video", which is what both points
        sitting at zero means.
        """
        if not self.ytdlp_cmd:
            self.log("ERROR: yt-dlp isn't available yet.")
            return None

        url = self.url_var.get().strip()
        if not url:
            self.log("ERROR: no video link.")
            return None

        start = normalize_timestamp(self.in_var.get())
        end = normalize_timestamp(self.out_var.get())
        if start is None or end is None:
            self.log("ERROR: in/end point must be SS, MM:SS or HH:MM:SS.")
            return None

        if to_seconds(start) == 0 and to_seconds(end) == 0:
            return url, None, None          # no section -> entire video

        if to_seconds(end) <= to_seconds(start):
            self.log("ERROR: end point must be after in point "
                     "(or set both to 00:00 for the whole video).")
            return None
        return url, start, end

    def _start_job(self, insert: bool) -> None:
        job = self._collect_job()
        if job is None:
            return
        url, start, end = job
        self.cancel_event.clear()
        self._set_busy(True)
        threading.Thread(
            target=self._worker,
            args=(url, start, end, QUALITY_OPTIONS[self.quality_var.get()],
                  self.insert_var.get(), insert),
            daemon=True,
        ).start()

    def on_yeet(self) -> None:
        # The same button stops the job while one is running.
        if self.busy:
            self.on_stop()
            return
        self._start_job(insert=True)

    def on_download_only(self) -> None:
        """Download the clip and leave it on disk — no Resolve involvement."""
        if self.busy:
            return
        self._start_job(insert=False)

    def on_stop(self) -> None:
        if not self.busy or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.log("Stopping…")
        self._progress(step="Stopping…")
        self._kill_active()

    def _kill_active(self) -> None:
        """Kill the running tool and everything it spawned.

        yt-dlp spawns ffmpeg, so the whole tree has to go — killing only the
        parent leaves ffmpeg running, still holding and writing the output file,
        which then can't be cleaned up.

        Windows walks the tree at kill time with `taskkill /T`. POSIX signals the
        process group that _spawn_kwargs established, giving it a SIGTERM to
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

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            # Stays clickable — that click is how you stop it.
            self.yeet_btn.set_text("STOP")
            self.yeet_btn.set_style(fill=T.DANGER, fg=T.ACCENT_TEXT, icon=None)
        else:
            self.yeet_btn.set_text(YEET_LABEL)
            self.yeet_btn.set_style(fill=T.ACCENT, fg=T.ACCENT_TEXT, icon="drop")
        self.yeet_btn.set_enabled(True)
        # Only one job at a time; STOP lives on the primary button.
        self.dl_btn.set_enabled(not busy)

    def _probe_metadata(self, url: str) -> dict:
        """Look up id/title/channel before downloading, so the clip can be filed
        under a descriptive folder. Best effort — a failure just means a plainer
        folder name, not a failed download."""
        self.log("Reading video info…")
        cmd = [*(self.ytdlp_cmd or []), *self.js_args,
               "--dump-single-json", "--no-warnings",
               "--skip-download", "--no-playlist", url]
        try:
            # Popen (not run) so STOP can kill it mid-lookup.
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                **_spawn_kwargs(),
            )
            self.active_proc = proc
            out, err = proc.communicate(timeout=120)
            self.active_proc = None
            if self._cancelled():
                return {"id": "", "title": "", "channel": "", "heights": []}
            proc = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
            if proc.returncode == 0 and (proc.stdout or "").strip():
                data = json.loads(proc.stdout)
                return {
                    "id": data.get("id") or "",
                    "title": data.get("title") or "",
                    "channel": data.get("channel") or data.get("uploader") or "",
                    "heights": _video_heights(data),
                }
            tail = (proc.stderr or "").strip().splitlines()
            self.log("Couldn't read video info; falling back to the URL id.")
            if tail:
                self.log(f"  {tail[-1]}")
        except Exception as e:  # noqa: BLE001
            self.log(f"Video info lookup failed: {e}")
        return {"id": naming.video_id_from_url(url), "title": "", "channel": "",
                "heights": []}

    def _probe_stream(self, path: str) -> dict | None:
        """First video stream's properties via ffprobe, or None."""
        ffprobe = deps.find_ffprobe()
        if not ffprobe:
            return None
        cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=codec_name,width,height,r_frame_rate",
               "-of", "json", path]
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=30, **_spawn_kwargs())
            if proc.returncode != 0:
                return None
            streams = (json.loads(proc.stdout) or {}).get("streams") or []
            return streams[0] if streams else None
        except Exception:  # noqa: BLE001 — a missing detail isn't worth failing over
            return None

    @staticmethod
    def _describe_stream(s: dict | None) -> str | None:
        """Human-readable resolution/codec/fps.

        Describes what actually landed on disk rather than what was requested —
        after codec and resolution fallbacks those can differ.
        """
        if not s:
            return None
        w, h = s.get("width"), s.get("height")
        if not (w and h):
            return None

        codec = str(s.get("codec_name") or "?")
        label = f"{h}p ({w}x{h}, {codec}"
        # r_frame_rate is a rational like "30000/1001".
        rate = str(s.get("r_frame_rate") or "")
        if "/" in rate:
            num, den = rate.split("/", 1)
            try:
                fps = float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                fps = 0.0
            if fps > 0:
                label += f", {fps:.2f}".rstrip("0").rstrip(".") + " fps"
        return label + ")"

    @staticmethod
    def _existing_download(folder: str, stem: str) -> str | None:
        """A finished download for `stem`, or None.

        Skips yt-dlp's scratch files and zero-byte remnants, so an interrupted
        attempt is never mistaken for a complete one — that would insert a broken
        file instead of re-downloading.
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
            if _FRAGMENT_RE.search(name):
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

    @staticmethod
    def _scrubs_poorly(codec: str) -> bool:
        """Whether Resolve will struggle to decode `codec`.

        "Slowly" undersells it. Measured on a 4K60 VP9 file, software decode runs
        at about real time on an RTX 5070 Ti — and Resolve is doing that while
        also compositing, so playback drops frames and the clip eventually reads
        MEDIA OFFLINE. Generate Optimized Media doesn't rescue it either, because
        building the proxy means decoding the same file.

        YouTube only offers H.264 up to 1080p, so anything above that is
        necessarily one of these. H.264 hardware-decodes and is fine.
        """
        codec = (codec or "").lower()
        return codec.startswith(("vp0", "vp8", "vp9", "av0", "av1"))

    def _stream_duration(self, path: str) -> float | None:
        """Container duration in seconds, for driving the re-encode progress bar."""
        ffprobe = deps.find_ffprobe()
        if not ffprobe:
            return None
        try:
            proc = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=60, **_spawn_kwargs())
            return float((proc.stdout or "").strip())
        except Exception:  # noqa: BLE001 — no duration just means a vaguer bar
            return None

    def _to_h264(self, path: str) -> str | None:
        """Re-encode `path` to H.264 in place, returning the new path.

        Only ever called for a whole-video download that came back VP9 or AV1,
        which happens above 1080p because YouTube offers nothing else up there.
        Resolve has no usable decoder for either: playback drops frames, and the
        clip eventually goes MEDIA OFFLINE. Generate Optimized Media is no escape
        — it has to decode the file too, and fails for the same reason.

        Sections never need this; --force-keyframes-at-cuts already re-encodes
        them, which is why clips worked when full videos didn't.

        Audio is copied rather than re-encoded: FORMAT_SORT already pinned it to
        AAC, and a second lossy pass over it would be loss for nothing.

        Returns None on failure or cancellation, leaving the original untouched —
        a VP9 file that plays badly still beats no file at all.
        """
        ffmpeg = self.ffmpeg_path or deps.find_ffmpeg()
        if not ffmpeg:
            self.log("Can't re-encode: ffmpeg wasn't found. Keeping the original.")
            return None

        duration = self._stream_duration(path)
        stem, ext = os.path.splitext(path)
        # A distinct name, so an interrupted pass can never be mistaken for the
        # finished file: only a clean exit gets to replace the original.
        tmp = f"{stem}.h264-tmp{ext}"

        self.log("Converting to H.264 so Resolve can actually play it…")
        if duration:
            # 0.6x realtime, measured on 4K60 VP9. Rounded up and never phrased
            # as "0 min", which is what a short clip used to report.
            estimate = duration * 0.6
            rough = ("under a minute" if estimate < 60
                     else f"around {estimate / 60:.0f} min")
            self.log(f"  {seconds_to_timestamp(round(duration))} of video — expect "
                     f"{rough}. STOP still works.")

        cmd = [
            ffmpeg, "-y", "-nostdin",
            "-i", path,
            "-c:v", "libx264", "-preset", REENCODE_PRESET, "-crf", REENCODE_CRF,
            "-pix_fmt", "yuv420p",       # Resolve wants 8-bit 4:2:0
            "-movflags", "+faststart",   # index up front, so import is instant
            "-c:a", "copy",
            "-progress", "pipe:1", "-nostats", "-loglevel", "error",
            tmp,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                **_spawn_kwargs())
        self.active_proc = proc
        assert proc.stdout is not None
        errors: list[str] = []
        for line in proc.stdout:
            if self._cancelled():
                break
            line = line.rstrip()
            if not line:
                continue
            m = _FFMPEG_TIME_RE.match(line)
            if m and duration:
                done = int(m.group(1)) / 1_000_000 / duration
                self._progress(P_DOWNLOAD + (P_CONVERT - P_DOWNLOAD) * min(done, 1.0),
                               f"Converting to H.264… {min(done, 1.0) * 100:.0f}%")
            elif not line.startswith(("frame=", "fps=", "bitrate=", "total_size=",
                                      "out_time", "dup_frames=", "drop_frames=",
                                      "speed=", "progress=", "stream_")):
                errors.append(line)      # a real message, not progress bookkeeping
                self.log(f"  {line}")
        proc.wait()
        self.active_proc = None

        if self._cancelled() or proc.returncode != 0:
            if proc.returncode != 0 and not self._cancelled():
                self.log(f"Re-encode failed (exit {proc.returncode}); "
                         "keeping the original file.")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None

        try:
            os.replace(tmp, path)
        except OSError as e:
            self.log(f"Re-encoded fine but couldn't replace the original: {e}")
            return None
        self.log("  Converted. Re-running this video will reuse the H.264 copy.")
        return path

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

    def _worker(self, url, start, end, max_height, insert_at, insert=True) -> None:
        try:
            self._progress(P_INFO, "Reading video info…")
            meta = self._probe_metadata(url)
            if self._cancelled():
                self._stopped()
                return

            max_height = self._resolve_quality(max_height, meta)

            path = self._download(url, start, end, max_height, meta)
            if self._cancelled():
                self._stopped()
                return
            if not path:
                self._progress(0.0, "Failed — see log")
                self.reveal_log()
                return

            # Whole videos above 1080p arrive as VP9 or AV1, which Resolve can't
            # usefully decode. Done here rather than inside _download so the
            # reuse path gets it too: a file fetched by an older version, or by a
            # run with this setting off, is repaired the next time it's used.
            whole = start is None or end is None
            if whole and self.reencode_h264:
                codec = ((self._probe_stream(path) or {}).get("codec_name") or "")
                if self._scrubs_poorly(codec):
                    self.log(f"This is {codec}, which Resolve can't play properly.")
                    converted = self._to_h264(path)
                    if self._cancelled():
                        self._stopped()
                        return
                    path = converted or path

            if insert:
                # Past this point the file exists; the insert itself is quick and
                # atomic enough that we let it finish rather than half-cancel it.
                self._progress(P_INSERT, "Pasting into timeline…")
                self.log("Sending to Resolve…")
                res = resolve_bridge.import_and_insert(path, insert_at=insert_at)
                self.log(f"Inserted '{res['clipName']}' at frame "
                         f"{res['insertedFrame']}. Done.")
            else:
                res = {"clipName": os.path.basename(path)}
                self.log(f"Downloaded '{res['clipName']}' — not inserted. Done.")
                self.log(f"  Saved to: {path}")

            # Recap what we got — the filename is only an id, so the
            # human-readable title and channel are worth restating here.
            stream = self._probe_stream(path)
            self.log(f"  Video:   {meta.get('title') or 'unknown'}")
            self.log(f"  Channel: {meta.get('channel') or 'unknown'}")
            self.log(f"  Quality: {self._describe_stream(stream) or 'unknown'}")

            codec = str((stream or {}).get("codec_name") or "")
            if self._scrubs_poorly(codec):
                # Reached when the conversion was declined, failed, or the codec
                # came through on a section. Generate Optimized Media is NOT
                # suggested here: it has to decode the file too, so it fails on
                # exactly the clips that need it.
                self.log(f"  WARNING: {codec} — Resolve has no usable decoder for "
                         "this.")
                self.log("           Expect dropped frames, and the clip may go "
                         "MEDIA OFFLINE.")
                if whole and not self.reencode_h264:
                    self.log("           Switch 'Whole videos above 1080p' to "
                             "'Keep quality' in Settings")
                    self.log("           to convert it to H.264 automatically.")

            self.log("Make sure to credit the sources!", tag="highlight")
            self._progress(1.0, f"Done — {res['clipName']}")
            if insert:
                self._check_connection(quiet=True)
        except resolve_bridge.ResolveError as e:
            self.log(f"RESOLVE: {e}")
            self._progress(0.0, "Resolve error — see log")
            self.reveal_log()
            self._check_connection(quiet=True)
        except Exception as e:  # noqa: BLE001
            if self._cancelled():
                self._stopped()          # a kill surfaces as an exception too
            else:
                self.log(f"ERROR: {e}")
                self._progress(0.0, "Failed — see log")
                self.reveal_log()
        finally:
            self.active_proc = None
            self.root.after(0, lambda: self._set_busy(False))

    def _stopped(self) -> None:
        self.log("Stopped.")
        self._progress(0.0, "Stopped")

    def _cleanup_partial(self, folder: str, stem: str) -> None:
        """Remove the fragments of a cancelled download."""
        removed = 0
        try:
            for name in os.listdir(folder):
                if name.startswith(stem + "."):
                    try:
                        os.remove(os.path.join(folder, name))
                        removed += 1
                    except OSError:
                        pass  # locked by a dying ffmpeg; harmless leftover
        except OSError:
            return
        if removed:
            self.log(f"Cleaned up {removed} partial file(s).")

    def _download(self, url, start, end, max_height, meta: dict) -> str | None:
        os.makedirs(self.download_dir, exist_ok=True)
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
            if existing:
                self.log(f"Already downloaded — reusing {os.path.basename(existing)}")
                described = self._describe_stream(self._probe_stream(existing))
                if described:
                    self.log(f"  {described}")
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
            # With the re-encode off, a whole video must arrive as H.264 in the
            # first place, since nothing downstream will fix it — and that means
            # letting codec outrank resolution. Everywhere else, resolution wins
            # and H.264 is only the tiebreaker.
            "-S", (FORMAT_SORT_H264_FIRST if whole and not self.reencode_h264
                   else FORMAT_SORT),
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", os.path.join(job_dir, stem + ".%(ext)s"),
            "--newline",
        ]
        if not whole:
            # Section mode: fetch only the requested range, re-encoding around the
            # cut points so the trim is frame-accurate. Omitted entirely for a
            # whole-video pull, where there's nothing to cut.
            cmd += ["--download-sections", f"*{start}-{end}",
                    "--force-keyframes-at-cuts"]
        if self.ffmpeg_path:
            cmd += ["--ffmpeg-location", os.path.dirname(self.ffmpeg_path)]

        if whole:
            self.log(f"Fetching the entire video at {self.quality_var.get()}…")
        else:
            self.log(f"Fetching *{start}-{end} at {self.quality_var.get()}…")
        # yt-dlp spends a moment extracting and selecting formats before any frames
        # arrive, so say what we're actually doing instead of leaving the label
        # on "Reading video info...".
        self._progress(step="Preparing download…")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, **_spawn_kwargs())
        self.active_proc = proc
        assert proc.stdout is not None
        saw_403 = False
        saw_no_js = False
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

            # yt-dlp reports a percentage per stream; map it into the download
            # band so the bar tracks real progress instead of guessing.
            m = _PCT_RE.search(line)
            if m:
                phase = "download"
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
                # A 403 here is YouTube rejecting a specific format URL, not a
                # missing resolution — the usual cures are a newer yt-dlp or
                # letting it pick the format.
                self.log("HINT: 403 means YouTube refused that format's URL.")
                self.log("      Try 'Best available', or hit 'Update yt-dlp'.")
            return None

        # Same rules as the reuse check: the merged mp4 if it's there, otherwise
        # another container — never a scratch file and never a per-stream
        # fragment, which would be video-only or audio-only.
        produced = self._existing_download(job_dir, stem)
        if not produced:
            self.log("yt-dlp finished but produced no usable file.")
            self.log("  (only per-stream fragments were found — the merge step "
                     "may have failed)")
            return None
        return produced


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp text on high-DPI displays
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    YeetApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
