"""
Repository guard: the encoders removed in 1.4.0 must not come back.

The app used to re-encode whole videos with one of them explicitly and, less
obviously, every clip through yt-dlp's --force-keyframes-at-cuts (which
re-encodes with the container's default encoder — the same one for MP4). Both
are gone; this test keeps them gone by scanning the repository for the
encoder names (media.FORBIDDEN_ENCODERS and the hardware variants) and for the
yt-dlp flag. The names themselves may appear only in the two files that
implement the guard, listed in ALLOWED.
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

ENCODER_NAMES = ("libx264", "libx264rgb", "libopenh264", "h264_nvenc", "h264_qsv",
                 "h264_amf", "h264_mf", "h264_videotoolbox", "h264_vaapi", "h264_v4l2m2m",
                 "x264", "h264", "avc1", "h.264")
# Only the quoted forms: the flag as an argument, or the yt-dlp option key.
# Prose that explains why the flag is NOT used may name it.
IMPLICIT_ENCODE_FLAGS = ('"--force-keyframes-at-cuts"', "'--force-keyframes-at-cuts'",
                         '"force_keyframes_at_cuts"', "'force_keyframes_at_cuts'")

# The only files allowed to spell these names: the guard itself.
ALLOWED = {
    "tests/test_encoder_guard.py": "this guard",
    "backend/media.py": "FORBIDDEN_ENCODERS: the runtime guard must know the names",
}

SCAN_DIRS = ("backend", "resolve", "tools", "tests")
SCAN_ROOT_FILES = ("build.py", "install.py", "README.md", "CHANGELOG.md",
                   "THIRD-PARTY-NOTICES.md", "BENCHMARK.md", "LICENSE")
EXTS = (".py", ".in", ".bat", ".sh", ".md", ".spec", ".txt", ".json", ".csv")


def _files():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, names in os.walk(base):
            if "__pycache__" in dirpath:
                continue
            for n in names:
                if n.endswith(EXTS):
                    yield os.path.relpath(os.path.join(dirpath, n), ROOT).replace("\\", "/")
    for n in SCAN_ROOT_FILES:
        if os.path.isfile(os.path.join(ROOT, n)):
            yield n


class ForbiddenEncoders(unittest.TestCase):
    def test_no_encoder_names_outside_allowlist(self):
        pattern = re.compile("|".join(re.escape(n) for n in ENCODER_NAMES), re.IGNORECASE)
        offenders = []
        for rel in _files():
            if rel in ALLOWED:
                continue
            with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    m = pattern.search(line)
                    if m:
                        offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(offenders, [], "removed encoder reference(s) reintroduced:\n" + "\n".join(offenders))

    def test_no_implicit_reencode_flag(self):
        offenders = []
        for rel in _files():
            if rel in ("tests/test_encoder_guard.py",):
                continue
            with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if any(f in line for f in IMPLICIT_ENCODE_FLAGS):
                        offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
        self.assertEqual(offenders, [], "implicit re-encode flag reintroduced:\n" + "\n".join(offenders))

    def test_app_only_passes_allowed_encoders_to_ffmpeg(self):
        """Every '-c:v' the app source hands to ffmpeg must be copy, mpeg4 or a
        hardware AV1 encoder — checked textually as a second line of defence
        behind test_media.OnlyAllowedEncoders."""
        allowed = {"copy", "mpeg4", "av1_nvenc", "av1_qsv", "av1_amf", "av1_vaapi",
                   'caps.av1_encoder', "enc", "encoder"}
        pattern = re.compile(r'"-c:v",\s*"?([A-Za-z0-9_.]+)"?')
        bad = []
        for rel in ("backend/media.py", "backend/yeet_app.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    for m in pattern.finditer(line):
                        if m.group(1) not in allowed:
                            bad.append(f"{rel}:{lineno}: {m.group(0)}")
        self.assertEqual(bad, [])

    def test_ffmpeg_download_is_the_lgpl_build(self):
        """The Windows ffmpeg fetched on first run must be the LGPL build, which
        omits the removed encoders (see deps.FFMPEG_URL)."""
        with open(os.path.join(ROOT, "backend", "deps.py"), encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r'FFMPEG_URL\s*=\s*\(\s*"([^"]+)"\s*"([^"]+)"', text)
        self.assertIsNotNone(m, "FFMPEG_URL not found in deps.py")
        url = m.group(1) + m.group(2)
        self.assertIn("lgpl", url)
        self.assertNotIn("-gpl", url)


if __name__ == "__main__":
    unittest.main()
