"""Single source of truth for YEETingus' version and authorship.

Consumed by the app (header, Settings, boot log) and by install.py, which bakes
the version into the Lua launcher so Resolve's Console can report it.
"""

__version__ = "2.0.0"

# Display name shown in the window title, header and Settings. The executable,
# install folder and Resolve menu entry all derive from this name;
# install.py migrates a previous "YEET" install across and removes its leftovers.
APP_NAME = "YEETingus"

AUTHOR = "haej"
# The clickable credit in Settings points here; unchanged by the name above.
AUTHOR_URL = "https://github.com/hajdawery"
COPYRIGHT = f"© 2026 {AUTHOR}"
