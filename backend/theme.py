"""
theme.py — palette and custom Tkinter widgets for YEETingus' dark UI.

Styled after AutoSubs: near-black canvas, softly rounded cards, numbered step
badges, pill controls. Tk has no native rounded corners, so cards and buttons
draw themselves on a Canvas behind their content.
"""

from __future__ import annotations

import math
import os
import sys
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


def _platform_fonts() -> tuple[str, str]:
    """(ui, mono) font families for this OS.

    Chosen by platform rather than probed, because theme.py is imported before a
    Tk root exists and font.families() needs one. Tk silently substitutes
    something ugly for an unknown family, so a wrong name here is invisible
    rather than an error — hence picking families that always ship.
    """
    if sys.platform == "win32":
        return "Segoe UI", "Consolas"
    if sys.platform == "darwin":
        # Helvetica Neue and Menlo are always present; "SF Pro" isn't reliably
        # addressable by name from Tk.
        return "Helvetica Neue", "Menlo"
    return "DejaVu Sans", "DejaVu Sans Mono"


FONT, MONO = _platform_fonts()

# --------------------------------------------------------------------------- #
# DPI scaling
# --------------------------------------------------------------------------- #
#
# Tk already scales *fonts* by the display DPI (an 11pt font is ~15px at 96 DPI
# and ~22px at 144 DPI). Pixel dimensions — button heights, padding, corner
# radii, icon geometry — do not scale, so on a HiDPI display the text grows while
# the chrome around it stays small and everything looks cramped.
#
# Every pixel value therefore goes through px(), and set_scale() is called once
# at startup with the display's DPI ratio. Sizes below are authored for 96 DPI.

_SCALE = 1.0

# Two different baselines, which is the whole subtlety here. Sharing one constant
# between them is what made the first macOS build come out with 33%-oversized
# chrome around correctly-sized text.
#
# AUTHORED_DPI is a fact about *this codebase*: every pixel constant below was
# drawn for a 96-DPI display. It does not vary by platform.
#
# POINTS_PER_INCH is a fact about *typography*: a point is 1/72 inch, everywhere.
# Tk's own "scaling" is pixels-per-point, so it is measured against this.
#
# Tk reports 96 units/inch on Windows at 100% and 72 on macOS, so the same
# authored 38 comes out 33% physically larger on a Mac unless it is divided by 96
# rather than by whatever the display happens to report.
AUTHORED_DPI = 96.0
POINTS_PER_INCH = 72.0

# Trim applied on top of the display's DPI scale. Windows' 150% is generous for a
# utility window, so the whole UI is drawn slightly tighter than the OS setting
# implies. Applied to fonts *and* pixels so proportions stay identical.
#
# 1.0 on macOS: with the divisor above correct, pixels already land at 72/96 =
# 0.75 and text at parity with Windows. There is no extra inflation to trim, and
# trimming anyway is what made the text look undersized.
DENSITY = 1.0 if sys.platform == "darwin" else 0.85

# Optional overrides for dialling the UI in without a rebuild:
#   YEET_UI_SCALE=0.8   shrink or grow the chrome
#   YEET_FONT_SCALE=1.1 shrink or grow the text, independently
# Both multiply the computed values. Unset means "use the computed value".


def _env_factor(name: str) -> float:
    """A positive multiplier from the environment, or 1.0 if unset/invalid."""
    try:
        value = float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return 1.0
    return value if 0.1 <= value <= 5.0 else 1.0


def px(value: float) -> int:
    """Scale a 96-DPI pixel measurement for the current display."""
    return max(1, int(round(value * _SCALE)))


def set_scale(factor: float) -> None:
    """Set the pixel scale. Call before building widgets; clamped to 0.5-3.0.

    The floor is 0.5, not 1.0. A 1.0 floor looks like a harmless guard against
    an absurd value, but macOS legitimately needs 72/96 = 0.75 — so the clamp
    silently discarded the correct scale and rendered every button, pad and
    radius a third too large.
    """
    global _SCALE
    _SCALE = max(0.5, min(3.0, float(factor)))


