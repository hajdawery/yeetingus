"""Regressions from the 2.1.1 code review (no network, no editor)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import naming  # noqa: E402
import resolve_bridge  # noqa: E402
from engine import Engine  # noqa: E402


class LinkTimestamp(unittest.TestCase):
    def test_whole_value_only(self):
        self.assertEqual(naming.start_seconds_from_url("https://youtu.be/abc?t=90"), 90)
        self.assertEqual(naming.start_seconds_from_url("https://youtube.com/watch?v=a&t=2m5s&list=x"), 125)
        self.assertEqual(naming.start_seconds_from_url("https://youtube.com/watch?v=a#t=1h2m3s"), 3723)
        # A tracking token that starts with a digit is not a timestamp.
        self.assertIsNone(naming.start_seconds_from_url("https://x.com/a/status/1?s=46&t=7kLmAb"))
        self.assertIsNone(naming.start_seconds_from_url("https://x.com/a/status/1?t=5mXq"))


class Timecode(unittest.TestCase):
    def test_no_playhead_reading(self):
        # Resolve returns nothing on the Media and Fusion pages.
        self.assertIsNone(resolve_bridge._timecode_to_frames("", 24.0))
        self.assertIsNone(resolve_bridge._timecode_to_frames(None, 24.0))
        self.assertEqual(resolve_bridge._timecode_to_frames("00:00:01:00", 24.0), 24)


class _Proc:
    def __init__(self):
        self.polled = False

    def poll(self):
        self.polled = True
        return None


class EngineFixes(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_settings_validated_before_applied(self):
        before = self.engine.download_dir
        with self.assertRaises(ValueError):
            self.engine.update_settings(download_dir=os.path.abspath("elsewhere"), default_length=0)
        self.assertEqual(self.engine.download_dir, before)
        with self.assertRaises(ValueError):
            self.engine.update_settings(download_dir="relative/clips")
        with self.assertRaises(ValueError):
            self.engine.update_settings(default_length=True)

    def test_explicit_none_kills_nothing(self):
        # A queued job between tools passes None; that must not fall back to
        # the main job's process.
        main = _Proc()
        self.engine.active_proc = main
        self.engine._kill_active(None)
        self.assertFalse(main.polled)

    def test_end_trimmed_to_exact_length(self):
        got = self.engine._check_range("00:03:32", "00:04:02", {"duration": 212.4})
        self.assertEqual(got, ("00:03:32", "00:03:32.4"))
        # In point at the very end: nothing left to download.
        self.assertIsNone(self.engine._check_range("00:03:32", "00:04:02", {"duration": 212.0}))

    def test_preview_ignores_a_stopped_job(self):
        # After a STOP the main job's flag stays set; a quiet preview lookup
        # must not read it (it used to come back empty for every link).
        self.engine.ytdlp_cmd = [sys.executable, "-c",
                                 "print('{\"id\": \"abc\", \"title\": \"T\"}')"]
        self.engine.cancel_event.set()
        meta = self.engine.probe_metadata("https://example.com/v", quiet=True)
        self.assertEqual(meta["title"], "T")
        self.assertIsNone(self.engine.active_proc)


if __name__ == "__main__":
    unittest.main()
