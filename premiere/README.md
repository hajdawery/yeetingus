# YEETingus in Premiere Pro

Premiere has no Python API, so the Premiere side of YEETingus is a small UXP
panel (`panel/`) that runs inside Premiere and does one thing: when the
YEETingus window asks, it imports a clip and places it on the active sequence
at the playhead (or at the start). The YEETingus window stays the UI; the
panel only shows whether it is connected.

## Setup (Windows, Premiere 26.3+)

1. In YEETingus: Settings → Editor → **Premiere Pro** → **Install the Premiere
   panel**. YEETingus zips `panel/` into a `.ccx` and hands it to Adobe's own
   `UnifiedPluginInstallerAgent` (part of Creative Cloud desktop 5.5+). No
   developer mode, no UXP Developer Tool, and it survives Premiere restarts.
   Nothing is installed unless that button is pressed; Adobe's own words are
   shown in the log if its installer refuses.
2. In Premiere: **Window → UXP Plugins → YEETingus**, dock the panel
   anywhere, and save your workspace (Window → Workspaces → Save Changes to
   this Workspace). Premiere then restores it on every launch — verified on
   26.3 — so this is a one-time step. The panel finds a running YEETingus by
   itself within a couple of seconds; either app can be started first.
3. Open a sequence, put the playhead where the clip should go, press YEET.

Re-running Install is also the upgrade and the repair path.

The panel cannot start YEETingus. That was tried on Premiere 26.3: UXP's
`shell.openExternal` refuses custom URL schemes and `shell.openPath` refuses
executables, by design. Start YEETingus yourself; the panel finds it.

### By hand, with UXP Developer Tool (development)

Enable developer mode in Premiere Preferences → Plugins, install UXP Developer
Tool from Creative Cloud, add `panel/manifest.json` and press Load. A panel
loaded this way must be loaded again every Premiere session.

## How it talks

The panel is the client. It long-polls the YEETingus service over plain HTTP
(`GET /api/premiere/poll` holds for up to 25 s), runs the command it receives
against Premiere's UXP API (`host.js`), and posts the reply. Only two commands
exist — `status` and `insert` — and the panel never evaluates anything else.

The service binds the first free port of `47591–47595`; the panel dials them
in turn (the list is in both `backend/service.py` and `panel/main.js`, and
must agree). Loopback only. The panel routes accept requests from native
origins (no `Origin` header, or `file://`) without the per-launch token,
because the panel can't know it; a browser page always sends an `http(s)`
origin and is refused.

## Placement

The whole file is imported once (an existing project item with the same media
path is reused, never duplicated), scaled to the sequence frame size, and
overwritten onto the lowest unlocked video and audio tracks that are free for
its duration — a new track if none is. Nothing ripples. Audio reserves the
free suffix of tracks because Premiere may spread a source's channels across
several. These rules come from Sherlock's panel (same author).
