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
from version import APP_NAME, COPYRIGHT, __version__  # noqa: E402

# Progress is split into bands so the bar moves through the whole job, not just
# the download: info lookup, download, then the Resolve insert.
P_INFO, P_DOWNLOAD, P_INSERT = 0.06, 0.80, 0.97

_PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")

# Width of the log panel docked to the right; the window grows by this when the
# log is shown. Authored at 96 DPI like every other pixel value.
LOG_PANEL_W = 420

# yt-dlp's post-download stages. --force-keyframes-at-cuts re-encodes around the
# cut points, so this can take a while and deserves its own label rather than
# sitting at "Downloading... 100%".
_POST_MARKERS = ("[merger]", "[videoconvertor]", "[videoremuxer]", "[fixup",
                 "[extractaudio]", "[postprocess", "[splitchapters]")

# Clip-length shortcuts: end point = in point + N seconds. The first three get
# their own buttons; the rest live behind the dropdown arrow.
QUICK_DURATIONS = (("15s", 15), ("30s", 30), ("1m", 60))
MORE_DURATIONS = (("2 min", 120), ("5 min", 300), ("10 min", 600))

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
FORMAT_SORT = "res,vcodec:h264"


def icon_path() -> str | None:
    """The app icon, whether running frozen or from source."""
    name = f"{APP_NAME.lower()}.ico"
    if getattr(sys, "frozen", False):
        candidate = os.path.join(getattr(sys, "_MEIPASS", ""), "assets", name)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(os.path.dirname(here), "assets", name)
    return candidate if os.path.isfile(candidate) else None


