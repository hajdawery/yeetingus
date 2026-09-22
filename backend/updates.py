"""
updates.py — "is there a newer YEETingus?"

Asks GitHub for the repository's latest published release (drafts and
pre-releases are never returned by that endpoint) and compares its tag with
this build's version. Nothing is downloaded or installed here: the app shows a
notice with a link to the installer for this platform, and the user runs it.

One unauthenticated request per check, to api.github.com, carrying nothing but
a User-Agent. Checks can be turned off in Settings.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

from version import APP_NAME, __version__

REPO = "hajdawery/yeetingus"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

# The installer each platform should be offered, by release asset name.
ASSET_NAMES = {
    "win32": "YEETingus-windows-x86_64.exe",
    "darwin": "YEETingus-Mac-ARM.dmg",
}


def parse_version(text: str) -> tuple[int, ...] | None:
    """(2, 1, 0) from "v2.1.0", "2.1.0", "v2.1.0 - Queue it up"; None if absent."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def pick_asset(release: dict, platform: str = sys.platform) -> str | None:
    """Download URL of this platform's installer in a release, if it has one."""
    want = ASSET_NAMES.get(platform)
    for asset in release.get("assets") or []:
        if want and asset.get("name") == want:
            return asset.get("browser_download_url")
    return None


def latest_release(timeout: float = 10.0) -> dict:
    """What the newest published release is. Raises OSError/ValueError on a
    network or parse failure, for the caller to report quietly."""
    import deps     # its SSL context copes with a frozen build's missing CA store
    req = urllib.request.Request(LATEST_URL, headers={
        "User-Agent": f"{APP_NAME}/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=deps._ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("no published release yet") from e
        raise
    # The tag is the version; a release published without one (GitHub shows
    # "untagged-…") still carries it in its title.
    tag = data.get("tag_name") or ""
    version = tag if parse_version(tag) and not tag.startswith("untagged-") else data.get("name") or ""
    parsed = parse_version(version)
    if not parsed:
        raise ValueError(f"can't read a version from release '{data.get('name')}'")
    return {
        "version": ".".join(str(n) for n in parsed),
        "name": data.get("name") or "",
        "page": data.get("html_url") or RELEASES_PAGE,
        "download": pick_asset(data),
        "published": data.get("published_at"),
    }
