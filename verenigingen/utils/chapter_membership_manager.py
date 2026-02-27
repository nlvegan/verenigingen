# verenigingen/utils/chapter_membership_manager.py — DEPRECATED: moved to services/chapter/
import warnings

warnings.warn(
    "Import from verenigingen.services.chapter.chapter_membership_manager instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.chapter.chapter_membership_manager import *  # noqa: E402,F401,F403
