"""Resolve Free insert bridge: the mailbox protocol, the fallback in
resolve_bridge, and the real Lua bridge run end to end.

The end-to-end tests run resolve/YEETingus.lua.in and YEETingusBridge.lua
under Resolve's own fuscript (LuaJIT) against a mock Resolve, in a copy of the
Free 21.1 sandbox (tests/lua/bridge_harness.lua). They are skipped when
fuscript isn't installed. No real Resolve is touched.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import resolve_bridge  # noqa: E402
import resolve_mailbox as mb  # noqa: E402

HARNESS = os.path.join(HERE, "lua", "bridge_harness.lua")
TEMPLATE = os.path.join(ROOT, "resolve", "YEETingus.lua.in")

_FUSCRIPT = [
    os.environ.get("YEET_FUSCRIPT", ""),
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fuscript.exe",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript",
    "/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fuscript",
    "/opt/resolve/libs/Fusion/fuscript",
]
FUSCRIPT = next((p for p in _FUSCRIPT if p and os.path.isfile(p)), None)


def _prefs_text(**keys) -> str:
    body = "".join(f'\t\t\t{k} = "{v}",\r\n' for k, v in keys.items())
    return ("{\r\n\tComp = {\r\n\t\tAutoSave = {\r\n\t\t\tEnabled = true\r\n\t\t},\r\n\t},\r\n"
            "\tGlobal = {\r\n\t\tYEETingus = {\r\n" + body + "\t\t},\r\n\t},\r\n}")


class EncodingTests(unittest.TestCase):
    def test_long_string_level(self):
        self.assertEqual(mb.lua_string("C:\\clips\\a.mp4"), "[[C:\\clips\\a.mp4]]")
        self.assertEqual(mb.lua_string("a]]b"), "[=[a]]b]=]")
        self.assertEqual(mb.lua_string("a]=]b]]"), "[==[a]=]b]]]==]")
        # Ends in "]": "[[x]]]" would close one early.
        self.assertEqual(mb.lua_string("x]"), "[=[x]]=]")

    def test_request_drops_none_and_keeps_types(self):
        text = mb.render_request("abc", "ImportAndInsert",
                                 {"path": "C:\\a b\\Piątek.mp4", "trackIndex": None,
                                  "endFrame": 120, "retimeName": "blend", "x": True},
                                 created=1000)
        self.assertTrue(text.startswith("return { id = [[abc]], cmd = [[ImportAndInsert]]"))
        self.assertIn("created = 1000", text)
        self.assertIn("path = [[C:\\a b\\Piątek.mp4]]", text)
        self.assertIn("endFrame = 120", text)
        self.assertIn("x = true", text)
        self.assertNotIn("trackIndex", text)

    def test_parse_prefs(self):
        keys = mb.parse_prefs(_prefs_text(Owner="tok", Ack="abc", Response="abc:7b7d"))
        self.assertEqual(keys, {"Owner": "tok", "Ack": "abc", "Response": "abc:7b7d"})
        self.assertEqual(mb.parse_prefs("{ Global = { Paths = { } } }"), {})

    def test_decode_response(self):
        body = '{"ok":true,"result":{"bin":"Piątek"}}'.encode("utf-8").hex()
        self.assertEqual(mb.decode_response("abc:" + body, "abc"),
                         {"ok": True, "result": {"bin": "Piątek"}})
        self.assertIsNone(mb.decode_response("old:" + body, "abc"))
        self.assertIsNone(mb.decode_response("", "abc"))


class _TempBridge(unittest.TestCase):
    """A private bridge folder and Fusion.prefs for each test."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.dir = os.path.join(self.root, "resolve-bridge")
        self.prefs = os.path.join(self.root, "Fusion.prefs")
        with open(self.prefs, "w", encoding="ascii", newline="") as fh:
            fh.write(_prefs_text())
        patches = [
            mock.patch.object(mb, "bridge_dir", lambda: self.dir),
            mock.patch.object(mb, "prefs_path", lambda: self.prefs),
            mock.patch.object(mb, "_prepared", False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.root, True)


class CallTests(_TempBridge):
    def _fake_lua(self, answer):
        """Plays the Lua side: waits for a request, acks, answers."""
        request = os.path.join(self.dir, mb.REQUEST_NAME)

        def run():
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    with open(request, encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    time.sleep(0.02)
                    continue
                req_id = re.search(r"id = \[=*\[(\w+)\]", text).group(1)
                with open(self.prefs, "w", encoding="ascii", newline="") as fh:
                    fh.write(_prefs_text(Owner="t", Ack=req_id,
                                         Response=req_id + ":" + answer.encode().hex()))
                return
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def test_round_trip(self):
        self._fake_lua('{"ok":true,"result":{"fps":24}}')
        self.assertEqual(mb.call("GetTimelineInfo"), {"fps": 24})
        self.assertFalse(os.path.exists(os.path.join(self.dir, mb.REQUEST_NAME)))

    def test_error_answer(self):
        self._fake_lua('{"ok":false,"error":"No project is open in Resolve."}')
        with self.assertRaisesRegex(mb.MailboxError, "No project"):
            mb.call("GetTimelineInfo")

    def test_no_ack_means_not_running(self):
        with mock.patch.object(mb, "ACK_TIMEOUT", 0.3):
            with self.assertRaisesRegex(mb.BridgeNotRunning, "Workspace > Scripts"):
                mb.call("Ping")
        self.assertFalse(os.path.exists(os.path.join(self.dir, mb.REQUEST_NAME)))

    def test_owner_decides_whether_to_wait(self):
        self.assertFalse(mb.might_be_running())
        with open(self.prefs, "w", encoding="ascii", newline="") as fh:
            fh.write(_prefs_text(Owner="tok"))
        self.assertTrue(mb.might_be_running())

    def test_leftover_request_is_cleared(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, mb.REQUEST_NAME), "w") as fh:
            fh.write("return {}")
        mb.ensure_bridge()
        self.assertFalse(os.path.exists(os.path.join(self.dir, mb.REQUEST_NAME)))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, mb.BRIDGE_NAME)))


