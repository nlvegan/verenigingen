# verenigingen/utils/optimized_chapter_lookup.py — DEPRECATED: moved to services/chapter/
import warnings

warnings.warn(
    "Import from verenigingen.services.chapter.optimized_chapter_lookup instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.chapter.optimized_chapter_lookup import *  # noqa: E402,F401,F403
