# Changelog

Notable changes to YEETingus. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2.0.0] — 2026-09-17

The rewrite. A new window (Tauri + React) on a new architecture (one Python
service doing the work, any front end driving it), Premiere Pro support, a
clip history, and a first-run setup. The download → prepare pipeline from
1.4.0 is carried over unchanged. `FEATURES.md` lists every user-facing change;
the short version:

### Added

- **New app.** Native window with a web view, ~10 MB, dark and light theme,
  fluid two-column layout that follows the window. AutoSubs-style: controls
  on the left, content on the right, one action button at the bottom.
- **Clips history**: every finished clip, newest first, with thumbnail,
  title, channel, length, size and date. Per clip: insert into the timeline,
  play, open the video's page, open its folder, delete (two-step, inline).
  Click the title or channel to copy it.
- **Link preview** with a green Ready badge; **age-restricted videos detected
  before downloading**.
- **Length slider** (0:01–5:00) beside the 15/30/60/Whole presets.
- **Premiere Pro.** Settings → Editor. A one-click panel install through
  Adobe's own installer; the panel is docked once and lives in the workspace.
  Premiere can't decode AV1, so for Premiere the preparation pass makes HEVC.
- **First-run setup** asking which editor you use.
- `backend/engine.py` (the app without a window), `backend/service.py`
  (the same over localhost HTTP + SSE), `backend/premiere_bridge.py`,
  `premiere/panel/` (the UXP panel), `app/` (the Tauri window).

### Changed

- Accent colour is now a muted olive; the yellow stays in the logo.
- The credit reads "haej".
- The Tk window (`backend/yeet_app.py`) still runs, now as a thin shell over
  the engine, and is no longer the shipped UI.

---

## [1.4.0] — 2026-09-16

The old re-encoding codec is gone. Every download is now converted into a
seek-friendly editing intermediate — keyframe every 0.5 s, no B-frames — by the fastest encoder the
machine has, chosen by one small decision engine (`backend/media.py`) from
what actually landed on disk. Full resolution everywhere; nothing is capped
at 1080p any more, and there is no setting to get wrong. The measurements
that drove the design are in `BENCHMARK.md`.

### Removed

- **The previous re-encoding codec, entirely.** There were two paths: the
  explicit conversion of whole videos above 1080p, and a hidden one — yt-dlp's
  `--force-keyframes-at-cuts`, used on every clip, re-encodes with the
  container's default encoder, which for MP4 was the same codec. Every
  `-cNNN.mp4` clip the app ever made went through it; none does now. Gone
  with them: the `REENCODE_CRF`/`REENCODE_PRESET` constants, the codec-first
  format sort, the "Whole videos above 1080p: Keep quality / Keep it quick"
  setting and its key (ignored if present in an old `settings.json`), the
  "Converting…" progress band, and the VP9/AV1 "Resolve can't play this"
  warnings.
