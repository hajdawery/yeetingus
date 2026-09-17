"""
premiere_bridge.py — Premiere Pro, through the YEETingus UXP panel.

Premiere has no Python API. What it has is UXP: a JavaScript panel that runs
inside Premiere and can import media and place it on a sequence. So the
Premiere side of YEETingus is a small panel (premiere/panel/) that does only
that, and this module is how the engine talks to it.

The panel is the client. It long-polls the service — `GET /api/premiere/poll`
waits up to ~25 s for a command — runs the command against Premiere's API,
and posts the reply. Nothing here evaluates code the panel sends; the panel
only ever executes the two named methods it knows ("status", "insert").

The bridge holds one connection's worth of state: when the panel was last
seen, the queue of commands waiting for it, and the replies it has posted.
`request()` blocks the calling (worker) thread until the reply arrives or the
deadline passes, exactly like resolve_bridge.import_and_insert blocks.

Installing the panel is here too, copied from Sherlock: a .ccx is a zip of
the panel folder, and Adobe's own UnifiedPluginInstallerAgent (part of every
Creative Cloud install since 5.5) installs it — no developer mode, no UXP
Developer Tool, and it survives Premiere restarts.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import zipfile

# How long the panel may be silent before it counts as gone. It polls with a
# 25 s wait and comes straight back, so a healthy panel is never this quiet.
PANEL_TIMEOUT = 40.0

# Waiting for Premiere to import and place a file. Big files on slow disks
# take a while to import; a stuck Premiere should still not hang a job forever.
REQUEST_TIMEOUT = 120.0

PLUGIN_ID = "com.haej.yeetingus.panel"
PLUGIN_NAME = "YEETingus"
PACKAGE_NAME = "YEETingus.ccx"


class PremiereError(RuntimeError):
    def __init__(self, message: str, kind: str = "PremiereError") -> None:
        super().__init__(message)
        self.kind = kind


class PremiereBridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._commands: queue.Queue[dict] = queue.Queue()
        self._pending: dict[str, threading.Event] = {}
        self._replies: dict[str, dict] = {}
        self.last_seen = 0.0
        self.panel: dict = {}          # what the panel said hello with
        self.on_change = None          # callback(connected: bool), set by the engine

    # ---- what the panel calls ------------------------------------------- #

    def hello(self, info: dict) -> None:
        with self._lock:
            was = self.connected
            self.panel = {k: info.get(k) for k in ("host", "version", "panel")}
            self.last_seen = time.time()
        if not was and self.on_change:
            self.on_change(True)

    def poll(self, wait: float) -> dict | None:
        """Hand the panel the next command, waiting up to `wait` seconds."""
        self._touch()
        try:
            cmd = self._commands.get(timeout=max(0.0, min(wait, 30.0)))
        except queue.Empty:
            self._touch()
            return None
        # A command that already timed out on our side isn't worth running.
        if cmd["id"] not in self._pending:
            return self.poll(wait)
        return cmd

    def reply(self, message: dict) -> bool:
        self._touch()
        rid = str(message.get("id", ""))
        with self._lock:
            event = self._pending.get(rid)
            if event is None:
                return False
            self._replies[rid] = message
        event.set()
        return True

    def _touch(self) -> None:
        with self._lock:
            was = self.connected
            self.last_seen = time.time()
        if not was and self.on_change:
            self.on_change(True)

    # ---- what the engine calls ------------------------------------------ #

    @property
    def connected(self) -> bool:
        return time.time() - self.last_seen < PANEL_TIMEOUT

    def check(self) -> bool:
        """Re-evaluate the connection (for the pill); fires on_change on a drop."""
        now = self.connected
        if not now and self.last_seen and self.on_change:
            self.last_seen = 0.0
            self.on_change(False)
        return now

    def request(self, method: str, params: dict | None = None,
                timeout: float = REQUEST_TIMEOUT) -> dict:
        if not self.connected:
            raise PremiereError(
                "The YEETingus panel isn't open in Premiere. Open it from "
                "Window → UXP Plugins → YEETingus (install it from Settings first).",
                "NoPanel")
        rid = uuid.uuid4().hex
        event = threading.Event()
        with self._lock:
            self._pending[rid] = event
        self._commands.put({"id": rid, "method": method, "params": params or {}})
        try:
            if not event.wait(timeout):
                raise PremiereError("Premiere didn't answer in time.", "Timeout")
            with self._lock:
                message = self._replies.pop(rid)
        finally:
            with self._lock:
                self._pending.pop(rid, None)
        if "error" in message and message["error"]:
            err = message["error"]
            raise PremiereError(str(err.get("message") or err), str(err.get("kind") or "PremiereError"))
        return message.get("result") or {}

    def status(self) -> dict:
        """Project and sequence names from the panel — quick, for the pill."""
        return self.request("status", timeout=10.0)

    def insert(self, path: str, insert_at: str = "playhead", has_video: bool = True) -> dict:
        """Import `path` and place it on the active sequence.

        `has_video` lets the panel tell a stale audio-only project item from
        a genuinely audio-only file. Returns what the panel reports:
        {clipName, sequence, insertedFrame, trackIndex}.
        """
        return self.request("insert", {"path": path, "at": insert_at, "hasVideo": has_video})


# --------------------------------------------------------------------------- #
# Installing the panel
# --------------------------------------------------------------------------- #

def panel_source() -> str | None:
    """The panel folder: beside the frozen service, or in the repo."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "premiere", "panel"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "premiere", "panel"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "premiere", "panel"))
    for c in candidates:
        if os.path.isfile(os.path.join(c, "manifest.json")):
            return c
    return None


