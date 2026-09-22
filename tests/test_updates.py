"""updates.py: version parsing, comparison and asset choice (no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import updates  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse_version("v2.1.0"), (2, 1, 0))
        self.assertEqual(updates.parse_version("2.1"), (2, 1, 0))
        self.assertEqual(updates.parse_version("v2.0.0 - Rewrite, Remux"), (2, 0, 0))
        self.assertIsNone(updates.parse_version("untagged-0ebf36a7"))

    def test_newer(self):
        self.assertTrue(updates.is_newer("2.1.1", "2.1.0"))
        self.assertTrue(updates.is_newer("2.10.0", "2.9.9"))
        self.assertFalse(updates.is_newer("2.1.0", "2.1.0"))
        self.assertFalse(updates.is_newer("2.0.9", "2.1.0"))
        self.assertFalse(updates.is_newer("nonsense", "2.1.0"))

    def test_asset(self):
        rel = {"assets": [
            {"name": "SHA256SUMS.txt", "browser_download_url": "sums"},
            {"name": "YEETingus-windows-x86_64.exe", "browser_download_url": "win"},
            {"name": "YEETingus-Mac-ARM.dmg", "browser_download_url": "mac"},
        ]}
        self.assertEqual(updates.pick_asset(rel, "win32"), "win")
        self.assertEqual(updates.pick_asset(rel, "darwin"), "mac")
        self.assertIsNone(updates.pick_asset(rel, "linux"))


if __name__ == "__main__":
    unittest.main()
