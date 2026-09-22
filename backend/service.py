#!/usr/bin/env python3
"""
service.py — the engine over localhost HTTP, for front ends that aren't Python.

    py -3.13 service.py [--port 47591] [--token SECRET]

One Engine, one process, any number of clients: a Tauri window, a Premiere
UXP panel, curl. Everything the Tk window can do is a request here, and
everything the engine says comes back on one Server-Sent Events stream.

Bound to 127.0.0.1 only. With --token, every request must carry it, as
`Authorization: Bearer <token>` or `?token=<token>` (the latter for
EventSource, which can't set headers). On start the port and token are written
to <app data>/service.json so a client on this machine can find them.

Routes (all JSON; POST bodies are JSON objects):

    GET  /api/health                 {ok, app, version, pid}
    GET  /api/state                  Engine.state()
    GET  /api/log[?since=SEQ]        {events: [log events after SEQ]}
    GET  /api/events[?since=SEQ]     SSE stream — every engine event, as
                                     `id: seq` / `event: kind` / `data: json`;
                                     ?since (or Last-Event-ID) first replays the
                                     log history after that point
    POST /api/jobs                   {url, in, out, quality|max_height,
                                      insert_at, insert} -> {started}
    POST /api/jobs/cancel            -> {cancelled}
    POST /api/meta                   {url} -> video metadata (blocks; 409 while
                                     a job is running)
    GET  /api/resolve                {status, env}
    POST /api/resolve/refresh        -> {connected, status}   (blocks)
    POST /api/tools/update-ytdlp     -> {started}
    POST /api/tools/install-ffmpeg   -> {started}
    POST /api/tools/install-js       -> {started}
    POST /api/settings               {download_dir?, default_length?, editor?} -> settings
    POST /api/log                    {text, tag?} -> a line in the shared log,
                                     for things the front end itself did
    POST /api/open-folder            opens the clips folder in the file manager
    GET  /api/resolve/menu           the Scripts-menu launcher: {installed, path, stale, …}
    POST /api/resolve/menu/install   -> {started}  writes the launcher (restart Resolve after)
    GET  /api/premiere               {connected, panel, installer, panel_source}
    POST /api/premiere/install       -> {started}  builds the .ccx, runs Adobe's installer
    POST /api/premiere/hello         (panel) {host, version} -> {ok}
    GET  /api/premiere/poll?wait=25  (panel) long-poll: {cmd: {id, method, params} | null}
    POST /api/premiere/reply         (panel) {id, result | error} -> {ok}

The three panel routes are also accepted without the token when the request
comes from a native origin (no Origin header, or file://) — the UXP panel can't
know a per-launch token. A browser page always sends an http(s) Origin and is
still refused. Same reasoning as Sherlock's bridge.
    GET  /api/clips                  {clips: [...]} every finished clip on disk
    POST /api/update/check           -> {started}   look for a newer release now
    POST /api/queue                  {url, in, out, quality, title?, thumbnail?} -> {item}
    POST /api/queue/remove           {id} -> {removed}   stops it if running
    POST /api/queue/clear            drops finished/failed/stopped items
    POST /api/clips/insert           {path | paths, insert_at} -> {started}
    POST /api/clips/delete           {path} -> {deleted}
    POST /api/clips/open             {path} opens that clip's folder
    POST /api/clips/play             {path} opens the clip in the default player
    POST /api/clips/source           {path} opens the video's page in the browser
    POST /api/quit                   stops the service

Timestamps ("in"/"out") are what the user typed — SS, MM:SS or HH:MM:SS — and
are validated by the engine like the window's fields. "quality" is a label from
state.quality_options; "max_height" an int or null overrides it.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import platform_paths            # noqa: E402
import resolve_bridge            # noqa: E402
from engine import QUALITY_OPTIONS, Engine  # noqa: E402
from version import APP_NAME, __version__   # noqa: E402

DEFAULT_PORT = 47591
# The Premiere panel can't be told the port, so it dials these in turn (the
# list is mirrored in premiere/panel/main.js). `--port 0` tries them first.
PANEL_PORTS = (47591, 47592, 47593, 47594, 47595)
INFO_FILE = os.path.join(platform_paths.app_data_dir(), "service.json")

# A comment line on the SSE stream every so often, so a proxy or a sleepy
# socket doesn't close an idle connection.
SSE_KEEPALIVE = 15.0


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def open_with_default_app(path: str) -> None:
    """Hand a file to whatever the OS opens it with — a clip to the default player."""
    if sys.platform == "win32" and hasattr(os, "startfile"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32" and hasattr(os, "startfile"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# What the Premiere panel calls. UXP sends no Origin and can't be handed the
# token, so these three (and only these) are let through without it.
PANEL_ROUTES = frozenset({"/api/premiere/hello", "/api/premiere/poll", "/api/premiere/reply"})


class Handler(BaseHTTPRequestHandler):
    server: "Service"
    protocol_version = "HTTP/1.1"

    # ---- plumbing ---------------------------------------------------------- #

    def log_message(self, fmt: str, *args) -> None:
        if self.server.verbose:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        # The clients are a Tauri webview (tauri://localhost, http://tauri.localhost)
        # and a UXP panel (a null/plugin origin), neither a fixed http origin, so
        # the origin check is "*" and the token is what actually gates access.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> None:
        """Read the request body once, before auth and routing. A route that
        never looked at its body used to leave it in the socket, where it
        became the start of the next request on the same keep-alive
        connection ("501 Unsupported method ('{}GET')")."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        self._body = self.rfile.read(length) if length > 0 else b""
        if length < 0 or "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self.close_connection = True

    def _read_json(self) -> dict:
        raw = getattr(self, "_body", b"")
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "body must be JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "body must be a JSON object")
        return data

    def _native_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin.startswith("file://")

    def _authorised(self, query: dict, path: str = "") -> bool:
        token = self.server.token
        if not token:
            return True
        if path in PANEL_ROUTES and self._native_origin():
            return True
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip(), token):
            return True
        given = query.get("token", [None])[0]
        return given is not None and hmac.compare_digest(given, token)

    def do_OPTIONS(self) -> None:  # noqa: N802 — http.server's naming
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        try:
            self._read_body()
            if not self._authorised(query, parts.path):
                raise ApiError(401, "missing or wrong token")
            route = self.ROUTES.get((method, parts.path))
            if route is None:
                raise ApiError(404, f"no such route: {method} {parts.path}")
            route(self, query)
        except ApiError as e:
            self._send_json({"error": str(e)}, e.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass    # client went away; nothing to tell it
        except Exception as e:  # noqa: BLE001 — surface, don't crash the thread
            self._send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ---- routes ------------------------------------------------------------ #

    @property
    def engine(self) -> Engine:
        return self.server.engine

    def r_health(self, _q) -> None:
        self._send_json({"ok": True, "app": APP_NAME, "version": __version__,
                         "pid": os.getpid()})

    def r_state(self, _q) -> None:
        self._send_json(self.engine.state())

    def r_log_since(self, q) -> None:
        try:
            since = int(q.get("since", ["0"])[0] or 0)
        except ValueError:
            raise ApiError(400, "since must be an integer")
        self._send_json({"events": [e for e in list(self.engine.history)
                                    if e["seq"] > since]})

    def r_events(self, q) -> None:
        """SSE: replay the log after `since`, then everything live."""
        since = q.get("since", [None])[0] or self.headers.get("Last-Event-ID") or "0"
        try:
            since = int(since)
        except ValueError:
            since = 0

        inbox: queue.Queue[dict] = queue.Queue()
        # Subscribe before replaying, so nothing slips between the two.
        self.engine.subscribe(inbox.put)
        try:
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            seen = since
            for ev in list(self.engine.history):
                if ev["seq"] > since:
                    self._sse(ev)
                    seen = ev["seq"]
            # A snapshot right after the backlog, so a client can draw itself
            # from the stream alone.
            self._sse({"kind": "state", "seq": seen, "t": time.time(),
                       **self.engine.state()})

            while not self.server.stopping:
                try:
                    ev = inbox.get(timeout=SSE_KEEPALIVE)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                if ev["seq"] <= seen:
                    continue          # already replayed from history
                self._sse(ev)
                seen = ev["seq"]
        finally:
            self.engine.unsubscribe(inbox.put)

    def _sse(self, ev: dict) -> None:
        data = json.dumps(ev)
        self.wfile.write(f"id: {ev['seq']}\nevent: {ev['kind']}\ndata: {data}\n\n"
                         .encode("utf-8"))
        self.wfile.flush()

    def r_jobs(self, _q) -> None:
        body = self._read_json()
        if "max_height" in body:
            max_height = body["max_height"]
            if max_height is not None and not isinstance(max_height, int):
                raise ApiError(400, "max_height must be an integer or null")
        else:
            label = body.get("quality", "Best available")
            if label not in QUALITY_OPTIONS:
                raise ApiError(400, f"unknown quality '{label}'")
            max_height = QUALITY_OPTIONS[label]
        started = self.engine.start_job(
            str(body.get("url", "")),
            str(body.get("in", "00:00")), str(body.get("out", "00:00")),
            max_height, str(body.get("insert_at", "playhead")),
            insert=bool(body.get("insert", True)))
        # A refusal has already been logged (and streamed) by the engine; the
        # status code just says so without the client parsing the log.
        self._send_json({"started": started}, 200 if started else 409)

    def r_update_check(self, _q) -> None:
        self._send_json({"started": self.engine.start_update_check()})

    def r_queue_add(self, _q) -> None:
        body = self._read_json()
        label = body.get("quality", "Best available")
        if label not in QUALITY_OPTIONS:
            raise ApiError(400, f"unknown quality '{label}'")
        thumb = body.get("thumbnail")
        item = self.engine.queue_add(
            str(body.get("url", "")),
            str(body.get("in", "00:00")), str(body.get("out", "00:00")),
            QUALITY_OPTIONS[label], str(body.get("title") or ""),
            thumb if isinstance(thumb, str) else None)
        self._send_json({"item": item}, 200 if item else 409)

    def r_queue_remove(self, _q) -> None:
        body = self._read_json()
        self._send_json({"removed": self.engine.queue_remove(str(body.get("id", "")))})

    def r_queue_clear(self, _q) -> None:
        self.engine.queue_clear()
        self._send_json({"ok": True})

    def r_cancel(self, _q) -> None:
        self._send_json({"cancelled": self.engine.cancel()})

    def r_meta(self, _q) -> None:
        body = self._read_json()
        url = str(body.get("url", "")).strip()
        if not url:
            raise ApiError(400, "url is required")
        if not self.engine.ytdlp_cmd:
            raise ApiError(503, "yt-dlp isn't available yet")
        # probe_metadata shares the engine's active-process slot with a running
        # job; letting them overlap would let STOP kill the wrong process.
        if self.engine.busy:
            raise ApiError(409, "a job is running")
        self._send_json(self.engine.probe_metadata(url, quiet=True))

    def r_resolve(self, _q) -> None:
        self._send_json({"status": self.engine.resolve_state,
                         "env": resolve_bridge.describe_env()})

    def r_resolve_refresh(self, _q) -> None:
        connected = self.engine.check_connection()
        self._send_json({"connected": connected,
                         "status": self.engine.resolve_state})

    def r_update_ytdlp(self, _q) -> None:
        self._send_json({"started": self.engine.start_update_ytdlp()})

    def r_install_ffmpeg(self, _q) -> None:
        self._send_json({"started": self.engine.start_install_ffmpeg()})

    def r_install_js(self, _q) -> None:
        self._send_json({"started": self.engine.start_install_js()})

    def r_settings(self, _q) -> None:
        body = self._read_json()
        try:
            self.engine.update_settings(
                download_dir=body.get("download_dir"),
                default_length=body.get("default_length"),
                editor=body.get("editor"),
                onboarded=body.get("onboarded"),
                retime=body.get("retime"),
                conform=body.get("conform"),
                check_updates=body.get("check_updates"))
        except ValueError as e:
            raise ApiError(400, str(e))
        except OSError as e:
            raise ApiError(500, f"couldn't save settings: {e}")
        self._send_json(self.engine.state()["settings"])

    def r_log(self, _q) -> None:
        body = self._read_json()
        text = str(body.get("text", "")).strip()
        if not text:
            raise ApiError(400, "text is required")
        tag = body.get("tag")
        self.engine.log(text, tag if isinstance(tag, str) else None)
        self._send_json({"ok": True})

    def r_open_folder(self, _q) -> None:
        try:
            open_folder(self.engine.download_dir)
        except OSError as e:
            raise ApiError(500, str(e))
        self._send_json({"opened": self.engine.download_dir})

    def r_clips(self, _q) -> None:
        self._send_json({"clips": self.engine.list_clips()})

    def _clip_path(self) -> str:
        body = self._read_json()
        path = str(body.get("path", "")).strip()
        if not path:
            raise ApiError(400, "path is required")
        return path

    def r_clips_insert(self, _q) -> None:
        body = self._read_json()
        raw = body.get("paths")
        if not isinstance(raw, list):
            raw = [body.get("path", "")]
        paths = [p.strip() for p in raw if isinstance(p, str) and p.strip()]
        if not paths:
            raise ApiError(400, "path is required")
        started = self.engine.start_insert(paths, str(body.get("insert_at", "playhead")))
        self._send_json({"started": started}, 200 if started else 409)

    def r_clips_delete(self, _q) -> None:
        deleted = self.engine.delete_clip(self._clip_path())
        self._send_json({"deleted": deleted}, 200 if deleted else 409)

    def r_clips_open(self, _q) -> None:
        folder = self.engine.clip_folder(self._clip_path())
        if folder is None:
            raise ApiError(400, "not a clip in the clips folder")
        try:
            open_folder(folder)
        except OSError as e:
            raise ApiError(500, str(e))
        self._send_json({"opened": folder})

    def r_clips_play(self, _q) -> None:
        path = self.engine.clip_file(self._clip_path())
        if path is None:
            raise ApiError(400, "not a clip in the clips folder")
        try:
            open_with_default_app(path)
        except OSError as e:
            raise ApiError(500, str(e))
        self._send_json({"opened": path})

    def r_clips_source(self, _q) -> None:
        url = self.engine.clip_source_url(self._clip_path())
        if not url:
            raise ApiError(404, "no source link is known for that clip")
        if urlsplit(url).scheme not in ("http", "https"):
            raise ApiError(400, "the clip's source isn't a web link")
        import webbrowser
        if not webbrowser.open(url):
            raise ApiError(500, "couldn't open a browser")
        self._send_json({"opened": url})

    # ---- Premiere -------------------------------------------------------- #

    def r_resolve_menu(self, _q) -> None:
        self._send_json(self.engine.resolve_menu_info())

    def r_resolve_menu_install(self, _q) -> None:
        self._send_json({"started": self.engine.start_install_resolve_menu()})

    def r_premiere(self, _q) -> None:
        self._send_json(self.engine.premiere_info())

    def r_premiere_install(self, _q) -> None:
        self._send_json({"started": self.engine.start_install_premiere_panel()})

    def r_premiere_probe(self, _q) -> None:
        """Ask the panel what Premiere holds for a file (diagnostics)."""
        self._send_json(self.engine.premiere.request("probe", {"path": self._clip_path()}, timeout=30))

    def r_premiere_hello(self, _q) -> None:
        self.engine.premiere.hello(self._read_json())
        self._send_json({"ok": True, "app": APP_NAME, "version": __version__})

    def r_premiere_poll(self, q) -> None:
        try:
            wait = float(q.get("wait", ["25"])[0])
        except ValueError:
            wait = 25.0
        self._send_json({"cmd": self.engine.premiere.poll(wait)})

    def r_premiere_reply(self, _q) -> None:
        self._send_json({"ok": self.engine.premiere.reply(self._read_json())})

    def r_quit(self, _q) -> None:
        self._send_json({"stopping": True})
        self.server.stop_soon()

    ROUTES = {
        ("GET", "/api/health"): r_health,
        ("GET", "/api/state"): r_state,
        ("GET", "/api/log"): r_log_since,
        ("GET", "/api/events"): r_events,
        ("POST", "/api/jobs"): r_jobs,
        ("POST", "/api/jobs/cancel"): r_cancel,
        ("POST", "/api/meta"): r_meta,
        ("GET", "/api/resolve"): r_resolve,
        ("POST", "/api/resolve/refresh"): r_resolve_refresh,
        ("POST", "/api/tools/update-ytdlp"): r_update_ytdlp,
        ("POST", "/api/tools/install-ffmpeg"): r_install_ffmpeg,
        ("POST", "/api/tools/install-js"): r_install_js,
        ("POST", "/api/settings"): r_settings,
        ("POST", "/api/log"): r_log,
        ("POST", "/api/open-folder"): r_open_folder,
        ("GET", "/api/clips"): r_clips,
        ("POST", "/api/update/check"): r_update_check,
        ("POST", "/api/queue"): r_queue_add,
        ("POST", "/api/queue/remove"): r_queue_remove,
        ("POST", "/api/queue/clear"): r_queue_clear,
        ("POST", "/api/clips/insert"): r_clips_insert,
        ("POST", "/api/clips/delete"): r_clips_delete,
        ("POST", "/api/clips/open"): r_clips_open,
        ("POST", "/api/clips/play"): r_clips_play,
        ("POST", "/api/clips/source"): r_clips_source,
        ("GET", "/api/resolve/menu"): r_resolve_menu,
        ("POST", "/api/resolve/menu/install"): r_resolve_menu_install,
        ("GET", "/api/premiere"): r_premiere,
        ("POST", "/api/premiere/install"): r_premiere_install,
        ("POST", "/api/premiere/probe"): r_premiere_probe,
        ("POST", "/api/premiere/hello"): r_premiere_hello,
        ("GET", "/api/premiere/poll"): r_premiere_poll,
        ("POST", "/api/premiere/reply"): r_premiere_reply,
        ("POST", "/api/quit"): r_quit,
    }


class Service(ThreadingHTTPServer):
    daemon_threads = True       # SSE handlers must not keep the process alive
    address_family = socket.AF_INET

    # On Windows SO_REUSEADDR lets a second server bind a port that is already
    # listened on, which would defeat the port-list fallback above. POSIX only
    # uses it to skip TIME_WAIT, which is what we want.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, host: str, port: int, engine: Engine,
                 token: str | None, verbose: bool = False) -> None:
        super().__init__((host, port), Handler)
        self.engine = engine
        self.token = token
        self.verbose = verbose
        self.stopping = False

    siblings: list = []         # the other-family twin, stopped together

    def handle_error(self, request, client_address) -> None:
        """A client that hangs up mid-request (the window closing, a panel
        poll cut short) is not an error worth a traceback on stderr."""
        import sys as _sys
        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def stop_soon(self) -> None:
        for server in (self, *self.siblings):
            server.stopping = True
            threading.Thread(target=server.shutdown, daemon=True).start()


