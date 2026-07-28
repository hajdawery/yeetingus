#!/usr/bin/env python3
"""
install.py — put YEETingus where Resolve and the launcher expect it.

    py -3.13 build.py      # produces dist\\YEETingus.exe
    py -3.13 install.py    # installs it + adds the Resolve menu entry

Installs:
  * dist\\YEETingus.exe    ->  %LOCALAPPDATA%\\YEETingus\\YEETingus.exe
  * launch_yeetingus.bat  ->  beside the exe (clears PYTHONHOME first)
  * YEETingus.lua         ->  Resolve's Scripts\\Utility folder
                              (Workspace -> Scripts -> Utility -> YEETingus)

Also migrates a previous "YEET" install: the downloaded tool cache and settings
are moved across, and the old exe, shim and menu entry are removed so Resolve
doesn't show two entries.

Pass --dev to skip the exe and wire the menu entry to the source script instead.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# True when running as the frozen Install-<App>.exe rather than from the repo.
FROZEN = getattr(sys, "frozen", False)

# The app was called "YEET" up to v1.0.0; used only for one-time migration.
LEGACY_NAME = "YEET"


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
EXE_NAME = f"{APP}.exe"
SHIM_NAME = f"launch_{APP.lower()}.bat"
LUA_NAME = f"{APP}.lua"


def app_dir() -> str:
    """Where the app and its shim are installed."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP)

def _find_scripts_dir() -> str:
    """Resolve's user Scripts folder. Per-user location first (no admin rights
    needed), then the machine-wide one some installs use."""
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "Blackmagic Design",
                     "DaVinci Resolve", "Support", "Fusion", "Scripts", "Utility"),
        os.path.join(os.environ.get("PROGRAMDATA", ""), "Blackmagic Design",
                     "DaVinci Resolve", "Fusion", "Scripts", "Utility"),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    # Nothing exists yet — return the per-user path so we can create it.
    return candidates[0]


SCRIPTS_DIR = _find_scripts_dir()


def migrate_legacy() -> None:
    """Carry a previous "YEET" install over to the new name, then clean it up.

    The tool cache (yt-dlp.exe + ffmpeg, ~100 MB) and settings.json are moved so
    nothing has to be re-downloaded or reconfigured. Our own old artefacts — the
    exe, shim, launcher log and Resolve menu entry — are deleted, since leaving
    the old .lua behind would give Resolve two entries.
    """
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


def install_dev_shim() -> str | None:
    """--dev: point the shim at the source script instead of the exe.

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
    with open(dest, "w", encoding="ascii", errors="replace", newline="") as fh:
        fh.write(body)
    print(f"+ dev shim  -> {dest}")
    print(f"    runs    -> py -3.13 {script}")
    return dest


def install_exe() -> str | None:
    """Copy the built exe and its launch shim into place. Returns the exe path."""
    src = resource("dist", EXE_NAME)
    if not os.path.isfile(src):
        return None
    dest_dir = app_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, EXE_NAME)
    try:
        shutil.copy2(src, dest)
    except PermissionError:
        print(f"! Could not overwrite {dest} — close {APP} if it's running, then retry.")
        return None
    print(f"+ app       -> {dest}")

    # The shim must sit next to the exe; it launches "%~dp0<App>.exe" with
    # PYTHONHOME cleared, without which the exe segfaults under Resolve.
    shim_src = resource("resolve", SHIM_NAME)
    if os.path.isfile(shim_src):
        shim_dest = os.path.join(dest_dir, SHIM_NAME)
        shutil.copy2(shim_src, shim_dest)
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
        ("@@BAT@@", os.path.join(target_dir, SHIM_NAME)),
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
    # parser happy regardless of its locale.
    with open(dest, "w", encoding="ascii", errors="replace", newline="\r\n") as fh:
        fh.write(text)
    print(f"+ menu item -> {dest}")
    print(f"    paths baked in -> {target_dir}")
    return dest


def verify() -> bool:
    """Re-read from disk and report exactly what is there, so a run of this
    script is self-proving rather than something you have to take on trust."""
    target_dir = app_dir()
    expected = [
        os.path.join(target_dir, EXE_NAME),
        os.path.join(target_dir, SHIM_NAME),
        os.path.join(SCRIPTS_DIR, LUA_NAME),
    ]
    print("\n--- verification (read back from disk) ---")
    print(f"LOCALAPPDATA = {os.environ.get('LOCALAPPDATA')}")
    print(f"APPDATA      = {os.environ.get('APPDATA')}")
    ok = True
    for path in expected:
        if os.path.isfile(path):
            print(f"  OK      {os.path.getsize(path):>10,} bytes  {path}")
        else:
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
            print(f"  (no dist\\{EXE_NAME} — run `py -3.13 build.py` first, or use --dev)")

    launcher = install_launcher()
    if not launcher:
        return 1

    if not verify():
        print("\n! Something is missing above. If a file failed to write, the most likely\n"
              "  causes are antivirus quarantine or a permissions problem on that folder.")
        return 1

    print(f"\nDone. In Resolve:  Workspace -> Scripts -> Utility -> {APP}")
    print("\n>>> RESTART DAVINCI RESOLVE NOW. <<<")
    print("    Resolve caches the launcher script when it builds the Scripts menu,")
    print("    so until you restart it will keep running the previous version.")
    if dev:
        print("\nDev mode: the menu entry now runs your source copy directly —")
        print("    no exe and no environment variables involved. Re-run this after")
        print("    moving the project, since the path is baked into the shim.")
    print("If the menu entry doesn't appear, restart Resolve.")
    return 0


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
