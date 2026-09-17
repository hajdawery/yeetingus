# YEETingus 2.0 — what changed for the user

A running list of every user-facing change in the 2.0 rewrite, written while it
was built. The 1.x app was a single Tkinter window; 2.0 is a new front end on a
new architecture, with the download / conversion / Resolve logic carried over
unchanged.

## First run

- A welcome window asks which editor you use. **DaVinci Resolve** explains
  the Studio requirement and the External-scripting switch, with a live
  connection check; **Premiere Pro** has the Install-the-panel button and the
  three-step setup (open, dock, save workspace) with a live panel status.
  Skippable; everything in it is reachable from Settings later.

## The redesign

- **New app, same job.** YEETingus is now a Tauri window (a native window with
  a web view inside — no bundled browser, ~10 MB) driving a Python service that
  does all the real work. The look follows AutoSubs: a near-black ground, one
  column of controls on the left, a wide content panel on the right, and the
  main action pinned to the bottom of the left column.
- **Two columns that follow the window.** The left column takes about 40 % of
  the width (never narrower than 360 px, never wider than 520 px); the right
  panel takes the rest. Below 720 px wide the two stack vertically. Window
  floor is 720 × 520; it opens at 1000 × 720.
- **Light and dark theme.** Moon / sun button in the top bar; the choice is
  remembered.
- **Accent colour** is a muted olive green (`#87a15e`) — used for the YEET
  button, focus rings, the insert icon, clip lengths and highlighted log lines.
- **Top bar**: the app logo with the Resolve connection next to it (green dot
  + project · timeline, or red dot + what's wrong — click to re-check), and
  three icon buttons: log, settings, theme.
- **No step numbers**, no marketing hints ("YouTube and more" is gone).
- **Everything scales**: the layout is fluid, dropdowns are drawn in-page (the
  OS popup came out white-on-white), popovers never hang off the edge, and
  the clip list re-flows when the panel gets narrow (see History).

## Source

- **Link field** with a link icon and a "Paste a video link…" placeholder.
- **In / End point** fields with clock icons. Same formats as before:
  `mm:ss`, `hh:mm:ss`, or plain seconds; both at `00:00` = the entire video.
- **Automatic `?t=` detection** — a link with a timestamp (`?t=90`, `&t=2m5s`,
  `#t=…`, `start=`) sets the in point and moves the end point to keep the range
  valid. Now driven by the field's value rather than the change event, so it
  fires however the link got there: typed, pasted, dropped.
- **The fields flash** (a soft accent glow) whenever the app fills one in by
  itself — the in point on detection, the end point when a length is applied.
- **Length presets**: `15s`, `30s`, `60s`, `Whole` (both points to 00:00), and
  an arrow that unfolds a **slider from 0:01 to 5:00** inline under the row;
  the end point follows the slider live and the change is logged on release.
- **From link** — a labelled button (copy icon) that pulls the `?t=` timestamp
  out of the link into the in point on demand.
- **Default clip length** (Settings) still decides where the end point lands
  when you commit an in point.

## Quality and insert

- **Quality** dropdown: Best available, 2160p, 1440p, 1080p, 720p, 480p.
- **Insert at**: a segmented pill — *Playhead* or *Start* of the timeline.
- Both are single rows (label left, control right) in one card.

## Actions

- **YEET into timeline** — the primary button, bottom of the left column.
  Hover lifts and glows, click presses, and it pops once when a job starts.
  While a job runs it becomes a red **Stop** that breathes.
- **Download only** — same pipeline, no Resolve insert.
- **Progress** line and bar directly above the buttons; the bar shimmers while
  it moves. The step text mirrors the Tk app's ("Reading video info…",
  "Downloading… 42%", "Preparing… 80%", "Pasting into timeline…", "Done — …").
- Both buttons are disabled until the tools are ready, and while a link is
  known to be age-restricted (see below).

## Preview (right panel, top)

- As soon as a link is pasted the app looks it up (quietly — nothing in the
  log) and shows a **preview card**: thumbnail with the duration in the
  corner, title, channel, and the resolutions on offer.
- A green **✓ Ready** badge (and green border) once the lookup succeeded;
  "Checking…" while it runs; × clears the link.
