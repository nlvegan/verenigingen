# verenigingen/utils/termination_operations.py — DEPRECATED: moved to services/termination/
import warnings

warnings.warn(
    "Import from verenigingen.services.termination.termination_operations instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.termination.termination_operations import *  # noqa: E402,F401,F403
