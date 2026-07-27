# YEETingus

Pull a time-ranged fragment of a YouTube video with
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and paste it straight onto the current
DaVinci Resolve timeline — a Resolve equivalent of Yoink for Premiere.

© 2026 Karol Szaciłło (GRApedia)

---

## Quick start

```bash
py -3.13 build.py      # -> dist\YEETingus.exe  (~10 MB, no Python needed to run it)
py -3.13 install.py    # -> %LOCALAPPDATA%\YEETingus\ + Resolve's Scripts menu
```

Restart Resolve, then: **Workspace → Scripts → Utility → YEETingus**.

Run from source instead with `py -3.13 backend\yeet_app.py`, or
`py -3.13 install.py --dev` to point the menu entry at your source copy.

> **Upgrading from "YEET"?** `install.py` handles it: the downloaded tool cache
> (yt-dlp + ffmpeg) and `settings.json` are moved to the new folder, and the old
> exe, shim and `YEET.lua` menu entry are deleted so Resolve doesn't list two
> entries. Nothing is re-downloaded and no settings are lost.

## Requirements

| | |
|---|---|
| DaVinci Resolve **Studio** | running, with a project and timeline open |
| Scripting enabled | Preferences → System → General → External scripting using → **Local** |
| Python (to build only) | **3.6–3.13** — see below |
| yt-dlp + ffmpeg | **fetched automatically on first run** → `%LOCALAPPDATA%\YEETingus\bin` |
| OS | Windows (the launcher shim, process-tree kill and ffmpeg build are Windows-specific) |

External scripting is a Studio feature — the free version likely won't work.

### The Python version constraint

`fusionscript.dll` is a version-specific CPython C extension (no `Py_LIMITED_API`),
so it only loads into an interpreter matching its ABI. Blackmagic's README claims
"3.6+", but the real ceiling lags new Python releases until they rebuild it.

Verified against Resolve's June 2026 `fusionscript.dll`:

| Python | Result |
|---|---|
| 3.11 | imports OK |
| 3.13 | imports OK |
| 3.14 | **segfault** |

The frozen exe embeds whichever interpreter builds it, so **anyone running
YEETingus.exe needs no Python at all** — the constraint only applies to building and to
running from source. `build.py` refuses to run on an unsupported version and
`resolve_bridge.python_is_supported()` guards it at runtime; Settings shows the
interpreter in use and whether the library was found.

`resolve_bridge.MAX_PY` is the single source of truth. To raise it, confirm
`py -3.X -c "import DaVinciResolveScript"` exits 0 (rather than crashing), then
bump that one constant.

## How it works

One standalone app; no server, no port. It drives yt-dlp and talks to Resolve
through Resolve's **official external Python scripting API**:

```
  Resolve  Workspace > Scripts > Utility > YEETingus
      |  YEETingus.lua spawns the app (never blocks Resolve)
      v
  YEETingus.exe  (Tkinter UI)
      |-- subprocess --> yt-dlp + ffmpeg     (downloads only the requested section)
      '-- import ------> resolve_bridge.py --> fusionscript.dll
                                                    |
                                              DaVinci Resolve
                                       (media pool import + timeline insert)
```

Three non-obvious things the launcher has to get right — each caused a silent
"clicking the menu does nothing" failure at some point:

1. **No environment variables.** Resolve's embedded Lua doesn't reliably expose
   `%LOCALAPPDATA%`, so `install.py` bakes absolute paths into the launcher from
   `resolve/YEETingus.lua.in`. (AutoSubs hardcodes its paths for the same reason.)
2. **Launch via LuaJIT FFI `ShellExecuteA`**, not `os.execute` — the latter is
   unreliable in Resolve's Lua host.
3. **Launch the `.bat`, not the `.exe`.** Resolve exports `PYTHONHOME`, and a
   PyInstaller exe that inherits it segfaults instantly. `launch_yeetingus.bat` clears
   it first.

Resolve caches the launcher when it builds the Scripts menu, so **restart Resolve
after reinstalling**. Diagnostics land in `%LOCALAPPDATA%\YEETingus\launcher.log`.

## UI

- **1 Source** — video link, in point, end point (`SS`, `MM:SS`, `HH:MM:SS`), plus:
  - **Clip length** shortcuts — `15s` · `30s` · `1m`, and a `▾` dropdown with
    2 / 5 / 10 min. Each sets the end point to the in point plus that length.
  - **Copy in point from link** — reads a share link's `?t=` value
    (`169`, `169s`, `2m49s`, `1h2m3s`, `start=`, `#t=`)
- **2 Max quality** — Best available (default) / 2160p / 1440p / 1080p / 720p / 480p.
  The metadata probe logs which resolutions the video actually has; asking for more
  than it offers falls back to its best instead of failing.
- **3 Insert clip by** — Playhead, or Start of timeline
- **YEET (download & insert)** — becomes a red **STOP** while running: kills yt-dlp
  *and its ffmpeg children* and deletes partials so the clip number stays free.
- **Open folder** · **Show log** · **Settings**
- **Progress** — `Reading video info` → `Preparing download` → `Downloading NN%`
  → `Merging & trimming` → `Pasting into timeline`
