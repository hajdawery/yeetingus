"""
deps.py — locate (and where it is legitimate to, fetch) the external binaries
YEETingus needs.

Lookup order for each tool:
  1. env override            (YEET_YTDLP / YEET_FFMPEG / YEET_FFPROBE / YEET_DENO)
  2. bundled next to the app (vendor/ inside the PyInstaller bundle)
  3. the app's own bin dir   (first-run downloads land here)
  4. whatever is on PATH
  5. (yt-dlp only) the pip-installed module, via `python -m yt_dlp`

WHAT GETS DOWNLOADED, AND WHY IT DIFFERS BY PLATFORM
----------------------------------------------------
yt-dlp publishes an official binary for every platform we support, so it is
fetched automatically everywhere — the user gets the publisher's own artifact.

Deno is the same case, and is fetched the same way. YouTube now serves its
formats behind a JavaScript challenge, and yt-dlp solves it by running scripts
in an external JS runtime — see https://github.com/yt-dlp/yt-dlp/wiki/EJS.
Without one, some videos lose formats or fail outright. Deno is the runtime
yt-dlp enables by default, publishes signed release builds for every platform we
support, and is MIT-licensed, so the provenance question that keeps ffmpeg off
this list does not arise.

ffmpeg does not, and the difference is not cosmetic:

  * Windows — BtbN's FFmpeg-Builds, the project yt-dlp's own FFmpeg-Builds is a
    fork of (yt-dlp's README states it applies no patches, so the binaries are
    the same). Auto-downloaded. The *LGPL* variant is fetched deliberately: it
    leaves out the GPL-only encoder libraries, none of which this app invokes
    (media.py uses exactly two encoders), while keeping everything it does
    use: the native MPEG-4 encoder, NVENC/Quick Sync/AMF AV1, dav1d, libvpx
    and the AAC/Opus codecs.

  * macOS — there is no equivalent. ffmpeg.org links exactly one macOS source,
    evermeet.cx, which states it will not build for Apple Silicon. Every arm64
    binary on offer traces back to a single personal site that labels its
    downloads "for educational purposes only" — including the GitHub projects
    that appear to be independent builders but are re-hosting it. We will not
    point users at a binary whose provenance we cannot vouch for, so ffmpeg is
    an install step on macOS rather than a download. Homebrew builds in public
    CI, ships checksummed bottles, and the user installs it themselves.

  * Linux — every distribution packages ffmpeg. Use the package manager.

Not bundling ffmpeg is also what keeps the licence position simple: its GPL
terms attach to *distribution*, and this project distributes no part of it. See
THIRD-PARTY-NOTICES.md. Bundling it — including indirectly, via a PyPI package
like imageio-ffmpeg that PyInstaller would freeze into the app — would change
that, which is why neither is done.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import urllib.request
import zipfile
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_paths as _pp  # noqa: E402

# Official release artifacts. yt-dlp's macOS build is a universal binary, so one
# asset covers both Apple Silicon and Intel.
_YTDLP_ASSET = {
    "win32": "yt-dlp.exe",
    "darwin": "yt-dlp_macos",
    "linux": "yt-dlp",
}
YTDLP_URL = ("https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
             + _YTDLP_ASSET["win32" if _pp.WINDOWS else
                            "darwin" if _pp.MACOS else "linux"])

# Windows only — see the module docstring for why there is no macOS counterpart,
# and for why it is the LGPL build.
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-lgpl.zip"
)


def _arch() -> str:
    """'x86_64' or 'aarch64' — the only two architectures Resolve runs on."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    return "x86_64"


# Deno's own release assets. Deliberately not "denort": that is the stripped
# runtime for compiled Deno binaries, and the EJS wiki calls out picking the
# wrong one as a common mistake. Each archive holds a single `deno` executable
# at its root.
_DENO_ASSET = {
    ("win32", "x86_64"): "deno-x86_64-pc-windows-msvc.zip",
    ("win32", "aarch64"): "deno-aarch64-pc-windows-msvc.zip",
    ("darwin", "x86_64"): "deno-x86_64-apple-darwin.zip",
    ("darwin", "aarch64"): "deno-aarch64-apple-darwin.zip",
    ("linux", "x86_64"): "deno-x86_64-unknown-linux-gnu.zip",
    ("linux", "aarch64"): "deno-aarch64-unknown-linux-gnu.zip",
}
_DENO_KEY = ("win32" if _pp.WINDOWS else "darwin" if _pp.MACOS else "linux", _arch())
DENO_ASSET = _DENO_ASSET.get(_DENO_KEY)
DENO_URL = ("https://github.com/denoland/deno/releases/latest/download/" + DENO_ASSET
            if DENO_ASSET else None)

