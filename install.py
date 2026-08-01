#!/usr/bin/env python3
"""
install.py — put YEETingus where Resolve and the launcher expect it.

    Windows:  py -3.13 build.py       then  py -3.13 install.py
    macOS:    python3.13 build.py     then  python3.13 install.py

Installs (paths shown for each platform):
  * the app     ->  %LOCALAPPDATA%\\YEETingus\\YEETingus.exe
                    ~/Library/Application Support/YEETingus/YEETingus.app
  * the shim    ->  beside the app (clears PYTHONHOME first)
                    launch_yeetingus.bat / launch_yeetingus.sh
  * YEETingus.lua ->  Resolve's Scripts/Utility folder
                      (Workspace -> Scripts -> Utility -> YEETingus)

Also migrates a previous "YEET" install on Windows: the downloaded tool cache
and settings are moved across, and the old exe, shim and menu entry are removed
so Resolve doesn't show two entries.

Pass --dev to skip the built app and wire the menu entry to the source instead.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# True when running as the frozen Install-<App> binary rather than from the repo.
FROZEN = getattr(sys, "frozen", False)

# The app was called "YEET" up to v1.0.0; used only for one-time migration, and
# only on Windows, which is the only platform it ever shipped for.
LEGACY_NAME = "YEET"

# platform_paths is the single source of truth for per-OS locations. Frozen, it
# is unpacked flat beside the other bundled resources, so make that directory
# importable before reaching for it.
if FROZEN:
    sys.path.insert(0, getattr(sys, "_MEIPASS", HERE))
else:
    sys.path.insert(0, os.path.join(HERE, "backend"))

import platform_paths as pp  # noqa: E402

WINDOWS = pp.WINDOWS
MACOS = pp.MACOS


def resource(*parts: str) -> str:
    """Locate a bundled file.

    Frozen, everything the installer needs — the app exe, the shim and the
    launcher template — is unpacked flat into a temp dir, so only the basename
    matters. From the repo they keep their normal layout.
    """
    if FROZEN:
        return os.path.join(getattr(sys, "_MEIPASS", HERE), parts[-1])
    return os.path.join(HERE, *parts)


def _read_const(name: str, fallback: str) -> str:
    """Read a constant from version.py without importing it (which would pull in
    tkinter via the package's other modules)."""
    try:
        with open(resource("backend", "version.py"), "r", encoding="utf-8") as fh:
            match = re.search(rf'{name}\s*=\s*["\']([^"\']+)["\']', fh.read())
        if match:
            return match.group(1)
    except OSError:
        pass
    return fallback


def read_version() -> str:
    """The app version from backend/version.py."""
    return _read_const("__version__", "unknown")


def read_app_name() -> str:
    """The app name from backend/version.py."""
    return _read_const("APP_NAME", "YEETingus")


APP = read_app_name()

# What build.py produces, and what we copy into place. On macOS that is a .app
# bundle — a directory, not a file — which is why every check below asks about
# "the app" rather than calling os.path.isfile.
EXE_NAME = f"{APP}.exe" if WINDOWS else (f"{APP}.app" if MACOS else APP)
SHIM_NAME = f"launch_{APP.lower()}" + (".bat" if WINDOWS else ".sh")
LUA_NAME = f"{APP}.lua"

# A macOS app bundle is a directory; everywhere else the app is a single file.
APP_IS_BUNDLE = MACOS


def app_dir() -> str:
    """Where the app and its shim are installed."""
    return pp.app_data_dir()


def app_exists(path: str) -> bool:
    """Does the installed app exist? Bundles are directories, so isfile lies."""
    return os.path.isdir(path) if APP_IS_BUNDLE else os.path.isfile(path)


SCRIPTS_DIR = pp.scripts_dir()


def migrate_legacy() -> None:
    """Carry a previous "YEET" install over to the new name, then clean it up.

    The tool cache (yt-dlp.exe + ffmpeg, ~100 MB) and settings.json are moved so
    nothing has to be re-downloaded or reconfigured. Our own old artefacts — the
    exe, shim, launcher log and Resolve menu entry — are deleted, since leaving
    the old .lua behind would give Resolve two entries.

    Windows only: "YEET" never shipped for any other platform, so there is
    nothing anywhere else to migrate from.
    """
    if not WINDOWS:
        return

    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    old_dir = os.path.join(base, LEGACY_NAME)
    new_dir = app_dir()
    if os.path.normcase(old_dir) == os.path.normcase(new_dir):
        return

    old_lua = os.path.join(SCRIPTS_DIR, f"{LEGACY_NAME}.lua")
    if not os.path.isdir(old_dir) and not os.path.isfile(old_lua):
        return

    print(f"Migrating previous {LEGACY_NAME} install…")

    if os.path.isdir(old_dir):
        os.makedirs(new_dir, exist_ok=True)
        # Keep anything expensive or user-owned.
        for name in ("bin", "settings.json"):
            src, dst = os.path.join(old_dir, name), os.path.join(new_dir, name)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.move(src, dst)
                    print(f"  moved   {name}")
                except (OSError, shutil.Error) as e:
                    print(f"  ! couldn't move {name}: {e}")

        # Drop our own replaceable files.
        for name in (f"{LEGACY_NAME}.exe", f"launch_{LEGACY_NAME.lower()}.bat",
                     "launcher.log"):
            path = os.path.join(old_dir, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    print(f"  removed {name}")
                except OSError as e:
                    print(f"  ! couldn't remove {name}: {e}")

        # Only if nothing of the user's is left behind.
        try:
            if not os.listdir(old_dir):
                os.rmdir(old_dir)
                print(f"  removed {old_dir}")
            else:
                print(f"  left    {old_dir} (still has files)")
        except OSError:
            pass

    if os.path.isfile(old_lua):
        try:
            os.remove(old_lua)
            print(f"  removed old menu entry {LEGACY_NAME}.lua")
        except OSError as e:
            print(f"  ! couldn't remove {old_lua}: {e}\n"
                  f"    Delete it by hand, or Resolve will list both {LEGACY_NAME} "
                  f"and {APP}.")


def _make_executable(path: str) -> None:
    """Set the execute bit. No-op on Windows, required for the .sh shim."""
    if WINDOWS:
        return
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _python_command() -> str:
    """How to invoke this interpreter from a shell script.

    sys.executable rather than a bare "python3": a --dev shim is launched by
    Resolve, not from the user's shell, so whatever "python3" resolves to there
    may not be the interpreter that could actually load fusionscript.
    """
    return sys.executable


def install_dev_shim() -> str | None:
    """--dev: point the shim at the source script instead of the built app.

    Baking the path into the shim keeps the Lua launcher unchanged and avoids
    depending on an environment variable, which Resolve's Lua host doesn't
    reliably see anyway.
    """
    script = os.path.join(HERE, "backend", "yeet_app.py")
    if not os.path.isfile(script):
        print(f"! missing {script}")
        return None
    dest_dir = app_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, SHIM_NAME)

    if WINDOWS:
        body = (
            "@echo off\r\n"
            f"rem DEV shim written by install.py --dev; runs {APP} from source.\r\n"
            'set "PYTHONHOME="\r\n'
            'set "PYTHONPATH="\r\n'
            'set "PYTHONSTARTUP="\r\n'
            'set "PYTHONEXECUTABLE="\r\n'
            'set "PYTHONNOUSERSITE="\r\n'
            f'start "" py -3.13 "{script}" %*\r\n'
        )
        newline = ""
    else:
        python = _python_command()
        body = (
            "#!/bin/sh\n"
            f"# DEV shim written by install.py --dev; runs {APP} from source.\n"
            "unset PYTHONHOME\n"
            "unset PYTHONPATH\n"
            "unset PYTHONSTARTUP\n"
            "unset PYTHONEXECUTABLE\n"
            "unset PYTHONNOUSERSITE\n"
            "unset PYTHONDONTWRITEBYTECODE\n"
            '# Homebrew prefixes are absent from a GUI process\'s inherited PATH.\n'
            'PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
            "export PATH\n"
            f'exec "{python}" "{script}" "$@"\n'
        )
        newline = "\n"

    with open(dest, "w", encoding="utf-8", errors="replace", newline=newline) as fh:
        fh.write(body)
    _make_executable(dest)
    print(f"+ dev shim  -> {dest}")
    print(f"    runs    -> {'py -3.13' if WINDOWS else _python_command()} {script}")
    return dest


def install_exe() -> str | None:
    """Copy the built app and its launch shim into place. Returns the app path."""
    src = resource("dist", EXE_NAME)
    if not app_exists(src):
        return None
    dest_dir = app_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, EXE_NAME)
    try:
        if APP_IS_BUNDLE:
            # copytree won't merge into an existing tree, and a stale bundle left
            # in place would keep old resources alongside the new ones.
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
    except PermissionError:
        print(f"! Could not overwrite {dest} — close {APP} if it's running, then retry.")
        return None
    except (OSError, shutil.Error) as e:
        print(f"! Could not install to {dest}: {e}")
        return None
    print(f"+ app       -> {dest}")

    # The shim must sit next to the app; it launches it with PYTHONHOME cleared,
    # without which the frozen build segfaults under Resolve.
    shim_src = resource("resolve", SHIM_NAME)
    if os.path.isfile(shim_src):
        shim_dest = os.path.join(dest_dir, SHIM_NAME)
        shutil.copy2(shim_src, shim_dest)
        _make_executable(shim_dest)
        print(f"+ shim      -> {shim_dest}")
    else:
        print(f"! missing {shim_src} — the Resolve menu entry will fall back to an inline scrub")
    return dest


