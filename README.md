<div align="center">

<img src="assets/logo.png" alt="YEETingus" width="130">

# YEETingus

**An open-source media ingestion tool for video editors: grab the part of a video you have the right to use and put it straight into your DaVinci Resolve timeline.**

Paste a link, set the in/out point, and press one button. No browser, no full-video download, no manual importing, no conversion step — the clip arrives ready to scrub.

![version](https://img.shields.io/badge/version-1.4.0-edff00?style=flat-square&labelColor=1a1a1a)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-0078d4?style=flat-square&labelColor=1a1a1a)
![resolve](https://img.shields.io/badge/DaVinci%20Resolve-Studio-ff5f56?style=flat-square&labelColor=1a1a1a)
![license](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square&labelColor=1a1a1a)

</div>

---

## What it does

YEETingus is an open-source media ingestion tool for video editors. It retrieves media you have the right to use and prepares it for editing workflows such as DaVinci Resolve. This includes your own uploads, openly licensed material, and promotional media made available for creator, press, or editorial use.

Instead of downloading a whole video, trimming it, converting it, importing it and dragging it onto the timeline, YEETingus downloads only the part you need, converts it into a file Resolve scrubs smoothly, and places it at your playhead.

![YEETingus](assets/screenshot.jpg)

## Features

### Clipping
- Download only the selected part of a video.
- Frame-accurate in/out points.
- Enter timestamps as `90`, `1:30`, or `00:01:30`.
- Quick lengths: `15s`, `30s`, `90s`, `2m`, `5m`, `10m`, or **Entire**.
- `?t=` timestamps in shared links are detected automatically.
- The end point can automatically follow your default clip length.
- Leave both points at `00:00` to download the whole video.

### DaVinci Resolve
- Insert at the **current playhead** or at the **start of the timeline**.
- Live connection status shows whether Resolve, a project, and a timeline are available.
- The playhead position is read when the clip is inserted, so no refresh is needed.
- Launch from `Workspace → Scripts → Utility`.
- **Download only** mode works without Resolve being open.

### Quality and playback
- Choose up to **Best, 2160p, 1440p, 1080p, 720p, or 480p**.
- The app checks which quality the video actually provides.
- Full resolution at every quality — nothing is capped to make Resolve happy.
- Every download is converted into an **editing intermediate with a keyframe every half second**, so Resolve scrubs, steps and jumps through it instantly — using the GPU's AV1 encoder when there is one (seconds, even for 4K60), otherwise the CPU.
- The log reports the actual resolution, codec, and frame rate of the resulting file, and what was done to it.

### File handling
- Clips are stored in your Videos folder by default.
- Files are placed in folders named `<video ID> - <title> - <channel>`.
- Existing clips are never overwritten.
- Whole videos are saved once and reused on later requests.
- Filenames are cleaned up for Windows. Accented Latin text is folded to plain ASCII (`Zażółć` → `Zazolc`); other scripts such as 日本語 are left readable.

### Quality of life
- Stop a download at any time.
- Clear progress states: downloading, merging, preparing, inserting, etc.
- Optional collapsible log.
- UI scales correctly on different display sizes.
- Dark Windows title bar.
- Built-in **Update yt-dlp** button.
- No Python installation is needed to run the built app.

---

## Requirements

| Requirement | Details |
|---|---|
| OS | Windows or macOS on Apple Silicon |
| DaVinci Resolve | Studio is the supported configuration |
| Resolve scripting | `Preferences → System → General → External scripting using → Local` |
| Python | Only needed to build/run from source: 3.6–3.13 |
| yt-dlp | Downloaded automatically on first run |
| ffmpeg | Downloaded automatically on Windows; install manually on macOS |
| JavaScript runtime | Deno is downloaded automatically |

> **Important:** External scripting must be enabled in Resolve or YEETingus cannot connect to it.

The built application includes its own Python runtime, so normal users do **not** need Python.

---

## Installation

### Download a release

Get it from the [latest release](https://github.com/hajdawery/yeetingus/releases/latest). No Python needed.

- **Windows** — download `YEETingus-windows-x86_64.exe` and run it.
- **macOS** — download `YEETingus-Mac-ARM.zip`, unzip it, and run `python3 install.py` from the unzipped folder. Also run `brew install ffmpeg`.

### Or build it yourself

Recommended if you would rather not trust a pre-built binary. It also avoids the antivirus and Gatekeeper warnings below.

**Windows**

```bash
git clone https://github.com/hajdawery/yeetingus.git
cd yeetingus

py -3.13 build.py
py -3.13 install.py
```

**macOS**

```bash
git clone https://github.com/hajdawery/yeetingus.git
cd yeetingus

brew install ffmpeg
python3.13 build.py
python3.13 install.py
```

Restart DaVinci Resolve after installing, either way. It caches the Scripts menu, so until you do you are still running the previous version.

The build creates:

- Windows: `dist\YEETingus.exe`
- macOS: `dist/YEETingus.app`

You can also run directly from source. On Windows:

```bash
py -3.13 backend\yeet_app.py
```

On macOS:

```bash
python3.13 backend/yeet_app.py
```

Use `install.py --dev` if you want the Resolve menu entry to launch your source copy.

---

## macOS: ffmpeg

Windows gets ffmpeg automatically from the builds maintained for yt-dlp.

On Apple Silicon there is no equivalent trusted distribution that YEETingus can bundle, so macOS requires:

```bash
brew install ffmpeg
```

If you already have a trusted ffmpeg installation, you can point YEETingus to it with `YEET_FFMPEG`.

`YEET_FFPROBE`, `YEET_YTDLP`, and `YEET_DENO` can also be used to provide custom tool paths.

---

## JavaScript runtime

YouTube now uses JavaScript challenges that yt-dlp sometimes needs to solve.

YEETingus downloads **Deno** automatically on first run. It is a one-time download of roughly 40 MB.

If Deno is already installed — on your `PATH`, or in `~/.deno/bin` where its own installer puts it — YEETingus uses that and downloads nothing.

If the download fails, for example on a first run with no network, **Settings → Install JavaScript runtime** retries it. That button only appears while Deno is missing.

---

## Antivirus warnings

Windows Defender and other scanners may flag the pre-built Windows executable as a false positive.

This happens because YEETingus:

- is a new, unsigned PyInstaller application;
- downloads other executables;
- starts and stops child processes;
- writes to DaVinci Resolve's Scripts folder.

The source code is public and not obfuscated.

If you do not trust the pre-built binary, build it yourself:

```bash
py -3.13 build.py
```

Release builds also provide SHA-256 checksums. Code signing is planned.

---

## macOS Gatekeeper

Pre-built unsigned macOS applications may be blocked by Gatekeeper.

The recommended solution is to build the application yourself. If you are using a downloaded build, you can also try:

- Right-click → **Open**
- **System Settings → Privacy & Security → Open Anyway**

Apple Developer signing and notarisation are planned.

---

## How to use

1. Open a project and timeline in DaVinci Resolve.
2. Open `Workspace → Scripts → Utility → YEETingus`.
3. Paste a YouTube or Twitch link.
4. Set the in/out points, or choose a clip length.
5. Choose the maximum quality.
6. Choose **Playhead** or **Start of timeline**.
7. Press **YEET**.

The clip is downloaded, processed, imported and placed on the timeline.

Use **Download only** if you just want the file.

The main button becomes **STOP** while a job is running.

---

## Settings

Settings are saved between installations.

### Available options

- **Clip storage folder** — Videos by default (`Movies` on macOS).
- **Default clip length** — `15s`, `30s`, `60s`, or `90s`.
- **Tool versions and paths** — yt-dlp, ffmpeg, and Deno, plus which encoder the conversion will use on this machine.
- **Resolve diagnostics** — scripting library and Python compatibility.
- **Update yt-dlp**.
- **Install JavaScript runtime** when Deno is missing.

---

## Where clips are saved

By default:

```text
Windows:
%USERPROFILE%\Videos\YEETingus\

macOS:
~/Movies/YEETingus/
```

Example:

```text
dQw4w9WgXcQ - Never Gonna Give You Up - Rick Astley\
├── dQw4w9WgXcQ-RickAstley-c001.mp4
└── dQw4w9WgXcQ-RickAstley-c002.mp4
```

Nothing is overwritten.

Whole videos use:

```text
<videoid>-<ChannelName>-full.mp4
```

If that file already exists and is complete, YEETingus reuses it instead of downloading it again.

---

## Why the clip is converted, and what that means for you

Videos on the web are made for *watching*, not editing. To keep them small, the site stores a full picture only every few seconds and just the changes in between. That is fine for playback, but when you scrub a timeline, Resolve has to rebuild every frame from the last full picture — up to a few hundred frames at 4K — and that is what makes a raw download feel sticky and slow on the timeline.

So YEETingus converts every clip into a file made for editing: a full picture every half second. Resolve then scrubs, steps and jumps through it instantly. There is nothing to configure; the app picks the fastest way your computer can do it:

| Your computer | How it converts | How fast (4K, 60 fps) |
|---|---|---|
| A recent graphics card that can encode AV1 — NVIDIA RTX 40 or 50 series, Intel Arc, AMD RX 7000 | on the graphics card | a one-minute clip in about 10 seconds |
| Anything else (older graphics cards, all Macs) | on the processor, using a simple, universal format | a one-minute clip in 10–25 seconds on a modern processor |

What that costs and where the limits are, in plain terms:

- **Files are bigger than the download — roughly 1.5 to 3 times.** An editing-friendly file has far more full pictures in it than a streaming file. That is the whole point, and it is a normal size for editing material (professional editing formats are 50–200 times bigger). A one-minute 4K clip is typically 130–200 MB.
- **Quality does not visibly change.** The conversion is tuned so that text, fine detail and gradients look the same as the download. We measured it; the numbers are in [BENCHMARK.md](BENCHMARK.md).
- **Full resolution is always kept.** Nothing is capped at 1080p any more.
- **HDR and 10-bit video are kept — but only on the graphics-card path.** If your clip is HDR and your computer converts on the processor instead, the result is ordinary 8-bit SDR. The log tells you when this happens.
- **Resolve 18.1 or newer is needed for clips made on the graphics-card path.** Older Resolve versions cannot play AV1 at all. If you are on an older Resolve, the processor path works everywhere.
- **On Macs everything goes through the processor path**, because Apple's chips cannot encode AV1. It is still fast, but 4K clips are a little heavier for Resolve to play back than on a PC with a recent graphics card.
- **Very long 4K downloads on the processor path are heavy for Resolve to play** (scrubbing is still instant). For whole 4K videos on such a machine, use Resolve's *Generate Optimized Media* or download at 1440p.
- **Audio is copied untouched** (AAC). It is only converted when the site offered nothing but Opus, which some Resolve versions cannot play.
- **Clips are frame-exact** at the in point and end point you typed, to within one frame.
- **Clips downloaded by an older version of YEETingus** are reused as they are. Delete the file (the log shows the folder) to download and convert it the new way.

Why not just hand Resolve the download as it is? We tried — it is instant and loses nothing, but on a 4K timeline it scrubbed badly for the reason above, and the converted clips scrubbed perfectly. The full comparison, including the other formats that were tested and rejected, is in [BENCHMARK.md](BENCHMARK.md).

---

## How it works

YEETingus is a standalone application. It does not run a server or listen on a port.

```text
DaVinci Resolve
      │
      ▼
YEETingus
      │
      ├── yt-dlp ── downloads video
      ├── ffmpeg ── converts it into a seek-friendly intermediate (backend/media.py decides how)
      └── Deno ──── solves YouTube JS challenges
      │
      ▼
Resolve scripting API
      │
      ├── imports media
      └── inserts it into the timeline
```

The Resolve-specific code is kept in `resolve_bridge.py`, making it possible to add support for another editor later without rebuilding the whole application.

---

## Troubleshooting

### YEETingus does nothing from the Resolve menu

1. Restart Resolve.
2. Check `launcher.log`:
   - Windows: `%LOCALAPPDATA%\YEETingus\`
   - macOS: `~/Library/Application Support/YEETingus/`
3. Run the installer again and check its verification output.

### Resolve is not connected

Make sure:

- Resolve is running.
- A project and timeline are open.
- `External scripting using` is set to **Local**.
- The Resolve diagnostic in Settings shows a supported scripting setup.

Click `↻` next to the connection status to check again.

### A 4K video stutters or goes Media Offline

Check the **Quality** line in the log. If it says `av1`, the file was made with your GPU's AV1 encoder, and the same GPU decodes it — so an older Resolve version is the likely cause: AV1 playback needs Resolve 18.1 or later.

A whole video downloaded by an older version of YEETingus is reused as-is. Delete it (the log shows the folder) and download again to have it prepared the new way.

### "No JavaScript runtime"

Open Settings and check the `JS:` line.

If Deno is missing, use **Install JavaScript runtime**.

If yt-dlp is old, use **Update yt-dlp**.

### HTTP 403

Common causes:

- **Age-restricted video:** YEETingus does not use a signed-in session, so it cannot download it.
- **YouTube changed something:** update yt-dlp and try again.
- **Missing Deno:** check the `JS:` line in Settings.

### Requested 4K but got 1080p

The video does not offer 4K. YEETingus falls back to the best available quality instead of failing.

### 4K clip playback is slow

Check the **Video** line in Settings → Tools: without a hardware AV1 encoder everything is converted on the CPU to MPEG-4, which Resolve decodes in software — fine for 1080p and 1440p, but 4K60 is heavy for any software decoder. Generate Optimized Media in Resolve for those clips, or download at 1440p.

---

## Known limitations

- **Every clip is converted, so it takes a few seconds** after the download (about 10 seconds per minute of 4K on a recent graphics card, up to about 25 on the processor) and the file is 1.5–3 times bigger than the download. See [above](#why-the-clip-is-converted-and-what-that-means-for-you) for why.
- **Resolve 18.1 or newer** is needed to play clips made on a computer with an AV1-capable graphics card.
- **HDR is kept only on the graphics-card path**; on the processor path HDR clips become SDR.
- **Macs always use the processor path** (no AV1 encoding on Apple chips).
- **29.97/59.94 drop-frame timelines:** playhead placement can be off by a frame or two.
- **Linux:** not tested or supported.
- **Intel Macs:** not tested or shipped; Apple Silicon is the supported macOS platform.
- **macOS:** ffmpeg must be installed manually.
- **macOS Light Mode:** the title bar may remain light.
- **No automatic app updates yet.**
- **Mostly tested with YouTube and Twitch.** yt-dlp supports many other sites, but they are not officially tested by this project.
- **Age-restricted videos:** currently unsupported because no signed-in browser session is used.

---

## Legal

YEETingus is for media you have the right to use: your own uploads, openly licensed material, and promotional media made available for creator, press, or editorial use. Downloading other videos may violate the terms of service of the site you download from, and copyright belongs to the content owner.

Fair use / fair dealing can apply to commentary, criticism, review, teaching, and similar uses, but the rules depend on your country and situation. YEETingus does not give you permission to use copyrighted material.

**You are responsible for what you download and publish. Credit your sources.**

YEETingus does not collect telemetry, analytics, or account information.

The app only makes network connections to:

- download yt-dlp, ffmpeg, and Deno when required;
- access the website corresponding to the link you provide.

DaVinci Resolve, Blackmagic Design, YouTube, Twitch, macOS, Apple Silicon, and Windows are trademarks of their respective owners. YEETingus is an independent project and is not affiliated with or endorsed by them.

---

## License

YEETingus is released under the **MIT License**.

You may use and sell it commercially as long as the copyright notice and licence are included.

The MIT licence for this project does not cover:

- content downloaded with the application;
- third-party components included in a built binary.

See `THIRD-PARTY-NOTICES.md` before redistributing a built application.

---

## How this was built

**This project was vibecoded, with heavy use of Claude.**

It was built to solve a real editing problem and tested against real DaVinci Resolve installations.

The source code is public and readable. Bugs are still my responsibility — if something breaks, please open an issue.

---

## Credits

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — video downloading
- **[ffmpeg](https://ffmpeg.org/)** — trimming, merging and conversion
- **[AutoSubs](https://github.com/tmoroney/auto-subs)** — reference for external Resolve tools
- **Blackmagic Design** — for the Resolve scripting API

<div align="center">

**© 2026 [haej](https://github.com/hajdawery)**

Made for editors who are tired of the download → trim → import shuffle.

</div>
