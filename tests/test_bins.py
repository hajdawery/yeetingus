"""Bins: a subfolder of the clips folder holding video folders (no network)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import naming  # noqa: E402
import resolve_bridge  # noqa: E402
from engine import Engine  # noqa: E402


def _clip(folder: str, stem: str) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, stem + ".mp4")
    with open(path, "wb") as fh:
        fh.write(b"x" * 10)
    # A stored length, so listing doesn't go probing with ffmpeg.
    with open(os.path.join(folder, stem + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"duration": 1.0}, fh)
    return path


class BinNameTests(unittest.TestCase):
    def test_folder_name(self):
        self.assertEqual(naming.bin_folder("Friday"), "Friday")
        self.assertEqual(naming.bin_folder("  Friday video  "), "Friday video")
        self.assertEqual(naming.bin_folder("Friday/video: b-roll"), "Friday video b-roll")
        self.assertEqual(naming.bin_folder(""), "")
        self.assertEqual(naming.bin_folder(".."), "")
        self.assertEqual(naming.bin_folder("con"), "_con")


class BinLibraryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.engine = Engine()
        self.engine.download_dir = self.root

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_bin_validation(self):
        self.assertEqual(self.engine._bin_folder(""), "")
        self.assertEqual(self.engine._bin_folder(" Friday video "), "Friday video")
        self.assertIsNone(self.engine._bin_folder("???"))

    def test_list_marks_bins(self):
        plain = _clip(os.path.join(self.root, "abcdefghijk - A video - Chan"), "abcdefghijk-Chan-c001")
        binned = _clip(os.path.join(self.root, "Friday video", "zyxwvutsrqp - Trailer - Rockstar"),
                       "zyxwvutsrqp-Rockstar-c001")
        clips = {c["path"]: c for c in self.engine.list_clips()}
        self.assertEqual(set(clips), {plain, binned})
        self.assertEqual(clips[plain]["bin"], "")
        self.assertEqual(clips[binned]["bin"], "Friday video")
        self.assertEqual(clips[binned]["id"], "zyxwvutsrqp")
        self.assertEqual(clips[binned]["channel"], "Rockstar")

    def test_bin_of(self):
        binned = os.path.join(self.root, "Friday video", "vid - T - C", "vid-C-c001.mp4")
        plain = os.path.join(self.root, "vid - T - C", "vid-C-c001.mp4")
        self.assertEqual(self.engine._bin_of(binned), "Friday video")
        self.assertEqual(self.engine._bin_of(plain), "")
        self.assertEqual(self.engine._bin_of(os.path.join(self.root, "old.mp4")), "")
        self.assertEqual(self.engine._bin_of(os.path.join(os.path.dirname(self.root), "a", "b.mp4")), "")

    def test_delete_drops_empty_bin(self):
        video = os.path.join(self.root, "Friday video", "zyxwvutsrqp - Trailer - Rockstar")
        first = _clip(video, "zyxwvutsrqp-Rockstar-c001")
        second = _clip(video, "zyxwvutsrqp-Rockstar-c002")
        self.assertTrue(self.engine.delete_clip(first))
        self.assertTrue(os.path.isdir(video))
        self.assertTrue(self.engine.delete_clip(second))
        self.assertFalse(os.path.exists(os.path.join(self.root, "Friday video")))
        self.assertTrue(os.path.isdir(self.root))


class _Folder:
    def __init__(self, name, subs=()):
        self.name, self.subs = name, list(subs)

    def GetName(self):
        return self.name

    def GetSubFolderList(self):
        return self.subs


class _Pool:
    def __init__(self, *names):
        self.root = _Folder("Master", [_Folder(n) for n in names])

    def GetRootFolder(self):
        return self.root

    def AddSubFolder(self, parent, name):
        folder = _Folder(name)
        parent.subs.append(folder)
        return folder


class MediaPoolBinTests(unittest.TestCase):
    def test_reuses_existing_bin(self):
        pool = _Pool("B-roll", "Friday video")
        self.assertIs(resolve_bridge._pool_bin(pool, "Friday video"), pool.root.subs[1])
        self.assertEqual(len(pool.root.subs), 2)

    def test_makes_missing_bin(self):
        pool = _Pool("B-roll")
        made = resolve_bridge._pool_bin(pool, "Friday video")
        self.assertEqual(made.GetName(), "Friday video")
        self.assertIs(resolve_bridge._pool_bin(pool, "Friday video"), made)


if __name__ == "__main__":
    unittest.main()