def get_scale() -> float:
    """The pixel scale currently in effect."""
    return _SCALE


def units_per_inch(widget: tk.Misc) -> float:
    """How many Tk units the display puts in an inch (96 on Windows, 72 on macOS)."""
    try:
        return float(widget.winfo_fpixels("1i"))
    except Exception:  # noqa: BLE001
        return AUTHORED_DPI


def scale_from_dpi(widget: tk.Misc) -> float:
    """Pixel scale for the authored constants: 1.0 at Windows 100%, 1.5 at 150%,
    0.75 on macOS — where a Tk unit is a 1/72" point rather than a 1/96" pixel."""
    return units_per_inch(widget) / AUTHORED_DPI


def apply_ui_scale(root: tk.Misc) -> float:
    """Set up DPI scaling for both pixels and fonts. Call before building widgets.

    Fonts are handled by Tk's own scaling factor (points -> pixels) rather than by
    rewriting every font size: setting it once here keeps DENSITY applying evenly
    to text and chrome, so the layout shrinks without distorting.
    """
    per_inch = units_per_inch(root)

    # Chrome: authored constants divided by the DPI they were authored at.
    set_scale((per_inch / AUTHORED_DPI) * DENSITY * _env_factor("YEET_UI_SCALE"))

    try:
        # Text: Tk's "scaling" is pixels-per-point, so it is measured against
        # 72 rather than 96. This lands on Tk's own default on both platforms
        # (1.333 on Windows at 100%, 1.0 on macOS) before DENSITY is applied,
        # which is the sign it's being computed the right way round.
        root.tk.call("tk", "scaling",
                     (per_inch / POINTS_PER_INCH) * DENSITY
                     * _env_factor("YEET_FONT_SCALE"))
    except tk.TclError:
        pass
    return get_scale()