- **The Windows ffmpeg download is now the LGPL build** from BtbN's
  FFmpeg-Builds (yt-dlp's fork of it applies no patches). It omits the
  GPL-only encoder libraries — none of which the app used — and keeps
  everything it does use. An existing GPL build in the tool cache keeps
  working.

### Added

- **`backend/media.py` — the decision engine.** Probes the download (codec,
  container, rate, bit depth, colour, timing), probes the hardware once at
  startup (which AV1 encoder actually initialises), and returns a plan:
  encoder, GOP, trim, conformed frame rate. Pure functions, so every branch
  is unit-tested.
- **Hardware AV1 transcode** (NVENC, Quick Sync, AMF) with a keyframe every
  0.5 s and no B-frames. Several times realtime for 4K60 on an RTX 5070 Ti
  (exact figures in `BENCHMARK.md`). 10-bit/HDR sources stay 10-bit with
  their mastering metadata. If the encoder fails on real footage despite
  passing its probe, the job retries on the CPU.
- **CPU fallback: ffmpeg's native MPEG-4 Part 2**, same GOP. Present in every
  ffmpeg build, a few times realtime for 4K60 on a 16-core CPU, decodes
  everywhere.
- **Frame-exact clips.** A section is downloaded cut at the keyframe before
  the in point (no re-encode by yt-dlp any more); the conversion starts
  decoding at that keyframe and drops frames up to the in point.
- **Variable-rate and odd-rate sources are conformed** (`-fps_mode cfr`) to
  the nearest standard rate when within 1% (YouTube passes 59.74 fps uploads
  through as-is).
- The download preference asks for AV1 first at full resolution — smallest
  download, decodes in hardware on the way in.
- **Opus audio is converted to AAC** when YouTube offers nothing else (older
  Resolve builds import Opus silently); AAC is copied untouched.
- **Tests** (`tests/`, stdlib unittest): probe parsing, cadence detection,
  GOP/rate maths, remux eligibility, encoder selection, hardware detection
  incl. absent/failed hardware, command generation, and a guard that fails
  if any source/hardware combination could ever choose a removed encoder, or
  if one of their names or `--force-keyframes-at-cuts` reappears anywhere in
  the repository.
- **`tools/bench.py`** and **`tools/resolve_check.py`**: the benchmark
  harness (encode speed, size, seek latency) and the Resolve-side check
  (import, seek, decode throughput via render, audio offset), kept for
  re-measuring against future ffmpeg or Resolve releases.

### Changed

- Settings → Tools shows what the preparation step can use on this machine.
- The log says exactly what happened to a download ("no re-encode needed —
  repacking", or which encoder and keyframe interval was used) and why.

### Why not the download as-is

Repacking YouTube's AV1 into MP4 is instant, lossless and decodes in hardware
(4K60 at ~140 fps in Resolve 21), and it was the plan — until it was scrubbed
side by side with the 0.5 s-GOP files on a 4K60 timeline: "very slow" versus
"amazing". YouTube's keyframes are ~5 s apart, so every seek decodes up to
300 frames; the keyframe interval is what matters, and only a re-encode can
set it. VP9 as-is is out for a second reason: VP9 in MP4 fails to decode in
Resolve at the first keyframe boundary ("Error decoding full resolution
media"), and VP9 in MKV plays but puts the audio 12.0 s out of sync.

---

## [1.3.1] — 2026-08-16

Reliability pass before three days of field use, plus the fix for the downloads
that had stopped working entirely.

### Changed

- **Accented Latin characters in filenames are folded to ASCII.** `Zażółć gęślą
  jaźń` becomes `Zazolc gesla jazn`, `Kraków` becomes `Krakow`. Two mechanisms,
  because one isn't enough: NFKD strips combining accents, but `ł` has no
  decomposition — it's a distinct letter, not l-with-a-mark — so it needs an
  explicit table, alongside `ø`, `đ`, `æ`, `ß` and friends. Non-Latin scripts are
  untouched, since there is no sensible ASCII to fold 日本語 to.
- **403 errors now explain themselves.** The old hint was *"403 means YouTube
  refused that format's URL. Try 'Best available', or hit 'Update yt-dlp'."* —
  which led with advice that cannot help, since changing quality does nothing
  when every format is refused. An out-of-date yt-dlp is overwhelmingly the
  cause, so that comes first, with the installed version quoted. The two shapes
  are told apart: refused outright (a clip, where ffmpeg fetches the byte range
  and can't reproduce the headers the URL is bound to) versus stopping part-way
  through (a whole video, which reads like a dropped connection but isn't).
  Age-restricted videos are identified separately, since no update fixes those.

### Fixed

- **"Update yt-dlp" dead-ended when yt-dlp came from pip.** A pip *console
  script* is indistinguishable from a standalone binary here — same single path,
  same name — but it refuses `-U` with *"You installed yt-dlp with pip… Use that
  to update"* and exit 100. The button reported the exit code and stopped, so the
  one remedy the app offers for a stale yt-dlp did nothing. It now recognises
  that refusal and retries through pip, using the interpreter next to the script
  rather than `sys.executable` — which in a frozen build is YEETingus itself, and
  would have relaunched the app instead of upgrading anything.
- **Non-ASCII output from yt-dlp and ffmpeg was mangled in the log.** Both write
  UTF-8 regardless of the console codepage, but the app decoded with the locale,
  so a Polish title logged as `WiedÅºmin 3 … PieÅ›ni przeszÅ‚oÅ›ci`. Files were
  never affected — yt-dlp escapes non-ASCII in the JSON the metadata probe reads,
  so folder names were always correct — but it made real errors hard to read.
- **A truncated whole video was reused forever as if complete.** If a download
  died partway, ffmpeg could leave a valid-but-short `-full.mp4`, and the reuse
  check accepted any non-empty file with the right name — so every later attempt
  said "Already downloaded" and handed Resolve part of a video, with no way to
  tell short of deleting the file by hand. The file's own duration is now checked
  against the video's, and anything materially short is re-downloaded. Unknown
  durations (livestreams) are trusted rather than re-fetched.
- **Cleanup after a failed download didn't happen at all**, and when it did it
  could lose a race. `_cleanup_partial` only ran on cancellation, so a failure
  left `<stem>.mp4.part` behind — which `next_clip_stem` counts, permanently
  burning that clip number. On a flaky connection the numbers marched upward and
  the folder filled with junk. It now runs on failure too, and retries the delete,
  because Windows won't unlink a file the dying ffmpeg still holds open.
- **A section past the end of the video** produced twenty lines of ffmpeg
  filter-graph errors ending in `ffmpeg exited with code 4294967262`, and a
  0-byte file. The requested range is now checked against the video's duration
  first: an in point past the end is refused in one sentence, and an end point
  past it is quietly trimmed.
- **A missing clips folder** reported `[WinError 3] The system cannot find the
  path specified: 'Q:\'` with nothing to say it was the clips folder — the
  realistic cause being a folder on a drive that isn't plugged in. It now names
  the folder and says where to change it.

---

## [1.3.0] — 2026-08-15

Whole videos downloaded above 1080p were unusable in Resolve — dropped frames,
then MEDIA OFFLINE, and Generate Optimized Media refused to run on them. Clips
with an in and out point were always fine, which is what made it hard to place.

### Added

- **Setting: Whole videos above 1080p.** **Keep quality** (default) keeps the
  resolution and converts the download to the old codec afterwards; **Keep it quick**
  skips the conversion and caps whole videos at 1080p instead. Clips are
  unaffected either way. Stored as the re-encode key in `settings.json`.

### Changed

- **The Settings window scrolls, and Save/Cancel are pinned to the bottom.** On a
  1080p display at 150% scale the settings were taller than the usable screen, so
  the two buttons the window exists for sat below the bottom edge. A tall window
  could also open low enough to hang off the screen; its position is now computed
  and clamped rather than left to Tk.

### Fixed

- **Whole videos above 1080p were unusable in Resolve** — dropped frames, then
  MEDIA OFFLINE, and Generate Optimized Media refused to run on them. YouTube
  offers no the old codec above 1080p, so those downloads arrive as VP9 or AV1, and
  Resolve has no usable decoder for either. Measured on a 4K60 file, VP9 software
  decode runs at about real time on an RTX 5070 Ti — while Resolve is also
  compositing. Proxies were never a workaround: building one means decoding the
  same file.

  Clips were never affected, which is what made this confusing —
  `--force-keyframes-at-cuts` already re-encodes them to the old codec. Whole videos had
  no such step.

  New setting, **Whole videos above 1080p**:
  - **Keep quality** (default) — full resolution, converted to the old codec after the
    download, at about 60% of the video's length. STOP works throughout and
    progress is reported.
  - **Keep it quick** — no conversion, but whole videos are capped at 1080p,
    which is where YouTube's the old codec stops.

  Existing VP9 files are repaired in place the next time you request that video,
  and the converted copy is reused after that. The old log advice to run Generate
  Optimized Media has been removed, since it does not work on these clips.

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
  video resolves to `vp9 + mp4a.40.2` instead of `vp9 + opus`, and the old codec still wins
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
- Prefers the codec Resolve played best without sacrificing resolution
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