- **Log** — collapsed by default; **Show log** expands it (and grows the window to
  fit, so it's never hidden behind a resize). It keeps recording while collapsed,
  and opens itself automatically on failure. Live yt-dlp output; after each paste
  it recaps the video title, channel and true resolution/codec/fps, flags a
  slow-decoding codec if there is one, then a highlighted credit reminder.
- **Header** — status pill: accent = connected (`project · timeline`), red =
  Resolve missing / no project / no timeline. `↻` re-checks.

### Settings

`%LOCALAPPDATA%\YEETingus\settings.json`, written atomically and preserved across
reinstalls (install.py only replaces the exe and launcher).

- **Clip storage** folder, with a Browse picker
- **Tools** — resolved yt-dlp/ffmpeg paths, the detected Resolve library and
  Python version, and an **Update yt-dlp** button (`-U` on the standalone binary,
  or a pip upgrade when running from source)

## Where clips land

```
%TEMP%\yeet_downloads\
  dQw4w9WgXcQ - Rick Astley - Never Gonna Give You Up (4K Remaster) - Rick Astley\
      dQw4w9WgXcQ-RickAstley-c001.mp4
      dQw4w9WgXcQ-RickAstley-c002.mp4
```

Folder is `<VIDEO ID> - <title> - <channel>` (readable, spaces kept). Files are
`<videoid>-<ChannelName>-cNNN` — the channel is squashed to a single token with
spaces and punctuation stripped (`Rick Astley` → `RickAstley`, capped at 32 chars)
so the filename has exactly three `-`-separated fields. Numbering comes from what's
already on disk, so **nothing is ever overwritten**. If the channel is unknown the
segment is dropped: `<videoid>-cNNN`.

Names are sanitised for every OS: letters, digits, marks and a small punctuation
whitelist survive — accented and CJK titles stay readable while emoji, symbols,
control characters and `<>:"/\|?*` are dropped. Reserved Windows names (`CON`,
`NUL`, …) get prefixed, trailing dots/spaces stripped, lengths capped.

If a title or channel is made **entirely** of characters we strip (an all-emoji
title, say), that field becomes **`unnamed`** rather than vanishing —
`emo01 - unnamed - unnamed\emo01-unnamed-c001.mp4`. A field we simply never had
(metadata probe failed) is still omitted instead, so `unnamed` always means "there
was a name, but nothing in it was usable".

Downloads use `--download-sections "*IN-END" --force-keyframes-at-cuts`, so trims
are frame-accurate rather than snapping to the nearest keyframe.

## Codecs and smooth playback

YEETingus asks yt-dlp to sort formats by resolution first, then prefer **H.264**
(`-S res,vcodec:h264`). H.264 hardware-decodes and scrubs well in Resolve; VP9 is
worse and AV1 is considerably worse.

The catch is what YouTube actually offers:

| Resolution | Codecs available |
|---|---|
| 2160p / 1440p | VP9, AV1 only |
| 1080p and below | **H.264**, VP9, AV1 |

So anything at 1080p or below arrives as H.264 and plays back fine. At 1440p/4K
there is no H.264 to choose — you necessarily get VP9 or AV1.

The sort order matters here: preference must not cost resolution. A naive
"H.264 else anything" fallback would silently cap **Best available** at 1080p,
since that's as high as YouTube's H.264 goes. Sorting keeps 4K at 4K.

**If a 1440p/4K clip stutters**, use Resolve's own proxies rather than expecting
the app to transcode: right-click the clip in the Media Pool → **Generate Optimized
Media** (or set the format under Project Settings → Master Settings → Optimized
Media). Resolve manages that cache and swaps proxies in transparently, which beats
anything this tool could do — and avoids the 10–45× disk cost of writing DNxHR
copies (measured: 1080p H.264 ≈ 29 MB/min, DNxHR LB ≈ 280, SQ ≈ 877, HQ ≈ 1323).

The log points this out when it applies: after a paste, if the clip isn't H.264 it
names the codec and suggests Generate Optimized Media.

## Layout

| Path | Role |
|---|---|
| `backend/yeet_app.py` | UI + orchestration |
| `backend/theme.py` | palette, rounded cards/buttons, vector icons |
| `backend/deps.py` | finds or downloads yt-dlp & ffmpeg |
| `backend/naming.py` | filesystem-safe names, URL parsing |
| `backend/config.py` | persisted settings |
| `backend/resolve_bridge.py` | Resolve import + timeline insert |
| `backend/version.py` | version + authorship |
| `resolve/YEETingus.lua.in` | Scripts-menu launcher template |
| `resolve/launch_yeetingus.bat` | clears `PYTHONHOME` before starting the exe |
| `build.py` / `install.py` | freeze / install |

## Known limitations

- **Drop-frame timecode** — playhead placement uses non-drop-frame math, so
  29.97/59.94 timelines may be off by a frame or two.
- **No transcode on ingest** — deliberate. H.264 is preferred where it exists, and
  Resolve's Generate Optimized Media handles the 1440p/4K VP9/AV1 case better than
  a bundled DNxHR pass would. See *Codecs and smooth playback*.
- **yt-dlp breakage** — YouTube changes extraction periodically; use
  **Update yt-dlp** in Settings.
- **No app icon** — `build.py` picks up `assets\yeet.ico` if you add one.

## Legal

Downloading YouTube video violates YouTube's Terms of Service. This is a private
reference/editing convenience tool; think carefully before using pulled footage in
published work, and credit sources.

ffmpeg is **downloaded, not redistributed** (from yt-dlp's FFmpeg-Builds), which
keeps its GPL obligations out of this package. yt-dlp is public domain (Unlicense).
