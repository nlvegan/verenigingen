# verenigingen/utils/termination_utils.py — DEPRECATED: moved to services/termination/
import warnings

warnings.warn(
    "Import from verenigingen.services.termination.termination_utils instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.termination.termination_utils import *  # noqa: E402,F401,F403
