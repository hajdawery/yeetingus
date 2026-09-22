"""
resolve_menu.py — the "YEETingus" entry in Resolve's Scripts menu.

Resolve's Workspace → Scripts → Utility menu lists Lua files from its
Scripts/Utility folder; one of them is our launcher, rendered from
resolve/YEETingus.lua.in with absolute paths baked in (Resolve's Lua host
does not reliably see %LOCALAPPDATA%, so nothing in the launcher may depend
on the environment — see the template's header for the whole story).

In 1.x install.py wrote this file. In 2.0 the app does, from Settings or the
first-run setup, the same way it installs the Premiere panel: on a click,
never by itself. Restart Resolve afterwards — it caches the menu at startup.

The launcher starts the app exe directly. The 1.x shim that cleared
PYTHONHOME first is no longer needed: the app is a Rust exe, and it strips
those variables itself before starting the Python service (see lib.rs).

On macOS the launcher is given the .app bundle, not the executable inside
it: the bundle is opened through Launch Services (/usr/bin/open), which
starts it with a clean environment and brings up the running copy instead
of a second one. See launch_target.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime

import platform_paths as pp
from version import APP_NAME, __version__

LUA_NAME = f"{APP_NAME}.lua"


class ResolveMenuError(RuntimeError):
    pass


def template_path() -> str | None:
    """resolve/YEETingus.lua.in — beside the frozen service, or in the repo."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "resolve", f"{APP_NAME}.lua.in"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "resolve", f"{APP_NAME}.lua.in"))
    return next((c for c in candidates if os.path.isfile(c)), None)


def launch_target(app_exe: str | None) -> str | None:
    """What the launcher should start for `app_exe`.

    On macOS the service is handed Contents/MacOS/<binary>; the launcher
    wants the enclosing .app. A dev build (target/debug/yeetingus) has no
    bundle and is started as it is.
    """
    if not app_exe or not pp.MACOS:
        return app_exe
    macos_dir = os.path.dirname(app_exe)
    contents = os.path.dirname(macos_dir)
    bundle = os.path.dirname(contents)
    if (os.path.basename(macos_dir) == "MacOS" and os.path.basename(contents) == "Contents"
            and bundle.endswith(".app")):
        return bundle
    return app_exe


def installed_path() -> str | None:
    """Where our launcher is, if it's in any of Resolve's Scripts folders."""
    for d in pp.scripts_dirs():
        p = os.path.join(d, LUA_NAME)
        if os.path.isfile(p):
            return p
    return None


def installed_target() -> str | None:
    """The app exe the installed launcher points at (to tell a stale one)."""
    p = installed_path()
    if not p:
        return None
    try:
        with open(p, "r", encoding="ascii", errors="replace") as fh:
            m = re.search(r"^local EXE\s*=\s*\[\[(.*?)\]\]", fh.read(), re.MULTILINE)
        return m.group(1) if m else None
    except OSError:
        return None


def info(app_exe: str | None) -> dict:
    app_exe = launch_target(app_exe)
    path = installed_path()
    target = installed_target()
    return {
        "installed": path is not None,
        "path": path,
        "target": target,
        # The launcher points somewhere else than this app: an old install,
        # or a dev build alongside a packaged one.
        "stale": bool(path and app_exe and target
                      and os.path.normcase(target) != os.path.normcase(app_exe)),
        "app_exe": app_exe,
        "resolve_found": any(os.path.isdir(d) for d in pp.scripts_dirs()),
    }


def install(app_exe: str | None, log) -> str:
    """Write the launcher for `app_exe` into Resolve's Scripts/Utility.
    Returns the path written."""
    if not app_exe or not os.path.isfile(app_exe):
        raise ResolveMenuError("This build doesn't know where its own exe is; "
                               "start YEETingus from its installed location.")
    src = template_path()
    if not src:
        raise ResolveMenuError("The launcher template isn't shipped with this build.")

    scripts = pp.scripts_dir()
    if not os.path.isdir(scripts):
        # Resolve creates this on first run; if it has never been opened, make
        # it ourselves rather than refusing.
        try:
            os.makedirs(scripts, exist_ok=True)
            log(f"  (created {scripts})")
        except OSError as e:
            raise ResolveMenuError(f"Resolve's Scripts folder couldn't be created: {e}. "
                                   "Is DaVinci Resolve installed for this user?")

    target = launch_target(app_exe)
    app_dir = os.path.dirname(target)
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    values = (
        ("@@YEET_DIR@@", app_dir),
        ("@@SHIM@@", target),           # no shim any more; the app clears the env itself
        ("@@EXE@@", target),
        ("@@LOG@@", os.path.join(pp.app_data_dir(), "launcher.log")),
        ("@@APP_NAME@@", APP_NAME),
        ("@@VERSION@@", __version__),
        ("@@INSTALLED_AT@@", datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    if not all(value.isascii() for _, value in values):
        # Written as ASCII (below), a path like C:\Users\Łukasz would turn
        # into C:\Users\?ukasz and the menu entry would silently do nothing.
        # The values, not the rendered text: the template is ours to keep ASCII.
        raise ResolveMenuError(
            "the app's path has non-ASCII characters, which Resolve's Lua can't "
            f"be given reliably: {target}. Install YEETingus to a plain-ASCII folder.")
    for token, value in values:
        text = text.replace(token, value)
    leftover = re.findall(r"@@[A-Z_]+@@", text)
    if leftover:
        raise ResolveMenuError(f"placeholders left unsubstituted: {sorted(set(leftover))}")

    dest = os.path.join(scripts, LUA_NAME)
    # ASCII + CRLF on Windows: what Resolve's Lua parser has always been given.
    newline = "\r\n" if pp.WINDOWS else "\n"
    try:
        with open(dest, "w", encoding="ascii", errors="replace", newline=newline) as fh:
            fh.write(text)
    except OSError as e:
        raise ResolveMenuError(f"couldn't write {dest}: {e}")
    os.makedirs(pp.app_data_dir(), exist_ok=True)

    # One copy only: a launcher in another Scripts folder would be listed twice.
    for d in pp.scripts_dirs():
        other = os.path.join(d, LUA_NAME)
        if os.path.normcase(other) != os.path.normcase(dest) and os.path.isfile(other):
            try:
                os.remove(other)
                log(f"  removed the old copy at {other}")
            except OSError:
                pass
    return dest


def uninstall(log) -> bool:
    removed = False
    for d in pp.scripts_dirs():
        p = os.path.join(d, LUA_NAME)
        if os.path.isfile(p):
            try:
                os.remove(p)
                removed = True
                log(f"Removed {p}")
            except OSError as e:
                raise ResolveMenuError(f"couldn't remove {p}: {e}")
    return removed
