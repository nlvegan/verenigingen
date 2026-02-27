# verenigingen/utils/termination_integration.py — DEPRECATED: moved to services/termination/
import warnings

warnings.warn(
    "Import from verenigingen.services.termination.termination_integration instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.termination.termination_integration import *  # noqa: E402,F401,F403
