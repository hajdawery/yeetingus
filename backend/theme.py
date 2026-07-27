"""
theme.py — palette and custom Tkinter widgets for YEETingus' dark UI.

Styled after AutoSubs: near-black canvas, softly rounded cards, numbered step
badges, pill controls. Tk has no native rounded corners, so cards and buttons
draw themselves on a Canvas behind their content.
"""

from __future__ import annotations

import math
import tkinter as tk

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #

BG = "#08090a"          # window background
CARD = "#131417"        # card surface
INPUT = "#1c1e22"       # entry / unselected pill
BORDER = "#26282c"      # hairline borders
TEXT = "#e7e8ea"        # primary text
MUTED = "#8a8d94"       # secondary text
LOG_BG = "#0d0e10"      # log surface
ACCENT = "#edff00"      # brand accent
ACCENT_TEXT = "#0a0b0c"  # text on accent
DANGER = "#ff5f56"

FONT = "Segoe UI"
MONO = "Consolas"


def lighten(hex_color: str, amount: float) -> str:
    """Blend a hex colour toward white by `amount` (0..1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle as a smoothed polygon (the classic Tk recipe)."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


# --------------------------------------------------------------------------- #
# Card
# --------------------------------------------------------------------------- #


class Card(tk.Frame):
    """A rounded panel. Put content in `.body`."""

    def __init__(self, parent, *, radius: int = 16, fill: str = CARD,
                 outline: str = BORDER, pad: int = 22):
        super().__init__(parent, bg=parent.cget("bg"))
        self._fill, self._outline, self._radius = fill, outline, radius
        self._cv = tk.Canvas(self, bg=parent.cget("bg"), highlightthickness=0,
                             bd=0, takefocus=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, ev) -> None:
        self._cv.delete("all")
        round_rect(self._cv, 1, 1, ev.width - 1, ev.height - 1, self._radius,
                   fill=self._fill, outline=self._outline)


# --------------------------------------------------------------------------- #
# Numbered step badge + section header
# --------------------------------------------------------------------------- #


def step_header(parent, number: int, title: str, *, bg: str = CARD) -> tk.Frame:
    row = tk.Frame(parent, bg=bg)
    size = 27
    cv = tk.Canvas(row, width=size, height=size, bg=bg, highlightthickness=0,
                   bd=0, takefocus=0)
    cv.create_oval(0, 0, size - 1, size - 1, fill=ACCENT, outline=ACCENT)
    cv.create_text(size / 2, size / 2 + 1, text=str(number), fill=ACCENT_TEXT,
                   font=(FONT, 11, "bold"))
    cv.pack(side="left")
    tk.Label(row, text=title, bg=bg, fg=TEXT, font=(FONT, 13, "bold")).pack(
        side="left", padx=(12, 0))
    return row


def field_label(parent, text: str, *, bg: str = CARD) -> tk.Label:
    return tk.Label(parent, text=text, bg=bg, fg=MUTED, font=(FONT, 10))


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #


class RoundButton(tk.Canvas):
    def __init__(self, parent, text: str, command=None, *, fill: str = ACCENT,
                 fg: str = ACCENT_TEXT, outline: str = "", height: int = 46,
                 radius: int = 12, font=(FONT, 11, "bold"), width: int | None = None,
                 icon: str | None = None):
        # width=1 by default: a bare Canvas requests ~238px, which would force the
        # window wider than intended. Callers size buttons via pack fill/expand.
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0,
                         height=height, width=width or 1, takefocus=0)
        self._text, self._cmd = text, command
        self._fill, self._fg, self._outline = fill, fg, outline
        self._hover_fill = lighten(fill, 0.14)
        self._radius, self._font = radius, font
        self._icon = icon
        self._enabled, self._hovering = True, False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    # -- public ------------------------------------------------------------
    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._draw()

    def set_style(self, *, fill: str | None = None, fg: str | None = None,
                  icon: str | None | bool = False) -> None:
        """Restyle in place. `icon=False` leaves the icon alone; pass None to
        remove it, or a name to change it."""
        if fill:
            self._fill = fill
            self._hover_fill = lighten(fill, 0.14)
        if fg:
            self._fg = fg
        if icon is not False:
            self._icon = icon  # type: ignore[assignment]
        self._draw()

    # -- internals ---------------------------------------------------------
    def _on_click(self, _ev) -> None:
        if self._enabled and self._cmd:
            self._cmd()

    def _on_enter(self, _ev) -> None:
        self._hovering = True
        self._draw()

    def _on_leave(self, _ev) -> None:
        self._hovering = False
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            return
        if not self._enabled:
            fill, fg, outline = INPUT, MUTED, BORDER
        else:
            fill = self._hover_fill if self._hovering else self._fill
            fg = self._fg
            outline = self._outline or fill
        round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=fill, outline=outline)

        cy = h / 2
        if self._icon:
            # Measure the label first, then centre icon+label as one unit.
            probe = self.create_text(-999, -999, text=self._text, font=self._font)
            x1, _, x2, _ = self.bbox(probe)
            self.delete(probe)
            text_w = x2 - x1
            icon_w, gap = 20, 12
            start = (w - (icon_w + gap + text_w)) / 2
            self._draw_icon(start + icon_w / 2, cy, fg, fill)
            self.create_text(start + icon_w + gap + text_w / 2, cy,
                             text=self._text, fill=fg, font=self._font)
        else:
            self.create_text(w / 2, cy, text=self._text, fill=fg, font=self._font)

        self.configure(cursor="hand2" if self._enabled else "")

    def _draw_icon(self, cx: float, cy: float, colour: str, bg: str) -> None:
        """Vector icons, drawn rather than font glyphs so they stay crisp at any
        DPI and can't fall back to a missing character. `bg` is the button fill,
        used to punch holes (Tk canvases have no transparency)."""
        if self._icon == "drop":
            # Arrow dropping onto a bar: "insert this into the timeline".
            self.create_line(cx, cy - 9, cx, cy + 1, fill=colour, width=2)
            self.create_polygon(cx - 6, cy - 1, cx + 6, cy - 1, cx, cy + 7,
                                fill=colour, outline=colour)
            self.create_line(cx - 9, cy + 10, cx + 9, cy + 10, fill=colour, width=2)

        elif self._icon == "folder":
            # Classic folder: back edge with a tab, then the front face.
            self.create_polygon(
                cx - 9, cy + 7, cx - 9, cy - 6, cx - 2, cy - 6,
                cx, cy - 4, cx + 9, cy - 4, cx + 9, cy + 7,
                fill=colour, outline=colour)
            # Thin notch so the front face reads separately from the back.
            self.create_line(cx - 9, cy - 1, cx + 9, cy - 1, fill=bg, width=1)

        elif self._icon == "list":
            # Three ragged lines — a log / text panel.
            for dy, half in ((-6, 9), (-1, 6), (4, 9)):
                self.create_line(cx - half, cy + dy, cx + half, cy + dy,
                                 fill=colour, width=2)

        elif self._icon == "gear":
            teeth, r_out, r_in = 8, 9.0, 6.4
            pts: list[float] = []
            steps = teeth * 2
            for i in range(steps):
                # Offset by half a step so a tooth points straight up.
                angle = (i + 0.5) / steps * 2 * math.pi
                r = r_out if i % 2 == 0 else r_in
                pts += [cx + r * math.cos(angle), cy + r * math.sin(angle)]
            self.create_polygon(pts, fill=colour, outline=colour)
            hole = 2.8
            self.create_oval(cx - hole, cy - hole, cx + hole, cy + hole,
                             fill=bg, outline=bg)


def ghost_button(parent, text: str, command=None, **kw) -> RoundButton:
    kw.setdefault("fill", INPUT)
    kw.setdefault("fg", TEXT)
    kw.setdefault("outline", BORDER)
    kw.setdefault("font", (FONT, 10))
    return RoundButton(parent, text, command, **kw)


# --------------------------------------------------------------------------- #
# Segmented control
# --------------------------------------------------------------------------- #


class Segmented(tk.Frame):
    """Row of mutually exclusive pills. `options` is [(value, label), ...]."""

    def __init__(self, parent, options, variable: tk.StringVar, *, bg: str = CARD,
                 height: int = 46):
        super().__init__(parent, bg=bg)
        self._var = variable
        self._buttons: dict[str, RoundButton] = {}
        for value, label in options:
            btn = RoundButton(
                self, label, lambda v=value: self._select(v),
                fill=INPUT, fg=MUTED, outline=BORDER, height=height,
                radius=11, font=(FONT, 11),
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self._buttons[value] = btn
        self._refresh()
        variable.trace_add("write", lambda *_: self._refresh())

    def _select(self, value: str) -> None:
        self._var.set(value)

    def _refresh(self) -> None:
        current = self._var.get()
        for value, btn in self._buttons.items():
            selected = value == current
            btn._fill = ACCENT if selected else INPUT
            btn._fg = ACCENT_TEXT if selected else MUTED
            btn._outline = "" if selected else BORDER
            btn._hover_fill = lighten(btn._fill, 0.14)
            btn._font = (FONT, 11, "bold") if selected else (FONT, 11)
            btn._draw()


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def entry(parent, textvariable, *, bg: str = CARD, width: int | None = None,
          justify: str = "left") -> tk.Frame:
    """A padded, bordered dark entry. Returns the wrapper; pack/grid that."""
    wrap = tk.Frame(parent, bg=BORDER)
    inner = tk.Frame(wrap, bg=INPUT)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    ent = tk.Entry(inner, textvariable=textvariable, bg=INPUT, fg=TEXT,
                   relief="flat", bd=0, highlightthickness=0, justify=justify,
                   insertbackground=ACCENT, font=(FONT, 12))
    if width:
        ent.configure(width=width)
    ent.pack(fill="both", expand=True, padx=14, pady=13)

    def focus_in(_e):
        wrap.configure(bg=ACCENT)

    def focus_out(_e):
        wrap.configure(bg=BORDER)

    ent.bind("<FocusIn>", focus_in)
    ent.bind("<FocusOut>", focus_out)
    wrap.entry = ent  # type: ignore[attr-defined]
    return wrap


# --------------------------------------------------------------------------- #
# Status pill (coloured dot + text)
# --------------------------------------------------------------------------- #


class StatusPill(tk.Frame):
    """Small connection indicator: a coloured dot plus a label."""

    def __init__(self, parent, *, bg: str = BG):
        super().__init__(parent, bg=bg)
        self._bg = bg
        self._dot = tk.Canvas(self, width=12, height=12, bg=bg,
                              highlightthickness=0, bd=0, takefocus=0)
        self._dot.pack(side="left", pady=(2, 0))
        self._label = tk.Label(self, text="", bg=bg, fg=MUTED, font=(FONT, 10))
        self._label.pack(side="left", padx=(8, 0))
        self.set("connecting...", MUTED)

    def set(self, text: str, colour: str) -> None:
        self._dot.delete("all")
        self._dot.create_oval(1, 1, 11, 11, fill=colour, outline=colour)
        self._label.configure(text=text, fg=TEXT if colour == ACCENT else MUTED)


# --------------------------------------------------------------------------- #
# Progress bar
# --------------------------------------------------------------------------- #


class ProgressBar(tk.Canvas):
    """Rounded determinate progress bar. `set(fraction)` with 0.0-1.0."""

    def __init__(self, parent, *, height: int = 12, track: str = INPUT,
                 fill: str = ACCENT):
        super().__init__(parent, height=height, width=1, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, takefocus=0)
        self._value = 0.0
        self._track, self._fill = track, fill
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, fraction: float) -> None:
        self._value = max(0.0, min(1.0, float(fraction)))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            return
        r = h / 2
        round_rect(self, 0, 0, w, h, r, fill=self._track, outline=self._track)
        if self._value > 0:
            # Never narrower than the cap radius, or the rounding looks broken.
            fw = max(h, w * self._value)
            round_rect(self, 0, 0, fw, h, r, fill=self._fill, outline=self._fill)


def style_combobox(root: tk.Misc) -> None:
    """Make ttk.Combobox (and its popdown list) match the dark theme."""
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Y.TCombobox",
        fieldbackground=INPUT, background=INPUT, foreground=TEXT,
        arrowcolor=MUTED, bordercolor=BORDER, lightcolor=INPUT, darkcolor=INPUT,
        selectbackground=INPUT, selectforeground=TEXT, arrowsize=16,
        padding=11, relief="flat",
    )
    style.map(
        "Y.TCombobox",
        fieldbackground=[("readonly", INPUT)],
        foreground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
    )
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT)
    root.option_add("*TCombobox*Listbox.font", f"{{{FONT}}} 11")
    root.option_add("*TCombobox*Listbox.borderWidth", "0")
    root.option_add("*TCombobox*Listbox.relief", "flat")
