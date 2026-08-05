# Changelog

Notable changes to YEETingus. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.2.0] — 2026-08-05

YouTube now hides its formats behind a JavaScript challenge, and solving it needs
a JS runtime that YEETingus didn't have. Some videos had stopped downloading
altogether. **Upgrading is worth it even if nothing looked broken for you** — the
same change quietly cost formats on videos that did still work.

### Added

- **A JavaScript runtime is now fetched on first run.** YouTube serves its
  formats behind a JavaScript challenge, and yt-dlp solves it by running solver
  scripts in a real JS engine — [EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
  Without one, some videos come back missing formats and others fail outright.
  YEETingus downloads **Deno**, the runtime yt-dlp enables by default: a one-time
  ~40 MB fetch into the same folder as yt-dlp, on every platform. Deno publishes
  official MIT-licensed builds for all of them, so the provenance problem that
  keeps ffmpeg off that list doesn't apply. A Deno already on `PATH` or in
  `~/.deno/bin` is used as-is, and `YEET_DENO` points at a specific build.
- **A Deno older than 2.3.0 is detected and replaced.** yt-dlp rejects those but
  reports it as "no runtime could be found", never naming the version — so an old
  `deno` on `PATH` would have looked like a bug with no visible cause. The user's
  own copy is left alone; it just stops being the one used.
- **`JS:` row and an Install button in Settings.** The button appears only while
  a runtime is missing — the download normally happens at startup, so it's there
  for the first run that had no network.
- **`--remote-components ejs:github`** is passed to yt-dlp, letting it fall back
  to fetching the solver scripts from its own repository when the copies bundled
  inside it are too old for the challenge YouTube is currently serving. yt-dlp
  hash-checks them before running, and Deno executes them with no filesystem or
  network access.

### Changed

- The startup log and the "no usable file" hints now name a missing JS runtime as
  a cause. It produces the same symptoms as a stale yt-dlp — 403s, missing
  resolutions — and previously there was nothing pointing at the real problem.
- yt-dlp is asked which flags it supports rather than having it inferred from its
  version, so an older build simply runs without the runtime instead of failing on
  an unknown option.

### Fixed

- **A duplicate `YEETingus` entry in Resolve's Scripts menu.** Resolve reads
  scripts from more than one folder, and an install that landed in a different one
  than a previous version left both behind. The installer now removes our entry
  from every folder except the one it just wrote, and says so when a leftover
  needs administrator rights to delete.
- The Settings window was sized by a fixed height that the new runtime controls
  overflowed, putting **Save** and **Cancel** off the bottom edge. It now measures
  its own content.

---

## [1.1.0] — 2026-08-01

macOS support. Windows behaviour is unchanged — every platform difference is
additive, and the shared paths are the same code they always were.

### Added

- **macOS support**, on Apple Silicon, built as a `.app` bundle. One codebase —
  `backend/platform_paths.py` is the single place that knows what differs
  between operating systems. Intel Macs are out of scope: nothing in the code
  precludes them and `build.py --universal` produces a universal2 bundle, but it
  is neither tested nor shipped.
- **`launch_yeetingus.sh`**, the macOS/Linux counterpart to the `.bat` shim. It
  clears `PYTHONHOME` for the same reason, and puts the Homebrew prefixes back on
  `PATH`, which a GUI process launched from Resolve does not inherit.
- **Install ffmpeg button** in Settings on macOS, shown only while ffmpeg is
  missing. Runs `brew install ffmpeg` on an explicit click, then picks the result
  up without a restart.
- **Certificate-store fallback.** The python.org macOS builds ship no CA bundle
  until you run `Install Certificates.command`, so every download failed with
  `CERTIFICATE_VERIFY_FAILED`. Falls back through certifi and the system bundle
  at `/etc/ssl/cert.pem`. Verification is never disabled.
- `.icns` icon generated at build time from `assets/logo.png` with `sips` and
  `iconutil`, both part of macOS.

### Changed

- **ffmpeg is not downloaded on macOS** — `brew install ffmpeg` instead. There is
  no Apple Silicon build whose provenance can be vouched for: ffmpeg.org's only
  listed macOS source declines to build for ARM, and the binaries that circulate
  all trace back to one site labelling them "for educational purposes only". See
  [ffmpeg on macOS](README.md#-ffmpeg-on-macos). yt-dlp is still fetched
  automatically everywhere — it publishes an official macOS binary.
- **The Lua launcher is now cross-platform**, choosing its launch strategy at
  runtime. On macOS it invokes `/bin/sh` by name: `open`-ing a `.sh` would hand
  it to a text editor via file association, which looks exactly like a silent
  failure.
- The standalone installer is **opt-in on macOS** (`build.py --installer`). An
  unsigned installer binary is what Gatekeeper blocks, so shipping one by default
  would put a warning on the step meant to reassure.
- Copyright now reads **haej / GRApedia**, in the app's Settings credit, the
  macOS bundle's `Info.plist` and the Windows version resource. The GitHub link
  behind the credit is unchanged.
- **macOS builds use onedir, not onefile.** A `.app` is a directory by
  definition, so `--onefile` only buries a self-extracting binary inside it that
  unpacks to a temp directory on every launch — the signature covers the bundle
  while the code that runs sits somewhere unsigned and transient. PyInstaller
  makes this an error in v7.0. The onedir bundle passes
  `codesign --verify --deep --strict` and starts faster. Windows still uses
  onefile, where it's the right shape.

### Fixed

- **STOP left ffmpeg running on macOS and Linux.** The process-tree kill was
  Windows-only; everywhere else it killed just yt-dlp, leaving ffmpeg alive and
  still writing the output file, which then couldn't be cleaned up. Processes are
  now spawned into their own group and signalled as a unit.
- **UI proportions were wrong on macOS** — the window came out 33% too large,
  which made correctly-sized text look small beside it. Two different baselines
  were sharing one constant: the pixel constants in `theme.py` are authored at
  96 DPI and must always be divided by 96, while Tk's `scaling` is
  pixels-per-point and must be divided by 72. A `max(1.0, …)` floor in
  `set_scale` then discarded the 0.75 macOS legitimately needs, reading as a
  guard against absurd input. Now 1.02× chrome and 1.00× text against Windows at
  100%. `YEET_UI_SCALE` and `YEET_FONT_SCALE` tune either without a rebuild.
- **`install.py --dev` always failed its own verification**, on every platform,
  by insisting on a built app that `--dev` deliberately doesn't produce.
- The window icon is set with `iconphoto` and a PNG off Windows; `iconbitmap`
  takes a `.ico` only on Windows and silently did nothing elsewhere.

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
