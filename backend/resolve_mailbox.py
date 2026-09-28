"""
resolve_mailbox.py — reach Resolve Free through the in-Resolve Lua bridge.

Resolve Free has no external scripting since 19.1, and 21.1 also sandboxes the
Lua it still runs. What is left: a Lua script started from Workspace > Scripts
can keep running, read a file with loadfile, and write Fusion's prefs file. So
resolve/YEETingusBridge.lua runs inside Resolve and this module talks to it:

    we   -> <mailbox>/request.lua   a Lua table literal, renamed into place
    Lua  -> Global.YEETingus.Ack       = id           (Fusion.prefs, on disk)
    Lua  -> Global.YEETingus.Response  = id:hex(json)

The Lua side cannot delete files, so the request is removed here once it is
answered. See RESOLVE-FREE-INSERT.md for the whole design and the traps.

resolve_bridge tries external scripting first and comes here when that fails,
so Studio never touches any of this.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_paths as pp  # noqa: E402

BRIDGE_NAME = "bridge.lua"
REQUEST_NAME = "request.lua"

# Without an ack within this long, nothing is running the loop.
ACK_TIMEOUT = 2.5
# After the ack: a big import can take a while; a modal dialog in Resolve
# blocks the loop entirely.
ANSWER_TIMEOUT = 90.0
POLL = 0.05

HOW_TO_START = ("On Resolve Free, click Workspace > Scripts > YEETingus once after "
                "Resolve starts; it keeps a small bridge running until you quit Resolve.")


class MailboxError(RuntimeError):
    """A bridge problem, with a message fit for the UI log."""


class BridgeNotRunning(MailboxError):
    """Nothing inside Resolve answered: the Scripts entry wasn't clicked."""


# ---------------------------------------------------------------- places --

def bridge_dir() -> str:
    """Our folder: the bridge script and the mailbox. User-private."""
    return os.path.join(pp.app_data_dir(), "resolve-bridge")


def bridge_template() -> str | None:
    """resolve/YEETingusBridge.lua — beside the frozen service, or in the repo."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "resolve",
                                       "YEETingusBridge.lua"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "resolve", "YEETingusBridge.lua"))
    return next((c for c in candidates if os.path.isfile(c)), None)


def prefs_candidates() -> list[str]:
    """Every Fusion.prefs of Resolve's per-user Fusion folder (one per
    profile). The per-user Scripts/Utility folder sits in the same Fusion
    folder, so it is derived from that."""
    scripts = pp.scripts_dirs()
    if not scripts:
        return []
    fusion = os.path.dirname(os.path.dirname(scripts[0]))
    return glob.glob(os.path.join(fusion, "Profiles", "*", "Fusion.prefs"))


def prefs_path() -> str | None:
    """The Fusion.prefs Resolve writes to: the most recently written one."""
    files = prefs_candidates()
    if not files:
        return None
    return max(files, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)


def lua_path(path: str) -> str:
    """`path` as the bridge should be given it. Resolve's Lua on Windows is
    narrow-path, so a name with Polish letters goes as its 8.3 short form
    when the volume has one."""
    path = os.path.abspath(path)
    if path.isascii() or not pp.WINDOWS:
        return path
    import resolve_menu                 # imports this module; import late
    return resolve_menu._ascii_path(path)


# ------------------------------------------------------------- install --

_prepared = False


def ensure_bridge() -> str:
    """Write the current bridge script and clear a leftover request. Once per
    process; the launcher loadfile()s the script on every menu click, so an
    updated app updates the bridge without reinstalling the menu entry."""
    global _prepared
    folder = bridge_dir()
    if _prepared:
        return folder
    os.makedirs(folder, exist_ok=True)
    src = bridge_template()
    if src:
        with open(src, "rb") as fh:
            new = fh.read()
        dest = os.path.join(folder, BRIDGE_NAME)
        try:
            with open(dest, "rb") as fh:
                same = fh.read() == new
        except OSError:
            same = False
        if not same:
            tmp = dest + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(new)
            _replace(tmp, dest)
    _remove(os.path.join(folder, REQUEST_NAME))
    _prepared = True
    return folder


# ------------------------------------------------------------- encoding --

def lua_string(s: str) -> str:
    """`s` as a Lua long-bracket string, with a level its text can't close."""
    level = 0
    while f"]{'=' * level}]" in s + "]":
        level += 1
    eq = "=" * level
    # A newline right after the opening bracket is dropped by Lua.
    lead = "\n" if s.startswith(("\n", "\r")) else ""
    return f"[{eq}[{lead}{s}]{eq}]"


