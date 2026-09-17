#!/usr/bin/env python3
"""
YEETingus — media ingestion for video editors: pull a time-ranged fragment of a
video you have the right to use (your own uploads, openly licensed material,
promotional media for creator/press/editorial use), prepare it for editing, and
paste it straight onto the current DaVinci Resolve timeline.

This file is the Tk window. Everything it does — the download, the preparation
pass, the Resolve insert, the tools and settings — lives in engine.py, which
the window drives in-process and listens to for events. service.py exposes the
same engine over localhost for the other front ends.

Run from source (needs Python 3.6-3.13 — Resolve's fusionscript library is a C
extension that CRASHES on 3.14+; see resolve_bridge.MAX_PY):

    py -3.13 yeet_app.py

yt-dlp and ffmpeg are fetched automatically on first run into
%LOCALAPPDATA%\\YEETingus\\bin if they aren't already available.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys

import tkinter as tk
from tkinter import filedialog, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config                    # noqa: E402
import deps                      # noqa: E402
import naming                    # noqa: E402
import resolve_bridge            # noqa: E402
import theme as T                # noqa: E402
from engine import (             # noqa: E402
    QUALITY_OPTIONS, Engine, normalize_timestamp, seconds_to_timestamp, to_seconds,
)
from version import APP_NAME, AUTHOR_URL, COPYRIGHT, __version__  # noqa: E402

# Width of the log panel docked to the right; the window grows by this when the
# log is shown. Authored at 96 DPI like every other pixel value.
LOG_PANEL_W = 420

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

# The engine reports the Resolve pill as ok/error; these are the colours.
_LEVEL_COLOURS = {"ok": T.ACCENT, "error": T.DANGER}


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #


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



# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


class YeetApp:
    def __init__(self, root: tk.Tk, engine: Engine | None = None) -> None:
        self.root = root
        self.engine = engine or Engine()
        # Engine events arrive on worker threads; they're queued here and
        # drained on the Tk thread by _poll_events.
        self.events: queue.Queue[dict] = queue.Queue()
        # "Update yt-dlp" lives in the Settings window, which may be closed while
        # an update is still running — hence the nullable reference.
        self.update_btn: T.RoundButton | None = None
        self.ytdlp_info_var = tk.StringVar(value="checking…")
        self.ffmpeg_info_var = tk.StringVar(value="checking…")
        self.caps_info_var = tk.StringVar(value="checking…")
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

        # Anything the engine said before we subscribed (nothing, when the
        # window owns the engine — but a shared one may have a history).
        for event in list(self.engine.history):
            self.events.put(event)
        self.engine.subscribe(self.events.put)
        self._poll_events()
        if not self.engine.booted:
            self.engine.start_boot()
        else:
            self._apply_tools(self.engine.tools_info())
            self._set_busy(self.engine.busy)

    # Engine-owned state the UI reads; kept as properties so the window never
    # holds a stale copy.
    @property
    def download_dir(self) -> str:
        return self.engine.download_dir

    @property
    def default_length(self) -> int:
        return self.engine.default_length

    @property
    def busy(self) -> bool:
        return self.engine.busy

    @property
    def ffmpeg_path(self) -> str | None:
        return self.engine.ffmpeg_path

    @property
    def deno_path(self) -> str | None:
        return self.engine.deno_path

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


    # ---- engine events ----------------------------------------------------- #

    def log(self, msg: str, tag: str | None = None) -> None:
        """Window-side messages go through the engine too, so every front end
        (and the service's history) sees the same log."""
        self.engine.log(msg, tag)

    def _poll_events(self) -> None:
        try:
            while True:
                self._on_event(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _on_event(self, ev: dict) -> None:
        """Apply one engine event to the widgets. Runs on the Tk thread."""
        kind = ev["kind"]
        if kind == "log":
            self._append_log(ev["text"], ev.get("tag"))
        elif kind == "progress":
            if ev.get("fraction") is not None:
                self.progress.set(ev["fraction"])
            if ev.get("step") is not None:
                self.step_var.set(ev["step"])
        elif kind == "resolve":
            self.status.set(ev["text"], _LEVEL_COLOURS.get(ev["level"], T.DANGER))
        elif kind == "busy":
            self._set_busy(ev["busy"])
        elif kind == "tools":
            self._apply_tools(ev)
        elif kind == "tool_busy":
            btn = {"ytdlp": self.update_btn, "ffmpeg": self.ffmpeg_btn,
                   "js": self.js_btn}.get(ev["tool"])
            # Safe even if the Settings window has since been closed.
            if btn is not None and btn.winfo_exists():
                btn.set_enabled(not ev["busy"])
        elif kind == "reveal_log":
            self.reveal_log()

    def _append_log(self, line: str, tag: str | None) -> None:
        if tag is None:
            low = line.lower()
            tag = "bad" if ("error" in low or "warning" in low or "resolve:" in low) else \
                  "accent" if ("ready" in low or "done" in low or "inserted" in low) else ""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _apply_tools(self, info: dict) -> None:
        self.ytdlp_info_var.set(info["ytdlp"])
        self.ffmpeg_info_var.set(info["ffmpeg"])
        self.caps_info_var.set(info["video"])
        self.js_info_var.set(info["js"])

    def _set_busy(self, busy: bool) -> None:
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

    # ---- log panel --------------------------------------------------------- #

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

    # ---- connection / tools (delegated) ------------------------------------ #

    def refresh_connection(self) -> None:
        self.engine.refresh_connection()

    def on_update_ytdlp(self) -> None:
        self.engine.start_update_ytdlp()

    def on_install_ffmpeg(self) -> None:
        self.engine.start_install_ffmpeg()

    def on_install_js(self) -> None:
        self.engine.start_install_js()

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

        info = T.Card(body)
        info.pack(fill="x", padx=T.px(26), pady=(0, T.px(16)))
        ib = info.body
        T.step_header(ib, 3, "Tools").pack(anchor="w", pady=(0, 14))
        # Live vars so an update performed from this window refreshes in place.
        self._apply_tools(self.engine.tools_info())
        for label, var in (("yt-dlp", self.ytdlp_info_var),
                           ("ffmpeg", self.ffmpeg_info_var),
                           ("video", self.caps_info_var),
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

            try:
                length = int(length_var.get())
            except ValueError:
                length = config.DEFAULTS["default_length"]

            try:
                if self.engine.update_settings(download_dir=new_dir,
                                               default_length=length):
                    self.log(f"Clips → {new_dir}")
                    self.log(f"Default clip length → {seconds_to_timestamp(length)} "
                             "(applied when the app opens)")
            except (OSError, ValueError) as e:
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


    # ---- jobs ------------------------------------------------------------- #

    def _start_job(self, insert: bool) -> None:
        self.engine.start_job(
            self.url_var.get(), self.in_var.get(), self.out_var.get(),
            QUALITY_OPTIONS[self.quality_var.get()], self.insert_var.get(),
            insert=insert)

    def on_yeet(self) -> None:
        # The same button stops the job while one is running.
        if self.busy:
            self.engine.cancel()
            return
        self._start_job(insert=True)

    def on_download_only(self) -> None:
        """Download the clip and leave it on disk — no Resolve involvement."""
        if self.busy:
            return
        self._start_job(insert=False)


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
