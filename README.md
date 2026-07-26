# YEET

Pull a time-ranged fragment of a YouTube video with
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and paste it straight onto the current
DaVinci Resolve timeline — a Resolve equivalent of Yoink for Premiere.

© 2026 haej (aka GRApedia)

---

## Quick start

```bash
py -3.13 build.py      # -> dist\YEET.exe  (~10 MB, no Python needed to run it)
py -3.13 install.py    # -> %LOCALAPPDATA%\YEET\ + Resolve's Scripts menu
```

Restart Resolve, then: **Workspace → Scripts → Utility → YEET**.

Run from source instead with `py -3.13 backend\yeet_app.py`.

## Requirements

| | |
|---|---|
| DaVinci Resolve **Studio** | running, with a project and timeline open |
| Scripting enabled | Preferences → System → General → External scripting using → **Local** |
| Python (to build only) | **3.6–3.13** — see below |
| yt-dlp + ffmpeg | **fetched automatically on first run** → `%LOCALAPPDATA%\YEET\bin` |
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
YEET.exe needs no Python at all** — the constraint only applies to building and to
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
  Resolve  Workspace > Scripts > Utility > YEET
      |  resolve/YEET.lua spawns the app (never blocks Resolve)
      v
  YEET.exe  (Tkinter UI)
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
   `resolve/YEET.lua.in`. (AutoSubs hardcodes its paths for the same reason.)
2. **Launch via LuaJIT FFI `ShellExecuteA`**, not `os.execute` — the latter is
   unreliable in Resolve's Lua host.
3. **Launch the `.bat`, not the `.exe`.** Resolve exports `PYTHONHOME`, and a
   PyInstaller exe that inherits it segfaults instantly. `launch_yeet.bat` clears
   it first.

Resolve caches the launcher when it builds the Scripts menu, so **restart Resolve
after reinstalling**. Diagnostics land in `%LOCALAPPDATA%\YEET\launcher.log`.

## UI

- **1 Source** — video link, in point, end point (`SS`, `MM:SS`, `HH:MM:SS`), plus
  **Copy in point from link** which reads a share link's `?t=` value
  (`169`, `169s`, `2m49s`, `1h2m3s`, `start=`, `#t=`)
- **2 Max quality** — Best available (default) / 2160p / 1440p / 1080p / 720p / 480p.
  The metadata probe logs which resolutions the video actually has; asking for more
  than it offers falls back to its best instead of failing.
- **3 Insert clip by** — Playhead, or Start of timeline
- **YEET** — download + insert. Becomes a red **STOP** while running: kills yt-dlp
  *and its ffmpeg children* and deletes partials so the clip number stays free.
- **Open folder** · **Show log** · **Settings**
- **Progress** — `Reading video info` → `Preparing download` → `Downloading NN%`
  → `Merging & trimming` → `Pasting into timeline`
- **Log** — collapsed by default; **Show log** expands it (and grows the window to
  fit, so it's never hidden behind a resize). It keeps recording while collapsed,
  and opens itself automatically on failure. Live yt-dlp output; after each paste
  it recaps the video title, channel and true resolution/fps, then a highlighted
  credit reminder.
- **Header** — status pill: accent = connected (`project · timeline`), red =
  Resolve missing / no project / no timeline. `↻` re-checks.

### Settings

`%LOCALAPPDATA%\YEET\settings.json`, written atomically and preserved across
reinstalls (install.py only replaces the exe and launcher).

- **Clip storage** folder, with a Browse picker
- **Tools** — resolved yt-dlp/ffmpeg paths, the detected Resolve library and
  Python version, and an **Update yt-dlp** button (`-U` on the standalone binary,
  or a pip upgrade when running from source)

## Where clips land

```
%TEMP%\yeet_downloads\
  dQw4w9WgXcQ - Rick Astley - Never Gonna Give You Up (4K Remaster) - Rick Astley\
      dQw4w9WgXcQ-clip-001.mp4
      dQw4w9WgXcQ-clip-002.mp4
```

Folder is `<VIDEO ID> - <title> - <channel>`; files are numbered from what's
already on disk, so **nothing is ever overwritten**.

Names are sanitised for every OS: letters, digits, marks and a small punctuation
whitelist survive — accented and CJK titles stay readable while emoji, symbols,
control characters and `<>:"/\|?*` are dropped. Reserved Windows names (`CON`,
`NUL`, …) get prefixed, trailing dots/spaces stripped, lengths capped.

Downloads use `--download-sections "*IN-END" --force-keyframes-at-cuts`, so trims
are frame-accurate rather than snapping to the nearest keyframe.

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
| `resolve/YEET.lua.in` | Scripts-menu launcher template |
| `resolve/launch_yeet.bat` | clears `PYTHONHOME` before starting the exe |
| `build.py` / `install.py` | freeze / install |

## Known limitations

- **Drop-frame timecode** — playhead placement uses non-drop-frame math, so
  29.97/59.94 timelines may be off by a frame or two.
- **No transcode on ingest** — YouTube delivers VP9/AV1, which can scrub poorly at
  4K in Resolve. A DNxHR pass would fix that.
- **yt-dlp breakage** — YouTube changes extraction periodically; use
  **Update yt-dlp** in Settings.
- **No app icon** — `build.py` picks up `assets\yeet.ico` if you add one.

## Legal

Downloading YouTube video violates YouTube's Terms of Service. This is a private
reference/editing convenience tool; think carefully before using pulled footage in
published work, and credit sources.

ffmpeg is **downloaded, not redistributed** (from yt-dlp's FFmpeg-Builds), which
keeps its GPL obligations out of this package. yt-dlp is public domain (Unlicense).
