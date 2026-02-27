# verenigingen/utils/chapter_utils.py — DEPRECATED: moved to services/chapter/
import warnings

warnings.warn(
    "Import from verenigingen.services.chapter.chapter_utils instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.chapter.chapter_utils import *  # noqa: E402,F401,F403
