<div align="center">

<img src="assets/icon-tile.png" alt="YEETingus" width="130">

# YEETingus

**Media ingestion for video editors: grab the part of a video you have the right to use and put it straight onto your timeline — DaVinci Resolve or Premiere Pro.**

Paste a link, set the in/out point, press one button. No browser, no full-video download, no manual importing, no conversion step — the clip arrives ready to scrub.

![version](https://img.shields.io/badge/version-2.0.0-fcca74?style=flat-square&labelColor=1a1a1a)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-0078d4?style=flat-square&labelColor=1a1a1a)
![resolve](https://img.shields.io/badge/DaVinci%20Resolve-Studio-ff5f56?style=flat-square&labelColor=1a1a1a)
![premiere](https://img.shields.io/badge/Premiere%20Pro-26.3%2B-9999ff?style=flat-square&labelColor=1a1a1a)
![license](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square&labelColor=1a1a1a)

</div>

---

## What it does

YEETingus retrieves media you have the right to use — your own uploads, openly licensed material, promotional media made available for creator, press or editorial use — and prepares it for editing.

Instead of downloading a whole video, trimming it, converting it, importing it and dragging it onto the timeline, YEETingus downloads only the part you need, converts it into a file your editor scrubs smoothly, and places it at your playhead.

![YEETingus](assets/screenshot.jpg)

## 2.0

2.0 is a rewrite of everything you can see. The download-and-prepare pipeline underneath is the one from 1.4, unchanged and still measured (`BENCHMARK.md`).

- **A new app.** Native window, ~10 MB, dark and light theme, a layout that follows the window instead of fighting it. Controls on the left, content on the right, one button that does the thing.
- **Clip history.** Every clip you've ever made, newest first, with thumbnail, title, channel, length, size and date. From each one: insert it into the timeline again, play it, open the video's page, open its folder, delete it. Click a title or a channel to copy it.
- **Link preview** the moment you paste, with a green **Ready** when it checks out — and a red warning when the video is age-restricted, *before* you waste a download on it.
- **A length slider** next to the presets, for anything from one second to five minutes.
- **Premiere Pro.** See below. Bring a helmet.
- **First-run setup** that asks which editor you use and gets you there.

`FEATURES.md` has the complete list.

## Features

### Clipping
- Download only the selected part of a video; frame-accurate in/out points.
- Timestamps as `90`, `1:30` or `00:01:30`; presets `15s`, `30s`, `60s`, **Whole**, or the slider.
- `?t=` timestamps in shared links set the in point automatically.
- The end point follows your default clip length when you type an in point.

### The editor
- **Insert at the playhead or at the start of the timeline.**
- Live connection status: your project and timeline (Resolve) or sequence (Premiere), and what's missing if something is.
- **Download only** works with no editor open at all.

### Quality and playback
- Choose up to **Best, 2160p, 1440p, 1080p, 720p or 480p**; the app checks what the video actually offers and says so.
- Full resolution at every quality — nothing is capped to make an editor happy.
- Every download becomes an **editing intermediate with a keyframe every half second**, so scrubbing, stepping and jumping are instant: your GPU's AV1 encoder for Resolve, HEVC for Premiere (see below), the CPU if you have neither.

### File handling
- Clips live in your Videos folder, in `<video ID> - <title> - <channel>` folders, with a small `.json` beside each one recording where it came from.
- Existing clips are never overwritten; whole videos are saved once and reused.
- Filenames are cleaned up for every OS. Accented Latin folds to ASCII (`Zażółć` → `Zazolc`); other scripts stay readable.

---

## DaVinci Resolve

Works with **DaVinci Resolve Studio**. External scripting — a program outside Resolve talking to it — is a Studio feature; on the free version you can still use **Download only** and drag the file in yourself.

Turn it on once: `Preferences → System → General → External scripting using → Local`. YEETingus tells you if it isn't.

---

## Premiere Pro

It works. Video and audio land on V1/A1 at your playhead, from the same button. Getting there required going through Adobe's extensibility platform, so, a word about that.

### The setup

1. Settings → Editor → **Premiere Pro** → **Install the Premiere panel**. YEETingus packages its panel and hands it to Adobe's own plugin installer. No developer mode, no "UXP Developer Tool", no signing ceremony. Ten seconds.
2. In Premiere: **Window → UXP Plugins → YEETingus**. Dock it somewhere small and **save your workspace**. Premiere then brings it back on every launch. You never touch it again.
3. Have YEETingus running. The panel finds it by itself.

That's it — one-time. The panel has no controls; it's a green dot.

### A word about UXP

Premiere Pro has no scripting interface you can reach from outside it. None. Resolve has had one for years — a program on the same machine can ask it what's open and put a clip on the timeline. Premiere offers "UXP": a JavaScript sandbox that runs *inside* Premiere, in a panel, and only while that panel is open.

So every tool like this one — AutoSubs, Taperat, YEETingus — has to ship a panel whose whole job is to sit there and be a phone line. Fine. Except the sandbox also can't:

- **start a program.** `shell.openExternal("yeetingus://")` → *"URI scheme yeetingus is not accepted."* `shell.openPath("YEETingus.exe")` → *"Extension .exe is not accepted."* Tested, both. The panel cannot launch the app it exists to talk to. You start YEETingus yourself, like an animal.
- **be opened from outside.** No API, no command line, nothing. Hence the workspace dance.
- **use a normal DOM or CSS.** A subset, with its own widgets, so nothing you already have carries over.

And then there's the codec.

### A word about AV1

It's 2026. AV1 is the codec YouTube serves you for anything past 1080p, the codec every GPU from the last four years encodes and decodes in hardware, the codec Resolve has played since 18.1. YEETingus makes its editing intermediates in AV1 for exactly those reasons: fast to make, instant to scrub, half the size.

**Premiere Pro 26.3 does not decode AV1.** Import an AV1 MP4 and you get a waveform. Audio only. No error, no warning, just silently less video than you gave it. This is the flagship NLE of the company that sells you Media Encoder.

So when Premiere is your editor, YEETingus encodes **HEVC** instead — same half-second keyframes, same hardware path, Premiere plays it fine — and if you insert an older AV1 clip from the history, it quietly makes an HEVC copy beside it first. You'll never notice. Adobe should.

---

## Requirements

| Requirement | Details |
|---|---|
| OS | Windows 10/11, or macOS on Apple Silicon |
| DaVinci Resolve | **Studio**, with `External scripting using → Local` |
| Premiere Pro | 26.3 or newer, with Creative Cloud desktop installed (its plugin installer is used) |
| yt-dlp, ffmpeg, Deno | Downloaded automatically on first run (macOS: `brew install ffmpeg`) |
| Python / Node / Rust | Only to build from source |

---

## Installation

### Download a release

Get it from the [latest release](https://github.com/hajdawery/yeetingus/releases/latest) and run the installer. On first launch YEETingus asks which editor you use and walks you through the one-time setup for it.

### Or build it yourself

```bash
git clone https://github.com/hajdawery/yeetingus.git
cd yeetingus
```

The service and the pipeline are Python (3.13); the window is Tauri (Rust + Node):

```bash
py -3.13 backend/service.py --port 47591 --token dev     # the engine, over localhost
cd app && npm install && npm run tauri dev                # the window
```

`build.py` freezes the service; `npm run tauri build` packages the app. Restart Resolve after installing either way — it caches its Scripts menu.

The 1.x Tkinter window (`backend/yeet_app.py`) still runs on the same engine, if you like it plain.

---

## Where clips are saved

Your Videos folder, in an app-named subfolder, one folder per video. Change it in Settings; existing clips are left where they are (your timelines reference them by path).

Windows: `%USERPROFILE%\Videos\YEETingus\` · macOS: `~/Movies/YEETingus/`

---

## Why the clip is converted

Handing the editor the download as-is is instant and lossless — and it scrubs like mud. YouTube puts a keyframe every five seconds, so every seek decodes up to 300 frames at 4K60. Seeking is the point of this tool, so every download is re-encoded with a keyframe every half second and no B-frames. That costs a few seconds and 1.5–3× the file size, and it's why the timeline feels instant. `BENCHMARK.md` has the numbers.

---

## Troubleshooting

**Resolve is not connected.** Resolve is running, a project and timeline are open, `External scripting using` is Local, and it's Studio. Click the status pill to re-check.

**Premiere panel not open.** Window → UXP Plugins → YEETingus, then save the workspace so it stays. The Settings card says whether the panel is installed and whether Premiere has it open.

**Premiere imported a clip as audio only.** It's an AV1 file from before Premiere was chosen as the editor, and Premiere remembers the audio-only import by path. Delete that item from the Project panel; inserting again from the history makes an HEVC copy and imports that.

**Age-restricted.** YEETingus uses no signed-in session, so it can't; the preview says so before you try.

**HTTP 403 / "no JavaScript runtime".** Settings → Update yt-dlp; check the JS line. YouTube changes things and yt-dlp catches up within days.

**Requested 4K, got 1080p.** The video doesn't offer 4K; the app took the best it has and said so in the log.

---

## Known limitations

- Every clip is converted, so it takes a few seconds after the download and the file is bigger than the download. See above for why.
- Resolve 18.1+ is needed to play AV1 clips; Premiere gets HEVC instead because it can't play AV1 at all.
- HDR is kept only on the GPU path; on the CPU path HDR clips become SDR.
- Macs use HEVC (VideoToolbox) for Premiere and the CPU path for Resolve — no AV1 encoder on Apple chips.
- 29.97/59.94 drop-frame timelines: playhead placement can be off by a frame or two.
- Linux and Intel Macs: not tested.
- No automatic app updates yet.
- Mostly tested with YouTube and Twitch.

---

## Legal

YEETingus is for media you have the right to use: your own uploads, openly licensed material, and promotional media made available for creator, press or editorial use. Downloading other videos may violate the terms of service of the site you download from, and copyright belongs to the content owner.

Fair use / fair dealing can apply to commentary, criticism, review, teaching and similar uses, but the rules depend on your country and situation. YEETingus does not give you permission to use copyrighted material.

**You are responsible for what you download and publish. Credit your sources.**

YEETingus collects no telemetry, analytics or account information. It connects only to download yt-dlp, ffmpeg and Deno when required, and to the site of the link you provide. Everything between the window, the service and the Premiere panel stays on your machine.

DaVinci Resolve, Blackmagic Design, Adobe, Premiere Pro, YouTube, Twitch, macOS, Apple Silicon and Windows are trademarks of their respective owners. YEETingus is an independent project and is not affiliated with or endorsed by them. Opinions about their extensibility platforms are the author's own, and earned.

---

## License

MIT. See `THIRD-PARTY-NOTICES.md` before redistributing a built application; the licence does not cover content downloaded with it or third-party components in a build.

---

## Credits

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — video downloading
- **[ffmpeg](https://ffmpeg.org/)** — trimming, merging and conversion
- **[AutoSubs](https://github.com/tmoroney/auto-subs)** — the look, and proof that a panel-as-phone-line works
- **Blackmagic Design** — for a scripting API that a program can actually call

<div align="center">

**© 2026 [haej](https://github.com/hajdawery)**

Made for editors who are tired of the download → trim → import shuffle.

</div>
