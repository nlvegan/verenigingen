# verenigingen/utils/chapter_security.py — DEPRECATED: moved to services/chapter/
import warnings

warnings.warn(
    "Import from verenigingen.services.chapter.chapter_security instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.chapter.chapter_security import *  # noqa: E402,F401,F403
