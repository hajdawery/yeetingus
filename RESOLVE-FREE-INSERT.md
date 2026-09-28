# Insert on Resolve Free, without external scripting

Research note, 2026-09-28. Written for YEETingus; the same channel applies
to Taperat.

**Status, 2026-09-28: built.** `resolve/YEETingusBridge.lua` (the loop and the
handlers), `backend/resolve_mailbox.py` (the Python side), a fallback in
`resolve_bridge.py`, and the launcher now starts the bridge on Free. The
tests run the real launcher and bridge under Resolve's `fuscript` against a
mock Resolve in a copy of the 21.1 sandbox (`tests/test_resolve_mailbox.py`).
**Confirmed on a real install, 2026-09-28:** Resolve Free 21.1 on Windows, on a
second PC. After Workspace > Scripts > YEETingus, a YEET landed on the
timeline correctly. The menu entry did not open the app; it had to be started
by hand, as expected. In use since then it has worked fine, with no crash.
Results per probe are in the table below. Shipped in 2.2.0.

## Answer

Yes, it is possible on Resolve Free 21.1. A Lua script started from
`Workspace > Scripts` stays running inside Resolve. The app talks to it
through a file mailbox. The script calls the normal Resolve API and places
the clip.

Two public projects do this today:

- **AutoSubs** (tmoroney/auto-subs, MIT, 4.3k stars, Tauri + Rust like
  YEETingus). v3.10.1, 2026-09-19. Places subtitle clips on Free 21.1,
  Windows and macOS.
- **davinci-resolve-lua-mcp** (saadk408, MIT). An MCP server for Free 21.1.
  Measured on macOS only. Has a sandbox diagnostic script we can reuse.

The cost for the user: start YEETingus by hand, then one click on
`Workspace > Scripts > YEETingus` per Resolve session. Nothing can start
either automatically (see trap 1 and "No app launch").