def install_launcher() -> str | None:
    """Render the launcher template with absolute paths baked in.

    Resolve's Lua host doesn't reliably expose %LOCALAPPDATA%, so the launcher
    must not depend on os.getenv — otherwise every path breaks and clicking the
    menu item silently does nothing. AutoSubs hardcodes its paths for the same
    reason.
    """
    src = resource("resolve", f"{APP}.lua.in")
    if not os.path.isfile(src):
        print(f"! missing {src}")
        return None
    if not os.path.isdir(SCRIPTS_DIR):
        # Resolve creates this on first run; if the user has never opened it, make
        # it ourselves rather than refusing to install.
        try:
            os.makedirs(SCRIPTS_DIR, exist_ok=True)
            print(f"  (created {SCRIPTS_DIR})")
        except OSError as e:
            print(f"! Resolve Scripts folder not found and couldn't be created:\n"
                  f"    {SCRIPTS_DIR}\n    {e}\n"
                  "  Is DaVinci Resolve installed for this user?")
            return None

    target_dir = app_dir()
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    for token, value in (
        ("@@YEET_DIR@@", target_dir),
        ("@@SHIM@@", os.path.join(target_dir, SHIM_NAME)),
        ("@@EXE@@", os.path.join(target_dir, EXE_NAME)),
        ("@@LOG@@", os.path.join(target_dir, "launcher.log")),
        ("@@APP_NAME@@", APP),
        ("@@VERSION@@", read_version()),
        ("@@INSTALLED_AT@@", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ):
        text = text.replace(token, value)
    # Match only real tokens (@@NAME@@) — the template legitimately mentions "@@"
    # in its header comment and in its own fallback check.
    leftover = re.findall(r"@@[A-Z_]+@@", text)
    if leftover:
        print(f"! placeholders left unsubstituted: {set(leftover)} — check {src}")

    dest = os.path.join(SCRIPTS_DIR, LUA_NAME)
    # Lua's [[...]] literals take the paths verbatim; ASCII keeps Resolve's
    # parser happy regardless of its locale. Line endings follow the platform:
    # CRLF is what Windows Resolve has always been given, and LF is correct
    # everywhere else.
    newline = "\r\n" if WINDOWS else "\n"
    with open(dest, "w", encoding="ascii", errors="replace", newline=newline) as fh:
        fh.write(text)
    print(f"+ menu item -> {dest}")
    print(f"    paths baked in -> {target_dir}")
    return dest


def verify(dev: bool = False) -> bool:
    """Re-read from disk and report exactly what is there, so a run of this
    script is self-proving rather than something you have to take on trust."""
    target_dir = app_dir()
    expected = [
        (os.path.join(target_dir, SHIM_NAME), False),
        (os.path.join(SCRIPTS_DIR, LUA_NAME), False),
    ]
    # A --dev install deliberately has no built app: the shim runs the source
    # directly. Demanding one here would fail every dev install.
    if not dev:
        expected.insert(0, (os.path.join(target_dir, EXE_NAME), APP_IS_BUNDLE))
    print("\n--- verification (read back from disk) ---")
    if WINDOWS:
        print(f"LOCALAPPDATA = {os.environ.get('LOCALAPPDATA')}")
        print(f"APPDATA      = {os.environ.get('APPDATA')}")
    else:
        print(f"app dir      = {target_dir}")
        print(f"scripts dir  = {SCRIPTS_DIR}")
    ok = True
    for path, is_dir in expected:
        if is_dir:
            # A bundle's size is the sum of its tree, which is what a user would
            # expect to see reported for "the app".
            if os.path.isdir(path):
                size = sum(os.path.getsize(os.path.join(root, name))
                           for root, _, names in os.walk(path)
                           for name in names
                           if not os.path.islink(os.path.join(root, name)))
                print(f"  OK      {size:>10,} bytes  {path}")
                continue
        elif os.path.isfile(path):
            print(f"  OK      {os.path.getsize(path):>10,} bytes  {path}")
            continue
        print(f"  MISSING                       {path}")
        ok = False
    return ok


def main() -> int:
    """Install, verify, and report. Returns a process exit code."""
    dev = "--dev" in sys.argv
    print(f"Installing {APP}…")

    migrate_legacy()

    if dev:
        if not install_dev_shim():
            return 1
    else:
        if not install_exe():
            build_cmd = "py -3.13 build.py" if WINDOWS else "python3.13 build.py"
            sep = "\\" if WINDOWS else "/"
            print(f"  (no dist{sep}{EXE_NAME} — run `{build_cmd}` first, or use --dev)")

    launcher = install_launcher()
    if not launcher:
        return 1

    if not verify(dev):
        if WINDOWS:
            print("\n! Something is missing above. If a file failed to write, the most likely\n"
                  "  causes are antivirus quarantine or a permissions problem on that folder.")
        else:
            print("\n! Something is missing above. The most likely cause is a permissions\n"
                  "  problem on that folder.")
        return 1

    print(f"\nDone. In Resolve:  Workspace -> Scripts -> Utility -> {APP}")
    print("\n>>> RESTART DAVINCI RESOLVE NOW. <<<")
    print("    Resolve caches the launcher script when it builds the Scripts menu,")
    print("    so until you restart it will keep running the previous version.")
    if dev:
        print("\nDev mode: the menu entry now runs your source copy directly —")
        print("    no bundle and no environment variables involved. Re-run this")
        print("    after moving the project, since the path is baked into the shim.")
    if MACOS:
        _report_ffmpeg()
    print("If the menu entry doesn't appear, restart Resolve.")
    return 0


def _report_ffmpeg() -> None:
    """Tell the user about ffmpeg while they are still at the terminal.

    macOS has no trustworthy ffmpeg binary to download on the user's behalf (see
    backend/deps.py), so it is an install step. Saying so here — rather than
    letting the app discover it on first launch — means the one manual step is
    surfaced next to the others instead of as a surprise later.
    """
    if shutil.which("ffmpeg") or os.path.isfile("/opt/homebrew/bin/ffmpeg") \
            or os.path.isfile("/usr/local/bin/ffmpeg"):
        return
    print("\n--- one more thing: ffmpeg ---")
    print("  ffmpeg isn't installed, and YEETingus doesn't download it on macOS:")
    print("  there is no build for Apple Silicon whose origin we can vouch for.")
    print("  Install it yourself with:\n")
    print("      brew install ffmpeg\n")
    print("  (No Homebrew? Get it from https://brew.sh first.)")


def _run() -> int:
    code = main()
    # Double-clicked, the console window closes the instant this returns, taking
    # the verification block with it. Wait for a keypress so it can be read.
    if FROZEN and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nPress Enter to close…")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(_run())
