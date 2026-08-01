# Changelog

Notable changes to YEETingus. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.0.1] — 2026-08-01

Two fixes, both in whole-video downloads — the newest and least-exercised path.

### Fixed

- **Silent audio on downloaded clips.** The format sort named a video codec but no
  audio codec, so yt-dlp picked **Opus** by its own preference even though YouTube
  offered AAC on every video tested. Resolve cannot decode Opus, so clips imported
  and played in silence. Now pinned to AAC without costing resolution — the same 4K
  video resolves to `vp9 + mp4a.40.2` instead of `vp9 + opus`, and H.264 still wins
  wherever it exists (1080p and below on YouTube).
- **MEDIA OFFLINE on long videos.** The reuse check accepted yt-dlp's per-stream
  fragments. An interrupted download leaves `<name>.f313.webm` (video only) and
  `<name>.f140.m4a` (audio only) behind, and the check returned the **audio-only**
  file as though it were a finished download. Handing Resolve an `.m4a` is what put
  MEDIA OFFLINE on the timeline. It only appeared on long videos because those are
  the ones interrupted often enough to leave fragments behind. Fragments, scratch
  files, zero-byte remnants and non-media extensions are all rejected now.

> **If you downloaded anything with 1.0.0**, those files still have Opus audio and
> the reuse check will hand them back unchanged. Delete them to pull fresh copies.

---

## [1.0.0] — 2026-07-28

First release.

### Added

**Clipping**
- Time-ranged downloads — only the requested section is fetched
- Frame-accurate cuts via `--force-keyframes-at-cuts`
- Flexible timestamps: `90`, `1:30` or `00:01:30`
- Whole-video downloads by leaving both points at `00:00`, saved once as `…-full`
  and reused on a repeat request
- Clip length shortcuts (`15s` · `30s` · `90s` · `Entire`, plus 2/5/10 minutes)
- Automatic detection of a link's `?t=` timestamp into the in point
- The end point follows the in point using a configurable default length

**Resolve**
- Insert at the playhead or the start of the timeline
- Live connection status distinguishing Resolve missing, no project and no timeline
- Launches from `Workspace → Scripts → Utility`
- **Download only** — skip the timeline entirely; works with Resolve closed

**Quality**
- Best available / 2160p / 1440p / 1080p / 720p / 480p
- Reports which resolutions a video actually offers, and falls back rather than
  failing when the requested one doesn't exist
- Prefers H.264 without sacrificing resolution
- Reports the real resolution, codec and frame rate of what landed on disk

**Files**
- Folders named `<VIDEO ID> - <title> - <channel>`, clips `<id>-<Channel>-cNNN`
- Numbered from what's on disk, so nothing is ever overwritten
- Names sanitised for every OS: accented and CJK text survives, emoji and
  characters Windows rejects do not; `unnamed` when a name is entirely stripped
- Saved under **Videos** by default rather than `%TEMP%`, which the OS may empty

**Interface**
- STOP mid-job, killing the whole process tree and cleaning up partial files
- Real download percentages, with distinct phases
- Collapsible log docked beside the controls, which keeps recording while hidden
  and opens itself on failure
- Scales with display DPI; dark native title bar
- Settings: clip folder with Reset, default clip length, tool paths, Resolve
  diagnostics, and an **Update yt-dlp** button

**Distribution**
- Standalone installer (`Install-YEETingus.exe`) — no Python needed
- yt-dlp and ffmpeg fetched automatically on first run
- MIT licence, third-party notices, and embedded version metadata

### Known issues

- Playhead placement uses non-drop-frame maths, so 29.97/59.94 timelines may be off
  by a frame or two
- Windows only
- Age-restricted videos fail with HTTP 403 — they need a signed-in session
- Unsigned binaries trip heuristic scanners; see the README
