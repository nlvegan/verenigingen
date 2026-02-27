# verenigingen/utils/chapter_board_permissions.py — DEPRECATED: moved to services/chapter/
import warnings

warnings.warn(
    "Import from verenigingen.services.chapter.chapter_board_permissions instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.chapter.chapter_board_permissions import *  # noqa: E402,F401,F403
