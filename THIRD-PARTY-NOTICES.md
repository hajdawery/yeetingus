# Third-party notices

YEETingus itself is MIT licensed (see [LICENSE](LICENSE)). This file records the
third-party components involved, because the *source repository* and the *built
executable* are not the same thing:

- **This repository contains no third-party code.** Every tracked file is
  original work.
- **The built app embeds an interpreter and its libraries** (`YEETingus.exe` on
  Windows, `YEETingus.app` on macOS), because it is produced by PyInstaller.
  Anyone redistributing that binary is redistributing those components too, and
  should ship this file with it.
- **yt-dlp and ffmpeg are never bundled or redistributed.** yt-dlp is fetched
  from its own official release page on first run and stored in the user's own
  application-data folder. ffmpeg is fetched the same way on Windows, and on
  macOS is installed by the user via Homebrew — see below.

---

## Embedded in the built executable

| Component | Version built against | Licence |
|---|---|---|
| CPython | 3.13 | Python Software Foundation License |
| Tcl/Tk (the `tkinter` GUI) | 8.6 | BSD-style (Tcl/Tk licence) |
| OpenSSL (via Python's `ssl`) | 3.x | Apache License 2.0 |
| Microsoft Visual C++ runtime *(Windows build only)* | — | Microsoft redistributable terms |
| PyInstaller bootloader | 6.x | GPL 2.0 **with an exception** permitting distribution of frozen applications under any licence |

Versions reflect the interpreter used to build; they move with whatever Python
the build machine has. Rebuild and re-check before publishing a binary if that
matters to you.

> The PyInstaller bootloader exception is the reason a GPL component does not
> impose GPL terms on this application. Its licence text is included with
> PyInstaller.

## Obtained at runtime, not redistributed

| Tool | Platform | Source | Licence |
|---|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | all | official GitHub releases (`yt-dlp.exe` / `yt-dlp_macos`) | The Unlicense (public domain) |
| [ffmpeg / ffprobe](https://ffmpeg.org/) | Windows | [yt-dlp's FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds), downloaded on first run | GPL (as built) |
| [ffmpeg / ffprobe](https://ffmpeg.org/) | macOS | **installed by the user** — `brew install ffmpeg` | GPL-3.0-or-later (as Homebrew builds it) |

Not bundling is deliberate: ffmpeg's GPL terms attach to *distribution*, and this
project distributes no part of it. The user obtains it directly from its
publisher, and can substitute their own build via the `YEET_FFMPEG` /
`YEET_FFPROBE` / `YEET_YTDLP` environment variables.

**On macOS the app does not download ffmpeg at all.** No Apple Silicon build
exists whose provenance can be vouched for — ffmpeg.org's only listed macOS
source declines to build for ARM, and the binaries that do circulate trace back
to a single site that labels them "for educational purposes only". Rather than
fetch one anyway, YEETingus asks the user to install it. This keeps both the
supply chain and the licence position clean: Homebrew is the publisher, the user
is the one who invoked it, and nothing about ffmpeg passes through this project.

> No part of ffmpeg — source, binary, or header — is present in this repository
> or in any build it produces, on any platform.

## Not included, merely interoperated with

DaVinci Resolve is not bundled, modified, or redistributed. YEETingus uses
Blackmagic Design's **documented, officially supported** external scripting API,
in the manner that API exists to allow.

## Trademarks

DaVinci Resolve, DaVinci Resolve Studio and Blackmagic Design are trademarks of
Blackmagic Design Pty. Ltd. YouTube is a trademark of Google LLC. Twitch is a
trademark of Twitch Interactive, Inc. Windows is a trademark of Microsoft
Corporation. macOS, Apple Silicon and Gatekeeper are trademarks of Apple Inc.
Homebrew is a trademark of the Homebrew project.

This project is **independent and unofficial**. It is not affiliated with,
endorsed by, sponsored by, or approved by any of them. Those names are used only
to describe what the software interoperates with.

## Network activity

The application makes outbound connections in exactly two situations, both
user-initiated:

1. **First run (or Update yt-dlp):** downloads yt-dlp from the GitHub release
   URL listed above, and on Windows ffmpeg from the same place. On macOS no
   ffmpeg download is made.
2. **When you press YEET or Download only:** yt-dlp contacts the site whose link
   you supplied.

If you press **Install ffmpeg** on macOS, Homebrew makes its own connections on
your behalf — that is Homebrew's network activity, under its own terms, and only
ever from an explicit click.

No telemetry, no analytics, no update check, no account, and nothing is sent
anywhere about you or what you download.