class FallbackTests(unittest.TestCase):
    """resolve_bridge uses the mailbox only when external scripting fails."""

    def setUp(self):
        p = mock.patch.object(resolve_bridge, "connect",
                              side_effect=resolve_bridge.ResolveError("Resolve isn't responding."))
        p.start()
        self.addCleanup(p.stop)

    def test_not_running_says_how_to_fix_both(self):
        with mock.patch.object(mb, "might_be_running", return_value=False):
            with self.assertRaises(resolve_bridge.ResolveError) as cm:
                resolve_bridge.get_timeline_info()
        msg = str(cm.exception)
        self.assertIn("Workspace > Scripts > YEETingus", msg)
        # engine.check_connection reads these words as "nothing open".
        self.assertNotIn("timeline", msg.lower())
        self.assertNotIn("project", msg.lower())

    def test_timeline_info_via_bridge(self):
        answer = {"project": "Friday video", "timeline": "Timeline 1", "fps": 24,
                  "currentTimecode": "01:00:10:00", "startFrame": 86400}
        with mock.patch.object(mb, "might_be_running", return_value=True), \
                mock.patch.object(mb, "call", return_value=dict(answer)) as call:
            info = resolve_bridge.get_timeline_info()
        call.assert_called_once_with("GetTimelineInfo", None)
        self.assertEqual(info["currentFrame"], 86640)
        self.assertIsNone(info["playbackFps"])

    def test_insert_via_bridge(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            path = fh.name
        self.addCleanup(os.remove, path)
        with mock.patch.object(mb, "might_be_running", return_value=True), \
                mock.patch.object(mb, "call", return_value={"clipName": "a", "trackIndex": 2,
                                                            "newTrack": True}) as call:
            res = resolve_bridge.import_and_insert(path, retime="optical", bin_name="Friday")
        cmd, args = call.call_args[0]
        self.assertEqual(cmd, "ImportAndInsert")
        self.assertEqual(args["retime"], resolve_bridge.RETIME_PROCESSES["optical"])
        self.assertEqual(args["bin"], "Friday")
        self.assertIsNone(args["trackIndex"])
        self.assertEqual(res["trackIndex"], 2)
        self.assertTrue(res["newTrack"])
        self.assertIsNone(res["retimed"])

    def test_bridge_errors_become_resolve_errors(self):
        with mock.patch.object(mb, "might_be_running", return_value=True), \
                mock.patch.object(mb, "call", side_effect=mb.MailboxError("No timeline is open.")):
            with self.assertRaisesRegex(resolve_bridge.ResolveError, "No timeline"):
                resolve_bridge.get_timeline_info()


@unittest.skipUnless(FUSCRIPT, "Resolve's fuscript isn't installed")
class LuaEndToEndTests(_TempBridge):
    """The real launcher and bridge, in a copy of the Free 21.1 sandbox."""

    def _render(self) -> str:
        with open(TEMPLATE, encoding="utf-8") as fh:
            text = fh.read()
        missing = os.path.join(self.root, "not-installed")
        for token, value in {
            "@@YEET_DIR@@": missing, "@@SHIM@@": os.path.join(missing, "app.exe"),
            "@@EXE@@": os.path.join(missing, "app.exe"), "@@LOG@@": "",
            "@@APP_NAME@@": "YEETingus", "@@VERSION@@": "test", "@@INSTALLED_AT@@": "now",
            "@@BRIDGE_DIR@@": self.dir.replace("\\", "/"),
        }.items():
            text = text.replace(token, value)
        self.assertEqual(re.findall(r"@@[A-Z_]+@@", text), [])
        path = os.path.join(self.root, "YEETingus.lua")
        with open(path, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(text)
        return path

    def _start(self, mode: str, **extra):
        mb.ensure_bridge()
        env = dict(os.environ, YEET_HARNESS_MODE=mode, YEET_HARNESS_LAUNCHER=self._render(),
                   YEET_HARNESS_PREFS=self.prefs, **extra)
        proc = subprocess.Popen([FUSCRIPT, "-l", "lua", HARNESS], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, errors="replace")
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def _wait_owner(self, proc):
        deadline = time.time() + 20
        while time.time() < deadline:
            if mb.might_be_running():
                return
            if proc.poll() is not None:
                self.fail("harness exited early:\n" + proc.stdout.read())
            time.sleep(0.1)
        proc.kill()
        self.fail("bridge never started:\n" + proc.stdout.read())

    def test_free_sandbox_round_trip(self):
        proc = self._start("free")
        self._wait_owner(proc)

        ping = mb.call("Ping", timeout=10)
        self.assertEqual(ping["product"], "DaVinci Resolve")

        with mock.patch.object(resolve_bridge, "connect",
                               side_effect=resolve_bridge.ResolveError("no external scripting")):
            info = resolve_bridge.get_timeline_info()
            self.assertEqual((info["project"], info["timeline"], info["fps"]),
                             ("Friday video", "Timeline 1", 24.0))
            self.assertEqual(info["currentFrame"], 86640)

            clip = os.path.join(self.root, "Friday video.mp4")
            with open(clip, "wb") as fh:
                fh.write(b"x")
            res = resolve_bridge.import_and_insert(clip, insert_at="playhead",
                                                   retime="blend", bin_name="Piątek")
        # V1 is taken at the playhead, so a new V2/A2 pair.
        self.assertEqual(res["insertedFrame"], 86640)
        self.assertEqual(res["trackIndex"], 2)
        self.assertTrue(res["newTrack"])
        self.assertEqual(res["bin"], "Piątek")
        self.assertEqual(res["retimed"], {"mode": "blend", "clipFps": 60, "timelineFps": 24})

        with self.assertRaisesRegex(mb.MailboxError, "Unknown request"):
            mb.call("Nope", timeout=10)

        mb.stop()
        out, _ = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("HARNESS DONE", out)
        self.assertIn("owner=\n", out + "\n")          # Stop clears Owner

    def test_retry_finds_the_clip_under_its_long_path(self):
        # A Polish name goes to Resolve as its 8.3 short path, and Resolve
        # reports the clip under the long one. When the returned item places
        # nothing, the retry must still find the clip in the bin.
        long_path = os.path.join(self.root, "Piątek clip.mp4")
        short_path = os.path.join(self.root, "PIATEK~1.MP4")
        for p in (long_path, short_path):
            with open(p, "wb") as fh:
                fh.write(b"x")
        reported = os.path.join(self.root, "reported.txt")
        with open(reported, "wb") as fh:
            fh.write(long_path.encode("utf-8"))
        proc = self._start("free", YEET_HARNESS_STALE_ITEM="1", YEET_HARNESS_REPORTED_FILE=reported)
        self._wait_owner(proc)

        with mock.patch.object(resolve_bridge, "connect",
                               side_effect=resolve_bridge.ResolveError("no external scripting")), \
                mock.patch.object(mb, "lua_path", return_value=short_path):
            res = resolve_bridge.import_and_insert(long_path, insert_at="playhead", retime="project")
        self.assertEqual((res["insertedFrame"], res["trackIndex"]), (86640, 2))

        mb.stop()
        out, _ = proc.communicate(timeout=15)
        self.assertIn("HARNESS DONE", out)

    def test_studio_never_starts_the_bridge(self):
        proc = self._start("studio")
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("HARNESS DONE saves=0 owner=nil", out)


if __name__ == "__main__":
    unittest.main()