The project that started this search (hiteshK03/davinci-resolve-mcp) runs a
Python HTTP server from the Scripts menu. That is dead on Free 21.1 (its
issue #2) and it has no auth (its issue #3). Do not copy it.

## What Blackmagic changed

| Resolve | Free: external scripting | Free: Python in Scripts menu | Free: Lua in Scripts menu |
|---|---|---|---|
| up to 19.0 | yes | yes | yes |
| 19.1 (Nov 2024) to 21.0.4 | no | yes | yes, full |
| 21.1 (2026-09-08) | no | no, `.py` files are ignored | yes, sandboxed |

Blackmagic's reason: "The Python API was being used to hack studio features
into the free version." Studio keeps everything.

## The Free 21.1 Lua sandbox

**Gone (nil):** `io`, `os.execute`, `os.remove`, `os.rename`, `require`,
`package`, `ffi`, `debug`, `bmd.readdir`, `bmd.readfile`, `bmd.writefile`,
UIManager. `print` is muted.

**Still there:** `loadfile`, `loadstring`, `setfenv`, `os.getenv`,
`os.time`, `os.clock`, `jit.os`, `bmd.fileexists`, `bmd.direxists`,
`bmd.wait`, `bmd.gettime`, `bmd.createuuid`, `bmd.getpid`,
`fusion:GetPrefs`, `fusion:SetPrefs`, `fusion:SavePrefs`, `fusion:MapPath`,
and the full `resolve` object.

**No app launch.** Free 21.1 cannot start an external program from a
script, `bmd.openfileexternal` included. AutoSubs' release notes say so: the
user starts the app by hand.

Sources: AutoSubs `bootstrap.lua` and `resolve_bridge.rs`; saadk408
`docs/windows.md` fact W7 (macOS, build 21.1.0.17). Blackmagic documents
none of it. A point release can change it.

## The channel: a file mailbox

```
YEETingus backend                        Lua loop inside Resolve
-----------------                        -----------------------
write request.lua.tmp, rename  ------->  bmd.fileexists every 50 ms
                                         loadfile(request.lua) in an empty env
                                         SetPrefs Ack = id
                                         run the handler (Resolve API)
poll Fusion.prefs for             <----- SetPrefs Response = id:base64(json)
"Response = "<id>:..."                   SavePrefs()  -> Resolve writes the file
```

- **Request:** a Lua chunk, `return { id = "...", ... }`. Python writes it.
  A Lua table literal needs no JSON decoder on the Lua side. Put strings in
  long brackets (`[=[ ... ]=]`) and raise the level until the closing
  bracket is not in the text (AutoSubs `encode_request`).
- **Response:** `fusion:SetPrefs("Global.YEETingus.Response", id .. ":" ..
  base64(json))`, then `fusion:SavePrefs()`. Resolve writes `Fusion.prefs`
  to disk. The backend reads the file and matches the id.
- **Ack:** the loop sets `Global.YEETingus.Ack = id` when it takes a
  request. No ack in 2 s means the bridge is not running. An ack for another
  recent id means it is busy, not dead (AutoSubs `request_in_flight`).
- **Latency:** about 60 ms a round trip (saadk408, Mac).
- **Fusion.prefs:** Windows
  `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Profiles\<profile>\Fusion.prefs`,
  macOS `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Profiles/<profile>/Fusion.prefs`.
  Take the newest one across profiles.
- **Mailbox:** `%LOCALAPPDATA%\YEETingus\resolve-mailbox` (user-private).
  Bake the path into the launcher at install. Do not rely on `os.getenv`.

## Traps other people paid for

1. **Start the loop from the Scripts menu only.** AutoSubs 3.10.0 started it
   at Resolve launch from a `.scriptlib` with `fusion:Execute`. That loop held
   Fusion's shared script executor for the whole session. Macro controls
   stopped working, text fields lost focus, a colour drag crashed Resolve.
   `bmd.wait` does not free the executor. Fixed in 3.10.1 by removing the
   scriptlib. The Scripts-menu state does not have this problem.
2. **The idle loop writes no prefs.** Each `SetPrefs` fires
   `FusionApp::PrefsChanged` through Resolve's UI queue. A write once a
   second broke Inspector drags. One during Resolve shutdown crashed it.
   Write only when answering. Read a few keys at most every 0.5 s.
3. **Keep the response ASCII.** Windows writes `Fusion.prefs` in the ANSI
   code page. Read the file as bytes. Base64 or hex the JSON. AutoSubs also
   escapes each byte >= 0x80 inside JSON strings as `\uE0xx`, then decodes
   each string as UTF-8, else ANSI.
4. **Windows paths are narrow.** `loadfile` uses ANSI `fopen`. Bake the
   mailbox path in the ANSI code page, or use its 8.3 short path, or keep it
   ASCII. Forward slashes work.
5. **Non-ASCII file names are a risk.** YEETingus names files from post
   text, so Polish letters are likely. A UTF-8 path passed to the Lua API on
   Windows may not import. Probe it (P4). Fallback: the 8.3 short path.
6. **Sharing violations on Windows.** Lua holds `request.lua` open for a
   moment. Retry delete and replace for about 1 s. Antivirus can hold it too.
7. **Dead handles.** `AppendToTimeline` onto a busy region returns truthy
   items whose methods return nil. Probe `item:GetStart()`. YEETingus already
   checks placement; keep that check in Lua.
8. **Whole frames only.** Resolve 21 `AppendToTimeline` rejects a
   non-integer frame and returns nil for the whole batch. Use
   `math.floor(x + 0.5)`.
9. **Locked tracks** return an empty table. `_free_track` already skips
   them.
10. **One loop only.** A second click must take over the first. AutoSubs
    uses `Stop`, `Probe`, `Owner` prefs keys, set in memory, never saved
    (`bootstrap.lua`).
11. **Stale requests.** The backend deletes a leftover `request.lua` at
    start. The loop refuses a request older than 120 s.
12. **One request at a time.** A modal dialog in Resolve blocks the loop.
    The backend needs a timeout and a message that names the cause.
13. **No eval.** saadk408 runs any Lua a request carries (`run_lua`). Anyone
    who can write the mailbox folder then controls Resolve. Use a fixed
    handler table.

## The current launcher breaks on Free 21.1

`resolve/YEETingus.lua.in` line 46 reads `package.config`. `package` is nil,
so the script throws there and does nothing. After that it uses `io.open`,
`require("ffi")`, `os.execute` and `print`. All are gone. `log()` passes
`io.open` into `pcall`, but `io.open` is evaluated before `pcall` runs, so
it throws too. Only `bmd.openfileexternal` might still launch the app.

So on Free 21.1 the menu entry cannot launch YEETingus. Detect the platform
with `jit.os`, not `package.config`. The Studio behaviour is unchanged.

**Fixed.** The launcher guards every one of those, takes the platform from
`jit.os`, and skips launching when it finds itself sandboxed.

## Design for YEETingus

1. **`resolve/YEETingus.lua.in`** stays the one menu entry. On Free (the
   product name has no "Studio") it starts the bridge loop, takeover first.
   Sandboxed, it doesn't try to open the app. No unguarded `io`, `ffi`,
   `require` or `package`. `BRIDGE_DIR` is baked by the app (Settings) or
   `install.py`.
2. **`resolve/YEETingusBridge.lua`**, which the app writes to
   `<app data>/resolve-bridge/bridge.lua` on start. The launcher loads it with
   `loadfile`, so updates need no reinstall of the menu entry. Handlers:
   - `Ping`: product, version, page.
   - `GetTimelineInfo`: port of `get_timeline_info`.
   - `ImportAndInsert`: port of `import_and_insert`, `_free_track`,
     `_pool_bin` and the retime step.
   - `Stop`.
3. **`backend/resolve_mailbox.py`**: writes the request, polls
   `Fusion.prefs`. `resolve_bridge.get_timeline_info` and `import_and_insert`
   try external scripting first (zero clicks on Studio), then the mailbox,
   but only if the bridge's `Owner` key is in `Fusion.prefs`. Without it,
   they fail at once, with a message that says how to fix Studio and Free.
4. **UI**: no new screen. The connection error names the Scripts click, and
   a menu entry from before the bridge shows as stale in Settings. README
   covers setup and limits.

### Python call to Lua call

| `resolve_bridge.py` | Lua |
|---|---|
| `connect()` | the `resolve` global |
| `GetProjectManager().GetCurrentProject()` | `resolve:GetProjectManager():GetCurrentProject()` |
| `tl.GetSetting("timelineFrameRate")` | `tl:GetSetting("timelineFrameRate")` |
| `tl.GetCurrentTimecode()`, `GetStartFrame()` | same, with `:` |
| `storage.AddItemListToMediaPool([path])` | `resolve:GetMediaStorage():AddItemListToMediaPool({ path })`, or `pool:ImportMedia({ path })` |
| `pool.SetCurrentFolder`, `AddSubFolder` | same, with `:` |
| `pool.AppendToTimeline([clip_info])` | `pool:AppendToTimeline({ { mediaPoolItem = item, startFrame = s, endFrame = e, recordFrame = r, trackIndex = t } })` |
| `tl.GetItemListInTrack`, `GetIsTrackLocked`, `AddTrack` | same, with `:` |
| `x.SetProperty("RetimeProcess", mode)` | `x:SetProperty("RetimeProcess", mode)` |

API lists are 1-based tables: use `#list`, not `pairs`.

Taperat found that the item `AddItemListToMediaPool` returns can append
nothing, while the same item fetched again from the pool by path works. YEETingus
uses the returned item directly and ships that way on Studio. Check it again
in Lua.

## Probe before building

Needs a Free 21.1 install on Windows. Free and Studio most likely share one
install folder, so use a second machine or a VM.

| # | Check | Pass | 2026-09-28, Free 21.1, Windows |
|---|---|---|---|
| P1 | A `.lua` in `%APPDATA%\...\Fusion\Scripts\Utility` shows in `Workspace > Scripts` | listed | **passed** |
| P2 | Sandbox census, including `bmd.openfileexternal`. saadk408's `scripts/claude_diag.lua` (MIT) does this and writes the result into `Fusion.prefs` | the table above holds | partly: enough of it holds for the bridge; the menu entry did not open the app |
| P3 | `loadfile` on the mailbox path, forward and back slashes | both load | **passed** with forward slashes, which is what we bake |
| P4 | Import a file with an ASCII name, then one with Polish letters | both import | no problem with Polish names in the user's work so far |
| P5 | `AppendToTimeline` at the playhead, on V1 and on a new track pair | clip at the right frame | **passed** at the playhead; the new-track case is open |
| P6 | `SetProperty("RetimeProcess", 2)` on a 60 fps clip in a 24 fps timeline | returns true | open |
| P7 | Round trip time; `Fusion.prefs` line endings and encoding | under 200 ms | open |
| P8 | With the loop running: Fusion macro controls, Inspector drags, a colour drag for 30 s, quit Resolve | no glitch, no crash | partly: no crash in use so far; the full sequence not run step by step |

## Fallback that needs no script at all

Drag and drop. Resolve Free accepts a file dropped from Explorer or Finder
onto the timeline or the media pool, on every version. A native drag out of
the YEETingus window (a Tauri drag plugin) gives Free users a one-gesture
insert without the bridge. No playhead or track logic, but no Resolve
dependency either.

## Sources

- hiteshK03/davinci-resolve-mcp, issues #2 and #3.
- saadk408/davinci-resolve-lua-mcp: `bridge/resolve_mcp_bridge.lua`, `README.md`, `docs/windows.md`.
- tmoroney/auto-subs: `Resolve-Integration/README.md`,
  `Resolve-Integration/docs/resident-bridge-fusion-regression.md`,
  `AutoSubs-App/src-tauri/src/resolve_bridge.rs`,
  `AutoSubs-App/src-tauri/resources/modules/bootstrap.lua`,
  `autosubs_core.lua` (the `AppendToTimeline` traps near lines 1457-1800).
- Puget Systems, 2026-09-10: "How DaVinci Resolve Free v21.1 Scripting Changes Affect Puget Bench".
- xere.my, 2026-09-14: "DaVinci Resolve 21.1 Silently Removed Python from the Free Edition".
