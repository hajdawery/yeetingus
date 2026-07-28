<div align="center">

<img src="assets/logo.png" alt="YEETingus" width="130">

# YEETingus

**Grab any slice of a YouTube video or Twitch clip and drop it straight onto your DaVinci Resolve timeline.**

Paste a link, set an in and out point, hit one button. No browser, no downloads folder
shuffling, no manual importing.

![version](https://img.shields.io/badge/version-1.0.0-edff00?style=flat-square&labelColor=1a1a1a)
![platform](https://img.shields.io/badge/platform-Windows-0078d4?style=flat-square&labelColor=1a1a1a)
![resolve](https://img.shields.io/badge/DaVinci%20Resolve-Studio-ff5f56?style=flat-square&labelColor=1a1a1a)
![python](https://img.shields.io/badge/build%20with-Python%203.6–3.13-3776ab?style=flat-square&labelColor=1a1a1a)
![license](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square&labelColor=1a1a1a)

</div>

---

## 📖 Table of contents

- [What it does](#-what-it-does)
- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [How to use it](#-how-to-use-it)
- [Settings](#-settings)
- [Where clips are saved](#-where-clips-are-saved)
- [Codecs and smooth playback](#-codecs-and-smooth-playback)
- [How it works](#-how-it-works)
- [Troubleshooting](#-troubleshooting)
- [Known limitations](#-known-limitations)
- [Legal](#-legal)
- [License](#-license)
- [Credits](#-credits)

---

## 🎬 What it does

Editing something that needs a clip of a YouTube video or Twitch stream for reference,
commentary or review? The usual routine is: open a browser, find a downloader, grab
the whole video, trim it, import it, drag it to the timeline.

YEETingus collapses that into one window. It downloads **only the seconds you
asked for** — not the whole video — and hands the clip to Resolve at your playhead.

Built for DaVinci Resolve, where no equivalent tool existed.

<div align="center">
  <img src="assets/screenshot.jpg" alt="YEETingus window" width="420">
</div>

---

## ✨ Features

### 🎯 Precise clipping

- **Time-ranged downloads** — only the requested section is fetched, so a 20-second
  clip from a 3-hour stream takes seconds, not a full download
- **Frame-accurate cuts** — uses `--force-keyframes-at-cuts`, so your in/out points
  land where you set them instead of snapping to the nearest keyframe
- **Flexible timestamps** — type `90`, `1:30` or `00:01:30`, whichever you prefer
- **📼 Or grab the whole thing** — leave **both** points at `00:00` and the entire
  video is downloaded, no section trimming. The **Entire** button clears them for you.
- **⏱️ Clip length shortcuts** — `15s` · `30s` · `90s` · `Entire`, plus a dropdown for
  2 / 5 / 10 minutes. Each sets the end point relative to your in point.
- **🔗 Timestamps detected automatically** — paste a share link with a `?t=` value and
  the in point fills itself in, no button press. `169`, `169s`, `2m49s`, `1h2m3s`,
  `start=` and `#t=` are all understood. **Copy in point from link** remains as a
  manual override.
- **🪄 The end point follows** — type an in point and click away (or press Enter) and
  the end is set to your [default clip length](#-settings). It only recalculates when
  the in point actually changed, so an end point you set deliberately is never wiped.

### 🎥 Resolve integration

- **Insert at playhead** or at the **start of the timeline**, your choice
- **Live connection status** — a tinted pill in the header shows the connected project
  and timeline, and tells you *which* piece is missing when something's wrong
  (Resolve absent vs. no project vs. no timeline)
- **Always lands on the live playhead** — the position is read at the moment of
  insertion, so you never have to refresh anything first
- **Launches from Resolve** — appears under `Workspace → Scripts → Utility`
- **📥 Download only** — skip the timeline entirely and just keep the file; works
  even with Resolve closed

### 🎛️ Quality control

- **Quality picker** — Best available (default), 2160p, 1440p, 1080p, 720p, 480p
- **Honest about what exists** — the app reads which resolutions the video actually
  offers and tells you, instead of failing on a request the video can't satisfy
- **Smart codec preference** — prefers H.264 (which scrubs smoothly in Resolve)
  *without* costing you resolution
- **Real quality readout** — after each clip, the actual resolution, codec and frame
  rate are reported, read from the file itself rather than assumed

### 🗂️ Sensible file handling

- **Descriptive folders** — `<VIDEO ID> - <title> - <channel>`
- **Never overwrites** — clips are numbered from what's already on disk, so repeated
  grabs from the same video pile up safely
- **♻️ Whole videos are reused** — a full download is saved once as `…-full` and a
  repeat request returns instantly instead of fetching it again. Interrupted
  attempts are never mistaken for finished ones.
- **Bulletproof names** — emoji, symbols and characters Windows rejects are stripped,
  while accented and CJK titles stay readable
- **Saved somewhere sensible** — your **Videos** folder by default (not `%TEMP%`,
  which the OS may empty), configurable with a **Reset** button to get the default
  back

### 🧰 Quality of life

- **⏹️ STOP mid-job** — cancels the download, kills the whole process tree and cleans
  up the partial files
- **📊 Progress with real percentages** — parsed from the downloader, with clear
  phases: reading info → downloading → merging → pasting
- **📜 Collapsible log** — hidden by default; **Show log** docks it beside the controls
  and widens the window, so it never covers or shifts anything. It keeps recording
  while hidden, and opens itself automatically if something fails
- **🖥️ Scales with your display** — reads the system DPI, so the whole UI stays
  proportionate on 1080p and 4K alike rather than shrinking to a postage stamp
- **🌒 Dark title bar** — the native Windows title bar is themed to match, instead of
  a white strip above a near-black window
- **🔄 Self-updating downloader** — an **Update yt-dlp** button, because YouTube
  changes things and breakage is a matter of when, not if
- **📦 Zero-dependency setup** — yt-dlp and ffmpeg are fetched automatically on first
  run; no Python needed to *run* the app

---

## 📋 Requirements

| | |
|---|---|
| 🖥️ **OS** | Windows |
| 🎬 **DaVinci Resolve** | Studio, running, with a project and timeline open |
| 🔓 **Scripting enabled** | `Preferences → System → General → External scripting using` → **Local** |
| 🐍 **Python** | **Only to build it** — 3.6–3.13 (see [note](#the-python-version-constraint)) |
| 📥 **yt-dlp + ffmpeg** | Fetched automatically on first run |

> [!IMPORTANT]
> Enabling external scripting is not optional — without it, Resolve won't accept
> connections and the app can't insert anything.

> [!NOTE]
> Blackmagic's own scripting docs state the API covers both the free and Studio
> versions, but external scripting on the free version is untested here. Studio is
> the supported configuration.

---

## 📦 Installation

There's no installer yet — you build it once, then install it.

```bash
git clone https://github.com/hajdawery/yeetingus.git
cd yeetingus

py -3.13 build.py      # creates dist\YEETingus.exe  (~11 MB)
py -3.13 install.py    # installs it + adds the Resolve menu entry
```

Then **restart DaVinci Resolve**.

> [!WARNING]
> Restarting Resolve is required, not optional. Resolve caches the launcher script
> when it builds the Scripts menu, so until you restart it keeps running the old one.

The installer prints a verification block listing exactly what it wrote, and fails
loudly if anything is missing rather than claiming success.

<details>
<summary><b>Running from source instead</b></summary>

```bash
py -3.13 backend\yeet_app.py          # just run it
py -3.13 install.py --dev             # or point the Resolve menu entry at your source copy
```

`--dev` bakes your source path into the launcher, so the menu entry runs your working
copy with no exe involved. Re-run it if you move the project.

</details>

<details>
<summary><b>Upgrading from the old "YEET" version</b></summary>

`install.py` handles it automatically. The downloaded tool cache (yt-dlp + ffmpeg) and
your `settings.json` are moved to the new folder, and the old exe, shim and menu entry
are deleted so Resolve doesn't list two entries. Nothing is re-downloaded and no
settings are lost.

</details>

<details id="the-python-version-constraint">
<summary><b>Why Python 3.6–3.13 (and why it doesn't matter to users)</b></summary>

Resolve's `fusionscript.dll` is a version-specific CPython C extension, so it only
loads into an interpreter matching its ABI. Blackmagic's docs claim "3.6+", but the
real ceiling lags new Python releases until they rebuild it.

Tested against Resolve's June 2026 library:

| Python | Result |
|---|---|
| 3.11 | ✅ loads |
| 3.13 | ✅ loads |
| 3.14 | ❌ segfault |

The built exe **embeds its own interpreter**, so anyone *running* YEETingus needs no
Python at all. This only affects building and running from source. `build.py` refuses
to run on an unsupported version rather than producing a broken exe, and
`resolve_bridge.MAX_PY` is the single constant to bump once a newer Python works.

</details>

---

## 🚀 How to use it

1. In Resolve, open a project and a timeline
2. **`Workspace → Scripts → Utility → YEETingus`**
3. Paste a **video link** — if it carries a `?t=` timestamp, the in point fills
   itself in and the end point follows
4. Otherwise set the **in point** (the end follows your default length) or click a
   length shortcut like `30s`. Leave both at `00:00` — or press **Entire** — to take
   the whole video.
5. Pick a **max quality** (leave it on *Best available* if unsure)
6. Choose **Playhead** or **Start of timeline**
7. Hit **YEET (download & insert)** 🚀

The clip lands on your timeline, and the log recaps the video title, channel and real
resolution.

**Just want the file?** Use **Download only** — same pipeline, no timeline, works with
Resolve closed.

**Changed your mind?** The main button becomes a red **STOP** while a job runs.

---

## ⚙️ Settings

Stored in `%LOCALAPPDATA%\YEETingus\settings.json`, written atomically and preserved
across reinstalls.

- 📁 **Clip storage folder** — with a Browse picker. Defaults to your **Videos**
  folder (`Movies` on macOS), honouring a relocated one rather than assuming
  `~\Videos`. Deliberately *not* `%TEMP%`, which Disk Cleanup and Storage Sense
  are entitled to empty — that would take media your timelines reference offline.
- ⏱️ **Default clip length** — `15s` · `30s` · `60s` · `90s`, applied to the end point
  when the app opens
- 🧰 **Tools** — the resolved yt-dlp and ffmpeg paths and versions
- 🩺 **Resolve diagnostics** — the detected scripting library and Python version, in red
  if either is wrong. This is the first thing to check on a new machine.
- 🔄 **Update yt-dlp** — self-updates the downloader

---

## 📁 Where clips are saved

```
%USERPROFILE%\Videos\YEETingus\
└── dQw4w9WgXcQ - Rick Astley - Never Gonna Give You Up (4K Remaster) - Rick Astley\
    ├── dQw4w9WgXcQ-RickAstley-c001.mp4
    └── dQw4w9WgXcQ-RickAstley-c002.mp4
```

**Folders** are `<VIDEO ID> - <title> - <channel>` and stay human-readable.

**Files** are `<videoid>-<ChannelName>-cNNN`, with the channel squashed into one token
(`Rick Astley` → `RickAstley`, capped at 32 characters) so every filename has exactly
three `-`-separated fields.

Numbering is derived from what's already on disk, so **nothing is ever overwritten** —
even across restarts, or if you delete clips by hand.

**Whole-video downloads** get a fixed name instead of a number —
`<videoid>-<ChannelName>-full` — because there's only ever one of them per video.
Asking for the same video again **reuses the existing file** rather than downloading
it twice, so the second request is instant. Delete the file to force a fresh
download. An interrupted attempt is never mistaken for a finished one.

<details>
<summary><b>How names are sanitised</b></summary>

Letters, digits and accent marks survive; spaces, punctuation, emoji, control
characters and every byte Windows forbids (`<>:"/\|?*`) are stripped. Reserved names
(`CON`, `NUL`, …) are escaped, trailing dots and spaces removed, lengths capped.

| Original | Becomes |
|---|---|
| `Rick Astley` | `RickAstley` |
| `GameBro™ 🎮` | `GameBroTM` |
| `Kanał Polski` | `KanałPolski` |
| `日本語チャンネル` | `日本語チャンネル` |
| `🔥🔥🔥` | `unnamed` |

If a title or channel is made **entirely** of stripped characters, it becomes
`unnamed` rather than disappearing. A field that was never known (metadata lookup
failed) is omitted instead — so `unnamed` always means "there was a name, but none of
it was usable".

</details>

---

## 🎥 Codecs and smooth playback

YEETingus sorts formats by resolution first, then prefers **H.264**
(`-S res,vcodec:h264`). H.264 hardware-decodes and scrubs well in Resolve; VP9 is
worse and AV1 noticeably worse.

The catch is what YouTube actually serves:

| Resolution | Codecs available |
|---|---|
| 2160p / 1440p | VP9, AV1 only |
| 1080p and below | ✅ **H.264**, VP9, AV1 |

So anything at 1080p or below arrives as H.264 and plays back smoothly. At 1440p/4K
there is no H.264 to choose.

> [!TIP]
> **If a 1440p/4K clip stutters**, use Resolve's own proxies: right-click the clip in
> the Media Pool → **Generate Optimized Media**. Resolve manages that cache and swaps
> proxies in transparently, which beats anything this tool could do — and avoids the
> 10–45× disk cost of writing intermediate copies. The log points this out whenever a
> clip isn't H.264.

The sort order matters: a naive "H.264 else anything" preference would silently cap
*Best available* at 1080p, since that's as high as YouTube's H.264 goes.

---

## 🧠 How it works

One standalone app — no server, no port, nothing listening.

```
  DaVinci Resolve   Workspace → Scripts → Utility → YEETingus
        │
        │  YEETingus.lua spawns the app (never blocks Resolve)
        ▼
  YEETingus.exe  ── subprocess ──▶  yt-dlp + ffmpeg   (fetch just the section)
        │
        └── Resolve's official external Python scripting API
                    │
                    ▼
            media pool import + timeline insert
```

<details>
<summary><b>Three launcher details that each caused a silent failure</b></summary>

Documented in `resolve/YEETingus.lua.in`, because each one cost real debugging time:

1. **No environment variables.** Resolve's embedded Lua host doesn't reliably expose
   `%LOCALAPPDATA%`, so `install.py` bakes absolute paths into the launcher. When
   `os.getenv` returned nil, every path broke and clicking the menu item did nothing
   at all — not even a log line.
2. **Launch via LuaJIT FFI `ShellExecuteA`**, not `os.execute`. The latter is
   unreliable inside Resolve's Lua host, though it works fine standalone — which
   makes it especially misleading to test.
3. **Launch the `.bat`, not the `.exe`.** Resolve exports `PYTHONHOME` for its own
   scripting, and a PyInstaller exe that inherits it segfaults instantly.
   `launch_yeetingus.bat` clears those variables first.

</details>

<details>
<summary><b>Project layout</b></summary>

| Path | Role |
|---|---|
| `backend/yeet_app.py` | UI and orchestration |
| `backend/theme.py` | Palette, rounded cards/buttons, vector icons |
| `backend/deps.py` | Finds or downloads yt-dlp and ffmpeg |
| `backend/naming.py` | Filesystem-safe names, URL parsing |
| `backend/config.py` | Persisted settings |
| `backend/resolve_bridge.py` | Resolve import and timeline insert |
| `backend/version.py` | Name, version, authorship |
| `resolve/YEETingus.lua.in` | Scripts-menu launcher template |
| `resolve/launch_yeetingus.bat` | Clears `PYTHONHOME` before starting the exe |
| `build.py` / `install.py` | Freeze / install |

`resolve_bridge.py` is the only Resolve-specific module, so porting to another NLE
means writing one new adapter rather than restructuring the app.

</details>

---

## 🩺 Troubleshooting

<details>
<summary><b>The menu entry does nothing when clicked</b></summary>

1. **Restart Resolve.** It caches the launcher when building the Scripts menu.
2. Check `%LOCALAPPDATA%\YEETingus\launcher.log`:
   - **New lines appear** → the launcher ran; the log names which launch mechanism
     failed and why
   - **No new lines** → Resolve isn't executing the file at all, which points at the
     script's location rather than its contents
3. Re-run `py -3.13 install.py` and read its verification block.

</details>

<details>
<summary><b>"Resolve not connected" / no project or timeline</b></summary>

- Resolve must be **running**, with a **project and a timeline open**
- `Preferences → System → General → External scripting using` must be **Local**
- Open **Settings** in the app — the Resolve diagnostic line shows whether the
  scripting library was found and whether the interpreter is supported
- Click `↻` next to the status pill to re-check

The status pill distinguishes "Resolve isn't there" from "Resolve is there but has
nothing open", because those need different fixes.

</details>

<details>
<summary><b>Download fails with HTTP 403</b></summary>

Two different causes:

**Age-restricted videos.** These need a signed-in session, which the app doesn't
have, so the fetch is refused outright. There's no setting that fixes it — the video
simply isn't reachable anonymously.

**A stale or rejected format URL.** Not about resolution. Try **Best available**, then
**Update yt-dlp** in Settings. Extraction breaks periodically as YouTube changes, and
a newer yt-dlp is the usual cure.

If the video plays fine in a browser while logged out, it's the second case.

</details>

<details>
<summary><b>Requested 4K but got 1080p</b></summary>

Working as intended. The video didn't offer 4K, so it fell back to the best available
and said so in the log, rather than failing.

</details>

<details>
<summary><b>Playback stutters on a 4K clip</b></summary>

That'll be VP9 or AV1 — YouTube has no H.264 above 1080p. Right-click the clip in the
Media Pool → **Generate Optimized Media**.

</details>

---

## 🚧 Known limitations

- ⏱️ **Drop-frame timecode** — playhead placement uses non-drop-frame maths, so
  29.97/59.94 timelines may be off by a frame or two
- 🪟 **Windows only** — the launcher shim, process-tree kill and ffmpeg build are
  Windows-specific
- 🎞️ **No transcode on ingest** — deliberate; see
  [Codecs and smooth playback](#-codecs-and-smooth-playback)
- 🔄 **No auto-update yet** — the app doesn't check for new versions of itself
- 📼 **Mostly YouTube** — **Twitch clips work too** (tested). Downloading is handled by
  yt-dlp, which supports
  [hundreds of sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
  so plenty of others will likely work — but nothing beyond those two is verified,
  and site-specific quirks (timestamp formats, resolution options) may differ
- 🔒 **Age-restricted videos fail** — they need a signed-in session, so the download is
  refused with HTTP 403

---

## ⚖️ Legal

> [!CAUTION]
> **Downloading videos generally violates the terms of service of the sites you
> download from**, regardless of whether the tools themselves are legal. Copyright
> in the video belongs to whoever made it, and "it was on the internet" is not a
> licence. Fair dealing / fair use for commentary, criticism, review or teaching is
> a real thing, but it is **narrow, jurisdiction-specific, and decided after the
> fact** — not something a tool can grant you.
>
> You are responsible for what you download and what you publish. **Credit your
> sources** — the app reminds you every time for a reason.

**Nothing third-party is redistributed by this project.** yt-dlp and ffmpeg are
downloaded from their own official release pages on first run, into your own
application-data folder.

The **built `.exe`** is a different matter: PyInstaller embeds a Python interpreter
and its libraries, so anyone redistributing that binary redistributes those too.
Everything involved — what's embedded, what's downloaded, trademarks, and exactly
what network connections the app makes — is set out in
**[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)**.

**No telemetry.** No analytics, no update check, no account. The only outbound
connections are fetching yt-dlp/ffmpeg on first run, and yt-dlp contacting the site
whose link you pasted.

### Not affiliated

DaVinci Resolve and Blackmagic Design are trademarks of Blackmagic Design Pty. Ltd.
YouTube is a trademark of Google LLC; Twitch of Twitch Interactive, Inc. This is an
independent, unofficial project, **not affiliated with or endorsed by** any of them.
It uses Blackmagic Design's documented, officially supported scripting API, and
bundles no part of Resolve.

---

## 📄 License

Released under the **[MIT License](LICENSE)** — do what you like with it, including
commercially, as long as the copyright notice and licence text come along. It comes
with no warranty.

Two things the MIT licence does **not** cover:

- **The content you download with it.** See [Legal](#-legal).
- **Components embedded in the built `.exe`.** The source here is MIT; the binary
  additionally contains a Python interpreter and its libraries, under their own
  licences. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) before
  redistributing a build.

---

## 🙏 Credits

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — does all the heavy lifting, and
  brings [support for hundreds of sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
  with it
- **[ffmpeg](https://ffmpeg.org/)** — trimming and merging
- **[AutoSubs](https://github.com/tmoroney/auto-subs)** — the reference for how a
  Resolve plugin can live outside Resolve's own UI. Reading its source solved two
  problems that had me stuck.
- **Blackmagic Design** — for shipping a scripting API at all

---

<div align="center">

**© 2026 [haej](https://github.com/hajdawery)**

Made for editors who are tired of the download-trim-import shuffle.

</div>