def apply_icon(window: tk.Misc) -> None:
    """Set the window/taskbar icon. Silently skipped if the .ico is missing."""
    path = icon_path()
    if not path:
        return
    try:
        window.iconbitmap(path)          # type: ignore[attr-defined]
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
        # Cancellation: the event is checked between phases and inside the
        # download loop; active_proc lets us kill yt-dlp (and its ffmpeg child)
        # mid-flight rather than waiting for it to finish.
        self.cancel_event = threading.Event()
        self.active_proc: subprocess.Popen | None = None
        self.settings = config.load()
        self.download_dir = self.settings["download_dir"]
        self.default_length = self.settings["default_length"]
        # "Update yt-dlp" lives in the Settings window, which may be closed while
        # an update is still running — hence the nullable reference.
        self.update_btn: T.RoundButton | None = None
        self.ytdlp_info_var = tk.StringVar(value="checking…")

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
        tk.Label(mark, text=f"  v{__version__}   youtube → timeline", bg=T.BG,
                 fg=T.MUTED, font=(T.FONT, 10)).pack(side="left", pady=(T.px(10), 0))

        right = tk.Frame(header, bg=T.BG)
        right.pack(side="right", pady=(T.px(8), 0))
        self.status = T.StatusPill(right)
        self.status.pack(side="left")
        T.ghost_button(right, "↻", self.refresh_connection, height=30,
                       width=36, radius=9, font=(T.FONT, 11)).pack(
                           side="left", padx=(T.px(12), 0))

        # 1. Source --------------------------------------------------------- #
        card1 = T.Card(root)
        card1.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        b = card1.body
        T.step_header(b, 1, "Source").pack(anchor="w", pady=(0, T.px(18)))

        T.field_label(b, "Video link").pack(anchor="w")
        self.url_var = tk.StringVar()
        # width=1 keeps the requested size minimal; fill="x" makes it span the card.
        T.entry(b, self.url_var, width=1).pack(fill="x", pady=(T.px(7), T.px(18)))

        times = tk.Frame(b, bg=T.CARD)
        times.pack(fill="x")
        times.columnconfigure(0, weight=1)
        times.columnconfigure(1, weight=1)

        incol = tk.Frame(times, bg=T.CARD)
        incol.grid(row=0, column=0, sticky="ew", padx=(0, T.px(9)))
        T.field_label(incol, "In point").pack(anchor="w")
        self.in_var = tk.StringVar(value="00:00")
        T.entry(incol, self.in_var, width=8).pack(fill="x", pady=(T.px(7), 0))

        outcol = tk.Frame(times, bg=T.CARD)
        outcol.grid(row=0, column=1, sticky="ew", padx=(T.px(9), 0))
        T.field_label(outcol, "End point").pack(anchor="w")
        # End point starts at the configured default length past 00:00.
        self.out_var = tk.StringVar(value=seconds_to_timestamp(self.default_length))
        T.entry(outcol, self.out_var, width=8).pack(fill="x", pady=(T.px(7), 0))

        # Quick durations: set the end point to in-point + N.
        T.field_label(b, "Clip length from in point").pack(anchor="w", pady=(T.px(16), 0))
        durations = tk.Frame(b, bg=T.CARD)
        durations.pack(fill="x", pady=(T.px(7), 0))
        for label, seconds in QUICK_DURATIONS:
            T.ghost_button(durations, label,
                           lambda s=seconds: self.set_length(s),
                           height=38, font=(T.FONT, 10)).pack(
                               side="left", fill="x", expand=True, padx=(0, T.px(8)))
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
                bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
        win.geometry(f"{T.px(640)}x{self._fit_height(T.px(810))}")
        win.minsize(T.px(470), T.px(780))
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="Settings", bg=T.BG, fg=T.TEXT,
                 font=(T.FONT, 17, "bold")).pack(anchor="w", padx=T.px(26), pady=(T.px(22), T.px(16)))

        card = T.Card(win)
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

        T.ghost_button(row, "Browse…", browse, height=48, width=110).pack(
            side="left", padx=(T.px(9), 0))
        tk.Label(b, text="Existing clips are left where they are.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", pady=(T.px(10), 0))

        # Defaults ---------------------------------------------------------- #
        defaults_card = T.Card(win)
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

        info = T.Card(win)
        info.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        ib = info.body
        T.step_header(ib, 3, "Tools").pack(anchor="w", pady=(0, 14))
        # Live vars so an update performed from this window refreshes in place.
        self.ytdlp_info_var.set(self._ytdlp_info_text())
        for label, var in (("yt-dlp", self.ytdlp_info_var),
                           ("ffmpeg", tk.StringVar(value=self.ffmpeg_path or "not found"))):
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

        # The button lives in a throwaway window; don't leave a dead widget
        # reference behind for the update thread to poke at.
        win.bind("<Destroy>", lambda e: setattr(self, "update_btn", None)
                 if e.widget is win else None)

        # About / credit ---------------------------------------------------- #
        about = tk.Frame(win, bg=T.BG)
        about.pack(fill="x", padx=T.px(26), pady=(T.px(2), 0))
        tk.Label(about, text=f"{APP_NAME} v{__version__}", bg=T.BG, fg=T.MUTED,
                 font=(T.FONT, 9)).pack(side="left")
        tk.Label(about, text=COPYRIGHT, bg=T.BG, fg=T.MUTED,
                 font=(T.FONT, 9)).pack(side="right")

        buttons = tk.Frame(win, bg=T.BG)
        buttons.pack(fill="x", padx=T.px(26), pady=(10, 22))

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

            try:
                path = config.save(self.settings)
                self.log(f"Clips → {new_dir}")
                self.log(f"Default clip length → {seconds_to_timestamp(length)} "
                         "(applied when the app opens)")
                self.log(f"Settings saved to {path}")
            except OSError as e:
                self.log(f"ERROR saving settings: {e}")
            win.destroy()

        T.RoundButton(buttons, "Save", save, height=48, font=(T.FONT, 12, "bold")).pack(
            side="left", fill="x", expand=True)
        T.ghost_button(buttons, "Cancel", win.destroy, height=48, width=120).pack(
            side="left", padx=(T.px(10), 0))

    # ---- startup ---------------------------------------------------------- #

    def _boot(self) -> None:
        """Resolve dependencies and check Resolve, off the UI thread."""
        self.log(f"{APP_NAME} {__version__} starting…")
        self.log(f"Clips → {self.download_dir}")

        try:
            self.ytdlp_cmd, self.ffmpeg_path = deps.ensure_all(self.log)
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR getting tools: {e}")
            self._set_status("missing tools", T.DANGER)
            return

        self.ytdlp_version = self._probe_version()
        self.log(f"yt-dlp {self.ytdlp_version or '?'} ready · "
                 f"ffmpeg {os.path.basename(self.ffmpeg_path or '?')}")
        self.root.after(0, lambda: self.ytdlp_info_var.set(self._ytdlp_info_text()))

        self._check_connection()
        # Both action buttons start disabled until the tools are resolved; go
        # through _set_busy(False) so neither is forgotten.
        self.root.after(0, lambda: self._set_busy(False))

    def _probe_version(self) -> str | None:
        try:
            proc = subprocess.run([*(self.ytdlp_cmd or []), "--version"],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=30,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return (proc.stdout or "").strip().splitlines()[-1] if proc.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    # ---- actions ---------------------------------------------------------- #

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

        stamp = seconds_to_timestamp(seconds)
        self.in_var.set(stamp)
        self.log(f"In point set to {stamp} (from the link's t={seconds}s).")

        # An in point past the end point would just fail validation later, so
        # nudge the end out rather than leaving the fields contradictory.
        end = normalize_timestamp(self.out_var.get())
        if end is None or to_seconds(end) <= seconds:
            new_end = seconds_to_timestamp(seconds + 10)
            self.out_var.set(new_end)
            self.log(f"End point moved to {new_end} to keep the range valid.")

    def _collect_job(self) -> tuple[str, str, str] | None:
        """Validate the form. Returns (url, start, end) or None after logging why."""
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
        if to_seconds(end) <= to_seconds(start):
            self.log("ERROR: end point must be after in point.")
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
        """Kill the running tool. yt-dlp spawns ffmpeg, so on Windows we take out
        the whole tree — killing only the parent would leave ffmpeg running."""
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
                proc.kill()
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
        cmd = [*(self.ytdlp_cmd or []), "--dump-single-json", "--no-warnings",
               "--skip-download", "--no-playlist", url]
        try:
            # Popen (not run) so STOP can kill it mid-lookup.
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
    def _scrubs_poorly(codec: str) -> bool:
        """VP9 and AV1 decode slowly in Resolve; H.264 hardware-decodes.

        YouTube only offers H.264 up to 1080p, so anything above that is
        necessarily one of these.
        """
        codec = (codec or "").lower()
        return codec.startswith(("vp0", "vp8", "vp9", "av0", "av1"))

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
                # YouTube has no H.264 above 1080p, so this is unavoidable at
                # 1440p/4K. Resolve's own proxies handle it better than we could.
                self.log(f"  Note: {codec} decodes slowly in Resolve. If playback "
                         "stutters, right-click")
                self.log("        the clip in the Media Pool -> Generate Optimized "
                         "Media.")

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
        # "<id>-<ChannelName>-cNNN", numbered from what's already on disk so
        # nothing is ever overwritten.
        stem = naming.next_clip_stem(job_dir, video_id, meta.get("channel", ""))
        section = f"*{start}-{end}"

        self.log(f"Folder: {os.path.basename(job_dir)}")
        self.log(f"File:   {stem}.mp4")

        cmd = [
            *(self.ytdlp_cmd or []),
            url,
            "--download-sections", section,
            "--force-keyframes-at-cuts",
            "-f", format_selector(max_height),
            "-S", FORMAT_SORT,
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", os.path.join(job_dir, stem + ".%(ext)s"),
            "--newline",
        ]
        if self.ffmpeg_path:
            cmd += ["--ffmpeg-location", os.path.dirname(self.ffmpeg_path)]

        self.log(f"Fetching {section} at {self.quality_var.get()}…")
        # yt-dlp spends a moment extracting and selecting formats before any frames
        # arrive, so say what we're actually doing instead of leaving the label
        # on "Reading video info...".
        self._progress(step="Preparing download…")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.active_proc = proc
        assert proc.stdout is not None
        saw_403 = False
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
            if saw_403:
                # A 403 here is YouTube rejecting a specific format URL, not a
                # missing resolution — the usual cures are a newer yt-dlp or
                # letting it pick the format.
                self.log("HINT: 403 means YouTube refused that format's URL.")
                self.log("      Try 'Best available', or hit 'Update yt-dlp'.")
            return None

        # Prefer the merged mp4; otherwise take whatever container we got,
        # ignoring yt-dlp's leftover .part / .ytdl scratch files.
        exact = os.path.join(job_dir, stem + ".mp4")
        if os.path.isfile(exact):
            return exact
        produced = [
            f for f in os.listdir(job_dir)
            if f.startswith(stem + ".") and not f.endswith((".part", ".ytdl"))
        ]
        if not produced:
            self.log("yt-dlp finished but produced no file.")
            return None
        return os.path.join(job_dir, produced[0])


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
