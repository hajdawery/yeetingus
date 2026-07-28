#!/usr/bin/env python3
"""
build.py — freeze YEETingus into a standalone Windows exe.

MUST be run with a Python that Resolve's fusionscript.dll can be loaded into
(currently 3.6-3.13 — see resolve_bridge.MAX_PY): the frozen exe embeds whichever
interpreter builds it.

    py -3.13 build.py

Output: dist\\YEETingus.exe — no Python needed on the target machine. yt-dlp and
ffmpeg are fetched on first run, so they aren't bundled.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "backend", "yeet_app.py")

sys.path.insert(0, os.path.join(HERE, "backend"))
from version import APP_NAME as NAME  # noqa: E402

INSTALLER_NAME = f"Install-{NAME}"


def main() -> int:
    # The supported range lives in resolve_bridge so there's one place to bump.
    sys.path.insert(0, os.path.join(HERE, "backend"))
    import resolve_bridge

    major, minor = sys.version_info[:2]
    if not resolve_bridge.python_is_supported():
        rng = resolve_bridge.version_range_text()
        newest = "%d.%d" % resolve_bridge.MAX_PY
        print(f"ERROR: building with Python {major}.{minor} would produce an exe that "
              "crashes when it loads Resolve's scripting library.\n"
              f"       Rebuild with {rng}, e.g.:  py -{newest} build.py")
        return 1
    print(f"Building with Python {major}.{minor} (supported range "
          f"{resolve_bridge.version_range_text()}).")

    try:
        import PyInstaller  # noqa: F401  (imported only to test availability)
    except ImportError:
        print("PyInstaller not installed. Installing…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-U", "pyinstaller"],
                       check=True)

    # A stale build/ dir makes PyInstaller reuse old analysis; start clean.
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(HERE, d), ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--windowed",                 # no console window
        "--name", NAME,
        "--paths", os.path.join(HERE, "backend"),
        # imported lazily / by string, so state them explicitly
        "--hidden-import", "config",
        "--hidden-import", "deps",
        "--hidden-import", "theme",
        "--hidden-import", "resolve_bridge",
        "--hidden-import", "naming",
        "--hidden-import", "version",
        # trim obvious dead weight
        "--exclude-module", "numpy",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        ENTRY,
    ]
    # Icon: used for the exe itself, and bundled so the running window/taskbar
    # can set it too (PyInstaller doesn't expose --icon at runtime).
    icon = os.path.join(HERE, "assets", f"{NAME.lower()}.ico")
    if os.path.isfile(icon):
        cmd += ["--icon", icon]
        cmd += ["--add-data", f"{icon}{os.pathsep}assets"]
        print(f"Icon: {icon}")
    else:
        print(f"(no icon at {icon} — building without one)")

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        return result.returncode

    exe = os.path.join(HERE, "dist", NAME + ".exe")
    if not os.path.isfile(exe):
        print(f"ERROR: build reported success but {exe} is missing.")
        return 1

    size = os.path.getsize(exe) / 1048576
    print(f"\nBuilt {exe}  ({size:.1f} MB)")

    if "--no-installer" in sys.argv:
        print("Next:  py -3.13 install.py    (copies it into place + adds the menu entry)")
        return 0

    rc = build_installer(exe, icon)
    if rc != 0:
        return rc

    print("\nNext:  run dist\\%s to install, or `py -3.13 install.py` from here."
          % (INSTALLER_NAME + ".exe"))
    return 0


def build_installer(app_exe: str, icon: str) -> int:
    """Freeze install.py into a single self-contained installer.

    The app exe, the launch shim and the launcher template are bundled inside it,
    so what ships is one file that needs no Python — the same logic already used
    for dev installs, rather than a second implementation that could drift.
    """
    print("\n--- installer ---")
    data = [
        (app_exe, "."),
        (os.path.join(HERE, "resolve", f"launch_{NAME.lower()}.bat"), "."),
        (os.path.join(HERE, "resolve", f"{NAME}.lua.in"), "."),
        (os.path.join(HERE, "backend", "version.py"), "."),
    ]
    missing = [src for src, _ in data if not os.path.isfile(src)]
    if missing:
        for m in missing:
            print(f"ERROR: missing {m}")
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--console",                  # the verification block is the point
        "--name", INSTALLER_NAME,
        "--exclude-module", "tkinter",   # the installer has no UI
        "--exclude-module", "numpy",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
    ]
    for src, dest in data:
        cmd += ["--add-data", f"{src}{os.pathsep}{dest}"]
    if os.path.isfile(icon):
        cmd += ["--icon", icon]
    cmd.append(os.path.join(HERE, "install.py"))

    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        return result.returncode

    out = os.path.join(HERE, "dist", INSTALLER_NAME + ".exe")
    if not os.path.isfile(out):
        print(f"ERROR: installer build reported success but {out} is missing.")
        return 1
    print(f"Built {out}  ({os.path.getsize(out) / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