def mix(colour: str, base: str, amount: float) -> str:
    """Blend `colour` into `base` by `amount` (0..1) — a tint, not a lighten."""
    c = colour.lstrip("#")
    b = base.lstrip("#")
    out = []
    for i in (0, 2, 4):
        cv, bv = int(c[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(int(round(bv + (cv - bv) * amount)))
    return "#{:02x}{:02x}{:02x}".format(*out)


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
        radius, pad = px(radius), px(pad)
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
    """A numbered accent badge followed by a section title."""
    row = tk.Frame(parent, bg=bg)
    size = px(27)
    cv = tk.Canvas(row, width=size, height=size, bg=bg, highlightthickness=0,
                   bd=0, takefocus=0)
    cv.create_oval(0, 0, size - 1, size - 1, fill=ACCENT, outline=ACCENT)
    cv.create_text(size / 2, size / 2 + 1, text=str(number), fill=ACCENT_TEXT,
                   font=(FONT, 11, "bold"))
    cv.pack(side="left")
    tk.Label(row, text=title, bg=bg, fg=TEXT, font=(FONT, 13, "bold")).pack(
        side="left", padx=(px(12), 0))
    return row


def field_label(parent, text: str, *, bg: str = CARD) -> tk.Label:
    """Small muted caption sitting above an input."""
    return tk.Label(parent, text=text, bg=bg, fg=MUTED, font=(FONT, 10))


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #


class RoundButton(tk.Canvas):
    def __init__(self, parent, text: str, command=None, *, fill: str = ACCENT,
                 fg: str = ACCENT_TEXT, outline: str = "", height: int = 46,
                 radius: int = 12, font=(FONT, 11, "bold"), width: int | None = None,
                 icon: str | None = None):
        height, radius = px(height), px(radius)
        # width=1 by default: a bare Canvas requests ~238px, which would force the
        # window wider than intended. Callers size buttons via pack fill/expand.
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0,
                         height=height, width=px(width) if width else 1, takefocus=0)
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
            icon_w, gap = px(20), px(12)
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
        # Offsets are authored for 96 DPI; s scales the whole glyph.
        s = get_scale()
        w2 = max(1, int(round(2 * s)))          # stroke width

        if self._icon == "drop":
            # Arrow dropping onto a bar: "insert this into the timeline".
            self.create_line(cx, cy - 9 * s, cx, cy + 1 * s, fill=colour, width=w2)
            self.create_polygon(cx - 6 * s, cy - 1 * s, cx + 6 * s, cy - 1 * s,
                                cx, cy + 7 * s, fill=colour, outline=colour)
            self.create_line(cx - 9 * s, cy + 10 * s, cx + 9 * s, cy + 10 * s,
                             fill=colour, width=w2)

        elif self._icon == "folder":
            # Classic folder: back edge with a tab, then the front face.
            self.create_polygon(
                cx - 9 * s, cy + 7 * s, cx - 9 * s, cy - 6 * s, cx - 2 * s, cy - 6 * s,
                cx, cy - 4 * s, cx + 9 * s, cy - 4 * s, cx + 9 * s, cy + 7 * s,
                fill=colour, outline=colour)
            # Thin notch so the front face reads separately from the back.
            self.create_line(cx - 9 * s, cy - 1 * s, cx + 9 * s, cy - 1 * s,
                             fill=bg, width=max(1, int(round(s))))

        elif self._icon == "list":
            # Three ragged lines — a log / text panel.
            for dy, half in ((-6, 9), (-1, 6), (4, 9)):
                self.create_line(cx - half * s, cy + dy * s, cx + half * s,
                                 cy + dy * s, fill=colour, width=w2)

        elif self._icon == "gear":
            teeth, r_out, r_in = 8, 9.0 * s, 6.4 * s
            pts: list[float] = []
            steps = teeth * 2
            for i in range(steps):
                # Offset by half a step so a tooth points straight up.
                angle = (i + 0.5) / steps * 2 * math.pi
                r = r_out if i % 2 == 0 else r_in
                pts += [cx + r * math.cos(angle), cy + r * math.sin(angle)]
            self.create_polygon(pts, fill=colour, outline=colour)
            hole = 2.8 * s
            self.create_oval(cx - hole, cy - hole, cx + hole, cy + hole,
                             fill=bg, outline=bg)


def ghost_button(parent, text: str, command=None, **kw) -> RoundButton:
    """A RoundButton styled as a secondary action: outlined, not filled."""
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
            btn.pack(side="left", fill="x", expand=True, padx=(0, px(8)))
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
    inner.pack(fill="both", expand=True, padx=px(1), pady=px(1))
    ent = tk.Entry(inner, textvariable=textvariable, bg=INPUT, fg=TEXT,
                   relief="flat", bd=0, highlightthickness=0, justify=justify,
                   insertbackground=ACCENT, font=(FONT, 12))
    if width:
        ent.configure(width=width)
    ent.pack(fill="both", expand=True, padx=px(14), pady=px(13))

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


class StatusPill(tk.Canvas):
    """Connection indicator drawn as a rounded chip: status dot + label.

    Sizes itself to its text, and tints the whole chip — not just the dot — so
    the connection state reads at a glance instead of needing to be parsed.
    """

    MAX_TEXT = 34          # characters before the label is elided

    def __init__(self, parent, *, bg: str = BG):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, takefocus=0,
                         height=px(30), width=px(10))
        self._text = ""
        self._colour = MUTED
        self.set("connecting…", MUTED)

    def set(self, text: str, colour: str) -> None:
        if len(text) > self.MAX_TEXT:
            text = text[:self.MAX_TEXT - 1].rstrip() + "…"
        self._text, self._colour = text, colour
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        font = (FONT, 10)
        pad, dot, gap = px(12), px(9), px(9)

        # Measure the label so the chip hugs it.
        probe = self.create_text(-999, -999, text=self._text, font=font)
        x1, _, x2, _ = self.bbox(probe)
        self.delete(probe)

        h = px(30)
        w = pad * 2 + dot + gap + (x2 - x1)
        self.configure(width=w, height=h)

        connected = self._colour == ACCENT
        # A faint wash of the status colour, so the chip itself carries the state.
        fill = mix(self._colour, INPUT, 0.14) if connected else mix(self._colour, INPUT, 0.10)
        round_rect(self, 1, 1, w - 1, h - 1, h / 2,
                   fill=fill, outline=mix(self._colour, BORDER, 0.35))

        cy = h / 2
        cx = pad + dot / 2
        self.create_oval(cx - dot / 2, cy - dot / 2, cx + dot / 2, cy + dot / 2,
                         fill=self._colour, outline=self._colour)
        self.create_text(pad + dot + gap, cy, text=self._text, anchor="w",
                         fill=TEXT if connected else MUTED, font=font)


