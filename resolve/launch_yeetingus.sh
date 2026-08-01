#!/bin/sh
# launch_yeetingus.sh — start YEETingus with a clean environment. macOS/Linux
# counterpart to launch_yeetingus.bat.
#
# Why this shim exists, same as on Windows: Resolve exports PYTHONHOME and
# friends for its own scripting host, and a PyInstaller build that inherits
# PYTHONHOME crashes on startup — which presents as "clicking the menu item does
# nothing". Clearing them first is the entire job.
#
# On macOS the app bundle is launched with `open`, which hands off to launchd
# rather than forking from this shell. That means the bundle gets launchd's
# clean environment and cannot inherit Resolve's variables at all — so the unset
# below is belt-and-braces there, and load-bearing only on the direct-exec paths
# (--dev installs, and Linux).

unset PYTHONHOME
unset PYTHONPATH
unset PYTHONSTARTUP
unset PYTHONEXECUTABLE
unset PYTHONNOUSERSITE
unset PYTHONDONTWRITEBYTECODE

# A GUI process launched from Resolve inherits a minimal PATH that omits both
# Homebrew prefixes, so an ffmpeg installed with `brew install ffmpeg` would look
# missing. Put them back before anything tries to find it.
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH

DIR=$(cd "$(dirname "$0")" && pwd)

APP="$DIR/YEETingus.app"
if [ -d "$APP" ]; then
  # -n: a new instance rather than re-activating an existing one, matching the
  # Windows behaviour of starting a fresh process per menu click.
  exec /usr/bin/open -n "$APP" --args "$@"
fi

# No bundle — a --dev install, where install.py rewrites this file with the
# interpreter and source path baked in. Reaching this line means neither
# happened.
echo "YEETingus: no app bundle at $APP, and this is not a --dev shim." >&2
echo "Reinstall with:  python3 build.py   then   python3 install.py" >&2
exit 1