def installer_path() -> str | None:
    """Adobe's UnifiedPluginInstallerAgent, where Creative Cloud put it."""
    if sys.platform == "darwin":
        p = ("/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents"
             "/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent")
        return p if os.path.isfile(p) else None
    if sys.platform != "win32":
        return None
    rel = (r"Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI"
           r"\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe")
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base and os.path.isfile(os.path.join(base, rel)):
            return os.path.join(base, rel)
    return None


def build_package(work_dir: str, app_exe: str | None = None) -> str:
    """Zip the panel folder into a .ccx (manifest at the archive root).

    `app_exe` is accepted and ignored: a Launch button was tried and UXP
    refuses both custom URL schemes and executables (see panel/main.js)."""
    src = panel_source()
    if not src:
        raise PremiereError("The panel source isn't shipped with this build.", "Missing")
    os.makedirs(work_dir, exist_ok=True)
    package = os.path.join(work_dir, PACKAGE_NAME)
    tmp = package + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, src))
    os.replace(tmp, package)
    return package


def _run(agent: str, args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run([agent, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", timeout=180,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return proc.returncode == 0, (proc.stdout or "").strip()


def installed_version(agent: str) -> str | None:
    """The version Adobe lists for our panel, or None if it isn't installed."""
    ok, out = _run(agent, ["/list", "all"])
    if not ok:
        return None
    for line in out.splitlines():
        if PLUGIN_NAME in line or PLUGIN_ID in line:
            parts = line.split()
            # The agent's table: name, version, status... — take the first
            # thing that looks like a version.
            for p in parts:
                if p and p[0].isdigit() and "." in p:
                    return p
            return "installed"
    return None


def install(work_dir: str, log, app_exe: str | None = None) -> str:
    """Build the .ccx and hand it to Adobe's installer. Returns the agent's
    own words on success; raises PremiereError with them on refusal."""
    agent = installer_path()
    if not agent:
        raise PremiereError(
            "Adobe's plugin installer wasn't found. It comes with Creative Cloud "
            "desktop 5.5 or newer.", "NoInstaller")
    package = build_package(work_dir, app_exe)
    # Same version already there? The agent keeps the old files, so a reinstall
    # would change nothing. Remove first; a refusal here (nothing installed)
    # is fine.
    if installed_version(agent):
        log("Removing the installed panel first…")
        _run(agent, ["/remove", PLUGIN_NAME])
    log(f"Built {os.path.basename(package)}; asking Adobe's installer…")
    ok, out = _run(agent, ["/install", package])
    if not ok:
        raise PremiereError(out or "Adobe's installer refused without saying why.", "Refused")
    return out


def uninstall(log) -> str:
    agent = installer_path()
    if not agent:
        raise PremiereError("Adobe's plugin installer wasn't found.", "NoInstaller")
    ok, out = _run(agent, ["/remove", PLUGIN_NAME])
    if not ok:
        raise PremiereError(out or "Adobe's installer refused without saying why.", "Refused")
    return out
