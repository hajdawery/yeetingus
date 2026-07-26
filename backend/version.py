"""Single source of truth for YEET's version and authorship.

Consumed by the app (header, Settings, boot log) and by install.py, which bakes
the version into the Lua launcher so Resolve's Console can report it.
"""

__version__ = "1.0.0"

AUTHOR = "haej (aka GRApedia)"
COPYRIGHT = f"© 2026 {AUTHOR}"
