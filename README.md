<div align="center">

<img src="assets/logo.png" alt="YEETingus" width="130">

# YEETingus

**Grab any part of a YouTube video or Twitch clip and put it straight into your DaVinci Resolve timeline.**

Paste a link, set the in/out point, and press one button. No browser, full-video download, or manual importing.

![version](https://img.shields.io/badge/version-1.3.1-edff00?style=flat-square&labelColor=1a1a1a)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-0078d4?style=flat-square&labelColor=1a1a1a)
![resolve](https://img.shields.io/badge/DaVinci%20Resolve-Studio-ff5f56?style=flat-square&labelColor=1a1a1a)
![license](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square&labelColor=1a1a1a)

</div>

---

## What it does

YEETingus is a small DaVinci Resolve tool for quickly grabbing video clips from YouTube and Twitch.

Instead of downloading a whole video, trimming it, importing it and dragging it onto the timeline, YEETingus downloads only the part you need and places it at your playhead.

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
- H.264 is preferred because it plays and scrubs well in Resolve.
- Clips are converted to H.264 when needed, so they remain playable in Resolve.
- Whole videos above 1080p are converted to H.264 too, or capped at 1080p instead if you prefer to skip the wait.
- The log reports the actual resolution, codec, and frame rate of the resulting file.

### File handling
- Clips are stored in your Videos folder by default.
- Files are placed in folders named `<video ID> - <title> - <channel>`.
- Existing clips are never overwritten.
- Whole videos are saved once and reused on later requests.
- Filenames are cleaned up for Windows. Accented Latin text is folded to plain ASCII (`Zażółć` → `Zazolc`); other scripts such as 日本語 are left readable.

### Quality of life
- Stop a download at any time.
- Clear progress states: downloading, merging, converting, inserting, etc.
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
- **Whole videos above 1080p**
  - **Keep quality** — keep the original resolution and convert to H.264.
  - **Keep it quick** — skip conversion and cap the download at 1080p.
- **Tool versions and paths** — yt-dlp, ffmpeg, and Deno.
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

## Codecs and smooth playback

YouTube normally provides H.264 up to 1080p. At 1440p and 4K, it usually provides VP9 or AV1 instead.

Resolve does not handle those codecs well enough for smooth high-resolution playback.

Because of this:

- **Clips** are converted to H.264 automatically.
- **Whole videos above 1080p** are converted to H.264 when **Keep quality** is selected.
- **Keep it quick** skips conversion but limits whole videos to 1080p.

Full-quality conversion takes extra time — roughly 60% of the video's length in typical testing.

For example, a 10-minute 4K video may need around 6 additional minutes to convert.

This is intentional: the goal is a file that Resolve can actually play smoothly.

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
      ├── ffmpeg ── trims / converts video
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

### A whole 4K video stutters or goes Media Offline

This usually means the file is VP9 or AV1.

Go to:

**Settings → Whole videos above 1080p → Keep quality**

Download the video again. It will be converted to H.264.

If you want it faster, use **Keep it quick**, which limits whole videos to 1080p.

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

Check the codec in the log. VP9/AV1 at high resolutions can be difficult for Resolve to decode.

Clips with an in/out point should normally be H.264.

---

## Known limitations

- **29.97/59.94 drop-frame timelines:** playhead placement can be off by a frame or two.
- **Linux:** not tested or supported.
- **Intel Macs:** not tested or shipped; Apple Silicon is the supported macOS platform.
- **macOS:** ffmpeg must be installed manually.
- **macOS Light Mode:** the title bar may remain light.
- **Whole videos above 1080p:** require conversion when keeping full quality.
- **No automatic app updates yet.**
- **Mostly tested with YouTube and Twitch.** yt-dlp supports many other sites, but they are not officially tested by this project.
- **Age-restricted videos:** currently unsupported because no signed-in browser session is used.

---

## Legal

Downloading videos may violate the terms of service of the site you download from. Copyright belongs to the content owner.

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
