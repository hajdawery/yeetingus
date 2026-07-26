#!/usr/bin/env python3
"""
install.py — put YEET where Resolve and the launcher expect it.

    py -3.13 build.py      # produces dist\\YEET.exe
    py -3.13 install.py    # installs it + adds the Resolve menu entry

Installs:
  * dist\\YEET.exe   ->  %LOCALAPPDATA%\\YEET\\YEET.exe
  * resolve\\YEET.lua ->  Resolve's Scripts\\Utility folder
                          (appears as Workspace -> Scripts -> Utility -> YEET)

Pass --dev to skip the exe and wire the menu entry to the source script instead.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def read_version() -> str:
    """Read backend/version.py without importing it (avoids pulling in tkinter)."""
    path = os.path.join(HERE, "backend", "version.py")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', fh.read())
        if match:
            return match.group(1)
    except OSError:
        pass
    return "unknown"

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


def install_exe() -> str | None:
    src = os.path.join(HERE, "dist", "YEET.exe")
    if not os.path.isfile(src):
        return None
    dest_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "YEET")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "YEET.exe")
    try:
        shutil.copy2(src, dest)
    except PermissionError:
        print(f"! Could not overwrite {dest} — close YEET if it's running, then retry.")
        return None
    print(f"+ app       -> {dest}")

    # The shim must sit next to the exe; it launches "%~dp0YEET.exe" with
    # PYTHONHOME cleared, without which the exe segfaults under Resolve.
    shim_src = os.path.join(HERE, "resolve", "launch_yeet.bat")
    if os.path.isfile(shim_src):
        shim_dest = os.path.join(dest_dir, "launch_yeet.bat")
        shutil.copy2(shim_src, shim_dest)
        print(f"+ shim      -> {shim_dest}")
    else:
        print(f"! missing {shim_src} — the Resolve menu entry will fall back to an inline scrub")
    return dest


def install_launcher() -> str | None:
    """Render resolve/YEET.lua.in with absolute paths baked in.

    Resolve's Lua host doesn't reliably expose %LOCALAPPDATA%, so the launcher
    must not depend on os.getenv — otherwise every path breaks and clicking the
    menu item silently does nothing. AutoSubs hardcodes its paths for the same
    reason.
    """
    src = os.path.join(HERE, "resolve", "YEET.lua.in")
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

    yeet_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "YEET")
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    for token, value in (
        ("@@YEET_DIR@@", yeet_dir),
        ("@@BAT@@", os.path.join(yeet_dir, "launch_yeet.bat")),
        ("@@EXE@@", os.path.join(yeet_dir, "YEET.exe")),
        ("@@LOG@@", os.path.join(yeet_dir, "launcher.log")),
        ("@@VERSION@@", read_version()),
        ("@@INSTALLED_AT@@", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ):
        text = text.replace(token, value)
    # Match only real tokens (@@NAME@@) — the template legitimately mentions "@@"
    # in its header comment and in its own fallback check.
    leftover = re.findall(r"@@[A-Z_]+@@", text)
    if leftover:
        print(f"! placeholders left unsubstituted: {set(leftover)} — check resolve/YEET.lua.in")

    dest = os.path.join(SCRIPTS_DIR, "YEET.lua")
    # Lua's [[...]] literals take the paths verbatim; ASCII keeps Resolve's
    # parser happy regardless of its locale.
    with open(dest, "w", encoding="ascii", errors="replace", newline="\r\n") as fh:
        fh.write(text)
    print(f"+ menu item -> {dest}")
    print(f"    paths baked in -> {yeet_dir}")
    return dest


def verify() -> bool:
    """Re-read from disk and report exactly what is there, so a run of this
    script is self-proving rather than something you have to take on trust."""
    yeet_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "YEET")
    expected = [
        os.path.join(yeet_dir, "YEET.exe"),
        os.path.join(yeet_dir, "launch_yeet.bat"),
        os.path.join(SCRIPTS_DIR, "YEET.lua"),
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
    dev = "--dev" in sys.argv
    print("Installing YEET…")

    exe = None if dev else install_exe()
    if not dev and not exe:
        print("  (no dist\\YEET.exe — run `py -3.13 build.py` first, or use --dev)")

    launcher = install_launcher()
    if not launcher:
        return 1

    if not verify():
        print("\n! Something is missing above. If a file failed to write, the most likely\n"
              "  causes are antivirus quarantine or a permissions problem on that folder.")
        return 1

    print("\nDone. In Resolve:  Workspace -> Scripts -> Utility -> YEET")
    print("\n>>> RESTART DAVINCI RESOLVE NOW. <<<")
    print("    Resolve caches the launcher script when it builds the Scripts menu,")
    print("    so until you restart it will keep running the previous version.")
    if dev:
        script = os.path.join(HERE, "backend", "yeet_app.py")
        print("\nDev mode: set this once so the launcher can find your source copy —")
        print(f'  setx YEET_DEV_SCRIPT "{script}"')
        print("  (then restart Resolve so it picks up the new environment)")
    print("If the menu entry doesn't appear, restart Resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