- **Age-restricted videos are detected up front.** yt-dlp can't read them
  without a signed-in session; the preview shows a red warning, YEET and
  Download only are disabled, and a job on such a link stops before
  downloading with an explanation in the log instead of a 403 later.

## History (right panel, "Clips")

Every finished clip in the clips folder, newest first — including clips made
by 1.x. The header shows the count, an open-folder button and a refresh.

Each row shows the **thumbnail**, **title**, **channel**, what it is and how
long it is (in accent colour: `Clip 1 · 30s`, `from 09:19 · 30s`,
`Entire video · 8:23`), the **file size** and **when** it was made. Lengths
under two minutes read as `Ns`, longer ones as `m:ss`. Clips that predate 2.0
get their length probed once in the background and remembered.

Row actions:

- **⤓ Insert** — paste this clip into the timeline at the chosen insert point,
  without downloading anything. Disabled while Resolve isn't connected or a
  job is running.
- **▶ Play** — open the clip in your default video player.
- **↗ Source** — open the video's page in your browser (the exact link you
  pasted, timestamp included; rebuilt from the YouTube id for older clips;
  greyed out when unknown).
- **📁 Folder** — open the clip's folder in the file manager.
- **🗑 Delete** — two-step, inline: the row turns red with **Delete / Keep**,
  no dialog. Removes the file and its info; drops the folder once it's empty.
  Refused while a job is running.

- **Click the title to copy it; click the channel to copy it.** A green
  "copied" tag confirms.
- **Narrow panel**: the title wraps to two lines, and the action buttons move
  to a second row, left-aligned under the text, larger and further apart.
- The list refreshes itself when a job finishes or a clip is deleted.

## Log

- The log takes over the right panel (list icon in the top bar, or
  automatically when something goes wrong). Monospace, colour-coded like the
  Tk app: errors red, "ready/done/inserted" in accent, the credit-the-source
  reminder highlighted. **clear** and × in its header.
- Things the window does by itself (timestamp detected, end point moved,
  length applied) are logged too, in the same log.

## Premiere Pro

- **Editor switch** in Settings: DaVinci Resolve or Premiere Pro. YEET,
  Download-only and the history's insert button all go to the chosen one; the
  top-left pill shows that editor's project · sequence (or what's missing).
- **One-click panel install**: YEETingus builds the panel package and hands
  it to Adobe's own plugin installer — no developer mode, no UXP Developer
  Tool. Then Window → UXP Plugins → YEETingus, dock it, save the workspace —
  Premiere brings it back every launch, so the whole setup is one-time.
  (The panel can't start YEETingus itself; UXP forbids panels launching
  programs. Start the app, the panel connects on its own.)
- The panel has no controls; it shows "Connected to YEETingus" and does the
  import + placement (playhead or start, lowest free tracks, scaled to the
  sequence) when asked. See `premiere/README.md`.
- **Premiere can't decode AV1**, so with Premiere chosen the preparation pass
  makes the same 0.5 s-keyframe intermediate in **HEVC** (hardware, `hvc1`)
  instead. Resolve keeps AV1. Inserting an older AV1 clip from the history
  into Premiere converts an `.hevc.mp4` copy beside it first (hidden from the
  list, deleted with the clip). Verified on Premiere 26.3: video + audio land
  on V1/A1 at the playhead.

## Settings

Same settings as 1.x in a dialog, plus the editor choice: clips folder (with
Browse…), default clip length (15 / 30 / 60 / 90 s), the tools line-up (yt-dlp, ffmpeg, video
encoder, JS runtime, Resolve library + Python check), **Update yt-dlp**, and
the install buttons for Deno and (on macOS) ffmpeg when they're missing.
Credit reads **© 2026 haej**, linked to GitHub.

## Under the hood, visible in behaviour

- One background service does the work; the window only talks to it. Closing
  the window stops the service. The service is bound to localhost and needs a
  per-launch token, so nothing else on the machine can drive it.
- Every clip made by 2.0 gets a small `<name>.json` next to it with its title,
  channel, source link, section, quality and length — that's what the history
  reads, and it survives moving the folder.
- The Tk app (`yeet_app.py`) still runs and drives the same service code
  in-process; nothing about the download or conversion pipeline changed in
  this rewrite.
