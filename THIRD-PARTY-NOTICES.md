# Third-party notices

YEETingus itself is MIT licensed (see [LICENSE](LICENSE)). This file records the
third-party components involved, because the *source repository* and the *built
executable* are not the same thing:

- **This repository contains no third-party code.** Every tracked file is
  original work.
- **`YEETingus.exe` embeds an interpreter and its libraries**, because it is
  produced by PyInstaller. Anyone redistributing that binary is redistributing
  those components too, and should ship this file with it.
- **yt-dlp and ffmpeg are downloaded at runtime, never bundled or
  redistributed.** They are fetched from their own official release pages on
  first run and stored in the user's own application-data folder.

---

## Embedded in the built executable

| Component | Version built against | Licence |
|---|---|---|
| CPython | 3.13 | Python Software Foundation License |
| Tcl/Tk (the `tkinter` GUI) | 8.6 | BSD-style (Tcl/Tk licence) |
| OpenSSL (via Python's `ssl`) | 3.x | Apache License 2.0 |
| Microsoft Visual C++ runtime | — | Microsoft redistributable terms |
| PyInstaller bootloader | 6.x | GPL 2.0 **with an exception** permitting distribution of frozen applications under any licence |

Versions reflect the interpreter used to build; they move with whatever Python
the build machine has. Rebuild and re-check before publishing a binary if that
matters to you.

> The PyInstaller bootloader exception is the reason a GPL component does not
> impose GPL terms on this application. Its licence text is included with
> PyInstaller.

## Downloaded at runtime, not redistributed

| Tool | Source | Licence |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | official GitHub releases | The Unlicense (public domain) |
| [ffmpeg / ffprobe](https://ffmpeg.org/) | [yt-dlp's FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds) | GPL (as built) |

Fetching rather than bundling is deliberate: ffmpeg's GPL terms attach to
*distribution*, and this project does not distribute it. The user obtains it
directly from its publisher, and can substitute their own build via the
`YEET_FFMPEG` / `YEET_YTDLP` environment variables.

## Not included, merely interoperated with

DaVinci Resolve is not bundled, modified, or redistributed. YEETingus uses
Blackmagic Design's **documented, officially supported** external scripting API,
in the manner that API exists to allow.

## Trademarks

DaVinci Resolve, DaVinci Resolve Studio and Blackmagic Design are trademarks of
Blackmagic Design Pty. Ltd. YouTube is a trademark of Google LLC. Twitch is a
trademark of Twitch Interactive, Inc. Windows is a trademark of Microsoft
Corporation.

This project is **independent and unofficial**. It is not affiliated with,
endorsed by, sponsored by, or approved by any of them. Those names are used only
to describe what the software interoperates with.

## Network activity

The application makes outbound connections in exactly two situations, both
user-initiated:

1. **First run (or Update yt-dlp):** downloads yt-dlp and ffmpeg from the GitHub
   release URLs listed above.
2. **When you press YEET or Download only:** yt-dlp contacts the site whose link
   you supplied.

No telemetry, no analytics, no update check, no account, and nothing is sent
anywhere about you or what you download.
