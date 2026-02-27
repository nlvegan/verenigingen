# verenigingen/utils/chapter_reference_manager.py — DEPRECATED: moved to services/chapter/
import warnings

warnings.warn(
    "Import from verenigingen.services.chapter.chapter_reference_manager instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.chapter.chapter_reference_manager import *  # noqa: E402,F401,F403