def lua_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if v == v and v not in (float("inf"), float("-inf")) else "nil"
    if isinstance(v, str):
        return lua_string(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {lua_value(x)}" for k, x in v.items()
                                if x is not None and re.fullmatch(r"[A-Za-z_]\w*", k)) + " }"
    raise TypeError(f"can't send {type(v).__name__} to Lua")


def render_request(req_id: str, cmd: str, args: dict, created: int | None = None) -> str:
    body = {"id": req_id, "cmd": cmd, "created": int(created or time.time()), "args": args}
    return "return " + lua_value(body) + "\n"


def parse_prefs(text: str) -> dict:
    """Our keys from Fusion.prefs: the flat `YEETingus = { ... }` table under
    Global. Values are ids and hex, so no escapes to worry about."""
    m = re.search(r"\bYEETingus\s*=\s*\{([^{}]*)\}", text)
    if not m:
        return {}
    return dict(re.findall(r'\b(\w+)\s*=\s*"([^"]*)"', m.group(1)))


def decode_response(value: str, req_id: str) -> dict | None:
    """The JSON body of `value` if it answers `req_id`, else None."""
    head, sep, payload = value.partition(":")
    if not sep or head != req_id:
        return None
    raw = bytes.fromhex(payload)
    for enc in ("utf-8", "mbcs" if pp.WINDOWS else "latin-1", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, LookupError):
            continue
    return json.loads(raw.decode("latin-1"))


# ------------------------------------------------------------- the call --

def _replace(src: str, dest: str) -> None:
    """os.replace, retried: Resolve or an antivirus may hold dest a moment."""
    for _ in range(20):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(src, dest)


def _remove(path: str) -> None:
    for _ in range(20):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.05)


class _Prefs:
    """Fusion.prefs, re-read only when it changes."""

    def __init__(self):
        self.path = prefs_path()
        self.stamp = None
        self.keys: dict = {}

    def read(self) -> dict:
        if not self.path:
            self.path = prefs_path()
            if not self.path:
                return {}
        try:
            st = os.stat(self.path)
            stamp = (st.st_mtime_ns, st.st_size)
            if stamp != self.stamp:
                with open(self.path, "rb") as fh:
                    self.keys = parse_prefs(fh.read().decode("latin-1"))
                self.stamp = stamp
        except OSError:
            pass
        return self.keys


def might_be_running() -> bool:
    """Cheap pre-check before waiting for an ack: the loop's Owner key has
    reached Fusion.prefs at least once, and wasn't cleared by a Stop. A loop
    that was never started leaves no trace, so this fails fast."""
    return bool(_Prefs().read().get("Owner"))


def call(cmd: str, args: dict | None = None, timeout: float = ANSWER_TIMEOUT) -> dict:
    """Send one request to the bridge and return its result, or raise."""
    folder = ensure_bridge()
    prefs = _Prefs()
    if not prefs.path:
        raise BridgeNotRunning("Couldn't find Resolve's Fusion settings. " + HOW_TO_START)

    req_id = uuid.uuid4().hex
    request = os.path.join(folder, REQUEST_NAME)
    tmp = request + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_request(req_id, cmd, args or {}))
    _replace(tmp, request)

    started = time.monotonic()
    acked = False
    try:
        while True:
            keys = prefs.read()
            answer = keys.get("Response")
            if answer:
                body = decode_response(answer, req_id)
                if body is not None:
                    if body.get("ok"):
                        return body.get("result") or {}
                    raise MailboxError(body.get("error") or "Resolve bridge failed.")
            if keys.get("Ack") == req_id:
                acked = True
            waited = time.monotonic() - started
            if not acked and waited > ACK_TIMEOUT:
                raise BridgeNotRunning("Resolve isn't answering. " + HOW_TO_START)
            if waited > timeout:
                raise MailboxError("Resolve took the request but didn't finish it. "
                                   "Is a dialog open in Resolve?")
            time.sleep(POLL)
    finally:
        _remove(request)


def stop() -> None:
    """Ask a running bridge to end (it also ends when Resolve quits)."""
    try:
        call("Stop", timeout=5)
    except MailboxError:
        pass