# --------------------------------------------------------------------------- #
# Progress bar
# --------------------------------------------------------------------------- #


class ProgressBar(tk.Canvas):
    """Rounded determinate progress bar. `set(fraction)` with 0.0-1.0."""

    def __init__(self, parent, *, height: int = 12, track: str = INPUT,
                 fill: str = ACCENT):
        super().__init__(parent, height=px(height), width=1, bg=parent.cget("bg"),
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


# --------------------------------------------------------------------------- #
# Windows title bar
# --------------------------------------------------------------------------- #


def windows_dark_mode() -> bool:
    """True when Windows is set to a dark app theme."""
    if sys.platform != "win32":
        return True
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            light, _ = winreg.QueryValueEx(handle, "AppsUseLightTheme")
        return not bool(light)
    except Exception:  # noqa: BLE001 — key absent on older builds
        return False


def apply_titlebar_theme(window: tk.Misc, dark: bool | None = None) -> bool:
    """Tint the native title bar dark.

    Tk draws its own content but leaves the title bar to Windows, which defaults
    to light — glaring next to a near-black window. DWM exposes this as
    DWMWA_USE_IMMERSIVE_DARK_MODE: attribute 20 on Windows 10 1903+ and 11, but
    19 on 1809, so both are attempted.

    Dark for everyone, regardless of the OS setting: the UI has no light variant,
    so following a light OS theme would just invert the mismatch. Pass dark=False
    to override, or dark=windows_dark_mode() to follow the system again.
    """
    if sys.platform != "win32":
        return False
    if dark is None:
        dark = True
    try:
        from ctypes import byref, c_int, sizeof, windll
        window.update_idletasks()          # the HWND must exist first
        hwnd = windll.user32.GetParent(window.winfo_id())
        value = c_int(1 if dark else 0)
        for attribute in (20, 19):
            if windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, byref(value), sizeof(value)) == 0:
                return True
    except Exception:  # noqa: BLE001 — cosmetic only, never worth failing over
        pass
    return False


# --------------------------------------------------------------------------- #
# Tooltip
# --------------------------------------------------------------------------- #


class _Tooltip:
    """Hover hint in a borderless Toplevel, styled to match the app."""

    def __init__(self, widget: tk.Misc, text: str, delay: int = 450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after_id: str | None = None
        self._win: tk.Toplevel | None = None
        # add="+" so we don't clobber the focus bindings entries already have.
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._win is not None or not self.widget.winfo_exists():
            return
        win = tk.Toplevel(self.widget)
        win.wm_overrideredirect(True)          # no title bar or border
        win.configure(bg=BORDER)               # 1px border via the outer bg
        inner = tk.Frame(win, bg=INPUT)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self.text, bg=INPUT, fg=TEXT, font=(FONT, 9),
                 justify="left", wraplength=px(300)).pack(padx=px(10), pady=px(7))
        win.wm_geometry(f"+{self.widget.winfo_rootx() + px(10)}"
                        f"+{self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)}")
        self._win = win

    def hide(self, _event=None) -> None:
        self._cancel()
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None


def tooltip(widget: tk.Misc, text: str, delay: int = 450) -> _Tooltip:
    """Attach a hover hint to `widget` (keep no reference; it binds itself)."""
    return _Tooltip(widget, text, delay)


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
        selectbackground=INPUT, selectforeground=TEXT, arrowsize=px(16),
        padding=px(11), relief="flat",
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
