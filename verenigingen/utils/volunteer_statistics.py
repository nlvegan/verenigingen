# verenigingen/utils/volunteer_statistics.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.volunteer_statistics instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.volunteer_statistics import *  # noqa: E402,F401,F403