class Service6(Service):
    """The same service on IPv6 loopback. Windows resolves "localhost" to ::1
    first, and the Premiere panel dials by name, so a service on 127.0.0.1
    alone leaves its first attempt hanging against a port nothing holds."""
    address_family = socket.AF_INET6

def write_info(port: int, token: str | None) -> str:
    """Tell clients on this machine where we are."""
    os.makedirs(os.path.dirname(INFO_FILE), exist_ok=True)
    info = {"port": port, "token": token, "pid": os.getpid(),
            "version": __version__}
    tmp = INFO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
    os.replace(tmp, INFO_FILE)
    return INFO_FILE


def remove_info() -> None:
    try:
        with open(INFO_FILE, "r", encoding="utf-8") as fh:
            if json.load(fh).get("pid") != os.getpid():
                return          # another instance's file; leave it
        os.remove(INFO_FILE)
    except (OSError, ValueError):
        pass


def watch_parent(pid: int, on_gone) -> None:
    """Call `on_gone` once process `pid` exits. The app stops this service
    on a normal close, but a force-kill (Task Manager, a crash) skips that
    and used to leave the service running with nobody to talk to."""
    def wait() -> None:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k32.WaitForSingleObject.restype = wintypes.DWORD
            k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)
            SYNCHRONIZE, ACCESS_DENIED, WAIT_FAILED = 0x00100000, 5, 0xFFFFFFFF
            handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
            if not handle:
                if ctypes.get_last_error() == ACCESS_DENIED:
                    return          # alive but not ours to watch; don't quit
                on_gone()           # already gone
                return
            result = k32.WaitForSingleObject(handle, 0xFFFFFFFF)
            k32.CloseHandle(handle)
            if result == WAIT_FAILED:
                return              # can't tell; staying up beats quitting wrongly
        else:
            import time
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                except PermissionError:
                    pass
                time.sleep(2)
        on_gone()
    threading.Thread(target=wait, daemon=True, name="parent-watch").start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} local service")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"TCP port (default {DEFAULT_PORT}; 0 picks a free one)")
    ap.add_argument("--token", default=None,
                    help="require this token on every request")
    ap.add_argument("--verbose", action="store_true", help="log each request")
    ap.add_argument("--no-boot", action="store_true",
                    help="don't resolve tools at start (tests)")
    ap.add_argument("--app-exe", default=None,
                    help="the desktop app that owns this service; baked into "
                         "the Premiere panel so its Launch button can start it")
    ap.add_argument("--parent-pid", type=int, default=None,
                    help="exit when this process does (the app that started us)")
    args = ap.parse_args(argv)

    engine = Engine()
    engine.app_exe = args.app_exe
    if args.verbose:
        engine.subscribe(lambda ev: ev["kind"] == "log" and
                         sys.stderr.write(ev["text"] + "\n"))
    server = None
    ports = list(PANEL_PORTS) + [0] if args.port == 0 else [args.port]
    for candidate in ports:
        try:
            server = Service(args.host, candidate, engine, args.token, args.verbose)
            break
        except OSError:
            continue        # held by another YEETingus, or something else
    if server is None:
        print(json.dumps({"error": "no free port"}), flush=True)
        return 1
    port = server.server_address[1]
    # A twin on ::1 for clients that dial "localhost" (see Service6). Best
    # effort: a machine without IPv6 loopback just doesn't get one.
    twin = None
    if args.host == "127.0.0.1":
        try:
            twin = Service6("::1", port, engine, args.token, args.verbose)
            server.siblings = [twin]
            twin.siblings = [server]
            threading.Thread(target=twin.serve_forever, daemon=True).start()
        except OSError:
            twin = None
    info = write_info(port, args.token)
    # One line on stdout, so a parent process can read where we are without
    # racing the info file.
    print(json.dumps({"port": port, "info": info}), flush=True)

    if args.parent_pid:
        watch_parent(args.parent_pid, server.stop_soon)
    if not args.no_boot:
        engine.start_boot()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping = True
        server.server_close()
        if twin is not None:
            twin.stopping = True
            twin.server_close()
        remove_info()
    return 0


if __name__ == "__main__":
    sys.exit(main())