# Roughly what the user is in for on first run, so the log can say so before
# spending it rather than after. Approximate on purpose — it grows every release
# and is only ever shown as "~N MB".
DENO_DOWNLOAD_MB = 40

# The oldest Deno yt-dlp will accept, from the EJS wiki. An older one is worse
# than none at all from the user's point of view: yt-dlp ignores it and reports
# that no runtime could be found, giving no hint that the deno on PATH is the
# problem. So it is version-checked and replaced rather than trusted.
DENO_MIN = (2, 3, 0)

ProgressCB = Callable[[str], None]

# True where ffmpeg is the user's to install rather than ours to fetch. The UI
# reads this to decide whether to offer an install button, so it stays in step
# with what ensure_ffmpeg will actually do.
MACOS_FFMPEG_MANUAL = _pp.MACOS


class MissingDependency(RuntimeError):
    """A required tool is absent and cannot be fetched for the user.

    Carries a message written for the log panel: what is missing, and the exact
    command to fix it.
    """


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def app_dir() -> str:
    """Per-user folder holding the downloaded tools and settings."""
    return _pp.app_data_dir()


def bin_dir() -> str:
    """Where first-run downloads of yt-dlp land. Created on demand."""
    return _pp.bin_dir()


def _bundled_dir() -> str | None:
    """vendor/ inside a PyInstaller bundle, or the repo's vendor/ during dev."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "vendor")
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(os.path.dirname(here), "vendor")
    return cand if os.path.isdir(cand) else None


def _candidate_names(tool: str) -> list[str]:
    """Filenames a tool might have here, most-specific first.

    Covers the platform's own naming (yt-dlp_macos), the Windows .exe suffix,
    and the bare name that a package manager or manual install would leave.
    """
    names = []
    if tool == "yt-dlp":
        names.append(_YTDLP_ASSET["win32" if _pp.WINDOWS else
                                  "darwin" if _pp.MACOS else "linux"])
    if _pp.EXE_SUFFIX:
        names.append(tool + _pp.EXE_SUFFIX)
    names.append(tool)
    # dict.fromkeys to dedupe while keeping order (bare name may repeat).
    return list(dict.fromkeys(names))


# Package-manager prefixes to search after PATH. A GUI process launched from
# Resolve does not inherit a login shell's PATH — on macOS it gets a minimal one
# with neither Homebrew prefix on it — so a perfectly good `brew install ffmpeg`
# would otherwise look like nothing is installed. The launcher shim also fixes
# PATH, but the app can be started directly, so don't rely on it.
_EXTRA_BIN_DIRS = (
    ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")  # brew arm64, brew Intel, MacPorts
    if _pp.MACOS else ()
)


def _look_for(tool: str) -> str | None:
    """Find `tool` in the bundle, our bin dir, on PATH, or in a known prefix.

    Location takes precedence over filename: a bundled copy wins over anything
    on PATH regardless of which name each goes by. Looping the other way round
    would let a PATH hit for the platform-specific name beat a bundled build,
    which is the opposite of the documented order.
    """
    names = _candidate_names(tool)
    bundled = _bundled_dir()
    for directory in (bundled, bin_dir()):
        if not directory:
            continue
        for name in names:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                return path
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for directory in _EXTRA_BIN_DIRS:
        for name in names:
            path = os.path.join(directory, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def _make_executable(path: str) -> None:
    """Set the execute bit on a freshly downloaded binary.

    No-op on Windows. On macOS and Linux a file written by urllib has mode 0644
    and would fail with "Permission denied" on the first run.

    Gatekeeper quarantine is deliberately not handled here: the com.apple.
    quarantine attribute is applied by Launch Services on behalf of browsers and
    similar, not by a plain urllib download, so there is nothing to strip. If
    that ever changes, the fix is `xattr -d com.apple.quarantine`, not disabling
    Gatekeeper.
    """
    if _pp.WINDOWS:
        return
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# --------------------------------------------------------------------------- #
# Download helper
# --------------------------------------------------------------------------- #


# CA bundles to fall back on, most-trustworthy first. /etc/ssl/cert.pem is part
# of stock macOS; the Homebrew paths cover a machine whose openssl came from
# there. Only consulted when the interpreter's own store is unusable.
_CA_BUNDLE_FALLBACKS = (
    "/etc/ssl/cert.pem",
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/usr/local/etc/ca-certificates/cert.pem",
    "/usr/local/etc/openssl@3/cert.pem",
)


def _ssl_context() -> ssl.SSLContext:
    """A verifying SSL context that works on a stock macOS Python.

    The python.org framework builds ship no CA bundle: they expect you to run
    /Applications/Python 3.x/Install Certificates.command after installing, and
    until you do, every HTTPS request fails with CERTIFICATE_VERIFY_FAILED. The
    Windows build never hits this because it uses the OS trust store, which is
    why this only shows up on the Mac port.

    A frozen build is usually fine — PyInstaller collects certifi — so this
    matters most when running from source. Falls back through certifi and then
    the system bundles above.

    Verification is never disabled. An unverified download of an executable that
    is then run is precisely the thing certificate checking exists to prevent,
    so when no trust store can be found this raises and tells the user how to
    fix theirs.
    """
    ctx = ssl.create_default_context()
    try:
        if ctx.get_ca_certs():
            return ctx
    except Exception:  # noqa: BLE001 — treat an unreadable store as empty
        pass

    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
        return ctx
    except Exception:  # noqa: BLE001 — not installed, or bundle unreadable
        pass

    for bundle in _CA_BUNDLE_FALLBACKS:
        if os.path.isfile(bundle):
            try:
                ctx.load_verify_locations(bundle)
                return ctx
            except Exception:  # noqa: BLE001 — try the next one
                continue

    hint = ""
    if _pp.MACOS:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        hint = (f"\n  Run:  /Applications/Python {version}/Install Certificates.command"
                "\n  (or:  pip install certifi)")
    raise MissingDependency(
        "No certificate authority bundle found, so downloads can't be verified."
        f"{hint}")


def _download(url: str, dest: str, log: ProgressCB) -> None:
    log(f"Downloading {os.path.basename(dest)} …")
    log(f"  from {url}")
    tmp = dest + ".part"
    last_pct = -10

    context = _ssl_context()
    req = urllib.request.Request(url, headers={"User-Agent": "YEETingus/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=context) as resp, \
            open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if pct - last_pct >= 10:
                    last_pct = pct
                    log(f"  {pct}%  ({done // 1048576} / {total // 1048576} MB)")
            elif done % (8 * 1048576) < 262144:
                log(f"  {done // 1048576} MB…")

    os.replace(tmp, dest)
    log(f"  saved to {dest}")


# --------------------------------------------------------------------------- #
# yt-dlp
# --------------------------------------------------------------------------- #


def find_ytdlp() -> list[str] | None:
    """How to invoke yt-dlp as a command list, or None if it is unavailable."""
    override = os.environ.get("YEET_YTDLP")
    if override and os.path.isfile(override):
        return [override]

    exe = _look_for("yt-dlp")
    if exe:
        return [exe]

    # pip-installed module (dev convenience only; not available when frozen)
    if not getattr(sys, "frozen", False):
        try:
            import importlib.util

            if importlib.util.find_spec("yt_dlp") is not None:
                return [sys.executable, "-m", "yt_dlp"]
        except Exception:  # noqa: BLE001
            pass
    return None


def ensure_ytdlp(log: ProgressCB) -> list[str]:
    """find_ytdlp(), downloading the official binary first if it is missing."""
    cmd = find_ytdlp()
    if cmd:
        return cmd
    dest = os.path.join(bin_dir(), os.path.basename(YTDLP_URL))
    _download(YTDLP_URL, dest, log)
    _make_executable(dest)
    return [dest]


# --------------------------------------------------------------------------- #
# ffmpeg
# --------------------------------------------------------------------------- #


def find_ffmpeg() -> str | None:
    """Path to an ffmpeg binary, or None if there is none to be found."""
    override = os.environ.get("YEET_FFMPEG")
    if override and os.path.isfile(override):
        return override
    return _look_for("ffmpeg")


def find_ffprobe() -> str | None:
    """ffprobe ships beside ffmpeg in every build we use, so fall back to that."""
    override = os.environ.get("YEET_FFPROBE")
    if override and os.path.isfile(override):
        return override
    found = _look_for("ffprobe")
    if found:
        return found
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        candidate = os.path.join(os.path.dirname(ffmpeg), "ffprobe" + _pp.EXE_SUFFIX)
        if os.path.isfile(candidate):
            return candidate
    return None


def homebrew_path() -> str | None:
    """The `brew` executable, or None. Also checks the two standard prefixes,
    since a GUI app launched from Resolve does not inherit a login shell's PATH
    and would otherwise conclude Homebrew is absent when it is installed."""
    found = shutil.which("brew")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/brew",   # Apple Silicon
                      "/usr/local/bin/brew"):      # Intel
        if os.path.isfile(candidate):
            return candidate
    return None


def ffmpeg_install_hint() -> str:
    """The command that installs ffmpeg on this platform, for the UI and logs."""
    if _pp.MACOS:
        return "brew install ffmpeg"
    if _pp.WINDOWS:
        return ""  # fetched automatically; nothing for the user to run
    for manager, command in (("apt-get", "sudo apt install ffmpeg"),
                             ("dnf", "sudo dnf install ffmpeg"),
                             ("pacman", "sudo pacman -S ffmpeg"),
                             ("zypper", "sudo zypper install ffmpeg")):
        if shutil.which(manager):
            return command
    return "install ffmpeg with your package manager"


def install_ffmpeg_via_brew(log: ProgressCB) -> str:
    """Run `brew install ffmpeg`, then re-locate it. macOS only.

    Only ever called from an explicit click in Settings — never as part of
    startup. Installing software is the user's decision, and Homebrew writes
    outside our own application-data folder.
    """
    brew = homebrew_path()
    if not brew:
        raise MissingDependency(
            "Homebrew isn't installed. Install it from https://brew.sh, then "
            "run:  brew install ffmpeg")

    log("Running: brew install ffmpeg")
    log("  (this is Homebrew's own download; it may take a few minutes)")
    proc = subprocess.Popen([brew, "install", "ffmpeg"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(f"  {line}")
    proc.wait()
    if proc.returncode != 0:
        raise MissingDependency(
            f"brew install ffmpeg failed (exit {proc.returncode}). See the log above.")

    found = find_ffmpeg()
    if not found:
        raise MissingDependency(
            "Homebrew reported success but ffmpeg still isn't on PATH. "
            "Try opening a new terminal and running `brew doctor`.")
    log(f"ffmpeg installed: {found}")
    return found


def ensure_ffmpeg(log: ProgressCB) -> str:
    """find_ffmpeg(), fetching a build first where we have a trustworthy source.

    Raises MissingDependency with install instructions where we do not — see the
    module docstring.
    """
    found = find_ffmpeg()
    if found:
        return found

    if not _pp.WINDOWS:
        hint = ffmpeg_install_hint()
        extra = ""
        if _pp.MACOS and not homebrew_path():
            extra = ("\n  Homebrew isn't installed either — get it from "
                     "https://brew.sh first.")
        raise MissingDependency(
            "ffmpeg isn't installed, and YEETingus doesn't download it on this "
            "platform.\n"
            f"  Install it with:  {hint}{extra}\n"
            "  Then reopen YEETingus, or press Retry in Settings.\n"
            "  (Already have a build elsewhere? Point YEET_FFMPEG at it.)")

    zip_path = os.path.join(bin_dir(), "_ffmpeg.zip")
    _download(FFMPEG_URL, zip_path, log)

    log("  extracting ffmpeg…")
    wanted = ("ffmpeg.exe", "ffprobe.exe")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            name = os.path.basename(member)
            if name in wanted:
                with zf.open(member) as src, open(os.path.join(bin_dir(), name), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                log(f"  extracted {name}")
    try:
        os.remove(zip_path)
    except OSError:
        pass

    found = find_ffmpeg()
    if not found:
        raise MissingDependency(
            "ffmpeg archive downloaded but ffmpeg.exe wasn't found inside it.")
    return found


# --------------------------------------------------------------------------- #
# JavaScript runtime (Deno) — for yt-dlp's YouTube challenge solver
# --------------------------------------------------------------------------- #


# Where Deno's own installer puts it. Same reasoning as _EXTRA_BIN_DIRS above:
# an app launched from Resolve doesn't inherit a login shell's PATH, so a deno
# the user installed perfectly well would otherwise look absent.
def _deno_install_dirs() -> tuple[str, ...]:
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".deno", "bin")]
    if _pp.MACOS:
        dirs += ["/opt/homebrew/bin", "/usr/local/bin"]
    return tuple(dirs)


def find_deno() -> str | None:
    """Path to a Deno executable, or None.

    Only Deno is looked for. yt-dlp also supports Node, Bun and QuickJS, but
    Deno is the one it enables by default and the one its wiki recommends, and
    every extra runtime here is another thing to detect, version-check and
    explain.

    YEET_DENO therefore has to point at a Deno build: the flag YEETingus passes
    names deno explicitly, so a Node or QuickJS path would be rejected by yt-dlp.
    Anyone who wants a different runtime should configure it in yt-dlp's own
    config file, which YEETingus does not override.
    """
    override = os.environ.get("YEET_DENO")
    if override and os.path.isfile(override):
        return override

    found = _look_for("deno")
    if found:
        return found

    for directory in _deno_install_dirs():
        path = os.path.join(directory, "deno" + _pp.EXE_SUFFIX)
        if os.path.isfile(path) and (_pp.WINDOWS or os.access(path, os.X_OK)):
            return path
    return None


def _deno_new_enough(version: str | None) -> bool:
    """Whether `version` meets DENO_MIN. An unreadable version counts as too old:
    a deno that won't report its version won't run the solver either."""
    if not version:
        return False
    found = [int(p) for p in re.findall(r"\d+", version)[:3]]
    if not found:
        return False
    # Pad rather than truncate DENO_MIN: comparing a bare "2" against (2,) would
    # call it new enough when it means 2.0.0, which is not.
    while len(found) < len(DENO_MIN):
        found.append(0)
    return tuple(found) >= DENO_MIN


def ensure_deno(log: ProgressCB) -> str:
    """find_deno(), downloading Deno's official build first if it is missing.

    Raises MissingDependency on an unsupported architecture, or if the archive
    turns out not to contain what we expect. The caller treats a failure as a
    warning rather than a fatal error: yt-dlp still works without a JS runtime,
    it just loses formats on YouTube.
    """
    ours = os.path.join(bin_dir(), "deno" + _pp.EXE_SUFFIX)
    found = find_deno()
    if found:
        version = deno_version(found)
        if _deno_new_enough(version):
            return found
        log(f"Found deno {version or '(unreadable)'} at {found}, but yt-dlp needs "
            f"{'.'.join(map(str, DENO_MIN))} or newer.")
        # A previous run may already have fetched a good one. Checked explicitly
        # because YEET_DENO outranks everything in find_deno — without this, an
        # override pointing at an old build would re-download on every launch.
        if found != ours and _deno_new_enough(deno_version(ours)):
            log(f"  Using the newer copy already in {bin_dir()}.")
            return ours

    if not DENO_URL:
        raise MissingDependency(
            f"No Deno build is published for this platform ({sys.platform} "
            f"{platform.machine()}).\n"
            "  Install a JavaScript runtime yourself and point YEET_DENO at it — "
            "see https://github.com/yt-dlp/yt-dlp/wiki/EJS")

    log(f"Getting Deno — YouTube needs a JavaScript runtime now (~{DENO_DOWNLOAD_MB} MB, "
        "one time).")
    log("  Why: https://github.com/yt-dlp/yt-dlp/wiki/EJS")
    zip_path = os.path.join(bin_dir(), "_deno.zip")
    _download(DENO_URL, zip_path, log)

    log("  extracting deno…")
    wanted = "deno" + _pp.EXE_SUFFIX
    extracted = None
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if os.path.basename(member) != wanted:
                continue
            dest = os.path.join(bin_dir(), wanted)
            with zf.open(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted = dest
            break
    try:
        os.remove(zip_path)
    except OSError:
        pass

    if not extracted:
        raise MissingDependency(
            f"Deno archive downloaded but {wanted} wasn't found inside it.")
    _make_executable(extracted)
    log(f"  deno ready: {extracted}")
    return extracted


def deno_version(deno: str) -> str | None:
    """'2.9.4', or None if it won't run. Used for the Settings readout.

    CREATE_NO_WINDOW matters here: the frozen app has no console of its own, so
    without it every startup flashes an empty black window on screen.
    """
    try:
        proc = subprocess.run([deno, "--version"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001 — absent, wrong architecture, blocked…
        return None
    if proc.returncode != 0:
        return None
    # "deno 2.9.4 (stable, release, x86_64-pc-windows-msvc)" on the first line.
    first = (proc.stdout or "").strip().splitlines()
    if not first:
        return None
    parts = first[0].split()
    return parts[1] if len(parts) > 1 else None


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def ensure_all(log: ProgressCB) -> tuple[list[str], str]:
    """Return (ytdlp_cmd, ffmpeg_path), fetching whatever is missing and can be
    fetched.

    Raises on failure — the caller shows the message in the UI log.
    """
    ytdlp = ensure_ytdlp(log)
    ffmpeg = ensure_ffmpeg(log)
    return ytdlp, ffmpeg
